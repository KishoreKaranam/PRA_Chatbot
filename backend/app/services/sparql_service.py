"""
SPARQL retrieval service.

Responsibilities:
  1. Build a SPARQL CONSTRUCT query relevant to the user question.
  2. Execute it against GraphDB.
  3. Return structured evidence.

Query-building strategy
  ─ Extract key terms from the question.
  ─ Map terms to known PRA ontology classes / instances using a label lookup.
  ─ Build a focused CONSTRUCT query around those seeds.
  ─ Fall back to a broad schema-level CONSTRUCT if nothing matches.
"""
from __future__ import annotations

import re
from app.graphdb.client import GraphDBClient
from app.models.schemas import SparqlEvidence, Triple
from app.core.log_config import get_logger

logger = get_logger(__name__)

# PRA_V2 class names that can appear in questions (lowercase → URI fragment)
# Namespace: https://example.org/pra#
PRA_CLASSES = {
    # Core functional classes (actual classes in PRA_V2 TTL)
    "business function": "BusinessFunction",
    "business rule": "BusinessRule",
    "activity": "Activity",
    "domain": "Domain",
    "main journey domain": "MainJourneyDomain",
    "main journey": "MainJourneyDomain",
    "supporting domain": "SupportingDomain",
    "supporting function": "SupportingFunction",
    "support function": "SupportingFunction",
    "process phase": "ProcessPhase",
    "phase": "ProcessPhase",
    "precondition": "Precondition",
    "postcondition": "Postcondition",
    "purpose": "PurposeStatement",
    "purpose statement": "PurposeStatement",
    "knowledge asset": "KnowledgeAsset",
    "business layer": "BusinessLayer",
    "layer": "BusinessLayer",
    "operational context": "OperationalContext",
    "context": "OperationalContext",
    "editorial note": "EditorialNote",
    "note": "EditorialNote",
    "applicability": "ApplicabilityStatus",
}


class SparqlRetrievalService:
    """Build and execute SPARQL CONSTRUCT queries for user questions."""

    def __init__(self, client: GraphDBClient) -> None:
        self._db = client

    async def retrieve(
        self, question: str, max_results: int = 10, max_triples: int = 500
    ) -> SparqlEvidence:
        """Return an ontology sub-graph relevant to the question."""
        query = self._build_query(question, max_results, max_triples)
        triples_raw = await self._db.construct(query)
        triples = [Triple(subject=t["subject"], predicate=t["predicate"], obj=t["obj"]) for t in triples_raw]
        logger.info("sparql_retrieve", triple_count=len(triples), question=question[:80])
        return SparqlEvidence(
            query=query,
            triples=triples,
            triple_count=len(triples),
        )

    # ── Query builder ─────────────────────────────────────────────────────────

    def _build_query(self, question: str, max_results: int, max_triples: int = 500) -> str:
        """Dynamically build a CONSTRUCT query based on question analysis."""
        q_lower = question.lower()
        matched_class = self._match_class(q_lower)
        keywords = self._extract_keywords(question)

        if matched_class:
            # When a PRA class is explicitly detected, retrieve ALL instances.
            # Apply a keyword filter only for highly specific discriminating terms
            # (6+ chars, not a component of the class name, not a question word).
            class_words = {w.lower() for w in re.findall(r'[A-Z][a-z]*|[a-z]+', matched_class)}
            generic_q_words = {
                "what", "which", "where", "when", "does", "list", "tell",
                "show", "give", "about", "with", "have", "from", "their",
                "these", "those", "some", "also", "your", "main", "they",
                "there", "more", "into", "functions", "classes", "types",
                "defined", "describe", "explain", "available", "examples",
            }
            extra_keywords = [
                k for k in keywords
                if k.lower() not in class_words
                and k.lower() not in generic_q_words
                and len(k) >= 7  # only very specific, long discriminating terms
            ]
            return self._class_subgraph_query(matched_class, extra_keywords, max_results, max_triples)
        if keywords:
            return self._keyword_subgraph_query(keywords, max_results, max_triples)
        return self._broad_schema_query(max_results, max_triples)

    def _match_class(self, q_lower: str) -> str | None:
        for phrase, cls in PRA_CLASSES.items():
            if phrase in q_lower:
                return cls
        return None

    def _extract_keywords(self, question: str) -> list[str]:
        """Extract meaningful keywords (≥4 chars, not stop-words)."""
        STOP = {
            "what", "which", "where", "when", "how", "does", "list", "tell",
            "show", "give", "are", "the", "all", "and", "for", "about",
            "with", "that", "have", "from", "this", "their", "there",
            "them", "been", "they", "some", "into", "more", "your",
        }
        words = re.findall(r"[a-zA-Z]{4,}", question)
        return [w for w in words if w.lower() not in STOP]

    # ── Concrete query templates ──────────────────────────────────────────────

    def _class_subgraph_query(
        self, cls: str, keywords: list[str], limit: int, max_triples: int = 500
    ) -> str:
        """CONSTRUCT query for all instances of a PRA_V2 class."""
        if keywords:
            regex_terms = "|".join(re.escape(k) for k in keywords[:5])
            seed_block = f"""\
  {{
    SELECT DISTINCT ?entity WHERE {{
      ?entity a pra:{cls} .
      OPTIONAL {{ ?entity rdfs:label ?lbl }}
      OPTIONAL {{ ?entity dcterms:description ?d }}
      FILTER(
        BOUND(?lbl) && REGEX(STR(?lbl), "{regex_terms}", "i") ||
        BOUND(?d)   && REGEX(STR(?d),   "{regex_terms}", "i")
      )
    }}
    LIMIT {limit}
  }}"""
        else:
            seed_block = f"""\
  ?entity a pra:{cls} ."""

        return f"""\
CONSTRUCT {{
  ?entity rdf:type ?type .
  ?entity rdfs:label ?label .
  ?entity dcterms:description ?desc .
  ?entity pra:hasApplicabilityNote ?appNote .
  ?entity pra:hasInputText ?inputText .
  ?entity pra:hasOutputText ?outputText .
  ?entity pra:isFunctionOf ?dom .
  ?entity pra:hasPhase ?phase .
  ?entity pra:hasActivity ?act .
  ?entity pra:governedBy ?rule .
  ?entity pra:dependsOn ?dep .
  ?entity pra:dependsOnDomain ?depDom .
  ?entity pra:providesTo ?provides .
  ?entity pra:hasFunction ?hasFunc .
  ?entity pra:supportsFunction ?supFunc .
  ?entity pra:supportsDomain ?supDom .
  ?entity pra:hasLayer ?layer .
  ?entity pra:inContext ?ctx .
  ?entity pra:notes ?notes .
  ?entity pra:hasPrecondition ?pre .
  ?entity pra:hasPostcondition ?post .
  ?entity pra:hasPurposeStatement ?purp .
  ?act rdfs:label ?actLabel .
  ?dom rdfs:label ?domLabel .
  ?rule rdfs:label ?ruleLabel .
  ?rule dcterms:description ?ruleDesc .
  ?pre rdfs:label ?preLabel .
  ?pre dcterms:description ?preDesc .
  ?post rdfs:label ?postLabel .
  ?post dcterms:description ?postDesc .
  ?dep rdfs:label ?depLabel .
  ?provides rdfs:label ?providesLabel .
  ?hasFunc rdfs:label ?hasFuncLabel .
}}
WHERE {{
{seed_block}
  ?entity a ?type .
  OPTIONAL {{ ?entity rdfs:label ?label }}
  OPTIONAL {{ ?entity dcterms:description ?desc }}
  OPTIONAL {{ ?entity pra:hasApplicabilityNote ?appNote }}
  OPTIONAL {{ ?entity pra:hasInputText ?inputText }}
  OPTIONAL {{ ?entity pra:hasOutputText ?outputText }}
  OPTIONAL {{ ?entity pra:isFunctionOf ?dom . ?dom rdfs:label ?domLabel }}
  OPTIONAL {{ ?entity pra:hasPhase ?phase }}
  OPTIONAL {{ ?entity pra:hasActivity ?act . ?act rdfs:label ?actLabel }}
  OPTIONAL {{ ?entity pra:governedBy ?rule . ?rule rdfs:label ?ruleLabel . OPTIONAL {{ ?rule dcterms:description ?ruleDesc }} }}
  OPTIONAL {{ ?entity pra:dependsOn ?dep . ?dep rdfs:label ?depLabel }}
  OPTIONAL {{ ?entity pra:dependsOnDomain ?depDom }}
  OPTIONAL {{ ?entity pra:providesTo ?provides . ?provides rdfs:label ?providesLabel }}
  OPTIONAL {{ ?entity pra:hasFunction ?hasFunc . ?hasFunc rdfs:label ?hasFuncLabel }}
  OPTIONAL {{ ?entity pra:supportsFunction ?supFunc }}
  OPTIONAL {{ ?entity pra:supportsDomain ?supDom }}
  OPTIONAL {{ ?entity pra:hasLayer ?layer }}
  OPTIONAL {{ ?entity pra:inContext ?ctx }}
  OPTIONAL {{ ?entity pra:notes ?notes }}
  OPTIONAL {{ ?entity pra:hasPrecondition ?pre . ?pre rdfs:label ?preLabel . OPTIONAL {{ ?pre dcterms:description ?preDesc }} }}
  OPTIONAL {{ ?entity pra:hasPostcondition ?post . ?post rdfs:label ?postLabel . OPTIONAL {{ ?post dcterms:description ?postDesc }} }}
  OPTIONAL {{ ?entity pra:hasPurposeStatement ?purp }}
}}
LIMIT {max_triples}
"""

    def _keyword_subgraph_query(self, keywords: list[str], limit: int, max_triples: int = 500) -> str:
        """CONSTRUCT query using label/description regex matching (PRA_V2)."""
        regex_terms = "|".join(re.escape(k) for k in keywords[:5])
        return f"""\
CONSTRUCT {{
  ?entity rdf:type ?type .
  ?entity rdfs:label ?label .
  ?entity dcterms:description ?desc .
  ?entity pra:hasApplicabilityNote ?appNote .
  ?entity pra:hasInputText ?inputText .
  ?entity pra:hasOutputText ?outputText .
  ?entity pra:isFunctionOf ?dom .
  ?entity pra:governedBy ?rule .
  ?entity pra:hasPrecondition ?pre .
  ?entity pra:hasPostcondition ?post .
  ?entity pra:dependsOn ?dep .
  ?entity pra:dependsOnDomain ?depDom .
  ?entity pra:providesTo ?provides .
  ?entity pra:hasFunction ?hasFunc .
  ?entity pra:supportsFunction ?supFunc .
  ?entity pra:supportsDomain ?supDom .
  ?entity pra:hasLayer ?layer .
  ?entity pra:inContext ?ctx .
  ?entity pra:notes ?notes .
  ?dom rdfs:label ?domLabel .
  ?rule rdfs:label ?ruleLabel .
  ?rule dcterms:description ?ruleDesc .
  ?pre rdfs:label ?preLabel .
  ?pre dcterms:description ?preDesc .
  ?post rdfs:label ?postLabel .
  ?post dcterms:description ?postDesc .
  ?dep rdfs:label ?depLabel .
  ?provides rdfs:label ?providesLabel .
  ?hasFunc rdfs:label ?hasFuncLabel .
}}
WHERE {{
  {{
    SELECT DISTINCT ?entity WHERE {{
      ?entity a ?cls .
      FILTER(STRSTARTS(STR(?cls), "https://example.org/pra#"))
      OPTIONAL {{ ?entity rdfs:label ?lbl }}
      OPTIONAL {{ ?entity dcterms:description ?d }}
      FILTER(
        BOUND(?lbl) && REGEX(STR(?lbl), "{regex_terms}", "i") ||
        BOUND(?d)   && REGEX(STR(?d),   "{regex_terms}", "i")
      )
    }}
    LIMIT {limit}
  }}
  ?entity a ?type .
  OPTIONAL {{ ?entity rdfs:label ?label }}
  OPTIONAL {{ ?entity dcterms:description ?desc }}
  OPTIONAL {{ ?entity pra:hasApplicabilityNote ?appNote }}
  OPTIONAL {{ ?entity pra:hasInputText ?inputText }}
  OPTIONAL {{ ?entity pra:hasOutputText ?outputText }}
  OPTIONAL {{ ?entity pra:isFunctionOf ?dom . ?dom rdfs:label ?domLabel }}
  OPTIONAL {{ ?entity pra:governedBy ?rule . ?rule rdfs:label ?ruleLabel . OPTIONAL {{ ?rule dcterms:description ?ruleDesc }} }}
  OPTIONAL {{ ?entity pra:dependsOn ?dep . ?dep rdfs:label ?depLabel }}
  OPTIONAL {{ ?entity pra:dependsOnDomain ?depDom }}
  OPTIONAL {{ ?entity pra:providesTo ?provides . ?provides rdfs:label ?providesLabel }}
  OPTIONAL {{ ?entity pra:hasFunction ?hasFunc . ?hasFunc rdfs:label ?hasFuncLabel }}
  OPTIONAL {{ ?entity pra:supportsFunction ?supFunc }}
  OPTIONAL {{ ?entity pra:supportsDomain ?supDom }}
  OPTIONAL {{ ?entity pra:hasLayer ?layer }}
  OPTIONAL {{ ?entity pra:inContext ?ctx }}
  OPTIONAL {{ ?entity pra:notes ?notes }}
  OPTIONAL {{ ?entity pra:hasPrecondition ?pre . ?pre rdfs:label ?preLabel . OPTIONAL {{ ?pre dcterms:description ?preDesc }} }}
  OPTIONAL {{ ?entity pra:hasPostcondition ?post . ?post rdfs:label ?postLabel . OPTIONAL {{ ?post dcterms:description ?postDesc }} }}
}}
LIMIT {max_triples}
"""

    def _broad_schema_query(self, _limit: int, max_triples: int = 500) -> str:
        """Fallback: return the ontology class hierarchy."""
        return f"""\
CONSTRUCT {{
  ?cls rdf:type owl:Class .
  ?cls rdfs:label ?label .
  ?cls rdfs:comment ?comment .
  ?cls rdfs:subClassOf ?parent .
  ?prop rdf:type ?propType .
  ?prop rdfs:label ?propLabel .
  ?prop rdfs:domain ?domain .
  ?prop rdfs:range ?range .
}}
WHERE {{
  {{
    ?cls a owl:Class .
    OPTIONAL {{ ?cls rdfs:label ?label }}
    OPTIONAL {{ ?cls rdfs:comment ?comment }}
    OPTIONAL {{ ?cls rdfs:subClassOf ?parent }}
  }} UNION {{
    ?prop a ?propType .
    FILTER(?propType IN (owl:ObjectProperty, owl:DatatypeProperty))
    OPTIONAL {{ ?prop rdfs:label ?propLabel }}
    OPTIONAL {{ ?prop rdfs:domain ?domain }}
    OPTIONAL {{ ?prop rdfs:range ?range }}
  }}
}}
LIMIT {max_triples}
"""
