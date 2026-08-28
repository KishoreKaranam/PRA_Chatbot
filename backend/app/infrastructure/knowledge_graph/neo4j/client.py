"""Small Neo4j client used by read and migration tooling."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from neo4j import AsyncGraphDatabase, AsyncDriver

from app.core.settings import get_settings


class Neo4jClient:
    """Async Neo4j client with explicit read and migration-write operations."""

    def __init__(self) -> None:
        settings = get_settings()
        dotenv_path = Path(__file__).resolve().parents[4] / ".env"
        dotenv = dotenv_values(dotenv_path)

        self._uri = self._value(settings, "neo4j_uri", "NEO4J_URI", dotenv)
        self._user = self._value(settings, "neo4j_user", "NEO4J_USER", dotenv)
        self._password = self._value(settings, "neo4j_password", "NEO4J_PASSWORD", dotenv)
        self._database = self._value(settings, "neo4j_database", "NEO4J_DATABASE", dotenv)
        self._driver: AsyncDriver | None = None

        if not self._uri:
            raise ValueError("NEO4J_URI is not configured")
        if not self._user:
            raise ValueError("NEO4J_USER is not configured")
        if not self._password:
            raise ValueError("NEO4J_PASSWORD is not configured")

    @staticmethod
    def _value(settings: Any, attribute: str, environment_name: str, dotenv: dict[str, Any]) -> str:
        configured = getattr(settings, attribute, None)
        return str(configured or os.getenv(environment_name) or dotenv.get(environment_name) or "")

    async def connect(self) -> None:
        """Create the driver and verify connectivity."""
        if self._driver is None:
            self._driver = AsyncGraphDatabase.driver(
                self._uri,
                auth=(self._user, self._password),
            )
        await self._driver.verify_connectivity()

    async def execute_read_query(self, query: str, **parameters: Any) -> list[dict[str, Any]]:
        """Execute a Cypher read query and return records as dictionaries."""
        if self._driver is None:
            await self.connect()

        assert self._driver is not None
        async with self._driver.session(database=self._database or None) as session:
            result = await session.run(query, **parameters)
            return [record.data() async for record in result]

    async def execute_write_query(self, query: str, **parameters: Any) -> list[dict[str, Any]]:
        """Execute an explicit Cypher write query and return records as dictionaries."""
        if self._driver is None:
            await self.connect()

        assert self._driver is not None
        async with self._driver.session(database=self._database or None) as session:
            result = await session.run(query, **parameters)
            return [record.data() async for record in result]

    async def close(self) -> None:
        """Close the Neo4j driver."""
        if self._driver is not None:
            await self._driver.close()
            self._driver = None
