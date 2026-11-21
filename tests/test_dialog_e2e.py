"""Milestone 4 over a real WebSocket: the agent greets, takes a spoken turn and typed turns, says the filler when
the LLM is slow, hands over on request, and ends the call."""
import asyncio
import json
from pathlib import Path

import numpy as np
from fake_backend import OTP, FakeBackend
from test_agent import RAJESH_NAME, Scripted
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from laghu_voice.audio.vad import EnergyVAD
from laghu_voice.config import Settings
from laghu_voice.dialog import hindi
from laghu_voice.dialog.backend import BackendClient
from laghu_voice.dialog.spec import load_spec
from laghu_voice.orchestrator.listener import ListenModels
from laghu_voice.services.stt_indic import StubSTT
from laghu_voice.services.tts_cache import CachedTTS
from laghu_voice.services.tts_stub import StubTTS
from laghu_voice.transport.ws_server import DialogDeps, make_handler

SR = 16000
SPEC = load_spec(Path(__file__).resolve().parents[1] / "agents" / "loan_onboarding.yaml")


def pcm(x):
    return (np.clip(x, -1, 1) * 32767).astype("<i2").tobytes()


def speech(ms):
    t = np.arange(int(SR * ms / 1000)) / SR
    return 0.3 * np.sin(2 * np.pi * 220 * t)


class Call:
    def __init__(self, ws):
        self.ws = ws
        self.events: list[dict] = []
        self.closed = asyncio.Event()

    async def recv(self):
        try:
            async for m in self.ws:
                if isinstance(m, str):
                    self.events.append(json.loads(m))
        finally:
            self.closed.set()

    async def wait(self, pred, timeout=10.0):
        for _ in range(int(timeout / 0.02)):
            if any(pred(e) for e in self.events):
                return
            await asyncio.sleep(0.02)
        raise AssertionError(f"timed out; last events: {self.events[-5:]}")

    async def idle(self):
        """Wait until the agent's last reply has been fully sent and played."""
        n = sum(1 for e in self.events if e["type"] == "dialog" and "state" in e)
        await self.wait(lambda e: e["type"] == "turn_trace") if n else None
        await asyncio.sleep(0.5)

    async def type(self, text):
        n = sum(1 for e in self.events if e["type"] == "dialog" and "state" in e)
        await self.ws.send(json.dumps({"type": "text", "text": text}))
        for _ in range(500):
            if sum(1 for e in self.events if e["type"] == "dialog" and "state" in e) > n:
                break
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.6)


def server(tmp_path, llm, tts=None):
    settings = Settings()
    settings.trace_dir = tmp_path
    settings.dialog = "agent"
    fb = FakeBackend()
    deps = DialogDeps(SPEC, BackendClient("http://fake", "k", transport=fb.transport()), llm)
    listen = ListenModels(EnergyVAD(), StubSTT("हाँ जी", ms_per_second=20), None)
    tts = tts or StubTTS(first_audio_ms=2, rtf=200, ms_per_char=2)
    return serve(make_handler(tts, settings, listen=listen, dialog=deps), "127.0.0.1", 0), fb


async def test_a_call_from_greeting_to_hand_over(tmp_path):
    srv_cm, fb = server(tmp_path, Scripted(RAJESH_NAME))
    async with srv_cm as srv:
        async with connect(f"ws://127.0.0.1:{srv.sockets[0].getsockname()[1]}") as ws:
            c = Call(ws)
            r = asyncio.create_task(c.recv())
            await c.wait(lambda e: e["type"] == "segment_start")
            assert c.events[0]["dialog"] == "agent"
            assert next(e for e in c.events if e["type"] == "segment_start")["text"].startswith("मैं लघु")
            await c.idle()
            # a spoken "हाँ जी" (the stub STT) answers the greeting
            x = np.concatenate([np.zeros(3200), speech(700), np.zeros(SR)])
            for i in range(0, len(x), 320):
                await ws.send(pcm(x[i:i + 320]))
                await asyncio.sleep(0.005)
            await c.wait(lambda e: e["type"] == "dialog" and e.get("state") == "ask_name")
            await c.idle()
            for line in ["मेरा नाम राजेश कुमार है", "बारह अप्रैल उन्नीस सौ अठासी", "ए बी सी डी ई एक दो तीन चार एफ़", "हाँ"]:
                await c.type(line)
            await c.wait(lambda e: e["type"] == "dialog" and (e.get("show") or {}).get("demo_otp") == OTP)
            await c.type(hindi.digits_words(OTP))
            await c.type("मुझे किसी इंसान से बात करनी है")
            await c.wait(lambda e: e["type"] == "end_call")
            await asyncio.wait_for(c.closed.wait(), 5)
            r.cancel()
    end = next(e for e in c.events if e["type"] == "end_call")
    assert end["reason"] == "transferred"
    s = next(iter(fb.sessions.values()))
    assert s["tools"] == ["verify_identity", "verify_otp", "escalate"]
    said = [e["text"] for e in c.events if e["type"] == "segment_start"]
    assert said[-1] == "कृपया लाइन पर बने रहिए।"
    records = [json.loads(x) for x in (tmp_path / f"{c.events[0]['session_id']}.jsonl").read_text("utf-8").splitlines()]
    dialog = [r for r in records if r.get("kind") == "dialog"]
    assert dialog and dialog[1]["user_turn_id"] == "u1" and "user_turn_end" in dialog[1]["ms"]
    assert all("reply_ready" in r["ms"] for r in dialog)


async def test_slow_llm_gets_the_filler_first(tmp_path):
    srv_cm, _ = server(tmp_path, Scripted(RAJESH_NAME, delay=0.8))
    async with srv_cm as srv:
        async with connect(f"ws://127.0.0.1:{srv.sockets[0].getsockname()[1]}") as ws:
            c = Call(ws)
            r = asyncio.create_task(c.recv())
            await c.wait(lambda e: e["type"] == "segment_start")
            await c.idle()
            await c.type("हाँ")
            await c.wait(lambda e: e["type"] == "dialog" and e.get("state") == "ask_name")
            await asyncio.sleep(0.3)
            r.cancel()
    said = [e["text"] for e in c.events if e["type"] == "segment_start"]
    k = said.index("जी, एक पल।")
    assert said[k + 1] == "ठीक है।"                         # the reply's first sentence comes after the filler
    step = next(e for e in c.events if e["type"] == "dialog" and e.get("state") == "ask_name")
    assert step["filler"] and step["path"] == "rule"        # understood by rule; writing the reply was slow


async def test_fixed_lines_play_from_the_cache():
    tts = CachedTTS(StubTTS(first_audio_ms=2, rtf=200, ms_per_char=2))
    await tts.prewarm(SPEC.fixed_lines())
    import threading

    from laghu_voice.services.base import TTSResult
    chunks = [c async for c in tts.stream("जी, एक पल।", threading.Event(), TTSResult())]
    assert chunks and tts.hits == 1 and tts.misses == 0
