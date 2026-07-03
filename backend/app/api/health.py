"""Health-check endpoint."""
from fastapi import APIRouter
from app.graphdb.client import get_graphdb_client
from app.core.settings import get_settings

router = APIRouter()


@router.get("/health")
async def health():
    settings = get_settings()
    graph_ready = False
    triple_count = 0
    try:
        client = get_graphdb_client()
        results = await client.select("SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }")
        graph_ready = bool(results)
        if results:
            triple_count = int(results[0].get("n", 0))
    except Exception:
        pass

    return {
        "status": "ok" if graph_ready else "degraded",
        "graph_ready": graph_ready,
        "graph_backend": settings.graph_backend,
        "triple_count": triple_count,
    }
