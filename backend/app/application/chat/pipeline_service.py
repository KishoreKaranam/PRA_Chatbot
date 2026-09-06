"""
Conversation Pipeline Service
==============================
Implements the 7-stage pipeline for multi-turn, context-aware conversations:

  Stage 1 – Context Resolver    : Detect follow-up, rewrite question fully
  Stage 2 – Intent Classifier   : Rule-based classification (no LLM cost)
  Stage 3 – Clarification Gate  : Return a question to user if intent is vague
  Stage 4 – Retrieval Router    : Handled by RetrievalOrchestrator (existing)
  Stage 5 – Evidence Validator  : Filter low-relevance evidence
  Stage 6 – Answer Generator    : Handled by AnswerGenerationService (existing)
  Stage 7 – Context Updater     : Maintain sliding window of conversation turns
"""
from __future__ import annotations

import json
import re
from typing import Literal

import anthropic
import httpx

from app.models.schemas import (
    AgentInstructions,
    ConversationTurn,
    FtsEvidence,
    SimilarityEvidence,
    SparqlEvidence,
)
from app.core.settings import get_settings
from app.core.log_config import get_logger
from app.prompts.conversation import (
    build_pipeline_clarification_message,
    build_pipeline_context_resolution_prompt,
)

logger = get_logger(__name__)

IntentType = Literal["definition", "list", "comparison", "exploratory", "vague"]

MAX_HISTORY_TURNS = 6   # max user+assistant pairs to keep in the window


class ConversationPipeline:
    """Stateless pipeline — all state lives in the caller (request payload)."""

    def __init__(self) -> None:
        settings = get_settings()
        self._provider = settings.llm_provider.lower()

        if self._provider == "anthropic":
            self._client = anthropic.AsyncAnthropic(
                api_key=settings.anthropic_api_key,
                http_client=httpx.AsyncClient(verify=False),
            )
            # Use a cheaper/faster model for lightweight pipeline stages
            self._fast_model = "claude-haiku-4-5"
            self._main_model = settings.anthropic_model
        elif self._provider == "azure_anthropic":
            self._client = anthropic.AsyncAnthropic(
                api_key=settings.azure_ai_api_key,
                base_url=settings.azure_ai_endpoint.rstrip("/"),
                default_headers={"api-key": settings.azure_ai_api_key},
                default_query={"api-version": settings.azure_ai_api_version},
                http_client=httpx.AsyncClient(verify=False),
            )
            # No separate cheap model on Foundry deployment — reuse the main model
            self._fast_model = settings.azure_ai_model
            self._main_model = settings.azure_ai_model
        else:
            self._client = None
            self._fast_model = None
            self._main_model = None

    # ── Stage 1: Context Resolver ─────────────────────────────────────────────

    async def stage1_resolve_context(
        self,
        raw_question: str,
        history: list[ConversationTurn],
    ) -> tuple[str, bool]:
        """
        Returns (rewritten_question, is_followup).

        If there is no conversation history the question is returned unchanged.
        Otherwise a small fast LLM call rewrites the question so it is fully
        self-contained (all pronouns and references resolved).
        """
        if not history:
            logger.info("pipeline_stage1", is_followup=False, rewritten=raw_question)
            return raw_question, False

        history_text = self._format_history(history)
        prompt = build_pipeline_context_resolution_prompt(history_text, raw_question)

        try:
            result = await self._fast_llm_json(prompt)
            is_followup: bool = bool(result.get("is_followup", False))
            rewritten: str = result.get("rewritten", raw_question).strip() or raw_question
        except Exception as exc:
            logger.warning("pipeline_stage1_failed", error=str(exc))
            return raw_question, False

        logger.info("pipeline_stage1", is_followup=is_followup, rewritten=rewritten)
        return rewritten, is_followup

    # ── Stage 2: Intent Classifier ────────────────────────────────────────────

    def stage2_classify_intent(self, question: str) -> IntentType:
        """
        Fast rule-based classification — no LLM call.

        Returns one of: definition | list | comparison | exploratory | vague
        """
        q = question.lower().strip()

        # Too short / clearly incomplete
        if len(q.split()) < 3:
            return "vague"

        # Only pronouns / references with no noun
        if re.match(r"^(what about|tell me more|and|also|how about)\s*(it|them|those|that|this)?\.?$", q):
            return "vague"

        if any(q.startswith(p) for p in (
            "what is", "what are", "define", "explain what",
            "describe what", "meaning of", "definition of",
        )):
            return "definition"

        if any(p in q for p in (
            "list ", "list all", "how many", "enumerate", "give me all",
            "show all", "what are all", "all the ",
        )):
            return "list"

        if any(p in q for p in (
            "difference between", "compare", " vs ", " versus ",
            "how does x differ", "distinguish",
        )):
            return "comparison"

        return "exploratory"

    # ── Stage 3: Clarification Gate ───────────────────────────────────────────

    def stage3_clarification_gate(
        self,
        intent: IntentType,
        question: str,
        history: list[ConversationTurn],
    ) -> str | None:
        """
        Returns a clarification question string if the intent is too vague,
        otherwise returns None (meaning we proceed with retrieval).
        """
        if intent != "vague":
            return None

        # If we have history, we can resolve it ourselves — don't ask again
        if history:
            return None

        return build_pipeline_clarification_message(question)

    # ── Stage 5: Evidence Validator ───────────────────────────────────────────

    def stage5_validate_evidence(
        self,
        evidence: list,
        instructions: AgentInstructions,
    ) -> tuple[list, bool]:
        """
        Filter evidence that falls below the confidence threshold.
        Returns (filtered_evidence, has_sufficient_evidence).
        """
        filtered: list = []
        threshold = instructions.confidence_threshold

        for ev in evidence:
            if isinstance(ev, SparqlEvidence):
                if ev.triple_count > 0:
                    filtered.append(ev)

            elif isinstance(ev, FtsEvidence):
                good_hits = [h for h in ev.hits if h.score >= threshold]
                if good_hits:
                    ev_copy = ev.model_copy(update={"hits": good_hits})
                    filtered.append(ev_copy)

            elif isinstance(ev, SimilarityEvidence):
                good_hits = [h for h in ev.hits if h.score >= threshold]
                if good_hits:
                    ev_copy = ev.model_copy(update={"hits": good_hits})
                    filtered.append(ev_copy)

        has_sufficient = len(filtered) > 0
        logger.info(
            "pipeline_stage5",
            before=len(evidence),
            after=len(filtered),
            sufficient=has_sufficient,
        )
        return filtered, has_sufficient

    # ── Stage 7: Context Updater ──────────────────────────────────────────────

    def stage7_update_context(
        self,
        history: list[ConversationTurn],
        rewritten_question: str,
        answer: str,
    ) -> list[ConversationTurn]:
        """
        Append the latest rewritten question + answer to history.
        Trims to the last MAX_HISTORY_TURNS user+assistant pairs.
        NOTE: The updated history is returned to the caller (frontend),
              not stored server-side.
        """
        updated = list(history) + [
            ConversationTurn(role="user", content=rewritten_question),
            ConversationTurn(role="assistant", content=answer),
        ]
        # Keep only the last N pairs (2 messages per pair)
        return updated[-(MAX_HISTORY_TURNS * 2):]

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _format_history(self, history: list[ConversationTurn]) -> str:
        lines = []
        for turn in history[-(MAX_HISTORY_TURNS * 2):]:
            label = "User" if turn.role == "user" else "Assistant"
            lines.append(f"{label}: {turn.content}")
        return "\n".join(lines)

    @staticmethod
    def _extract_text_from_content(content) -> str:
        """
        Extract answer text from an Anthropic response's content blocks.

        Extended-thinking-capable models (e.g. claude-sonnet-4.5+) may return
        a `ThinkingBlock` (internal reasoning, has `.thinking` not `.text`)
        before the actual `TextBlock`. Skip any non-text blocks.
        """
        if not content:
            return ""
        texts = [block.text for block in content if getattr(block, "type", None) == "text"]
        return "".join(texts)

    async def _fast_llm_json(self, prompt: str) -> dict:
        """Make a small fast LLM call and parse the JSON response."""
        if self._provider in ("anthropic", "azure_anthropic"):
            response = await self._client.messages.create(
                model=self._fast_model,
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = self._extract_text_from_content(response.content).strip()
        else:
            raise NotImplementedError("pipeline fast LLM only supports anthropic currently")

        # Extract JSON even if model wraps it in ```json ... ```
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ValueError(f"No JSON found in LLM response: {raw!r}")
        return json.loads(match.group())


# ── Module-level singleton ────────────────────────────────────────────────────

_pipeline: ConversationPipeline | None = None


def get_pipeline() -> ConversationPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = ConversationPipeline()
    return _pipeline
