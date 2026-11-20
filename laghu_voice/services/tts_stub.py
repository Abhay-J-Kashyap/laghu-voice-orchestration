"""A stand-in TTS with fixed, configurable timing: a quiet tone whose length depends on the text.

Used by the tests and the load generator, and to run the whole system without Laghu's weights. Its timing
defaults are Laghu's measured numbers (26 ms to first audio, 11.3x real time on 2 cores).
"""
from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator

import numpy as np

from ..frames import FRAME_SAMPLES_OUT, SAMPLE_RATE_OUT
from .base import TTSResult


class StubTTS:
    sample_rate = SAMPLE_RATE_OUT

    def __init__(self, first_audio_ms: float = 26.0, rtf: float = 11.3, ms_per_char: float = 70.0,
                 freq_hz: float = 220.0):
        self.first_audio_ms = first_audio_ms
        self.rtf = rtf
        self.ms_per_char = ms_per_char
        self.freq_hz = freq_hz

    async def stream(self, text: str, stop: threading.Event, info: TTSResult) -> AsyncIterator[np.ndarray]:
        info.model_text = text
        total = max(1, int(len(text) * self.ms_per_char / 1000 * self.sample_rate / FRAME_SAMPLES_OUT))
        await asyncio.sleep(self.first_audio_ms / 1000)
        t = np.arange(FRAME_SAMPLES_OUT) / self.sample_rate
        for k in range(total):
            if stop.is_set():
                return
            phase = 2 * np.pi * self.freq_hz * (t + k * FRAME_SAMPLES_OUT / self.sample_rate)
            yield (0.1 * np.sin(phase)).astype(np.float32)
            await asyncio.sleep(FRAME_SAMPLES_OUT / self.sample_rate / self.rtf)
