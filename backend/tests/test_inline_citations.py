"""The evidence check returns, per claim, the exact answer text it came from,
so the UI can show source links next to that part of the answer."""
from __future__ import annotations

import json

from app.infrastructure.llm.answer_service import AnswerGenerationService
from app.prompts.grounding import GROUNDING_SYSTEM_PROMPT


def test_prompt_asks_for_answer_quote():
    assert '"answer_quote"' in GROUNDING_SYSTEM_PROMPT


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
