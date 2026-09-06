"""
Retrieval orchestrator.

Chooses which retrieval mode(s) to invoke based on agent instructions
and the character of the user question. Returns consolidated evidence.
This version always allows local FTS and local similarity search.
"""
from __future__ import annotations

import asyncio
from enum import Enum
import re

from app.core.log_config import get_logger
from app.core.settings import get_settings
from app.models.schemas import (
    AgentInstructions,
    RetrievalStrategy,
    FtsEvidence,
    Neo4jGraphEvidence,
)
from app.infrastructure.retrieval.full_text.service import FtsRetrievalService
from app.infrastructure.retrieval.vector.service import SimilarityRetrievalService
from app.infrastructure.retrieval.sparql.service import SparqlRetrievalService

logger = get_logger(__name__)

# Signals that hint the question is about the ontology structure
ONTOLOGY_SIGNALS = [
    r"\b(class|classes|property|properties|subclass|subclasses|hierarchy|schema|ontology|type|types)\b",
    r"\b(define|definition|model|models|modelling)\b",
    r"\bwhat (is|are) (a|an|the)\b",
    r"\bhow (is|are).+(defined|modelled|structured)\b",
]

# Signals that hint the question is keyword / entity lookup
KEYWORD_SIGNALS = [
    r"\b(list|show|find|search|lookup|which)\b",
    r"\brelated to\b",
    r"\bcontains?\b",
    r"\bwhat.+(activities|functions|domains|rules|schemes)\b",
]

class RetrievalBackend(str, Enum):
    GRAPHDB = "graphdb"
    NEO4J = "neo4j"


class RetrievalOrchestrator:
    """Coordinate SPARQL, FTS, and similarity retrieval."""

    def __init__(
        self,
        sparql_svc: SparqlRetrievalService | None,
        neo4j_svc: Neo4jGraphEvidence,
        fts_svc: FtsRetrievalService,
        sim_svc: SimilarityRetrievalService,
    ) -> None:
        self._sparql = sparql_svc
        self._neo4j = neo4j_svc
        self._fts = fts_svc
        self._sim = sim_svc

    async def retrieve(
        self,
        question: str,
        instructions: AgentInstructions,
    ) -> tuple[list[str], list]:
        """
        Returns:
          - modes_used: list[str]   - which modes produced results
          - evidence:   list        - list of evidence objects
        """
        strategy = instructions.retrieval_strategy
        max_r = instructions.max_results
        max_t = instructions.max_triples

        if strategy == RetrievalStrategy.SPARQL:
            return await self._sparql_only(question, max_r, max_t)

        if strategy == RetrievalStrategy.FTS:
            return await self._fts_only(question, max_r)

        if strategy == RetrievalStrategy.SIMILARITY:
            return await self._similarity_only(question, max_r)

        return await self._hybrid(question, max_r, max_t)

    async def _sparql_only(self, question: str, max_r: int, max_t: int):
        ev = await self._sparql.retrieve(question, max_r, max_t)
        return (["sparql"] if ev.triple_count > 0 else []), [ev]

    async def _fts_only(self, question: str, max_r: int):
        ev = await self._fts.retrieve(question, max_r)
        return (["fts"] if ev.hits else []), [ev]

    async def _similarity_only(self, question: str, max_r: int):
        ev = await self._sim.retrieve(question, max_r)
        return (["similarity"] if ev.hits else []), [ev]

    async def _hybrid(
        self,
        question: str,
        max_r: int,
        max_t: int,
    ):
        _is_ontology_q = self._is_ontology_question(question)
        _is_keyword_q = self._is_keyword_question(question)

        evidence: list = []
        modes_used: list[str] = []

        settings = get_settings()
        backend = settings.retrieval_backend

        # --- [DEBUG-GROUNDING] Log backend and question ---
        logger.info("[DEBUG-GROUNDING] 1. User Question & Backend", question=question, retrieval_backend=backend)
        # ----------------------------------------------------

        graph_task = None
        if backend == RetrievalBackend.NEO4J:
            graph_task = asyncio.create_task(self._neo4j.retrieve(question))
        else: # Default to GraphDB/SPARQL
            graph_task = asyncio.create_task(self._sparql.retrieve(question, max_r, max_t))

        fts_task = asyncio.create_task(self._fts.retrieve(question, max_r))
        sim_task = asyncio.create_task(self._sim.retrieve(question, max_r))

        sparql_ev, fts_ev, sim_ev = await asyncio.gather(graph_task, fts_task, sim_task)

        # --- [DEBUG-GROUNDING] Log Neo4j evidence ---
        if isinstance(sparql_ev, Neo4jGraphEvidence):
            logger.info("[DEBUG-GROUNDING] 2. Neo4j Query", query=sparql_ev.query)
            logger.info("[DEBUG-GROUNDING] 3. Neo4j Result Count", count=sparql_ev.result_count)
            logger.info("[DEBUG-GROUNDING] 4. Sample Neo4j Relationships",
                        relationships=[r.model_dump() for r in sparql_ev.relationships[:5]])
        # --------------------------------------------

        evidence.append(sparql_ev)
        # Check for results in either Sparql or Neo4j evidence
        if hasattr(sparql_ev, "triple_count") and sparql_ev.triple_count > 0:
            modes_used.append("sparql")
        elif hasattr(sparql_ev, "result_count") and sparql_ev.result_count > 0:
            # Use the backend name to label the mode
            modes_used.append(backend)

        evidence.append(fts_ev)
        if fts_ev.hits:
            modes_used.append("fts")

        evidence.append(sim_ev)
        if sim_ev.hits:
            modes_used.append("similarity")

        # Preserve the legacy broad SPARQL fallback only for an explicitly
        # configured legacy graph backend. Neo4j zero results are a legitimate
        # empty-result state and must not switch databases implicitly.
        if not modes_used:
            logger.warning("all_retrieval_empty", question=question[:80])
            if backend != RetrievalBackend.NEO4J and self._sparql is not None:
                wide_ev = await self._sparql.retrieve("ontology schema classes", max_r, max_t)
                evidence.append(wide_ev)
                if wide_ev.triple_count > 0:
                    modes_used.append("sparql-fallback")

        logger.info(
            "hybrid_modes",
            modes=modes_used,
            question=question[:60],
            ontology_hint=_is_ontology_q,
            keyword_hint=_is_keyword_q,
        )
        return modes_used, evidence

    def _is_ontology_question(self, q: str) -> bool:
        q_lower = q.lower()
        return any(re.search(p, q_lower) for p in ONTOLOGY_SIGNALS)

    def _is_keyword_question(self, q: str) -> bool:
        q_lower = q.lower()
        return any(re.search(p, q_lower) for p in KEYWORD_SIGNALS)
