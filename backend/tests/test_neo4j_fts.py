from __future__ import annotations

import asyncio

from app.infrastructure.retrieval.neo4j.full_text_service import (
    Neo4jFtsRetrievalService,
)
from app.models.schemas import FtsEvidence


class FakeNeo4jClient:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.calls = []

    async def execute_read_query(self, query, **parameters):
        self.calls.append((query, parameters))
        return self.rows


def test_property_conversion_and_fallbacks():
    service = Neo4jFtsRetrievalService(FakeNeo4jClient())

    assert service._text(["ABC"]) == "ABC"
    assert service._text(["ABC", "DEF"]) == "ABC; DEF"
    assert service._text(None) == ""

    assert service._first_text({"label": ["ABC"]}, "label", "name") == "ABC"
    assert service._first_text({"normalizedLabel": ["ABC"]}, "label", "normalizedLabel") == "ABC"
    assert service._first_text({"name": "ABC"}, "label", "normalizedLabel", "name") == "ABC"
    assert service._local_identifier("https://example.org/pra#ABC") == "ABC"

    assert service._first_text({"description": ["description"]}, "description", "comment", "label") == "description"
    assert service._first_text({"comment": ["comment"]}, "description", "comment", "label") == "comment"
    assert service._first_text({"label": ["label"]}, "description", "comment", "label") == "label"


def test_score_normalization_is_bounded_and_preserves_ranking():
    raw_scores = [3.1, 4.3, 6.9, 8.0, 12.8]
    normalized = [Neo4jFtsRetrievalService._normalize_score(score) for score in raw_scores]

    assert all(0.0 <= score <= 1.0 for score in normalized)
    assert normalized == sorted(normalized)
    assert Neo4jFtsRetrievalService._normalize_score(0) == 0.0
    assert Neo4jFtsRetrievalService._normalize_score(float("nan")) == 0.0


def test_empty_results_return_empty_fts_evidence():
    client = FakeNeo4jClient([])
    evidence = asyncio.run(
        Neo4jFtsRetrievalService(client).retrieve("No matching PRA entity")
    )

    assert isinstance(evidence, FtsEvidence)
    assert evidence.hits == []
    assert client.calls[0][1] == {
        "index_name": "pra_fulltext",
        "search_term": "matching OR PRA OR entity",
        "limit": 10,
    }


def test_mapping_preserves_fts_contract_and_search_term():
    client = FakeNeo4jClient([
        {
            "node": {
                "uri": "https://example.org/pra#activity_1",
                "label": ["Monitor transaction flows"],
                "description": ["Monitor transaction flows and resolve discrepancies."],
            },
            "score": 12.8,
        }
    ])

    evidence = asyncio.run(
        Neo4jFtsRetrievalService(client).retrieve(
            "What activities are associated with business functions?", 5
        )
    )
    hit = evidence.hits[0]

    assert evidence.mode == "fts"
    assert evidence.search_term == "activities OR associated OR business OR functions"
    assert set(hit.model_dump()) == {"uri", "label", "score", "snippet"}
    assert hit.uri.endswith("activity_1")
    assert hit.label == "Monitor transaction flows"
    assert hit.snippet == "Monitor transaction flows and resolve discrepancies."
    assert 0.0 <= hit.score <= 1.0
    assert client.calls[0][1]["limit"] == 5
