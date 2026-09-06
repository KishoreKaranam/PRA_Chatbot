"""
LangGraph Nodes for PRA Chatbot
================================
Eight pure async functions — each takes PRAState and returns a partial dict.
LangGraph merges returned keys back into the shared state automatically.

Node execution order (controlled by graph.py edges):
  node_load_history
      ↓
  node_resolve_context   (3-layer: regex → entity cache → Claude Haiku)
      ↓
  node_classify_intent   (pure Python, zero LLM cost)
      ↓
  node_clarification_gate ──needs_clarification=True──► END (clarification event)
      ↓
  node_retrieve
      ↓
  node_validate_evidence ──has_sufficient=False──► needs_clarification=True ──► END
      ↓
  node_generate_answer   (Claude Sonnet, streaming in graph.py)
      ↓
  node_save_to_db        (fire-and-forget DB writes)

Design contract:
  - Every node is a plain `async def` that accepts PRAState.
  - Nodes return ONLY the keys they modified (partial dict).
  - Nodes never raise — all exceptions are caught and logged; safe defaults returned.
  - No node holds state between calls; all dependencies are module-level singletons.
"""
from __future__ import annotations

import json
import re
from typing import Any

import anthropic
import httpx
from langchain_core.runnables import RunnableConfig
from app.core.log_config import get_logger
from app.core.settings import get_settings
from app.infrastructure.persistence.postgres.entity_cache import find_entities
from app.infrastructure.persistence.postgres.session_store import load_history, save_retrieval_log, save_turn
from app.orchestration.langgraph.state import PRAState
from app.models.schemas import (
    AgentInstructions,
    ConversationTurn,
    FtsEvidence,
    SimilarityEvidence,
    Neo4jGraphEvidence,
    SparqlEvidence,
)
from app.infrastructure.llm.answer_service import AnswerGenerationService
from app.infrastructure.configuration.config_service import get_config_service
from app.application.retrieval.orchestrator import RetrievalOrchestrator
from app.prompts.conversation import (
    build_insufficient_evidence_message,
    build_node_clarification_message,
    build_node_context_resolution_prompt,
)

logger = get_logger(__name__)

# ── Module-level singletons (initialised once, reused across requests) ─────────

_answer_svc: AnswerGenerationService | None = None
_orchestrator: RetrievalOrchestrator | None = None
_haiku_client: anthropic.AsyncAnthropic | None = None
_haiku_client_azure: Any | None = None

MAX_HISTORY_TURNS = 6       # sliding window — 3 user+assistant pairs
PRONOUN_RE = re.compile(
    r"\b(it|its|they|them|their|those|that|this|these|he|she|"
    r"which|the function|the domain|the rule|the scheme|the activity)\b",
    re.IGNORECASE,
)


def _get_answer_service() -> AnswerGenerationService:
    global _answer_svc
    if _answer_svc is None:
        _answer_svc = AnswerGenerationService()
    return _answer_svc


def _get_orchestrator() -> RetrievalOrchestrator:
    """Lazy-import to avoid circular imports at module load time."""
    global _orchestrator
    if _orchestrator is None:
        from app.infrastructure.knowledge_graph.neo4j.client import Neo4jClient
        from app.infrastructure.retrieval.full_text.service import FtsRetrievalService
        from app.infrastructure.retrieval.vector.service import SimilarityRetrievalService
        from app.infrastructure.retrieval.neo4j.graph_service import Neo4jGraphRetrievalService
        from app.infrastructure.retrieval.neo4j.full_text_service import Neo4jFtsRetrievalService
        from app.infrastructure.retrieval.neo4j.vector_service import Neo4jVectorRetrievalService
        settings = get_settings()
        retrieval_backend = settings.retrieval_backend.strip().lower()
        neo4j_client = Neo4jClient()
        if retrieval_backend == "neo4j":
            graph_client = None
            sparql_service = None
        else:
            from app.infrastructure.knowledge_graph.graphdb.client import get_graphdb_client
            from app.infrastructure.retrieval.sparql.service import SparqlRetrievalService

            graph_client = get_graphdb_client()
            sparql_service = SparqlRetrievalService(graph_client)

        fts_service = _build_fts_service(
            graph_client,
            neo4j_client,
            FtsRetrievalService,
            Neo4jFtsRetrievalService,
        )
        vector_service = _build_vector_service(
            graph_client,
            neo4j_client,
            SimilarityRetrievalService,
            Neo4jVectorRetrievalService,
        )
        _orchestrator = RetrievalOrchestrator(
            sparql_service,
            Neo4jGraphRetrievalService(neo4j_client),
            fts_service,
            vector_service,
        )
    return _orchestrator


def _build_fts_service(
    graph_client,
    neo4j_client,
    legacy_service_cls,
    neo4j_service_cls,
):
    """Select the configured FTS implementation while keeping one FTS API."""
    settings = get_settings()
    backend = settings.fts_backend.strip().lower()
    if backend == "neo4j":
        logger.info("fts_backend_selected", fts_backend="neo4j")
        return neo4j_service_cls(neo4j_client)

    logger.info("fts_backend_selected", fts_backend="legacy")
    return legacy_service_cls(graph_client)


def _build_vector_service(
    graph_client,
    neo4j_client,
    legacy_service_cls,
    neo4j_service_cls,
):
    """
    Select the vector implementation while preserving one retrieve API.

    Preference order:
      1. Neo4j vector index  (neo4j_service_cls) — if VECTOR_BACKEND=neo4j AND
         the index actually exists in the running DB.
      2. In-memory NumPy + Azure/OpenAI embeddings (legacy_service_cls) — used
         when the Neo4j index is absent.  Loads all node texts once at startup,
         embeds them via Azure, and runs cosine similarity in RAM.
    """
    settings = get_settings()
    backend = settings.vector_backend.strip().lower()

    if backend == "neo4j":
        # This selector is synchronous but is called while FastAPI's event
        # loop is already running. Do not block it with run_until_complete;
        # that creates an un-awaited coroutine and incorrectly selects legacy.
        logger.info("vector_backend_selected", vector_backend="neo4j_index")
        service = neo4j_service_cls(neo4j_client)
        # Keep Neo4j as the primary backend, but create the legacy NumPy
        # service only if a real Neo4j vector query fails. This avoids manual
        # .env changes and avoids building duplicate embeddings on startup.
        if hasattr(service, "set_fallback_factory"):
            service.set_fallback_factory(lambda: legacy_service_cls())
        return service

    if backend == "neo4j":
        # Quick sync check — probe the index before committing
        import asyncio, neo4j as _neo4j_pkg

        async def _index_exists() -> bool:
            try:
                from app.infrastructure.knowledge_graph.neo4j.client import Neo4jClient as _C
                _c = _C()
                await _c.connect()
                rows = await _c.execute_read_query(
                    "SHOW INDEXES YIELD name, state "
                    "WHERE name = 'pra_embedding_index' AND state = 'ONLINE' "
                    "RETURN name"
                )
                await _c.close()
                return len(rows) > 0
            except Exception:
                return False

        try:
            exists = asyncio.get_event_loop().run_until_complete(_index_exists())
        except RuntimeError:
            # No running event loop at import time — default to in-memory
            exists = False

        if exists:
            logger.info("vector_backend_selected", vector_backend="neo4j_index")
            return neo4j_service_cls(neo4j_client)

        logger.info(
            "vector_backend_selected",
            vector_backend="in_memory_numpy",
            reason="pra_embedding_index not found in Neo4j — using Azure-backed NumPy index",
        )
        return legacy_service_cls()   # SimilarityRetrievalService — pulls from Neo4j + embeds via Azure

    logger.info("vector_backend_selected", vector_backend="azure_in_memory_numpy")
    return legacy_service_cls(graph_client)


def _get_haiku_client():
    """Return (client, model, provider) for the lightweight context-resolution call."""
    global _haiku_client, _haiku_client_azure
    settings = get_settings()
    provider = settings.llm_provider.lower()

    if provider == "azure_anthropic":
        if _haiku_client_azure is None:
            _haiku_client_azure = anthropic.AsyncAnthropic(
                api_key=settings.azure_ai_api_key,
                base_url=settings.azure_ai_endpoint.rstrip("/"),
                default_headers={"api-key": settings.azure_ai_api_key},
                default_query={"api-version": settings.azure_ai_api_version},
                http_client=httpx.AsyncClient(verify=False),
            )
        return _haiku_client_azure, settings.azure_ai_model, "azure_anthropic"

    if _haiku_client is None:
        _haiku_client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            http_client=httpx.AsyncClient(verify=False),
        )
    return _haiku_client, "claude-haiku-4-5", "anthropic"


def _format_history(history: list[ConversationTurn], max_turns: int = MAX_HISTORY_TURNS) -> str:
    lines: list[str] = []
    for turn in history[-(max_turns * 2):]:
        label = "User" if turn.role == "user" else "Assistant"
        lines.append(f"{label}: {turn.content}")
    return "\n".join(lines)


def _extract_text_from_content(content) -> str:
    """
    Extract answer text from an Anthropic response's content blocks.

    Extended-thinking-capable models (e.g. claude-sonnet-4.5+) may return a
    `ThinkingBlock` (internal reasoning, has `.thinking` not `.text`) before
    the actual `TextBlock`. Skip any non-text blocks.
    """
    if not content:
        return ""
    texts = [block.text for block in content if getattr(block, "type", None) == "text"]
    return "".join(texts)


def _get_db(config: RunnableConfig | None):
    """Extract the AsyncSession from LangGraph config['configurable']['db']."""
    if config is None:
        return None
    return config.get("configurable", {}).get("db", None)


# ════════════════════════════════════════════════════════════════════════════════
# Node 1 — node_load_history
# ════════════════════════════════════════════════════════════════════════════════

async def node_load_history(state: PRAState, config: RunnableConfig) -> dict:
    """
    Load conversation history from PostgreSQL for this session.

    Skips silently if:
      - session_id is empty (stateless / anonymous call)
      - db not present in config (tests / direct graph calls)

    Writes: conversation_history
    """
    session_id = state.get("session_id", "")
    db = _get_db(config)
    if not session_id or db is None:
        logger.info("node_load_history_skipped", session_id=session_id)
        return {}

    try:
        raw = await load_history(db, session_id, limit=MAX_HISTORY_TURNS)
        history = [ConversationTurn(role=t["role"], content=t["content"]) for t in raw]
        logger.info("node_load_history_ok", session_id=session_id, turns=len(history))
        return {"conversation_history": history}
    except Exception as exc:
        logger.warning("node_load_history_failed", error=str(exc))
        return {}


# ════════════════════════════════════════════════════════════════════════════════
# Node 2 — node_resolve_context
# ════════════════════════════════════════════════════════════════════════════════

async def node_resolve_context(state: PRAState, config: RunnableConfig) -> dict:
    """
    3-layer context resolution — cheapest layer tried first.

    Layer A — Pure Python (FREE):
      No pronouns detected AND question > 4 words → skip straight to Layer B entity extraction.
      The question is self-contained; no rewrite needed.

    Layer B — Entity Cache Lookup (FREE, DB only):
      Always runs to extract PRA entities mentioned in the question.
      If a pronoun IS present and the last history turn mentions an entity,
      attempt local substitution (no LLM call needed).
      Confidence is based on exact entity label match.

    Layer C — Claude Haiku (PAID, ~$0.0001/call):
      Only invoked when:
        - A pronoun was found (ambiguous reference)
        - AND Layer B entity substitution was uncertain (< 0.8 confidence)
        - AND conversation history exists to resolve from

    Writes: rewritten_question, is_followup, entities_mentioned
    """
    raw = state.get("raw_question", "")
    history: list[ConversationTurn] = state.get("conversation_history", [])
    db = _get_db(config)

    entities_mentioned: list[str] = []
    rewritten = raw
    is_followup = False

    # ── Layer A: Does question need rewriting at all? ──────────────────────────
    words = raw.split()
    has_pronoun = bool(PRONOUN_RE.search(raw))
    self_contained = not has_pronoun and len(words) > 4

    if self_contained:
        logger.info("node_resolve_context_layer_a", rewritten=raw, is_followup=False)
        # Still run Layer B to extract entity names — used for DB logging
        if db is not None:
            try:
                matches = await find_entities(db, raw, top_k=5)
                entities_mentioned = [m["label"] for m in matches]
            except Exception as exc:
                logger.warning("node_resolve_context_entity_lookup_failed", error=str(exc))
        return {
            "rewritten_question": raw,
            "is_followup": False,
            "entities_mentioned": entities_mentioned,
        }

    # ── Layer B: Entity cache substitution ────────────────────────────────────
    entity_confidence = 0.0

    if db is not None:
        try:
            # Find entities in the raw question
            matches = await find_entities(db, raw, top_k=5)
            entities_mentioned = [m["label"] for m in matches]

            # If pronoun found and we have history, try resolving from history entities
            if has_pronoun and history:
                last_user_text = next(
                    (t.content for t in reversed(history) if t.role == "user"), ""
                )
                history_matches = await find_entities(db, last_user_text, top_k=3)

                if history_matches:
                    # Best entity from last user turn — use as pronoun substitute
                    best = history_matches[0]["label"]
                    # Substitute the first standalone pronoun with the entity label
                    candidate = PRONOUN_RE.sub(best, raw, count=1).strip()
                    entity_confidence = 0.85   # heuristic: exact entity match from history
                    rewritten = candidate
                    is_followup = True
                    logger.info(
                        "node_resolve_context_layer_b",
                        pronoun_replaced=True,
                        entity=best,
                        rewritten=rewritten,
                        confidence=entity_confidence,
                    )
        except Exception as exc:
            logger.warning("node_resolve_context_layer_b_failed", error=str(exc))

    # ── Layer C: Claude Haiku (only if still ambiguous) ───────────────────────
    if has_pronoun and entity_confidence < 0.8 and history:
        try:
            haiku, haiku_model, haiku_provider = _get_haiku_client()
            history_text = _format_history(history)
            prompt = build_node_context_resolution_prompt(history_text, raw)
            response = await haiku.messages.create(
                model=haiku_model,
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            raw_json = _extract_text_from_content(response.content).strip()
            match = re.search(r"\{.*\}", raw_json, re.DOTALL)
            if match:
                result = json.loads(match.group())
                is_followup = bool(result.get("is_followup", False))
                rewritten = result.get("rewritten", raw).strip() or raw
                logger.info(
                    "node_resolve_context_layer_c",
                    is_followup=is_followup,
                    rewritten=rewritten,
                )
        except Exception as exc:
            logger.warning("node_resolve_context_layer_c_failed", error=str(exc))
            # Fall through with whatever Layer B produced

    return {
        "rewritten_question": rewritten,
        "is_followup": is_followup,
        "entities_mentioned": entities_mentioned,
    }


# ════════════════════════════════════════════════════════════════════════════════
# Node 3 — node_classify_intent
# ════════════════════════════════════════════════════════════════════════════════

async def node_classify_intent(state: PRAState) -> dict:
    """
    Pure Python intent classification — zero LLM cost.

    Rules (evaluated in order — first match wins):
      len < 3 words                             → vague
      bare pronoun/reference with no noun       → vague
      starts with "what is/are/define/explain"  → definition
      contains "list/enumerate/all/how many"    → list
      contains "compare/vs/versus/difference"   → comparison
      everything else                           → exploratory

    Writes: intent 
    """
    q = state.get("rewritten_question", state.get("raw_question", "")).lower().strip()

    # Too short
    if len(q.split()) < 3:
        return {"intent": "vague"}

    # Bare follow-up with no real noun (still vague even after rewrite attempt)
    if re.match(
        r"^(what about|tell me more|and|also|how about)\s*(it|them|those|that|this)?\.?$",
        q,
    ):
        return {"intent": "vague"}

    # Definition
    if any(q.startswith(p) for p in (
        "what is", "what are", "define", "explain what",
        "describe what", "meaning of", "definition of",
    )):
        return {"intent": "definition"}

    # List
    if any(p in q for p in (
        "list ", "list all", "how many", "enumerate", "give me all",
        "show all", "what are all", "all the ",
    )):
        return {"intent": "list"}

    # Comparison
    if any(p in q for p in (
        "difference between", "compare", " vs ", " versus ",
        "how does x differ", "distinguish",
    )):
        return {"intent": "comparison"}

    return {"intent": "exploratory"}


# ════════════════════════════════════════════════════════════════════════════════
# Node 4 — node_clarification_gate
# ════════════════════════════════════════════════════════════════════════════════

async def node_clarification_gate(state: PRAState) -> dict:
    """
    Decide whether to ask the user for clarification.

    Triggers clarification when:
      - intent == "vague"
      - AND no conversation history exists to resolve context from

    When clarification IS needed:
      - needs_clarification = True   (edge in graph.py routes to END)
      - clarification_msg = human-readable question to send to user

    If history exists (follow-up on a vague turn), proceed without asking —
    context_node will already have attempted a rewrite.

    Writes: needs_clarification, clarification_msg
    """
    intent = state.get("intent", "exploratory")
    question = state.get("rewritten_question", state.get("raw_question", ""))
    history: list[ConversationTurn] = state.get("conversation_history", [])

    if intent != "vague":
        return {"needs_clarification": False, "clarification_msg": ""}

    # If we have history, the context node already tried to resolve it — proceed
    if history:
        return {"needs_clarification": False, "clarification_msg": ""}

    msg = build_node_clarification_message(question)
    logger.info("node_clarification_gate_triggered", question=question)
    return {"needs_clarification": True, "clarification_msg": msg}


# ════════════════════════════════════════════════════════════════════════════════
# Node 5 — node_retrieve
# ════════════════════════════════════════════════════════════════════════════════

async def node_retrieve(state: PRAState) -> dict:
    """
    Run hybrid retrieval (SPARQL + FTS + Similarity) using the existing
    RetrievalOrchestrator.  No changes to retrieval logic — the orchestrator
    is reused verbatim from pipeline_service.

    Writes: evidence, retrieval_modes
    """
    question = state.get("rewritten_question", state.get("raw_question", ""))

    # Build AgentInstructions from server config (same as chat.py)
    instructions: AgentInstructions = get_config_service().get()

    try:
        orchestrator = _get_orchestrator()
        modes_used, evidence = await orchestrator.retrieve(question, instructions)
        logger.info("node_retrieve_ok", modes=modes_used, evidence_count=len(evidence))
        return {"evidence": evidence, "retrieval_modes": modes_used}
    except Exception as exc:
        logger.error("node_retrieve_failed", error=str(exc))
        return {"evidence": [], "retrieval_modes": []}


# ════════════════════════════════════════════════════════════════════════════════
# Node 6 — node_validate_evidence
# ════════════════════════════════════════════════════════════════════════════════

async def node_validate_evidence(state: PRAState) -> dict:
    """
    Filter evidence below the configured confidence threshold.

    Validation rules per evidence type:
      SparqlEvidence    → keep if triple_count > 0
      FtsEvidence       → keep hits with score >= confidence_threshold
      SimilarityEvidence → keep hits with score >= confidence_threshold

    Neo4jGraphEvidence → keep if result_count > 0
    If nothing passes (has_sufficient = False):
      - Set needs_clarification = True so the conditional edge routes to END
      - Set clarification_msg to an "insufficient evidence" fallback message
      - validated_evidence falls back to the raw unfiltered list so the answer
        node still has *something* to work with

    Writes: validated_evidence, has_sufficient, needs_clarification, clarification_msg
    """
    evidence: list[Any] = state.get("evidence", [])
    instructions: AgentInstructions = get_config_service().get()
    threshold = instructions.confidence_threshold

    filtered: list[Any] = []

    for ev in evidence:
        if isinstance(ev, SparqlEvidence):
            if ev.triple_count > 0:
                filtered.append(ev)

        elif isinstance(ev, Neo4jGraphEvidence):
            if ev.result_count > 0:
                filtered.append(ev)

        elif isinstance(ev, FtsEvidence):
            good_hits = [h for h in ev.hits if h.score >= threshold]
            if good_hits:
                filtered.append(ev.model_copy(update={"hits": good_hits}))

        elif isinstance(ev, SimilarityEvidence):
            good_hits = [h for h in ev.hits if h.score >= threshold]
            if good_hits:
                filtered.append(ev.model_copy(update={"hits": good_hits}))

    has_sufficient = len(filtered) > 0

    logger.info(
        "node_validate_evidence",
        before=len(evidence),
        after=len(filtered),
        sufficient=has_sufficient,
    )

    if not has_sufficient:
        question = state.get("rewritten_question", state.get("raw_question", ""))
        return {
            "validated_evidence": evidence,    # fall back to unfiltered
            "has_sufficient": False,
            "needs_clarification": True,
            "clarification_msg": build_insufficient_evidence_message(question),
        }

    return {
        "validated_evidence": filtered,
        "has_sufficient": True,
        "needs_clarification": False,
        "clarification_msg": "",
    }


# ════════════════════════════════════════════════════════════════════════════════
# Node 7 — node_generate_answer
# ════════════════════════════════════════════════════════════════════════════════

async def node_generate_answer(state: PRAState) -> dict:
    """
    Generate a grounded answer using the existing AnswerGenerationService
    (Claude Sonnet with CoT prompt + conversation history).

    Uses `validated_evidence` (post Stage 5 filtering).
    Injects `conversation_history` for multi-turn CoT.

    Note: graph.py calls this node's *streaming* variant separately for SSE.
    This non-streaming version is used for non-streaming / test paths.

    Writes: answer, confidence
    """
    question = state.get("rewritten_question", state.get("raw_question", ""))
    validated_evidence: list[Any] = state.get("validated_evidence", [])
    retrieval_modes: list[str] = state.get("retrieval_modes", [])
    history: list[ConversationTurn] = state.get("conversation_history", [])
    intent: str = state.get("intent", "exploratory")
    is_followup: bool = state.get("is_followup", False)

    instructions: AgentInstructions = get_config_service().get()
    answer_svc = _get_answer_service()

    # --- [DEBUG-GROUNDING] Log evidence passed to LLM ---
    logger.info("[DEBUG-GROUNDING] 5. Evidence passed to LLM",
                evidence=[ev.model_dump() for ev in validated_evidence])
    # ----------------------------------------------------

    try:
        answer, confidence = await answer_svc.generate(
            question,
            validated_evidence,
            retrieval_modes,
            instructions,
            history=history,
            intent=intent,
            is_followup=is_followup,
        )

        # --- [DEBUG-GROUNDING] Log final answer ---
        logger.info("[DEBUG-GROUNDING] 6. Final LLM Answer", answer=answer)
        # ------------------------------------------

        logger.info("node_generate_answer_ok", confidence=confidence, answer_len=len(answer))
        return {"answer": answer, "confidence": confidence or 0.0}
    except Exception as exc:
        logger.error("node_generate_answer_failed", error=str(exc))
        return {
            "answer": (
                "Answer generation failed. Please check your API configuration.\n\n"
                f"Error: {exc}"
            ),
            "confidence": 0.0,
        }


# ════════════════════════════════════════════════════════════════════════════════
# Node 8 — node_save_to_db
# ════════════════════════════════════════════════════════════════════════════════

async def node_save_to_db(state: PRAState, config: RunnableConfig) -> dict:
    """
    Persist the completed turn to PostgreSQL.

    Saves:
      1. User turn  (raw_question, rewritten_question, intent, is_followup, entities)
      2. Retrieval log  (sparql/fts/similarity counts, evidence_passed, confidence)
      3. Assistant turn  (answer, confidence, modes_used)

    All three writes are independent try/except blocks so a single DB failure
    doesn't prevent the others from completing.

    This node is always the last in the graph (no outgoing edges).
    It writes nothing back to state (side-effect only).

    Writes: (nothing)
    """
    db = _get_db(config)
    if db is None or not state.get("session_id"):
        logger.info("node_save_to_db_skipped", session_id=state.get("session_id"))
        return {}

    session_id: str = state["session_id"]
    raw_question: str = state.get("raw_question", "")
    rewritten_question: str = state.get("rewritten_question", raw_question)
    intent: str = state.get("intent", "exploratory")
    is_followup: bool = state.get("is_followup", False)
    entities: list[str] = state.get("entities_mentioned", [])
    evidence: list[Any] = state.get("evidence", [])
    retrieval_modes: list[str] = state.get("retrieval_modes", [])
    answer: str = state.get("answer", "")
    confidence: float = state.get("confidence", 0.0)
    has_sufficient: bool = state.get("has_sufficient", False)

    # 1 — Save user turn
    try:
        await save_turn(
            db,
            session_id,
            "user",
            raw_question,
            rewritten_content=rewritten_question if rewritten_question != raw_question else None,
            intent=intent,
            is_followup=is_followup,
            entities=entities,
        )
        logger.info("node_save_to_db_user_turn_ok", session_id=session_id)
    except Exception as exc:
        logger.warning("node_save_to_db_user_turn_failed", error=str(exc))

    # 2 — Save retrieval log
    try:
        sparql_count = sum(1 for e in evidence if isinstance(e, SparqlEvidence))
        neo4j_count = sum(1 for e in evidence if isinstance(e, Neo4jGraphEvidence))
        fts_count    = sum(1 for e in evidence if isinstance(e, FtsEvidence))
        sim_count    = sum(1 for e in evidence if isinstance(e, SimilarityEvidence))
        await save_retrieval_log(
            db,
            session_id,
            rewritten_question,
            sparql_count=sparql_count,
            neo4j_count=neo4j_count,
            fts_count=fts_count,
            similarity_count=sim_count,
            evidence_passed=has_sufficient,
            confidence=confidence,
        )
        logger.info("node_save_to_db_retrieval_log_ok", session_id=session_id)
    except Exception as exc:
        logger.warning("node_save_to_db_retrieval_log_failed", error=str(exc))

    # 3 — Save assistant turn
    try:
        await save_turn(
            db,
            session_id,
            "assistant",
            answer,
            confidence=confidence,
            modes_used=retrieval_modes,
        )
        logger.info("node_save_to_db_assistant_turn_ok", session_id=session_id)
    except Exception as exc:
        logger.warning("node_save_to_db_assistant_turn_failed", error=str(exc))

    return {}
