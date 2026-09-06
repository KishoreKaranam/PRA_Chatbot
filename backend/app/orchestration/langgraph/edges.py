"""
LangGraph Conditional Edge Functions for PRA Chatbot
=====================================================
These are pure routing functions — they read state and return a node name string.
LangGraph uses the returned string to look up the next node in the graph.

Two conditional edges are needed:

  After node_clarification_gate:
    needs_clarification = True  →  "clarification"   (→ END in graph.py)
    needs_clarification = False →  "retrieve"

  After node_validate_evidence:
    has_sufficient = False      →  "clarification"   (→ END in graph.py)
    has_sufficient = True       →  "generate_answer"

Both functions share the same destination name "clarification" so graph.py
only needs one END mapping for that branch.

Design rules:
  - Functions are synchronous (LangGraph supports sync routing functions).
  - Functions never raise — missing state keys fall back to safe defaults.
  - Return values are plain string literals that match node names in graph.py.
"""
from __future__ import annotations

from typing import Literal

from app.orchestration.langgraph.state import PRAState

# String literals used as node / branch names in graph.py
TO_CLARIFICATION = "clarification"
TO_RETRIEVE      = "retrieve"
TO_GENERATE      = "generate_answer"


def route_after_clarification_gate(
    state: PRAState,
) -> Literal["clarification", "retrieve"]:
    """
    Called by the conditional edge after node_clarification_gate.

    Decision:
      state.needs_clarification = True  →  "clarification"  (graph routes to END)
      state.needs_clarification = False →  "retrieve"        (continue pipeline)

    Triggered by:
      - intent == "vague" with no conversation history

    Example state values that route to "clarification":
      {"intent": "vague", "conversation_history": [], "needs_clarification": True}

    Example state values that route to "retrieve":
      {"intent": "definition", "needs_clarification": False}
      {"intent": "vague",      "conversation_history": [<turns>], "needs_clarification": False}
    """
    if state.get("needs_clarification", False):
        return TO_CLARIFICATION
    return TO_RETRIEVE


def route_after_validate(
    state: PRAState,
) -> Literal["clarification", "generate_answer"]:
    """
    Called by the conditional edge after node_validate_evidence.

    Decision:
      state.has_sufficient = False →  "clarification"   (graph routes to END)
                                       clarification_msg = "could not find evidence, try rephrasing"
      state.has_sufficient = True  →  "generate_answer" (continue to Claude Sonnet)

    Triggered by:
      - All evidence items fell below confidence_threshold
      - Retrieval returned zero results

    Example state values that route to "clarification":
      {"has_sufficient": False, "needs_clarification": True,
       "clarification_msg": "I searched the PRA knowledge graph..."}

    Example state values that route to "generate_answer":
      {"has_sufficient": True, "validated_evidence": [<SparqlEvidence>, ...]}
    """
    if not state.get("has_sufficient", False):
        return TO_CLARIFICATION
    return TO_GENERATE
