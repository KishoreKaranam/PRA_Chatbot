"""Chat endpoint – wires up retrieval + answer generation."""
from fastapi import APIRouter, HTTPException
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

# Module-level service instances (lazy-initialised per request via DI)
_answer_svc: AnswerGenerationService | None = None


def _get_answer_service() -> AnswerGenerationService:
    global _answer_svc
    if _answer_svc is None:
        _answer_svc = AnswerGenerationService()
    return _answer_svc


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

    db_client = get_graphdb_client()
    sparql_svc = SparqlRetrievalService(db_client)
    fts_svc = FtsRetrievalService(db_client)
    sim_svc = SimilarityRetrievalService(db_client)
    orchestrator = RetrievalOrchestrator(sparql_svc, fts_svc, sim_svc)
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
        # Return retrieval evidence even if LLM fails
        answer = (
            "⚠️  Answer generation failed. Please check your OPENAI_API_KEY or model configuration.\n\n"
            f"Error: {exc}"
        )
        confidence = None

    warning: str | None = None
    if not modes_used:
        warning = "No relevant information was found in the knowledge graph."

    # Strip evidence if user toggled show_raw_evidence off
    returned_evidence = evidence if instructions.show_raw_evidence else []

    return ChatResponse(
        question=request.question,
        answer=answer,
        retrieval_modes_used=modes_used,
        evidence=returned_evidence,
        confidence=confidence,
        warning=warning,
    )
