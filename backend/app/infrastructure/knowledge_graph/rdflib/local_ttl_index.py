from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
import os
import re

from rdflib import Graph, URIRef
from rdflib.namespace import DCTERMS, RDF, RDFS

from app.core.log_config import get_logger

logger = get_logger(__name__)

STOPWORDS = {
    "what", "which", "where", "when", "how", "does", "do", "did", "is", "are",
    "was", "were", "the", "a", "an", "all", "and", "or", "for", "about",
    "with", "that", "this", "their", "from", "into", "to", "of", "in", "on",
    "tell", "show", "give", "list", "find", "search", "lookup", "can", "could",
    "would", "should", "please", "me",
}


@dataclass(slots=True)
class LocalRecord:
    uri: str
    label: str
    description: str
    comment: str
    text: str
    tokens: tuple[str, ...]


def resolve_ttl_files(ttl_files: Sequence[str] | None = None) -> list[Path]:
    candidates: list[str] = []

    if ttl_files:
        candidates.extend(str(p) for p in ttl_files)
    else:
        env_files = os.getenv("TTL_FILES") or os.getenv("PRA_TTL_FILES")
        env_dir = os.getenv("TTL_DIR") or os.getenv("PRA_TTL_DIR")

        if env_files:
            candidates.extend(part.strip() for part in env_files.split(",") if part.strip())
        elif env_dir:
            base = Path(env_dir).expanduser()
            if base.exists() and base.is_dir():
                candidates.extend(str(p) for p in sorted(base.glob("*.ttl")))
            else:
                logger.warning("ttl_dir_missing", path=str(base))

    resolved: list[Path] = []
    
    # If backend is running from backend/ directory, use that as the base
    backend_dir = Path(__file__).resolve().parent.parent.parent.parent.parent
    
    for item in candidates:
        path = Path(item).expanduser()
        
        # Try as-is first
        if path.exists() and path.is_file():
            resolved.append(path)
        # Try relative to backend directory
        elif (backend_dir / path).exists() and (backend_dir / path).is_file():
            resolved.append(backend_dir / path)
        # Try relative to parent of backend directory
        elif (backend_dir.parent / path).exists() and (backend_dir.parent / path).is_file():
            resolved.append(backend_dir.parent / path)
        else:
            logger.warning("ttl_file_missing", path=str(path), tried_relative=str(backend_dir / path))

    seen: set[str] = set()
    unique: list[Path] = []
    for path in resolved:
        key = str(path.resolve())
        if key not in seen:
            unique.append(path)
            seen.add(key)

    return unique


def load_local_records(ttl_files: Sequence[str] | None = None) -> list[LocalRecord]:
    paths = resolve_ttl_files(ttl_files)
    if not paths:
        logger.warning("no_ttl_files_found")
        return []

    records: list[LocalRecord] = []
    seen_uris: set[str] = set()

    for path in paths:
        graph = Graph()
        try:
            graph.parse(str(path), format="turtle")
        except Exception as exc:
            logger.warning("ttl_parse_failed", path=str(path), error=str(exc))
            continue

        subjects = {str(s) for s in graph.subjects(None, None) if isinstance(s, URIRef)}

        for uri in sorted(subjects):
            if uri in seen_uris:
                continue
            seen_uris.add(uri)

            subj = URIRef(uri)
            label = _first_literal(graph, subj, RDFS.label) or _local_name(uri)
            desc = _first_literal(graph, subj, DCTERMS.description)
            comment = _first_literal(graph, subj, RDFS.comment)

            type_names = [
                _local_name(str(obj))
                for obj in graph.objects(subj, RDF.type)
                if isinstance(obj, URIRef)
            ]

            text_parts = [label, desc, comment, " ".join(type_names)]
            text = " ".join(part for part in text_parts if part).strip()
            if not text:
                text = label or _local_name(uri)

            tokens = tuple(tokenize(text))
            records.append(
                LocalRecord(
                    uri=uri,
                    label=label,
                    description=desc,
                    comment=comment,
                    text=text,
                    tokens=tokens,
                )
            )

    logger.info("local_ttl_records_loaded", count=len(records), files=len(paths))
    return records


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-zA-Z0-9]{3,}", text.lower())
    return [w for w in words if w not in STOPWORDS]


def _first_literal(graph: Graph, subject: URIRef, predicate) -> str:
    for obj in graph.objects(subject, predicate):
        value = str(obj).strip()
        if value:
            return value
    return ""


def _local_name(uri: str) -> str:
    if "#" in uri:
        return uri.rsplit("#", 1)[-1]
    if "/" in uri:
        return uri.rstrip("/").rsplit("/", 1)[-1]
    return uri
