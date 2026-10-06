"""
Sweep management endpoints.
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse
from livekit.api import AccessToken, VideoGrants
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.config import settings
from app.database import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


class CreateSweepRequest(BaseModel):
    country: str = Field("GB", min_length=2, max_length=2)
    currency: str = Field("GBP", min_length=3, max_length=3)
    device: Optional[str] = None


class SweepResponse(BaseModel):
    sweep_id: str
    ws_url: str
    state: str
    country: str
    currency: str


class SweepStateResponse(BaseModel):
    sweep_id: str
    state: str
    book_count: int
    books_identified: int
    items_count: int
    processing_progress: Optional[float] = None
    packet_ready: bool = False
    packet_url: Optional[str] = None


class LiveKitTokenResponse(BaseModel):
    token: str
    url: str


class SweepAnalytics(BaseModel):
    sweep_id: str
    state: str
    country: str
    currency: str
    created_at: Optional[str] = None
    # Detection stats
    total_books: int = 0
    identified_books: int = 0
    low_confidence_books: int = 0
    unidentified_books: int = 0
    total_items: int = 0
    # Confidence averages
    avg_detection_confidence: Optional[float] = None
    avg_ocr_confidence: Optional[float] = None
    # Value
    total_replacement_value: Optional[float] = None
    currency_symbol: str = "£"
    # Evidence
    packet_available: bool = False
    packet_url: Optional[str] = None
    # Books list (for detail view)
    books: Optional[list] = None


@router.get("", response_model=list[SweepAnalytics])
async def list_sweeps() -> list[SweepAnalytics]:
    """List all sweeps with analytics summary."""
    import os
    async with get_db() as db:
        rows = await db.execute(text("""
            SELECT
                s.id, s.state, s.country, s.currency,
                s.captured_at,
                COUNT(b.id) AS total_books,
                COUNT(b.id) FILTER (WHERE b.status = 'identified') AS identified,
                COUNT(b.id) FILTER (WHERE b.status = 'low_confidence') AS low_conf,
                COUNT(b.id) FILTER (WHERE b.status = 'unidentified') AS unidentified,
                AVG(b.detection_confidence) FILTER (WHERE b.detection_confidence IS NOT NULL) AS avg_det_conf,
                AVG(b.id_confidence) FILTER (WHERE b.id_confidence IS NOT NULL AND b.status != 'unidentified') AS avg_ocr_conf,
                SUM(b.replacement_cost_amount) FILTER (WHERE b.replacement_cost_amount IS NOT NULL) AS total_value,
                (SELECT COUNT(*) FROM items i WHERE i.sweep_id = s.id) AS total_items
            FROM sweeps s
            LEFT JOIN books b ON b.sweep_id = s.id
            GROUP BY s.id, s.state, s.country, s.currency, s.captured_at
            ORDER BY s.captured_at DESC NULLS LAST
        """))
        sweeps = rows.fetchall()

    CURRENCY_SYMBOL = {"GBP": "£", "USD": "$", "EUR": "€", "INR": "₹", "JPY": "¥"}
    result = []
    for s in sweeps:
        packet_path = os.path.join(settings.frames_dir, str(s.id), "claim_packet.zip")
        result.append(SweepAnalytics(
            sweep_id=str(s.id),
            state=s.state,
            country=s.country or "GB",
            currency=s.currency or "GBP",
            created_at=str(s.captured_at) if s.captured_at else None,
            total_books=int(s.total_books or 0),
            identified_books=int(s.identified or 0),
            low_confidence_books=int(s.low_conf or 0),
            unidentified_books=int(s.unidentified or 0),
            total_items=int(s.total_items or 0),
            avg_detection_confidence=round(float(s.avg_det_conf), 2) if s.avg_det_conf else None,
            avg_ocr_confidence=round(float(s.avg_ocr_conf), 2) if s.avg_ocr_conf else None,
            total_replacement_value=round(float(s.total_value), 2) if s.total_value else None,
            currency_symbol=CURRENCY_SYMBOL.get(s.currency or "GBP", "£"),
            packet_available=os.path.exists(packet_path),
            packet_url=f"/sweeps/{s.id}/packet" if os.path.exists(packet_path) else None,
        ))
    return result


@router.get("/{sweep_id}/analytics", response_model=SweepAnalytics)
async def get_sweep_analytics(sweep_id: str) -> SweepAnalytics:
    """Full analytics for one sweep including all book details."""
    import os
    async with get_db() as db:
        sr = await db.execute(text("""
            SELECT s.id, s.state, s.country, s.currency, s.captured_at AS captured_at,
                   AVG(b.detection_confidence) FILTER (WHERE b.detection_confidence IS NOT NULL) AS avg_det_conf,
                   AVG(b.id_confidence) FILTER (WHERE b.id_confidence IS NOT NULL AND b.status != 'unidentified') AS avg_ocr_conf,
                   SUM(b.replacement_cost_amount) FILTER (WHERE b.replacement_cost_amount IS NOT NULL) AS total_value,
                   COUNT(b.id) AS total_books,
                   COUNT(b.id) FILTER (WHERE b.status = 'identified') AS identified,
                   COUNT(b.id) FILTER (WHERE b.status = 'low_confidence') AS low_conf,
                   COUNT(b.id) FILTER (WHERE b.status = 'unidentified') AS unidentified,
                   (SELECT COUNT(*) FROM items i WHERE i.sweep_id = s.id) AS total_items
            FROM sweeps s LEFT JOIN books b ON b.sweep_id = s.id
            WHERE s.id = :id GROUP BY s.id
        """), {"id": sweep_id})
        s = sr.fetchone()
        if not s:
            raise HTTPException(status_code=404, detail="Sweep not found")

        br = await db.execute(text("""
            SELECT id, status, title, author, isbn, id_confidence, detection_confidence,
                   replacement_cost_amount, replacement_cost_source, detected_language, frame_ref
            FROM books WHERE sweep_id = :id ORDER BY replacement_cost_amount DESC NULLS LAST
        """), {"id": sweep_id})
        books = br.fetchall()

    CURRENCY_SYMBOL = {"GBP": "£", "USD": "$", "EUR": "€", "INR": "₹", "JPY": "¥"}
    packet_path = os.path.join(settings.frames_dir, sweep_id, "claim_packet.zip")
    book_list = [
        {
            "id": str(b.id),
            "status": b.status,
            "title": b.title,
            "author": b.author,
            "isbn": b.isbn,
            "id_confidence": round(float(b.id_confidence), 2) if b.id_confidence else None,
            "detection_confidence": round(float(b.detection_confidence), 2) if b.detection_confidence else None,
            "replacement_cost": round(float(b.replacement_cost_amount), 2) if b.replacement_cost_amount else None,
            "source": b.replacement_cost_source,
            "language": b.detected_language,
            "crop_url": f"/sweeps/{sweep_id}/crops/{b.id}",
        }
        for b in books
    ]
    return SweepAnalytics(
        sweep_id=str(s.id),
        state=s.state,
        country=s.country or "GB",
        currency=s.currency or "GBP",
        created_at=str(s.created_at) if s.created_at else None,
        total_books=int(s.total_books or 0),
        identified_books=int(s.identified or 0),
        low_confidence_books=int(s.low_conf or 0),
        unidentified_books=int(s.unidentified or 0),
        total_items=int(s.total_items or 0),
        avg_detection_confidence=round(float(s.avg_det_conf), 2) if s.avg_det_conf else None,
        avg_ocr_confidence=round(float(s.avg_ocr_conf), 2) if s.avg_ocr_conf else None,
        total_replacement_value=round(float(s.total_value), 2) if s.total_value else None,
        currency_symbol=CURRENCY_SYMBOL.get(s.currency or "GBP", "£"),
        packet_available=os.path.exists(packet_path),
        packet_url=f"/sweeps/{s.id}/packet" if os.path.exists(packet_path) else None,
        books=book_list,
    )


@router.post("", status_code=201, response_model=SweepResponse)
async def create_sweep(body: CreateSweepRequest) -> SweepResponse:
    sweep_id = str(uuid.uuid4())

    async with get_db() as db:
        await db.execute(
            text("""
            INSERT INTO sweeps (id, country, currency, state, sweep_profile)
            VALUES (:id, :country, :currency, 'initializing', :profile)
            """),
            {
                "id": sweep_id,
                "country": body.country.upper(),
                "currency": body.currency.upper(),
                "profile": settings.sweep_profile,
            },
        )

    # Notify agents runner so it starts the LangGraph for this sweep
    from app.api.webhooks import _redis
    import json as _json
    if _redis:
        await _redis.publish(
            f"sweep_created:{sweep_id}",
            _json.dumps({"country": body.country.upper(), "currency": body.currency.upper()}),
        )

    ws_url = f"ws://localhost:8000/ws/{sweep_id}"
    logger.info(f"Created sweep {sweep_id} ({body.country}/{body.currency})")

    return SweepResponse(
        sweep_id=sweep_id,
        ws_url=ws_url,
        state="initializing",
        country=body.country.upper(),
        currency=body.currency.upper(),
    )


@router.get("/{sweep_id}", response_model=SweepStateResponse)
async def get_sweep(sweep_id: str) -> SweepStateResponse:
    async with get_db() as db:
        row = await db.execute(
            text("SELECT id, state FROM sweeps WHERE id = :id"),
            {"id": sweep_id}
        )
        sweep = row.fetchone()
        if not sweep:
            raise HTTPException(status_code=404, detail="Sweep not found")

        bc = (await db.execute(
            text("""
            SELECT COUNT(*) as total,
                   COUNT(*) FILTER (WHERE status = 'identified') as identified
            FROM books WHERE sweep_id = :id
            """),
            {"id": sweep_id}
        )).fetchone()

        ic = (await db.execute(
            text("SELECT COUNT(*) as total FROM items WHERE sweep_id = :id"),
            {"id": sweep_id}
        )).fetchone()

        tr = (await db.execute(
            text("""
            SELECT COUNT(*) as total,
                   COUNT(*) FILTER (WHERE status = 'complete') as done
            FROM celery_tasks WHERE sweep_id = :id
            """),
            {"id": sweep_id}
        )).fetchone()

    progress = float(tr.done) / float(tr.total) if tr.total > 0 else None
    is_complete = sweep.state == "complete"

    return SweepStateResponse(
        sweep_id=sweep_id,
        state=sweep.state,
        book_count=bc.total or 0,
        books_identified=bc.identified or 0,
        items_count=ic.total or 0,
        processing_progress=progress,
        packet_ready=is_complete,
        packet_url=f"/sweeps/{sweep_id}/packet" if is_complete else None,
    )


@router.get("/{sweep_id}/livekit-token", response_model=LiveKitTokenResponse)
async def get_livekit_token(sweep_id: str) -> LiveKitTokenResponse:
    token = (
        AccessToken(
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
        )
        .with_identity(f"policyholder-{sweep_id[:8]}")
        .with_name("Policyholder")
        .with_grants(VideoGrants(
            room=sweep_id,
            room_join=True,
            can_publish=True,
            can_subscribe=True,
            can_publish_data=True,
        ))
        .to_jwt()
    )
    return LiveKitTokenResponse(token=token, url=settings.livekit_url)


@router.post("/{sweep_id}/end", status_code=200)
async def end_sweep(sweep_id: str) -> dict:
    from app.api.webhooks import _redis

    async with get_db() as db:
        row = await db.execute(
            text("SELECT state FROM sweeps WHERE id = :id"),
            {"id": sweep_id}
        )
        sweep = row.fetchone()
        if not sweep:
            raise HTTPException(status_code=404, detail="Sweep not found")
        if sweep.state not in ("initializing", "sweeping"):
            raise HTTPException(status_code=409, detail=f"Sweep in state '{sweep.state}' cannot be ended")

        await db.execute(
            text("UPDATE sweeps SET state = 'processing' WHERE id = :id"),
            {"id": sweep_id}
        )

    # Use RPUSH so message_pump BLPOP on sweep_end_queue receives it
    if _redis is not None:
        await _redis.rpush(f"sweep_end_queue:{sweep_id}", "end")

    return {"status": "processing"}


@router.get("/{sweep_id}/crops/{book_id}")
async def get_crop(sweep_id: str, book_id: str) -> StreamingResponse:
    """Serve a spine crop JPEG for a detected book."""
    import os

    crop_path = os.path.join(settings.frames_dir, sweep_id, "crops", f"{book_id}.jpg")
    if not os.path.exists(crop_path):
        raise HTTPException(status_code=404, detail="Crop not found")

    with open(crop_path, "rb") as f:
        data = f.read()

    return StreamingResponse(
        content=iter([data]),
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/{sweep_id}/packet")
async def download_packet(sweep_id: str) -> StreamingResponse:
    """Download claim packet ZIP from filesystem storage."""
    import os

    packet_path = os.path.join(settings.frames_dir, sweep_id, "claim_packet.zip")
    if not os.path.exists(packet_path):
        raise HTTPException(status_code=404, detail="Packet not ready or not found")

    with open(packet_path, "rb") as f:
        data = f.read()

    return StreamingResponse(
        content=iter([data]),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="claim_{sweep_id[:8]}.zip"',
            "Content-Length": str(len(data)),
        },
    )


@router.delete("/{sweep_id}", status_code=204)
async def cancel_sweep(sweep_id: str) -> Response:
    async with get_db() as db:
        result = await db.execute(
            text("""
            UPDATE sweeps SET state = 'failed', error_message = 'Cancelled by user'
            WHERE id = :id AND state IN ('initializing', 'sweeping', 'processing')
            """),
            {"id": sweep_id}
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Sweep not found or already in terminal state")

    return Response(status_code=204)
