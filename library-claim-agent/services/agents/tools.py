"""
LangGraph tool definitions for the conversation agent.

Design principle: LLM decides WHEN to call tools.
                  Tools execute deterministic DB writes.
                  LLM never writes numeric fields.

Tools are built as closures over sweep_id so the DB writer knows
which sweep to update without passing sweep_id in every LLM call.
"""
from __future__ import annotations

import logging
import os

import asyncpg
from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def make_sweep_tools(sweep_id: str):
    """
    Factory: build tool list with sweep_id in closure.
    Called once per sweep session — not per LLM call.
    """

    async def _db() -> asyncpg.Connection:
        url = os.environ["DATABASE_URL"].replace("+asyncpg", "")
        return await asyncpg.connect(url)

    @tool
    async def update_book_edition(book_id: str, edition: str) -> str:
        """Update the edition of a book when the user corrects it verbally."""
        conn = await _db()
        try:
            await conn.execute(
                "UPDATE books SET edition = $1, updated_at = NOW() WHERE id = $2 AND sweep_id = $3",
                edition, book_id, sweep_id,
            )
        finally:
            await conn.close()
        return f"Edition updated for book {book_id}: {edition!r}"

    @tool
    async def exclude_book(book_id: str, reason: str) -> str:
        """
        Exclude a book from the claim (user says it doesn't belong to them).
        Adds to review_queue for adjuster awareness.
        """
        conn = await _db()
        try:
            await conn.execute(
                """UPDATE books SET excluded_from_totals = TRUE,
                   status = 'excluded', updated_at = NOW()
                   WHERE id = $1 AND sweep_id = $2""",
                book_id, sweep_id,
            )
            await conn.execute(
                """INSERT INTO review_queue (sweep_id, ref_id, reason, severity)
                   VALUES ($1, $2, $3, 'info')""",
                sweep_id, book_id, f"Excluded by policyholder: {reason}",
            )
        finally:
            await conn.close()
        return f"Excluded book {book_id}: {reason!r}"

    @tool
    async def flag_for_appraisal(item_id: str, reason: str) -> str:
        """
        Flag a book or item for human appraisal (signed, rare, original art).
        Sets status = 'needs_appraisal' — pricing is NOT attempted.
        """
        conn = await _db()
        try:
            # Try books first, then items
            result = await conn.execute(
                "UPDATE books SET status = 'needs_appraisal', updated_at = NOW() WHERE id = $1 AND sweep_id = $2",
                item_id, sweep_id,
            )
            if "UPDATE 0" in str(result):
                await conn.execute(
                    "UPDATE items SET status = 'needs_appraisal' WHERE id = $1 AND sweep_id = $2",
                    item_id, sweep_id,
                )
            await conn.execute(
                """INSERT INTO review_queue (sweep_id, ref_id, reason, severity)
                   VALUES ($1, $2, $3, 'warning')""",
                sweep_id, item_id, f"Flagged for appraisal: {reason}",
            )
        finally:
            await conn.close()
        return f"Flagged {item_id} for human appraisal: {reason!r}"

    @tool
    async def set_scale_anchor(method: str, value_m: float, description: str) -> str:
        """
        Record scale calibration when user states object dimensions.
        Example: 'these are IKEA Billy shelves, 80cm wide'
        Persists to DB for the measurement worker to use.
        """
        conn = await _db()
        try:
            await conn.execute(
                "UPDATE sweeps SET scale_method = $1, scale_value_m = $2 WHERE id = $3",
                method, value_m, sweep_id,
            )
        finally:
            await conn.close()
        return (
            f"Scale anchor recorded: {method}={value_m}m ({description}). "
            "I'll use this to calibrate measurements."
        )

    @tool
    async def confirm_art_as_print(item_id: str) -> str:
        """
        Mark an art item as confirmed print (not original).
        Enables replacement cost pricing at market value.
        """
        conn = await _db()
        try:
            await conn.execute(
                "UPDATE items SET user_confirmed_print = TRUE WHERE id = $1 AND sweep_id = $2",
                item_id, sweep_id,
            )
        finally:
            await conn.close()
        return f"Art item {item_id} confirmed as print — I'll price it at reproduction value."

    @tool
    def end_sweep() -> str:
        """
        Signal that the camera sweep is complete.
        Triggers worker dispatch and packet generation.
        """
        return "SWEEP_END_SIGNAL"

    return [
        update_book_edition,
        exclude_book,
        flag_for_appraisal,
        set_scale_anchor,
        confirm_art_as_print,
        end_sweep,
    ]
