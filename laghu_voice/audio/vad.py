"""Silero VAD v5 through ONNX Runtime (design doc: Voice activity detection).

One model is loaded per process and shared; each call gets its own VadStream holding the recurrent state and
the 64-sample context that v5 expects in front of every 512-sample (32 ms) window. A window costs well under
a millisecond on CPU, so it runs inline on the event loop.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

SR = 16_000
WINDOW = 512          # 32 ms
CONTEXT = 64


class SileroVAD:
    def __init__(self, path: Path, threads: int = 1):
        import onnxruntime as ort

        if not Path(path).exists():
            raise FileNotFoundError(f"{path} not found: run python scripts/get_listen_models.py")
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        so.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(path), sess_options=so, providers=["CPUExecutionProvider"])
        self._sr = np.array(SR, dtype=np.int64)

    def stream(self) -> "VadStream":
        return VadStream(self)


class VadStream:
    def __init__(self, model: SileroVAD):
        self.model = model
        self.reset()

    def reset(self) -> None:
        self.state = np.zeros((2, 1, 128), np.float32)
        self.context = np.zeros(CONTEXT, np.float32)

    def prob(self, window: np.ndarray) -> float:
        """Speech probability of one 512-sample float32 window."""
        x = np.concatenate([self.context, window.astype(np.float32)])[None, :]
        out, self.state = self.model.session.run(None, {"input": x, "state": self.state, "sr": self.model._sr})
        self.context = x[0, -CONTEXT:]
        return float(out[0, 0])


class EnergyVAD:
    """Stand-in for tests and for running without the model: loudness above a threshold counts as speech."""

    def __init__(self, threshold_dbfs: float = -40.0):
        self.threshold = 10 ** (threshold_dbfs / 20)

    def stream(self) -> "EnergyVAD":
        return self

    def reset(self) -> None:
        pass

    def prob(self, window: np.ndarray) -> float:
        rms = float(np.sqrt(np.mean(np.square(window, dtype=np.float32)) + 1e-12))
        return 1.0 if rms > self.threshold else 0.0
