"""WebSocket transport (design doc: Transport, audio formats and client).

Client -> server, JSON text frames:
    {"type": "say", "text": "..."}                      speak this text (Milestone 1 stands in for the dialog)
    {"type": "interrupt", "reason": "..."}              barge-in (Milestone 3 moves this server-side, from VAD)
    {"type": "playback", "segment_id": 3, "samples": 4800}   how much of a segment the speaker has played
    {"type": "hangup"}
Client -> server, binary frames: microphone PCM16 little-endian, 16 kHz mono, any length (20 ms is typical).
    The client sends continuously, silence included: the listener counts silence on the audio clock.

Server -> client, JSON: ready, segment_start, flush, turn_trace, error, and from Milestone 2:
    {"type": "vad", "speech": true|false, "turn_id": "u1"}             caller started / paused speaking
    {"type": "user_turn", "text": "...", "trace": {...}}                 caller's turn ended, with its timings
Server -> client, binary: 8-byte header (uint32 epoch, uint32 segment_id, little-endian) + PCM16 24 kHz mono.
"""
from __future__ import annotations

import asyncio
import json
import logging

from websockets.asyncio.server import ServerConnection
from websockets.exceptions import ConnectionClosed

from ..config import Settings
from ..dialog.echo import echo_reply
from ..frames import FRAME_SAMPLES_OUT, SAMPLE_RATE_OUT, AudioOut, pack_audio
from ..orchestrator.listener import Listener, ListenModels, UserTurn
from ..orchestrator.session import Session
from ..services.base import TTSService

log = logging.getLogger(__name__)


def make_handler(tts: TTSService, settings: Settings, sessions: dict | None = None,
                 listen: ListenModels | None = None):
    async def handler(ws: ServerConnection) -> None:
        async def send_audio(f: AudioOut) -> None:
            await ws.send(pack_audio(f))

        async def send_event(ev: dict) -> None:
            await ws.send(json.dumps(ev, ensure_ascii=False))

        s = Session(tts, send_audio, send_event, settings)
        if sessions is not None:
            sessions[s.id] = s
        s.start()
        pending: set[asyncio.Task] = set()
        listener = None
        if listen is not None:
            async def on_user_turn(ut: UserTurn) -> None:
                rec = s.trace.write(ut.trace)
                await send_event({"type": "user_turn", "text": ut.text, "trace": rec})
                if settings.dialog == "echo":
                    listener.set_muted(True)           # half-duplex until the reply has played (Milestone 2)
                    await s.say(echo_reply(ut))

            listener = Listener(listen.vad, listen.stt, listen.turn, on_user_turn, send_event, s.id, listen.config)

            async def gate():                          # reopen the mic once the agent's audio has played out
                while True:
                    await asyncio.sleep(0.05)
                    listener.set_muted(s.agent_busy())
            gate_task = asyncio.create_task(gate())
            pending.add(gate_task)
        await send_event({"type": "ready", "session_id": s.id, "sample_rate": SAMPLE_RATE_OUT,
                          "frame_samples": FRAME_SAMPLES_OUT, "audio_header": "<II epoch, segment_id"})
        log.info("session %s connected", s.id)
        mic_bytes = 0
        try:
            async for msg in ws:
                if isinstance(msg, bytes):
                    mic_bytes += len(msg)
                    if listener is not None:
                        listener.feed(msg)
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
            if listener is not None:
                await listener.close()
            await s.close()
            if sessions is not None:
                sessions.pop(s.id, None)
            log.info("session %s closed (%d mic bytes received)", s.id, mic_bytes)

    return handler
