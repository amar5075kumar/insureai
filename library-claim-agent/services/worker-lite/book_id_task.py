"""
Lightweight book identification using Claude Haiku vision.
Replaces PaddleOCR + PyTorch with a simple API call.
No GPU required. Image size: ~250 MB vs 3.46 GB.

Pipeline:
  1. Load spine crop from filesystem
  2. Send to Claude Haiku vision → extract title + author
  3. Search Open Library for ISBN
  4. Write to DB
  5. Dispatch pricing task
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os

import asyncpg
import httpx
from celery_app import app

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "").replace("+asyncpg", "")
FRAMES_DIR = os.environ.get("FRAMES_DIR", "/app/frame_data")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
# Corporate proxies do SSL inspection — set SSL_VERIFY=false to bypass for dev
SSL_VERIFY = os.environ.get("SSL_VERIFY", "true").lower() != "false"


def _load_crop(crop_s3_key: str) -> bytes | None:
    """Load crop from local filesystem. crop_s3_key = sweep_id/crops/book_id.jpg"""
    local_path = os.path.join(FRAMES_DIR, crop_s3_key)
    if os.path.exists(local_path):
        with open(local_path, "rb") as f:
            return f.read()
    return None


def _identify_with_claude(image_bytes: bytes) -> dict:
    """
    Send spine crop to Claude Haiku vision.
    Uses Enterprise Gateway (bearer token) if BEDROCK_BASE_URL is set,
    otherwise falls back to direct Anthropic API.
    Returns {"title": "...", "author": "..."} or {"title": None, "author": None}.
    """
    import httpx2 as _httpx

    BEDROCK_BASE_URL = os.environ.get("BEDROCK_BASE_URL", "")
    BEDROCK_MODEL = os.environ.get("BEDROCK_MODEL", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
    BEDROCK_AUTH_TYPE = os.environ.get("BEDROCK_AUTH_TYPE", "aws")

    b64 = base64.standard_b64encode(image_bytes).decode()
    prompt_text = (
        "This is a book spine image. The text may be in any language including "
        "English, Hindi (Devanagari), Bengali, Gujarati, Tamil, or other scripts. "
        "Extract the title and author name exactly as written (preserve the original script). "
        "Also detect the language. "
        'Reply ONLY with valid JSON: {"title": "...", "author": "...", "language": "en|hi|bn|gu|ta|other"}. '
        'If the text is completely unreadable, reply: {"title": null, "author": null, "language": null}.'
    )

    # Try Enterprise Gateway (Bedrock) first if configured
    if BEDROCK_BASE_URL and BEDROCK_AUTH_TYPE == "bearer":
        invoke_url = f"{BEDROCK_BASE_URL.rstrip('/')}/model/{BEDROCK_MODEL}/invoke"
        payload = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 150,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                    {"type": "text", "text": prompt_text},
                ],
            }],
        }
        try:
            with _httpx.Client(verify=SSL_VERIFY, timeout=30.0) as client:
                resp = client.post(
                    invoke_url,
                    headers={"Authorization": f"Bearer {ANTHROPIC_API_KEY}", "Content-Type": "application/json"},
                    content=json.dumps(payload),
                )
                resp.raise_for_status()
            data = resp.json()
            text = data["content"][0]["text"].strip()
            if text.startswith("```"):
                text = text.split("```")[1].lstrip("json").strip()
            return json.loads(text)
        except Exception as e:
            logger.warning(f"Enterprise Gateway vision failed: {e}")
            return {"title": None, "author": None, "language": None}

    # Fallback: direct Anthropic API
    try:
        import anthropic
        client = anthropic.Anthropic(
            api_key=ANTHROPIC_API_KEY,
            http_client=_httpx.Client(verify=SSL_VERIFY),
        )
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                    {"type": "text", "text": prompt_text},
                ],
            }],
        )
        text = msg.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1].lstrip("json").strip()
        return json.loads(text)
    except Exception as e:
        logger.warning(f"Claude vision failed: {e}")
        return {"title": None, "author": None}


async def _search_open_library(title: str, author: str) -> dict | None:
    """Search Open Library for book metadata. Returns best match or None."""
    query = f"{title} {author}".strip()
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=SSL_VERIFY) as client:
            resp = await client.get(
                "https://openlibrary.org/search.json",
                params={"q": query, "limit": 3, "fields": "title,author_name,isbn,first_publish_year"},
            )
            data = resp.json()
            docs = data.get("docs", [])
            if not docs:
                return None
            doc = docs[0]
            isbns = doc.get("isbn", [])
            authors = doc.get("author_name", [])
            return {
                "title": doc.get("title", title),
                "author": authors[0] if authors else author,
                "isbn": isbns[0] if isbns else None,
                "year": doc.get("first_publish_year"),
            }
    except Exception as e:
        logger.warning(f"Open Library search failed: {e}")
        return None


async def _update_book_db(book_id: str, sweep_id: str, data: dict) -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute(
            """
            UPDATE books SET
                status = $1,
                title = $2,
                author = $3,
                isbn = $4,
                id_confidence = $5,
                detected_language = $6,
                updated_at = NOW()
            WHERE id = $7 AND sweep_id = $8
            """,
            data.get("status", "unidentified"),
            data.get("title"),
            data.get("author"),
            data.get("isbn"),
            data.get("id_confidence", 0.0),
            data.get("language"),
            book_id,
            sweep_id,
        )
    finally:
        await conn.close()


@app.task(
    bind=True,
    name="workers.book_id.identify_book",
    queue="book_id",
    max_retries=2,
    default_retry_delay=10,
    acks_late=True,
)
def identify_book(
    self,
    sweep_id: str,
    book_id: str,
    frame_id: str,
    crop_s3_key: str,
    ocr_hint: str | None = None,
) -> dict:
    try:
        logger.info(f"Identifying {book_id[:8]} (sweep={sweep_id[:8]})")

        # 1. Load crop
        image_bytes = _load_crop(crop_s3_key)
        if not image_bytes:
            logger.warning(f"Crop not found: {crop_s3_key}")
            asyncio.run(_update_book_db(book_id, sweep_id, {"status": "unidentified", "id_confidence": 0.0}))
            return {"status": "unidentified", "reason": "crop_not_found"}

        # 2. Claude Haiku vision
        vision_result = _identify_with_claude(image_bytes)
        title = vision_result.get("title")
        author = vision_result.get("author")
        detected_lang = vision_result.get("language")

        if not title:
            asyncio.run(_update_book_db(book_id, sweep_id, {"status": "unidentified", "id_confidence": 0.0, "language": detected_lang}))
            return {"status": "unidentified", "reason": "unreadable"}

        logger.info(f"Vision [{book_id[:8]}]: '{title}' by '{author}'")

        # 3. Open Library lookup for ISBN
        match = asyncio.run(_search_open_library(title, author or ""))
        if match and match.get("isbn"):
            final_title = match["title"]
            final_author = match["author"]
            isbn = match["isbn"]
            confidence = 0.80
            status = "identified"
        else:
            # Vision found text but no ISBN match — store what we have
            final_title = title
            final_author = author
            isbn = None
            confidence = 0.55
            status = "low_confidence"

        data = {
            "status": status,
            "title": final_title,
            "author": final_author,
            "isbn": isbn,
            "id_confidence": confidence,
            "language": detected_lang,
        }
        asyncio.run(_update_book_db(book_id, sweep_id, data))

        # Push title/author update to browser immediately
        from ws_notify import push_book_update
        push_book_update(sweep_id, book_id)

        # 4. Dispatch pricing for identified or low_confidence books
        if status in ("identified", "low_confidence") and final_title:
            from pricing_task import price_book
            price_book.delay(
                sweep_id=sweep_id,
                book_id=book_id,
                isbn=isbn,
                title=final_title,
                country="GB",
                currency="GBP",
            )
            logger.info(f"Pricing dispatched for {book_id[:8]} (ISBN={isbn})")

        return data

    except Exception as exc:
        logger.error(f"Book ID failed [{book_id[:8]}]: {exc}", exc_info=True)
        raise self.retry(exc=exc)
