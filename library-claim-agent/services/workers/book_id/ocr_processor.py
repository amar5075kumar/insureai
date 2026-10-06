"""
Spine OCR pipeline.

Steps:
  1. Super-resolution (if crop height < 60px and profile enables it)
  2. Deskew: rotate vertical spine text to horizontal
  3. PaddleOCR: detect + recognise text regions
  4. Clean and return text + confidence

Returns (text, confidence) where:
  confidence is the mean PaddleOCR confidence over all detected text lines
  text is the joined recognised text, cleaned of noise (ISBNs, prices, etc.)
"""
from __future__ import annotations

import logging
import os
import re
from typing import Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Noise patterns found on book spines that confuse the title parser
_NOISE_PATTERNS = [
    re.compile(r"\b\d{9,13}\b"),       # ISBNs
    re.compile(r"[£$€¥]\s*\d+"),       # Prices
    re.compile(r"\b\d{4}\b"),          # Standalone years
    re.compile(r"www\.\S+", re.I),     # URLs
    re.compile(r"\bISBN\b", re.I),     # Literal "ISBN"
]


def run_ocr_on_crop(crop: np.ndarray) -> Tuple[str, float]:
    """
    Full OCR pipeline on a single spine crop.
    Returns (text, confidence).
    """
    if crop is None or crop.size == 0:
        return "", 0.0

    profile_name = os.environ.get("SWEEP_PROFILE", "standard")
    use_sr = profile_name != "slow" and crop.shape[0] < 60

    if use_sr:
        crop = _upscale_with_esrgan(crop)

    crop = _deskew(crop)

    ocr_lang = os.environ.get("OCR_LANG_OVERRIDE") or _get_ocr_language(profile_name)
    return _run_paddleocr(crop, lang=ocr_lang)


def _get_ocr_language(profile_name: str) -> str:
    """Derive OCR language from sweep profile (can be overridden per sweep)."""
    # Language can be overridden per-session via env var
    return os.environ.get("OCR_LANGUAGE", "en")


def _upscale_with_esrgan(crop: np.ndarray) -> np.ndarray:
    """Upscale small spine crops with Real-ESRGAN ×4."""
    try:
        from basicsr.archs.rrdbnet_arch import RRDBNet
        from realesrgan import RealESRGANer

        if not hasattr(_upscale_with_esrgan, "_upsampler"):
            model = RRDBNet(
                num_in_ch=3, num_out_ch=3,
                num_feat=64, num_block=23, num_grow_ch=32, scale=4,
            )
            _upscale_with_esrgan._upsampler = RealESRGANer(
                scale=4,
                model_path="/app/models/realesrgan/RealESRGAN_x4plus.pth",
                model=model,
                tile=0,
                tile_pad=10,
                pre_pad=0,
            )

        output, _ = _upscale_with_esrgan._upsampler.enhance(crop, outscale=4)
        return output
    except Exception as e:
        logger.debug(f"SR failed (using original): {e}")
        return crop


def _deskew(crop: np.ndarray) -> np.ndarray:
    """Rotate vertical spine text to horizontal for OCR."""
    h, w = crop.shape[:2]
    # Spine images are taller than wide — rotate 90° CW
    if h > w * 1.5:
        return cv2.rotate(crop, cv2.ROTATE_90_CLOCKWISE)
    return crop


def _run_paddleocr(crop: np.ndarray, lang: str = "en") -> Tuple[str, float]:
    """Run PaddleOCR and return (text, mean_confidence)."""
    from paddleocr import PaddleOCR

    # Cache one instance per language (model loading is expensive)
    cache_key = f"_ocr_{lang}"
    if not hasattr(_run_paddleocr, cache_key):
        setattr(
            _run_paddleocr,
            cache_key,
            PaddleOCR(
                use_angle_cls=True,
                lang=lang,
                use_gpu=False,
                show_log=False,
            ),
        )
    ocr = getattr(_run_paddleocr, cache_key)

    try:
        result = ocr.ocr(crop, cls=True)
    except Exception as e:
        logger.warning(f"PaddleOCR failed: {e}")
        return "", 0.0

    if not result or not result[0]:
        return "", 0.0

    texts: list[str] = []
    confidences: list[float] = []

    for line in result[0]:
        if not line or len(line) < 2:
            continue
        text_part, conf = line[1]
        if conf < 0.3:
            continue  # Skip very low confidence
        # Clean noise patterns
        cleaned = text_part
        for pattern in _NOISE_PATTERNS:
            cleaned = pattern.sub("", cleaned)
        cleaned = cleaned.strip()
        if len(cleaned) >= 2:
            texts.append(cleaned)
            confidences.append(conf)

    if not texts:
        return "", 0.0

    return " ".join(texts), sum(confidences) / len(confidences)
