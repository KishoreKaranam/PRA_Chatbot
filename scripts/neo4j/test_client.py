"""Minimal read-only Neo4j client check."""
from __future__ import annotations

import asyncio

from app.infrastructure.knowledge_graph.neo4j import Neo4jClient


async def main() -> None:
    client = Neo4jClient()
    try:
        result = await client.execute_read_query(
            "MATCH (n) RETURN count(n) AS count"
        )
        print(result[0]["count"] if result else 0)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
