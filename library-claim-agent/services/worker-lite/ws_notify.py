"""
Push inventory_update to the browser WebSocket relay via Redis pub/sub.
Called after book identification or pricing completes.
"""
from __future__ import annotations

import asyncio
import json
import os
import logging

import asyncpg
import redis as _redis_sync

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "").replace("+asyncpg", "")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")


async def _fetch_book(book_id: str, sweep_id: str) -> dict | None:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        row = await conn.fetchrow(
            """SELECT id, status, title, author, isbn, id_confidence, detection_confidence,
                      replacement_cost_amount, replacement_cost_source,
                      used_value_amount, used_value_source
               FROM books WHERE id=$1 AND sweep_id=$2""",
            book_id, sweep_id,
        )
        if not row:
            return None
        return {
            "id": str(row["id"]),
            "status": row["status"],
            "crop_url": f"/sweeps/{sweep_id}/crops/{row['id']}",
            "title": row["title"],
            "author": row["author"],
            "isbn": row["isbn"],
            "id_confidence": float(row["id_confidence"]) if row["id_confidence"] else None,
            "detection_confidence": float(row["detection_confidence"]) if row["detection_confidence"] else None,
            "replacement_cost": {
                "amount": float(row["replacement_cost_amount"]),
                "source": row["replacement_cost_source"],
            } if row["replacement_cost_amount"] else None,
            "used_value": {
                "amount": float(row["used_value_amount"]),
                "source": row["used_value_source"],
            } if row["used_value_amount"] else None,
        }
    finally:
        await conn.close()


def push_book_update(sweep_id: str, book_id: str) -> None:
    """Publish inventory_update for a single book to the WebSocket relay."""
    try:
        book = asyncio.run(_fetch_book(book_id, sweep_id))
        if not book:
            return
        r = _redis_sync.from_url(REDIS_URL, decode_responses=True)
        r.publish(
            f"ws_broadcast:{sweep_id}",
            json.dumps({"type": "inventory_update", "books": [book], "items": []}),
        )
        r.close()
    except Exception as e:
        logger.warning(f"ws_notify failed [{book_id[:8]}]: {e}")
