from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.application.retrieval.orchestrator import RetrievalOrchestrator
from app.models.schemas import AgentInstructions, FtsEvidence, FtsHit
from app.orchestration.langgraph import nodes


class FakeLegacyFts:
    def __init__(self, client):
        self.client = client

    async def retrieve(self, question, max_results):
        return FtsEvidence(
            search_term=question,
            hits=[FtsHit(uri="legacy", label="Legacy", score=0.8, snippet="legacy")],
        )


class FakeNeo4jFts:
    def __init__(self, client):
        self.client = client

    async def retrieve(self, question, max_results):
        return FtsEvidence(
            search_term=question,
            hits=[FtsHit(uri="neo4j", label="Neo4j", score=0.8, snippet="neo4j")],
        )


def test_neo4j_fts_is_selected(monkeypatch):
    monkeypatch.setattr(nodes, "get_settings", lambda: SimpleNamespace(fts_backend="neo4j"))

    service = nodes._build_fts_service(
        object(), object(), FakeLegacyFts, FakeNeo4jFts
    )

    assert isinstance(service, FakeNeo4jFts)


def test_legacy_fts_is_selected(monkeypatch):
    monkeypatch.setattr(nodes, "get_settings", lambda: SimpleNamespace(fts_backend="legacy"))

    service = nodes._build_fts_service(
        object(), object(), FakeLegacyFts, FakeNeo4jFts
    )

    assert isinstance(service, FakeLegacyFts)


def test_orchestrator_fts_call_shape_is_unchanged():
    service = FakeNeo4jFts(object())
    orchestrator = RetrievalOrchestrator(object(), object(), service, object())

    modes, evidence = asyncio.run(
        orchestrator._fts_only("business functions", 10)
    )

    assert modes == ["fts"]
    assert evidence[0].mode == "fts"
    assert evidence[0].hits[0].uri == "neo4j"
