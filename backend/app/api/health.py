"""Health-check endpoint."""
from fastapi import APIRouter
from app.core.settings import get_settings

router = APIRouter()


@router.get("/health")
async def health():
    settings = get_settings()
    graph_ready = False
    node_count = 0
    error_msg = None

    try:
        from app.infrastructure.knowledge_graph.neo4j.client import Neo4jClient
        client = Neo4jClient()
        await client.connect()
        results = await client.execute_read_query("MATCH (n) RETURN count(n) AS node_count")
        if results:
            node_count = results[0].get("node_count", 0)
            graph_ready = True
        await client.close()
    except Exception as exc:
        error_msg = str(exc)

    return {
        "status": "ok" if graph_ready else "degraded",
        "graph_ready": graph_ready,
        "graph_backend": "neo4j",
        "graph_backend_label": "Neo4j",
        "neo4j_uri": settings.neo4j_uri,
        "node_count": node_count,
        **({"error": error_msg} if error_msg else {}),
    }
