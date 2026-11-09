"""
PRA Chatbot – backend application entry point.
"""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat, config, documents, health, session
from app.core.log_config import configure_logging
from app.core.settings import get_settings

configure_logging()

# Clear the settings cache so every (re)start picks up the latest .env
get_settings.cache_clear()


async def _chat_retention_loop() -> None:
    """Delete expired conversations now, then once every 24 hours."""
    from app.core.log_config import get_logger
    from app.infrastructure.persistence.postgres.database import AsyncSessionLocal
    from app.infrastructure.persistence.postgres.session_store import delete_expired_sessions

    logger = get_logger(__name__)
    days = get_settings().chat_retention_days
    while True:
        try:
            async with AsyncSessionLocal() as db:
                deleted = await delete_expired_sessions(db, days)
            logger.info("chat_retention_cleanup", retention_days=days, **deleted)
        except Exception as exc:
            logger.warning("chat_retention_cleanup_failed", error=str(exc))
        await asyncio.sleep(24 * 60 * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Pre-warm caches on startup for faster first-query response."""
    from app.core.log_config import get_logger
    _logger = get_logger(__name__)

    # 1 — Create all PostgreSQL tables (no-op if already exist)
    from app.infrastructure.persistence.postgres.database import create_tables
    await create_tables()
    _logger.info("startup_db_tables_ready")

    # 2 — Sync PRA entity cache from Neo4j
    try:
        from app.infrastructure.persistence.postgres.database import AsyncSessionLocal
        from app.infrastructure.persistence.postgres.entity_cache import sync_entity_cache
        async with AsyncSessionLocal() as db:
            count = await sync_entity_cache(db)
            _logger.info("startup_entity_cache_synced", entity_count=count)
    except Exception as exc:
        _logger.warning("startup_entity_cache_failed", error=str(exc))

    # 3 — Pre-compile the LangGraph (builds StateGraph + validates all edges once)
    try:
        from app.orchestration.langgraph.graph import get_graph
        get_graph()
        _logger.info("startup_langgraph_compiled")
    except Exception as exc:
        _logger.warning("startup_langgraph_compile_failed", error=str(exc))

    # 4 — Chat retention: delete conversations older than CHAT_RETENTION_DAYS (default 365)
    retention_task = asyncio.create_task(_chat_retention_loop())

    # 5 — Pre-build the orchestrator + similarity index in background
    from app.api.chat import _get_orchestrator
    orch = _get_orchestrator()
    asyncio.create_task(_warm_similarity(orch))
    yield
    retention_task.cancel()

    # Shutdown — close Neo4j driver
    try:
        from app.infrastructure.knowledge_graph.neo4j.client import Neo4jClient
        # driver is per-instance; global teardown via module-level helper if present
    except Exception:
        pass


async def _warm_similarity(orch):
    """Build embedding index at startup so first query is instant."""
    from app.core.log_config import get_logger
    logger = get_logger(__name__)
    try:
        from app.models.schemas import AgentInstructions
        dummy_instr = AgentInstructions()
        await orch._sim.retrieve("payment", 1)
        logger.info("startup_similarity_index_warmed")
    except Exception as e:
        logger.warning("startup_similarity_warm_failed", error=str(e))


app = FastAPI(
    title="PRA Chatbot API",
    description="Chatbot for the Payment Reference Architecture GraphDB repository",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(chat.router, prefix="/api", tags=["chat"])
app.include_router(config.router, prefix="/api", tags=["config"])
app.include_router(session.router, prefix="/api", tags=["session"])
app.include_router(documents.router, prefix="/api", tags=["documents"])
