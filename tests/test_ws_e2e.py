"""Server and a scripted client over a real WebSocket, with the stub TTS."""
import asyncio
import json

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from laghu_voice.config import Settings
from laghu_voice.frames import unpack_audio
from laghu_voice.services.tts_stub import StubTTS
from laghu_voice.transport.ws_server import make_handler


@pytest.fixture
async def server(tmp_path):
    settings = Settings()
    settings.trace_dir = tmp_path
    async with serve(make_handler(StubTTS(first_audio_ms=5, rtf=50, ms_per_char=80), settings),
                     "127.0.0.1", 0) as srv:
        port = srv.sockets[0].getsockname()[1]
        yield f"ws://127.0.0.1:{port}", tmp_path


async def collect(ws, until, timeout=5.0):
    audio, events = [], []
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not until(audio, events):
        msg = await asyncio.wait_for(ws.recv(), end - loop.time())
        t = loop.time()
        if isinstance(msg, bytes):
            audio.append((t, *unpack_audio(msg)))
        else:
            events.append((t, json.loads(msg)))
    return audio, events


async def test_say_then_barge_in_over_websocket(server):
    url, trace_dir = server
    async with connect(url) as ws:
        ready = json.loads(await ws.recv())
        assert ready["type"] == "ready" and ready["sample_rate"] == 24000
        await ws.send(json.dumps({"type": "say", "text": "यह एक लंबा जवाब है जो रोका जाएगा। " * 3}))
        audio, events = await collect(ws, lambda a, e: len(a) >= 4)
        assert all(epoch == 0 for _, epoch, _, _ in audio)
        assert events[0][1]["type"] == "segment_start"
        await ws.send(json.dumps({"type": "playback", "segment_id": audio[0][2], "samples": 3840}))
        await ws.send(json.dumps({"type": "interrupt", "reason": "test"}))
        audio2, events2 = await collect(ws, lambda a, e: any(ev["type"] == "turn_trace" for _, ev in e))
        flush = next(ev for _, ev in events2 if ev["type"] == "flush")
        t_flush = next(t for t, ev in events2 if ev["type"] == "flush")
        assert flush["epoch"] == 1
        assert not [a for a in audio2 if a[0] > t_flush], "audio arrived after the flush"
        trace = next(ev["trace"] for _, ev in events2 if ev["type"] == "turn_trace")
        assert trace["outcome"] == "interrupted"
        assert trace["segments"][0]["samples_played"] == 3840
        await ws.send(json.dumps({"type": "hangup"}))
    lines = (trace_dir / f"{ready['session_id']}.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["outcome"] == "interrupted"


async def test_bad_message_gets_an_error_not_a_disconnect(server):
    url, _ = server
    async with connect(url) as ws:
        await ws.recv()
        await ws.send("not json")
        ev = json.loads(await ws.recv())
        assert ev["type"] == "error"
        await ws.send(json.dumps({"type": "say", "text": "ठीक है।"}))
        _, events = await collect(ws, lambda a, e: any(ev["type"] == "turn_trace" for _, ev in e))
        assert next(ev for _, ev in events if ev["type"] == "turn_trace")["trace"]["outcome"] == "completed"
