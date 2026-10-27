"""The rewriting step must not swap words in a question that names its own subject."""
from __future__ import annotations

import asyncio

from app.models.schemas import ConversationTurn
from app.orchestration.langgraph import nodes

Q2 = "What does Foreign Exchange Management do and which journey stages does it support?"
HISTORY = [ConversationTurn(role="user", content="What are business functions in Payment Processing?"),
           ConversationTurn(role="assistant", content="...")]


def _run(question, history, monkeypatch):
    async def fake_find_entities(db, text, top_k=5):
        names = ["Foreign Exchange Management", "Payment Processing", "Settlement"]
        return [{"label": n} for n in names if n.lower() in text.lower()]

    monkeypatch.setattr(nodes, "find_entities", fake_find_entities)
    monkeypatch.setattr(nodes, "_get_haiku_client", lambda: (_ for _ in ()).throw(RuntimeError("no haiku in tests")))
    state = {"raw_question": question, "conversation_history": history}
    return asyncio.run(nodes.node_resolve_context(state, {"configurable": {"db": object()}}))


def test_which_is_not_a_pronoun():
    assert not nodes.PRONOUN_RE.search("Which journey stages are there?")


def test_question_naming_its_subject_is_not_rewritten(monkeypatch):
    out = _run(Q2, HISTORY, monkeypatch)
    assert out["rewritten_question"] == Q2                 # was: "... and Payment Processing journey stages ..."
    assert out["is_followup"] is False


def test_real_follow_up_is_still_resolved(monkeypatch):
    out = _run("What rules apply to it?", HISTORY, monkeypatch)
    assert out["rewritten_question"] == "What rules apply to Payment Processing?"
    assert out["is_followup"] is True
