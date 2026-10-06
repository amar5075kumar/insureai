"""
Text-to-speech synthesis.

Primary: Kokoro TTS (Apache 2.0, 82M params, ~100ms first chunk)
Fallback: Piper TTS (MIT, ONNX, lighter weight)

Both produce PCM bytes (int16, 24kHz, mono) suitable for:
  - Web Audio API playback (browser)
  - LiveKit audio track injection

Streaming mode: yields PCM chunks as they're generated.
Use streaming when latency matters (hot path agent responses).
"""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator

import numpy as np

logger = logging.getLogger(__name__)

SAMPLE_RATE = 24000  # Both Kokoro and Piper output 24kHz
DEFAULT_VOICE = "af_heart"  # Warm professional female (American English)


class Synthesizer:
    def __init__(self) -> None:
        self._backend: str = "none"
        self._pipeline = None
        self._piper = None
        self._try_load_kokoro()
        if self._backend == "none":
            self._try_load_piper()

    def _try_load_kokoro(self) -> None:
        try:
            from kokoro import KPipeline
            self._pipeline = KPipeline(lang_code="a")  # American English
            self._backend = "kokoro"
            logger.info("TTS: Kokoro loaded")
        except ImportError:
            logger.info("Kokoro not available, trying Piper")
        except Exception as e:
            logger.warning(f"Kokoro load failed: {e}")

    def _try_load_piper(self) -> None:
        try:
            from piper import PiperVoice
            model_path = "/app/models/piper/en_US-lessac-medium.onnx"
            config_path = f"{model_path}.json"
            self._piper = PiperVoice.load(model_path, config_path=config_path)
            self._backend = "piper"
            logger.info("TTS: Piper loaded")
        except Exception as e:
            logger.warning(f"Piper load failed: {e}. TTS unavailable.")

    @property
    def available(self) -> bool:
        return self._backend != "none"

    def synthesize(self, text: str) -> bytes:
        """
        Synthesise text to PCM bytes synchronously.
        Use for short responses where latency matters less.
        """
        if not text.strip():
            return b""

        if self._backend == "kokoro":
            return self._kokoro_synthesize(text)
        elif self._backend == "piper":
            return self._piper_synthesize(text)
        return b""

    async def synthesize_streaming(self, text: str) -> AsyncGenerator[bytes, None]:
        """
        Yield PCM chunks as they're generated.
        First chunk available in ~100ms for Kokoro.
        """
        if not text.strip():
            return

        if self._backend == "kokoro":
            async for chunk in self._kokoro_stream(text):
                yield chunk
        elif self._backend == "piper":
            # Piper doesn't stream — yield all at once
            data = self._piper_synthesize(text)
            if data:
                yield data
        else:
            return

    def _kokoro_synthesize(self, text: str) -> bytes:
        chunks: list[bytes] = []
        for chunk in self._pipeline(text, voice=DEFAULT_VOICE, speed=1.0):
            if chunk.audio is not None:
                pcm = (chunk.audio * 32767).astype(np.int16).tobytes()
                chunks.append(pcm)
        return b"".join(chunks)

    async def _kokoro_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        for chunk in self._pipeline(text, voice=DEFAULT_VOICE, speed=1.0):
            if chunk.audio is not None and len(chunk.audio) > 0:
                pcm = (chunk.audio * 32767).astype(np.int16).tobytes()
                yield pcm
                await asyncio.sleep(0)  # Yield control to other coroutines

    def _piper_synthesize(self, text: str) -> bytes:
        import io
        import wave

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(22050)
            for audio_bytes in self._piper.synthesize_stream_raw(text):
                wf.writeframes(audio_bytes)
        return buf.getvalue()
