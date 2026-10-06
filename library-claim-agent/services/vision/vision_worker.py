"""
Vision pipeline worker.

Consumes frames from Redis Streams, runs:
  1. Quality assessment  (blur / glare / darkness)
  2. YOLOv8 detection   (books + room items)
  3. BookTracker dedup  (same spine seen in 20+ frames → one record)
  4. Spine crop save    (filesystem, same root as frames)
  5. DB insert          (books/items with status='processing')
  6. Celery dispatch    (identify_book task per new book)
  7. Quality warnings   (push to quality_queue:{sweep_id} for idle_node)

One async task per active sweep; exits when sweep state is terminal.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid

import asyncpg
import cv2
import numpy as np
import redis.asyncio as aioredis

# Allow importing shared modules (config/, output/)
_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
for _p in [_root, os.path.join(_root, "services/vision")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("vision_worker")

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
DATABASE_URL = os.environ.get("DATABASE_URL", "").replace("+asyncpg", "")
FRAMES_DIR = os.environ.get("FRAMES_DIR", "/app/frame_data")
SWEEP_PROFILE = os.environ.get("SWEEP_PROFILE", "slow")


# ── Lazy-loaded model singletons ─────────────────────────────────────────────

_book_detector = None
_item_detector = None
_quality_assessors: dict[str, object] = {}


def _get_detectors():
    global _book_detector, _item_detector
    if _book_detector is None:
        from detector import BookDetector, ItemDetector
        logger.info("Loading YOLO models...")
        _book_detector = BookDetector()
        _item_detector = ItemDetector()
        logger.info("YOLO models ready")
    return _book_detector, _item_detector


def _get_assessor(sweep_id: str):
    if sweep_id not in _quality_assessors:
        from quality import FrameQualityAssessor
        _quality_assessors[sweep_id] = FrameQualityAssessor()
    return _quality_assessors[sweep_id]


# ── Database helpers ──────────────────────────────────────────────────────────

async def _insert_book(conn, sweep_id: str, book_id: str, frame_ref: str, detection_confidence: float = 0.0) -> None:
    await conn.execute(
        """
        INSERT INTO books (id, sweep_id, frame_ref, status, detection_confidence)
        VALUES ($1, $2, $3, 'processing', $4)
        ON CONFLICT (id) DO NOTHING
        """,
        book_id, sweep_id, frame_ref, detection_confidence,
    )


async def _insert_item(conn, sweep_id: str, item_id: str,
                       category: str, frame_ref: str, confidence: float) -> None:
    await conn.execute(
        """
        INSERT INTO items (id, sweep_id, category, frame_ref, status, confidence)
        VALUES ($1, $2, $3, $4, 'processing', $5)
        ON CONFLICT (id) DO NOTHING
        """,
        item_id, sweep_id, category, frame_ref, confidence,
    )


async def _update_sweep_counts(conn, sweep_id: str,
                               book_count: int, item_count: int) -> None:
    await conn.execute(
        """
        UPDATE sweeps
        SET cost_usd = $1
        WHERE id = $2
        """,
        float(book_count + item_count) * 0.0,
        sweep_id,
    )


async def _sweep_is_active(conn, sweep_id: str) -> bool:
    row = await conn.fetchrow(
        "SELECT state FROM sweeps WHERE id = $1", sweep_id
    )
    if not row:
        return False
    return row["state"] in ("initializing", "sweeping")


# ── Celery dispatch ───────────────────────────────────────────────────────────

def _dispatch_identify(sweep_id: str, book_id: str,
                       frame_id: str, crop_s3_key: str) -> None:
    from celery import Celery as _Celery
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    app = _Celery(broker=redis_url, backend=redis_url.replace("/0", "/1"))
    app.send_task(
        "workers.book_id.identify_book",
        kwargs={
            "sweep_id": sweep_id,
            "book_id": book_id,
            "frame_id": frame_id,
            "crop_s3_key": crop_s3_key,
        },
        queue="book_id",
    )


# ── Frame processor ───────────────────────────────────────────────────────────

async def process_frame(
    sweep_id: str,
    frame_data: dict,
    tracker,
    conn,
    redis_client,
) -> tuple[int, int]:
    """
    Process one frame. Returns (new_books, new_items) counts.
    """
    from quality import FrameQualityAssessor

    frame_id = frame_data.get("frame_id", "unknown")
    local_path = frame_data.get("local_path", "")
    s3_key = frame_data.get("s3_key", "")

    if not local_path or not os.path.exists(local_path):
        return 0, 0

    # Load frame
    frame = cv2.imread(local_path)
    if frame is None:
        return 0, 0

    h, w = frame.shape[:2]

    # 1. Quality check
    assessor = _get_assessor(sweep_id)
    quality = assessor.assess(frame)

    if quality.feedback:
        await redis_client.rpush(
            f"quality_queue:{sweep_id}", quality.feedback
        )

    # Skip heavily blurred frames entirely (save CPU)
    if quality.is_blurry and quality.blur_score < 30:
        return 0, 0

    # 2. Detection
    book_det, item_det = _get_detectors()
    spines = book_det.detect(frame)
    items = item_det.detect(frame)

    new_books = 0
    new_items = 0

    # 3. Book tracking + crop save + DB + Celery
    for spine in spines:
        crop_quality = quality.blur_score * spine.bbox_height
        book_id = tracker.update(
            spine,
            frame_id=frame_id,
            frame_width=w,
            frame_height=h,
            blur_score=quality.blur_score,
            crop_s3_key=None,
        )
        if book_id is None:
            continue  # Duplicate

        # Extract and save spine crop
        x1, y1 = max(0, int(spine.x1)), max(0, int(spine.y1))
        x2, y2 = min(w, int(spine.x2)), min(h, int(spine.y2))
        crop = frame[y1:y2, x1:x2]

        crop_dir = os.path.join(FRAMES_DIR, sweep_id, "crops")
        os.makedirs(crop_dir, exist_ok=True)
        crop_path = os.path.join(crop_dir, f"{book_id}.jpg")
        cv2.imwrite(crop_path, crop)

        crop_s3_key = f"{sweep_id}/crops/{book_id}.jpg"
        frame_ref = s3_key

        await _insert_book(conn, sweep_id, book_id, frame_ref, spine.confidence)
        new_books += 1

        # Dispatch OCR + identification (non-blocking, best-effort)
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, _dispatch_identify, sweep_id, book_id, frame_id, crop_s3_key
            )
        except Exception as e:
            logger.warning(f"Failed to dispatch identify task for {book_id}: {e}")

    # 4. Room items
    new_item_payloads = []
    for item in items:
        item_id = str(uuid.uuid4())
        frame_ref = s3_key
        await _insert_item(conn, sweep_id, item_id,
                           item.category, frame_ref, item.confidence)
        new_items += 1
        new_item_payloads.append({
            "id": item_id,
            "category": item.category,
            "status": "processing",
            "confidence": item.confidence,
        })

    # 5. Push inventory_update to WebSocket via ws_broadcast channel
    if new_books > 0 or new_items > 0:
        # Fetch all current books for this sweep to send fresh list
        rows = await conn.fetch(
            """SELECT id, status, title, author, isbn, id_confidence, detection_confidence,
                      replacement_cost_amount, replacement_cost_source,
                      used_value_amount, used_value_source
               FROM books WHERE sweep_id = $1""",
            sweep_id,
        )
        book_payloads = [
            {
                "id": str(r["id"]),
                "status": r["status"],
                "crop_url": f"/sweeps/{sweep_id}/crops/{r['id']}",
                "title": r["title"],
                "author": r["author"],
                "isbn": r["isbn"],
                "id_confidence": float(r["id_confidence"]) if r["id_confidence"] else None,
                "detection_confidence": float(r["detection_confidence"]) if r["detection_confidence"] else None,
                "replacement_cost": {"amount": float(r["replacement_cost_amount"]), "source": r["replacement_cost_source"]} if r["replacement_cost_amount"] else None,
                "used_value": {"amount": float(r["used_value_amount"]), "source": r["used_value_source"]} if r["used_value_amount"] else None,
            }
            for r in rows
        ]
        await redis_client.publish(
            f"ws_broadcast:{sweep_id}",
            json.dumps({
                "type": "inventory_update",
                "books": book_payloads,
                "items": new_item_payloads,
            }),
        )

    return new_books, new_items


# ── Sweep processor ───────────────────────────────────────────────────────────

async def run_sweep_vision(sweep_id: str) -> None:
    """
    Consume frames for one sweep until it leaves the active state.
    """
    from book_tracker import BookTracker

    logger.info(f"Vision started for sweep {sweep_id}")
    tracker = BookTracker()

    r = await aioredis.from_url(REDIS_URL, decode_responses=True)
    db = await asyncpg.connect(DATABASE_URL)

    stream_key = f"frames:{sweep_id}"
    last_id = "0"
    total_books = 0
    total_items = 0
    idle_rounds = 0

    try:
        while True:
            # Exit if sweep is no longer active
            if idle_rounds % 20 == 0:
                if not await _sweep_is_active(db, sweep_id):
                    logger.info(
                        f"Sweep {sweep_id} ended — "
                        f"{total_books} books, {total_items} items detected"
                    )
                    break

            # Read up to 5 frames, block up to 500ms
            try:
                entries = await r.xread(
                    {stream_key: last_id}, count=5, block=500
                )
            except Exception as e:
                logger.warning(f"xread error [{sweep_id}]: {e}")
                await asyncio.sleep(1)
                continue

            if not entries:
                idle_rounds += 1
                continue

            idle_rounds = 0
            for _, records in entries:
                for entry_id, data in records:
                    last_id = entry_id
                    try:
                        nb, ni = await process_frame(
                            sweep_id, data, tracker, db, r
                        )
                        total_books += nb
                        total_items += ni
                        if nb or ni:
                            logger.info(
                                f"[{sweep_id[:8]}] frame {entry_id}: "
                                f"+{nb} books +{ni} items "
                                f"(total: {total_books}B {total_items}I)"
                            )
                    except Exception as e:
                        logger.error(
                            f"Frame processing error [{sweep_id}/{entry_id}]: {e}",
                            exc_info=True,
                        )
    finally:
        await db.close()
        await r.aclose()
        _quality_assessors.pop(sweep_id, None)


# ── Main loop ─────────────────────────────────────────────────────────────────

async def main() -> None:
    logger.info("Vision worker started — waiting for sweep events")

    r = await aioredis.from_url(REDIS_URL, decode_responses=True)
    pubsub = r.pubsub()
    await pubsub.psubscribe("sweep_created:*")

    active: dict[str, asyncio.Task] = {}

    async for message in pubsub.listen():
        if message["type"] != "pmessage":
            continue
        channel = message.get("channel", "")
        if not channel.startswith("sweep_created:"):
            continue

        sweep_id = channel.split(":", 1)[1]
        if sweep_id in active and not active[sweep_id].done():
            continue

        task = asyncio.create_task(run_sweep_vision(sweep_id))
        active[sweep_id] = task


if __name__ == "__main__":
    asyncio.run(main())
