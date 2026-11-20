"""LaghuTTS's thread-to-asyncio bridge and cancellation, against a fake runtime_onnx (no weights needed).

The fake mimics the real OnnxTTS interface: voice_state(name) and a blocking generate_audio_stream that checks
`stop` between chunks. test_laghu_real at the bottom runs the real model when its weights are present.
"""
import asyncio
import textwrap
import threading
import time

import numpy as np
import pytest

from laghu_voice.config import Settings
from laghu_voice.services.base import TTSResult
from laghu_voice.services.tts_laghu import LaghuTTS
from laghu_voice.text.prep import Prepared

FAKE_RUNTIME = textwrap.dedent('''
    import time, numpy as np
    CALLS = []
    class OnnxTTS:
        def __init__(self, model_dir, lm_threads=1, decoder_threads=1):
            self.model_dir = model_dir
        def voice_state(self, voice):
            return ("voice", voice)
        def generate_audio_stream(self, voice_state, text, cfg=2.0, stop=None, normalize=True, **kw):
            CALLS.append({"text": text, "normalize": normalize, "cfg": cfg})
            for i in range(50):
                if stop is not None and stop.is_set():
                    return
                time.sleep(0.01)
                yield np.full(1920, 0.01 * (i + 1), np.float32)
''')


@pytest.fixture
def fake_laghu(tmp_path, monkeypatch):
    (tmp_path / "model").mkdir()
    (tmp_path / "model" / "meta.json").write_text("{}")
    (tmp_path / "runtime_onnx.py").write_text(FAKE_RUNTIME)
    monkeypatch.syspath_prepend(str(tmp_path))
    import importlib
    import sys
    sys.modules.pop("runtime_onnx", None)
    mod = importlib.import_module("runtime_onnx")
    tts = LaghuTTS(tmp_path, prep=lambda t: Prepared(model_text=f"[{t}]"))
    yield tts, mod
    sys.modules.pop("runtime_onnx", None)


async def test_chunks_arrive_in_order_and_text_is_prepared_once(fake_laghu):
    tts, mod = fake_laghu
    info = TTSResult()
    chunks = [c async for c in tts.stream("नमस्ते", threading.Event(), info)]
    assert len(chunks) == 50 and np.allclose([c[0] for c in chunks], 0.01 * np.arange(1, 51))
    assert mod.CALLS[-1] == {"text": "[नमस्ते]", "normalize": False, "cfg": 2.0}
    assert info.model_text == "[नमस्ते]"


async def test_stop_event_ends_the_stream_quickly(fake_laghu):
    tts, _ = fake_laghu
    stop = threading.Event()
    got = []
    t0 = time.perf_counter()
    async for c in tts.stream("x", stop, TTSResult()):
        got.append(c)
        if len(got) == 3:
            stop.set()
    assert len(got) <= 5
    assert time.perf_counter() - t0 < 0.3


async def test_leaving_early_stops_the_model_thread(fake_laghu):
    tts, _ = fake_laghu
    stop = threading.Event()
    gen = tts.stream("x", stop, TTSResult())
    await gen.__anext__()
    await gen.aclose()
    assert stop.is_set()


async def test_stop_set_by_someone_else_while_waiting_does_not_hang(fake_laghu):
    """The session sets `stop` on barge-in while the TTS worker is waiting for the next chunk."""
    tts, _ = fake_laghu
    stop = threading.Event()
    gen = tts.stream("x", stop, TTSResult())
    await gen.__anext__()                    # the stream is running; no sleep-based timing (Windows timers are coarse)

    async def rest():
        return [c async for c in gen]

    task = asyncio.create_task(rest())
    await asyncio.sleep(0)                   # let the consumer start waiting for the next chunk
    stop.set()
    got = await asyncio.wait_for(task, timeout=1.0)   # the point of the test: this must not hang
    assert len(got) <= 2                     # at most what was already queued; the fake makes 50 chunks


def test_missing_weights_gives_download_instructions(tmp_path):
    with pytest.raises(FileNotFoundError, match="get_laghu.py"):
        LaghuTTS(tmp_path)


REAL_DIR = Settings().laghu_dir


@pytest.mark.skipif(not (REAL_DIR / "model" / "meta.json").exists(),
                    reason="run scripts/get_laghu.py first to test the real model")
async def test_laghu_real():
    tts = LaghuTTS(REAL_DIR)
    info = TTSResult()
    t0 = time.perf_counter()
    first = None
    total = 0
    async for c in tts.stream("आपका loan approve हो गया है।", threading.Event(), info):
        first = first or time.perf_counter() - t0
        total += len(c)
    assert info.model_text == "आपका लोन अप्रूव हो गया है."
    assert total > 24000 * 0.5 and first < 1.0
    print(f"real Laghu: first audio {first * 1000:.0f} ms, {total / 24000:.2f} s of audio")
