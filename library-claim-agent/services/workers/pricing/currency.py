"""
Currency conversion.
Uses frankfurter.app (free, ECB-sourced, no API key, reliable).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from functools import lru_cache

import httpx

logger = logging.getLogger(__name__)

FRANKFURTER_BASE = "https://api.frankfurter.app"
FALLBACK_RATES = {
    "USD": 1.0, "GBP": 0.79, "EUR": 0.92, "AUD": 1.53,
    "CAD": 1.36, "JPY": 148.5, "CHF": 0.88, "CNY": 7.24,
}


async def get_rates() -> dict[str, float]:
    """Fetch current rates from frankfurter.app (USD base)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{FRANKFURTER_BASE}/latest?base=USD")
            resp.raise_for_status()
            return resp.json()["rates"]
    except Exception as e:
        logger.warning(f"Currency fetch failed ({e}) — using fallback rates")
        return FALLBACK_RATES


async def convert(
    amount: float,
    from_currency: str,
    to_currency: str,
) -> tuple[float, bool]:
    """
    Convert amount from one currency to another.
    Returns (converted_amount, converted_flag).
    If currencies are the same, returns (amount, False).
    """
    if from_currency.upper() == to_currency.upper():
        return amount, False

    rates = await get_rates()
    # Both rates relative to USD
    from_usd = rates.get(from_currency.upper(), 1.0)
    to_usd = rates.get(to_currency.upper(), 1.0)

    # amount / from_usd = amount in USD; * to_usd = amount in target
    converted = (amount / from_usd) * to_usd
    return round(converted, 2), True
