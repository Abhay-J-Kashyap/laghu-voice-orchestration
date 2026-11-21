"""Fixed lines are synthesised once, at startup (design doc: TTS cache).

The agent's fixed lines (greeting, questions, the filler) are cut into segments exactly as a session would cut
them, synthesised once, and kept as audio. When a session asks for one of those segments again it is played
from memory: no synthesis, first audio at once, and the same voice every time. Anything else (lines with the
caller's numbers in them) is synthesised as usual.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import AsyncIterator

import numpy as np

from ..text.segmenter import Segmenter
from .base import TTSResult

log = logging.getLogger(__name__)


class CachedTTS:
    def __init__(self, tts):
        self.tts = tts
        self.sample_rate = tts.sample_rate
        self.cache: dict[str, tuple[list[np.ndarray], str]] = {}
        self.hits = 0
        self.misses = 0

    async def prewarm(self, lines: list[str], first_clause: bool = False, trim: list[str] = ()) -> float:
        """Synthesise every segment of `lines`; returns the seconds it took. Segments of the lines in `trim`
        (the filler) lose their trailing silence: a filler that holds the floor longer than it speaks delays
        the reply queued behind it."""
        t0 = time.perf_counter()
        segments: list[str] = []
        for line in lines:
            seg = Segmenter(first_clause=first_clause)
            segments += seg.feed(line) + seg.flush()
        todo = [s for s in dict.fromkeys(segments) if s not in self.cache]
        for k, text in enumerate(todo):
            info = TTSResult()
            chunks = [c async for c in self.tts.stream(text, threading.Event(), info)]
            self.cache[text] = (chunks, info.model_text)
            if (k + 1) % 10 == 0:
                log.info("pre-rendered %d/%d fixed segments", k + 1, len(todo))
        for line in trim:
            seg = Segmenter(first_clause=first_clause)
            for text in seg.feed(line) + seg.flush():
                if text in self.cache:
                    chunks, model_text = self.cache[text]
                    self.cache[text] = ([trim_tail(np.concatenate(chunks), self.sample_rate)], model_text)
        return time.perf_counter() - t0

    async def stream(self, text: str, stop: threading.Event, info: TTSResult) -> AsyncIterator[np.ndarray]:
        hit = self.cache.get(text)
        if hit is None:
            self.misses += 1
            async for c in self.tts.stream(text, stop, info):
                yield c
            return
        self.hits += 1
        chunks, info.model_text = hit
        for c in chunks:
            if stop.is_set():
                return
            yield c
            await asyncio.sleep(0)


def trim_tail(x: np.ndarray, sample_rate: int, keep_ms: float = 120.0) -> np.ndarray:
    """Cut trailing silence, keeping `keep_ms` after the last 20 ms frame of speech. A synthesised clip's
    "silence" is low-level noise, so the floor is measured from the clip's own last 300 ms: speech is a frame
    10 dB above that floor (and within 40 dB of the loudest frame)."""
    frame = max(1, int(sample_rate * 0.02))
    n = len(x) // frame
    if n == 0:
        return x
    rms = np.sqrt(np.mean(x[:n * frame].reshape(n, frame).astype(np.float64) ** 2, axis=1))
    floor = float(np.median(rms[-max(1, int(0.3 / 0.02)):]))
    loud = np.flatnonzero(rms > max(floor * 10 ** (10 / 20), rms.max() * 0.01))
    if loud.size == 0:
        return x
    end = min(len(x), (loud[-1] + 1) * frame + int(sample_rate * keep_ms / 1000))
    return x[:end].astype(np.float32)
