"""
Full-Text Search (FTS) retrieval service.

GraphDB ships with a built-in Lucene FTS connector.
The repository config has:
  enable-fts-index = true
  fts-indexes = ("default" "iri")
  fts-string-literals-index = "default"

That means we can run FTS via the Lucene connector syntax OR via the
built-in fts:search magic predicate available in GraphDB:

  SELECT ?entity ?score ?snippet WHERE {
    ?entity <http://www.ontotext.com/owlim/lucene#> "payment" .
    ...
  }

GraphDB ≥ 9.x also exposes the standard FTS via:
  PREFIX luc: <http://www.ontotext.com/connectors/lucene#>

We use the simpler built-in magic predicate approach below.
"""
from __future__ import annotations

import re
from app.graphdb.client import GraphDBClient
from app.models.schemas import FtsEvidence, FtsHit
from app.core.log_config import get_logger

logger = get_logger(__name__)

# GraphDB built-in FTS predicate URI (fallback only)
GRAPHDB_FTS_PRED = "http://www.ontotext.com/owlim/lucene#"

# Lucene connector name (created by create_connector.py / 01_create_fts_connector.sparql)
LUCENE_CONNECTOR = "pra_connector"

# Fields to search and return (PRA_V2)
FTS_SEARCH_PROPERTIES = [
    "rdfs:label",
    "dcterms:description",
    "rdfs:comment",
]


class FtsRetrievalService:
    """Full-text search retrieval using GraphDB's built-in Lucene index."""

    def __init__(self, client: GraphDBClient) -> None:
        self._db = client

    async def retrieve(self, question: str, max_results: int = 10) -> FtsEvidence:
        """Search the FTS index and return matching entities with snippets."""
        search_term = self._build_search_term(question)
        hits = await self._run_fts(search_term, max_results)
        logger.info("fts_retrieve", hits=len(hits), term=search_term)
        return FtsEvidence(search_term=search_term, hits=hits)

    # ── Search term builder ───────────────────────────────────────────────────

    def _build_search_term(self, question: str) -> str:
        """Extract a Lucene query string from the user question."""
        STOP = {
            "what", "which", "where", "when", "how", "does", "list", "tell",
            "show", "give", "are", "the", "all", "and", "for", "about",
            "with", "that", "have", "from", "this", "their", "is", "can",
            "do", "did", "was", "were", "a", "an", "in", "of", "to",
        }
        words = re.findall(r"[a-zA-Z]{3,}", question)
        meaningful = [w for w in words if w.lower() not in STOP]

        if not meaningful:
            # Fall back to cleaned question
            return question.strip()

        # Build a Lucene OR query; wrap multi-word concepts in quotes
        if len(meaningful) == 1:
            return meaningful[0]

        # Use all meaningful words joined with OR for broad recall
        return " OR ".join(meaningful[:8])

    # ── FTS execution ─────────────────────────────────────────────────────────

    async def _run_fts(self, search_term: str, limit: int) -> list[FtsHit]:
        """
        Execute FTS using the Lucene connector (primary) with regex fallback.

        Priority:
          1. Lucene connector query (luc:query) — accurate Lucene scoring
          2. Built-in magic predicate (owlim/lucene#) — simpler but less reliable
          3. SPARQL REGEX — always works, no ranking
        """
        # ── 1. Lucene connector ───────────────────────────────────────────────
        safe_term = _escape_lucene(search_term)
        sparql_connector = f"""\
SELECT DISTINCT ?entity ?label ?desc ?score WHERE {{
  ?search a luc-index:{LUCENE_CONNECTOR} ;
          luc:query "{safe_term}" ;
          luc:entities ?entity .
  ?entity luc:score ?score .
  OPTIONAL {{ ?entity rdfs:label ?label }}
  OPTIONAL {{ ?entity dcterms:description ?desc }}
  FILTER(!isBlank(?entity))
}}
ORDER BY DESC(?score)
LIMIT {limit}
"""
        try:
            bindings = await self._db.select_get(sparql_connector)
            hits = [self._binding_to_hit(b) for b in bindings]
            if hits:
                logger.info("fts_connector_hit", hits=len(hits), term=search_term)
                return hits
        except Exception as exc:
            logger.warning("fts_connector_failed", error=str(exc))

        # ── 2. Magic predicate fallback ───────────────────────────────────────
        sparql_magic = f"""\
SELECT DISTINCT ?entity ?label ?desc ?score WHERE {{
  ?entity <{GRAPHDB_FTS_PRED}> "{safe_term}" .
  OPTIONAL {{ ?entity rdfs:label ?label }}
  OPTIONAL {{ ?entity dcterms:description ?desc }}
  OPTIONAL {{ ?entity <{GRAPHDB_FTS_PRED}score> ?score }}
  FILTER(!isBlank(?entity))
}}
ORDER BY DESC(?score)
LIMIT {limit}
"""
        try:
            bindings = await self._db.select(sparql_magic)
            hits = [self._binding_to_hit(b) for b in bindings]
            if hits:
                logger.info("fts_magic_hit", hits=len(hits), term=search_term)
                return hits
        except Exception as exc:
            logger.warning("fts_magic_failed", error=str(exc))

        # ── 3. Regex fallback ─────────────────────────────────────────────────
        logger.info("fts_regex_fallback", term=search_term)
        return await self._run_regex_fallback(search_term, limit)

    async def _run_regex_fallback(self, search_term: str, limit: int) -> list[FtsHit]:
        """
        Regex-based fallback when Lucene FTS magic predicate is unavailable.
        Searches labels and descriptions using SPARQL REGEX across all keywords.
        """
        # Extract all individual keywords from the OR-joined search term
        keywords = [k.strip().strip('"') for k in search_term.split(" OR ") if k.strip()]
        if not keywords:
            keywords = [search_term.strip()]

        # Build REGEX filters: match if ANY keyword appears in label OR description
        label_clauses  = " || ".join(f'REGEX(STR(?label), "{re.escape(k)}", "i")' for k in keywords)
        desc_clauses   = " || ".join(f'REGEX(STR(?desc),  "{re.escape(k)}", "i")' for k in keywords)

        sparql = f"""\
SELECT DISTINCT ?entity ?label ?desc WHERE {{
  ?entity a ?cls .
  FILTER(STRSTARTS(STR(?cls), "https://example.org/pra#"))
  OPTIONAL {{ ?entity rdfs:label ?label }}
  OPTIONAL {{ ?entity dcterms:description ?desc }}
  FILTER(
    (BOUND(?label) && ({label_clauses})) ||
    (BOUND(?desc)  && ({desc_clauses}))
  )
}}
LIMIT {limit}
"""
        bindings = await self._db.select(sparql)
        return [self._binding_to_hit(b, fallback=True) for b in bindings]

    # ── Result mapping ────────────────────────────────────────────────────────

    def _binding_to_hit(self, b: dict, fallback: bool = False) -> FtsHit:
        uri = b.get("entity", {}).get("value", "")
        label = b.get("label", {}).get("value", uri.split("/")[-1])
        desc = b.get("desc", {}).get("value", "")
        score_raw = b.get("score", {}).get("value")
        score = float(score_raw) if score_raw else (0.5 if not fallback else 0.3)

        # Use description as the snippet (truncated)
        snippet = desc[:300] if desc else label

        return FtsHit(uri=uri, label=label, score=score, snippet=snippet)


def _escape_lucene(term: str) -> str:
    """Escape Lucene special characters."""
    special = r'+-&|!(){}[]^"~*?:\/'
    return "".join(f"\\{c}" if c in special else c for c in term)
