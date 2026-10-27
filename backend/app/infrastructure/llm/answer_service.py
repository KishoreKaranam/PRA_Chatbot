"""
Answer generation service.

Takes structured evidence from the retrieval layer and calls an
LLM (OpenAI, Azure OpenAI, or Anthropic Claude) to generate a grounded, cited answer.
Supports both full-response and streaming modes.
"""
from __future__ import annotations

from typing import AsyncGenerator
import json
import re
from math import isfinite
from openai import AsyncOpenAI, AsyncAzureOpenAI
import anthropic
import httpx2 as httpx

from app.models.schemas import (
    AgentInstructions,
    ConversationTurn,
    SparqlEvidence,
    FtsEvidence,
    SimilarityEvidence,
    Neo4jGraphEvidence,
    GroundingClaim,
    GroundingReport,
)
from app.core.settings import get_settings
from app.core.log_config import get_logger
from app.prompts.answer import (
    STYLE_INSTRUCTIONS,
    build_current_question_message,
    build_system_prompt,
)
from app.prompts.grounding import (
    GROUNDING_SYSTEM_PROMPT,
    build_grounding_user_message,
)

logger = get_logger(__name__)

class AnswerGenerationService:
    """Generate LLM answers grounded in retrieved evidence."""

    # Upper limit of graph entities written into Claude's evidence text.
    MAX_GRAPH_ENTITIES = 40

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
        elif self._provider == "azure_anthropic":
            # ── Claude via Azure AI Foundry — uses the Anthropic SDK's dedicated
            # Foundry client, pointed at the resource's "/anthropic" endpoint.
            self._anthropic_client = anthropic.AsyncAnthropicFoundry(
                api_key=settings.azure_ai_api_key,
                base_url=settings.azure_ai_endpoint.rstrip("/"),
                http_client=httpx.AsyncClient(verify=False),
            )
            self._model = settings.azure_ai_model
            self._client = None
            self._max_tokens = 8000
            logger.info(
                "llm_backend",
                backend="azure_anthropic",
                endpoint=settings.azure_ai_endpoint,
                model=self._model,
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

        if self._provider in ("anthropic", "azure_anthropic"):
            # ── Anthropic Claude API (direct or via Azure AI Foundry) ──────────
            response = await self._anthropic_client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system_prompt,
                messages=messages,
            )
            answer = self._extract_text_from_content(response.content)
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

    @staticmethod
    def _extract_text_from_content(content) -> str:
        """
        Extract the answer text from an Anthropic response's content blocks.

        Extended-thinking-capable models (e.g. claude-sonnet-4.5+) may return
        a `ThinkingBlock` (internal reasoning, has `.thinking` not `.text`)
        before the actual `TextBlock`. Skip any non-text blocks and
        concatenate all text blocks found.
        """
        if not content:
            return ""
        texts = [block.text for block in content if getattr(block, "type", None) == "text"]
        return "".join(texts)

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

        if self._provider in ("anthropic", "azure_anthropic"):
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

    # ── Output validation / grounding review ──────────────────────────────────

    async def review_grounding(
        self,
        answer: str,
        evidence: list,
        modes_used: list[str],
        instructions: AgentInstructions,
    ) -> GroundingReport:
        """
        Validate a generated answer against the retrieved evidence and report
        what fraction of it is grounded in that evidence (final result only).
        """
        report = GroundingReport(summary="No answer to review.", method="none")
        async for kind, current in self.review_grounding_stream(answer, evidence, modes_used, instructions):
            if kind == "final":
                report = current
        return report

    async def review_grounding_stream(
        self,
        answer: str,
        evidence: list,
        modes_used: list[str],
        instructions: AgentInstructions,
    ):
        """
        Same check as `review_grounding`, but yields progress while it runs:

          ("partial", report)  each time another answer line has been checked
          ("final", report)    once, at the end

        The reviewer answers one short line per answer line ("L7 ok"), so the
        UI can show source links line by line instead of waiting for the end.
        Falls back to a deterministic lexical-overlap estimate if the LLM call
        fails or its output cannot be read, so the layer never breaks.
        """
        answer = (answer or "").strip()
        context = self._build_context(evidence, instructions, purpose="review")

        # No answer, or nothing was retrieved → nothing to ground against.
        if not answer:
            yield "final", GroundingReport(summary="No answer to review.", method="none")
            return
        if not context.strip():
            yield "final", GroundingReport(
                grounding_score=0.0,
                grounded_percentage=0,
                total_claims=0,
                supported_claims=0,
                verdict="low",
                summary="No document evidence was retrieved; the answer is not grounded in sources.",
                method="none",
            )
            return

        answer_lines = answer.split("\n")
        claims: list[GroundingClaim] = []
        seen_lines: set[int] = set()
        summary = ""
        raw = ""
        buffer = ""

        def take(line_text: str) -> bool:
            nonlocal summary
            parsed = self._parse_verdict_line(line_text, answer_lines)
            if parsed == "summary":
                summary = line_text.split(":", 1)[1].strip() if ":" in line_text else ""
                return False
            if parsed is None or parsed["line"] in seen_lines:
                return False
            seen_lines.add(parsed["line"])
            claims.append(self._claim_from_verdict(parsed, answer_lines))
            return True

        try:
            async for chunk in self._stream_reviewer(answer, context):
                raw += chunk
                buffer += chunk
                while "\n" in buffer:
                    line_text, buffer = buffer.split("\n", 1)
                    if take(line_text):
                        yield "partial", self._report_from_claims(claims, "", method="partial")
            if buffer.strip():
                take(buffer)

            report = (
                self._report_from_claims(claims, summary, method="llm")
                if claims else self._parse_grounding(raw, answer)   # older JSON-style output
            )
            if report is not None:
                logger.info(
                    "grounding_review_ok",
                    score=report.grounding_score,
                    supported=report.supported_claims,
                    total=report.total_claims,
                    method="llm",
                )
                yield "final", report
                return
        except Exception as exc:
            logger.warning("grounding_review_llm_failed", error=str(exc))

        # Deterministic fallback.
        report = self._lexical_grounding(answer, context)
        logger.info(
            "grounding_review_fallback",
            score=report.grounding_score,
            method="lexical",
        )
        yield "final", report

    async def _stream_reviewer(self, answer: str, context: str):
        """Run the reviewer LLM pass, yielding its text as it is written."""
        user_message = build_grounding_user_message(answer, context)
        max_tokens = min(self._max_tokens, 8000)

        if self._provider in ("anthropic", "azure_anthropic"):
            text = ""
            async with self._anthropic_client.messages.stream(
                model=self._model,
                max_tokens=max_tokens,
                system=GROUNDING_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            ) as stream:
                async for chunk in stream.text_stream:
                    text += chunk
                    yield chunk
                final = await stream.get_final_message()
            logger.info(
                "grounding_reviewer_raw",
                stop_reason=final.stop_reason,
                output_tokens=final.usage.output_tokens,
                ending=text[-150:],
            )
            return

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": GROUNDING_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            max_completion_tokens=max_tokens,
            stream=True,
        )
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    # Reviewer output, one line per checked answer line:
    #   "L7 ok"   |   "L9 no | finishes in seconds"   |   "SUMMARY: ..."
    _VERDICT_RE = re.compile(
        r"^\s*[-*]?\s*L?\s*(\d+)\s*[:|.)\-]?\s*(ok|yes|true|no|false)\b\s*[|:\-–—]?\s*(.*)$",
        re.IGNORECASE,
    )

    @classmethod
    def _parse_verdict_line(cls, text: str, answer_lines: list[str]):
        """One reviewer output line → {"line", "ok", "missing"}, "summary", or None."""
        stripped = text.strip().strip("`")
        if stripped.upper().startswith("SUMMARY"):
            return "summary"
        match = cls._VERDICT_RE.match(stripped)
        if not match:
            return None
        line_no = int(match.group(1))
        if not (1 <= line_no <= len(answer_lines)) or not answer_lines[line_no - 1].strip():
            return None
        ok = match.group(2).lower() in ("ok", "yes", "true")
        return {"line": line_no, "ok": ok, "missing": "" if ok else match.group(3).strip()}

    @classmethod
    def _claim_from_verdict(cls, verdict: dict, answer_lines: list[str]) -> GroundingClaim:
        line = answer_lines[verdict["line"] - 1]
        text = cls._plain_line(line)
        return GroundingClaim(
            claim=text if verdict["ok"] else (verdict["missing"] or text),
            supported=verdict["ok"],
            evidence_refs=[],
            answer_quote=line.strip(),
        )

    @classmethod
    def _report_from_claims(cls, claims: list[GroundingClaim], summary: str, method: str) -> GroundingReport:
        total = len(claims)
        supported = sum(1 for c in claims if c.supported)
        score = (supported / total) if total else 0.0
        return GroundingReport(
            grounding_score=round(score, 4),
            grounded_percentage=round(score * 100),
            total_claims=total,
            supported_claims=supported,
            verdict=cls._verdict(score, total),
            summary=summary or cls._default_summary(score, supported, total),
            claims=list(claims),
            method=method,
        )

    @staticmethod
    def _extract_json(text: str) -> dict | None:
        """Extract the first JSON object from an LLM response (tolerates fences/prose)."""
        if not text:
            return None
        # Strip common ```json ... ``` fences.
        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
        candidate = fenced.group(1) if fenced else text
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            return json.loads(candidate[start : end + 1])
        except (json.JSONDecodeError, ValueError):
            return None

    @classmethod
    def _parse_grounding(cls, raw: str, answer: str = "") -> GroundingReport | None:
        """Convert the reviewer's JSON into a GroundingReport.

        The reviewer points to the answer line each claim came from ("line");
        that line's text is kept as `answer_quote` so the UI can show the
        claim's source links next to it.
        """
        answer_lines = answer.split("\n") if answer else []
        data = cls._extract_json(raw)
        if not isinstance(data, dict):
            return None

        raw_claims = data.get("claims")
        if not isinstance(raw_claims, list):
            raw_claims = cls._line_verdicts_to_claims(data.get("lines"), answer_lines)
        if not isinstance(raw_claims, list):
            return None

        claims: list[GroundingClaim] = []
        for item in raw_claims:
            if not isinstance(item, dict):
                continue
            text = str(item.get("claim", "")).strip()
            if not text:
                continue
            refs = item.get("evidence_refs") or []
            if not isinstance(refs, list):
                refs = [str(refs)]
            claims.append(
                GroundingClaim(
                    claim=text,
                    supported=bool(item.get("supported", False)),
                    evidence_refs=[str(r) for r in refs],
                    note=str(item.get("note", "") or "").strip(),
                    answer_quote=cls._quote_for(item, answer_lines),
                )
            )

        total = len(claims)
        supported = sum(1 for c in claims if c.supported)
        score = (supported / total) if total else 0.0

        return GroundingReport(
            grounding_score=round(score, 4),
            grounded_percentage=round(score * 100),
            total_claims=total,
            supported_claims=supported,
            verdict=cls._verdict(score, total),
            summary=str(data.get("summary", "")).strip() or cls._default_summary(score, supported, total),
            claims=claims,
            method="llm",
        )

    @staticmethod
    def _plain_line(line: str) -> str:
        """Answer line without markdown symbols (for display as a claim)."""
        text = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", line)        # bullet / number
        text = text.replace("**", "").replace("__", "").replace("`", "")
        text = re.sub(r"\s*\|\s*", " — ", text.strip().strip("|")).strip(" —")
        return text.strip()

    @classmethod
    def _line_verdicts_to_claims(cls, lines, answer_lines: list[str]) -> list[dict] | None:
        """Turn per-line verdicts ({"line", "ok", "refs", "missing"}) into claim dicts."""
        if not isinstance(lines, list):
            return None
        claims: list[dict] = []
        for item in lines:
            if not isinstance(item, dict):
                continue
            try:
                line_no = int(item.get("line"))
            except (TypeError, ValueError):
                continue
            if not (1 <= line_no <= len(answer_lines)) or not answer_lines[line_no - 1].strip():
                continue
            ok = bool(item.get("ok", False))
            text = cls._plain_line(answer_lines[line_no - 1])
            missing = str(item.get("missing", "") or "").strip()
            claims.append({
                "claim": missing if (not ok and missing) else text,
                "supported": ok,
                "line": line_no,
                "evidence_refs": item.get("refs") or [],
            })
        return claims

    @staticmethod
    def _quote_for(item: dict, answer_lines: list[str]) -> str:
        """Text of the answer line the claim came from (or the reviewer's own quote)."""
        try:
            line_no = int(item.get("line"))
        except (TypeError, ValueError):
            line_no = 0
        if 1 <= line_no <= len(answer_lines) and answer_lines[line_no - 1].strip():
            return answer_lines[line_no - 1].strip()
        return str(item.get("answer_quote", "") or "").strip()

    def _lexical_grounding(self, answer: str, context: str) -> GroundingReport:
        """
        Fallback: sentence-level lexical overlap between the answer and evidence.

        A sentence counts as grounded when a meaningful share of its content
        words also appear in the evidence context. Rough, but deterministic.
        """
        context_words = set(re.findall(r"[a-z0-9]{3,}", context.lower()))
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", answer) if len(s.strip()) > 15]

        claims: list[GroundingClaim] = []
        for sentence in sentences:
            words = set(re.findall(r"[a-z0-9]{3,}", sentence.lower()))
            if not words:
                continue
            overlap = len(words & context_words) / len(words)
            supported = overlap >= 0.5
            claims.append(
                GroundingClaim(
                    claim=sentence,
                    supported=supported,
                    evidence_refs=[],
                    note=f"lexical overlap {overlap:.0%}",
                    answer_quote=sentence,
                )
            )

        total = len(claims)
        supported = sum(1 for c in claims if c.supported)
        score = (supported / total) if total else 0.0

        return GroundingReport(
            grounding_score=round(score, 4),
            grounded_percentage=round(score * 100),
            total_claims=total,
            supported_claims=supported,
            verdict=self._verdict(score, total),
            summary=self._default_summary(score, supported, total)
            + " (estimated via lexical overlap; reviewer model unavailable)",
            claims=claims,
            method="lexical",
        )

    @staticmethod
    def _verdict(score: float, total: int) -> str:
        if total == 0:
            return "unverified"
        if score >= 0.8:
            return "high"
        if score >= 0.5:
            return "moderate"
        return "low"

    @staticmethod
    def _default_summary(score: float, supported: int, total: int) -> str:
        if total == 0:
            return "No verifiable claims were found in the answer."
        return (
            f"{supported} of {total} claims ({score:.0%}) are supported by the "
            "retrieved document evidence."
        )

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

    def _build_context(
        self,
        evidence: list,
        instructions: AgentInstructions,
        purpose: str = "answer",
    ) -> str:
        """Serialise evidence objects into a text context block.

        purpose: "answer" (text Claude answers from) or "review" (text the
        grounding reviewer checks against) — only used for logging.
        """
        primary_evidence, supporting_evidence = self._prioritize_evidence(evidence)
        supporting_before_drop = list(supporting_evidence)

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
        stats: dict[str, int] = {}

        if primary_evidence:
            parts.append("### PRIMARY GRAPH EVIDENCE (Highest Priority)")
            parts.append("This evidence comes directly from the structured PRA knowledge graph. Prefer these facts for questions about relationships and definitions.")
            self._format_evidence(primary_evidence, parts, stats)

        if supporting_evidence:
            parts.append("\n### SUPPORTING EVIDENCE (Lower Priority)")
            parts.append("This evidence is from keyword or semantic searches. Use it for supplementary details or when primary evidence is absent.")
            self._format_evidence(supporting_evidence, parts, stats)

        context = "\n".join(parts)
        self._log_context(evidence, supporting_before_drop, supporting_evidence, stats, context, purpose)
        return context

    # ── Measurement: what actually reaches Claude ─────────────────────────────

    def _log_context(
        self,
        evidence: list,
        supporting_before_drop: list,
        supporting_kept: list,
        stats: dict[str, int],
        context: str,
        purpose: str,
    ) -> None:
        """Log what the search FOUND vs what was actually SENT to Claude.

        Measurement only — does not change the answer. Compare *_found with
        *_sent to see evidence that was retrieved but never reached Claude.
        Set LOG_LLM_CONTEXT=true in backend/.env to also save the full text
        sent to Claude under backend/logs/llm_context/.
        """
        graph = [ev for ev in evidence if isinstance(ev, Neo4jGraphEvidence)]
        fts = [ev for ev in evidence if isinstance(ev, FtsEvidence)]
        sim = [ev for ev in evidence if isinstance(ev, SimilarityEvidence)]
        logger.info(
            "llm_context_built",
            purpose=purpose,
            graph_entities_found=sum(len(ev.results) for ev in graph),
            graph_relationships_found=sum(len(ev.relationships) for ev in graph),
            graph_entities_sent=stats.get("graph_entities_sent", 0),
            graph_relationships_sent=stats.get("graph_relationships_sent", 0),
            fts_hits_found=sum(len(ev.hits) for ev in fts),
            fts_hits_sent=stats.get("fts_hits_sent", 0),
            similarity_hits_found=sum(len(ev.hits) for ev in sim),
            similarity_hits_sent=stats.get("similarity_hits_sent", 0),
            supporting_dropped=len(supporting_before_drop) > len(supporting_kept),
            context_chars=len(context),
            context_tokens_est=len(context) // 4,
        )
        if get_settings().log_llm_context:
            self._dump_context(context, purpose)

    @staticmethod
    def _dump_context(context: str, purpose: str) -> None:
        """Save the exact text sent to Claude (debugging / before-after comparisons)."""
        try:
            from datetime import datetime
            from pathlib import Path

            folder = Path(__file__).resolve().parents[3] / "logs" / "llm_context"
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{datetime.now():%Y%m%d_%H%M%S_%f}_{purpose}.txt"
            path.write_text(context, encoding="utf-8")
            logger.info("llm_context_saved", path=str(path))
        except Exception as exc:  # never break an answer because of logging
            logger.warning("llm_context_save_failed", error=str(exc))

    def _format_evidence(
        self,
        evidence_list: list,
        parts: list[str],
        stats: dict[str, int] | None = None,
    ) -> None:
        """Helper to format a list of evidence into text parts.

        stats (optional) counts what is written, for the llm_context_built log.
        """
        stats = stats if stats is not None else {}

        def count(key: str, n: int = 1) -> None:
            stats[key] = stats.get(key, 0) + n

        for ev in evidence_list:
            if isinstance(ev, Neo4jGraphEvidence) and ev.summary:
                # PRA map / domain profiles: already a compact, readable summary.
                parts.append("=== Neo4j Graph Results (PRA structure) ===")
                parts.append(ev.summary)
                parts.append("")
                count("graph_entities_sent", len(ev.results))

            elif isinstance(ev, SparqlEvidence) and ev.triple_count > 0:
                parts.append("=== SPARQL CONSTRUCT Results (ontology sub-graph) ===")
                for t in ev.triples[:60]:  # cap to avoid token overflow
                    parts.append(f"  <{t.subject}> <{t.predicate}> {t.obj} .")

            elif isinstance(ev, FtsEvidence) and ev.hits:
                parts.append(f"=== Full-Text Search Results (term: {ev.search_term}) ===")
                count("fts_hits_sent", len(ev.hits))
                for hit in ev.hits:
                    parts.append(f"  URI: {hit.uri}")
                    parts.append(f"  Label: {hit.label}")
                    parts.append(f"  Score: {hit.score:.3f}")
                    parts.append(f"  Snippet: {hit.snippet[:200]}")
                    parts.append("")

            elif isinstance(ev, SimilarityEvidence) and ev.hits:
                parts.append("=== Similarity Search Results ===")
                count("similarity_hits_sent", len(ev.hits))
                for hit in ev.hits:
                    parts.append(f"  URI: {hit.uri}")
                    parts.append(f"  Label: {hit.label}")
                    parts.append(f"  Score: {hit.score:.3f}")
                    parts.append(f"  Text: {hit.text[:200]}")
                    parts.append("")

            elif isinstance(ev, Neo4jGraphEvidence) and ev.relationships:
                parts.append("=== Neo4j Graph Results (nodes and relationships) ===")
                # Cap to avoid token overflow
                count("graph_relationships_sent", len(ev.relationships[:30]))
                count("graph_entities_sent", len(
                    {r.start_node for r in ev.relationships[:30]} | {r.end_node for r in ev.relationships[:30]}
                ))
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

            elif isinstance(ev, Neo4jGraphEvidence) and ev.results:
                # Graph queries such as "functions of a domain" return the
                # entities without relationship objects. Previously these were
                # silently dropped, so Claude never saw them.
                shown = ev.results[:self.MAX_GRAPH_ENTITIES]
                parts.append("=== Neo4j Graph Results (entities) ===")
                count("graph_entities_sent", len(shown))
                groups: dict[str, list] = {}
                for node in shown:
                    kind = next((lbl for lbl in node.labels if lbl != "Resource"), "Entity")
                    groups.setdefault(kind, []).append(node)
                for kind, nodes in groups.items():
                    parts.append(f"{kind}:")
                    for node in nodes:
                        name = self._node_name(node)
                        description = self._human_value(node.properties.get("description"))
                        parts.append(f"  - {name}" + (f": {description[:300]}" if description else ""))
                    parts.append("")
                if len(ev.results) > len(shown):
                    parts.append(f"  (+{len(ev.results) - len(shown)} more not shown)")

    @staticmethod
    def _format_neo4j_node(node, fallback_id: str, parts: list[str]) -> None:
        """Expose human-readable Neo4j properties before technical identifiers."""
        if node is None:
            parts.append(f"  label: {fallback_id}")
            return

        properties = node.properties
        label = AnswerGenerationService._node_name(node)
        description = AnswerGenerationService._human_value(properties.get("description"))

        parts.append(f"  label: {label or fallback_id}")
        if description:
            parts.append(f"  description: {description}")
        parts.append(f"  element_id: {node.element_id}")

    @staticmethod
    def _node_name(node) -> str:
        """Readable name of a graph node: `name` (PRA schema), then `label`, then its id."""
        props = node.properties or {}
        return (AnswerGenerationService._human_value(props.get("name"))
                or AnswerGenerationService._human_value(props.get("label"))
                or str(node.element_id))

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
