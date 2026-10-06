"""
Database access for Celery workers.
Workers run in a separate process from FastAPI and cannot import app.database.
This module maintains its own asyncpg connection pool.

Pattern: _run() bridges async functions into sync Celery task context.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional, Tuple

import asyncpg

logger = logging.getLogger(__name__)

# Module-level pool — initialised lazily on first use
_pool: asyncpg.Pool | None = None


async def _get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        # DATABASE_URL uses +asyncpg driver which asyncpg itself doesn't understand
        url = os.environ["DATABASE_URL"].replace("+asyncpg", "")
        _pool = await asyncpg.create_pool(
            url,
            min_size=2,
            max_size=10,
            command_timeout=30,
        )
        logger.info("Worker DB pool created")
    return _pool


def _run(coro):
    """
    Run an async coroutine from a synchronous Celery task.
    Handles the case where an event loop may or may not be running.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're inside an async context — use a thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


# ── Book identification ──────────────────────────────────────────────────────

def update_book_identification(book_id: str, sweep_id: str, data: dict) -> None:
    """Write book identification results to DB."""
    async def _run_async() -> None:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE books
                SET status = $1,
                    title = $2,
                    author = $3,
                    isbn = $4,
                    edition = $5,
                    ocr_raw_text = $6,
                    id_confidence = $7,
                    updated_at = NOW()
                WHERE id = $8 AND sweep_id = $9
                """,
                data.get("status"),
                data.get("title"),
                data.get("author"),
                data.get("isbn"),
                data.get("edition"),
                data.get("ocr_raw_text"),
                data.get("id_confidence"),
                book_id,
                sweep_id,
            )
    _run(_run_async())


# ── Book pricing ─────────────────────────────────────────────────────────────

def update_book_pricing(book_id: str, sweep_id: str, pricing) -> None:
    """
    Write pricing results to DB.
    pricing=None → mark excluded_from_totals=True (scraper failed).
    """
    async def _run_async() -> None:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            if pricing is None:
                await conn.execute(
                    """
                    UPDATE books
                    SET excluded_from_totals = TRUE,
                        updated_at = NOW()
                    WHERE id = $1
                    """,
                    book_id,
                )
                return

            await conn.execute(
                """
                UPDATE books
                SET replacement_cost_amount = $1,
                    replacement_cost_source = $2,
                    replacement_cost_url = $3,
                    replacement_cost_retrieved_at = $4,
                    replacement_cost_converted = $5,
                    used_value_amount = $6,
                    used_value_source = $7,
                    used_value_url = $8,
                    used_value_retrieved_at = $9,
                    used_value_condition = $10,
                    updated_at = NOW()
                WHERE id = $11
                """,
                pricing.replacement_cost_amount,
                pricing.replacement_cost_source,
                pricing.replacement_cost_url,
                pricing.replacement_cost_retrieved_at,
                pricing.replacement_cost_converted,
                pricing.used_value_amount,
                pricing.used_value_source,
                pricing.used_value_url,
                pricing.used_value_retrieved_at,
                pricing.used_value_condition,
                book_id,
            )
    _run(_run_async())


# ── Sweep metadata ────────────────────────────────────────────────────────────

def get_sweep_country_currency(sweep_id: str) -> Tuple[str, str]:
    """Returns (country, currency) for a sweep."""
    async def _run_async() -> Tuple[str, str]:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT country, currency FROM sweeps WHERE id = $1",
                sweep_id,
            )
            return (row["country"], row["currency"]) if row else ("GB", "GBP")
    return _run(_run_async())


def get_scale_anchor(sweep_id: str) -> Optional[dict]:
    """Returns scale anchor dict if the user provided shelf dimensions."""
    async def _run_async() -> Optional[dict]:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT scale_method, scale_value_m FROM sweeps WHERE id = $1",
                sweep_id,
            )
            if row and row["scale_value_m"] is not None:
                return {
                    "method": row["scale_method"],
                    "value_m": row["scale_value_m"],
                }
            return None
    return _run(_run_async())


# ── Room geometry ─────────────────────────────────────────────────────────────

def update_room_geometry(sweep_id: str, room) -> None:
    """Write room geometry results to DB."""
    async def _run_async() -> None:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            if room is None:
                await conn.execute(
                    """
                    INSERT INTO room_geometry (sweep_id, confidence, notes)
                    VALUES ($1, 0.0, 'Measurement failed')
                    ON CONFLICT (sweep_id) DO UPDATE
                    SET notes = 'Measurement failed', updated_at = NOW()
                    """,
                    sweep_id,
                )
                return

            await conn.execute(
                """
                INSERT INTO room_geometry
                    (sweep_id, length_m, width_m, height_m, floor_area_m2,
                     wall_area_m2, shelved_wall_area_m2, scale_method, confidence)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (sweep_id) DO UPDATE
                SET length_m = $2, width_m = $3, height_m = $4,
                    floor_area_m2 = $5, wall_area_m2 = $6,
                    shelved_wall_area_m2 = $7, scale_method = $8,
                    confidence = $9, updated_at = NOW()
                """,
                sweep_id,
                getattr(room, "length_m", None),
                getattr(room, "width_m", None),
                getattr(room, "height_m", None),
                getattr(room, "floor_area_m2", None),
                getattr(room, "wall_area_m2", None),
                getattr(room, "shelved_wall_area_m2", None),
                getattr(room, "scale_method", None),
                getattr(room, "confidence", None),
            )
    _run(_run_async())
