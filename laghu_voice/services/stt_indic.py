"""Speech to text: AI4Bharat's Hindi IndicConformer 120M, CTC, ONNX fp32 (Milestone 0, Amendment 7).

The ONNX export is OpenVoiceOS/ai4bharat-indicconformer-hi-onnx, run through the onnx-asr library. One model
per process, shared by every call. Decodes run one at a time in a single worker thread: ONNX Runtime releases
the GIL, so the event loop keeps running, and a fixed thread budget (4 by default) keeps STT from starving
Laghu and the turn model. scripts/get_listen_models.py puts the files in vendor/stt_hi120m.
"""
from __future__ import annotations

import asyncio
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

REPO = "OpenVoiceOS/ai4bharat-indicconformer-hi-onnx"


def clean_ctc(h: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", "", h)).strip()


class STTBase:
    """transcribe() runs in the STT worker thread; decode() is the async entry point."""

    def __init__(self):
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stt")

    def transcribe(self, audio: np.ndarray) -> str:
        raise NotImplementedError

    async def decode(self, audio: np.ndarray) -> tuple[str, float]:
        """(text, decode milliseconds). Waiting in the worker's queue is not counted as decode time."""
        def run():
            t0 = time.perf_counter()
            text = self.transcribe(audio)
            return text, 1000 * (time.perf_counter() - t0)
        return await asyncio.get_running_loop().run_in_executor(self._pool, run)

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


class IndicConformerSTT(STTBase):
    """pad_s: silence added before and after every segment. This export misreads audio that starts or stops
    right at the speech (Milestone 2, Amendment 3: CER 16.6% without, 3.9% with 0.25 s on each side)."""

    def __init__(self, path: Path, threads: int = 4, pad_s: float = 0.25):
        super().__init__()
        self.pad = np.zeros(int(pad_s * 16000), np.float32)
        import onnx_asr
        import onnxruntime as ort

        if not Path(path, "model.onnx").exists():
            raise FileNotFoundError(f"{path} has no model.onnx: run python scripts/get_listen_models.py")
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        self.model = onnx_asr.load_model(REPO, str(path), sess_options=so)
        self.transcribe(np.zeros(16000, np.float32))   # warm-up, so the first caller doesn't pay for it

    def transcribe(self, audio: np.ndarray) -> str:
        if len(audio) < 1600:          # under 0.1 s: nothing to decode
            return ""
        x = np.concatenate([self.pad, np.asarray(audio, dtype=np.float32), self.pad])
        out = self.model.recognize(x, sample_rate=16000)
        return clean_ctc(out if isinstance(out, str) else getattr(out, "text", str(out)))


class StubSTT(STTBase):
    """For tests and for running without the model: returns a fixed text after a delay proportional to length."""

    def __init__(self, text: str = "हाँ जी", ms_per_second: float = 75.0):
        super().__init__()
        self.text = text
        self.ms_per_second = ms_per_second
        self.calls: list[float] = []

    def transcribe(self, audio: np.ndarray) -> str:
        seconds = len(audio) / 16000
        self.calls.append(seconds)
        time.sleep(seconds * self.ms_per_second / 1000)
        return self.text if seconds >= 0.1 else ""
