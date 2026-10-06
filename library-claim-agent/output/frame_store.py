"""
FrameStore: filesystem-based frame existence and retrieval.
Replaces MinIO with local filesystem (FRAMES_DIR env var).
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

FRAMES_DIR = os.environ.get("FRAMES_DIR", "/app/frame_data")


class FrameStore:
    def exists(self, key: str) -> bool:
        """key format: sweep_id/frames/frame_xxx.jpg or sweep_id/crops/book_id.jpg"""
        return os.path.exists(os.path.join(FRAMES_DIR, key))

    def get(self, key: str) -> Optional[bytes]:
        path = os.path.join(FRAMES_DIR, key)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "rb") as f:
                return f.read()
        except OSError as e:
            logger.warning(f"FrameStore.get failed for {key}: {e}")
            return None
