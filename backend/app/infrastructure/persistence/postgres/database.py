"""
Async PostgreSQL engine and session factory.
============================================
Uses SQLAlchemy 2.x async engine with asyncpg driver.

Usage:
    # Inject into FastAPI endpoints
    async def my_endpoint(db: AsyncSession = Depends(get_db)):
        ...

    # Use directly in services
    async with AsyncSessionLocal() as db:
        ...
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text

from app.core.settings import get_settings
from app.core.log_config import get_logger

logger = get_logger(__name__)


def _build_engine():
    settings = get_settings()
    engine = create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,      # detect stale connections automatically
        pool_recycle=3600,       # recycle connections every 1 hour
        echo=False,              # set True to log all SQL (debug only)
    )
    logger.info(
        "db_engine_created",
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )
    return engine


# ── Module-level singletons ───────────────────────────────────────────────────

engine = _build_engine()

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,   # keep objects usable after commit
    autoflush=False,
    autocommit=False,
)


# ── Base class for all ORM models ─────────────────────────────────────────────

class Base(DeclarativeBase):
    """All SQLAlchemy ORM models inherit from this."""
    pass


# ── FastAPI dependency ────────────────────────────────────────────────────────

async def get_db() -> AsyncSession:
    """
    FastAPI dependency — yields an async DB session per request.

    Usage in endpoints:
        async def endpoint(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ── Table creation ────────────────────────────────────────────────────────────

async def create_tables() -> None:
    """
    Create all tables defined in ORM models if they don't exist.
    Called once at application startup.
    """
    # Import models here so metadata is populated before create_all
    from app.infrastructure.persistence.postgres import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(
            "ALTER TABLE retrieval_log "
            "ADD COLUMN IF NOT EXISTS neo4j_count INTEGER NOT NULL DEFAULT 0"
        ))

    logger.info("db_tables_created")


async def drop_tables() -> None:
    """
    Drop all tables. USE WITH CAUTION — only for dev/testing.
    """
    from app.infrastructure.persistence.postgres import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    logger.info("db_tables_dropped")
