"""Laghu TTS 7M Hindi as a streaming service (design doc: Laghu streaming).

Wraps `runtime_onnx.OnnxTTS` from the Laghu repo without changing it:
- The model and the voice state are loaded once per process and shared by every session. ONNX Runtime
  sessions are safe to call from several threads, and generate_audio_stream keeps its own state per call.
- generate_audio_stream is a blocking generator that runs its own two threads (transformer and decoder).
  It is iterated in a worker thread, and each chunk is handed to the event loop as soon as it's decoded.
- Cancellation uses the `stop` event the runtime already checks between frames and between chunks.
- Text goes through TextPrep (Laghu's frontend plus the banking fixes) and is then passed with
  normalize=False, so it isn't normalized twice.
"""
from __future__ import annotations

import asyncio
import sys
import threading
from collections.abc import AsyncIterator
from pathlib import Path

import numpy as np

from ..text.prep import TextPrep
from .base import TTSResult

_DONE = object()


class LaghuTTS:
    sample_rate = 24_000

    def __init__(self, laghu_dir: Path, voice: str = "female", cfg: float = 2.0,
                 lm_threads: int = 1, decoder_threads: int = 1, prep: TextPrep | None = None):
        laghu_dir = Path(laghu_dir).resolve()
        model_dir = laghu_dir / "model"
        if not (model_dir / "meta.json").exists() or not (laghu_dir / "runtime_onnx.py").exists():
            raise FileNotFoundError(
                f"Laghu isn't in {laghu_dir}. Download it from Hugging Face with:\n"
                f"  python scripts/get_laghu.py")
        if str(laghu_dir) not in sys.path:
            sys.path.insert(0, str(laghu_dir))
        from runtime_onnx import OnnxTTS

        self.tts = OnnxTTS(model_dir, lm_threads=lm_threads, decoder_threads=decoder_threads)
        self.voice = self.tts.voice_state(voice)
        self.cfg = cfg
        self.prep = prep or TextPrep(laghu_dir)

    async def stream(self, text: str, stop: threading.Event, info: TTSResult) -> AsyncIterator[np.ndarray]:
        p = self.prep(text)
        info.model_text, info.dropped_words = p.model_text, p.dropped_words
        if not p.model_text.strip(" ."):
            return
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()

        def post(item) -> bool:
            """Hand an item to the event loop. False if the loop is closed (server shutting down)."""
            try:
                loop.call_soon_threadsafe(q.put_nowait, item)
                return True
            except RuntimeError:
                return False

        def work() -> None:
            try:
                for chunk in self.tts.generate_audio_stream(self.voice, p.model_text, cfg=self.cfg,
                                                            stop=stop, normalize=False):
                    if stop.is_set() or not post(chunk):
                        break               # cancelled: no more chunks, but still post the end marker
                post(_DONE)
            except Exception as e:  # noqa: BLE001 - surfaced to the caller below
                post(e)

        threading.Thread(target=work, name="laghu-tts", daemon=True).start()
        try:
            while True:
                try:
                    item = await asyncio.wait_for(q.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    if stop.is_set():
                        return              # cancelled and the model is slow to wind down: don't wait for it
                    continue
                if item is _DONE or stop.is_set():
                    return
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            stop.set()   # the consumer left early (barge-in or error): stop the model threads too
