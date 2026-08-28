"""
Chat endpoint – FastAPI routes wired to the LangGraph PRA pipeline.

Streaming endpoint (/chat/stream):
  Drives the graph with graph.astream() and maps state-key changes
  to SSE events in real time:

    Node completing...        SSE event emitted
    ─────────────────────     ─────────────────────────────────────────────
    resolve_context           pipeline  {rewritten_question, is_followup, intent}
    clarification_end         clarification {message}  → generator returns early
    validate_evidence         retrieval {modes_used, evidence, warning}
    generate_answer (tokens)  token {text}  (separate streaming call)
    save_to_db                done  {confidence, session_id}

Non-streaming endpoint (/chat):
  Drives the graph with graph.ainvoke() and returns a single ChatResponse.
  Used by integration tests and the legacy frontend path.
"""
from __future__ import annotations

import json
from typing import Any, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.persistence.postgres.database import get_db
from app.orchestration.langgraph.graph import get_graph
from app.orchestration.langgraph.nodes import _get_answer_service, _get_orchestrator
from app.orchestration.langgraph.state import PRAState, make_initial_state
from app.models.schemas import AgentInstructions, ChatRequest, ChatResponse, ConversationTurn, Neo4jGraphEvidence
from app.infrastructure.configuration.config_service import get_config_service
from app.core.log_config import get_logger

router = APIRouter()
logger = get_logger(__name__)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _sse(event: str, data: Any) -> str:
    """Format a single Server-Sent Event frame."""
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _serialize_evidence(evidence: list) -> list:
    """Convert evidence ORM objects to JSON-serializable dicts."""
    result = []
    for ev in evidence:
        if hasattr(ev, "model_dump"):
            result.append(ev.model_dump())
        elif hasattr(ev, "dict"):
            result.append(ev.dict())
        else:
            result.append(str(ev))
    return result


def _build_initial_state(request: ChatRequest) -> PRAState:
    """
    Build the initial PRAState from the incoming request.
    conversation_history starts empty — node_load_history fills it from DB.
    """
    return make_initial_state(
        session_id=request.session_id or "",
        raw_question=request.question,
        # Inline history used only when session_id is absent (stateless / legacy)
        conversation_history=request.conversation_history if not request.session_id else [],
    )


# ── Non-streaming endpoint ─────────────────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    """
    Non-streaming chat endpoint powered by the LangGraph pipeline.

    Runs graph.ainvoke() — waits for the full graph to complete then
    returns a single ChatResponse JSON.

    Used by: integration tests, curl debugging, legacy /chat callers.
    """
    graph = get_graph()
    initial_state = _build_initial_state(request)
    instructions: AgentInstructions = request.agent_instructions or get_config_service().get()

    try:
        # Pass db as a LangGraph config value so nodes can receive it
        final_state: PRAState = await graph.ainvoke(
            initial_state,
            config={"configurable": {"db": db, "instructions": instructions}},
        )
    except Exception as exc:
        logger.error("graph_invoke_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Pipeline error: {exc}") from exc

    # Clarification branch — graph ended early, no answer generated
    if final_state.get("needs_clarification"):
        return ChatResponse(
            question=request.question,
            answer=final_state.get("clarification_msg", "Could you please clarify your question?"),
            clarification_needed=final_state.get("clarification_msg"),
            rewritten_question=final_state.get("rewritten_question", request.question),
            is_followup=final_state.get("is_followup", False),
            intent=final_state.get("intent", "vague"),
            retrieval_modes_used=[],
            evidence=[],
            confidence=None,
            session_id=request.session_id,
        )

    evidence = final_state.get("validated_evidence", [])
    modes_used = final_state.get("retrieval_modes", [])
    returned_evidence = evidence if instructions.show_raw_evidence else []

    return ChatResponse(
        question=request.question,
        rewritten_question=final_state.get("rewritten_question", request.question),
        is_followup=final_state.get("is_followup", False),
        intent=final_state.get("intent", "exploratory"),
        answer=final_state.get("answer", ""),
        retrieval_modes_used=modes_used,
        evidence=returned_evidence,
        confidence=final_state.get("confidence"),
        warning="No relevant information was found in the knowledge graph." if not modes_used else None,
        session_id=request.session_id,
    )


# ── Streaming endpoint ─────────────────────────────────────────────────────────

@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Streaming chat endpoint — drives the LangGraph graph with astream()
    and maps each node's state output to SSE events in real time.

    POST body:  { question, session_id?, agent_instructions? }

    SSE events (in order):
      pipeline       {rewritten_question, is_followup, intent}
      clarification  {message}           ← graph ended early (vague / no evidence)
      retrieval      {retrieval_modes_used, evidence, warning}
      token          {text}              ← one per streamed token
      done           {confidence, session_id}
      error          {detail}
    """
    graph = get_graph()
    initial_state = _build_initial_state(request)
    instructions: AgentInstructions = request.agent_instructions or get_config_service().get()
    answer_svc = _get_answer_service()

    async def event_generator() -> AsyncGenerator[str, None]:
        # ── Run the graph (all nodes except answer streaming) ─────────────────
        # astream() yields a dict of {node_name: partial_state} after each node.
        # We accumulate state as nodes complete and emit SSE at the right moments.

        accumulated: PRAState = dict(initial_state)  # type: ignore[assignment]
        pipeline_emitted = False
        retrieval_emitted = False

        try:
            async for chunk in graph.astream(
                initial_state,
                config={"configurable": {"db": db, "instructions": instructions}},
                stream_mode="updates",   # yields {node_name: {changed_keys}}
            ):
                # chunk = {"node_name": {key: value, ...}}
                for node_name, node_output in chunk.items():
                    # Merge into accumulated state
                    # LangGraph represents a node with no state changes as None.
                    # Treat it as an empty update instead of passing None to
                    # dict.update(), which raises "'NoneType' object is not iterable".
                    accumulated.update(node_output or {})

                    # ── After resolve_context: emit pipeline event ─────────────
                    if node_name == "resolve_context" and not pipeline_emitted:
                        pipeline_emitted = True
                        yield _sse("pipeline", {
                            "rewritten_question": accumulated.get("rewritten_question", request.question),
                            "is_followup":        accumulated.get("is_followup", False),
                            "intent":             accumulated.get("intent", "exploratory"),
                        })

                    # ── After classify_intent: update intent in pipeline event ─
                    # (intent may have changed since resolve_context ran before it)
                    elif node_name == "classify_intent" and pipeline_emitted:
                        yield _sse("pipeline", {
                            "rewritten_question": accumulated.get("rewritten_question", request.question),
                            "is_followup":        accumulated.get("is_followup", False),
                            "intent":             accumulated.get("intent", "exploratory"),
                        })

                    # ── After clarification_end: emit clarification + stop ─────
                    elif node_name == "clarification":
                        yield _sse("clarification", {
                            "message": accumulated.get("clarification_msg", "Could you clarify your question?"),
                        })
                        return   # graph already at END — stop generator

                    # ── After validate_evidence: emit retrieval event ──────────
                    elif node_name == "validate_evidence" and not retrieval_emitted:
                        # Check if validate routed to clarification (no evidence)
                        if accumulated.get("needs_clarification"):
                            yield _sse("clarification", {
                                "message": accumulated.get("clarification_msg", ""),
                            })
                            return

                        retrieval_emitted = True
                        evidence = accumulated.get("validated_evidence", [])
                        modes = accumulated.get("retrieval_modes", [])
                        returned = evidence if instructions.show_raw_evidence else []
                        yield _sse("retrieval", {
                            "retrieval_modes_used": modes,
                            "evidence": _serialize_evidence(returned),
                            "warning": "No relevant information was found in the knowledge graph." if not modes else None,
                        })

        except Exception as exc:
            logger.error("graph_stream_failed", error=str(exc))
            yield _sse("error", {"detail": str(exc)})
            return

        # ── If graph ended on clarification branch (no answer) ─────────────────
        if accumulated.get("needs_clarification") and not retrieval_emitted:
            yield _sse("clarification", {
                "message": accumulated.get("clarification_msg", "Could you clarify your question?"),
            })
            return

        # ── Stream answer tokens separately (bypasses graph for true streaming) ─
        # node_generate_answer already ran non-streaming inside the graph above.
        # For the stream endpoint we re-run the answer generation in streaming
        # mode here so the user sees tokens in real time.
        rewritten_q   = accumulated.get("rewritten_question", request.question)
        validated_ev  = accumulated.get("validated_evidence", [])
        modes_used    = accumulated.get("retrieval_modes", [])
        history       = accumulated.get("conversation_history", [])
        intent        = accumulated.get("intent", "exploratory")
        is_followup   = accumulated.get("is_followup", False)
        full_answer   = ""

        # If graph already produced an answer (non-streaming path ran), stream it
        # character-by-character to keep SSE events consistent.
        existing_answer: str = accumulated.get("answer", "")

        if existing_answer:
            # Answer came from node_generate_answer — re-emit as tokens
            # (chunk into ~20-char pieces to simulate streaming)
            chunk_size = 20
            for i in range(0, len(existing_answer), chunk_size):
                token = existing_answer[i:i + chunk_size]
                full_answer += token
                yield _sse("token", {"text": token})
        else:
            # Generate fresh streaming answer
            try:
                async for token in answer_svc.generate_stream(
                    rewritten_q, validated_ev, modes_used, instructions,
                    history=history, intent=intent, is_followup=is_followup,
                ):
                    full_answer += token
                    yield _sse("token", {"text": token})
            except Exception as exc:
                logger.error("answer_stream_failed", error=str(exc))
                yield _sse("error", {"detail": str(exc)})
                return

        confidence = answer_svc._estimate_confidence(validated_ev, modes_used)
        yield _sse("done", {
            "confidence": confidence,
            "session_id": request.session_id,
        })

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection":    "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
