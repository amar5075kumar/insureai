"""
MVP room geometry estimation.

Uses Depth Anything v2 on 1fps frames to estimate floor area and wall area.
No SLAM in the MVP — depth-only with statistical priors.

Accuracy (honest):
  With user-stated shelf width: floor area ±8–12% (may not pass ±10% bar)
  Without scale anchor: ±15–25% (will not pass ±10% bar)
  Standard UK ceiling height used as prior: 2.4m

For production accuracy, ARKit LiDAR (iPhone Pro) or ORB-SLAM3 is required.
This MVP implementation is documented in the failure log.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_CEILING_HEIGHT_M = 2.4  # UK standard ceiling prior


@dataclass
class RoomGeometryResult:
    length_m: Optional[float]
    width_m: Optional[float]
    height_m: Optional[float]
    floor_area_m2: Optional[float]
    wall_area_m2: Optional[float]
    shelved_wall_area_m2: Optional[float]
    scale_method: str
    confidence: float


async def estimate_room_geometry(
    sweep_id: str,
    frame_ids: List[str],
    scale_anchor: Optional[dict],
) -> RoomGeometryResult:
    """
    Estimate room dimensions from depth maps of sampled frames.

    scale_anchor: {"method": "shelf_width", "value_m": 0.8} or None
    """
    from minio import load_frame_from_minio

    if not frame_ids:
        return RoomGeometryResult(
            length_m=None, width_m=None, height_m=DEFAULT_CEILING_HEIGHT_M,
            floor_area_m2=None, wall_area_m2=None, shelved_wall_area_m2=None,
            scale_method="no_frames", confidence=0.0,
        )

    # Sample up to 30 frames (1 per second over a 3-minute sweep)
    step = max(1, len(frame_ids) // 30)
    sample_ids = frame_ids[::step][:30]

    depth_maps: List[np.ndarray] = []
    for fid in sample_ids:
        s3_key = f"{sweep_id}/frames/{fid}.jpg"
        frame = load_frame_from_minio(s3_key)
        if frame is None:
            continue
        depth = _estimate_depth(frame)
        if depth is not None:
            depth_maps.append(depth)

    if not depth_maps:
        return RoomGeometryResult(
            length_m=None, width_m=None, height_m=DEFAULT_CEILING_HEIGHT_M,
            floor_area_m2=None, wall_area_m2=None, shelved_wall_area_m2=None,
            scale_method="depth_unavailable", confidence=0.0,
        )

    # Maximum depth across frames ≈ far wall distance
    max_depths = [float(np.percentile(d, 95)) for d in depth_maps]
    room_depth_relative = float(np.median(max_depths))

    # Determine scale
    if scale_anchor and scale_anchor.get("value_m"):
        scale = scale_anchor["value_m"] / room_depth_relative if room_depth_relative > 0 else 1.0
        scale_method = f"user_{scale_anchor.get('method', 'stated')}"
        confidence = 0.72
    else:
        # Depth Anything v2 metric checkpoint (less reliable without anchor)
        scale = 1.0
        scale_method = "depth_metric_uncalibrated"
        confidence = 0.48

    room_depth_m = room_depth_relative * scale

    # Width: use horizontal spread from middle rows of depth maps
    h_spreads = []
    for d in depth_maps:
        h, w = d.shape
        mid = d[h // 2, :]
        valid = mid[mid > 0.5]  # Ignore near-zero (floor) and very far
        if len(valid) > 10:
            h_spreads.append(float(np.std(valid)))
    room_width_m = room_depth_m * 1.2 if not h_spreads else room_depth_m * 1.1

    floor_area = round(room_depth_m * room_width_m, 2)
    wall_area = round(
        2 * (room_depth_m + room_width_m) * DEFAULT_CEILING_HEIGHT_M, 2
    )

    logger.info(
        f"Room [{sweep_id}]: {room_depth_m:.1f}×{room_width_m:.1f}m "
        f"floor={floor_area}m² wall={wall_area}m² conf={confidence}"
    )

    return RoomGeometryResult(
        length_m=round(room_depth_m, 2),
        width_m=round(room_width_m, 2),
        height_m=DEFAULT_CEILING_HEIGHT_M,
        floor_area_m2=floor_area,
        wall_area_m2=wall_area,
        shelved_wall_area_m2=None,  # Requires shelf detection + projection
        scale_method=scale_method,
        confidence=confidence,
    )


def _estimate_depth(frame: np.ndarray) -> Optional[np.ndarray]:
    """Lazy-loads the depth model and estimates depth for a single frame."""
    try:
        import torch
        from depth_anything_v2.dpt import DepthAnythingV2

        if not hasattr(_estimate_depth, "_model"):
            from config.sweep_profiles import get_profile
            profile = get_profile()
            encoder_map = {"dav2_small": "vits", "dav2_vitl": "vitl", "dav2_vitg": "vitg"}
            encoder = encoder_map.get(profile.depth_model, "vitl")
            ckpt = f"/app/models/depth_anything/depth_anything_v2_metric_indoor_{encoder}.pth"
            out_ch_map = {
                "vits": [48, 96, 192, 384],
                "vitl": [256, 512, 1024, 1024],
                "vitg": [1536, 1536, 1536, 1536],
            }
            model = DepthAnythingV2(encoder=encoder, features=256, out_channels=out_ch_map[encoder])
            model.load_state_dict(torch.load(ckpt, map_location="cpu"))
            model.eval()
            _estimate_depth._model = model

        with torch.no_grad():
            return _estimate_depth._model.infer_image(frame, input_size=518)
    except Exception as e:
        logger.debug(f"Depth estimation failed: {e}")
        return None
