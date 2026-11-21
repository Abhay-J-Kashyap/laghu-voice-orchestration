"""Smart Turn v3.2 end-of-turn model through ONNX Runtime (design doc: Turn detection).

Smart Turn looks at the last 8 s of the caller's audio (not the words) and returns the probability that the
caller has finished their turn. Hindi is one of its 23 languages. Input preparation follows the authors'
inference code: keep the last 8 s, pad shorter audio with zeros at the front, normalise the waveform, then
Whisper log-mel features (laghu_voice/audio/mel.py). The int8 CPU export is about 8 MB.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .mel import SR, log_mel, normalize

WINDOW_S = 8
N = WINDOW_S * SR


def prepare(audio: np.ndarray) -> np.ndarray:
    """(1, 80, 800) features for the last 8 s of `audio` (float32, 16 kHz)."""
    x = np.asarray(audio, dtype=np.float32)[-N:]
    if len(x) < N:
        x = np.concatenate([np.zeros(N - len(x), np.float32), x])
    return log_mel(normalize(x))[None]


class SmartTurn:
    def __init__(self, path: Path, threads: int = 1, threshold: float = 0.5):
        import onnxruntime as ort

        if not Path(path).exists():
            raise FileNotFoundError(f"{path} not found: run python scripts/get_listen_models.py")
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        so.inter_op_num_threads = 1
        so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(str(path), sess_options=so, providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        self.threshold = threshold

    def probability(self, audio: np.ndarray) -> float:
        out = self.session.run(None, {self.input_name: prepare(audio)})
        return float(np.asarray(out[0]).reshape(-1)[0])
