"""
Voice Activity Detection using Silero VAD.
Detects speech boundaries in a continuous PCM stream.

Input:  Raw PCM bytes (int16, 16kHz, mono)
Output: SpeechSegment when a complete utterance is detected

The iterator pattern means VAD is stateful per-session — one SileroVAD
instance per sweep.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import torch

logger = logging.getLogger(__name__)


@dataclass
class SpeechSegment:
    audio: np.ndarray     # float32, normalised -1 to 1, 16kHz
    start_sample: int
    end_sample: int
    duration_ms: float


class SileroVAD:
    """
    Stateful VAD processor.
    Create one instance per sweep session.
    Call process_chunk() for each incoming PCM chunk.
    """

    SAMPLE_RATE = 16000
    MIN_SPEECH_MS = 300     # Ignore utterances shorter than this
    MAX_SILENCE_MS = 700    # Silence this long ends an utterance
    CHUNK_SAMPLES = 512     # Required chunk size for Silero (32ms at 16kHz)

    def __init__(self) -> None:
        self._model, self._utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            trust_repo=True,
            force_reload=False,
            verbose=False,
        )
        (
            _get_speech_timestamps,
            _,
            _,
            VADIterator,
            _,
        ) = self._utils

        self._vad_iter = VADIterator(
            self._model,
            sampling_rate=self.SAMPLE_RATE,
            threshold=0.5,
            min_silence_duration_ms=self.MAX_SILENCE_MS,
        )
        self._buffer: List[np.ndarray] = []
        self._speaking = False

    def process_chunk(self, pcm_bytes: bytes) -> Optional[SpeechSegment]:
        """
        Process one chunk of raw PCM.
        Returns a SpeechSegment when an utterance boundary is detected,
        otherwise returns None.
        """
        audio_int16 = np.frombuffer(pcm_bytes, dtype=np.int16)
        audio_float = audio_int16.astype(np.float32) / 32768.0

        # Silero requires exactly CHUNK_SAMPLES per call
        for i in range(0, len(audio_float), self.CHUNK_SAMPLES):
            chunk = audio_float[i : i + self.CHUNK_SAMPLES]
            if len(chunk) < self.CHUNK_SAMPLES:
                # Pad the last chunk
                chunk = np.pad(chunk, (0, self.CHUNK_SAMPLES - len(chunk)))

            tensor = torch.from_numpy(chunk)
            speech_dict = self._vad_iter(tensor, return_seconds=False)

            if speech_dict:
                if "start" in speech_dict:
                    self._speaking = True
                    self._buffer = []
                if self._speaking:
                    self._buffer.append(chunk)
                if "end" in speech_dict and self._speaking:
                    self._speaking = False
                    audio = np.concatenate(self._buffer)
                    duration_ms = len(audio) / self.SAMPLE_RATE * 1000
                    if duration_ms >= self.MIN_SPEECH_MS:
                        return SpeechSegment(
                            audio=audio,
                            start_sample=0,
                            end_sample=len(audio),
                            duration_ms=duration_ms,
                        )
            elif self._speaking:
                self._buffer.append(chunk)

        return None

    def reset(self) -> None:
        """Reset state between utterances (e.g., after an error)."""
        self._vad_iter.reset_states()
        self._buffer = []
        self._speaking = False
