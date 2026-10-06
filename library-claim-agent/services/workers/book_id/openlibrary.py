"""
Open Library API search.
Free, no API key required, 20M+ book records.
Rate limit: ~100 requests/minute for polite use.
"""
from __future__ import annotations

import logging
from typing import List

import httpx

from book_id.confidence import BookMetadata

logger = logging.getLogger(__name__)

OPEN_LIBRARY_BASE = "https://openlibrary.org"
REQUEST_TIMEOUT = 10.0
MAX_RESULTS = 5


async def search_open_library(query: str) -> List[BookMetadata]:
    """
    Search Open Library by title/author text.
    Returns up to MAX_RESULTS candidates.
    Returns [] on any network error (caller falls back to Google Books).
    """
    # Limit query to 8 words to avoid over-specification from OCR noise
    clean_query = " ".join(query.split()[:8])
    if not clean_query.strip():
        return []

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(
                f"{OPEN_LIBRARY_BASE}/search.json",
                params={
                    "q": clean_query,
                    "limit": MAX_RESULTS,
                    "fields": "key,title,author_name,isbn,edition_key,first_publish_year",
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        logger.warning(f"Open Library search failed for '{clean_query[:40]}': {e}")
        return []
    except Exception as e:
        logger.error(f"Open Library unexpected error: {e}")
        return []

    results: List[BookMetadata] = []
    for doc in data.get("docs", [])[:MAX_RESULTS]:
        isbn_list = doc.get("isbn") or []
        # Prefer ISBN-13 (13 digits)
        isbn = next((i for i in isbn_list if len(i) == 13), None) or (isbn_list[0] if isbn_list else None)

        results.append(
            BookMetadata(
                title=doc.get("title", ""),
                author=(doc.get("author_name") or [None])[0],
                isbn=isbn,
                edition=None,
                first_publish_year=doc.get("first_publish_year"),
            )
        )

    return results
