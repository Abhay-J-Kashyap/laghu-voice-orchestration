"""WebSocket transport (design doc: Transport, audio formats and client).

Client -> server, JSON text frames:
    {"type": "say", "text": "..."}                      speak this text (Milestone 1 stands in for the dialog)
    {"type": "interrupt", "reason": "..."}              barge-in (Milestone 3 moves this server-side, from VAD)
    {"type": "playback", "segment_id": 3, "samples": 4800}   how much of a segment the speaker has played
    {"type": "hangup"}
Client -> server, binary frames: microphone PCM16 16 kHz (accepted and counted; used from Milestone 2).

Server -> client, JSON: ready, segment_start, flush, turn_trace, error.
Server -> client, binary: 8-byte header (uint32 epoch, uint32 segment_id, little-endian) + PCM16 24 kHz mono.
"""
from __future__ import annotations

import asyncio
import json
import logging

from websockets.asyncio.server import ServerConnection
from websockets.exceptions import ConnectionClosed

from ..config import Settings
from ..frames import FRAME_SAMPLES_OUT, SAMPLE_RATE_OUT, AudioOut, pack_audio
from ..orchestrator.session import Session
from ..services.base import TTSService

log = logging.getLogger(__name__)


def make_handler(tts: TTSService, settings: Settings, sessions: dict | None = None):
    async def handler(ws: ServerConnection) -> None:
        async def send_audio(f: AudioOut) -> None:
            await ws.send(pack_audio(f))

        async def send_event(ev: dict) -> None:
            await ws.send(json.dumps(ev, ensure_ascii=False))

        s = Session(tts, send_audio, send_event, settings)
        if sessions is not None:
            sessions[s.id] = s
        s.start()
        await send_event({"type": "ready", "session_id": s.id, "sample_rate": SAMPLE_RATE_OUT,
                          "frame_samples": FRAME_SAMPLES_OUT, "audio_header": "<II epoch, segment_id"})
        log.info("session %s connected", s.id)
        mic_bytes = 0
        pending: set[asyncio.Task] = set()
        try:
            async for msg in ws:
                if isinstance(msg, bytes):
                    mic_bytes += len(msg)
                    continue
                try:
                    m = json.loads(msg)
                    kind = m.get("type")
                    if kind == "say":
                        t = asyncio.create_task(s.say(str(m["text"])))
                        pending.add(t)
                        t.add_done_callback(pending.discard)
                    elif kind == "interrupt":
                        await s.interrupt(str(m.get("reason", "client")))
                    elif kind == "playback":
                        s.on_playback(int(m["segment_id"]), int(m["samples"]))
                    elif kind == "hangup":
                        break
                    else:
                        await send_event({"type": "error", "error": f"unknown message type {kind!r}"})
                except (ValueError, KeyError, TypeError) as e:
                    await send_event({"type": "error", "error": f"bad message: {e!r}"})
        except ConnectionClosed:
            pass
        finally:
            for t in pending:
                t.cancel()
            await s.close()
            if sessions is not None:
                sessions.pop(s.id, None)
            log.info("session %s closed (%d mic bytes received)", s.id, mic_bytes)

    return handler
