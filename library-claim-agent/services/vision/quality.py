"""
Frame quality assessment.
Runs on every incoming frame — must be fast (<10ms).

Detects:
  - Motion blur (camera moving too fast)
  - Overexposure / glare (window light)
  - Underexposure / darkness
  - Overall sharpness (Laplacian variance)

Returns a QualityResult with an optional feedback string for the agent to speak.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class QualityResult:
    blur_score: float          # Laplacian variance — higher = sharper
    is_blurry: bool
    is_overexposed: bool
    is_dark: bool
    motion_magnitude: float    # Optical flow mean magnitude
    feedback: Optional[str]    # Message for the voice agent, or None


class FrameQualityAssessor:
    """
    Stateful quality assessor — tracks consecutive bad frames to avoid
    spamming the user with every single frame.

    One instance per sweep session.
    """

    BLUR_THRESHOLD = 100.0          # Laplacian variance below this = blurry
    OVEREXPOSURE_FRACTION = 0.30    # >30% saturated pixels = glare
    DARK_MEAN_THRESHOLD = 40.0      # Mean brightness < 40 = too dark
    MOTION_THRESHOLD = 8.0          # px/frame mean optical flow

    # Only emit feedback once every N blurry/dark frames (avoid spam)
    FEEDBACK_COOLDOWN_FRAMES = 15

    def __init__(self) -> None:
        self._prev_gray: Optional[np.ndarray] = None
        self._frames_since_feedback = 0

    def assess(self, frame: np.ndarray) -> QualityResult:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Sharpness (Laplacian variance — high frequency energy)
        blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        is_blurry = blur_score < self.BLUR_THRESHOLD

        # Overexposure
        saturated = float(np.sum(gray > 250) / gray.size)
        is_overexposed = saturated > self.OVEREXPOSURE_FRACTION

        # Darkness
        is_dark = float(np.mean(gray)) < self.DARK_MEAN_THRESHOLD

        # Optical flow (motion blur estimation)
        motion_mag = 0.0
        if self._prev_gray is not None and self._prev_gray.shape == gray.shape:
            try:
                flow = cv2.calcOpticalFlowFarneback(
                    self._prev_gray, gray, None,
                    pyr_scale=0.5, levels=3, winsize=15,
                    iterations=3, poly_n=5, poly_sigma=1.2,
                    flags=0,
                )
                motion_mag = float(
                    np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2).mean()
                )
            except cv2.error:
                pass
        self._prev_gray = gray

        # Feedback (rate-limited)
        feedback: Optional[str] = None
        self._frames_since_feedback += 1

        if self._frames_since_feedback >= self.FEEDBACK_COOLDOWN_FRAMES:
            if motion_mag > self.MOTION_THRESHOLD:
                feedback = "you're moving a bit quickly — I can't read the spines clearly"
                self._frames_since_feedback = 0
            elif is_blurry:
                feedback = "please slow down a little, the image is blurry"
                self._frames_since_feedback = 0
            elif is_overexposed:
                feedback = "there's quite a bit of glare — try adjusting your angle slightly"
                self._frames_since_feedback = 0
            elif is_dark:
                feedback = "it's quite dark on this side — a light would help"
                self._frames_since_feedback = 0

        return QualityResult(
            blur_score=blur_score,
            is_blurry=is_blurry,
            is_overexposed=is_overexposed,
            is_dark=is_dark,
            motion_magnitude=motion_mag,
            feedback=feedback,
        )
