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

