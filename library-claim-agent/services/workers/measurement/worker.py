"""
Room measurement Celery worker.
Dispatched at sweep end after all frames are captured.
"""
from __future__ import annotations

import asyncio
import logging

from celery_app import app
from db import get_scale_anchor, update_room_geometry

logger = logging.getLogger(__name__)


@app.task(
    bind=True,
    name="workers.measurement.measure_room",
    queue="measurement",
    max_retries=1,
    time_limit=120,
    soft_time_limit=100,
    acks_late=True,
)
def measure_room_task(
    self,
    sweep_id: str,
    frame_ids: list,
    scale_anchor: dict | None = None,
) -> dict:
    """
    Estimate room geometry from 1fps depth frames.
    frame_ids: list of frame IDs in chronological order
    scale_anchor: {"method": ..., "value_m": ...} or None
    """
    try:
        if scale_anchor is None:
            scale_anchor = get_scale_anchor(sweep_id)

        from measurement.geometry import estimate_room_geometry
        room = asyncio.run(
            estimate_room_geometry(sweep_id, frame_ids, scale_anchor)
        )

        update_room_geometry(sweep_id, room)

        logger.info(
            f"Room measured [{sweep_id}]: floor={room.floor_area_m2}m² "
            f"wall={room.wall_area_m2}m² conf={room.confidence}"
        )
        return {
            "floor_area_m2": room.floor_area_m2,
            "wall_area_m2": room.wall_area_m2,
            "confidence": room.confidence,
            "scale_method": room.scale_method,
        }

    except Exception as exc:
        logger.error(f"Measurement failed [{sweep_id}]: {exc}", exc_info=True)
        update_room_geometry(sweep_id, None)
        raise self.retry(exc=exc)
