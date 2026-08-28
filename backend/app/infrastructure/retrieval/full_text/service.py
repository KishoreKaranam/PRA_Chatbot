"""
Full-Text Search retrieval service — Neo4j implementation.

Replaces GraphDB Lucene FTS with Neo4j CONTAINS-based keyword search
across all PRA node labels (name + description properties).

Neo4j schema searched:
  Function, Domain, SupportingDomain, Rule, PaymentScheme,
  Phase, Purpose, PreCondition, PostCondition, Input, Output, PRA
"""
from __future__ import annotations

import re

from app.core.log_config import get_logger
from app.infrastructure.knowledge_graph.neo4j.client import Neo4jClient
from app.models.schemas import FtsEvidence, FtsHit

logger = get_logger(__name__)

# All searchable node labels in the Neo4j PRA schema
SEARCHABLE_LABELS = [
    "Function", "Domain", "SupportingDomain", "Rule",
    "PaymentScheme", "Phase", "Purpose",
    "PreCondition", "PostCondition", "Input", "Output", "PRA",
]


class FtsRetrievalService:
    """Full-text search retrieval using Neo4j CONTAINS queries."""

    def __init__(self, client=None) -> None:
        # client param kept for backwards compatibility
        pass

    async def retrieve(self, question: str, max_results: int = 10) -> FtsEvidence:
        """Search Neo4j for nodes matching keywords from the question."""
        search_term = self._build_search_term(question)
        hits = await self._run_neo4j_search(search_term, max_results)
        logger.info("fts_retrieve_neo4j", hits=len(hits), term=search_term)
        return FtsEvidence(search_term=search_term, hits=hits)

    # ── Search term builder ───────────────────────────────────────────────────

    def _build_search_term(self, question: str) -> str:
        """Extract meaningful keywords from the user question."""
        STOP = {
            "what", "which", "where", "when", "how", "does", "list", "tell",
            "show", "give", "are", "the", "all", "and", "for", "about",
            "with", "that", "have", "from", "this", "their", "is", "can",
            "do", "did", "was", "were", "a", "an", "in", "of", "to",
        }
        words = re.findall(r"[a-zA-Z]{3,}", question)
        meaningful = [w for w in words if w.lower() not in STOP]
        if not meaningful:
            return question.strip()
        return " ".join(meaningful[:8])

    # ── Neo4j search ──────────────────────────────────────────────────────────

    async def _run_neo4j_search(self, search_term: str, limit: int) -> list[FtsHit]:
        """
        Search all PRA node labels using CONTAINS on name and description.

        Strategy:
          1. Split search_term into individual keywords.
          2. For each keyword, check if it appears in name OR description.
          3. Score by number of keyword matches (higher = more relevant).
          4. Return top-k results.
        """
        keywords = [k.strip().lower() for k in search_term.split() if k.strip()]
        if not keywords:
            keywords = [search_term.strip().lower()]

        # Build WHERE conditions — each keyword must match at least one node
        kw_clauses = " OR ".join(
            f"toLower(n.name) CONTAINS '{k}' OR toLower(coalesce(n.description, '')) CONTAINS '{k}'"
            for k in keywords[:6]
        )

        cypher = f"""
        MATCH (n)
        WHERE any(lbl IN labels(n) WHERE lbl IN $labels)
          AND ({kw_clauses})
        RETURN labels(n)[0] AS node_type,
               n.name AS name,
               coalesce(n.description, '') AS description
        LIMIT {limit}
        """

        client = Neo4jClient()
        await client.connect()
        try:
            records = await client.execute_read_query(cypher, labels=SEARCHABLE_LABELS)
        finally:
            await client.close()

        hits: list[FtsHit] = []
        for rec in records:
            name = rec.get("name", "")
            description = rec.get("description", "")
            node_type = rec.get("node_type", "")

            # Score = fraction of keywords matched
            text = (name + " " + description).lower()
            matched = sum(1 for k in keywords if k in text)
            score = round(matched / max(len(keywords), 1), 2)

            snippet = description[:300] if description else name
            uri = f"neo4j://{node_type}/{name}"

            hits.append(FtsHit(uri=uri, label=name, score=score, snippet=snippet))

        # Sort by score descending
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits
