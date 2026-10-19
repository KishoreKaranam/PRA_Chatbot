"""Tests for source-document attribution and the /api/documents endpoint."""
from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import documents as documents_api
from app.application.grounding import sources
from app.models.schemas import (
    FtsEvidence,
    FtsHit,
    GroundingClaim,
    GroundingReport,
    Neo4jGraphEvidence,
    Neo4jNode,
    SimilarityEvidence,
    SimilarityHit,
)

PATTERNS = "PRA Patterns guide.docx"
JOURNEY = "PRA Functional descriptions for Payments Journey.xlsx"


class FakeClient:
    """Returns rows shaped like SOURCE_LOOKUP_QUERY results."""

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def execute_read_query(self, query, **params):
        self.calls.append(params)
        names = set(params["names"])
        return [r for r in self.rows if r["name"] in names]


@pytest.fixture
def docs_dir(tmp_path, monkeypatch):
    folder = tmp_path / "documents"
    folder.mkdir()
    (folder / "PRA Patterns guide.pdf").write_bytes(b"%PDF-1.4 test")
    (tmp_path / "secret.pdf").write_bytes(b"%PDF-1.4 secret")
    monkeypatch.setattr(sources, "documents_dir", lambda: folder)
    return folder


def _evidence():
    return [
        FtsEvidence(search_term="x", hits=[
            FtsHit(uri="u1", label="Payment Routing Engine", score=0.9, snippet="routes"),
        ]),
        SimilarityEvidence(hits=[
            SimilarityHit(uri="u2", label="Idempotent Processing", score=0.8, text="pattern"),
        ]),
        Neo4jGraphEvidence(results=[
            Neo4jNode(element_id="1", labels=["Purpose"], properties={"name": "Route payments correctly"}),
        ], result_count=1),
    ]


def test_evidence_names_collects_all_modes_without_duplicates():
    names = sources.evidence_names(_evidence() + _evidence())
    assert names == ["Payment Routing Engine", "Idempotent Processing", "Route payments correctly"]


def test_names_for_claim_prefers_reviewer_refs():
    names = ["Payment Routing Engine", "Idempotent Processing"]
    picked = sources.names_for_claim(
        "Some claim mentioning Idempotent Processing",
        ["payment routing engine"],
        names,
    )
    assert picked == ["Payment Routing Engine"]


def test_names_for_claim_falls_back_to_names_in_claim_text():
    names = ["Payment Routing Engine", "Idempotent Processing", "Fee"]
    picked = sources.names_for_claim("The Payment Routing Engine routes orders.", [], names)
    assert picked == ["Payment Routing Engine"]


def test_pdf_name_and_safe_resolution(docs_dir):
    assert sources.pdf_name_for(PATTERNS) == "PRA Patterns guide.pdf"
    assert sources.resolve_document("PRA Patterns guide.pdf") == docs_dir / "PRA Patterns guide.pdf"
    assert sources.resolve_document("../secret.pdf") is None
    assert sources.resolve_document("..\\secret.pdf") is None
    assert sources.resolve_document(str(docs_dir.parent / "secret.pdf")) is None
    assert sources.resolve_document("PRA Patterns guide.docx") is None


def test_attach_sources_links_supported_claims(docs_dir):
    client = FakeClient([
        {"name": "Payment Routing Engine", "own": JOURNEY, "inherited": []},
        {"name": "Idempotent Processing", "own": PATTERNS, "inherited": []},
        # Purpose has no own source → inherits from its Function
        {"name": "Route payments correctly", "own": None, "inherited": [JOURNEY]},
    ])
    report = GroundingReport(
        claims=[
            GroundingClaim(claim="Routing is done by the engine", supported=True,
                           evidence_refs=["Payment Routing Engine"]),
            GroundingClaim(claim="Idempotent Processing avoids duplicates", supported=True),
            GroundingClaim(claim="Made-up fact", supported=False,
                           evidence_refs=["Payment Routing Engine"]),
        ],
        total_claims=3, supported_claims=2, method="llm",
    )

    result = asyncio.run(sources.attach_sources(report, _evidence(), client))

    first, second, third = result.claims
    assert [d.name for d in first.sources] == [JOURNEY]
    assert first.sources[0].url is None                     # no PDF copy for the xlsx
    assert [d.name for d in second.sources] == [PATTERNS]
    assert second.sources[0].url == "/api/documents/PRA%20Patterns%20guide.pdf"
    assert third.sources == []                              # unsupported claims get no links
    assert {d.name for d in result.documents} == {JOURNEY, PATTERNS}


def test_attach_sources_never_raises():
    class Broken:
        async def execute_read_query(self, *a, **k):
            raise RuntimeError("neo4j down")

    report = GroundingReport(claims=[GroundingClaim(claim="x", supported=True)])
    assert asyncio.run(sources.attach_sources(report, _evidence(), Broken())) is report
    assert asyncio.run(sources.attach_sources(None, _evidence(), Broken())) is None


def test_documents_endpoint_serves_only_known_pdfs(docs_dir):
    app = FastAPI()
    app.include_router(documents_api.router, prefix="/api")
    client = TestClient(app)

    ok = client.get("/api/documents/PRA%20Patterns%20guide.pdf")
    assert ok.status_code == 200
    assert ok.headers["content-type"] == "application/pdf"
    assert ok.headers["content-disposition"].startswith("inline")

    assert client.get("/api/documents/secret.pdf").status_code == 404
    assert client.get("/api/documents/..%2Fsecret.pdf").status_code == 404
    assert client.get("/api/documents/missing.pdf").status_code == 404
