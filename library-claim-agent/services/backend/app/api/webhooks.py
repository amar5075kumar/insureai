"""
Webhook handlers for video frames and audio from the browser.
Saves frames to filesystem (no MinIO needed), pushes events to Redis.
"""
from __future__ import annotations

import asyncio
import logging
import os

from fastapi import APIRouter, File, Form, Header, Request, Response, UploadFile

from app.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

_redis = None


def set_redis(redis_client) -> None:
    global _redis
    _redis = redis_client


@router.post("/frame")
async def receive_frame(
    sweep_id: str = Form(...),
    frame_id: str = Form(...),
    timestamp_ms: int = Form(...),
    jpeg_data: UploadFile = File(...),
) -> dict:
    """
    Receives a video frame from the browser.
    Saves to filesystem, pushes to Redis Stream for vision pipeline.
    Responds immediately (<100ms) — heavy work is async.
    """
    jpeg_bytes = await jpeg_data.read()

    async def _background() -> None:
        try:
            # Save frame to filesystem
            sweep_dir = os.path.join(settings.frames_dir, sweep_id, "frames")
            os.makedirs(sweep_dir, exist_ok=True)
            frame_path = os.path.join(sweep_dir, f"{frame_id}.jpg")
            with open(frame_path, "wb") as f:
                f.write(jpeg_bytes)

            s3_key = f"{sweep_id}/frames/{frame_id}.jpg"  # logical path for workers

            # Push to Redis Stream → vision pipeline
            if _redis is not None:
                await _redis.xadd(
                    f"frames:{sweep_id}",
                    {
                        "frame_id": frame_id,
                        "s3_key": s3_key,
                        "local_path": frame_path,
                        "timestamp_ms": str(timestamp_ms),
                    },
                    maxlen=2000,
                )
        except Exception as exc:
            logger.error(f"Frame save failed [{sweep_id}/{frame_id}]: {exc}")

    asyncio.create_task(_background())
    return {"queued": True}


@router.post("/audio")
async def receive_audio(
    request: Request,
    x_sweep_id: str = Header(..., alias="X-Sweep-Id"),
    x_chunk_id: str = Header(..., alias="X-Chunk-Id"),
) -> Response:
    """Receives audio PCM chunk from browser microphone."""
    pcm_bytes = await request.body()

    if _redis is not None:
        asyncio.create_task(
            _redis.xadd(
                f"audio:{x_sweep_id}",
                {"pcm": pcm_bytes, "chunk_id": x_chunk_id},
                maxlen=1000,
            )
        )
    return Response(status_code=200)
