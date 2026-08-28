"""Backfill canonical PRA embeddings into Neo4j.

The default mode is a real-provider dry run. Pass --write only after reviewing
the dry-run summary. No vector index is created by this script.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any, Iterable

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from openai import AsyncAzureOpenAI, AsyncOpenAI

from app.core.settings import get_settings
from app.infrastructure.knowledge_graph.neo4j.client import Neo4jClient
from app.infrastructure.knowledge_graph.neo4j.searchable_labels import SEARCHABLE_LABELS


EMBEDDING_TEXT_VERSION = "pra-canonical-v1"
TECHNICAL_LABELS = {"Resource"}
READ_QUERY = """
MATCH (n)
WHERE any(label IN labels(n) WHERE label IN $searchable_labels)
  AND coalesce(n.name, n.label) IS NOT NULL
RETURN elementId(n) AS node_id,
       labels(n) AS labels,
       coalesce(n.label, n.name) AS label,
       n.description AS description,
       n.comment AS comment,
       n.embedding IS NOT NULL AS embedding_present,
       n['embedding_model'] AS embedding_model,
       n['embedding_dimension'] AS embedding_dimension
ORDER BY node_id
"""
WRITE_QUERY = """
UNWIND $items AS item
MATCH (n)
WHERE elementId(n) = item.node_id
  AND any(label IN labels(n) WHERE label IN $searchable_labels)
SET n.embedding = item.embedding,
    n.embedding_model = item.embedding_model,
    n.embedding_dimension = item.embedding_dimension,
    n.embedding_generated_at = item.embedding_generated_at,
    n.embedding_text_version = item.embedding_text_version
RETURN count(n) AS updated
"""


def _values(value: Any) -> list[str]:
    """Flatten Neo4j scalar/list values into clean strings."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        result: list[str] = []
        for item in value:
            result.extend(_values(item))
        return result
    text = str(value).strip()
    return [text] if text else []


def canonical_embedding_text(node: dict[str, Any]) -> str:
    """Build the same label/description/comment/type text used by TTL search."""
    labels = sorted(
        label
        for label in _values(node.get("labels"))
        if label not in TECHNICAL_LABELS and not label.startswith("_")
    )
    parts = [
        *_values(node.get("label")),
        *_values(node.get("description")),
        *_values(node.get("comment")),
        " ".join(labels),
    ]
    return " ".join(part for part in parts if part).strip()


def _chunks(items: list[Any], size: int) -> Iterable[list[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _embedding_client() -> tuple[Any, str]:
    settings = get_settings()
    if not settings.embedding_enabled:
        raise RuntimeError("EMBEDDING_ENABLED is false")

    if settings.azure_openai_endpoint and settings.azure_openai_api_key:
        model = settings.azure_openai_embedding_deployment or settings.embedding_model
        return (
            AsyncAzureOpenAI(
                api_key=settings.azure_openai_api_key,
                azure_endpoint=settings.azure_openai_endpoint,
                api_version=settings.azure_openai_api_version,
            ),
            model,
        )

    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    return (
        AsyncOpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url),
        settings.embedding_model,
    )


async def _embed_all(client: Any, model: str, texts: list[str], batch_size: int) -> list[list[float]]:
    vectors: list[list[float]] = []
    for batch in _chunks(texts, batch_size):
        response = await client.embeddings.create(input=batch, model=model)
        ordered = sorted(response.data, key=lambda item: item.index)
        vectors.extend([item.embedding for item in ordered])
    return vectors


async def _load_nodes(client: Neo4jClient) -> list[dict[str, Any]]:
    rows = await client.execute_read_query(
        READ_QUERY,
        searchable_labels=list(SEARCHABLE_LABELS),
    )
    if not rows:
        raise RuntimeError("No searchable Neo4j nodes were found")
    return rows


async def run(args: argparse.Namespace) -> int:
    neo4j = Neo4jClient()
    try:
        nodes = await _load_nodes(neo4j)
        labels = Counter(label for node in nodes for label in _values(node.get("labels")))
        pending = [
            node
            for node in nodes
            if args.force or not node.get("embedding_present")
        ]
        skipped = len(nodes) - len(pending)
        texts = [canonical_embedding_text(node) for node in pending]
        empty_text = [node for node, text in zip(pending, texts) if not text]
        pending = [node for node, text in zip(pending, texts) if text]
        texts = [text for text in texts if text]

        embedding_client, model = _embedding_client()
        print("DRY-RUN SUMMARY" if not args.write else "BACKFILL SUMMARY")
        print(f"Searchable Neo4j nodes: {len(nodes)}")
        print(f"Nodes to embed: {len(pending)}")
        print(f"Already embedded and skipped: {skipped}")
        print(f"Empty canonical text skipped: {len(empty_text)}")
        print(f"Labels: {dict(sorted(labels.items()))}")
        print(f"Embedding model: {model}")
        print(f"Example canonical text: {texts[0][:500] if texts else '(none)'}")

        if not pending:
            print("No nodes require embedding.")
            return 0

        probe_response = await embedding_client.embeddings.create(input=[texts[0]], model=model)
        probe = probe_response.data[0].embedding
        dimension = len(probe)
        print(f"Verified embedding dimension: {dimension}")

        if not args.write:
            print("No Neo4j writes performed. Re-run with --write after reviewing this summary.")
            return 0

        vectors = await _embed_all(embedding_client, model, texts, args.batch_size)
        if len(vectors) != len(pending):
            raise RuntimeError(f"Embedding count mismatch: expected {len(pending)}, got {len(vectors)}")

        generated_at = datetime.now(timezone.utc).isoformat()
        successes = 0
        failures = 0
        for batch_nodes, batch_vectors in zip(
            _chunks(pending, args.write_batch_size),
            _chunks(vectors, args.write_batch_size),
        ):
            items = [
                {
                    "node_id": node["node_id"],
                    "embedding": vector,
                    "embedding_model": model,
                    "embedding_dimension": dimension,
                    "embedding_generated_at": generated_at,
                    "embedding_text_version": EMBEDDING_TEXT_VERSION,
                }
                for node, vector in zip(batch_nodes, batch_vectors)
            ]
            try:
                result = await neo4j.execute_write_query(
                    WRITE_QUERY,
                    items=items,
                    searchable_labels=list(SEARCHABLE_LABELS),
                )
                updated = int(result[0]["updated"]) if result else 0
                successes += updated
                failures += len(items) - updated
            except Exception as exc:
                failures += len(items)
                print(f"Write batch failed ({len(items)} nodes): {type(exc).__name__}: {exc}")

        print(f"Nodes embedded successfully: {successes}")
        print(f"Failures: {failures}")
        print("Vector index created: no")
        return 1 if failures else 0
    except Exception as exc:
        print(f"Backfill failed before writes: {type(exc).__name__}: {exc}")
        return 1
    finally:
        await neo4j.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Persist embeddings; default is dry-run")
    parser.add_argument("--force", action="store_true", help="Regenerate nodes that already have embeddings")
    parser.add_argument("--batch-size", type=int, default=256, help="Embedding API batch size")
    parser.add_argument("--write-batch-size", type=int, default=32, help="Neo4j write batch size")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(parse_args())))
