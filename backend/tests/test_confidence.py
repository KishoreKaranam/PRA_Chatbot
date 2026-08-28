from app.infrastructure.llm.answer_service import AnswerGenerationService
from app.models.schemas import (
    FtsEvidence,
    FtsHit,
    Neo4jGraphEvidence,
    Neo4jNode,
    Neo4jRelationship,
    SimilarityEvidence,
    SimilarityHit,
    SparqlEvidence,
    Triple,
)


def service() -> AnswerGenerationService:
    return AnswerGenerationService.__new__(AnswerGenerationService)


def neo4j_evidence(result_count: int = 25) -> Neo4jGraphEvidence:
    source_id = "source-1"
    target_id = "target-1"
    return Neo4jGraphEvidence(
        query=(
            "MATCH (source:BusinessFunction)-[r:hasActivity]->(target:Activity) "
            "RETURN source AS n, r, target AS m"
        ),
        results=[
            Neo4jNode(
                element_id=source_id,
                labels=["BusinessFunction"],
                properties={"label": "Payments", "description": "Payment function"},
            ),
            Neo4jNode(
                element_id=target_id,
                labels=["Activity"],
                properties={"label": "Monitor flows", "description": "Monitor flows"},
            ),
        ],
        relationships=[
            Neo4jRelationship(
                element_id="rel-1",
                type="hasActivity",
                start_node=source_id,
                end_node=target_id,
                properties={},
            )
        ],
        result_count=result_count,
    )


def test_neo4j_relationship_question_has_bounded_graph_confidence():
    score = service()._estimate_confidence([neo4j_evidence()], ["neo4j"])
    assert 0.0 < score <= 0.55


def test_combined_neo4j_fts_and_semantic_evidence_contributes():
    fts = FtsEvidence(
        search_term="activity",
        hits=[FtsHit(uri="u", label="Activity", score=0.8, snippet="activity")],
    )
    semantic = SimilarityEvidence(
        hits=[SimilarityHit(uri="u", label="Activity", score=0.9, text="activity")]
    )
    score = service()._estimate_confidence([neo4j_evidence(), fts, semantic], ["neo4j", "fts", "similarity"])
    assert score > 0.55
    assert score < 1.0


def test_no_neo4j_results_contribute_zero_graph_quality():
    empty = neo4j_evidence(result_count=0).model_copy(update={"relationships": []})
    assert service()._estimate_confidence([empty], ["neo4j"]) == 0.0


def test_no_semantic_results_contribute_zero_semantic_quality():
    score_without_semantic = service()._estimate_confidence([neo4j_evidence()], ["neo4j"])
    score_with_empty_semantic = service()._estimate_confidence(
        [neo4j_evidence(), SimilarityEvidence(hits=[])], ["neo4j", "similarity"]
    )
    assert score_with_empty_semantic == score_without_semantic


def test_existing_graphdb_sparql_evidence_contributes_graph_quality():
    evidence = SparqlEvidence(
        query="CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }",
        triples=[Triple(subject="s", predicate="p", obj="o")] * 10,
        triple_count=10,
    )
    score = service()._estimate_confidence([evidence], ["sparql"])
    assert score == 0.55 * 0.5
