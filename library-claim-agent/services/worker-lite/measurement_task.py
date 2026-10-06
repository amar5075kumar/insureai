"""
Lightweight measurement stub — no depth model, no PyTorch.
Estimates room geometry from frame count and sweep duration.
Good enough for local dev; replace with Depth Anything v2 in production.
"""
from __future__ import annotations

import asyncio
import logging
import os

import asyncpg
from celery_app import app

logger = logging.getLogger(__name__)
DATABASE_URL = os.environ.get("DATABASE_URL", "").replace("+asyncpg", "")


@app.task(
    bind=True,
    name="workers.measurement.measure_room",
    queue="measurement",
    max_retries=1,
    acks_late=True,
)
def measure_room(
    self,
    sweep_id: str,
    frame_ids: list,
    scale_anchor: dict | None = None,
) -> dict:
    """
    Estimate room geometry without depth model.
    Uses frame count as a proxy for shelf length (1 frame ≈ 30cm at 3s interval, slow walk).
    """
    try:
        n_frames = len(frame_ids) if frame_ids else 0
        # Heuristic: ~0.3m per frame at slow walk speed
        estimated_shelf_length_m = round(n_frames * 0.30, 1)
        # Standard shelf height 2.1m, width from frames
        floor_area = round(estimated_shelf_length_m * 3.5, 1)   # room depth ~3.5m
        wall_area = round(estimated_shelf_length_m * 2.1, 1)    # 1 wall

        # Apply scale anchor if user told us shelf size
        if scale_anchor and scale_anchor.get("value_m"):
            scale = float(scale_anchor["value_m"]) / max(estimated_shelf_length_m, 0.1)
            floor_area = round(floor_area * scale, 1)
            wall_area = round(wall_area * scale, 1)

        result = {
            "floor_area_m2": floor_area,
            "wall_area_m2": wall_area,
            "confidence": 0.40,  # Low confidence — heuristic only
            "scale_method": scale_anchor.get("method", "heuristic") if scale_anchor else "heuristic",
            "frame_count": n_frames,
        }

        # Write to DB if table exists
        async def _write():
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                await conn.execute(
                    "UPDATE sweeps SET floor_area_m2=$1 WHERE id=$2",
                    result["floor_area_m2"], sweep_id,
                )
            except Exception:
                pass  # Column may not exist — non-fatal
            finally:
                await conn.close()

        asyncio.run(_write())
        logger.info(f"Measurement [{sweep_id[:8]}]: floor={floor_area}m² (heuristic, {n_frames} frames)")
        return result

    except Exception as exc:
        logger.error(f"Measurement failed [{sweep_id[:8]}]: {exc}")
        return {"error": str(exc), "floor_area_m2": None}
