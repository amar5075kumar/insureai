"""
Cross-frame book deduplication.

The same book may be detected in 20+ frames as the camera pans.
BookTracker maintains a list of unique spine tracks using 2D spatial proximity.
When the same book is seen again, it updates the track with the highest-quality frame.

Design:
  - "same book" = centres within SPATIAL_THRESHOLD of the frame diagonal
  - Best frame = highest blur_score × spine pixel height
  - Returns book_id (str) for new books, None for duplicates

No 3D SLAM used in Phase 1 — plain 2D tracking with normalised coordinates.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from detector import SpineDetection

logger = logging.getLogger(__name__)


@dataclass
class BookTrack:
    book_id: str
    center_x: float            # Normalised 0–1
    center_y: float
    best_frame_id: str
    best_quality: float         # composite score
    frame_count: int = 1
    crop_s3_key: Optional[str] = None


class BookTracker:
    """
    Stateful tracker.  One instance per sweep session.
    Call update() for every spine detection.
    """

    # Threshold for "same book": fraction of image diagonal
    SPATIAL_THRESHOLD = 0.06

    def __init__(self) -> None:
        self._tracks: list[BookTrack] = []

    def update(
        self,
        detection: SpineDetection,
        frame_id: str,
        frame_width: int = 1920,
        frame_height: int = 1080,
        blur_score: float = 100.0,
        crop_s3_key: Optional[str] = None,
    ) -> Optional[str]:
        """
        Returns book_id if this is a new book.
        Returns None if this matches an existing track (duplicate).
        Updates the best frame if this detection has higher quality.
        """
        cx = ((detection.x1 + detection.x2) / 2) / frame_width
        cy = ((detection.y1 + detection.y2) / 2) / frame_height

        # Quality score: sharpness × spine height (larger + sharper = better OCR)
        quality = blur_score * detection.bbox_height

        for track in self._tracks:
            dist = float(
                np.sqrt((track.center_x - cx) ** 2 + (track.center_y - cy) ** 2)
            )
            if dist < self.SPATIAL_THRESHOLD:
                # Same book — update if higher quality
                if quality > track.best_quality:
                    track.best_frame_id = frame_id
                    track.best_quality = quality
                    if crop_s3_key:
                        track.crop_s3_key = crop_s3_key
                track.frame_count += 1
                return None  # Duplicate

        # New book
        book_id = str(uuid.uuid4())
        self._tracks.append(
            BookTrack(
                book_id=book_id,
                center_x=cx,
                center_y=cy,
                best_frame_id=frame_id,
                best_quality=quality,
                crop_s3_key=crop_s3_key,
            )
        )
        return book_id

    @property
    def unique_count(self) -> int:
        return len(self._tracks)

    def get_best_frame_id(self, book_id: str) -> Optional[str]:
        for track in self._tracks:
            if track.book_id == book_id:
                return track.best_frame_id
        return None
