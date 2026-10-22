"""The evidence check returns, per claim, the exact answer text it came from,
so the UI can show source links next to that part of the answer."""
from __future__ import annotations

import json

from app.infrastructure.llm.answer_service import AnswerGenerationService
from app.prompts.grounding import GROUNDING_SYSTEM_PROMPT


def test_prompt_asks_for_short_claims_with_line_numbers():
    assert '"line"' in GROUNDING_SYSTEM_PROMPT
    assert '"note"' not in GROUNDING_SYSTEM_PROMPT      # per-claim notes removed (slow, not shown)


def test_answer_is_sent_with_line_numbers():
    from app.prompts.grounding import build_grounding_user_message
    msg = build_grounding_user_message("First line.\n\n- Second item", "evidence")
    assert "L1| First line." in msg and "L3| - Second item" in msg and "L2|" not in msg


def test_line_number_becomes_the_quote():
    answer = "Intro sentence.\n\n- **Routing Engine** – selects the route."
    raw = json.dumps({"claims": [
        {"claim": "Routing Engine selects the route", "supported": True, "line": 3, "evidence_refs": ["Routing Engine"]},
        {"claim": "Bad line number", "supported": True, "line": 99},
    ], "summary": "ok"})
    report = AnswerGenerationService._parse_grounding(raw, answer)
    assert report.claims[0].answer_quote == "- **Routing Engine** – selects the route."
    assert report.claims[0].note == ""
    assert report.claims[1].answer_quote == ""


def test_parse_keeps_answer_quote():
    raw = json.dumps({"claims": [
        {"claim": "Routing Engine selects the route", "supported": True, "evidence_refs": ["x"],
         "answer_quote": "Routing Engine – selects the clearing route."},
        {"claim": "Older reviewer output without a quote", "supported": False},
    ], "summary": "ok"})
    report = AnswerGenerationService._parse_grounding(raw)
    assert report.claims[0].answer_quote == "Routing Engine – selects the clearing route."
    assert report.claims[1].answer_quote == ""          # optional, defaults to empty


def test_lexical_fallback_quotes_the_sentence_itself():
    svc = AnswerGenerationService.__new__(AnswerGenerationService)
    report = svc._lexical_grounding(
        "Payment Processing routes accepted orders to clearing.", "payment processing routes orders")
    assert report.claims[0].answer_quote == report.claims[0].claim


def test_per_line_verdicts_become_claims():
    answer = ("Payment Processing decides how orders are handled.\n\n"
              "- **Routing Engine** – selects the route.\n"
              "| FX Management | Payment Processing |\n"
              "Instant payments finish in seconds.")
    raw = json.dumps({"lines": [
        {"line": 1, "ok": True, "refs": ["Payment Processing"]},
        {"line": 3, "ok": True, "refs": ["Routing Engine"]},
        {"line": 4, "ok": True, "refs": ["FX Management"]},
        {"line": 5, "ok": False, "missing": "finish in seconds"},
        {"line": 2, "ok": True},           # empty line -> ignored
        {"line": 42, "ok": True},          # out of range -> ignored
    ], "summary": "Mostly supported."})
    report = AnswerGenerationService._parse_grounding(raw, answer)
    assert report.total_claims == 4 and report.supported_claims == 3
    c = report.claims
    assert c[0].evidence_refs == ["Payment Processing"]
    assert c[1].claim == "Routing Engine – selects the route."          # markdown removed
    assert c[1].answer_quote == "- **Routing Engine** – selects the route."
    assert c[2].claim == "FX Management — Payment Processing"
    assert c[3].claim == "finish in seconds" and not c[3].supported
    assert c[3].answer_quote == "Instant payments finish in seconds."


def test_sources_can_be_prefetched_and_reused():
    import asyncio
    from app.application.grounding import sources
    from app.models.schemas import GroundingClaim, GroundingReport, Neo4jGraphEvidence, Neo4jNode

    calls = []

    class FakeClient:
        async def execute_read_query(self, query, **params):
            calls.append(params["names"])
            return [{"name": "Routing Engine", "own": "PRA Functional descriptions for Payments Journey.xlsx"}]

    ev = [Neo4jGraphEvidence(query="q", result_count=1, results=[
        Neo4jNode(element_id="1", labels=["Function"], properties={"name": "Routing Engine"})])]
    report = GroundingReport(claims=[GroundingClaim(claim="Routing Engine selects the route", supported=True,
                                                    evidence_refs=["Routing Engine"])], method="llm")

    async def run():
        prefetched = await sources.prefetch_sources(ev, FakeClient())
        return await sources.attach_sources(report, ev, client=FakeClient(), sources_by_name=prefetched)

    out = asyncio.run(run())
    assert len(calls) == 1                                   # looked up once, not twice
    assert out.claims[0].sources[0].name.endswith("Payments Journey.xlsx")
