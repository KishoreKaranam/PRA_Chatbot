"""
Abstract base classes for knowledge graph backends.

GraphBackend  – SPARQL-based (legacy, kept for reference)
Neo4jBackend  – Cypher-based (primary backend for Neo4j)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class GraphBackend(ABC):
    """Abstract SPARQL client — legacy interface, kept for compatibility."""

    @abstractmethod
    async def select(self, sparql: str) -> list[dict]:
        """Execute a SPARQL SELECT and return bindings list."""
        ...

    @abstractmethod
    async def select_get(self, sparql: str) -> list[dict]:
        """Execute a SPARQL SELECT (GET method). Identical to select() for non-HTTP backends."""
        ...

    @abstractmethod
    async def construct(self, sparql: str) -> list[dict[str, str]]:
        """Execute SPARQL CONSTRUCT and return list of {subject, predicate, obj}."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release resources."""
        ...


class Neo4jBackend(ABC):
    """Abstract Cypher client — primary backend backed by Neo4j."""

    @abstractmethod
    async def query(self, cypher: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Execute a Cypher read query and return records as dicts."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release resources."""
        ...
