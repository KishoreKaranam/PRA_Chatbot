import asyncio
import math
from types import SimpleNamespace

from app.infrastructure.retrieval.neo4j.vector_service import Neo4jVectorRetrievalService
from app.models.schemas import SimilarityEvidence


class FakeEmbeddingClient:
    def __init__(self, vector=None, error=None):
        self.vector = vector or [0.1, 0.2, 0.3]
        self.error = error
        self.calls = []

        class Embeddings:
            pass

        self.embeddings = Embeddings()
        self.embeddings.create = self.create

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(data=[SimpleNamespace(embedding=self.vector)])


class FakeNeo4jClient:
    def __init__(self, rows=None, error=None):
        self.rows = rows or []
        self.error = error
        self.calls = []

    async def execute_read_query(self, query, **parameters):
        self.calls.append((query, parameters))
        if self.error:
            raise self.error
        return self.rows


def service(client=None, embedding=None):
    svc = Neo4jVectorRetrievalService(
        client or FakeNeo4jClient(),
        embedding_client=embedding or FakeEmbeddingClient(),
    )
    svc._settings = SimpleNamespace(
        embedding_enabled=True,
        embedding_model="text-embedding-3-large",
        azure_openai_endpoint="",
        azure_openai_api_key="",
        openai_api_key="test",
        openai_base_url="https://api.openai.com/v1",
    )
    return svc


def row(uri="u", label=None, description=None, comment=None, node_labels=None, score=0.5):
    return {
        "uri": uri,
        "label": label,
        "description": description,
        "comment": comment,
        "node_labels": node_labels or ["Function", "Activity"],
        "score": score,
    }


def test_query_embedding_generation_and_parameterization():
    client = FakeNeo4jClient([row()])
    embedding = FakeEmbeddingClient([1.0, 2.0])
    evidence = asyncio.run(service(client, embedding).retrieve("question", 5))

    assert isinstance(evidence, SimilarityEvidence)
    assert embedding.calls == [{"input": ["question"], "model": "text-embedding-3-large"}]
    query, params = client.calls[0]
    assert "SEARCH node IN" in query
    assert "VECTOR INDEX pra_embedding_index" in query
    assert params["query_embedding"] == [1.0, 2.0]
    assert params["top_k"] == 5
    assert "question" not in query


def test_list_valued_properties_are_readable():
    hit = Neo4jVectorRetrievalService._to_hit(
        row(
            label=["Payment Initiation", "PI"],
            description=["Creates payment orders"],
            comment=["Business context"],
            node_labels=["Domain"],
        )
    )
    assert hit.label == "Payment Initiation; PI"
    assert hit.text == "Payment Initiation; PI Creates payment orders Business context Domain"
    assert "[" not in hit.text


def test_score_preservation_and_ranking_order():
    rows = [row(uri="a", label=["A"], score=0.6), row(uri="b", label=["B"], score=0.95)]
    evidence = asyncio.run(service(FakeNeo4jClient(rows)).retrieve("question", 2))
    assert [hit.uri for hit in evidence.hits] == ["b", "a"]
    assert math.isclose(evidence.hits[0].score, 0.9, abs_tol=1e-12)
    assert math.isclose(evidence.hits[1].score, 0.2, abs_tol=1e-12)


def test_neo4j_score_conversion_uses_inverse_cosine_mapping():
    values = [0.50, 0.60, 0.75, 0.80, 0.8839, 0.95, 1.00]
    converted = [Neo4jVectorRetrievalService._normalize_neo4j_vector_score(value) for value in values]
    expected = [0.0, 0.2, 0.5, 0.6, 0.7678, 0.9, 1.0]
    assert all(math.isclose(actual, wanted, abs_tol=1e-12) for actual, wanted in zip(converted, expected))


def test_neo4j_score_conversion_preserves_order():
    raw_scores = [0.50, 0.60, 0.75, 0.95]
    converted = [Neo4jVectorRetrievalService._normalize_neo4j_vector_score(value) for value in raw_scores]
    assert converted == sorted(converted)


def test_empty_results_return_empty_evidence():
    evidence = asyncio.run(service(FakeNeo4jClient([])).retrieve("question", 5))
    assert isinstance(evidence, SimilarityEvidence)
    assert evidence.mode == "similarity"
    assert evidence.hits == []
    assert "no results" in evidence.note.lower()


def test_embedding_error_returns_controlled_empty_evidence():
    evidence = asyncio.run(
        service(embedding=FakeEmbeddingClient(error=RuntimeError("provider unavailable"))).retrieve(
            "question", 5
        )
    )
    assert isinstance(evidence, SimilarityEvidence)
    assert evidence.hits == []
    assert "failed" in evidence.note.lower()


def test_neo4j_error_returns_controlled_empty_evidence():
    evidence = asyncio.run(
        service(FakeNeo4jClient(error=RuntimeError("database unavailable"))).retrieve("question", 5)
    )
    assert isinstance(evidence, SimilarityEvidence)
    assert evidence.hits == []
    assert "failed" in evidence.note.lower()


def test_max_results_is_forwarded_and_zero_skips_dependencies():
    client = FakeNeo4jClient([row()])
    embedding = FakeEmbeddingClient()
    evidence = asyncio.run(service(client, embedding).retrieve("question", 0))
    assert evidence.hits == []
    assert client.calls == []
    assert embedding.calls == []
