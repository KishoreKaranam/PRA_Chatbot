from __future__ import annotations

import asyncio

from app.infrastructure.retrieval.neo4j.graph_service import Neo4jGraphRetrievalService


class FakeClient:
    def __init__(self, rows=None):
        self.calls = []
        self.rows = rows or []

    async def execute_read_query(self, query, **parameters):
        self.calls.append((query, parameters))
        if "RETURN n.uri AS uri" in query:
            return [{
                "uri": "https://example.org/pra#dom_PaymentInitiation",
                "label": ["Payment Initiation"],
                "normalized_label": ["payment initiation"],
                "labels": ["Resource", "Domain", "MainJourneyDomain"],
            }]
        return self.rows


def test_payment_initiation_resolves_to_domain():
    service = Neo4jGraphRetrievalService(FakeClient())
    entity = asyncio.run(service._resolve_domain("Payment Initiation"))
    assert entity["uri"].endswith("dom_PaymentInitiation")
    assert "Domain" in entity["labels"]


def test_activities_alias_is_recognized():
    assert "Activity" in Neo4jGraphRetrievalService._match_labels("activities")


def test_unknown_scoped_domain_does_not_use_generic_fallback():
    client = FakeClient()
    evidence = asyncio.run(
        Neo4jGraphRetrievalService(client).retrieve(
            "What are the business functions within CompletelyFakeDomain?"
        )
    )
    assert evidence.result_count == 0
    assert all("BusinessFunction" not in call[0] for call in client.calls[1:])


def test_domain_patterns_are_selected_for_supported_questions():
    service = Neo4jGraphRetrievalService(FakeClient())
    assert service._find_pattern("business functions within Payment Initiation", True)[0] == "domain_functions"
    assert service._find_pattern("activities associated with Payment Initiation", True)[0] == "domain_activities"
    assert service._find_pattern("Payment Initiation depend on", True)[0] == "domain_dependencies"


def test_domain_query_uses_resolved_uri_parameter_and_preserves_relationships():
    source = {
        "uri": "https://example.org/pra#dom_PaymentInitiation",
        "label": ["Payment Initiation"],
    }
    target = {
        "uri": "https://example.org/pra#func_PaymentInstructionCapture",
        "label": ["Payment Instruction Capture"],
    }
    activity = {
        "uri": "https://example.org/pra#activity_capture_1",
        "label": ["Capture payment instruction"],
    }
    rows = [{
        "n": source,
        "m": target,
        "k": activity,
        "n_labels": ["Resource", "Domain"],
        "m_labels": ["Resource", "BusinessFunction"],
        "k_labels": ["Resource", "Activity"],
        "r": (source, "hasFunction", target),
        "r2": (target, "hasActivity", activity),
    }]
    client = FakeClient(rows)
    evidence = asyncio.run(
        Neo4jGraphRetrievalService(client).retrieve(
            "What activities are associated with Payment Initiation?"
        )
    )

    assert evidence.result_count == 2
    assert {rel.type for rel in evidence.relationships} == {"hasFunction", "hasActivity"}
    query, parameters = client.calls[1]
    assert "$entity_uri" in query
    assert parameters["entity_uri"].endswith("dom_PaymentInitiation")
    assert "Payment Initiation" not in query


def test_domain_dependencies_include_both_controlled_relationship_queries():
    client = FakeClient()
    asyncio.run(
        Neo4jGraphRetrievalService(client).retrieve(
            "What does Payment Initiation depend on?"
        )
    )
    queries = [call[0] for call in client.calls[1:]]
    assert any("dependsOn" in query for query in queries)
    assert any("dependsOnDomain" in query for query in queries)
