"""Neo4j full-text retrieval returning the existing FTS evidence contract."""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from app.core.log_config import get_logger
from app.infrastructure.knowledge_graph.neo4j.client import Neo4jClient
from app.infrastructure.retrieval.full_text.service import FtsRetrievalService
from app.models.schemas import FtsEvidence, FtsHit

logger = get_logger(__name__)

NEO4J_FTS_INDEX = "pra_fulltext"

NEO4J_FTS_QUERY = """CALL db.index.fulltext.queryNodes($index_name, $search_term)
YIELD node, score
RETURN node, score
ORDER BY score DESC
LIMIT $limit"""

# CONTAINS fallback — used when the fulltext index does not exist in the dump
NEO4J_CONTAINS_QUERY = """
MATCH (n)
WHERE toLower(n.name) CONTAINS toLower($search_term)
   OR toLower(coalesce(n.description, '')) CONTAINS toLower($search_term)
RETURN n AS node, 1.0 AS score
LIMIT $limit
"""


class Neo4jFtsRetrievalService(FtsRetrievalService):
    """Read-only Neo4j FTS service with the application's FtsEvidence API.

    Primary:  db.index.fulltext.queryNodes (Lucene FTS index)
    Fallback: CONTAINS search (works without any index)
    """

    def __init__(self, client: Neo4jClient) -> None:
        self._neo4j = client

    async def retrieve(self, question: str, max_results: int = 10) -> FtsEvidence:
        """Search Neo4j for nodes matching keywords in the question."""
        search_term = self._build_search_term(question)

        # Try Lucene fulltext index first; fall back to CONTAINS if unavailable
        rows = await self._run_fts_query(search_term, max_results)
        if not rows:
            rows = await self._run_contains_query(search_term, max_results)

        hits = [self._row_to_hit(row) for row in rows]
        logger.info(
            "neo4j_fts_retrieve",
            hits=len(hits),
            term=search_term,
        )
        return FtsEvidence(search_term=search_term, hits=hits)

    async def _run_fts_query(self, search_term: str, limit: int) -> list[dict]:
        try:
            return await self._neo4j.execute_read_query(
                NEO4J_FTS_QUERY,
                index_name=NEO4J_FTS_INDEX,
                search_term=search_term,
                limit=limit,
            )
        except Exception as exc:
            logger.warning("neo4j_fts_index_unavailable", error=str(exc))
            return []

    async def _run_contains_query(self, search_term: str, limit: int) -> list[dict]:
        """CONTAINS fallback — no index required."""
        # Use first keyword only for CONTAINS (avoid multi-word noise)
        keyword = search_term.split()[0] if search_term.split() else search_term
        try:
            return await self._neo4j.execute_read_query(
                NEO4J_CONTAINS_QUERY,
                search_term=keyword,
                limit=limit,
            )
        except Exception as exc:
            logger.error("neo4j_contains_fallback_failed", error=str(exc))
            return []

    @classmethod
    def _row_to_hit(cls, row: Mapping[str, Any]) -> FtsHit:
        node = row.get("node")
        properties = cls._node_properties(node)

        # New dump uses `name` and `description` (not `label`/`uri`)
        name = cls._first_text(properties, "name", "label")
        uri = cls._first_text(properties, "uri") or f"neo4j://node/{name}"
        snippet = cls._first_text(properties, "description", "comment", "name")

        raw_score = row.get("score", 0.0)
        return FtsHit(
            uri=uri,
            label=name or uri,
            score=cls._normalize_score(raw_score),
            snippet=(snippet or "")[:300],
        )

    @staticmethod
    def _node_properties(node: Any) -> dict[str, Any]:
        """Extract properties from a Neo4j driver Node or a record mapping."""
        if node is None:
            return {}
        if isinstance(node, Mapping):
            return dict(node)
        try:
            return dict(node)
        except (TypeError, ValueError):
            return {}

    @staticmethod
    def _text(value: Any) -> str:
        """Convert Neo4j scalar/list values to readable text."""
        if value is None:
            return ""
        if isinstance(value, (list, tuple)):
            return "; ".join(str(item) for item in value if item is not None).strip()
        return str(value).strip()

    @classmethod
    def _first_text(cls, properties: Mapping[str, Any], *names: str) -> str:
        for name in names:
            value = cls._text(properties.get(name))
            if value:
                return value
        return ""

    @staticmethod
    def _local_identifier(uri: str) -> str:
        if "#" in uri:
            return uri.rsplit("#", 1)[-1]
        if "/" in uri:
            return uri.rstrip("/").rsplit("/", 1)[-1]
        return uri

    @staticmethod
    def _normalize_score(raw_score: Any) -> float:
        """Map a non-negative Neo4j Lucene score into [0, 1].

        Neo4j's score has no fixed upper bound.  The monotonic saturation
        function raw / (1 + raw) avoids assuming one, preserves ranking, and
        gives diminishing gains as raw relevance increases.
        """
        try:
            raw = float(raw_score)
        except (TypeError, ValueError):
            return 0.0
        if not math.isfinite(raw) or raw <= 0.0:
            return 0.0
        return raw / (1.0 + raw)
