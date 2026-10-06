"""
LLM provider connection test endpoint.
Validates credentials without storing them server-side.
"""
from __future__ import annotations
import json, logging, os, time
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

router = APIRouter()
logger = logging.getLogger(__name__)


class TestLLMRequest(BaseModel):
    provider: str = "anthropic"           # anthropic | bedrock | azgateway
    apiKey: Optional[str] = None
    baseUrl: Optional[str] = None
    bearerToken: Optional[str] = None
    region: Optional[str] = "us-east-1"
    accessKey: Optional[str] = None
    secretKey: Optional[str] = None


@router.post("/config/test-llm")
async def test_llm(body: TestLLMRequest) -> dict:
    """Test LLM connection with the provided credentials. Nothing is stored."""
    start = time.monotonic()

    try:
        if body.provider in ("bedrock", "azgateway") and body.baseUrl:
            result = await _test_enterprise_gateway(body)
        elif body.provider == "anthropic" and body.apiKey:
            result = await _test_anthropic(body.apiKey)
        elif body.provider == "openai" and body.apiKey:
            result = await _test_openai(body.apiKey)
        else:
            return {"success": False, "error": "Missing credentials for selected provider"}

        ms = int((time.monotonic() - start) * 1000)
        return {"success": True, "model": result, "latency_ms": ms}

    except Exception as e:
        ms = int((time.monotonic() - start) * 1000)
        msg = str(e)
        if "401" in msg or "authentication" in msg.lower():
            msg = "Invalid API key or bearer token"
        elif "404" in msg:
            msg = "Base URL not found — check the gateway URL"
        elif "SSL" in msg or "certificate" in msg.lower():
            msg = "SSL certificate error — gateway URL may be incorrect"
        elif "connect" in msg.lower() or "timeout" in msg.lower():
            msg = "Cannot reach the endpoint — check Base URL and network"
        return {"success": False, "error": msg, "latency_ms": ms}


async def _test_enterprise_gateway(body: TestLLMRequest) -> str:
    import httpx2
    token = body.bearerToken or body.apiKey or ""
    model = os.environ.get("BEDROCK_MODEL", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
    url = f"{body.baseUrl.rstrip('/')}/model/{model}/invoke"
    payload = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 20,
        "messages": [{"role": "user", "content": "Reply with just: OK"}],
    }
    async with httpx2.AsyncClient(verify=False, timeout=15.0) as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            content=json.dumps(payload),
        )
        resp.raise_for_status()
    data = resp.json()
    return data.get("content", [{}])[0].get("text", "OK")


async def _test_anthropic(api_key: str) -> str:
    import httpx2
    async with httpx2.AsyncClient(verify=False, timeout=15.0) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            content=json.dumps({
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 20,
                "messages": [{"role": "user", "content": "Reply: OK"}],
            }),
        )
        resp.raise_for_status()
    data = resp.json()
    return data.get("content", [{}])[0].get("text", "OK")


async def _test_openai(api_key: str) -> str:
    import httpx2
    async with httpx2.AsyncClient(verify=False, timeout=15.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            content=json.dumps({
                "model": "gpt-4o-mini",
                "max_tokens": 10,
                "messages": [{"role": "user", "content": "Reply: OK"}],
            }),
        )
        resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]
