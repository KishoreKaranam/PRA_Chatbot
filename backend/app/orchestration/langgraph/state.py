"""
LangGraph State Definition for PRA Chatbot
==========================================

PRAState is the single shared dict that flows through every node in the graph.
Each node reads from it and writes back to it — LangGraph merges the returned
partial dicts automatically.

State lifecycle per request:
  ┌──────────────────────────────────────────────────────────┐
  │  Initialised by chat.py with:                            │
  │    session_id, raw_question, conversation_history        │
  │                                                          │
  │  Node: context_node    writes: rewritten_question,       │
  │                                is_followup,              │
  │                                entities_mentioned        │
  │                                                          │
  │  Node: intent_node     writes: intent                    │
  │                                                          │
  │  Node: clarify_node    writes: needs_clarification,      │
  │                                clarification_msg         │
  │                                                          │
  │  Node: retrieve_node   writes: evidence,                 │
  │                                retrieval_modes           │
  │                                                          │
  │  Node: validate_node   writes: validated_evidence,       │
  │                                has_sufficient            │
  │                                                          │
  │  Node: answer_node     writes: answer, confidence        │
  │                                                          │
  │  Node: persist_node    writes: (nothing — DB side-effect)│
  └──────────────────────────────────────────────────────────┘

Design rules:
  - All fields have safe defaults so nodes never KeyError on missing keys.
  - String fields default to ""; bool fields to False; list fields to [].
  - `confidence` defaults to 0.0 (not None) to avoid float-comparison issues.
  - `clarification_msg` is the human-readable question to send back to the user.
  - `needs_clarification` is the routing flag checked by the conditional edge.
"""
from __future__ import annotations

from typing import Any

from typing_extensions import TypedDict

from app.models.schemas import ConversationTurn


class PRAState(TypedDict, total=False):
    """
    Shared mutable state threaded through every LangGraph node.

    `total=False` means every key is optional at construction time —
    LangGraph merges partial updates, so nodes only need to return the
    keys they actually modified.

    Fields
    ------
    session_id : str
        PostgreSQL session UUID.  Empty string for stateless / anonymous calls.

    raw_question : str
        The original question exactly as typed by the user.
        Never overwritten after initialisation.

    rewritten_question : str
        After context_node runs Stage 1 pronoun/co-reference resolution.
        E.g. "What rules apply to it?" → "What rules apply to ISO 20022?"
        Equals raw_question when no rewrite was needed.

    is_followup : bool
        True when context_node determined this question continues a prior turn
        (detected via pronoun presence or semantic similarity to history).

    intent : str
        Classified by intent_node (Stage 2).
        One of: "definition" | "list" | "comparison" | "exploratory" | "vague"

    entities_mentioned : list[str]
        PRA entity labels extracted by entity_cache.find_entities() in context_node.
        E.g. ["SEPA Credit Transfer", "Fraud Check"]
        Used for pronoun resolution and to pre-filter SPARQL queries.

    needs_clarification : bool
        Set by clarify_node (Stage 3).
        True  → graph routes to END, streaming a clarification event.
        False → graph proceeds to retrieve_node.

    clarification_msg : str
        Human-readable question to present to the user when needs_clarification=True.
        E.g. "Could you clarify which payment scheme you're asking about?"

    evidence : list[Any]
        Raw retrieval results from retrieve_node (Stage 4).
        Mixed list of SparqlEvidence | FtsEvidence | SimilarityEvidence objects.

    retrieval_modes : list[str]
        Which retrieval modes returned results, e.g. ["sparql", "fts"].
        Populated by retrieve_node alongside `evidence`.

    validated_evidence : list[Any]
        Filtered subset of `evidence` that passed Stage 5 confidence threshold.
        Falls back to full `evidence` list when nothing clears the threshold.

    has_sufficient : bool
        True when validate_node found at least one high-confidence evidence item.
        Used by answer_node to decide whether to add a "low confidence" caveat.

    answer : str
        The final LLM-generated answer from answer_node (Stage 6).
        Starts as "" and is populated by streaming accumulation.

    confidence : float
        Estimated answer confidence in [0.0, 1.0].
        Computed by answer_node._estimate_confidence() after streaming completes.

    conversation_history : list[ConversationTurn]
        Last N turns loaded from PostgreSQL by chat.py before graph entry.
        Read-only inside the graph — persist_node writes new turns to DB separately.
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    session_id:           str                    # "" for stateless calls

    # ── Input ─────────────────────────────────────────────────────────────────
    raw_question:         str                    # original user text (immutable)
    conversation_history: list[ConversationTurn] # loaded from DB before graph entry

    # ── Stage 1: Context resolution ───────────────────────────────────────────
    rewritten_question:   str                    # after pronoun/co-ref resolution
    is_followup:          bool                   # True = continues prior turn
    entities_mentioned:   list[str]              # PRA entity labels found in text

    # ── Stage 2: Intent classification ────────────────────────────────────────
    intent:               str                    # definition|list|comparison|exploratory|vague

    # ── Stage 3: Clarification gate ───────────────────────────────────────────
    needs_clarification:  bool                   # routing flag → END if True
    clarification_msg:    str                    # question to ask user

    # ── Stage 4: Retrieval ────────────────────────────────────────────────────
    evidence:             list[Any]              # raw SparqlEvidence|FtsEvidence|SimilarityEvidence
    retrieval_modes:      list[str]              # ["sparql", "fts", "similarity"]

    # ── Stage 5: Evidence validation ──────────────────────────────────────────
    validated_evidence:   list[Any]              # filtered by confidence_threshold
    has_sufficient:       bool                   # True = at least one item passed

    # ── Stage 6: Answer generation ────────────────────────────────────────────
    answer:               str                    # full LLM response
    confidence:           float                  # 0.0 – 1.0


# ── Safe default factory ───────────────────────────────────────────────────────

def make_initial_state(
    *,
    session_id: str = "",
    raw_question: str,
    conversation_history: list[ConversationTurn] | None = None,
) -> PRAState:
    """
    Build a fully-populated initial PRAState with all fields set to safe defaults.

    Called by chat.py before invoking the LangGraph graph:

        state = make_initial_state(
            session_id=request.session_id or "",
            raw_question=request.question,
            conversation_history=history,
        )
        async for chunk in graph.astream(state):
            ...

    Using a factory (rather than relying on TypedDict defaults) ensures that
    every node can safely read any key without a KeyError, even on the first node
    in the chain before earlier nodes have had a chance to populate the field.
    """
    return PRAState(
        # Identity
        session_id=session_id,

        # Input
        raw_question=raw_question,
        conversation_history=conversation_history or [],

        # Stage 1 — populated by context_node
        rewritten_question=raw_question,     # default = unchanged
        is_followup=False,
        entities_mentioned=[],

        # Stage 2 — populated by intent_node
        intent="exploratory",

        # Stage 3 — populated by clarify_node
        needs_clarification=False,
        clarification_msg="",

        # Stage 4 — populated by retrieve_node
        evidence=[],
        retrieval_modes=[],

        # Stage 5 — populated by validate_node
        validated_evidence=[],
        has_sufficient=False,

        # Stage 6 — populated by answer_node
        answer="",
        confidence=0.0,
    )
