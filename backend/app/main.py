"""
PRA Chatbot – backend application entry point.
"""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat, config, health
from app.core.log_config import configure_logging
from app.core.settings import get_settings

configure_logging()

# Clear the settings cache so every (re)start picks up the latest .env
get_settings.cache_clear()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Pre-warm caches on startup for faster first-query response."""
    # Pre-build the orchestrator + similarity index in background
    from app.api.chat import _get_orchestrator
    orch = _get_orchestrator()
    # Trigger similarity index build without blocking too long
    asyncio.create_task(_warm_similarity(orch))
    yield


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
