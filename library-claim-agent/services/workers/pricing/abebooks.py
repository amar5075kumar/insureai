"""
AbeBooks price scraper.

AbeBooks is the primary pricing source.
Amazon scraping is NOT implemented — Amazon blocks new IPs within ~10 requests.
AbeBooks is more scraper-friendly with reasonable delays.

Strategy:
  - Random 1–2.5s delay between requests
  - Rotate user-agent
  - Use ISBN search (most reliable)
  - Return top 5 listings (new + used mix)
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List

logger = logging.getLogger(__name__)

# Map ISO 3166-1 → AbeBooks domain
DOMAIN_MAP = {
    "GB": "abebooks.co.uk",
    "US": "abebooks.com",
    "AU": "abebooks.com.au",
    "CA": "abebooks.com",
    "FR": "abebooks.fr",
    "DE": "abebooks.de",
    "ES": "abebooks.es",
    "IT": "abebooks.it",
}

DOMAIN_CURRENCY = {
    "abebooks.co.uk": "GBP",
    "abebooks.com": "USD",
    "abebooks.com.au": "AUD",
    "abebooks.fr": "EUR",
    "abebooks.de": "EUR",
    "abebooks.es": "EUR",
    "abebooks.it": "EUR",
}

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
]


@dataclass
class AbeBooksPriceResult:
    amount: float
    currency: str
    condition: str
    source: str = "AbeBooks"
    url: str = ""
    retrieved_at: str = ""


async def scrape_abebooks(
    isbn: str,
    country: str,
    max_results: int = 5,
) -> List[AbeBooksPriceResult]:
    """
    Scrape AbeBooks for book prices.
    Returns up to max_results price listings.
    Returns [] on any scraping failure.
    """
    from playwright.async_api import async_playwright

    domain = DOMAIN_MAP.get(country.upper(), "abebooks.com")
    search_url = f"https://www.{domain}/servlet/SearchResults?isbn={isbn}&cm_sp=mbc-_-ISBN-_-all"
    retrieved_at = datetime.now(timezone.utc).isoformat()

    results: List[AbeBooksPriceResult] = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                locale="en-GB" if country == "GB" else "en-US",
            )
            page = await context.new_page()

            # Rate limit
            await asyncio.sleep(random.uniform(1.0, 2.5))

            await page.goto(
                search_url,
                wait_until="domcontentloaded",
                timeout=25_000,
            )
            await page.wait_for_timeout(1500)  # Allow JS rendering

            listings = await page.query_selector_all('[data-cy="listing-item"]')
            currency = DOMAIN_CURRENCY.get(domain, "USD")

            for listing in listings[:max_results]:
                try:
                    price_el = await listing.query_selector('[itemprop="price"]')
                    cond_el = await listing.query_selector('[data-cy="listing-condition"]')
                    link_el = await listing.query_selector('a[href*="/book-details/"]')

                    if not price_el or not link_el:
                        continue

                    price_text = await price_el.inner_text()
                    # Extract numeric price (handles "£12.99", "$12.99", "12,99 €")
                    price_match = re.search(r"[\d,]+\.?\d*", price_text.replace(",", "."))
                    if not price_match:
                        continue
                    price = float(price_match.group().replace(",", "."))

                    condition = await cond_el.inner_text() if cond_el else "Unknown"
                    href = await link_el.get_attribute("href") or ""
                    full_url = f"https://www.{domain}{href}" if href.startswith("/") else href

                    results.append(
                        AbeBooksPriceResult(
                            amount=price,
                            currency=currency,
                            condition=condition.strip(),
                            url=full_url,
                            retrieved_at=retrieved_at,
                        )
                    )
                except Exception:
                    continue

            await browser.close()

    except Exception as e:
        logger.warning(f"AbeBooks scrape failed for ISBN {isbn}: {e}")

    logger.info(f"AbeBooks: {len(results)} results for ISBN {isbn} on {domain}")
    return results
