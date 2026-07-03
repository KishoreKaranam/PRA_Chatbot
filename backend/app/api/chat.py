"""Chat endpoint – wires up retrieval + answer generation."""
import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from app.models.schemas import ChatRequest, ChatResponse
from app.graphdb.client import get_graphdb_client
from app.services.sparql_service import SparqlRetrievalService
from app.services.fts_service import FtsRetrievalService
from app.services.similarity_service import SimilarityRetrievalService
from app.services.orchestrator import RetrievalOrchestrator
from app.services.answer_service import AnswerGenerationService
from app.services.config_service import get_config_service
from app.core.log_config import get_logger

router = APIRouter()
logger = get_logger(__name__)

# Module-level cached service instances
_answer_svc: AnswerGenerationService | None = None
_orchestrator: RetrievalOrchestrator | None = None


def _get_answer_service() -> AnswerGenerationService:
    global _answer_svc
    if _answer_svc is None:
        _answer_svc = AnswerGenerationService()
    return _answer_svc


def _get_orchestrator() -> RetrievalOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        db_client = get_graphdb_client()
        sparql_svc = SparqlRetrievalService(db_client)
        fts_svc = FtsRetrievalService(db_client)
        sim_svc = SimilarityRetrievalService(db_client)
        _orchestrator = RetrievalOrchestrator(sparql_svc, fts_svc, sim_svc)
    return _orchestrator


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """
    Main chat endpoint.

    1. Resolves agent instructions (request-level or server config).
    2. Runs retrieval orchestration.
    3. Generates a grounded LLM answer.
    4. Returns answer + evidence.
    """
    instructions = request.agent_instructions or get_config_service().get()

    orchestrator = _get_orchestrator()
    answer_svc = _get_answer_service()

    try:
        modes_used, evidence = await orchestrator.retrieve(request.question, instructions)
    except Exception as exc:
        logger.error("retrieval_failed", error=str(exc))
        raise HTTPException(status_code=502, detail=f"Retrieval error: {exc}") from exc

    try:
        answer, confidence = await answer_svc.generate(
            request.question, evidence, modes_used, instructions
        )
    except Exception as exc:
        logger.error("answer_generation_failed", error=str(exc))
        answer = (
            "Answer generation failed. Please check your API key or model configuration.\n\n"
            f"Error: {exc}"
        )
        confidence = None

    warning: str | None = None
    if not modes_used:
        warning = "No relevant information was found in the knowledge graph."

    returned_evidence = evidence if instructions.show_raw_evidence else []

    return ChatResponse(
        question=request.question,
        answer=answer,
        retrieval_modes_used=modes_used,
        evidence=returned_evidence,
        confidence=confidence,
        warning=warning,
    )


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """
    Streaming chat endpoint using Server-Sent Events (SSE).

    Sends events:
      - event: retrieval  data: {modes_used, evidence}
      - event: token      data: {text: "..."}
      - event: done       data: {confidence}
    """
    instructions = request.agent_instructions or get_config_service().get()

    orchestrator = _get_orchestrator()
    answer_svc = _get_answer_service()

    async def event_generator():
        # Phase 1: Retrieval
        try:
            modes_used, evidence = await orchestrator.retrieve(request.question, instructions)
        except Exception as exc:
            yield f"event: error\ndata: {json.dumps({'detail': str(exc)})}\n\n"
            return

        # Send retrieval results
        returned_evidence = evidence if instructions.show_raw_evidence else []
        retrieval_payload = {
            "retrieval_modes_used": modes_used,
            "evidence": _serialize_evidence(returned_evidence),
            "warning": "No relevant information was found in the knowledge graph." if not modes_used else None,
        }
        yield f"event: retrieval\ndata: {json.dumps(retrieval_payload, default=str)}\n\n"

        # Phase 2: Stream LLM tokens
        try:
            async for token in answer_svc.generate_stream(
                request.question, evidence, modes_used, instructions
            ):
                yield f"event: token\ndata: {json.dumps({'text': token})}\n\n"
        except Exception as exc:
            yield f"event: error\ndata: {json.dumps({'detail': str(exc)})}\n\n"
            return

        # Phase 3: Done
        confidence = answer_svc._estimate_confidence(evidence, modes_used)
        yield f"event: done\ndata: {json.dumps({'confidence': confidence})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _serialize_evidence(evidence: list) -> list:
    """Convert evidence objects to JSON-serializable dicts."""
    result = []
    for ev in evidence:
        if hasattr(ev, "model_dump"):
            result.append(ev.model_dump())
        elif hasattr(ev, "dict"):
            result.append(ev.dict())
        else:
            result.append(str(ev))
    return result
