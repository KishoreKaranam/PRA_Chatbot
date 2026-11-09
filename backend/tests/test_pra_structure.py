"""Fix 2: overview questions get the PRA map; named domains get their profile."""
from __future__ import annotations

import asyncio

from app.infrastructure.llm.answer_service import AnswerGenerationService
from app.infrastructure.retrieval.neo4j import pra_structure
from app.infrastructure.retrieval.neo4j.graph_service_current import Neo4jGraphRetrievalService
from app.models.schemas import AgentInstructions

NAMES = [
    ("Payment Initiation", ["Domain"]), ("Order Management", ["Domain"]),
    ("Payment Processing", ["Domain"]), ("Clearing", ["Domain"]), ("Settlement", ["Domain"]),
    ("Financial and Treasury Services", ["Domain"]), ("Inter PSP Interactions", ["Domain"]),
    ("Foreign Exchange Management", ["SupportingDomain"]),
    ("Liquidity Management", ["SupportingDomain"]), ("Financial Reporting", ["SupportingDomain"]),
    ("Treasury and Cash Management", ["SupportingDomain"]),
    ("Transaction Monitoring (AML)", ["SupportingDomain"]),
    ("Market Infrastructure Gateway", ["SupportingDomain"]),
]


class FakeGraph:
    """Answers like the real PRA graph (shapes checked in Neo4j Browser)."""

    def __init__(self):
        self.queries = []

    async def execute_read_query(self, query, **params):
        self.queries.append(query)
        if "normalized_label" in query:                      # domain name resolution
            return [{"name": n, "normalized_label": n.lower(), "labels": l} for n, l in NAMES]
        if "// pra_map_domains" in query:
            return [
                {"domain": "Settlement", "description": "d", "functions": ["Settlement Execution"], "supporting": []},
                {"domain": "Payment Initiation", "description": "d", "functions": ["Instruction Capture"],
                 "supporting": []},
                {"domain": "Payment Processing", "description": "d", "functions": ["Workflow Orchestration"],
                 "supporting": []},
                {"domain": "Clearing", "description": "d", "functions": ["Clearing Submission"], "supporting": []},
                {"domain": "Order Management", "description": "d", "functions": ["Order Registration"],
                 "supporting": []},
                {"domain": "Financial and Treasury Services", "description": "d", "functions": [],
                 "supporting": ["Foreign Exchange Management", "Liquidity Management"]},
                {"domain": "Inter PSP Interactions", "description": "d", "functions": [],
                 "supporting": ["Market Infrastructure Gateway"]},
            ]
        if "// pra_map_support" in query:
            return [{"supporting_domain": "Foreign Exchange Management", "stage": "Settlement",
                     "supports": ["Settlement Execution"], "depends_on": []},
                    {"supporting_domain": "Foreign Exchange Management", "stage": "Payment Processing",
                     "supports": ["Workflow Orchestration"], "depends_on": ["Workflow Orchestration"]}]
        if "// profile_node" in query and params["name"] == "Foreign Exchange Management":
            return [{"name": "Foreign Exchange Management", "labels": ["SupportingDomain"],
                     "description": "Converts currencies.", "layers": ["Financial and Treasury Services"],
                     "functions": [], "supporting": [], "purposes": ["Accurate FX conversion"],
                     "rules": ["Real-time Conversion"]}]
        if "// profile_links" in query and params["name"] == "Foreign Exchange Management":
            fx = "Foreign Exchange Management"
            return [  # exactly the 7 links seen in Neo4j (read from FX's side)
                {"member": fx, "link": "DEPENDS_ON_SUPPORTING", "outgoing": False, "kind": ["Function"],
                 "other": "Workflow Orchestration", "stages": ["Payment Processing"]},
                {"member": fx, "link": "DEPENDS_ON_SUPPORTING", "outgoing": False, "kind": ["Function"],
                 "other": "Settlement Execution", "stages": ["Settlement"]},
                {"member": fx, "link": "DEPENDS_ON_SUPPORTING", "outgoing": False, "kind": ["SupportingDomain"],
                 "other": "Financial Reporting", "stages": []},
                {"member": fx, "link": "DEPENDS_ON_SUPPORTING", "outgoing": True, "kind": ["Function"],
                 "other": "Workflow Orchestration", "stages": ["Payment Processing"]},
                {"member": fx, "link": "DEPENDS_ON_SUPPORTING", "outgoing": True, "kind": ["SupportingDomain"],
                 "other": "Liquidity Management", "stages": []},
                {"member": fx, "link": "PROVIDES_TO_SUPPORTING", "outgoing": True, "kind": ["Function"],
                 "other": "Settlement Execution", "stages": ["Settlement"]},
                {"member": fx, "link": "PROVIDES_TO_SUPPORTING", "outgoing": True, "kind": ["SupportingDomain"],
                 "other": "Financial Reporting", "stages": []},
            ]
        if "// profile_node" in query or "// profile_links" in query:
            return []
        if "CONTAINS]->(f:Function)" in query and "$entity_name" in query:   # domain -> functions pattern
            if params.get("entity_name") == "Payment Processing" and "domain:Domain" in query:
                return [{"n": {"name": "Payment Processing"}, "m": {"name": "Workflow Orchestration"},
                         "n_labels": ["Domain"], "m_labels": ["Function"]}]
            return []
        return []


def _retrieve(question):
    graph = FakeGraph()
    evidence = asyncio.run(Neo4jGraphRetrievalService(graph).retrieve(question))
    return evidence, graph


Q2 = "What does Foreign Exchange Management do and which journey stages does it support?"
Q3 = ("Provide a clear architecture diagram of the Payments Reference Architecture (Payment Initiation, "
      "Order Management, Payment Processing, Inter-PSP Interactions, and supporting domains like FX Management, "
      "Treasury & Cash Management)")


def test_named_supporting_domain_gets_a_profile_instead_of_nothing():
    evidence, _ = _retrieve(Q2)
    assert evidence.result_count > 0                      # was 0 before fix 2
    s = evidence.summary
    assert "Foreign Exchange Management (Supporting domain)" in s
    assert "part of layer: Financial and Treasury Services" in s
    assert "rules: Real-time Conversion" in s
    assert "supports journey stages: Payment Processing, Settlement" in s
    assert "Settlement Execution (Settlement stage)" in s
    assert "depends on journey functions: Workflow Orchestration (Payment Processing stage)" in s
    assert "supports supporting domains: Financial Reporting" in s
    assert "depends on supporting domains: Liquidity Management" in s


def test_architecture_question_gets_the_full_map_with_stages_in_order():
    evidence, graph = _retrieve(Q3)
    s = evidence.summary
    assert "PRA STRUCTURE" in s
    order = [s.index(f"{i}. {name}") for i, name in enumerate(pra_structure.JOURNEY_ORDER, start=1)]
    assert order == sorted(order)                        # 1. Payment Initiation ... 5. Settlement
    assert "Inter PSP Interactions: Market Infrastructure Gateway" in s   # a supporting layer, not a stage
    assert "Foreign Exchange Management → Payment Processing (Workflow Orchestration); Settlement" in s
    assert not any("// profile" in q for q in graph.queries)


def test_list_all_supporting_domains_gets_the_map():
    evidence, _ = _retrieve("List all supporting domains")
    assert "Supporting layers and their supporting domains (2 layers, 3 supporting domains)" in evidence.summary


def test_q1_functions_question_is_unchanged():
    evidence, graph = _retrieve("What are business functions in Payment Processing?")
    assert evidence.summary == ""                        # same fixed pattern as before
    assert {n.element_id for n in evidence.results} == {"Payment Processing", "Workflow Orchestration"}
    assert not any("// profile" in q or "// pra_map" in q for q in graph.queries)


def test_functions_of_a_supporting_domain_falls_back_to_its_profile():
    evidence, _ = _retrieve("What are the functions of FX Management?")
    assert "Foreign Exchange Management (Supporting domain)" in evidence.summary


def test_name_matching_handles_and_ampersand_fx_and_brackets():
    rows = [{"name": n, "labels": l} for n, l in NAMES]
    found = pra_structure.find_named_domains(
        "How do FX Management, Treasury & Cash Management and Transaction Monitoring relate to Settlement?", rows)
    assert [f["name"] for f in found] == ["Foreign Exchange Management", "Treasury and Cash Management",
                                          "Transaction Monitoring (AML)", "Settlement"]


def test_longer_name_wins_over_a_name_inside_it():
    rows = [{"name": "Payment Initiation", "labels": ["Domain"]},
            {"name": "Payment Initiation Channels", "labels": ["SupportingDomain"]}]
    found = pra_structure.find_named_domains("Explain Payment Initiation Channels", rows)
    assert [f["name"] for f in found] == ["Payment Initiation Channels"]


def test_summary_reaches_claude_and_is_counted():
    from structlog.testing import capture_logs
    import structlog
    evidence, _ = _retrieve(Q2)
    svc = AnswerGenerationService.__new__(AnswerGenerationService)
    structlog.reset_defaults()
    with capture_logs() as logs:
        context = svc._build_context([evidence], AgentInstructions())
    assert "PRIMARY GRAPH EVIDENCE" in context and "supports journey stages: Payment Processing, Settlement" in context
    e = next(l for l in logs if l["event"] == "llm_context_built")
    assert e["graph_entities_sent"] == e["graph_entities_found"] > 0


def test_graph_errors_never_break_the_answer():
    class Broken(FakeGraph):
        async def execute_read_query(self, query, **params):
            if "// profile" in query or "// pra_map" in query:
                raise RuntimeError("Cypher syntax error")
            return await super().execute_read_query(query, **params)

    for question in (Q2, Q3):
        evidence = asyncio.run(Neo4jGraphRetrievalService(Broken()).retrieve(question))
        assert evidence.result_count == 0           # same as before fix 2, no crash
