"""The automated caller of Milestone 4 part B (m4/auto_calls.py), over a real WebSocket against the full server
loop: a tone stands in for the caller's voice, and the stub STT returns the line the caller is saying."""
import asyncio
import importlib.util
from pathlib import Path

import numpy as np
from fake_backend import FakeBackend
from test_agent import RAJESH_NAME, Scripted
from websockets.asyncio.server import serve

from laghu_voice.audio.vad import EnergyVAD
from laghu_voice.config import Settings
from laghu_voice.dialog.backend import BackendClient
from laghu_voice.dialog.llm import DialogLLM  # noqa: F401  (the handler builds it)
from laghu_voice.dialog.spec import load_spec
from laghu_voice.orchestrator.listener import ListenModels
from laghu_voice.services.stt_indic import STTBase
from laghu_voice.services.tts_stub import StubTTS
from laghu_voice.transport.ws_server import DialogDeps, make_handler

ROOT = Path(__file__).resolve().parents[1]
_s = importlib.util.spec_from_file_location("auto_calls", ROOT / "m4" / "auto_calls.py")
auto = importlib.util.module_from_spec(_s)
_s.loader.exec_module(auto)


class LineSTT(STTBase):
    """Whatever the caller is saying right now."""
    def __init__(self):
        super().__init__()
        self.line = ""

    def transcribe(self, audio):
        return self.line if len(audio) >= 1600 else ""


class ToneVoice:
    async def say(self, text):
        t = np.arange(int(16000 * min(2.0, 0.3 + 0.02 * len(text)))) / 16000
        return (0.3 * 32767 * np.sin(2 * np.pi * 220 * t)).astype(np.int16)


async def test_the_automated_caller_completes_l1(tmp_path):
    settings = Settings()
    settings.trace_dir = tmp_path
    settings.dialog = "agent"
    fb = FakeBackend()
    stt = LineSTT()
    spec = load_spec(ROOT / "agents" / "loan_onboarding.yaml")
    deps = DialogDeps(spec, BackendClient("http://fake", "k", transport=fb.transport()), Scripted(RAJESH_NAME))
    handler = make_handler(StubTTS(first_audio_ms=2, rtf=50, ms_per_char=8), settings,
                           listen=ListenModels(EnergyVAD(), stt, None), dialog=deps)
    log = []

    def heard(text):
        stt.line = text
    async with serve(handler, "127.0.0.1", 0) as srv:
        url = f"ws://127.0.0.1:{srv.sockets[0].getsockname()[1]}"
        st = await asyncio.wait_for(auto.call(url, auto.SCRIPTS["L1"], ToneVoice(), log, on_line=heard), 120)
    assert st["end"] == "completed", "\n".join(log)
    s = next(iter(fb.sessions.values()))
    assert s["state"] == "completed" and s["consents"] == [True]
    assert st["said"] == 11                   # one answer per question: nothing was asked twice
