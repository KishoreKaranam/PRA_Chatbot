"""Live isolated Neo4j vector-service test; does not modify Neo4j."""
from __future__ import annotations

import asyncio
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.infrastructure.knowledge_graph.neo4j.client import Neo4jClient
from app.infrastructure.retrieval.neo4j.vector_service import Neo4jVectorRetrievalService


async def main() -> None:
    client = Neo4jClient()
    service = Neo4jVectorRetrievalService(client)
    try:
        evidence = await service.retrieve("What is Payment Initiation?", max_results=5)
        print("mode=", evidence.mode)
        print("hit_count=", len(evidence.hits))
        print("note=", evidence.note)
        for index, hit in enumerate(evidence.hits, 1):
            print(
                f"{index}: label={hit.label!r} score={hit.score:.16f} "
                f"uri={hit.uri!r} text={hit.text!r}"
            )
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
