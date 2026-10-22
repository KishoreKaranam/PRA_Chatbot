"""The llm_context_built log line reports what the search FOUND vs what was SENT to Claude."""
from __future__ import annotations

import structlog
from structlog.testing import capture_logs

from app.infrastructure.llm import answer_service as svc_module
from app.infrastructure.llm.answer_service import AnswerGenerationService
from app.models.schemas import (
    AgentInstructions,
    FtsEvidence,
    FtsHit,
    Neo4jGraphEvidence,
    Neo4jNode,
    SimilarityEvidence,
    SimilarityHit,
)


def _service() -> AnswerGenerationService:
    # Skip __init__ (no API clients needed for building the context text).
    return AnswerGenerationService.__new__(AnswerGenerationService)


def _functions_without_relationships(n: int = 16) -> Neo4jGraphEvidence:
    """Same shape as 'What are business functions in Payment Processing?':
    nodes come back, but the query returns no relationship objects."""
    nodes = [Neo4jNode(element_id="d", labels=["Domain"], properties={"name": "Payment Processing"})]
    nodes += [
        Neo4jNode(element_id=f"f{i}", labels=["Function"], properties={"name": f"Function {i}"})
        for i in range(n - 1)
    ]
    return Neo4jGraphEvidence(query="MATCH (domain:Domain)-[:CONTAINS]->(f)", results=nodes, result_count=n)


def _search_hits():
    return [
        FtsEvidence(search_term="x", hits=[FtsHit(uri="u", label="A", score=0.9, snippet="s")]),
        SimilarityEvidence(hits=[SimilarityHit(uri="u2", label="B", score=0.8, text="t"),
                                 SimilarityHit(uri="u3", label="C", score=0.7, text="t")]),
    ]


def _event(logs, purpose):
    return next(e for e in logs if e["event"] == "llm_context_built" and e["purpose"] == purpose)


def test_logs_found_vs_sent_for_graph_nodes_without_relationships():
    structlog.reset_defaults()
    with capture_logs() as logs:
        context = _service()._build_context(
            [_functions_without_relationships(), *_search_hits()], AgentInstructions())
    e = _event(logs, "answer")
    assert e["graph_entities_found"] == 16
    assert e["graph_relationships_found"] == 0
    # Fix 1: graph entities without relationships now reach Claude.
    # (Before the fix this was graph_entities_sent == 0.)
    assert e["graph_entities_sent"] == 16
    assert "Function 3" in context
    assert "Payment Processing" in context
    assert e["fts_hits_found"] == e["fts_hits_sent"] == 1
    assert e["similarity_hits_found"] == e["similarity_hits_sent"] == 2
    assert e["context_tokens_est"] == len(context) // 4


def test_review_purpose_is_logged_separately():
    structlog.reset_defaults()
    with capture_logs() as logs:
        _service()._build_context(_search_hits(), AgentInstructions(), purpose="review")
    assert _event(logs, "review")["similarity_hits_sent"] == 2


def test_context_dump_only_when_enabled(tmp_path, monkeypatch):
    saved = []
    monkeypatch.setattr(AnswerGenerationService, "_dump_context", staticmethod(lambda c, p: saved.append(p)))

    class S:  # minimal settings stand-in
        log_llm_context = False

    monkeypatch.setattr(svc_module, "get_settings", lambda: S)
    _service()._build_context(_search_hits(), AgentInstructions())
    assert saved == []

    S.log_llm_context = True
    _service()._build_context(_search_hits(), AgentInstructions())
    assert saved == ["answer"]


def test_dump_writes_file(tmp_path, monkeypatch):
    # _dump_context builds its folder from this module's __file__ (backend/app/infrastructure/llm/...)
    fake_backend = tmp_path / "backend"
    fake_file = fake_backend / "app" / "infrastructure" / "llm" / "answer_service.py"
    monkeypatch.setattr(svc_module, "__file__", str(fake_file))
    AnswerGenerationService._dump_context("the exact context", "answer")
    files = list((fake_backend / "logs" / "llm_context").glob("*_answer.txt"))
    assert len(files) == 1
    assert files[0].read_text(encoding="utf-8") == "the exact context"


def test_entities_are_grouped_with_names_and_descriptions():
    ev = Neo4jGraphEvidence(query="q", result_count=2, results=[
        Neo4jNode(element_id="d", labels=["Domain"], properties={"name": "Payment Processing",
                                                                 "description": "Decides how orders are processed"}),
        Neo4jNode(element_id="f", labels=["Function"], properties={"name": "Workflow Orchestration",
                                                                   "description": "Controls execution"}),
    ])
    context = _service()._build_context([ev], AgentInstructions())
    assert "PRIMARY GRAPH EVIDENCE" in context
    assert "Domain:\n  - Payment Processing: Decides how orders are processed" in context
    assert "Function:\n  - Workflow Orchestration: Controls execution" in context


def test_relationship_results_show_names_not_internal_ids():
    from app.models.schemas import Neo4jRelationship
    ev = Neo4jGraphEvidence(query="q", result_count=2, results=[
        Neo4jNode(element_id="4:abc:1", labels=["Function"], properties={"name": "Order Registration"}),
        Neo4jNode(element_id="4:abc:2", labels=["Rule"], properties={"name": "Mandatory fields"}),
    ], relationships=[Neo4jRelationship(element_id="r1", type="HAS_RULE", start_node="4:abc:1",
                                         end_node="4:abc:2", properties={})])
    structlog.reset_defaults()
    with capture_logs() as logs:
        context = _service()._build_context([ev], AgentInstructions())
    assert "label: Order Registration" in context and "label: Mandatory fields" in context
    assert "label: 4:abc:1" not in context
    e = _event(logs, "answer")
    assert e["graph_relationships_sent"] == 1 and e["graph_entities_sent"] == 2


def test_entity_cap():
    nodes = [Neo4jNode(element_id=str(i), labels=["Rule"], properties={"name": f"R{i}"}) for i in range(50)]
    context = _service()._build_context([Neo4jGraphEvidence(query="q", results=nodes, result_count=50)],
                                        AgentInstructions())
    assert "R39" in context and "R40" not in context and "(+10 more not shown)" in context
