"""
Book identification Celery worker.

Pipeline:
  1. Load spine crop from MinIO
  2. Run OCR (with optional SR upscale)
  3. Search Open Library (+ Google Books fallback)
  4. Score matches against OCR text
  5. Write result to DB
  6. IMMEDIATELY dispatch pricing task if ISBN found

The immediate pricing dispatch is critical for meeting the 5-minute
time-to-packet target.
"""
from __future__ import annotations

import asyncio
import logging

from celery_app import app
from book_id.confidence import final_status, score_matches
from book_id.ocr_processor import run_ocr_on_crop
from book_id.openlibrary import search_open_library
from db import get_sweep_country_currency, update_book_identification
from minio import load_crop_from_minio

logger = logging.getLogger(__name__)


@app.task(
    bind=True,
    name="workers.book_id.identify_book",
    queue="book_id",
    max_retries=3,
    default_retry_delay=10,
    acks_late=True,
)
def identify_book_task(
    self,
    sweep_id: str,
    book_id: str,
    frame_id: str,
    crop_s3_key: str,
    ocr_hint: str | None = None,
) -> dict:
    """
    Identify a single book.
    Returns result dict (also written to DB as side effect).
    """
    try:
        logger.info(f"Identifying {book_id} (sweep={sweep_id[:8]})")

        # 1. Load spine crop
        crop = load_crop_from_minio(crop_s3_key)
        if crop is None:
            logger.warning(f"Crop not found: {crop_s3_key}")
            update_book_identification(book_id, sweep_id, {
                "status": "unidentified",
                "ocr_raw_text": "",
                "id_confidence": 0.0,
            })
            return {"status": "unidentified", "reason": "crop_not_found"}

        # 2. OCR
        if ocr_hint:
            ocr_text, ocr_conf = ocr_hint, 0.80
        else:
            ocr_text, ocr_conf = run_ocr_on_crop(crop)

        logger.info(
            f"OCR [{book_id}]: '{ocr_text[:60]}' (conf={ocr_conf:.2f})"
        )

        # Low OCR confidence → unidentified immediately (don't waste API calls)
        if ocr_conf < 0.30 or not ocr_text.strip():
            update_book_identification(book_id, sweep_id, {
                "status": "unidentified",
                "ocr_raw_text": ocr_text,
                "id_confidence": ocr_conf,
            })
            return {"status": "unidentified", "reason": "low_ocr"}

        # 3. Metadata search
        candidates = asyncio.run(search_open_library(ocr_text))

        # 4. Score
        best_match, match_score = score_matches(ocr_text, candidates)
        status = final_status(match_score, ocr_conf)

        data: dict = {
            "status": status,
            "ocr_raw_text": ocr_text,
            "id_confidence": round(match_score * ocr_conf, 3) if best_match else ocr_conf,
        }

        if best_match and status == "identified":
            data.update({
                "title": best_match.title,
                "author": best_match.author,
                "isbn": best_match.isbn,
                "edition": best_match.edition,
            })

        # 5. Write to DB
        update_book_identification(book_id, sweep_id, data)

        # 6. IMMEDIATELY dispatch pricing (do not wait for all books)
        if best_match and best_match.isbn and status == "identified":
            country, currency = get_sweep_country_currency(sweep_id)
            from pricing.worker import price_book_task
            price_book_task.delay(
                sweep_id=sweep_id,
                book_id=book_id,
                isbn=best_match.isbn,
                title=best_match.title or "",
                country=country,
                currency=currency,
            )
            logger.info(f"Pricing dispatched for {book_id} (ISBN={best_match.isbn})")

        return data

    except Exception as exc:
        logger.error(f"Book ID failed [{book_id}]: {exc}", exc_info=True)
        raise self.retry(exc=exc)
