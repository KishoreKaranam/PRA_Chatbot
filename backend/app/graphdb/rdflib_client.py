"""
In-memory RDF graph backend using rdflib.

Loads .ttl file(s) from disk and executes SPARQL queries locally.
No external database required — fully self-contained.

Supports:
  - SPARQL SELECT (returns same binding format as GraphDB HTTP client)
  - SPARQL CONSTRUCT (returns list of {subject, predicate, obj} dicts)

Limitations vs GraphDB:
  - No Lucene FTS (regex fallback is used automatically by fts_service)
  - Performance is fine for <100k triples; for larger graphs use GraphDB
"""
from __future__ import annotations

import os
from pathlib import Path

import rdflib
from rdflib import Graph, Namespace
from rdflib.plugins.sparql import prepareQuery

from app.graphdb.base import GraphBackend
from app.core.log_config import get_logger

logger = get_logger(__name__)

# Standard prefixes (same as COMMON_PREFIXES in client.py)
_INIT_BINDINGS = {
    "rdf": Namespace("http://www.w3.org/1999/02/22-rdf-syntax-ns#"),
    "rdfs": Namespace("http://www.w3.org/2000/01/rdf-schema#"),
    "owl": Namespace("http://www.w3.org/2002/07/owl#"),
    "xsd": Namespace("http://www.w3.org/2001/XMLSchema#"),
    "skos": Namespace("http://www.w3.org/2004/02/skos/core#"),
    "dcterms": Namespace("http://purl.org/dc/terms/"),
    "prov": Namespace("http://www.w3.org/ns/prov#"),
    "pra": Namespace("https://example.org/pra#"),
}

# The prefix block that client.py prepends to every query
COMMON_PREFIXES = """\
PREFIX rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl:   <http://www.w3.org/2002/07/owl#>
PREFIX xsd:   <http://www.w3.org/2001/XMLSchema#>
PREFIX skos:  <http://www.w3.org/2004/02/skos/core#>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX prov:  <http://www.w3.org/ns/prov#>
PREFIX pra:   <https://example.org/pra#>
PREFIX luc:   <http://www.ontotext.com/connectors/lucene#>
PREFIX luc-index: <http://www.ontotext.com/connectors/lucene/instance#>
"""


class RDFLibClient(GraphBackend):
    """
    In-memory SPARQL backend using rdflib.

    Load TTL files from a directory or a single file path.
    All SPARQL queries execute locally — zero network dependencies.
    """

    def __init__(self, ttl_path: str) -> None:
        """
        Args:
            ttl_path: Path to a .ttl file or a directory containing .ttl files.
        """
        self._graph = Graph()
        self._load(ttl_path)

    def _load(self, ttl_path: str) -> None:
        """Load one or more TTL files into the in-memory graph."""
        path = Path(ttl_path)
        if not path.exists():
            raise FileNotFoundError(f"TTL path not found: {ttl_path}")

        if path.is_file():
            self._graph.parse(str(path), format="turtle")
            logger.info("rdflib_loaded_file", path=str(path), triples=len(self._graph))
        elif path.is_dir():
            ttl_files = list(path.glob("*.ttl"))
            if not ttl_files:
                raise FileNotFoundError(f"No .ttl files found in: {ttl_path}")
            for f in ttl_files:
                self._graph.parse(str(f), format="turtle")
            logger.info("rdflib_loaded_dir", path=str(path), files=len(ttl_files), triples=len(self._graph))
        else:
            raise ValueError(f"TTL path is neither file nor directory: {ttl_path}")

        # Bind common namespaces for cleaner query output
        for prefix, ns in _INIT_BINDINGS.items():
            self._graph.bind(prefix, ns)

    @property
    def triple_count(self) -> int:
        """Number of triples currently loaded."""
        return len(self._graph)

    # ── SPARQL SELECT ─────────────────────────────────────────────────────────

    async def select(self, sparql: str) -> list[dict]:
        """Execute SPARQL SELECT and return GraphDB-compatible bindings."""
        full_query = COMMON_PREFIXES + "\n" + sparql
        try:
            results = self._graph.query(full_query)
        except Exception as e:
            logger.error("rdflib_select_error", error=str(e), query=sparql[:200])
            return []

        bindings = []
        for row in results:
            binding = {}
            for var in results.vars:
                val = row[var]
                if val is None:
                    continue
                binding[str(var)] = _rdflib_term_to_binding(val)
            bindings.append(binding)
        return bindings

    async def select_get(self, sparql: str) -> list[dict]:
        """
        Same as select() — rdflib doesn't differentiate GET/POST.
        GraphDB Lucene queries will fail gracefully (no luc: support),
        causing FTS service to fall through to regex fallback.
        """
        return await self.select(sparql)

    # ── SPARQL CONSTRUCT ──────────────────────────────────────────────────────

    async def construct(self, sparql: str) -> list[dict[str, str]]:
        """Execute SPARQL CONSTRUCT and return {subject, predicate, obj} dicts."""
        full_query = COMMON_PREFIXES + "\n" + sparql
        try:
            results = self._graph.query(full_query)
        except Exception as e:
            logger.error("rdflib_construct_error", error=str(e), query=sparql[:200])
            return []

        triples = []
        for s, p, o in results:
            triples.append({
                "subject": str(s),
                "predicate": str(p),
                "obj": _format_object(o),
            })
        return triples

    async def close(self) -> None:
        """Release graph memory."""
        self._graph = Graph()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _rdflib_term_to_binding(term) -> dict:
    """Convert an rdflib term to a SPARQL JSON result binding dict."""
    from rdflib import URIRef, Literal, BNode

    if isinstance(term, URIRef):
        return {"type": "uri", "value": str(term)}
    elif isinstance(term, Literal):
        result = {"type": "literal", "value": str(term)}
        if term.datatype:
            result["datatype"] = str(term.datatype)
        if term.language:
            result["xml:lang"] = str(term.language)
        return result
    elif isinstance(term, BNode):
        return {"type": "bnode", "value": str(term)}
    else:
        return {"type": "literal", "value": str(term)}


def _format_object(term) -> str:
    """Format an rdflib term as a string suitable for the obj field."""
    from rdflib import URIRef, Literal

    if isinstance(term, URIRef):
        return str(term)
    elif isinstance(term, Literal):
        return str(term)
    else:
        return str(term)
