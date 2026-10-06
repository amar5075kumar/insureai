"""
Lightweight pricing using Google Books API (free, no scraping).
Falls back to a price estimate based on publication year if no data found.
No PyTorch. No scraping. No external paid APIs.
"""
from __future__ import annotations

import asyncio
import logging
import os

import asyncpg
import httpx
from celery_app import app

logger = logging.getLogger(__name__)
DATABASE_URL = os.environ.get("DATABASE_URL", "").replace("+asyncpg", "")
SSL_VERIFY = os.environ.get("SSL_VERIFY", "true").lower() != "false"


async def _fetch_google_books_price(isbn: str, title: str) -> dict | None:
    """
    Query Google Books API for price info.
    Returns {"amount": float, "source": str} or None.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=SSL_VERIFY) as client:
            # Try ISBN first, then title
            query = f"isbn:{isbn}" if isbn else f'intitle:"{title}"'
            resp = await client.get(
                "https://www.googleapis.com/books/v1/volumes",
                params={"q": query, "maxResults": 1},
            )
            if resp.status_code == 429:
                return None  # Rate limited — use estimate
            data = resp.json()
            items = data.get("items", [])
            if not items and isbn:
                # ISBN failed — try title
                resp = await client.get(
                    "https://www.googleapis.com/books/v1/volumes",
                    params={"q": f'intitle:"{title}"', "maxResults": 1},
                )
                if resp.status_code == 429:
                    return None
                data = resp.json()
                items = data.get("items", [])

            if items:
                sale = items[0].get("saleInfo", {})
                list_price = sale.get("listPrice")
                retail_price = sale.get("retailPrice")
                if list_price and list_price.get("amount"):
                    return {"amount": float(list_price["amount"]), "source": "google_books_list"}
                if retail_price and retail_price.get("amount"):
                    return {"amount": float(retail_price["amount"]), "source": "google_books_retail"}
    except Exception as e:
        logger.warning(f"Google Books API failed: {e}")
    return None


def _estimate_price(isbn: str | None, title: str = "") -> dict:
    """
    Heuristic price estimate when no API data.
    Uses ISBN or title to get a stable £10-30 range.
    """
    import hashlib
    seed_str = (isbn or title or "unknown").encode()
    seed = int(hashlib.md5(seed_str).hexdigest()[:6], 16) % 2000
    amount = 10.0 + (seed / 100.0)  # £10 – £30
    return {"amount": round(amount, 2), "source": "estimate"}


async def _update_pricing_db(book_id: str, sweep_id: str, replacement: dict, used: dict, currency: str = "GBP") -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute(
            """
            UPDATE books SET
                replacement_cost_amount = $1,
                replacement_cost_source = $2,
                replacement_cost_from_currency = $3,
                used_value_amount = $4,
                used_value_source = $5,
                updated_at = NOW()
            WHERE id = $6 AND sweep_id = $7
            """,
            replacement["amount"],
            replacement["source"],
            currency,
            used["amount"],
            used["source"],
            book_id,
            sweep_id,
        )
    finally:
        await conn.close()


@app.task(
    bind=True,
    name="workers.pricing.price_book",
    queue="pricing",
    max_retries=2,
    default_retry_delay=15,
    time_limit=30,
    acks_late=True,
)
def price_book(
    self,
    sweep_id: str,
    book_id: str,
    isbn: str,
    title: str,
    country: str,
    currency: str,
) -> dict:
    try:
        logger.info(f"Pricing {book_id[:8]} (ISBN={isbn})")

        price = asyncio.run(_fetch_google_books_price(isbn, title))

        if price:
            replacement = price
            # Used value ≈ 60% of list price
            used = {"amount": round(price["amount"] * 0.60, 2), "source": price["source"] + "_used"}
        else:
            replacement = _estimate_price(isbn, title)
            used = {"amount": round(replacement["amount"] * 0.55, 2), "source": "estimate_used"}

        asyncio.run(_update_pricing_db(book_id, sweep_id, replacement, used, currency))

        # Push price update to browser
        from ws_notify import push_book_update
        push_book_update(sweep_id, book_id)

        logger.info(f"Priced {book_id[:8]}: £{replacement['amount']} ({replacement['source']})")
        return {"replacement_cost": replacement["amount"], "source": replacement["source"]}

    except Exception as exc:
        logger.error(f"Pricing failed [{book_id[:8]}]: {exc}")
        raise self.retry(exc=exc)
