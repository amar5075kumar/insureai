"""
Async database access layer for the FastAPI backend.
Workers use services/workers/db.py (different connection pool, raw asyncpg).
This module uses SQLAlchemy async ORM for the backend service.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger(__name__)

# Engine — created once at startup
engine = create_async_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=settings.debug,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


async def init_db() -> None:
    """Called once at application startup."""
    from sqlalchemy import text as sa_text
    async with engine.begin() as conn:
        await conn.execute(sa_text("SELECT 1"))
    logger.info("Database connection established")


@asynccontextmanager
async def get_db() -> AsyncIterator[AsyncSession]:
    """Async context manager for a database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
