"""
WebSocket endpoint for real-time sweep updates.

Message types (server → browser):
  inventory_update   → new/updated books and items list
  agent_audio        → base64-encoded PCM audio from TTS
  quality_warning    → motion blur, glare, darkness notice
  processing_progress → worker completion percentage
  sweep_complete     → packet is ready

Message types (browser → server):
  user_text          → typed correction (bypasses voice)
  sweep_end          → user taps "Done"
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.websocket_manager import manager

router = APIRouter()
logger = logging.getLogger(__name__)


@router.websocket("/ws/{sweep_id}")
async def websocket_endpoint(websocket: WebSocket, sweep_id: str) -> None:
    await manager.connect(sweep_id, websocket)
    relay_task = asyncio.create_task(_relay_agent_responses(sweep_id))
    try:
        while True:
            data = await websocket.receive_json()
            await _handle_client_message(sweep_id, data)
    except WebSocketDisconnect:
        manager.disconnect(sweep_id)
        await _handle_disconnect(sweep_id)
    except Exception as exc:
        logger.error(f"WebSocket error [{sweep_id}]: {exc}")
        manager.disconnect(sweep_id)
    finally:
        relay_task.cancel()


async def _handle_client_message(sweep_id: str, data: dict) -> None:
    """Route incoming browser messages to the appropriate handler."""
    from app.api.webhooks import _redis  # lazy to avoid circular

    msg_type = data.get("type")

    if msg_type == "user_text":
        if _redis and data.get("text"):
            import json
            await _redis.rpush(
                f"transcript_queue:{sweep_id}",
                json.dumps({
                    "text": data["text"],
                    "confidence": 1.0,
                    "language": "en",
                    "source": "text_input",
                }),
            )

    elif msg_type == "sweep_end":
        if _redis:
            await _redis.rpush(f"sweep_end_queue:{sweep_id}", "end")

    else:
        logger.debug(f"Unknown WS message type from browser: {msg_type!r}")


async def _relay_agent_responses(sweep_id: str) -> None:
    """Subscribe to agent_response:{sweep_id} Redis channel and forward to browser."""
    import json
    import redis.asyncio as aioredis

    redis_url = None
    try:
        from app.config import settings
        redis_url = settings.redis_url
    except Exception:
        return

    sub_redis = aioredis.from_url(redis_url, decode_responses=True)
    pubsub = sub_redis.pubsub()
    await pubsub.subscribe(f"agent_response:{sweep_id}", f"ws_broadcast:{sweep_id}")
    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            if not manager.is_connected(sweep_id):
                break
            try:
                channel = message.get("channel", "")
                data = json.loads(message["data"])
                if f"ws_broadcast:{sweep_id}" in channel:
                    # inventory_update, processing_progress, sweep_complete — relay as-is
                    await manager.broadcast(sweep_id, data)
                else:
                    await manager.broadcast(sweep_id, {
                        "type": "agent_text",
                        "text": data.get("text", ""),
                    })
            except Exception as exc:
                logger.debug(f"Relay error [{sweep_id}]: {exc}")
    except asyncio.CancelledError:
        pass
    finally:
        await pubsub.unsubscribe(f"agent_response:{sweep_id}")
        await sub_redis.aclose()


async def _handle_disconnect(sweep_id: str) -> None:
    """Handle browser disconnection — mark sweep as interrupted if still running."""
    from app.database import get_db

    from sqlalchemy import text
    async with get_db() as db:
        await db.execute(
            text("""
            UPDATE sweeps
            SET state = 'interrupted',
                error_message = 'WebSocket disconnected (battery / navigation)'
            WHERE id = :id AND state IN ('initializing', 'sweeping')
            """),
            {"id": sweep_id},
        )
    logger.info(f"Sweep {sweep_id} marked interrupted after WS disconnect")
