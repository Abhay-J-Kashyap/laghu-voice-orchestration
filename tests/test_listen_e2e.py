"""Milestone 2 over a real WebSocket: mic audio in, a user turn out, the echo reply spoken back, mic gated."""
import asyncio
import json

import numpy as np
import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from laghu_voice.audio.vad import EnergyVAD
from laghu_voice.config import Settings
from laghu_voice.orchestrator.listener import ListenModels
from laghu_voice.services.stt_indic import StubSTT
from laghu_voice.services.tts_stub import StubTTS
from laghu_voice.transport.ws_server import make_handler

SR = 16000


def pcm(x):
    return (np.clip(x, -1, 1) * 32767).astype("<i2").tobytes()


def speech(ms):
    t = np.arange(int(SR * ms / 1000)) / SR
    return 0.3 * np.sin(2 * np.pi * 220 * t)


@pytest.fixture
async def server(tmp_path):
    settings = Settings()
    settings.trace_dir = tmp_path
    listen = ListenModels(EnergyVAD(), StubSTT("हाँ जी", ms_per_second=50), None)
    async with serve(make_handler(StubTTS(first_audio_ms=5, rtf=50, ms_per_char=20), settings, listen=listen),
                     "127.0.0.1", 0) as srv:
        yield f"ws://127.0.0.1:{srv.sockets[0].getsockname()[1]}", tmp_path


async def stream(ws, x, speed=4.0):
    """Send audio in 20 ms frames, `speed` times faster than real time."""
    for i in range(0, len(x), 320):
        await ws.send(pcm(x[i:i + 320]))
        await asyncio.sleep(0.02 / speed)


async def test_spoken_turn_is_transcribed_and_echoed(server):
    url, trace_dir = server
    events = []
    async with connect(url) as ws:
        async def recv():
            async for m in ws:
                if isinstance(m, str):
                    events.append(json.loads(m))
        r = asyncio.create_task(recv())
        await stream(ws, np.concatenate([np.zeros(3200), speech(800), np.zeros(SR * 1)]))
        for _ in range(100):
            if any(e["type"] == "segment_start" for e in events):
                break
            await asyncio.sleep(0.05)
        # while the reply plays, the mic is closed: this speech must not start a second turn
        await stream(ws, np.concatenate([speech(600), np.zeros(SR)]))
        await asyncio.sleep(0.3)
        r.cancel()
    turns = [e for e in events if e["type"] == "user_turn"]
    assert len(turns) == 1 and turns[0]["text"] == "हाँ जी"
    assert turns[0]["trace"]["end_reason"] == "silence_only"
    assert "speech_end_to_transcript" in turns[0]["trace"]["latency_ms"]
    said = [e["text"] for e in events if e["type"] == "segment_start"]
    assert said and said[0].startswith("मैंने सुना")
    assert [e["speech"] for e in events if e["type"] == "vad"][0] is True
    lines = (trace_dir / f"{events[0]['session_id']}.jsonl").read_text(encoding="utf-8").splitlines()
    assert any(json.loads(l).get("kind") == "user" for l in lines)
