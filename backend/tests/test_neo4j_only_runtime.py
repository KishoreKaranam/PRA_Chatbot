import asyncio
from types import SimpleNamespace

import pytest

from app.application.retrieval import orchestrator as orchestrator_module
from app.application.retrieval.orchestrator import RetrievalOrchestrator
from app.models.schemas import (
    AgentInstructions,
    FtsEvidence,
    FtsHit,
    Neo4jGraphEvidence,
    SimilarityEvidence,
    SimilarityHit,
    SparqlEvidence,
    Triple,
)
from app.orchestration.langgraph import nodes


class FakeSparql:
    def __init__(self, result=None, error=None, results=None):
        self.calls = []
        self.result = result or SparqlEvidence(
            query="fallback",
            triples=[Triple(subject="s", predicate="p", obj="o")],
            triple_count=1,
        )
        self.results = list(results or [])
        self.error = error

    async def retrieve(self, question, max_results, max_triples):
        self.calls.append((question, max_results, max_triples))
        if self.error:
            raise self.error
        if self.results:
            return self.results.pop(0)
        return self.result


class FakeGraph:
    def __init__(self, result=None, error=None):
        self.result = result or Neo4jGraphEvidence()
        self.error = error

    async def retrieve(self, question):
        if self.error:
            raise self.error
        return self.result


class FakeFts:
    def __init__(self, result=None, error=None):
        self.result = result or FtsEvidence(search_term="", hits=[])
        self.error = error

    async def retrieve(self, question, max_results):
        if self.error:
            raise self.error
        return self.result


class FakeSimilarity:
    def __init__(self, result=None, error=None):
        self.result = result or SimilarityEvidence(hits=[])
        self.error = error

    async def retrieve(self, question, max_results):
        if self.error:
            raise self.error
        return self.result


def _instructions():
    return AgentInstructions()


def _hybrid(monkeypatch, backend, graph, fts, similarity, sparql):
    monkeypatch.setattr(
        orchestrator_module,
        "get_settings",
        lambda: SimpleNamespace(retrieval_backend=backend),
    )
    service = RetrievalOrchestrator(sparql, graph, fts, similarity)
    return asyncio.run(service._hybrid("question", 10, 500))


def test_neo4j_empty_results_do_not_call_sparql_fallback(monkeypatch):
    sparql = FakeSparql()

    modes, evidence = _hybrid(
        monkeypatch,
        "neo4j",
        FakeGraph(),
        FakeFts(),
        FakeSimilarity(),
        sparql,
    )

    assert modes == []
    assert len(evidence) == 3
    assert sparql.calls == []


def test_neo4j_graph_empty_with_other_results_does_not_call_sparql(monkeypatch):
    sparql = FakeSparql()
    fts = FakeFts(
        FtsEvidence(
            search_term="question",
            hits=[FtsHit(uri="u", label="label", score=0.8, snippet="text")],
        )
    )
    similarity = FakeSimilarity(
        SimilarityEvidence(
            hits=[SimilarityHit(uri="u", label="label", score=0.8, text="text")]
        )
    )

    modes, _ = _hybrid(monkeypatch, "neo4j", FakeGraph(), fts, similarity, sparql)

    assert modes == ["fts", "similarity"]
    assert sparql.calls == []


def test_neo4j_failures_do_not_call_legacy_sparql(monkeypatch):
    sparql = FakeSparql()

    with pytest.raises(RuntimeError, match="neo4j graph failed"):
        _hybrid(
            monkeypatch,
            "neo4j",
            FakeGraph(error=RuntimeError("neo4j graph failed")),
            FakeFts(error=RuntimeError("neo4j fts failed")),
            FakeSimilarity(error=RuntimeError("neo4j vector failed")),
            sparql,
        )

    assert sparql.calls == []


def test_legacy_mode_preserves_sparql_fallback(monkeypatch):
    sparql = FakeSparql(
        results=[
            SparqlEvidence(query="primary", triples=[], triple_count=0),
            SparqlEvidence(
                query="fallback",
                triples=[Triple(subject="s", predicate="p", obj="o")],
                triple_count=1,
            ),
        ]
    )

    modes, evidence = _hybrid(
        monkeypatch,
        "legacy",
        FakeGraph(),
        FakeFts(),
        FakeSimilarity(),
        sparql,
    )

    assert modes == ["sparql-fallback"]
    assert evidence[-1].mode == "sparql"
    assert sparql.calls == [
        ("question", 10, 500),
        ("ontology schema classes", 10, 500),
    ]


def test_neo4j_initialization_skips_legacy_graph_client(monkeypatch):
    class FakeNeo4jClient:
        pass

    class FakeNeo4jGraph:
        def __init__(self, client):
            self.client = client

    class FakeNeo4jFts:
        def __init__(self, client):
            self.client = client

    class FakeNeo4jVector:
        def __init__(self, client):
            self.client = client

    class UnexpectedGraphClient:
        def __init__(self):
            raise AssertionError("legacy graph client was constructed")

    class NeverConstructedLegacy:
        def __init__(self, client):
            raise AssertionError("legacy retrieval service was constructed")

    settings = SimpleNamespace(
        retrieval_backend="neo4j",
        fts_backend="neo4j",
        vector_backend="neo4j",
    )
    monkeypatch.setattr(nodes, "_orchestrator", None)
    monkeypatch.setattr(nodes, "get_settings", lambda: settings)

    import app.infrastructure.knowledge_graph.graphdb.client as graphdb_client
    import app.infrastructure.knowledge_graph.neo4j.client as neo4j_client
    import app.infrastructure.retrieval.full_text.service as legacy_fts
    import app.infrastructure.retrieval.neo4j.full_text_service as neo4j_fts
    import app.infrastructure.retrieval.neo4j.graph_service as neo4j_graph
    import app.infrastructure.retrieval.neo4j.vector_service as neo4j_vector
    import app.infrastructure.retrieval.vector.service as legacy_vector

    monkeypatch.setattr(graphdb_client, "get_graphdb_client", UnexpectedGraphClient)
    monkeypatch.setattr(neo4j_client, "Neo4jClient", FakeNeo4jClient)
    monkeypatch.setattr(legacy_fts, "FtsRetrievalService", NeverConstructedLegacy)
    monkeypatch.setattr(legacy_vector, "SimilarityRetrievalService", NeverConstructedLegacy)
    monkeypatch.setattr(neo4j_graph, "Neo4jGraphRetrievalService", FakeNeo4jGraph)
    monkeypatch.setattr(neo4j_fts, "Neo4jFtsRetrievalService", FakeNeo4jFts)
    monkeypatch.setattr(neo4j_vector, "Neo4jVectorRetrievalService", FakeNeo4jVector)

    service = nodes._get_orchestrator()

    assert service._sparql is None
    assert isinstance(service._neo4j, FakeNeo4jGraph)
    assert isinstance(service._fts, FakeNeo4jFts)
    assert isinstance(service._sim, FakeNeo4jVector)
    assert service._neo4j.client is service._fts.client is service._sim.client


def test_legacy_initialization_keeps_sparql_client(monkeypatch):
    class FakeNeo4jClient:
        pass

    class FakeGraph:
        def __init__(self, client):
            self.client = client

    class FakeSparqlService:
        def __init__(self, client):
            self.client = client

    class FakeLegacyFts:
        def __init__(self, client):
            self.client = client

    class FakeLegacyVector:
        def __init__(self, client):
            self.client = client

    graph_client = object()
    settings = SimpleNamespace(
        retrieval_backend="legacy",
        fts_backend="legacy",
        vector_backend="legacy",
    )
    monkeypatch.setattr(nodes, "_orchestrator", None)
    monkeypatch.setattr(nodes, "get_settings", lambda: settings)

    import app.infrastructure.knowledge_graph.graphdb.client as graphdb_client
    import app.infrastructure.knowledge_graph.neo4j.client as neo4j_client
    import app.infrastructure.retrieval.full_text.service as legacy_fts
    import app.infrastructure.retrieval.sparql.service as sparql_service
    import app.infrastructure.retrieval.vector.service as legacy_vector
    import app.infrastructure.retrieval.neo4j.graph_service as neo4j_graph

    monkeypatch.setattr(graphdb_client, "get_graphdb_client", lambda: graph_client)
    monkeypatch.setattr(neo4j_client, "Neo4jClient", FakeNeo4jClient)
    monkeypatch.setattr(sparql_service, "SparqlRetrievalService", FakeSparqlService)
    monkeypatch.setattr(legacy_fts, "FtsRetrievalService", FakeLegacyFts)
    monkeypatch.setattr(legacy_vector, "SimilarityRetrievalService", FakeLegacyVector)
    monkeypatch.setattr(neo4j_graph, "Neo4jGraphRetrievalService", FakeGraph)

    service = nodes._get_orchestrator()

    assert isinstance(service._sparql, FakeSparqlService)
    assert service._sparql.client is graph_client
    assert isinstance(service._fts, FakeLegacyFts)
    assert service._fts.client is graph_client
    assert isinstance(service._sim, FakeLegacyVector)
    assert service._sim.client is graph_client
