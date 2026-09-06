"""
LangGraph Graph Assembly for PRA Chatbot
=========================================
Builds and compiles the PRAState graph from nodes + edges.

Graph topology:
  START
    │
    ▼
  load_history
    │
    ▼
  resolve_context
    │
    ▼
  classify_intent
    │
    ▼
  clarification_gate ──needs_clarification=True──► clarification_end ──► END
    │ False
    ▼
  retrieve
    │
    ▼
  validate_evidence ──has_sufficient=False──► clarification_end ──► END
    │ True
    ▼
  generate_answer
    │
    ▼
  save_to_db
    │
    ▼
  END

The compiled graph is a module-level singleton (build_graph() is called once
at startup).  chat.py imports `get_graph()` to obtain the compiled instance.

Streaming:
  graph.astream(state, config) yields partial state dicts after each node.
  chat.py watches for specific keys to emit SSE events:
    - after resolve_context  → emit "pipeline" event
    - after clarification_end → emit "clarification" event + return early
    - after retrieve         → emit "retrieval" event
    - token-by-token         → answer_node streams via a separate generator
    - after save_to_db       → emit "done" event
"""
from __future__ import annotations

import functools

from langgraph.graph import END, START, StateGraph

from app.orchestration.langgraph.edges import (
    TO_CLARIFICATION,
    TO_GENERATE,
    TO_RETRIEVE,
    route_after_clarification_gate,
    route_after_validate,
)
from app.orchestration.langgraph.nodes import (
    node_classify_intent,
    node_clarification_gate,
    node_generate_answer,
    node_load_history,
    node_resolve_context,
    node_retrieve,
    node_save_to_db,
    node_validate_evidence,
)
from app.orchestration.langgraph.state import PRAState
from app.core.log_config import get_logger

logger = get_logger(__name__)

# ── Node name constants (avoid magic strings) ──────────────────────────────────

N_LOAD_HISTORY         = "load_history"
N_RESOLVE_CONTEXT      = "resolve_context"
N_CLASSIFY_INTENT      = "classify_intent"
N_CLARIFICATION_GATE   = "clarification_gate"
N_CLARIFICATION_END    = TO_CLARIFICATION          # "clarification"
N_RETRIEVE             = TO_RETRIEVE               # "retrieve"
N_VALIDATE             = "validate_evidence"
N_GENERATE             = TO_GENERATE               # "generate_answer"
N_SAVE_DB              = "save_to_db"


# ── Clarification passthrough node ────────────────────────────────────────────
# LangGraph requires every branch destination to be a real node.
# This node does nothing — it just acts as a named waypoint so the
# conditional edges have a concrete target.  chat.py detects the
# "clarification" key in the streamed state and emits the SSE event.

async def _node_clarification_end(state: PRAState) -> dict:
    """
    Passthrough node — signals that clarification is needed.
    Writes nothing; the `clarification_msg` key is already in state from
    either node_clarification_gate or node_validate_evidence.
    """
    logger.info(
        "clarification_end",
        msg_preview=state.get("clarification_msg", "")[:80],
    )
    return {}


# ── Graph builder ─────────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    """
    Assemble and compile the PRA LangGraph StateGraph.

    Returns a compiled graph that can be called with:
      async for chunk in graph.astream(initial_state, config):
          ...

    The graph is deterministic — same state always produces same routing.
    All nodes are async; LangGraph runs them sequentially (no parallel nodes).
    """
    graph = StateGraph(PRAState)

    # ── Register nodes ────────────────────────────────────────────────────────
    graph.add_node(N_LOAD_HISTORY,       node_load_history)
    graph.add_node(N_RESOLVE_CONTEXT,    node_resolve_context)
    graph.add_node(N_CLASSIFY_INTENT,    node_classify_intent)
    graph.add_node(N_CLARIFICATION_GATE, node_clarification_gate)
    graph.add_node(N_CLARIFICATION_END,  _node_clarification_end)
    graph.add_node(N_RETRIEVE,           node_retrieve)
    graph.add_node(N_VALIDATE,           node_validate_evidence)
    graph.add_node(N_GENERATE,           node_generate_answer)
    graph.add_node(N_SAVE_DB,            node_save_to_db)

    # ── Linear edges (always run in order) ────────────────────────────────────
    graph.add_edge(START,               N_LOAD_HISTORY)
    graph.add_edge(N_LOAD_HISTORY,      N_RESOLVE_CONTEXT)
    graph.add_edge(N_RESOLVE_CONTEXT,   N_CLASSIFY_INTENT)
    graph.add_edge(N_CLASSIFY_INTENT,   N_CLARIFICATION_GATE)

    # ── Conditional edge 1: after clarification_gate ──────────────────────────
    #   needs_clarification=True  → N_CLARIFICATION_END
    #   needs_clarification=False → N_RETRIEVE
    graph.add_conditional_edges(
        N_CLARIFICATION_GATE,
        route_after_clarification_gate,
        {
            TO_CLARIFICATION: N_CLARIFICATION_END,
            TO_RETRIEVE:      N_RETRIEVE,
        },
    )

    # ── Linear edge: retrieve → validate ──────────────────────────────────────
    graph.add_edge(N_RETRIEVE, N_VALIDATE)

    # ── Conditional edge 2: after validate_evidence ───────────────────────────
    #   has_sufficient=False → N_CLARIFICATION_END
    #   has_sufficient=True  → N_GENERATE
    graph.add_conditional_edges(
        N_VALIDATE,
        route_after_validate,
        {
            TO_CLARIFICATION: N_CLARIFICATION_END,
            TO_GENERATE:      N_GENERATE,
        },
    )

    # ── Clarification end → END ───────────────────────────────────────────────
    # Both clarification branches converge here and stop.
    graph.add_edge(N_CLARIFICATION_END, END)

    # ── Linear tail: generate → save → END ───────────────────────────────────
    graph.add_edge(N_GENERATE, N_SAVE_DB)
    graph.add_edge(N_SAVE_DB,  END)

    compiled = graph.compile()
    logger.info("pra_graph_compiled")
    return compiled


# ── Module-level singleton ────────────────────────────────────────────────────

@functools.lru_cache(maxsize=1)
def get_graph():
    """
    Return the compiled PRA graph (built once, cached forever).

    Called by:
      - chat.py  → `graph = get_graph()` at module level
      - main.py  → `get_graph()` at startup to pre-compile
      - tests    → `get_graph()` directly

    Thread-safe: lru_cache is thread-safe in CPython; FastAPI is single-process.
    """
    logger.info("building_pra_graph")
    return build_graph()
