"""
Low-level SPARQL HTTP client for GraphDB.

All queries go through the SPARQL endpoint:
  GET/POST http://<host>:<port>/repositories/<repo>
  POST     http://<host>:<port>/repositories/<repo>/statements  (updates)

GraphDB FTS uses the Lucene connector:
  PREFIX luc: <http://www.ontotext.com/connectors/lucene#>
  PREFIX luc-index: <http://www.ontotext.com/connectors/lucene/instance#>
"""
from __future__ import annotations

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.infrastructure.knowledge_graph.base import GraphBackend
from app.core.settings import get_settings
from app.core.log_config import get_logger

logger = get_logger(__name__)

# Ontology namespace used throughout the PRA_V2 repository
PRA_NS = "https://example.org/pra#"
PRA_INSTANCE_NS = "https://example.org/pra#"

# Common prefix block appended to every SPARQL query
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


class GraphDBClient(GraphBackend):
    """Thread-safe, async SPARQL client for one GraphDB repository."""

    def __init__(self) -> None:
        settings = get_settings()
        self._endpoint = (
            f"{settings.graphdb_base_url}/repositories/{settings.graphdb_repository}"
        )
        auth = None
        if settings.graphdb_username:
            auth = (settings.graphdb_username, settings.graphdb_password)
        self._client = httpx.AsyncClient(
            auth=auth,
            headers={"Accept": "application/sparql-results+json"},
            timeout=60.0,
        )

    # ── Core query ────────────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    async def select(self, sparql: str) -> list[dict]:
        """Execute a SPARQL SELECT via POST and return the bindings list."""
        query = COMMON_PREFIXES + "\n" + sparql
        logger.debug("sparql_select", query=query[:200])
        resp = await self._client.post(
            self._endpoint,
            data={"query": query},
            headers={"Content-Type": "application/x-www-form-urlencoded",
                      "Accept": "application/sparql-results+json"},
        )
        resp.raise_for_status()
        return resp.json().get("results", {}).get("bindings", [])

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    async def select_get(self, sparql: str) -> list[dict]:
        """
        Execute a SPARQL SELECT via GET (required for GraphDB Lucene connector queries).
        The connector evaluates luc:query only when the request is a GET.
        """
        query = COMMON_PREFIXES + "\n" + sparql
        logger.debug("sparql_select_get", query=query[:200])
        resp = await self._client.get(
            self._endpoint,
            params={"query": query},
            headers={"Accept": "application/sparql-results+json"},
        )
        resp.raise_for_status()
        return resp.json().get("results", {}).get("bindings", [])

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    async def construct(self, sparql: str) -> list[dict[str, str]]:
        """
        Execute a SPARQL CONSTRUCT and return a list of
        {subject, predicate, object} dicts (parsed from N-Triples).
        """
        query = COMMON_PREFIXES + "\n" + sparql
        logger.debug("sparql_construct", query=query[:200])
        resp = await self._client.post(
            self._endpoint,
            data={"query": query},
            headers={"Content-Type": "application/x-www-form-urlencoded",
                      "Accept": "application/n-triples"},
        )
        resp.raise_for_status()
        return _parse_ntriples(resp.text)

    async def close(self) -> None:
        await self._client.aclose()


# ── N-Triples parser (lightweight) ───────────────────────────────────────────

def _parse_ntriples(text: str) -> list[dict[str, str]]:
    """Parse N-Triples text into a list of {subject, predicate, obj} dicts."""
    triples: list[dict[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Remove trailing ' .'
        if line.endswith(" ."):
            line = line[:-2].rstrip()
        parts = _split_ntriples_line(line)
        if len(parts) == 3:
            triples.append(
                {"subject": parts[0], "predicate": parts[1], "obj": parts[2]}
            )
    return triples


def _split_ntriples_line(line: str) -> list[str]:
    """Very simple tokeniser for N-Triples lines (handles URIs and literals)."""
    tokens: list[str] = []
    i = 0
    while i < len(line) and len(tokens) < 3:
        # Skip whitespace
        while i < len(line) and line[i] in (" ", "\t"):
            i += 1
        if i >= len(line):
            break
        if line[i] == "<":
            # URI reference
            end = line.index(">", i)
            tokens.append(line[i + 1 : end])
            i = end + 1
        elif line[i] == '"':
            # Literal
            end = i + 1
            while end < len(line):
                if line[end] == "\\" :
                    end += 2
                    continue
                if line[end] == '"':
                    break
                end += 1
            full = line[i : end + 1]
            # include datatype / lang tag
            rest_start = end + 1
            while rest_start < len(line) and line[rest_start] in (" ", "\t"):
                rest_start += 1
            rest_end = rest_start
            while rest_end < len(line) and line[rest_end] not in (" ", "\t"):
                rest_end += 1
            tokens.append((full + line[rest_start:rest_end]).strip())
            i = rest_end
        elif line[i] == "_":
            # Blank node
            end = i
            while end < len(line) and line[end] not in (" ", "\t"):
                end += 1
            tokens.append(line[i:end])
            i = end
        else:
            i += 1
    return tokens


# ── Singleton accessor ────────────────────────────────────────────────────────
_client_instance: GraphBackend | None = None


def get_graphdb_client() -> GraphBackend:
    """
    Return the configured graph backend (singleton).

    - GRAPH_BACKEND=graphdb → GraphDBClient (HTTP to running GraphDB)
    - GRAPH_BACKEND=rdflib  → RDFLibClient  (in-memory, loads TTL files)
    """
    global _client_instance
    if _client_instance is None:
        settings = get_settings()
        backend = settings.graph_backend.lower()

        if backend == "rdflib":
            from app.infrastructure.knowledge_graph.rdflib.client import RDFLibClient
            if not settings.ttl_file_path:
                raise ValueError(
                    "GRAPH_BACKEND=rdflib but TTL_FILE_PATH is not set. "
                    "Point it to a .ttl file or directory."
                )
            _client_instance = RDFLibClient(settings.ttl_file_path)
            logger.info("graph_backend_init", backend="rdflib", path=settings.ttl_file_path)
        else:
            _client_instance = GraphDBClient()
            logger.info("graph_backend_init", backend="graphdb")

    return _client_instance
