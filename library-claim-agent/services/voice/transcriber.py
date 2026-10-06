"""
Speech-to-text transcription using faster-whisper.

Model is loaded once at startup (heavy).
transcribe() is synchronous — run in a thread pool executor from async code.

Accuracy vs speed trade-off (configured by sweep profile):
  slow:     base    (74M,  ~100ms, WER ~12%)
  standard: medium  (769M, ~200ms, WER ~7%)
  hot:      large-v3 (1550M, ~500ms, WER ~5%)
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import numpy as np
from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)


@dataclass
class TranscriptResult:
    text: str
    language: str
    confidence: float   # 0.0–1.0 (derived from avg log probability)
    duration_s: float


_MODEL_SIZE_MAP = {
    "slow": "base",
    "standard": "medium",
    "hot": "large-v3",
}


class Transcriber:
    def __init__(self) -> None:
        profile_name = os.environ.get("SWEEP_PROFILE", "standard")
        model_size = _MODEL_SIZE_MAP.get(profile_name, "medium")

        logger.info(f"Loading Whisper {model_size}…")
        self.model = WhisperModel(
            model_size,
            device="cpu",
            compute_type="int8",
            download_root="/app/models/whisper",
            num_workers=2,
        )
        logger.info(f"Whisper {model_size} loaded")

    def transcribe(
        self,
        audio: np.ndarray,
        language: str | None = None,
    ) -> TranscriptResult:
        """
        Transcribe a float32 numpy array (16kHz, mono).
        language=None → Whisper auto-detects.

        This is CPU-bound. Call it from a ThreadPoolExecutor:
            loop.run_in_executor(None, transcriber.transcribe, audio, lang)
        """
        segments, info = self.model.transcribe(
            audio,
            language=language,
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            word_timestamps=False,
        )

        text_parts: list[str] = []
        log_probs: list[float] = []
        for seg in segments:
            text_parts.append(seg.text.strip())
            if seg.avg_logprob is not None:
                log_probs.append(seg.avg_logprob)

        text = " ".join(text_parts).strip()

        # avg_logprob is ≤ 0; closer to 0 = higher confidence
        avg_lp = sum(log_probs) / len(log_probs) if log_probs else -1.0
        confidence = float(max(0.0, min(1.0, avg_lp + 1.0)))

        return TranscriptResult(
            text=text,
            language=info.language,
            confidence=confidence,
            duration_s=info.duration,
        )
