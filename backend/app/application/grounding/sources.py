"""
Source-document attribution for grounding claims.

Every PRA graph node that was loaded from a file carries a `source` property
with that file's name (e.g. "PRA Patterns guide.docx"). Detail nodes such as
Purpose, Rule or PostCondition have no `source` of their own, so they inherit
it from the nodes they are directly connected to (their Function, Pattern ...).

This module:
  1. collects the names of the evidence items the answer was built from,
  2. looks up each name's source document(s) in Neo4j (own or inherited),
  3. attaches those documents to each supported claim in the GroundingReport,
  4. adds a link to a PDF copy when one exists in the documents folder.

It never raises: on any failure the report is returned unchanged.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import quote

from app.core.log_config import get_logger
from app.core.settings import get_settings
from app.models.schemas import (
    DocumentRef,
    FtsEvidence,
    GroundingReport,
    Neo4jGraphEvidence,
    SimilarityEvidence,
)

logger = get_logger(__name__)

MAX_SOURCES_PER_CLAIM = 3
MIN_NAME_LENGTH = 4          # ignore very short names when matching free text
MAX_NAMES_TO_LOOK_UP = 300

# One round trip: a node's own source, or the sources of its direct neighbours.
SOURCE_LOOKUP_QUERY = """
UNWIND $names AS nm
MATCH (n) WHERE n.name = nm
OPTIONAL MATCH (n)--(m) WHERE n.source IS NULL AND m.source IS NOT NULL
RETURN nm AS name, n.source AS own, collect(DISTINCT m.source) AS inherited
"""

DOCUMENTS_URL_PREFIX = "/api/documents/"

_neo4j_client: Any | None = None


# ── Documents folder ──────────────────────────────────────────────────────────

def documents_dir() -> Path:
    """Folder that holds the PDF copies of the source documents."""
    configured = get_settings().documents_dir.strip()
    if configured:
        return Path(configured).expanduser().resolve()
    # backend/app/application/grounding/sources.py → backend/documents
    return Path(__file__).resolve().parents[3] / "documents"


def pdf_name_for(source: str) -> str:
    """'PRA Patterns guide.docx' → 'PRA Patterns guide.pdf'."""
    return f"{Path(source).stem}.pdf"


def resolve_document(filename: str) -> Path | None:
    """
    Return the path of a PDF in the documents folder, or None.

    Only exact file names that are actually listed in the folder are accepted,
    so a crafted name ("..\\..\\secrets.pdf", absolute paths, ...) can never
    reach a file outside it.
    """
    if not filename or not filename.lower().endswith(".pdf"):
        return None
    folder = documents_dir()
    if not folder.is_dir():
        return None
    for entry in folder.iterdir():
        if entry.is_file() and entry.name == filename:
            return entry
    return None


def make_document_ref(source: str) -> DocumentRef:
    pdf = pdf_name_for(source)
    url = f"{DOCUMENTS_URL_PREFIX}{quote(pdf)}" if resolve_document(pdf) else None
    return DocumentRef(name=source, url=url)


# ── Evidence names ────────────────────────────────────────────────────────────

def evidence_names(evidence: list) -> list[str]:
    """Distinct node names that appear in the evidence, in first-seen order."""
    seen: dict[str, None] = {}

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if text:
            seen.setdefault(text, None)

    for ev in evidence or []:
        if isinstance(ev, FtsEvidence):
            for hit in ev.hits:
                add(hit.label)
        elif isinstance(ev, SimilarityEvidence):
            for hit in ev.hits:
                add(hit.label)
        elif isinstance(ev, Neo4jGraphEvidence):
            for node in ev.results:
                props = node.properties or {}
                add(props.get("name") or props.get("label"))
    return list(seen)[:MAX_NAMES_TO_LOOK_UP]


# ── Claim ↔ evidence matching ─────────────────────────────────────────────────

def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9&]+", " ", text.lower())).strip()


def names_for_claim(claim_text: str, refs: list[str], names: list[str]) -> list[str]:
    """
    Pick the evidence names a claim relies on.

    Prefer the reviewer's own evidence_refs (matched loosely against the names);
    fall back to evidence names mentioned word-for-word in the claim text.
    """
    normalized = {name: _norm(name) for name in names}

    matched: list[str] = []
    for ref in refs or []:
        r = _norm(ref)
        if not r:
            continue
        for name, n in normalized.items():
            if len(n) < MIN_NAME_LENGTH or name in matched:
                continue
            if r == n or n in r or (len(r) >= MIN_NAME_LENGTH and r in n):
                matched.append(name)
    if matched:
        return matched

    claim = f" {_norm(claim_text)} "
    return [
        name for name, n in normalized.items()
        if len(n) >= MIN_NAME_LENGTH and f" {n} " in claim
    ]


def pick_sources(names: list[str], sources_by_name: dict[str, list[str]]) -> list[str]:
    """Most frequently referenced documents first, capped."""
    counts: Counter[str] = Counter()
    for name in names:
        for source in sources_by_name.get(name, []):
            counts[source] += 1
    return [source for source, _ in counts.most_common(MAX_SOURCES_PER_CLAIM)]


# ── Neo4j lookup ──────────────────────────────────────────────────────────────

def _get_client():
    global _neo4j_client
    if _neo4j_client is None:
        from app.infrastructure.knowledge_graph.neo4j.client import Neo4jClient
        _neo4j_client = Neo4jClient()
    return _neo4j_client


async def lookup_sources(names: list[str], client=None) -> dict[str, list[str]]:
    """Map each node name to its source document(s): own, else inherited."""
    if not names:
        return {}
    client = client or _get_client()
    rows = await client.execute_read_query(SOURCE_LOOKUP_QUERY, names=names)

    result: dict[str, list[str]] = {}
    for row in rows:
        name = str(row.get("name") or "")
        own = row.get("own")
        found = [str(own)] if own else [str(s) for s in (row.get("inherited") or []) if s]
        bucket = result.setdefault(name, [])
        for source in found:
            if source not in bucket:
                bucket.append(source)
    return result


# ── Public entry point ────────────────────────────────────────────────────────

async def prefetch_sources(evidence: list, client=None) -> dict[str, list[str]] | None:
    """Look up the evidence's source documents ahead of time. Never raises.

    The lookup only depends on the retrieved evidence, not on the evidence
    check, so it can run while the answer is being written.
    """
    try:
        return await lookup_sources(evidence_names(evidence), client)
    except Exception as exc:
        logger.warning("grounding_sources_prefetch_failed", error=str(exc))
        return None


async def attach_sources(
    report: GroundingReport | None,
    evidence: list,
    client=None,
    sources_by_name: dict[str, list[str]] | None = None,
    quiet: bool = False,
) -> GroundingReport | None:
    """Attach source documents to every supported claim. Never raises."""
    if report is None or not report.claims:
        return report
    try:
        names = evidence_names(evidence)
        if sources_by_name is None:
            sources_by_name = await lookup_sources(names, client)
        if not sources_by_name:
            return report

        refs_cache: dict[str, DocumentRef] = {}

        def ref(source: str) -> DocumentRef:
            if source not in refs_cache:
                refs_cache[source] = make_document_ref(source)
            return refs_cache[source]

        claims = []
        used: list[str] = []
        for claim in report.claims:
            if not claim.supported:
                claims.append(claim)
                continue
            claim_sources = pick_sources(
                names_for_claim(claim.claim, claim.evidence_refs, names),
                sources_by_name,
            )
            for source in claim_sources:
                if source not in used:
                    used.append(source)
            claims.append(claim.model_copy(update={"sources": [ref(s) for s in claim_sources]}))

        if not quiet:
            logger.info(
                "grounding_sources_attached",
                documents=used,
                claims_with_sources=sum(1 for c in claims if c.sources),
                total_claims=len(claims),
            )
        return report.model_copy(update={
            "claims": claims,
            "documents": [ref(s) for s in used],
        })
    except Exception as exc:
        logger.warning("grounding_sources_failed", error=str(exc))
        return report
