"""Whisper log-mel features in NumPy, for Smart Turn (design doc: Turn detection).

Smart Turn v3 was trained on HuggingFace's WhisperFeatureExtractor(chunk_length=8). This reproduces it without
transformers: 16 kHz, periodic Hann window of 400, hop 160, reflect padding, 80 Slaney mel bins from 0 to
8 kHz, power spectrum, log10 floored at 1e-10, clamped to (max - 8), then (x + 4) / 4. The last STFT frame
is dropped, so 8 s gives 800 frames. tests/test_mel.py checks it against transformers when that is installed.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np

SR = 16_000
N_FFT = 400
HOP = 160
N_MELS = 80


def _hz_to_mel(f):
    f = np.asarray(f, dtype=np.float64)
    min_log_hz, min_log_mel, logstep = 1000.0, 15.0, np.log(6.4) / 27.0
    mel = 3.0 * f / 200.0
    return np.where(f >= min_log_hz, min_log_mel + np.log(np.maximum(f, 1e-10) / min_log_hz) / logstep, mel)


def _mel_to_hz(m):
    m = np.asarray(m, dtype=np.float64)
    min_log_hz, min_log_mel, logstep = 1000.0, 15.0, np.log(6.4) / 27.0
    f = 200.0 * m / 3.0
    return np.where(m >= min_log_mel, min_log_hz * np.exp(logstep * (m - min_log_mel)), f)


@lru_cache(maxsize=1)
def mel_filters() -> np.ndarray:
    """(N_MELS, N_FFT // 2 + 1) Slaney-scale, Slaney-normalised triangular filters (as librosa / Whisper)."""
    fft_freqs = np.linspace(0, SR / 2, N_FFT // 2 + 1)
    mel_pts = np.linspace(_hz_to_mel(0.0), _hz_to_mel(SR / 2), N_MELS + 2)
    hz_pts = _mel_to_hz(mel_pts)
    fdiff = np.diff(hz_pts)
    ramps = hz_pts[:, None] - fft_freqs[None, :]
    lower = -ramps[:-2] / fdiff[:-1, None]
    upper = ramps[2:] / fdiff[1:, None]
    w = np.maximum(0, np.minimum(lower, upper))
    w *= (2.0 / (hz_pts[2:] - hz_pts[:-2]))[:, None]
    return w.astype(np.float32)


@lru_cache(maxsize=1)
def _window() -> np.ndarray:
    n = np.arange(N_FFT)
    return (0.5 - 0.5 * np.cos(2 * np.pi * n / N_FFT)).astype(np.float32)   # periodic Hann


def log_mel(x: np.ndarray) -> np.ndarray:
    """x: float32 mono 16 kHz. Returns (80, len(x) // 160) log-mel features scaled as Whisper's."""
    x = np.asarray(x, dtype=np.float32)
    p = np.pad(x, N_FFT // 2, mode="reflect")
    n_frames = 1 + (len(p) - N_FFT) // HOP
    idx = np.arange(N_FFT)[None, :] + HOP * np.arange(n_frames)[:, None]
    spec = np.fft.rfft(p[idx] * _window(), axis=1)
    power = (spec.real ** 2 + spec.imag ** 2).astype(np.float32)[:-1]     # drop the last frame
    mel = mel_filters() @ power.T
    logm = np.log10(np.maximum(mel, 1e-10))
    logm = np.maximum(logm, logm.max() - 8.0)
    return ((logm + 4.0) / 4.0).astype(np.float32)


def normalize(x: np.ndarray) -> np.ndarray:
    """Zero mean, unit variance, as WhisperFeatureExtractor(do_normalize=True) does to the waveform."""
    x = np.asarray(x, dtype=np.float32)
    return (x - x.mean()) / np.sqrt(x.var() + 1e-7)
