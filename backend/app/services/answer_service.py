"""
Answer generation service.

Takes structured evidence from the retrieval layer and calls an
OpenAI-compatible LLM to generate a grounded, cited answer.
"""
from __future__ import annotations

from openai import AsyncOpenAI, AsyncAzureOpenAI

from app.models.schemas import (
    AgentInstructions,
    AnswerStyle,
    SparqlEvidence,
    FtsEvidence,
    SimilarityEvidence,
)
from app.core.settings import get_settings
from app.core.log_config import get_logger

logger = get_logger(__name__)

STYLE_INSTRUCTIONS: dict[AnswerStyle, str] = {
    AnswerStyle.BUSINESS: (
        "Answer in clear business language. Avoid jargon. "
        "Use bullet points where helpful. Target a payments business audience."
    ),
    AnswerStyle.TECHNICAL: (
        "Answer with technical precision. Include ontology class names, "
        "property URIs, and graph relationships where relevant."
    ),
    AnswerStyle.CONCISE: (
        "Be brief and to the point. Limit the answer to 3-5 sentences or bullet points."
    ),
    AnswerStyle.DETAILED: (
        "Provide a thorough, comprehensive answer. Include examples from the "
        "retrieved context, relationships, and relevant activities or rules."
    ),
}


class AnswerGenerationService:
    """Generate LLM answers grounded in retrieved evidence."""

    def __init__(self) -> None:
        settings = get_settings()

        if settings.azure_openai_endpoint:
            # ── Azure OpenAI ──────────────────────────────────────────────────
            self._client = AsyncAzureOpenAI(
                api_key=settings.openai_api_key,
                azure_endpoint=settings.azure_openai_endpoint,
                api_version=settings.azure_openai_api_version,
            )
            # In Azure the "model" param to chat.completions.create must be the
            # deployment name, not the underlying model name.
            self._model = settings.azure_openai_deployment or settings.openai_model
            logger.info(
                "llm_backend",
                backend="azure",
                endpoint=settings.azure_openai_endpoint,
                deployment=self._model,
                api_version=settings.azure_openai_api_version,
            )
        else:
            # ── Standard OpenAI (or any OpenAI-compatible endpoint) ───────────
            self._client = AsyncOpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
            )
            self._model = settings.openai_model
            logger.info("llm_backend", backend="openai", model=self._model)

    async def generate(
        self,
        question: str,
        evidence: list,
        modes_used: list[str],
        instructions: AgentInstructions,
    ) -> tuple[str, float | None]:
        """
        Returns (answer_text, confidence_score | None).
        confidence_score is a heuristic 0-1 value based on evidence richness.
        """
        context = self._build_context(evidence, instructions)
        confidence = self._estimate_confidence(evidence, modes_used)

        if not context.strip():
            if instructions.strict_ontology_mode:
                return (
                    "No relevant information was found in the Payment Reference "
                    "Architecture knowledge graph for your question.",
                    0.0,
                )
            context = "(No specific graph evidence retrieved; answering from general PRA knowledge.)"

        if confidence < instructions.confidence_threshold and instructions.strict_ontology_mode:
            return (
                f"The evidence retrieved (confidence ≈ {confidence:.0%}) falls below "
                f"the configured threshold ({instructions.confidence_threshold:.0%}). "
                "Please rephrase your question or lower the confidence threshold.",
                confidence,
            )

        system_prompt = self._build_system_prompt(instructions)
        user_message = self._build_user_message(question, context, modes_used)

        logger.info("llm_call", model=self._model, modes=modes_used)
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            max_completion_tokens=8000,  # reasoning models use tokens internally; needs headroom
        )
        answer = response.choices[0].message.content or ""
        return answer.strip(), confidence

    # ── Context builder ───────────────────────────────────────────────────────

    def _build_context(self, evidence: list, instructions: AgentInstructions) -> str:
        """Serialise evidence objects into a text context block."""
        parts: list[str] = []

        for ev in evidence:
            if isinstance(ev, SparqlEvidence) and ev.triple_count > 0:
                parts.append("=== SPARQL CONSTRUCT Results (ontology sub-graph) ===")
                for t in ev.triples[:60]:  # cap to avoid token overflow
                    parts.append(f"  <{t.subject}> <{t.predicate}> {t.obj} .")

            elif isinstance(ev, FtsEvidence) and ev.hits:
                parts.append(f"=== Full-Text Search Results (term: {ev.search_term}) ===")
                for hit in ev.hits:
                    parts.append(f"  URI: {hit.uri}")
                    parts.append(f"  Label: {hit.label}")
                    parts.append(f"  Score: {hit.score:.3f}")
                    parts.append(f"  Snippet: {hit.snippet[:200]}")
                    parts.append("")

            elif isinstance(ev, SimilarityEvidence) and ev.hits:
                parts.append("=== Similarity Search Results ===")
                for hit in ev.hits:
                    parts.append(f"  URI: {hit.uri}")
                    parts.append(f"  Label: {hit.label}")
                    parts.append(f"  Score: {hit.score:.3f}")
                    parts.append(f"  Text: {hit.text[:200]}")
                    parts.append("")

        return "\n".join(parts)

    # ── Prompt builder ────────────────────────────────────────────────────────

    def _build_system_prompt(self, instructions: AgentInstructions) -> str:
        style_instr = STYLE_INSTRUCTIONS.get(instructions.answer_style, "")
        return (
            f"{instructions.system_prompt}\n\n"
            f"Answer style: {style_instr}\n\n"
            "IMPORTANT RULES:\n"
            "- Only use facts present in the retrieved context below.\n"
            "- If the context does not contain an answer, say so explicitly.\n"
            "- Do NOT invent ontology terms, classes, or relationships.\n"
            "- Always cite which retrieval mode provided the information "
            "(SPARQL, full-text search, or similarity search).\n"
            "- Use PRA terminology exactly as it appears in the graph.\n"
        )

    def _build_user_message(
        self, question: str, context: str, modes_used: list[str]
    ) -> str:
        modes_label = ", ".join(modes_used) if modes_used else "none"
        return (
            f"Question: {question}\n\n"
            f"Retrieval modes used: {modes_label}\n\n"
            f"Retrieved context:\n{context}\n\n"
            "Please answer the question based strictly on the context above."
        )

    # ── Confidence heuristic ──────────────────────────────────────────────────

    def _estimate_confidence(self, evidence: list, modes_used: list[str]) -> float:
        """Simple heuristic: 0 = no evidence, 1 = rich multi-mode evidence."""
        score = 0.0
        for ev in evidence:
            if isinstance(ev, SparqlEvidence):
                score += min(ev.triple_count / 20.0, 0.4)
            elif isinstance(ev, FtsEvidence) and ev.hits:
                top_score = ev.hits[0].score if ev.hits else 0.0
                score += min(top_score / 2.0, 0.3) if top_score > 1.0 else min(len(ev.hits) / 10.0, 0.3)
            elif isinstance(ev, SimilarityEvidence) and ev.hits:
                top_sim = ev.hits[0].score if ev.hits else 0.0
                score += min(top_sim, 0.3)
        return min(score, 1.0)
