"""
Price aggregation across multiple sources.
Selects the best replacement cost (lowest new) and used value (median good).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from pricing.abebooks import AbeBooksPriceResult, scrape_abebooks
from pricing.currency import convert

logger = logging.getLogger(__name__)


@dataclass
class BookPricingResult:
    replacement_cost_amount: Optional[float]
    replacement_cost_source: Optional[str]
    replacement_cost_url: Optional[str]
    replacement_cost_retrieved_at: Optional[str]
    replacement_cost_converted: bool
    used_value_amount: Optional[float]
    used_value_source: Optional[str]
    used_value_url: Optional[str]
    used_value_retrieved_at: Optional[str]
    used_value_condition: Optional[str]


_NO_PRICE = BookPricingResult(
    replacement_cost_amount=None,
    replacement_cost_source=None,
    replacement_cost_url=None,
    replacement_cost_retrieved_at=None,
    replacement_cost_converted=False,
    used_value_amount=None,
    used_value_source=None,
    used_value_url=None,
    used_value_retrieved_at=None,
    used_value_condition=None,
)


async def aggregate_prices(
    isbn: str,
    title: str,
    country: str,
    currency: str,
) -> BookPricingResult:
    """
    Aggregate prices from available scrapers.
    Currently: AbeBooks only (Amazon blocked; ThriftBooks for US/GB).
    """
    async def _no_prices():
        return []

    tasks = [
        scrape_abebooks(isbn, country),
        _scrape_thriftbooks(isbn) if country in ("US", "GB") else _no_prices(),
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_prices: List[AbeBooksPriceResult] = []
    for r in results:
        if isinstance(r, list):
            all_prices.extend(r)
        elif isinstance(r, Exception):
            logger.debug(f"Scraper returned exception: {r}")

    if not all_prices:
        logger.info(f"No prices found for ISBN {isbn}")
        return _NO_PRICE

    # ── Replacement cost (lowest price across all listings) ──────────
    # We use "lowest overall" as proxy for "new" since AbeBooks mix is
    # new + used. This is documented in the packet as "AbeBooks lowest".
    replacement = min(all_prices, key=lambda p: p.amount)

    # Convert if needed
    rep_amount = replacement.amount
    rep_converted = False
    if replacement.currency != currency:
        rep_amount, rep_converted = await convert(
            replacement.amount, replacement.currency, currency
        )

    # ── Used value (median price, good/very good condition) ──────────
    used_prices = [
        p for p in all_prices
        if any(w in p.condition.lower() for w in ("good", "very good", "used"))
    ]
    if not used_prices:
        used_prices = all_prices  # Fall back to all prices

    sorted_used = sorted(used_prices, key=lambda p: p.amount)
    used = sorted_used[len(sorted_used) // 2]  # Median

    used_amount = used.amount
    if used.currency != currency:
        used_amount, _ = await convert(used.amount, used.currency, currency)

    return BookPricingResult(
        replacement_cost_amount=round(rep_amount, 2),
        replacement_cost_source=replacement.source,
        replacement_cost_url=replacement.url,
        replacement_cost_retrieved_at=replacement.retrieved_at,
        replacement_cost_converted=rep_converted,
        used_value_amount=round(used_amount, 2),
        used_value_source=used.source,
        used_value_url=used.url,
        used_value_retrieved_at=used.retrieved_at,
        used_value_condition=used.condition,
    )


async def _scrape_thriftbooks(isbn: str) -> List[AbeBooksPriceResult]:
    """
    ThriftBooks scraper (US/UK used books).
    Returns [] — placeholder for future implementation.
    ThriftBooks is more lenient than Amazon but requires separate Playwright flow.
    """
    # TODO: Implement ThriftBooks scraper
    return []
