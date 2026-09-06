from types import SimpleNamespace

from app.orchestration.langgraph import nodes


class LegacyVector:
    def __init__(self, client):
        self.client = client


class Neo4jVector:
    def __init__(self, client):
        self.client = client


def test_neo4j_vector_backend_is_selected(monkeypatch):
    monkeypatch.setattr(nodes, "get_settings", lambda: SimpleNamespace(vector_backend="neo4j"))
    service = nodes._build_vector_service(object(), object(), LegacyVector, Neo4jVector)
    assert isinstance(service, Neo4jVector)


def test_legacy_vector_backend_is_selected(monkeypatch):
    monkeypatch.setattr(nodes, "get_settings", lambda: SimpleNamespace(vector_backend="legacy"))
    service = nodes._build_vector_service(object(), object(), LegacyVector, Neo4jVector)
    assert isinstance(service, LegacyVector)
