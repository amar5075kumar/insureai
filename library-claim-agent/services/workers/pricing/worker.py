"""
Book pricing Celery worker.
Dispatched immediately when a book is identified (ISBN known).
Writes results directly to DB — never via LLM.
"""
from __future__ import annotations

import asyncio
import logging

from celery_app import app
from db import update_book_pricing
from pricing.aggregator import aggregate_prices

logger = logging.getLogger(__name__)


@app.task(
    bind=True,
    name="workers.pricing.price_book",
    queue="pricing",
    max_retries=2,
    default_retry_delay=15,
    time_limit=60,  # Hard kill after 60s (scraper may hang)
    soft_time_limit=50,
    acks_late=True,
)
def price_book_task(
    self,
    sweep_id: str,
    book_id: str,
    isbn: str,
    title: str,
    country: str,
    currency: str,
) -> dict:
    """
    Price a single book.
    Returns result dict (also written to DB as side effect).

    On final failure: writes null pricing (excluded_from_totals=True).
    """
    try:
        logger.info(f"Pricing {book_id} (ISBN={isbn}, {country}/{currency})")

        pricing = asyncio.run(
            aggregate_prices(isbn, title, country, currency)
        )
        update_book_pricing(book_id, sweep_id, pricing)

        result = {
            "replacement_cost": pricing.replacement_cost_amount,
            "used_value": pricing.used_value_amount,
            "source": pricing.replacement_cost_source,
        }
        logger.info(
            f"Priced {book_id}: replacement={pricing.replacement_cost_amount}, "
            f"used={pricing.used_value_amount}"
        )
        return result

    except Exception as exc:
        logger.error(f"Pricing failed for {book_id}: {exc}")
        if self.request.retries >= self.max_retries:
            # Final failure: exclude from totals
            update_book_pricing(book_id, sweep_id, None)
            return {"error": str(exc), "excluded": True}
        raise self.retry(exc=exc)
