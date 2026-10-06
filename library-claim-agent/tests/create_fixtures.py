#!/usr/bin/env python3
"""
Creates synthetic test fixtures.
Run once before running tests:
    python tests/create_fixtures.py
Or via Makefile:
    make fixtures
"""
from __future__ import annotations

import logging
import sys
import os
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURES.mkdir(exist_ok=True)
(FIXTURES / "test_frames").mkdir(exist_ok=True)


def create_bookshelf() -> None:
    import cv2
    import numpy as np

    img = np.zeros((720, 1280, 3), dtype=np.uint8)
    img[:] = (45, 35, 25)
    colors = [
        (200, 100, 50), (50, 150, 200), (100, 200, 100),
        (200, 200, 50), (180, 80, 180), (80, 180, 180),
    ]
    for i, color in enumerate(colors * 3):
        x = 60 + i * 65
        if x + 50 > 1280:
            break
        cv2.rectangle(img, (x, 80), (x + 45, 420), color, -1)
        label = f"Book {i+1}"
        cv2.putText(img, label, (x + 2, 260), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1)

    cv2.imwrite(str(FIXTURES / "bookshelf_sample.jpg"), img)
    log.info("✓ bookshelf_sample.jpg")

    # Spine crop
    crop = np.zeros((200, 50, 3), dtype=np.uint8)
    crop[:] = (100, 150, 200)
    cv2.putText(crop, "BOOK", (3, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    cv2.putText(crop, "AUTH", (3, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
    cv2.imwrite(str(FIXTURES / "spine_test_crop.jpg"), crop)
    log.info("✓ spine_test_crop.jpg")

    # Test frames for integration sweep test
    for i in range(10):
        frame = img.copy()
        cv2.putText(frame, f"Frame {i:02d}", (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        cv2.imwrite(str(FIXTURES / "test_frames" / f"frame_{i:04d}.jpg"), frame)
    log.info("✓ 10 test_frames/*.jpg")


def create_test_audio() -> None:
    try:
        import numpy as np
        import soundfile as sf

        sr = 16000
        silence = np.zeros(sr, dtype=np.float32)
        t = np.linspace(0, 0.5, sr // 2)
        tone = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        audio = np.concatenate([silence, tone, silence])
        sf.write(str(FIXTURES / "test_audio.wav"), audio, sr)
        log.info("✓ test_audio.wav")
    except ImportError:
        log.warning("  soundfile not installed — skipping test_audio.wav")


def main() -> None:
    create_bookshelf()
    create_test_audio()
    log.info(f"\n✓ All fixtures created in {FIXTURES}")


if __name__ == "__main__":
    main()
