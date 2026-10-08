"""Pydantic models for chat request / response and agent configuration."""
from __future__ import annotations
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field
from app.prompts.defaults import DEFAULT_SYSTEM_PROMPT


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
        default=DEFAULT_SYSTEM_PROMPT,
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


# ── Neo4j evidence ──────────────────────────────────────────────────────────

class Neo4jNode(BaseModel):
    element_id: str
    labels: list[str]
    properties: dict[str, Any]


class Neo4jRelationship(BaseModel):
    element_id: str
    type: str
    start_node: str
    end_node: str
    properties: dict[str, Any]


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


class Neo4jGraphEvidence(BaseModel):
    mode: str = "neo4j"
    query: str = ""
    results: list[Neo4jNode] = Field(default_factory=list)
    relationships: list[Neo4jRelationship] = Field(default_factory=list)
    result_count: int = 0


# ── Grounding / output review ─────────────────────────────────────────────────

class GroundingClaim(BaseModel):
    """A single atomic claim extracted from the generated answer and its verdict."""
    claim: str = Field(..., description="The atomic statement taken from the answer")
    supported: bool = Field(..., description="True if backed by retrieved evidence")
    evidence_refs: list[str] = Field(
        default_factory=list,
        description="Labels/URIs of the evidence items supporting this claim",
    )
    note: str = Field(default="", description="Short rationale for the verdict")


class GroundingReport(BaseModel):
    """
    Result of the output validation / review layer.

    Scores what fraction of the generated answer is grounded in the retrieved
    document evidence, so the UI can show an "X% evidence-based" indicator.
    """
    grounding_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Fraction (0.0-1.0) of claims supported by evidence",
    )
    grounded_percentage: int = Field(
        default=0, ge=0, le=100,
        description="grounding_score expressed as a 0-100 percentage for display",
    )
    total_claims: int = 0
    supported_claims: int = 0
    verdict: str = Field(
        default="unverified",
        description="high | moderate | low | unverified",
    )
    summary: str = Field(default="", description="Human-readable review summary")
    claims: list[GroundingClaim] = Field(default_factory=list)
    method: str = Field(
        default="none",
        description="How the score was derived: llm | lexical | none",
    )


# ── Conversation memory ───────────────────────────────────────────────────────

class ConversationTurn(BaseModel):
    role: str = Field(..., description="'user' or 'assistant'")
    content: str = Field(..., description="The message text")


# ── Chat request / response ───────────────────────────────────────────────────

class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, description="User question")
    session_id: str | None = Field(
        default=None,
        description="UUID session identifier returned by POST /api/session. "
                    "When provided, history is loaded from the database; "
                    "when absent the request is treated as stateless.",
    )
    agent_instructions: AgentInstructions | None = Field(
        default=None,
        description="Override agent instructions for this request; falls back to server config if None",
    )
    # Kept for backwards-compatibility (ignored when session_id is present)
    conversation_history: list[ConversationTurn] = Field(
        default_factory=list,
        description="[Legacy] Inline history; used only when session_id is not provided.",
    )


class ChatResponse(BaseModel):
    question: str
    rewritten_question: str = ""        # after Stage 1 context resolution
    is_followup: bool = False
    intent: str = "exploratory"         # definition | list | comparison | exploratory | vague
    answer: str
    retrieval_modes_used: list[str] = Field(default_factory=list)
    evidence: list[SparqlEvidence | FtsEvidence | SimilarityEvidence | Neo4jGraphEvidence] = Field(default_factory=list)
    confidence: float | None = None
    warning: str | None = None
    clarification_needed: str | None = None   # non-None means ask user this
    session_id: str | None = None             # echo back so frontend can store it
    grounding: GroundingReport | None = None  # output review: % grounded in evidence
    # updated_history removed — history now lives entirely in PostgreSQL
