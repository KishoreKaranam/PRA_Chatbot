"""
Abstract base class for SPARQL graph backends.

Supports pluggable implementations:
  - GraphDBClient: HTTP SPARQL endpoint (requires running GraphDB)
  - RDFLibClient:  In-memory graph loaded from .ttl files (no external DB)
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class GraphBackend(ABC):
    """Abstract SPARQL client — implemented by GraphDB and RDFLib backends."""

    @abstractmethod
    async def select(self, sparql: str) -> list[dict]:
        """Execute a SPARQL SELECT and return bindings list."""
        ...

    @abstractmethod
    async def select_get(self, sparql: str) -> list[dict]:
        """
        Execute a SPARQL SELECT (GET method for connectors).
        For non-HTTP backends, behaves identically to select().
        """
        ...

    @abstractmethod
    async def construct(self, sparql: str) -> list[dict[str, str]]:
        """Execute SPARQL CONSTRUCT and return list of {subject, predicate, obj}."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release resources."""
        ...
