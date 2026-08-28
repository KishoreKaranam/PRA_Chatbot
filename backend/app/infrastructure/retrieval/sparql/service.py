"""
Graph retrieval service — Neo4j / Cypher implementation.

Responsibilities:
  1. Analyse the user question to identify PRA node labels and keywords.
  2. Build a focused Cypher query against Neo4j.
  3. Return structured evidence (reuses SparqlEvidence / Triple schemas
     so the rest of the application needs no schema changes).

Neo4j schema (from dump):
  Node labels : PRA, Phase, Domain, SupportingDomain, Function,
                PaymentScheme, Purpose, Rule, PreCondition,
                PostCondition, Input, Output
  Relationships: COMPRISES, HAS_PHASE, CONTAINS, BELONGS_TO_PHASE,
                 HAS_PURPOSE, HAS_RULE, HAS_PRECONDITION,
                 HAS_POSTCONDITION, HAS_INPUT, HAS_OUTPUT,
                 APPLIES_TO, PROVIDES_TO, DEPENDS_ON_SUPPORTING,
                 PROVIDES_TO_SUPPORTING, SUPPORTS_SCHEME
"""
from __future__ import annotations

import re
from typing import Any

from app.infrastructure.knowledge_graph.neo4j.client import Neo4jClient
from app.models.schemas import SparqlEvidence, Triple
from app.core.log_config import get_logger

logger = get_logger(__name__)

# Map question keywords → Neo4j node labels
PRA_LABELS: dict[str, str] = {
    "function":          "Function",
    "business function": "Function",
    "domain":            "Domain",
    "journey domain":    "Domain",
    "main journey":      "Domain",
    "supporting domain": "SupportingDomain",
    "supporting":        "SupportingDomain",
    "rule":              "Rule",
    "business rule":     "Rule",
    "payment scheme":    "PaymentScheme",
    "scheme":            "PaymentScheme",
    "phase":             "Phase",
    "purpose":           "Purpose",
    "precondition":      "PreCondition",
    "pre-condition":     "PreCondition",
    "postcondition":     "PostCondition",
    "post-condition":    "PostCondition",
    "input":             "Input",
    "output":            "Output",
    "pra":               "PRA",
}

STOP_WORDS = {
    "what", "which", "where", "when", "how", "does", "list", "tell",
    "show", "give", "are", "the", "all", "and", "for", "about",
    "with", "that", "have", "from", "this", "their", "there",
    "them", "been", "they", "some", "into", "more", "your",
}


class SparqlRetrievalService:
    """
    Cypher-based graph retrieval service.

    Named SparqlRetrievalService for backwards compatibility so no
    changes are needed in orchestrators, API layer, or LangGraph nodes.
    """

    def __init__(self, client=None) -> None:
        # client param kept for backwards compatibility; Neo4jClient is created internally
        pass

    async def retrieve(
        self, question: str, max_results: int = 10, max_triples: int = 500
    ) -> SparqlEvidence:
        """Return an entity sub-graph relevant to the question."""
        label = self._match_label(question.lower())
        keywords = self._extract_keywords(question)

        if label:
            records = await self._retrieve_by_label(label, keywords, max_results)
            query_used = f"MATCH (n:{label}) ... (keywords: {keywords})"
        elif keywords:
            records = await self._retrieve_by_keywords(keywords, max_results)
            query_used = f"Keyword search: {keywords}"
        else:
            records = await self._retrieve_top_level()
            query_used = "Top-level PRA structure"

        triples = self._records_to_triples(records)
        logger.info("cypher_retrieve", triple_count=len(triples), question=question[:80])

        return SparqlEvidence(
            query=query_used,
            triples=triples[:max_triples],
            triple_count=len(triples),
        )

    # ── Label / keyword matching ──────────────────────────────────────────────

    def _match_label(self, q_lower: str) -> str | None:
        for phrase, label in PRA_LABELS.items():
            if phrase in q_lower:
                return label
        return None

    def _extract_keywords(self, question: str) -> list[str]:
        words = re.findall(r"[a-zA-Z]{4,}", question)
        return [w for w in words if w.lower() not in STOP_WORDS]

    # ── Cypher queries ────────────────────────────────────────────────────────

    async def _retrieve_by_label(
        self, label: str, keywords: list[str], limit: int
    ) -> list[dict[str, Any]]:
        """Retrieve all nodes of a given label, optionally filtered by keywords."""
        client = Neo4jClient()
        await client.connect()
        try:
            if keywords:
                kw_conditions = " OR ".join(
                    f"toLower(n.name) CONTAINS toLower('{k}') OR toLower(coalesce(n.description,'')) CONTAINS toLower('{k}')"
                    for k in keywords[:5]
                )
                cypher = f"""
                MATCH (n:{label})
                WHERE {kw_conditions}
                OPTIONAL MATCH (n)-[:HAS_PURPOSE]->(p:Purpose)
                OPTIONAL MATCH (n)-[:HAS_INPUT]->(i:Input)
                OPTIONAL MATCH (n)-[:HAS_OUTPUT]->(o:Output)
                OPTIONAL MATCH (n)-[:HAS_RULE]->(r:Rule)
                OPTIONAL MATCH (n)-[:HAS_PRECONDITION]->(pre:PreCondition)
                OPTIONAL MATCH (n)-[:HAS_POSTCONDITION]->(post:PostCondition)
                OPTIONAL MATCH (n)-[:APPLIES_TO]->(s:PaymentScheme)
                OPTIONAL MATCH (d:Domain)-[:CONTAINS]->(n)
                OPTIONAL MATCH (sd:SupportingDomain)-[:CONTAINS]->(n)
                RETURN n, p, i, o, r, pre, post, s, d, sd
                LIMIT {limit}
                """
            else:
                cypher = f"""
                MATCH (n:{label})
                OPTIONAL MATCH (n)-[:HAS_PURPOSE]->(p:Purpose)
                OPTIONAL MATCH (n)-[:HAS_INPUT]->(i:Input)
                OPTIONAL MATCH (n)-[:HAS_OUTPUT]->(o:Output)
                OPTIONAL MATCH (n)-[:HAS_RULE]->(r:Rule)
                OPTIONAL MATCH (n)-[:HAS_PRECONDITION]->(pre:PreCondition)
                OPTIONAL MATCH (n)-[:HAS_POSTCONDITION]->(post:PostCondition)
                OPTIONAL MATCH (n)-[:APPLIES_TO]->(s:PaymentScheme)
                OPTIONAL MATCH (d:Domain)-[:CONTAINS]->(n)
                OPTIONAL MATCH (sd:SupportingDomain)-[:CONTAINS]->(n)
                RETURN n, p, i, o, r, pre, post, s, d, sd
                LIMIT {limit}
                """
            return await client.execute_read_query(cypher)
        finally:
            await client.close()

    async def _retrieve_by_keywords(
        self, keywords: list[str], limit: int
    ) -> list[dict[str, Any]]:
        """Search all node types by keyword match on name/description."""
        client = Neo4jClient()
        await client.connect()
        try:
            kw_conditions = " OR ".join(
                f"toLower(n.name) CONTAINS toLower('{k}') OR toLower(coalesce(n.description,'')) CONTAINS toLower('{k}')"
                for k in keywords[:5]
            )
            cypher = f"""
            MATCH (n)
            WHERE ({kw_conditions})
            OPTIONAL MATCH (n)-[:HAS_PURPOSE]->(p:Purpose)
            OPTIONAL MATCH (n)-[:HAS_INPUT]->(i:Input)
            OPTIONAL MATCH (n)-[:HAS_OUTPUT]->(o:Output)
            OPTIONAL MATCH (n)-[:HAS_RULE]->(r:Rule)
            OPTIONAL MATCH (d:Domain)-[:CONTAINS]->(n)
            RETURN n, p, i, o, r, d
            LIMIT {limit}
            """
            return await client.execute_read_query(cypher)
        finally:
            await client.close()

    async def _retrieve_top_level(self) -> list[dict[str, Any]]:
        """Return the top-level PRA structure (PRA → Domains → Functions)."""
        client = Neo4jClient()
        await client.connect()
        try:
            cypher = """
            MATCH (pra:PRA)
            OPTIONAL MATCH (pra)-[:COMPRISES]->(d:Domain)
            OPTIONAL MATCH (pra)-[:HAS_PHASE]->(ph:Phase)
            OPTIONAL MATCH (d)-[:CONTAINS]->(f:Function)
            RETURN pra, d, ph, f
            LIMIT 100
            """
            return await client.execute_read_query(cypher)
        finally:
            await client.close()

    # ── Result mapping ────────────────────────────────────────────────────────

    def _records_to_triples(self, records: list[dict[str, Any]]) -> list[Triple]:
        """
        Convert Neo4j record dicts into Triple objects.

        Each node property becomes a subject-predicate-object triple so
        the downstream answer generator and evidence panel work unchanged.
        """
        triples: list[Triple] = []
        seen: set[tuple[str, str, str]] = set()

        def _add(subject: str, predicate: str, obj: str) -> None:
            key = (subject, predicate, obj)
            if key not in seen and subject and obj:
                seen.add(key)
                triples.append(Triple(subject=subject, predicate=predicate, obj=obj))

        for rec in records:
            for key, node in rec.items():
                if not isinstance(node, dict):
                    continue
                name = node.get("name", "")
                desc = node.get("description", "")
                node_id = name or str(node)

                if name:
                    _add(node_id, "name", name)
                if desc:
                    _add(node_id, "description", desc)
                # Additional properties
                for prop, val in node.items():
                    if prop not in ("name", "description") and val:
                        _add(node_id, prop, str(val))

        return triples


# PRA_V2 class names that can appear in questions (lowercase → URI fragment)
# Namespace: https://example.org/pra#
PRA_CLASSES = {
    # Core functional classes (actual classes in PRA_V2 TTL)
    "business function": "BusinessFunction",
    "business rule": "BusinessRule",
    "activity": "Activity",
    "domain": "Domain",
    "main journey domain": "MainJourneyDomain",
    "main journey": "MainJourneyDomain",
    "supporting domain": "SupportingDomain",
    "supporting function": "SupportingFunction",
    "support function": "SupportingFunction",
    "process phase": "ProcessPhase",
    "phase": "ProcessPhase",
    "precondition": "Precondition",
    "postcondition": "Postcondition",
    "purpose": "PurposeStatement",
    "purpose statement": "PurposeStatement",
    "knowledge asset": "KnowledgeAsset",
    "business layer": "BusinessLayer",
    "layer": "BusinessLayer",
    "operational context": "OperationalContext",
    "context": "OperationalContext",
    "editorial note": "EditorialNote",
    "note": "EditorialNote",
    "applicability": "ApplicabilityStatus",
}
