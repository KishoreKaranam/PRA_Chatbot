"""
Answer generation service.

Takes structured evidence from the retrieval layer and calls an
LLM (OpenAI, Azure OpenAI, or Anthropic Claude) to generate a grounded, cited answer.
Supports both full-response and streaming modes.
"""
from __future__ import annotations

from typing import AsyncGenerator
import re
from math import isfinite
from openai import AsyncOpenAI, AsyncAzureOpenAI
import anthropic
import httpx

from app.models.schemas import (
    AgentInstructions,
    ConversationTurn,
    SparqlEvidence,
    FtsEvidence,
    SimilarityEvidence,
    Neo4jGraphEvidence,
)
from app.core.settings import get_settings
from app.core.log_config import get_logger
from app.prompts.answer import (
    STYLE_INSTRUCTIONS,
    build_current_question_message,
    build_system_prompt,
)

logger = get_logger(__name__)

class AnswerGenerationService:
    """Generate LLM answers grounded in retrieved evidence."""

    def __init__(self) -> None:
        settings = get_settings()
        self._provider = settings.llm_provider.lower()

        if self._provider == "anthropic":
            # ── Anthropic Claude ──────────────────────────────────────────────
            self._anthropic_client = anthropic.AsyncAnthropic(
                api_key=settings.anthropic_api_key,
                http_client=httpx.AsyncClient(verify=False),
            )
            self._model = settings.anthropic_model
            self._max_tokens = settings.anthropic_max_tokens
            self._client = None
            logger.info("llm_backend", backend="anthropic", model=self._model)

        elif self._provider == "azure":
            # ── Azure OpenAI ──────────────────────────────────────────────────
            self._client = AsyncAzureOpenAI(
                api_key=settings.azure_openai_api_key or settings.openai_api_key,
                azure_endpoint=settings.azure_openai_endpoint,
                api_version=settings.azure_openai_api_version,
            )
            self._model = settings.azure_openai_deployment or settings.openai_model
            self._anthropic_client = None
            self._max_tokens = 8000
            logger.info(
                "llm_backend",
                backend="azure",
                endpoint=settings.azure_openai_endpoint,
                deployment=self._model,
            )
        else:
            # ── Standard OpenAI (or any OpenAI-compatible endpoint) ───────────
            self._client = AsyncOpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
            )
            self._model = settings.openai_model
            self._anthropic_client = None
            self._max_tokens = 8000
            logger.info("llm_backend", backend="openai", model=self._model)

    async def generate(
        self,
        question: str,
        evidence: list,
        modes_used: list[str],
        instructions: AgentInstructions,
        history: list[ConversationTurn] | None = None,
        intent: str = "exploratory",
        is_followup: bool = False,
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

        system_prompt = self._build_system_prompt(instructions, is_followup, intent)
        messages = self._build_messages(question, context, modes_used, history or [])

        logger.info("llm_call", model=self._model, modes=modes_used, provider=self._provider,
                    is_followup=is_followup, intent=intent, history_turns=len(history or []))

        if self._provider == "anthropic":
            # ── Anthropic Claude API ──────────────────────────────────────────
            response = await self._anthropic_client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system_prompt,
                messages=messages,
            )
            answer = response.content[0].text if response.content else ""
        else:
            # ── OpenAI / Azure OpenAI API ─────────────────────────────────────
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "system", "content": system_prompt}] + messages,
                max_completion_tokens=self._max_tokens,
            )
            answer = response.choices[0].message.content or ""

        cleaned_answer = self._clean_answer(answer)
        return cleaned_answer.strip(), confidence

    async def generate_stream(
        self,
        question: str,
        evidence: list,
        modes_used: list[str],
        instructions: AgentInstructions,
        history: list[ConversationTurn] | None = None,
        intent: str = "exploratory",
        is_followup: bool = False,
    ) -> AsyncGenerator[str, None]:
        """
        Stream answer tokens as they are generated.
        Yields individual text chunks from the LLM.
        """
        context = self._build_context(evidence, instructions)
        confidence = self._estimate_confidence(evidence, modes_used)

        if not context.strip():
            if instructions.strict_ontology_mode:
                yield (
                    "No relevant information was found in the Payment Reference "
                    "Architecture knowledge graph for your question."
                )
                return
            context = "(No specific graph evidence retrieved; answering from general PRA knowledge.)"

        if confidence < instructions.confidence_threshold and instructions.strict_ontology_mode:
            yield (
                f"The evidence retrieved (confidence {confidence:.0%}) falls below "
                f"the configured threshold ({instructions.confidence_threshold:.0%}). "
                "Please rephrase your question or lower the confidence threshold."
            )
            return

        system_prompt = self._build_system_prompt(instructions, is_followup, intent)
        messages = self._build_messages(question, context, modes_used, history or [])

        logger.info("llm_stream_call", model=self._model, modes=modes_used, provider=self._provider,
                    is_followup=is_followup, intent=intent, history_turns=len(history or []))

        if self._provider == "anthropic":
            async with self._anthropic_client.messages.stream(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system_prompt,
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    yield text
        else:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "system", "content": system_prompt}] + messages,
                max_completion_tokens=self._max_tokens,
                stream=True,
            )
            async for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

    def _clean_answer(self, answer: str) -> str:
        """Defensively remove any internal reasoning sections from the final answer."""
        # Patterns to match "Chain of Thought", "Internal Reasoning", etc.,
        # followed by a newline and potentially a numbered or bulleted list.
        patterns_to_remove = [
            re.compile(r"^\s*###?\s*(chain of thought|internal reasoning|hidden reasoning|internal monologue)[\s\S]*?(?=(###?\s*\w|Direct Answer|Key Findings))", re.IGNORECASE | re.MULTILINE),
            re.compile(r"^\s*###?\s*(chain of thought|internal reasoning|hidden reasoning|internal monologue)[\s\S]*$", re.IGNORECASE | re.MULTILINE),
        ]

        cleaned = answer
        for pattern in patterns_to_remove:
            cleaned = pattern.sub("", cleaned)

        return cleaned.strip()
    # ── Context builder ───────────────────────────────────────────────────────

    def _build_context(self, evidence: list, instructions: AgentInstructions) -> str:
        """Serialise evidence objects into a text context block."""
        primary_evidence, supporting_evidence = self._prioritize_evidence(evidence)

        # A sufficiently populated Neo4j relationship result answers the
        # relationship question directly. Do not dilute it with unrelated
        # keyword/semantic hits in the LLM context.
        neo4j_relationship_evidence = any(
            isinstance(ev, Neo4jGraphEvidence) and ev.relationships
            for ev in primary_evidence
        )
        if neo4j_relationship_evidence:
            supporting_evidence = []

        logger.info(
            "evidence_prioritization",
            primary=[ev.mode for ev in primary_evidence],
            supporting=[ev.mode for ev in supporting_evidence],
        )

        parts: list[str] = []

        if primary_evidence:
            parts.append("### PRIMARY GRAPH EVIDENCE (Highest Priority)")
            parts.append("This evidence comes directly from the structured PRA knowledge graph. Prefer these facts for questions about relationships and definitions.")
            self._format_evidence(primary_evidence, parts)

        if supporting_evidence:
            parts.append("\n### SUPPORTING EVIDENCE (Lower Priority)")
            parts.append("This evidence is from keyword or semantic searches. Use it for supplementary details or when primary evidence is absent.")
            self._format_evidence(supporting_evidence, parts)

        return "\n".join(parts)

    def _format_evidence(self, evidence_list: list, parts: list[str]) -> None:
        """Helper to format a list of evidence into text parts."""
        for ev in evidence_list:
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

            elif isinstance(ev, Neo4jGraphEvidence) and ev.relationships:
                parts.append("=== Neo4j Graph Results (nodes and relationships) ===")
                # Cap to avoid token overflow
                for rel in ev.relationships[:30]:
                    # Find the start and end nodes from the results list
                    start_node = next((n for n in ev.results if n.element_id == rel.start_node), None)
                    end_node = next((n for n in ev.results if n.element_id == rel.end_node), None)
                    parts.append("SOURCE:")
                    self._format_neo4j_node(start_node, rel.start_node, parts)
                    parts.append("")
                    parts.append("RELATIONSHIP:")
                    parts.append(f"  {rel.type}")
                    parts.append("")
                    parts.append("TARGET:")
                    self._format_neo4j_node(end_node, rel.end_node, parts)
                    parts.append("")

    @staticmethod
    def _format_neo4j_node(node, fallback_id: str, parts: list[str]) -> None:
        """Expose human-readable Neo4j properties before technical identifiers."""
        if node is None:
            parts.append(f"  label: {fallback_id}")
            return

        properties = node.properties
        label = AnswerGenerationService._human_value(properties.get("label"))
        description = AnswerGenerationService._human_value(properties.get("description"))

        parts.append(f"  label: {label or fallback_id}")
        if description:
            parts.append(f"  description: {description}")
        parts.append(f"  element_id: {node.element_id}")

    def _prioritize_evidence(self, evidence: list) -> tuple[list, list]:
        """Sort evidence into primary (graph) and supporting (search) buckets."""
        primary = []
        supporting = []
        for ev in evidence:
            if isinstance(ev, (SparqlEvidence, Neo4jGraphEvidence)):
                # Check if it's a specific, non-fallback Neo4j query
                if isinstance(ev, Neo4jGraphEvidence) and ")-[r]-(" in ev.query:
                    supporting.append(ev) # Treat fallback as supporting
                else:
                    primary.append(ev)
            else:
                supporting.append(ev)
        return primary, supporting

    @staticmethod
    def _human_value(value) -> str:
        """Return a readable scalar from Neo4j scalar/list property values."""
        if value is None:
            return ""
        if isinstance(value, (list, tuple)):
            return "; ".join(str(item) for item in value if item is not None)
        return str(value)

    # ── Prompt builders ───────────────────────────────────────────────────────

    def _build_system_prompt(
        self,
        instructions: AgentInstructions,
        is_followup: bool = False,
        intent: str = "exploratory",
    ) -> str:
        style_instr = STYLE_INSTRUCTIONS.get(instructions.answer_style.value, "")
        return build_system_prompt(
            instructions.system_prompt,
            style_instr,
            intent,
            is_followup,
        )

    def _build_messages(
        self,
        question: str,
        context: str,
        modes_used: list[str],
        history: list[ConversationTurn],
        max_turns: int = 6,
    ) -> list[dict]:
        """
        Build the multi-turn messages array.
        Prior turns from history are injected first, then the current question
        with freshly retrieved context appended.
        """
        messages: list[dict] = []

        # Inject prior conversation turns (capped to avoid token overflow)
        for turn in history[-(max_turns * 2):]:
            messages.append({"role": turn.role, "content": turn.content})

        # Current question with retrieved context
        modes_label = ", ".join(modes_used) if modes_used else "none"
        messages.append({
            "role": "user",
            "content": build_current_question_message(question, modes_label, context),
        })
        return messages

    # ── Confidence heuristic ──────────────────────────────────────────────────

    def _estimate_confidence(self, evidence: list, modes_used: list[str]) -> float:
        """Estimate combined evidence support on a bounded 0.0-1.0 scale."""
        graph_quality = 0.0
        fts_quality = 0.0
        semantic_quality = 0.0

        for ev in evidence:
            if isinstance(ev, Neo4jGraphEvidence):
                graph_quality = max(graph_quality, self._neo4j_quality(ev))
            elif isinstance(ev, SparqlEvidence):
                graph_quality = max(graph_quality, self._sparql_quality(ev))
            elif isinstance(ev, FtsEvidence):
                fts_quality = max(fts_quality, self._fts_quality(ev))
            elif isinstance(ev, SimilarityEvidence):
                semantic_quality = max(semantic_quality, self._semantic_quality(ev))

        return min(
            0.55 * graph_quality
            + 0.20 * fts_quality
            + 0.25 * semantic_quality,
            1.0,
        )

    @classmethod
    def _neo4j_quality(cls, evidence: Neo4jGraphEvidence) -> float:
        """Score direct Neo4j graph support without treating rows as completeness."""
        relationships = evidence.relationships
        if evidence.result_count <= 0 or not relationships:
            return 0.0

        pattern_quality = 1.0 if cls._has_graph_pattern(evidence.query) else 0.5
        relationship_quality = 1.0

        nodes_by_id = {node.element_id: node for node in evidence.results}
        valid_relationships = [
            rel for rel in relationships
            if rel.start_node in nodes_by_id
            and rel.end_node in nodes_by_id
            and nodes_by_id[rel.start_node].labels
            and nodes_by_id[rel.end_node].labels
        ]
        endpoint_quality = len(valid_relationships) / len(relationships)

        readable_node_ids = {
            node.element_id
            for node in evidence.results
            if cls._has_human_readable_properties(node.properties)
        }
        readable_relationships = [
            rel for rel in relationships
            if rel.start_node in readable_node_ids and rel.end_node in readable_node_ids
        ]
        readable_quality = len(readable_relationships) / len(relationships)

        # Additional rows help, but with diminishing returns.
        result_strength = min(evidence.result_count / 10.0, 1.0)

        return min(
            0.30 * pattern_quality
            + 0.25 * relationship_quality
            + 0.15 * endpoint_quality
            + 0.15 * readable_quality
            + 0.15 * result_strength,
            1.0,
        )

    @staticmethod
    def _sparql_quality(evidence: SparqlEvidence) -> float:
        """Map non-empty SPARQL graph evidence to a bounded graph quality."""
        return min(max(evidence.triple_count, 0) / 20.0, 1.0)

    @staticmethod
    def _fts_quality(evidence: FtsEvidence) -> float:
        """Score FTS relevance using quality and bounded top-result coverage."""
        if not evidence.hits:
            return 0.0

        scores = [
            max(0.0, min(float(hit.score), 1.0))
            for hit in evidence.hits[:5]
            if isfinite(float(hit.score))
        ]
        if not scores:
            return 0.0

        top_quality = max(scores)
        coverage_quality = min(len(scores) / 5.0, 1.0)
        return 0.70 * top_quality + 0.30 * coverage_quality

    @staticmethod
    def _semantic_quality(evidence: SimilarityEvidence) -> float:
        """Score semantic relevance using bounded similarity and top-k support."""
        if not evidence.hits:
            return 0.0

        scores = [
            max(0.0, min(float(hit.score), 1.0))
            for hit in evidence.hits[:5]
            if isfinite(float(hit.score))
        ]
        if not scores:
            return 0.0

        top_quality = max(scores)
        coverage_quality = min(len(scores) / 5.0, 1.0)
        return 0.70 * top_quality + 0.30 * coverage_quality

    @staticmethod
    def _has_graph_pattern(query: str) -> bool:
        normalized = re.sub(r"\s+", " ", query or "").lower()
        return "match (source:" in normalized and ")-[r:" in normalized and "]->(target:" in normalized

    @staticmethod
    def _has_human_readable_properties(properties: dict) -> bool:
        return any(
            value not in (None, "", [], ())
            for key in ("label", "description")
            for value in [properties.get(key)]
        )
