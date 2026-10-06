"""
FastAPI application entry point.
Sets up middleware, routers, and startup/shutdown lifecycle.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import sweeps, websocket, webhooks, config
from app.config import settings
from app.database import init_db

logger = logging.getLogger(__name__)

# Module-level Redis client shared across the app
_redis_client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    global _redis_client

    logger.info(f"Starting Library Claim Agent (SWEEP_PROFILE={settings.sweep_profile})")

    # Database
    await init_db()

    # Redis
    _redis_client = await aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=False,  # Keep bytes for PCM audio
    )
    webhooks.set_redis(_redis_client)
    logger.info("Redis connected")

    # Storage: filesystem mode (no MinIO needed)
    import os
    os.makedirs(settings.frames_dir, exist_ok=True)
    logger.info(f"Frame storage: filesystem at {settings.frames_dir}")

    yield  # ← Application runs here

    # Shutdown
    if _redis_client:
        await _redis_client.aclose()
    logger.info("Shutdown complete")


# ── Application ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="Library Claim Agent",
    description="Live voice+vision insurance inventory agent",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url=None,
)

# CORS — allow the React frontend origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──────────────────────────────────────────────────────────────────

app.include_router(sweeps.router, prefix="/sweeps", tags=["sweeps"])
app.include_router(websocket.router, tags=["websocket"])
app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
app.include_router(config.router, tags=["config"])


# ── Health check ─────────────────────────────────────────────────────────────

@app.get("/health", tags=["health"])
async def health() -> dict:
    return {
        "status": "ok",
        "profile": settings.sweep_profile,
        "version": "0.1.0",
    }
