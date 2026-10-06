"""
Sweep profile configuration system.
Controls the entire system behaviour: model sizes, devices, concurrency, LLM choice.

Usage:
    from config.sweep_profiles import get_profile
    profile = get_profile()  # reads SWEEP_PROFILE env var

Override a single component without changing the whole profile:
    SWEEP_PROFILE=standard CONV_LLM_OVERRIDE=claude-haiku-4-5-20251001 ...
"""
from __future__ import annotations

import dataclasses
import os
from enum import Enum
from typing import Optional


class SweepProfile(str, Enum):
    SLOW = "slow"
    STANDARD = "standard"
    HOT = "hot"


@dataclasses.dataclass(frozen=True)
class ProfileConfig:
    # ── Detection ──────────────────────────────────────────────────────
    yolo_model: str            # yolov8n | yolov8s | yolov8m
    yolo_device: str           # cpu | cuda
    frame_rate_detection: int  # fps submitted to YOLOv8 (1–10)
    frame_rate_slam: int       # fps for depth/SLAM (1–3)
    realtime_detection: bool   # run during sweep (True) or batch post-sweep (False)

    # ── OCR ────────────────────────────────────────────────────────────
    ocr_language: str          # PaddleOCR lang code: en | japan | arabic | ru | ch
    ocr_device: str            # cpu | cuda
    use_superresolution: bool  # upscale tiny spines with Real-ESRGAN before OCR
    sr_device: str             # cpu | cuda
    ocr_during_sweep: bool     # True = per-crop immediately; False = batch post-sweep

    # ── Depth / Measurement ────────────────────────────────────────────
    depth_model: str           # dav2_small | dav2_vitl | dav2_vitg
    depth_device: str          # cpu | cuda
    slam_enabled: bool         # True = ORB-SLAM3; False = depth-only
    measurement_mode: str      # realtime | post_sweep

    # ── Language Model ─────────────────────────────────────────────────
    conversation_llm: str      # e.g. ollama:llama3.1:8b | claude-haiku-4-5-20251001
    conversation_provider: str # ollama | anthropic | openai
    review_llm: str
    review_provider: str
    max_conversation_tokens: int
    stream_tts: bool

    # ── Text-to-Speech ─────────────────────────────────────────────────
    tts_engine: str            # kokoro | piper
    tts_device: str            # cpu | cuda

    # ── Pricing ────────────────────────────────────────────────────────
    pricing_dispatch: str      # immediate | post_sweep
    pricing_workers: int       # Celery worker concurrency
    pricing_timeout_s: int     # Per-book timeout in seconds

    # ── Worker concurrency ─────────────────────────────────────────────
    book_id_workers: int
    measurement_workers: int
    review_wait_timeout_s: int  # Max seconds to wait for workers before packet

    # ── Quality gates ──────────────────────────────────────────────────
    blur_threshold: float       # Laplacian variance; lower = stricter
    min_ocr_confidence: float   # Below this → unidentified (no guess)
    min_id_confidence: float    # Below this → low_confidence (review queue)

    # ── Geography ──────────────────────────────────────────────────────
    language_code: str          # ISO 639-1: en, fr, ja, ar …
    cjk_mode: bool              # Vertical text + CJK OCR
    rtl_text: bool              # Right-to-left (Arabic, Hebrew)


PROFILES: dict[SweepProfile, ProfileConfig] = {
    SweepProfile.SLOW: ProfileConfig(
        yolo_model="yolov8n",
        yolo_device="cpu",
        frame_rate_detection=2,
        frame_rate_slam=1,
        realtime_detection=False,
        ocr_language="en",
        ocr_device="cpu",
        use_superresolution=False,
        sr_device="cpu",
        ocr_during_sweep=False,
        depth_model="dav2_small",
        depth_device="cpu",
        slam_enabled=False,
        measurement_mode="post_sweep",
        conversation_llm="claude-haiku-4-5-20251001",
        conversation_provider="anthropic",
        review_llm="claude-haiku-4-5-20251001",
        review_provider="anthropic",
        max_conversation_tokens=80,
        stream_tts=False,
        tts_engine="piper",
        tts_device="cpu",
        pricing_dispatch="post_sweep",
        pricing_workers=3,
        pricing_timeout_s=15,
        book_id_workers=3,
        measurement_workers=1,
        review_wait_timeout_s=240,
        blur_threshold=80.0,
        min_ocr_confidence=0.45,
        min_id_confidence=0.70,
        language_code="en",
        cjk_mode=False,
        rtl_text=False,
    ),

    SweepProfile.STANDARD: ProfileConfig(
        yolo_model="yolov8s",
        yolo_device="cuda",
        frame_rate_detection=5,
        frame_rate_slam=1,
        realtime_detection=True,
        ocr_language="en",
        ocr_device="cpu",
        use_superresolution=True,
        sr_device="cuda",
        ocr_during_sweep=True,
        depth_model="dav2_vitl",
        depth_device="cuda",
        slam_enabled=True,
        measurement_mode="realtime",
        conversation_llm="ollama:llama3.1:8b",
        conversation_provider="ollama",
        review_llm="claude-sonnet-4-6",
        review_provider="anthropic",
        max_conversation_tokens=120,
        stream_tts=True,
        tts_engine="kokoro",
        tts_device="cpu",
        pricing_dispatch="immediate",
        pricing_workers=5,
        pricing_timeout_s=12,
        book_id_workers=5,
        measurement_workers=2,
        review_wait_timeout_s=240,
        blur_threshold=100.0,
        min_ocr_confidence=0.40,
        min_id_confidence=0.70,
        language_code="en",
        cjk_mode=False,
        rtl_text=False,
    ),

    SweepProfile.HOT: ProfileConfig(
        yolo_model="yolov8m",
        yolo_device="cuda",
        frame_rate_detection=10,
        frame_rate_slam=3,
        realtime_detection=True,
        ocr_language="en",
        ocr_device="cuda",
        use_superresolution=True,
        sr_device="cuda",
        ocr_during_sweep=True,
        depth_model="dav2_vitg",
        depth_device="cuda",
        slam_enabled=True,
        measurement_mode="realtime",
        conversation_llm="ollama:llama3.1:70b",
        conversation_provider="ollama",
        review_llm="ollama:llama3.1:70b",
        review_provider="ollama",
        max_conversation_tokens=200,
        stream_tts=True,
        tts_engine="kokoro",
        tts_device="cuda",
        pricing_dispatch="immediate",
        pricing_workers=10,
        pricing_timeout_s=10,
        book_id_workers=10,
        measurement_workers=4,
        review_wait_timeout_s=200,
        blur_threshold=100.0,
        min_ocr_confidence=0.35,
        min_id_confidence=0.65,
        language_code="en",
        cjk_mode=False,
        rtl_text=False,
    ),
}


def get_profile() -> ProfileConfig:
    """
    Returns the active profile, applying any per-component env var overrides.
    Called once per service startup — not per request.
    """
    name = os.environ.get("SWEEP_PROFILE", "standard").lower().strip()
    try:
        base = PROFILES[SweepProfile(name)]
    except ValueError:
        raise ValueError(
            f"Unknown SWEEP_PROFILE={name!r}. "
            f"Valid values: {[p.value for p in SweepProfile]}"
        )

    # Per-component overrides (for mixed configurations)
    overrides: dict = {}
    env_map = {
        "CONV_LLM_OVERRIDE": "conversation_llm",
        "CONV_PROVIDER_OVERRIDE": "conversation_provider",
        "REVIEW_LLM_OVERRIDE": "review_llm",
        "REVIEW_PROVIDER_OVERRIDE": "review_provider",
        "YOLO_DEVICE_OVERRIDE": "yolo_device",
        "OCR_LANG_OVERRIDE": "ocr_language",
    }
    for env_key, field_name in env_map.items():
        val = os.environ.get(env_key)
        if val:
            overrides[field_name] = val

    pricing_workers_override = os.environ.get("PRICING_WORKERS_OVERRIDE")
    if pricing_workers_override:
        try:
            overrides["pricing_workers"] = int(pricing_workers_override)
        except ValueError:
            pass

    if overrides:
        return dataclasses.replace(base, **overrides)
    return base
