"""Small, read-only Neo4j graph retrieval service."""
from __future__ import annotations

import re
from typing import Any

from app.infrastructure.knowledge_graph.neo4j.client import Neo4jClient
from app.models.schemas import Neo4jGraphEvidence, Neo4jNode, Neo4jRelationship


class Neo4jGraphRetrievalService:
    """Resolve named PRA entities and execute controlled graph patterns."""

    # Map question keywords â†’ actual Neo4j labels in the new dump
    _ENTITY_LABELS = {
        "function":           "Function",
        "business function":  "Function",
        "business functions": "Function",
        "rule":               "Rule",
        "business rule":      "Rule",
        "domain":             "Domain",
        "journey domain":     "Domain",
        "supporting domain":  "SupportingDomain",
        "phase":              "Phase",
        "precondition":       "PreCondition",
        "pre-condition":      "PreCondition",
        "postcondition":      "PostCondition",
        "post-condition":     "PostCondition",
        "purpose":            "Purpose",
        "payment scheme":     "PaymentScheme",
        "scheme":             "PaymentScheme",
        "input":              "Input",
        "output":             "Output",
        "pattern":            "Pattern",
        "patterns":           "Pattern",
        "anti-pattern":       "AntiPattern",
        "anti pattern":       "AntiPattern",
        "antipattern":        "AntiPattern",
        "anti-patterns":      "AntiPattern",
        "intent":             "Intent",
        "why it matters":     "WhyItMatters",
        "guide":              "GuideDocument",
        "guide document":     "GuideDocument",
    }

    _DOMAIN_LABELS = ["Domain", "SupportingDomain"]

    # Domain resolution: nodes use `name` property (not `uri`/`label`)
    _DOMAIN_RESOLUTION_QUERY = """
    MATCH (n)
    WHERE any(lbl IN labels(n) WHERE lbl IN $domain_labels)
      AND n.name IS NOT NULL
    RETURN n.name AS name,
           toLower(n.name) AS normalized_label,
           labels(n) AS labels
    LIMIT $limit
    """

    # Domain â†’ Functions
    _DOMAIN_FUNCTIONS_QUERY = """
    MATCH (domain:Domain {name: $entity_name})-[:CONTAINS]->(f:Function)
    RETURN domain AS n, f AS m,
           labels(domain) AS n_labels, labels(f) AS m_labels
    LIMIT $limit
    """

    # SupportingDomain â†’ Functions
    _SUPPORTING_DOMAIN_FUNCTIONS_QUERY = """
    MATCH (sd:SupportingDomain {name: $entity_name})-[:CONTAINS]->(f:Function)
    RETURN sd AS n, f AS m,
           labels(sd) AS n_labels, labels(f) AS m_labels
    LIMIT $limit
    """

    # Function dependencies
    _FUNCTION_DEPENDENCIES_QUERY = """
    MATCH (source:Function)-[r:PROVIDES_TO]->(target:Function)
    RETURN source AS n, r, target AS m,
           labels(source) AS n_labels, labels(target) AS m_labels
    LIMIT $limit
    """

    # Function â†’ Rules
    _FUNCTION_RULES_QUERY = """
    MATCH (source:Function)-[r:HAS_RULE]->(target:Rule)
    RETURN source AS n, r, target AS m,
           labels(source) AS n_labels, labels(target) AS m_labels
    LIMIT $limit
    """

    # Function â†’ PreConditions
    _PRECONDITIONS_QUERY = """
    MATCH (source:Function)-[r:HAS_PRECONDITION]->(target:PreCondition)
    RETURN source AS n, r, target AS m,
           labels(source) AS n_labels, labels(target) AS m_labels
    LIMIT $limit
    """

    # Function â†’ PostConditions
    _POSTCONDITIONS_QUERY = """
    MATCH (source:Function)-[r:HAS_POSTCONDITION]->(target:PostCondition)
    RETURN source AS n, r, target AS m,
           labels(source) AS n_labels, labels(target) AS m_labels
    LIMIT $limit
    """

    # Pattern â†’ AntiPattern
    _PATTERN_ANTIPATTERNS_QUERY = """
    MATCH (source:Pattern)-[r:HAS_ANTI_PATTERN]->(target:AntiPattern)
    RETURN source AS n, r, target AS m,
           labels(source) AS n_labels, labels(target) AS m_labels
    LIMIT $limit
    """

    # Pattern â†’ Intent
    _PATTERN_INTENT_QUERY = """
    MATCH (source:Pattern)-[r:HAS_INTENT]->(target:Intent)
    RETURN source AS n, r, target AS m,
           labels(source) AS n_labels, labels(target) AS m_labels
    LIMIT $limit
    """

    # Pattern â†’ WhyItMatters
    _PATTERN_WHY_IT_MATTERS_QUERY = """
    MATCH (source:Pattern)-[r:HAS_WHY_IT_MATTERS]->(target:WhyItMatters)
    RETURN source AS n, r, target AS m,
           labels(source) AS n_labels, labels(target) AS m_labels
    LIMIT $limit
    """

    # GuideDocument â†’ Pattern (documents)
    _GUIDE_PATTERNS_QUERY = """
    MATCH (source:GuideDocument)-[r:DOCUMENTS]->(target:Pattern)
    RETURN source AS n, r, target AS m,
           labels(source) AS n_labels, labels(target) AS m_labels
    LIMIT $limit
    """

    # PRA â†’ Pattern / GuideDocument
    _PRA_PATTERNS_QUERY = """
    MATCH (source:PRA)-[r:HAS_PATTERN]->(target:Pattern)
    RETURN source AS n, r, target AS m,
           labels(source) AS n_labels, labels(target) AS m_labels
    LIMIT $limit
    """

    _PRA_GUIDES_QUERY = """
    MATCH (source:PRA)-[r:HAS_GUIDE]->(target:GuideDocument)
    RETURN source AS n, r, target AS m,
           labels(source) AS n_labels, labels(target) AS m_labels
    LIMIT $limit
    """

    # PRA top-level structure
    _PRA_TOP_LEVEL_QUERY = """
    MATCH (pra:PRA)
    OPTIONAL MATCH (pra)-[:COMPRISES]->(d:Domain)
    OPTIONAL MATCH (pra)-[:HAS_PHASE]->(ph:Phase)
    OPTIONAL MATCH (d)-[:CONTAINS]->(f:Function)
    RETURN pra AS n, d AS m, ph AS k, f AS j,
           labels(pra) AS n_labels, labels(d) AS m_labels,
           labels(ph) AS k_labels, labels(f) AS j_labels
    LIMIT $limit
    """

    _PRA_PATTERNS = {
        "domain_functions": {
            "kind": "domain",
            "intent_keywords": ["function", "functions"],
            "query": [_DOMAIN_FUNCTIONS_QUERY, _SUPPORTING_DOMAIN_FUNCTIONS_QUERY],
        },
        "function_rules": {
            "kind": "generic",
            "intent_keywords": ["rule", "rules", "govern"],
            "entity_labels": ["Function", "Rule"],
            "query": _FUNCTION_RULES_QUERY,
        },
        "function_dependencies": {
            "kind": "generic",
            "intent_keywords": ["depend", "dependency", "depends on", "provides to"],
            "entity_labels": ["Function"],
            "query": _FUNCTION_DEPENDENCIES_QUERY,
        },
        "preconditions_only": {
            "kind": "generic",
            "intent_keywords": ["precondition", "preconditions"],
            "entity_labels": ["PreCondition"],
            "query": _PRECONDITIONS_QUERY,
        },
        "postconditions_only": {
            "kind": "generic",
            "intent_keywords": ["postcondition", "postconditions"],
            "entity_labels": ["PostCondition"],
            "query": _POSTCONDITIONS_QUERY,
        },
        "pattern_antipatterns": {
            "kind": "generic",
            "intent_keywords": ["anti-pattern", "anti pattern", "antipattern", "anti-patterns"],
            "entity_labels": ["Pattern", "AntiPattern"],
            "query": _PATTERN_ANTIPATTERNS_QUERY,
        },
        "pattern_intent": {
            "kind": "generic",
            "intent_keywords": ["intent"],
            "entity_labels": ["Pattern", "Intent"],
            "query": _PATTERN_INTENT_QUERY,
        },
        "pattern_why_it_matters": {
            "kind": "generic",
            "intent_keywords": ["why it matters", "why does it matter", "matters"],
            "entity_labels": ["Pattern", "WhyItMatters"],
            "query": _PATTERN_WHY_IT_MATTERS_QUERY,
        },
        "guide_patterns": {
            "kind": "generic",
            "intent_keywords": ["guide", "documents", "documented"],
            "entity_labels": ["GuideDocument", "Pattern"],
            "query": _GUIDE_PATTERNS_QUERY,
        },
        "pra_patterns": {
            "kind": "generic",
            "intent_keywords": ["pattern", "patterns"],
            "entity_labels": ["PRA", "Pattern"],
            "query": _PRA_PATTERNS_QUERY,
        },
        "pra_guides": {
            "kind": "generic",
            "intent_keywords": ["guide", "guides"],
            "entity_labels": ["PRA", "GuideDocument"],
            "query": _PRA_GUIDES_QUERY,
        },
    }

    def __init__(self, client: Neo4jClient, max_results: int = 25) -> None:
        self._client = client
        self._max_results = max_results

    async def retrieve(self, question: str) -> Neo4jGraphEvidence:
        """Resolve a named domain and return only its controlled relationships."""
        entity = await self._resolve_domain(question)
        pattern_name, pattern_details = self._find_pattern(question, entity is not None)

        if not pattern_details:
            if entity is not None or self._looks_domain_scoped(question):
                return Neo4jGraphEvidence()
            return await self._retrieve_generic(question)

        if pattern_details.get("kind") == "domain":
            if entity is None:
                return Neo4jGraphEvidence()
            return await self._retrieve_domain_pattern(pattern_name, pattern_details, entity)

        return await self._retrieve_generic_pattern(pattern_name, pattern_details)

    async def _resolve_domain(self, question: str) -> dict[str, Any] | None:
        """Find an exact domain name contained in the question."""
        rows = await self._client.execute_read_query(
            self._DOMAIN_RESOLUTION_QUERY,
            domain_labels=self._DOMAIN_LABELS,
            limit=100,
        )
        normalized_question = self._normalize(question)
        candidates: list[tuple[int, int, dict[str, Any]]] = []

        for row in rows:
            name = str(row.get("name") or "")
            normalized_value = str(row.get("normalized_label") or "")
            labels = row.get("labels") or []

            if normalized_value and normalized_value in normalized_question:
                candidates.append((1, len(normalized_value), {
                    "name": name,
                    "labels": labels,
                }))

        if not candidates:
            return None

        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return candidates[0][2] if candidates else None

    async def _retrieve_domain_pattern(
        self,
        pattern_name: str,
        pattern_details: dict[str, Any],
        entity: dict[str, Any],
    ) -> Neo4jGraphEvidence:
        queries = pattern_details["query"]
        if isinstance(queries, str):
            queries = [queries]

        all_rows: list[dict[str, Any]] = []
        query_texts: list[str] = []
        for query in queries:
            rows = await self._client.execute_read_query(
                query,
                entity_name=entity["name"],
                limit=self._max_results,
            )
            all_rows.extend(rows)
            query_texts.append(query)

        return self._rows_to_evidence(all_rows, "\n\n---\n\n".join(query_texts))

    async def _retrieve_generic(self, question: str) -> Neo4jGraphEvidence:
        # Fall back to top-level PRA structure
        rows = await self._client.execute_read_query(
            self._PRA_TOP_LEVEL_QUERY,
            limit=self._max_results,
        )
        return self._rows_to_evidence(rows, self._PRA_TOP_LEVEL_QUERY)

    async def _retrieve_generic_pattern(
        self,
        pattern_name: str,
        pattern_details: dict[str, Any],
    ) -> Neo4jGraphEvidence:
        query = pattern_details["query"]
        query_text = (
            f"{query}\n"
            "LIMIT $limit"
        )
        rows = await self._client.execute_read_query(
            query_text,
            limit=self._max_results,
        )
        return self._rows_to_evidence(rows, query_text)

    def _find_pattern(
        self,
        question: str,
        has_domain_entity: bool = False,
    ) -> tuple[str | None, dict[str, Any] | None]:
        question_lower = question.lower()

        if has_domain_entity:
            for name in ("domain_functions",):
                pattern = self._PRA_PATTERNS[name]
                if any(self._contains_phrase(question_lower, keyword) for keyword in pattern["intent_keywords"]):
                    return name, pattern

        matched_labels = self._match_labels(question)
        candidates = []
        for name, pattern in self._PRA_PATTERNS.items():
            if pattern.get("kind") != "generic":
                continue
            required_labels = set(pattern.get("entity_labels", []))
            if required_labels.issubset(set(matched_labels)) and any(
                self._contains_phrase(question_lower, keyword)
                for keyword in pattern.get("intent_keywords", [])
            ):
                candidates.append((name, pattern))

        if candidates:
            candidates.sort(key=lambda item: len(item[1].get("entity_labels", [])), reverse=True)
            return candidates[0]

        if len(matched_labels) == 1 and not self._looks_domain_scoped(question):
            label = matched_labels[0]
            return "fallback_entity_listing", {
                "kind": "generic",
                "query": f"MATCH (source:{label})-[r]-(target) RETURN source AS n, r, target AS m, labels(source) AS n_labels, labels(target) AS m_labels",
            }

        return None, None

    @classmethod
    def _match_labels(cls, question: str) -> list[str]:
        question_lower = question.lower()
        found: list[str] = []
        for phrase, label in sorted(cls._ENTITY_LABELS.items(), key=lambda item: len(item[0]), reverse=True):
            if re.search(rf"\b{re.escape(phrase)}\b", question_lower) and label not in found:
                found.append(label)
        return found

    @staticmethod
    def _contains_phrase(question: str, phrase: str) -> bool:
        return bool(re.search(rf"\b{re.escape(phrase)}\b", question))

    @staticmethod
    def _looks_domain_scoped(question: str) -> bool:
        question_lower = question.lower()
        return any(
            phrase in question_lower
            for phrase in ("within ", "associated with ", "depend on", "dependencies of ", "responsibilities of ")
        )

    @staticmethod
    def _normalize(value: str) -> str:
        value = re.sub(r"[^a-zA-Z0-9]+", " ", value.lower())
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def _values(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            return [str(item) for item in value if item is not None and str(item).strip()]
        return [str(value)]

    def _rows_to_evidence(self, rows: list[dict[str, Any]], query: str) -> Neo4jGraphEvidence:
        nodes: dict[str, Neo4jNode] = {}
        relationships: dict[str, Neo4jRelationship] = {}

        for row in rows:
            for node_key, labels_key in (("n", "n_labels"), ("m", "m_labels"), ("k", "k_labels"), ("j", "j_labels")):
                node = self._node(row.get(node_key), row.get(labels_key) or [])
                if node is not None:
                    nodes[node.element_id] = node

            for relationship_key in ("r", "r2"):
                relationship = self._relationship(row.get(relationship_key))
                if relationship is not None:
                    relationships[relationship.element_id] = relationship

        return Neo4jGraphEvidence(
            query=query,
            results=list(nodes.values()),
            relationships=list(relationships.values()),
            result_count=len(nodes),
        )

    @staticmethod
    def _node(value: Any, labels: list[str]) -> Neo4jNode | None:
        if value is None:
            return None
        if isinstance(value, dict):
            properties = dict(value)
            # New dump uses `name` as identifier, not `uri`
            element_id = properties.get("name") or properties.get("uri") or properties.get("element_id")
            if not element_id:
                return None
            return Neo4jNode(
                element_id=str(element_id),
                labels=sorted(str(label) for label in labels),
                properties=properties,
            )
        if not hasattr(value, "element_id"):
            return None
        return Neo4jNode(
            element_id=str(value.element_id),
            labels=sorted(str(label) for label in value.labels),
            properties=dict(value),
        )

    @staticmethod
    def _relationship(value: Any) -> Neo4jRelationship | None:
        if value is None:
            return None
        if isinstance(value, tuple) and len(value) == 3:
            start, relationship_type, end = value
            if not isinstance(start, dict) or not isinstance(end, dict):
                return None
            start_id = start.get("name") or start.get("uri") or start.get("element_id")
            end_id = end.get("name") or end.get("uri") or end.get("element_id")
            if not start_id or not end_id:
                return None
            return Neo4jRelationship(
                element_id=f"{relationship_type}:{start_id}:{end_id}",
                type=str(relationship_type),
                start_node=str(start_id),
                end_node=str(end_id),
                properties={},
            )
        if not hasattr(value, "element_id"):
            return None
        return Neo4jRelationship(
            element_id=str(value.element_id),
            type=str(value.type),
            start_node=str(value.start_node.element_id),
            end_node=str(value.end_node.element_id),
            properties=dict(value),
        )


    _DOMAIN_FUNCTIONS_QUERY = """MATCH (domain:Domain {uri: $entity_uri})
      -[r:hasFunction]->(function:BusinessFunction)
RETURN domain AS n, r, function AS m,
       labels(domain) AS n_labels, labels(function) AS m_labels
LIMIT $limit"""

    _DOMAIN_ACTIVITIES_QUERY = """MATCH (domain:Domain {uri: $entity_uri})
      -[r_function:hasFunction]->(function:BusinessFunction)
      -[r_activity:hasActivity]->(activity:Activity)
RETURN domain AS n, r_function AS r, function AS m, activity AS k,
       r_activity AS r2,
       labels(domain) AS n_labels,
       labels(function) AS m_labels,
       labels(activity) AS k_labels
LIMIT $limit"""

    _DOMAIN_DEPENDS_ON_QUERY = """MATCH (domain:Domain {uri: $entity_uri})
      -[r:dependsOn]->(target:BusinessFunction)
RETURN domain AS n, r, target AS m,
       labels(domain) AS n_labels, labels(target) AS m_labels
LIMIT $limit"""

    _DOMAIN_DEPENDS_ON_DOMAIN_QUERY = """MATCH (domain:Domain {uri: $entity_uri})
      -[r:dependsOnDomain]->(target:Domain)
RETURN domain AS n, r, target AS m,
       labels(domain) AS n_labels, labels(target) AS m_labels
LIMIT $limit"""

    _DOMAIN_RESOLUTION_QUERY = """MATCH (n)
WHERE any(node_label IN labels(n) WHERE node_label IN $domain_labels)
RETURN n.uri AS uri, n.label AS label,
       n.normalizedLabel AS normalized_label,
       labels(n) AS labels
LIMIT $limit"""

    _PRA_PATTERNS = {
        "domain_functions": {
            "kind": "domain",
            "intent_keywords": ["business function", "business functions"],
            "query": _DOMAIN_FUNCTIONS_QUERY,
        },
        "domain_activities": {
            "kind": "domain",
            "intent_keywords": ["activity", "activities"],
            "query": _DOMAIN_ACTIVITIES_QUERY,
        },
        "domain_dependencies": {
            "kind": "domain",
            "intent_keywords": ["depend", "dependency", "depends on"],
            "query": [_DOMAIN_DEPENDS_ON_QUERY, _DOMAIN_DEPENDS_ON_DOMAIN_QUERY],
        },
        # Existing controlled class-level patterns are retained for generic
        # questions that do not name a specific domain.
        "function_activities": {
            "kind": "generic",
            "intent_keywords": ["activity", "activities"],
            "entity_labels": ["BusinessFunction"],
            "query": "MATCH (source:BusinessFunction)-[r:hasActivity]->(target:Activity)",
        },
        "function_rules": {
            "kind": "generic",
            "intent_keywords": ["rule", "rules", "govern"],
            "entity_labels": ["BusinessFunction", "BusinessRule"],
            "query": "MATCH (source:BusinessFunction)-[r:governedBy]->(target:BusinessRule)",
        },
        "function_dependencies": {
            "kind": "generic",
            "intent_keywords": ["depend", "dependency", "depends on", "each other"],
            "entity_labels": ["BusinessFunction"],
            "query": "MATCH (source:BusinessFunction)-[r:dependsOn]->(target:BusinessFunction)",
        },
        "preconditions_only": {
            "kind": "generic",
            "intent_keywords": ["precondition", "preconditions"],
            "entity_labels": ["Precondition"],
            "query": "MATCH (source)-[r:hasPrecondition]->(target:Precondition)",
        },
        "postconditions_only": {
            "kind": "generic",
            "intent_keywords": ["postcondition", "postconditions"],
            "entity_labels": ["Postcondition"],
            "query": "MATCH (source)-[r:hasPostcondition]->(target:Postcondition)",
        },
    }

    def __init__(self, client: Neo4jClient, max_results: int = 25) -> None:
        self._client = client
        self._max_results = max_results

    async def retrieve(self, question: str) -> Neo4jGraphEvidence:
        """Resolve a named domain and return only its controlled relationships."""
        entity = await self._resolve_domain(question)
        pattern_name, pattern_details = self._find_pattern(question, entity is not None)

        if not pattern_details:
            # A named domain must never fall through to unrelated generic rows.
            if entity is not None or self._looks_domain_scoped(question):
                return Neo4jGraphEvidence()
            return await self._retrieve_generic(question)

        if pattern_details.get("kind") == "domain":
            if entity is None:
                return Neo4jGraphEvidence()
            return await self._retrieve_domain_pattern(pattern_name, pattern_details, entity)

        return await self._retrieve_generic_pattern(pattern_name, pattern_details)

    async def _resolve_domain(self, question: str) -> dict[str, Any] | None:
        """Find an exact normalized domain label contained in the question."""
        rows = await self._client.execute_read_query(
            self._DOMAIN_RESOLUTION_QUERY,
            domain_labels=self._DOMAIN_LABELS,
            limit=100,
        )
        normalized_question = self._normalize(question)
        candidates: list[tuple[int, int, dict[str, Any]]] = []

        for row in rows:
            uri = str(row.get("uri") or "")
            labels = row.get("labels") or []
            normalized_values = self._values(row.get("normalized_label"))
            label_values = self._values(row.get("label"))

            for value in normalized_values:
                normalized_value = self._normalize(value)
                if normalized_value and normalized_value in normalized_question:
                    candidates.append((1, len(normalized_value), {
                        "uri": uri,
                        "label": label_values[0] if label_values else value,
                        "labels": labels,
                    }))
            for value in label_values:
                normalized_value = self._normalize(value)
                if normalized_value and normalized_value in normalized_question:
                    candidates.append((0, len(normalized_value), {
                        "uri": uri,
                        "label": value,
                        "labels": labels,
                    }))

        if not candidates:
            return None

        # Prefer normalizedLabel matches, then the most specific longest name.
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        selected = candidates[0][2]
        return selected if selected.get("uri") else None

    async def _retrieve_domain_pattern(
        self,
        pattern_name: str,
        pattern_details: dict[str, Any],
        entity: dict[str, Any],
    ) -> Neo4jGraphEvidence:
        queries = pattern_details["query"]
        if isinstance(queries, str):
            queries = [queries]

        all_rows: list[dict[str, Any]] = []
        query_texts: list[str] = []
        for query in queries:
            rows = await self._client.execute_read_query(
                query,
                entity_uri=entity["uri"],
                limit=self._max_results,
            )
            all_rows.extend(rows)
            query_texts.append(query)

        evidence = self._rows_to_evidence(all_rows, "\n\n---\n\n".join(query_texts))
        return evidence

    async def _retrieve_generic(self, question: str) -> Neo4jGraphEvidence:
        pattern_name, pattern_details = self._find_pattern(question, False)
        if not pattern_details or pattern_details.get("kind") != "generic":
            return Neo4jGraphEvidence()
        return await self._retrieve_generic_pattern(pattern_name, pattern_details)

    async def _retrieve_generic_pattern(
        self,
        pattern_name: str,
        pattern_details: dict[str, Any],
    ) -> Neo4jGraphEvidence:
        query = pattern_details["query"]
        query_text = (
            f"{query}\n"
            "RETURN source AS n, r, target AS m, "
            "labels(source) AS n_labels, labels(target) AS m_labels\n"
            "LIMIT $limit"
        )
        rows = await self._client.execute_read_query(
            query_text,
            limit=self._max_results,
        )
        return self._rows_to_evidence(rows, query_text)

    def _find_pattern(
        self,
        question: str,
        has_domain_entity: bool = False,
    ) -> tuple[str | None, dict[str, Any] | None]:
        question_lower = question.lower()

        if has_domain_entity:
            for name in ("domain_functions", "domain_activities", "domain_dependencies"):
                pattern = self._PRA_PATTERNS[name]
                if any(self._contains_phrase(question_lower, keyword) for keyword in pattern["intent_keywords"]):
                    return name, pattern

        matched_labels = self._match_labels(question)
        candidates = []
        for name, pattern in self._PRA_PATTERNS.items():
            if pattern.get("kind") != "generic":
                continue
            required_labels = set(pattern.get("entity_labels", []))
            if required_labels.issubset(set(matched_labels)) and any(
                self._contains_phrase(question_lower, keyword)
                for keyword in pattern.get("intent_keywords", [])
            ):
                candidates.append((name, pattern))

        if candidates:
            candidates.sort(key=lambda item: len(item[1].get("entity_labels", [])), reverse=True)
            return candidates[0]

        if len(matched_labels) == 1 and not self._looks_domain_scoped(question):
            label = matched_labels[0]
            return "fallback_entity_listing", {
                "kind": "generic",
                "query": f"MATCH (source:{label})-[r]-(target)",
            }

        return None, None

    @classmethod
    def _match_labels(cls, question: str) -> list[str]:
        question_lower = question.lower()
        found: list[str] = []
        for phrase, label in sorted(cls._ENTITY_LABELS.items(), key=lambda item: len(item[0]), reverse=True):
            if re.search(rf"\b{re.escape(phrase)}\b", question_lower) and label not in found:
                found.append(label)
        return found

    @staticmethod
    def _contains_phrase(question: str, phrase: str) -> bool:
        return bool(re.search(rf"\b{re.escape(phrase)}\b", question))

    @staticmethod
    def _looks_domain_scoped(question: str) -> bool:
        question_lower = question.lower()
        return any(
            phrase in question_lower
            for phrase in ("within ", "associated with ", "depend on", "dependencies of ", "responsibilities of ")
        )

    @staticmethod
    def _normalize(value: str) -> str:
        value = re.sub(r"[^a-zA-Z0-9]+", " ", value.lower())
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def _values(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            return [str(item) for item in value if item is not None and str(item).strip()]
        return [str(value)]

    def _rows_to_evidence(self, rows: list[dict[str, Any]], query: str) -> Neo4jGraphEvidence:
        nodes: dict[str, Neo4jNode] = {}
        relationships: dict[str, Neo4jRelationship] = {}

        for row in rows:
            for node_key, labels_key in (("n", "n_labels"), ("m", "m_labels"), ("k", "k_labels")):
                node = self._node(row.get(node_key), row.get(labels_key, []))
                if node is not None:
                    nodes[node.element_id] = node

            for relationship_key in ("r", "r2"):
                relationship = self._relationship(row.get(relationship_key))
                if relationship is not None:
                    relationships[relationship.element_id] = relationship

        return Neo4jGraphEvidence(
            query=query,
            results=list(nodes.values()),
            relationships=list(relationships.values()),
            result_count=len(relationships),
        )

    @staticmethod
    def _node(value: Any, labels: list[str]) -> Neo4jNode | None:
        if value is None:
            return None
        if isinstance(value, dict):
            properties = dict(value)
            element_id = properties.get("uri") or properties.get("element_id")
            if not element_id:
                return None
            return Neo4jNode(
                element_id=str(element_id),
                labels=sorted(str(label) for label in labels),
                properties=properties,
            )
        if not hasattr(value, "element_id"):
            return None
        return Neo4jNode(
            element_id=str(value.element_id),
            labels=sorted(str(label) for label in value.labels),
            properties=dict(value),
        )

    @staticmethod
    def _relationship(value: Any) -> Neo4jRelationship | None:
        if isinstance(value, tuple) and len(value) == 3:
            start, relationship_type, end = value
            if not isinstance(start, dict) or not isinstance(end, dict):
                return None
            start_id = start.get("uri") or start.get("element_id")
            end_id = end.get("uri") or end.get("element_id")
            if not start_id or not end_id:
                return None
            relationship_type = str(relationship_type)
            return Neo4jRelationship(
                element_id=f"{relationship_type}:{start_id}:{end_id}",
                type=relationship_type,
                start_node=str(start_id),
                end_node=str(end_id),
                properties={},
            )
        if value is None or not hasattr(value, "element_id"):
            return None
        return Neo4jRelationship(
            element_id=str(value.element_id),
            type=str(value.type),
            start_node=str(value.start_node.element_id),
            end_node=str(value.end_node.element_id),
            properties=dict(value),
        )


# Export the schema-compatible implementation. The legacy RDF/GraphDB block
# above remains for historical reference but is not used at runtime.
from app.infrastructure.retrieval.neo4j.graph_service_current import (  # noqa: E402
    Neo4jGraphRetrievalService,
)
