"""Pydantic models for chat request / response and agent configuration."""
from __future__ import annotations
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


# ── Enumerations ─────────────────────────────────────────────────────────────

class RetrievalStrategy(str, Enum):
    SPARQL = "sparql"
    FTS = "fts"
    SIMILARITY = "similarity"
    HYBRID = "hybrid"


class AnswerStyle(str, Enum):
    BUSINESS = "business"
    TECHNICAL = "technical"
    CONCISE = "concise"
    DETAILED = "detailed"


# ── Agent Instructions (persisted config) ────────────────────────────────────

class AgentInstructions(BaseModel):
    system_prompt: str = Field(
        default=(
            "You are a knowledgeable assistant for the Payment Reference Architecture (PRA). "
            "Answer questions strictly from the information retrieved from the PRA knowledge graph. "
            "If the retrieved context does not contain enough information, say so clearly."
        ),
        description="System prompt / assistant behaviour",
    )
    retrieval_strategy: RetrievalStrategy = RetrievalStrategy.HYBRID
    answer_style: AnswerStyle = AnswerStyle.BUSINESS
    strict_ontology_mode: bool = Field(
        default=False,
        description="If true, only use ontology class/property definitions; ignore instance data",
    )
    confidence_threshold: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Minimum relevance score for a result to be included in context",
    )
    max_results: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum number of entities per retrieval mode (SELECT LIMIT)",
    )
    max_triples: int = Field(
        default=500,
        ge=50,
        le=5000,
        description="Maximum number of triples returned by the SPARQL CONSTRUCT query",
    )
    show_sparql_queries: bool = Field(
        default=True,
        description="Include the SPARQL queries in the response evidence",
    )
    show_raw_evidence: bool = Field(
        default=True,
        description="Show triples / search hits in the UI source panel",
    )


# ── Retrieval evidence ────────────────────────────────────────────────────────

class Triple(BaseModel):
    subject: str
    predicate: str
    obj: str  # 'object' is reserved in Python


class SparqlEvidence(BaseModel):
    mode: str = "sparql"
    query: str
    triples: list[Triple]
    triple_count: int


class FtsHit(BaseModel):
    uri: str
    label: str
    score: float
    snippet: str


class FtsEvidence(BaseModel):
    mode: str = "fts"
    search_term: str
    hits: list[FtsHit]


class SimilarityHit(BaseModel):
    uri: str
    label: str
    score: float
    text: str


class SimilarityEvidence(BaseModel):
    mode: str = "similarity"
    hits: list[SimilarityHit]
    note: str = ""


# ── Chat request / response ───────────────────────────────────────────────────

class ChatRequest(BaseModel):
    question: str = Field(..., min_length=3, description="User question")
    agent_instructions: AgentInstructions | None = Field(
        default=None,
        description="Override agent instructions for this request; falls back to server config if None",
    )


class ChatResponse(BaseModel):
    question: str
    answer: str
    retrieval_modes_used: list[str]
    evidence: list[Any]  # list of SparqlEvidence | FtsEvidence | SimilarityEvidence
    confidence: float | None = None
    warning: str | None = None
