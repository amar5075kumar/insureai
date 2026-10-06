"""
Metric depth estimation using Depth Anything v2.

Model selection (from profile):
  slow:     dav2_small  (ViT-S, ~300ms CPU)
  standard: dav2_vitl   (ViT-L, ~200ms GPU)
  hot:      dav2_vitg   (ViT-G, best accuracy)

The metric indoor checkpoint returns depth in metres.
Without a scale anchor from the user, absolute accuracy is ~±15%.
With a user-provided shelf width, it improves to ~±5–8%.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_ENCODER_MAP = {
    "dav2_small": "vits",
    "dav2_vitl": "vitl",
    "dav2_vitg": "vitg",
}

_CHECKPOINT_MAP = {
    "vits": "depth_anything_v2_metric_indoor_vits.pth",
    "vitl": "depth_anything_v2_metric_indoor_vitl.pth",
    "vitg": "depth_anything_v2_metric_indoor_vitg.pth",
}

_OUT_CHANNELS_MAP = {
    "vits": [48, 96, 192, 384],
    "vitl": [256, 512, 1024, 1024],
    "vitg": [1536, 1536, 1536, 1536],
}


class DepthEstimator:
    def __init__(self) -> None:
        from config.sweep_profiles import get_profile

        profile = get_profile()
        encoder = _ENCODER_MAP.get(profile.depth_model, "vitl")
        ckpt = f"/app/models/depth_anything/{_CHECKPOINT_MAP[encoder]}"
        self._device = profile.depth_device
        self._model = None

        if os.path.exists(ckpt):
            self._load(encoder, ckpt)
        else:
            logger.warning(
                f"Depth model checkpoint not found: {ckpt}. "
                "Depth estimation disabled — scale will use priors only."
            )

    def _load(self, encoder: str, ckpt_path: str) -> None:
        import torch
        from depth_anything_v2.dpt import DepthAnythingV2

        out_ch = _OUT_CHANNELS_MAP[encoder]
        model = DepthAnythingV2(encoder=encoder, features=256, out_channels=out_ch)
        state = torch.load(ckpt_path, map_location=self._device)
        model.load_state_dict(state)
        model = model.to(self._device).eval()
        self._model = model
        logger.info(f"Depth Anything v2 {encoder} loaded on {self._device}")

    def estimate(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """
        Returns a depth map in metres, shape (H, W), dtype float32.
        Returns None if model is unavailable.
        """
        if self._model is None:
            return None
        try:
            import torch
            with torch.no_grad():
                depth = self._model.infer_image(frame, input_size=518)
            return depth
        except Exception as e:
            logger.error(f"Depth estimation failed: {e}")
            return None

    @property
    def available(self) -> bool:
        return self._model is not None
