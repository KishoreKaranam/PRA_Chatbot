"""
Retrieval orchestrator.

Chooses which retrieval mode(s) to invoke based on agent instructions
and the character of the user question.  Returns consolidated evidence.
"""
from __future__ import annotations

import re
from app.models.schemas import (
    AgentInstructions,
    RetrievalStrategy,
    SparqlEvidence,
    FtsEvidence,
    SimilarityEvidence,
)
from app.services.sparql_service import SparqlRetrievalService
from app.services.fts_service import FtsRetrievalService
from app.services.similarity_service import SimilarityRetrievalService
from app.core.log_config import get_logger

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


class RetrievalOrchestrator:
    """Coordinate SPARQL, FTS, and similarity retrieval."""

    def __init__(
        self,
        sparql_svc: SparqlRetrievalService,
        fts_svc: FtsRetrievalService,
        sim_svc: SimilarityRetrievalService,
    ) -> None:
        self._sparql = sparql_svc
        self._fts = fts_svc
        self._sim = sim_svc

    async def retrieve(
        self,
        question: str,
        instructions: AgentInstructions,
    ) -> tuple[list[str], list]:
        """
        Returns:
          - modes_used: list[str]   – which modes produced results
          - evidence:   list        – list of evidence objects
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

        # HYBRID: choose based on question characteristics
        return await self._hybrid(question, max_r, max_t, instructions)

    # ── Single-mode strategies ────────────────────────────────────────────────

    async def _sparql_only(self, question: str, max_r: int, max_t: int):
        ev = await self._sparql.retrieve(question, max_r, max_t)
        return (["sparql"] if ev.triple_count > 0 else []), [ev]

    async def _fts_only(self, question: str, max_r: int):
        ev = await self._fts.retrieve(question, max_r)
        return (["fts"] if ev.hits else []), [ev]

    async def _similarity_only(self, question: str, max_r: int):
        ev = await self._sim.retrieve(question, max_r)
        return (["similarity"] if ev.hits else []), [ev]

    # ── Hybrid strategy ───────────────────────────────────────────────────────

    async def _hybrid(
        self,
        question: str,
        max_r: int,
        max_t: int,
        instructions: AgentInstructions,
    ):
        is_ontology_q = self._is_ontology_question(question)
        is_keyword_q  = self._is_keyword_question(question)

        evidence: list = []
        modes_used: list[str] = []

        # ── Run all three modes in parallel ───────────────────────────────────
        import asyncio
        sparql_task = asyncio.create_task(self._sparql.retrieve(question, max_r, max_t))
        fts_task    = asyncio.create_task(self._fts.retrieve(question, max_r))
        sim_task    = asyncio.create_task(self._sim.retrieve(question, max_r))

        sparql_ev, fts_ev, sim_ev = await asyncio.gather(
            sparql_task, fts_task, sim_task
        )

        # ── Collect results — SPARQL always first ────────────────────────────
        evidence.append(sparql_ev)
        if sparql_ev.triple_count > 0:
            modes_used.append("sparql")

        # FTS always included when it has hits
        evidence.append(fts_ev)
        if fts_ev.hits:
            modes_used.append("fts")

        # Similarity included when it has hits
        evidence.append(sim_ev)
        if sim_ev.hits:
            modes_used.append("similarity")

        # ── Fallback: widen SPARQL to schema level if nothing worked ──────────
        if not modes_used:
            logger.warning("all_retrieval_empty", question=question[:80])
            wide_ev = await self._sparql.retrieve("ontology schema classes", max_r, max_t)
            evidence.append(wide_ev)
            if wide_ev.triple_count > 0:
                modes_used.append("sparql-fallback")

        logger.info("hybrid_modes", modes=modes_used, question=question[:60])
        return modes_used, evidence

    # ── Question classifiers ──────────────────────────────────────────────────

    def _is_ontology_question(self, q: str) -> bool:
        q_lower = q.lower()
        return any(re.search(p, q_lower) for p in ONTOLOGY_SIGNALS)

    def _is_keyword_question(self, q: str) -> bool:
        q_lower = q.lower()
        return any(re.search(p, q_lower) for p in KEYWORD_SIGNALS)
