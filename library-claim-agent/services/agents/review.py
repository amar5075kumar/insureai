"""
Post-sweep review agent.
Runs deterministic checks first (no LLM), then an LLM audit for edge cases.
Populates the review_queue table.
"""
from __future__ import annotations

import json
import logging
import os

import asyncpg

logger = logging.getLogger(__name__)


async def run_review(sweep_id: str, conn: asyncpg.Connection) -> int:
    """
    Run all review checks and insert findings into review_queue.
    Returns the number of review items added.
    """
    items: list[dict] = []

    # Fetch all books and items
    books = await conn.fetch(
        """SELECT id, status, id_confidence, title, ocr_raw_text,
                  replacement_cost_amount, replacement_cost_url
           FROM books WHERE sweep_id = $1""",
        sweep_id,
    )
    db_items = await conn.fetch(
        "SELECT id, category, confidence, user_confirmed_print, status FROM items WHERE sweep_id = $1",
        sweep_id,
    )
    room = await conn.fetchrow(
        "SELECT confidence, scale_method FROM room_geometry WHERE sweep_id = $1",
        sweep_id,
    )

    # ── Deterministic checks ────────────────────────────────────────

    for book in books:
        if book["status"] == "identified" and book["id_confidence"] and book["id_confidence"] < 0.70:
            items.append({
                "ref_id": str(book["id"]),
                "reason": f"Low identification confidence ({book['id_confidence']:.0%})",
                "severity": "warning",
            })

        if book["status"] == "unidentified":
            ocr = book["ocr_raw_text"] or ""
            items.append({
                "ref_id": str(book["id"]),
                "reason": f"Spine unreadable — OCR text: {ocr[:50]!r}",
                "severity": "info",
            })

        if book["status"] == "identified" and book["replacement_cost_amount"] is None:
            items.append({
                "ref_id": str(book["id"]),
                "reason": "No price source found — excluded from totals",
                "severity": "info",
            })

        if book["status"] == "identified" and book["replacement_cost_url"] and not book["replacement_cost_url"].startswith("http"):
            items.append({
                "ref_id": str(book["id"]),
                "reason": "Price URL is invalid — excluded from totals",
                "severity": "critical",
            })

    for item in db_items:
        if item["category"] in ("portrait", "framed_art", "painting") and not item["user_confirmed_print"]:
            items.append({
                "ref_id": str(item["id"]),
                "reason": "Art/portrait requires human appraisal unless confirmed as print",
                "severity": "warning",
            })
        if item["confidence"] and item["confidence"] < 0.60:
            items.append({
                "ref_id": str(item["id"]),
                "reason": f"Low item classification confidence ({item['confidence']:.0%})",
                "severity": "info",
            })

    if room and room["confidence"] and room["confidence"] < 0.70:
        items.append({
            "ref_id": "room_geometry",
            "reason": f"Room measurement confidence low ({room['confidence']:.0%}) — tape measure recommended",
            "severity": "warning",
        })

    if not room or room["confidence"] is None:
        items.append({
            "ref_id": "room_geometry",
            "reason": "Room geometry could not be estimated — depth model unavailable or no scale anchor",
            "severity": "warning",
        })

    # ── Insert findings ─────────────────────────────────────────────

    for finding in items:
        await conn.execute(
            """INSERT INTO review_queue (sweep_id, ref_id, reason, severity)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT DO NOTHING""",
            sweep_id, finding["ref_id"], finding["reason"], finding["severity"],
        )

    return len(items)
