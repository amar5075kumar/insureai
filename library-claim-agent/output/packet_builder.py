"""
Claim packet builder.

Assembles ClaimPacket from DB, computes totals deterministically,
validates, generates HTML/PDF report, and saves ZIP to MinIO.

The FINALIZING state prevents late worker writes from corrupting the packet:
  1. Set state = 'finalizing'
  2. Assemble packet from DB (workers in this state write to a late_results
     side-table — NOT implemented in MVP but the state lock is in place)
  3. Compute totals
  4. Validate
  5. Generate report
  6. Save ZIP to MinIO
  7. Set state = 'complete'
"""
from __future__ import annotations

import io
import json
import logging
import zipfile
from datetime import datetime, timezone
from typing import List

import asyncpg

from output.compute_totals import compute_totals
from output.frame_store import FrameStore
from output.schemas import (
    BookRecord,
    ClaimPacket,
    ItemDimensions,
    ItemRecord,
    PriceRecord,
    ReplacementCostRange,
    ReviewItem,
    RoomGeometry,
    SweepInfo,
    Totals,
    UsedValueRecord,
)
from output.validator import PacketValidator

logger = logging.getLogger(__name__)


async def build_and_save_packet(sweep_id: str) -> ClaimPacket:
    """
    Full pipeline: DB → packet → validate → report → MinIO.
    Returns the assembled ClaimPacket.
    """
    import os
    url = os.environ["DATABASE_URL"].replace("+asyncpg", "")
    conn = await asyncpg.connect(url)

    try:
        # Lock: prevent late worker writes
        await conn.execute(
            "UPDATE sweeps SET state = 'finalizing' WHERE id = $1", sweep_id
        )

        sweep_row = await conn.fetchrow("SELECT * FROM sweeps WHERE id = $1", sweep_id)
        books = await _load_books(sweep_id, conn)
        items = await _load_items(sweep_id, conn)
        room = await _load_room(sweep_id, conn)
        review_items = await _load_review_queue(sweep_id, conn)
    finally:
        await conn.close()

    # Compute totals — deterministic, no LLM
    totals = compute_totals(books, items)

    duration_s = 0
    if sweep_row["completed_at"] and sweep_row["captured_at"]:
        duration_s = int(
            (sweep_row["completed_at"] - sweep_row["captured_at"]).total_seconds()
        )

    packet = ClaimPacket(
        sweep=SweepInfo(
            id=sweep_id,
            captured_at=sweep_row["captured_at"].isoformat(),
            device=sweep_row.get("device"),
            duration_s=duration_s,
            country=sweep_row["country"],
            currency=sweep_row["currency"],
        ),
        room=room,
        books=books,
        items=items,
        totals=totals,
        review_queue=review_items,
    )

    # Validate
    frame_store = FrameStore()
    report = PacketValidator().validate(packet, frame_store)
    if not report.valid:
        for err in report.errors:
            logger.error(f"Packet validation error [{sweep_id}]: {err}")
    if report.warnings:
        for w in report.warnings:
            logger.warning(f"Packet warning [{sweep_id}]: {w}")

    # Generate HTML report
    html = _generate_html(packet)

    # Build ZIP
    zip_bytes = _build_zip(sweep_id, packet, html, frame_store)

    # Save to filesystem (FRAMES_DIR/sweep_id/claim_packet.zip)
    await _save_to_filesystem(sweep_id, zip_bytes)

    # Mark complete
    conn2 = await asyncpg.connect(url)
    try:
        await conn2.execute(
            "UPDATE sweeps SET state = 'complete', completed_at = NOW() WHERE id = $1",
            sweep_id,
        )
    finally:
        await conn2.close()

    logger.info(
        f"Packet saved for {sweep_id}: "
        f"{totals.book_count} books, {totals.books_identified} identified, "
        f"£{totals.books_replacement_cost:.2f} replacement cost"
    )
    return packet


async def _load_books(sweep_id: str, conn: asyncpg.Connection) -> List[BookRecord]:
    rows = await conn.fetch(
        "SELECT * FROM books WHERE sweep_id = $1 ORDER BY created_at",
        sweep_id,
    )
    books = []
    for r in rows:
        rc = None
        if r["replacement_cost_amount"]:
            rc = PriceRecord(
                amount=r["replacement_cost_amount"],
                source=r["replacement_cost_source"] or "AbeBooks",
                url=r["replacement_cost_url"] or "",
                retrieved_at=(r["replacement_cost_retrieved_at"] or datetime.now(timezone.utc)).isoformat(),
                converted=r["replacement_cost_converted"] or False,
            )

        uv = None
        if r["used_value_amount"]:
            uv = UsedValueRecord(
                amount=r["used_value_amount"],
                source=r["used_value_source"] or "AbeBooks",
                url=r["used_value_url"] or "",
                retrieved_at=(r["used_value_retrieved_at"] or datetime.now(timezone.utc)).isoformat(),
                condition_assumed=r["used_value_condition"] or "Good",
            )

        status = r["status"]
        if status not in ("identified", "unidentified", "needs_appraisal", "ocr_only", "low_confidence"):
            status = "unidentified"

        title = r["title"] if status == "identified" else None

        books.append(BookRecord(
            id=str(r["id"]),
            shelf=r["shelf"],
            position=r["position"],
            frame_ref=r["frame_ref"],
            status=status,
            title=title,
            author=r["author"],
            edition=r["edition"],
            isbn=r["isbn"],
            spine_height_cm=r["spine_height_cm"],
            spine_thickness_cm=r["spine_thickness_cm"],
            id_confidence=r["id_confidence"],
            replacement_cost=rc,
            used_value=uv,
        ))
    return books


async def _load_items(sweep_id: str, conn: asyncpg.Connection) -> List[ItemRecord]:
    rows = await conn.fetch(
        "SELECT * FROM items WHERE sweep_id = $1 ORDER BY created_at",
        sweep_id,
    )
    items = []
    for r in rows:
        rc = None
        if r["replacement_cost_low"] and r["replacement_cost_url"] and r["replacement_cost_url"].startswith("http"):
            rc = ReplacementCostRange(
                low=r["replacement_cost_low"],
                high=r["replacement_cost_high"] or r["replacement_cost_low"],
                source=r["replacement_cost_source"] or "Google Shopping",
                url=r["replacement_cost_url"] or "",
                retrieved_at=(r["replacement_cost_retrieved_at"] or datetime.now(timezone.utc)).isoformat(),
            )

        items.append(ItemRecord(
            id=str(r["id"]),
            category=r["category"],
            description=r["description"],
            brand_model=r["brand_model"],
            frame_ref=r["frame_ref"],
            dimensions_cm=ItemDimensions(w=r["width_cm"], h=r["height_cm"], d=r["depth_cm"]),
            status=r["status"] if r["status"] in ("priced","range","needs_appraisal","no_price","processing") else "no_price",
            replacement_cost=rc,
            confidence=r["confidence"],
        ))
    return items


async def _load_room(sweep_id: str, conn: asyncpg.Connection) -> RoomGeometry:
    row = await conn.fetchrow(
        "SELECT * FROM room_geometry WHERE sweep_id = $1", sweep_id
    )
    if not row:
        return RoomGeometry()
    return RoomGeometry(
        length_m=row["length_m"],
        width_m=row["width_m"],
        height_m=row["height_m"],
        floor_area_m2=row["floor_area_m2"],
        wall_area_m2=row["wall_area_m2"],
        shelved_wall_area_m2=row["shelved_wall_area_m2"],
        scale_method=row["scale_method"],
        confidence=row["confidence"],
    )


async def _load_review_queue(sweep_id: str, conn: asyncpg.Connection) -> List[ReviewItem]:
    rows = await conn.fetch(
        "SELECT ref_id, reason, severity FROM review_queue WHERE sweep_id = $1 ORDER BY created_at",
        sweep_id,
    )
    return [
        ReviewItem(ref_id=r["ref_id"], reason=r["reason"], severity=r["severity"])
        for r in rows
    ]


def _generate_html(packet: ClaimPacket) -> str:
    """Generate a simple HTML report from the packet."""
    currency = packet.sweep.currency
    t = packet.totals

    lines = [
        f"<html><head><title>Claim Report {packet.sweep.id[:8]}</title>",
        "<style>body{font-family:Arial,sans-serif;max-width:900px;margin:auto;padding:2em}",
        "table{width:100%;border-collapse:collapse}td,th{border:1px solid #ccc;padding:6px;text-align:left}",
        "th{background:#f0f0f0}.warn{background:#fff3cd}.critical{background:#f8d7da}</style></head><body>",
        f"<h1>Library Contents Claim</h1>",
        f"<p><strong>Date:</strong> {packet.sweep.captured_at[:10]} | "
        f"<strong>Country:</strong> {packet.sweep.country} | "
        f"<strong>Currency:</strong> {currency}</p>",
        f"<h2>Summary</h2>",
        f"<p>Books found: <strong>{t.book_count}</strong> "
        f"({t.books_identified} identified, {t.books_unidentified} unidentified) | "
        f"Shelf run: <strong>{t.shelf_run_m:.1f}m</strong></p>",
        f"<p>Replacement cost (books): <strong>{currency} {t.books_replacement_cost:.2f}</strong> | "
        f"Used value: {currency} {t.books_used_value:.2f}</p>",
        f"<p>Items: {len(packet.items)} | "
        f"Items cost: {currency} {t.items_replacement_cost_low:.2f}–{t.items_replacement_cost_high:.2f}</p>",
    ]

    if packet.room.floor_area_m2:
        lines.append(
            f"<p>Floor area: <strong>{packet.room.floor_area_m2:.1f}m²</strong> | "
            f"Wall area: {(packet.room.wall_area_m2 or 0):.1f}m² | "
            f"Scale: {packet.room.scale_method or 'unknown'}</p>"
        )

    lines += [
        "<h2>Books</h2><table>",
        "<tr><th>#</th><th>Title</th><th>Author</th><th>ISBN</th>"
        "<th>Status</th><th>Confidence</th>"
        f"<th>Replacement ({currency})</th><th>Used ({currency})</th><th>Source URL</th></tr>",
    ]

    for i, book in enumerate(packet.books, 1):
        rep = f"{book.replacement_cost.amount:.2f}" if book.replacement_cost else "—"
        used = f"{book.used_value.amount:.2f}" if book.used_value else "—"
        src_url = book.replacement_cost.url if book.replacement_cost else "—"
        conf = f"{book.id_confidence:.0%}" if book.id_confidence else "—"
        row_class = "" if book.status == "identified" else ' class="warn"'
        lines.append(
            f"<tr{row_class}><td>{i}</td><td>{book.title or '—'}</td>"
            f"<td>{book.author or '—'}</td><td>{book.isbn or '—'}</td>"
            f"<td>{book.status}</td><td>{conf}</td>"
            f"<td>{rep}</td><td>{used}</td>"
            f"<td><a href='{src_url}' target='_blank'>link</a></td></tr>"
        )

    lines += ["</table>"]

    if packet.review_queue:
        lines += [
            "<h2>Review Queue</h2><table>",
            "<tr><th>Reference</th><th>Reason</th><th>Severity</th></tr>",
        ]
        for item in packet.review_queue:
            row_class = f' class="{item.severity}"' if item.severity in ("warning", "critical") else ""
            lines.append(
                f"<tr{row_class}><td>{item.ref_id}</td>"
                f"<td>{item.reason}</td><td>{item.severity}</td></tr>"
            )
        lines += ["</table>"]

    lines += ["</body></html>"]
    return "\n".join(lines)


def _build_zip(
    sweep_id: str,
    packet: ClaimPacket,
    html: str,
    frame_store: FrameStore,
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "claim_packet.json",
            json.dumps(packet.model_dump(), indent=2, ensure_ascii=False, default=str),
        )
        zf.writestr("claim_report.html", html)

        # Include referenced frames
        all_refs = (
            {b.frame_ref for b in packet.books}
            | {i.frame_ref for i in packet.items}
        )
        for ref in all_refs:
            data = frame_store.get(ref)
            if data:
                filename = f"frames/{ref.split('/')[-1]}"
                zf.writestr(filename, data)

    return buf.getvalue()


async def _save_to_filesystem(sweep_id: str, zip_bytes: bytes) -> None:
    """Save claim packet ZIP to local filesystem (same dir the backend serves from)."""
    import os
    frames_dir = os.environ.get("FRAMES_DIR", "/app/frame_data")
    sweep_dir = os.path.join(frames_dir, sweep_id)
    os.makedirs(sweep_dir, exist_ok=True)
    packet_path = os.path.join(sweep_dir, "claim_packet.zip")
    with open(packet_path, "wb") as f:
        f.write(zip_bytes)
    logger.info(f"Packet saved to filesystem: {packet_path} ({len(zip_bytes)} bytes)")
