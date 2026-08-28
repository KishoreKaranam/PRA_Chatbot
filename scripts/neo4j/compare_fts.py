"""Temporary read-only comparison of GraphDB/RDFLib FTS and Neo4j FTS."""
from __future__ import annotations

import asyncio

from app.infrastructure.knowledge_graph.graphdb.client import get_graphdb_client
from app.infrastructure.knowledge_graph.neo4j.client import Neo4jClient
from app.infrastructure.retrieval.full_text.service import FtsRetrievalService
from app.infrastructure.retrieval.neo4j.full_text_service import Neo4jFtsRetrievalService


async def main() -> None:
    graphdb_client = get_graphdb_client()
    neo4j_client = Neo4jClient()
    try:
        old_service = FtsRetrievalService(graphdb_client)
        new_service = Neo4jFtsRetrievalService(neo4j_client)
        for question in (
            "Payment Initiation",
            "business functions",
            "monitor transaction flows",
            "depends on",
        ):
            old_evidence, new_evidence = await asyncio.gather(
                old_service.retrieve(question, 10),
                new_service.retrieve(question, 10),
            )
            print(f"search_term: {new_evidence.search_term}")
            print(f"old hit count: {len(old_evidence.hits)}")
            print(f"new hit count: {len(new_evidence.hits)}")
            print(f"old labels: {[hit.label for hit in old_evidence.hits]}")
            print(f"new labels: {[hit.label for hit in new_evidence.hits]}")
            print(f"old scores: {[hit.score for hit in old_evidence.hits]}")
            print(f"new scores: {[hit.score for hit in new_evidence.hits]}")
            print()
    finally:
        await neo4j_client.close()
        await graphdb_client.close()


if __name__ == "__main__":
    asyncio.run(main())
