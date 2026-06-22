"""Health-check endpoint."""
from fastapi import APIRouter
from app.graphdb.client import get_graphdb_client
from app.core.settings import get_settings

router = APIRouter()


@router.get("/health")
async def health():
    settings = get_settings()
    db_ok = False
    try:
        client = get_graphdb_client()
        results = await client.select("SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o } LIMIT 1")
        db_ok = bool(results)
    except Exception as exc:
        pass

    return {
        "status": "ok" if db_ok else "degraded",
        "graphdb_connected": db_ok,
        "repository": settings.graphdb_repository,
        "graphdb_url": settings.graphdb_base_url,
    }
