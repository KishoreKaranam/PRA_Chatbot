"""
Semantic similarity service — Neo4j implementation.

Replaces local TTL file loading with a Neo4j query to build the
embedding corpus.  The in-memory NumPy vector index is retained.

All Function, Domain, SupportingDomain, Rule, and PaymentScheme nodes
are embedded once at startup and cached in memory.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from openai import AsyncOpenAI, AsyncAzureOpenAI

from app.core.log_config import get_logger
from app.infrastructure.knowledge_graph.neo4j.searchable_labels import SEARCHABLE_LABELS
from app.core.settings import get_settings
from app.models.schemas import SimilarityEvidence, SimilarityHit

logger = get_logger(__name__)

# Node labels to embed
EMBED_LABELS = list(SEARCHABLE_LABELS)


@dataclass(slots=True)
class _RecordBundle:
    records: list[dict]


class SimilarityRetrievalService:
    """
    Adapter-pattern vector search over PRA Neo4j entities.

    The semantic index is built from Neo4j node properties (name + description),
    so the application does not require TTL files.
    """

    def __init__(self, client=None, ttl_files=None) -> None:
        # params kept for backwards compatibility; unused in Neo4j mode
        self._settings = get_settings()
        self._backend: _NumPyBackend | None = None
        self._ready = False

    async def retrieve(self, question: str, max_results: int = 10) -> SimilarityEvidence:
        if not self._settings.embedding_enabled:
            return SimilarityEvidence(
                hits=[],
                note=(
                    "Similarity search is disabled. Set EMBEDDING_ENABLED=true and "
                    "provide an OpenAI or Azure OpenAI key to activate it."
                ),
            )

        if not self._ready:
            await self._build_index()

        if self._backend is None or len(self._backend) == 0:
            return SimilarityEvidence(hits=[], note="Embedding index is empty.")

        hits = await self._backend.search(question, max_results)
        logger.info("similarity_retrieve_neo4j", hits=len(hits), question=question[:80])
        return SimilarityEvidence(hits=hits)

    # ── Index builder ─────────────────────────────────────────────────────────

    async def _load_records_from_neo4j(self) -> list[dict[str, Any]]:
        """Fetch all embeddable nodes from Neo4j."""
        from app.infrastructure.knowledge_graph.neo4j.client import Neo4jClient

        cypher = """
        MATCH (n)
        WHERE any(lbl IN labels(n) WHERE lbl IN $labels)
          AND n.name IS NOT NULL
        RETURN labels(n)[0] AS label_type,
               n.name AS name,
               coalesce(n.description, '') AS description
        """
        client = Neo4jClient()
        await client.connect()
        try:
            records = await client.execute_read_query(cypher, labels=EMBED_LABELS)
        finally:
            await client.close()

        result = []
        for rec in records:
            name = rec.get("name", "")
            description = rec.get("description", "")
            label_type = rec.get("label_type", "")
            if not name:
                continue
            text = f"{name}. {description}".strip().rstrip(".")
            result.append({
                "uri":   f"neo4j://{label_type}/{name}",
                "label": name,
                "text":  text,
            })

        logger.info("similarity_neo4j_records_loaded", count=len(result))
        return result

    async def _build_index(self) -> None:
        logger.info("similarity_index_building_neo4j")
        records = await self._load_records_from_neo4j()

        if not records:
            logger.warning("similarity_index_empty")
            self._ready = True
            return

        s = self._settings
        try:
            if getattr(s, "azure_openai_endpoint", None) and getattr(s, "azure_openai_api_key", None):
                openai_client = AsyncAzureOpenAI(
                    api_key=s.azure_openai_api_key,
                    azure_endpoint=s.azure_openai_endpoint,
                    api_version=s.azure_openai_api_version,
                )
                embed_model = s.azure_openai_embedding_deployment or s.embedding_model
                logger.info("embedding_backend", backend="azure", deployment=embed_model)
            else:
                if not s.openai_api_key:
                    logger.error("embedding_no_api_key", msg="OPENAI_API_KEY not set")
                    self._ready = True
                    return
                openai_client = AsyncOpenAI(
                    api_key=s.openai_api_key,
                    base_url=s.openai_base_url,
                )
                embed_model = s.embedding_model
                logger.info("embedding_backend", backend="openai", model=embed_model)

            self._backend = await _NumPyBackend.build(records, openai_client, embed_model)
            self._ready = True
            logger.info("similarity_index_built_neo4j", count=len(records))
        except Exception as exc:
            logger.error("similarity_index_build_failed", error=str(exc))
            self._ready = True


class _NumPyBackend:
    """Cosine similarity search over pre-computed local embeddings."""

    def __init__(
        self,
        records: list[dict],
        matrix: np.ndarray,
        openai_client: AsyncOpenAI,
        model: str,
    ) -> None:
        self._records = records
        self._matrix = matrix
        self._openai = openai_client
        self._model = model

    def __len__(self) -> int:
        return len(self._records)

    @classmethod
    async def build(
        cls,
        records: list[dict],
        openai_client: AsyncOpenAI,
        model: str,
    ) -> "_NumPyBackend":
        texts = [r["text"] for r in records]
        embeddings: list[list[float]] = []
        batch_size = 256

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            resp = await openai_client.embeddings.create(input=batch, model=model)
            embeddings.extend([d.embedding for d in resp.data])

        matrix = np.array(embeddings, dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        matrix /= norms
        return cls(records, matrix, openai_client, model)

    async def search(self, query: str, k: int) -> list[SimilarityHit]:
        resp = await self._openai.embeddings.create(input=[query], model=self._model)
        q_vec = np.array(resp.data[0].embedding, dtype=np.float32)
        q_vec /= max(np.linalg.norm(q_vec), 1e-9)

        scores = self._matrix @ q_vec
        top_idx = np.argsort(-scores)[:k]

        return [
            SimilarityHit(
                uri=self._records[i]["uri"],
                label=self._records[i]["label"],
                score=float(scores[i]),
                text=self._records[i]["text"][:300],
            )
            for i in top_idx
        ]
