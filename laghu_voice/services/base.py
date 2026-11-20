"""Interfaces every model service implements, so swapping a model is a config change (design doc: components)."""
from __future__ import annotations

import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np


@dataclass
class TTSResult:
    """Filled in by the service while it streams; read by the session for the trace."""
    model_text: str = ""
    dropped_words: list[str] = field(default_factory=list)


class TTSService(Protocol):
    sample_rate: int

    def stream(self, text: str, stop: threading.Event, info: TTSResult) -> AsyncIterator[np.ndarray]:
        """Yield float32 mono chunks at `sample_rate` as soon as each is decoded. Must stop promptly once
        `stop` is set (the session sets it on barge-in)."""
        ...


class LLMService(Protocol):
    def stream(self, messages: list[dict], **kw) -> AsyncIterator[str]:
        """Yield text deltas of the assistant reply. Reasoning text, if any, is not yielded."""
        ...


def float_to_pcm16(x: np.ndarray) -> bytes:
    return (np.clip(x, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
