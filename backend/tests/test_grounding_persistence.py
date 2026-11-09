"""The evidence check (grounding report) is saved with each answer and returned with history."""
from __future__ import annotations

import asyncio

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.api.session import HistoryTurn
from app.infrastructure.persistence.postgres.models import ConversationTurn
from app.models.schemas import DocumentRef, GroundingClaim, GroundingReport
from app.orchestration.langgraph import nodes


def _report() -> GroundingReport:
    doc = DocumentRef(name="PRA Patterns guide.docx", url="/api/documents/PRA%20Patterns%20guide.pdf")
    return GroundingReport(
        grounding_score=0.5, grounded_percentage=50, total_claims=2, supported_claims=1,
        verdict="moderate", summary="half", method="llm",
        claims=[GroundingClaim(claim="a", supported=True, sources=[doc]),
                GroundingClaim(claim="b", supported=False)],
        documents=[doc],
    )


def test_table_has_jsonb_grounding_column():
    ddl = str(CreateTable(ConversationTurn.__table__).compile(dialect=postgresql.dialect()))
    assert "grounding JSONB" in ddl


def test_grounding_dict_handles_model_dict_and_none():
    as_dict = nodes._grounding_dict(_report())
    assert as_dict["grounded_percentage"] == 50
    assert as_dict["claims"][0]["sources"][0]["url"].startswith("/api/documents/")
    assert nodes._grounding_dict({"x": 1}) == {"x": 1}
    assert nodes._grounding_dict(None) is None


def test_save_to_db_stores_grounding_on_the_assistant_turn(monkeypatch):
    calls = []

    async def fake_save_turn(db, session_id, role, content, **kw):
        calls.append((role, kw))

    async def fake_log(*a, **k):
        return None

    monkeypatch.setattr(nodes, "save_turn", fake_save_turn)
    monkeypatch.setattr(nodes, "save_retrieval_log", fake_log)
    state = {
        "session_id": "00000000-0000-0000-0000-000000000001",
        "raw_question": "q", "answer": "a", "grounding_report": _report(),
    }
    asyncio.run(nodes.node_save_to_db(state, {"configurable": {"db": object()}}))

    user_kw = next(kw for role, kw in calls if role == "user")
    assistant_kw = next(kw for role, kw in calls if role == "assistant")
    assert "grounding" not in user_kw
    assert assistant_kw["grounding"]["supported_claims"] == 1


def test_history_turn_returns_grounding_and_is_optional():
    base = dict(id=1, role="assistant", raw_content="a", rewritten_content=None, intent=None,
                is_followup=False, entities=[], confidence=None, modes_used=[], timestamp=None)
    assert HistoryTurn(**base).grounding is None          # older turns saved before this change
    turn = HistoryTurn(**base, grounding=_report().model_dump(mode="json"))
    assert turn.grounding["documents"][0]["name"] == "PRA Patterns guide.docx"
