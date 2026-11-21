"""The listening models: mel features against transformers, and the real models when vendor/ has them."""
from pathlib import Path

import numpy as np
import pytest

from laghu_voice.audio.mel import log_mel, normalize
from laghu_voice.audio.turn import N, prepare

VENDOR = Path(__file__).resolve().parents[1] / "vendor"


def test_mel_matches_whisper_feature_extractor():
    tr = pytest.importorskip("transformers")
    rng = np.random.default_rng(0)
    t = np.arange(48000) / 16000
    x = (0.2 * np.sin(2 * np.pi * 300 * t) * (1 + np.sin(2 * np.pi * 3 * t)) + 0.01 * rng.standard_normal(48000))
    x = np.concatenate([np.zeros(N - 48000), x]).astype(np.float32)
    fe = tr.WhisperFeatureExtractor(chunk_length=8)
    ref = fe(x, sampling_rate=16000, return_tensors="np", padding="max_length", max_length=N, truncation=True,
             do_normalize=True).input_features[0]
    assert np.abs(ref - log_mel(normalize(x))).max() < 1e-4


def test_turn_input_keeps_the_last_8_seconds_right_aligned():
    short = np.ones(16000, np.float32)
    f = prepare(short)
    assert f.shape == (1, 80, 800)
    long = np.concatenate([np.zeros(16000 * 5, np.float32), np.ones(16000 * 8, np.float32)])
    assert np.allclose(prepare(long), prepare(np.ones(16000 * 8, np.float32)))


@pytest.mark.skipif(not (VENDOR / "silero" / "silero_vad.onnx").exists(), reason="run scripts/get_listen_models.py")
def test_silero_hears_no_speech_in_silence():
    from laghu_voice.audio.vad import SileroVAD
    v = SileroVAD(VENDOR / "silero" / "silero_vad.onnx").stream()
    probs = [v.prob(np.zeros(512, np.float32)) for _ in range(20)]
    assert max(probs) < 0.2


@pytest.mark.skipif(not (VENDOR / "smart_turn" / "smart-turn-v3.2-cpu.onnx").exists(),
                    reason="run scripts/get_listen_models.py")
def test_smart_turn_returns_a_probability():
    from laghu_voice.audio.turn import SmartTurn
    m = SmartTurn(VENDOR / "smart_turn" / "smart-turn-v3.2-cpu.onnx")
    p = m.probability(0.05 * np.random.default_rng(0).standard_normal(16000 * 3).astype(np.float32))
    assert 0.0 <= p <= 1.0


@pytest.mark.skipif(not (VENDOR / "stt_hi120m" / "model.onnx").exists(), reason="run scripts/get_listen_models.py")
async def test_stt_decodes_a_second_of_silence():
    pytest.importorskip("onnx_asr")
    from laghu_voice.services.stt_indic import IndicConformerSTT
    stt = IndicConformerSTT(VENDOR / "stt_hi120m")
    text, ms = await stt.decode(np.zeros(16000, np.float32))
    assert isinstance(text, str) and len(text) < 20 and ms >= 0
    stt.close()
