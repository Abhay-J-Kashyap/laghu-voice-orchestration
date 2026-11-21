"""WebSocket transport (design doc: Transport, audio formats and client).

Client -> server, JSON text frames:
    {"type": "say", "text": "..."}                      speak this text (Milestone 1 stands in for the dialog)
    {"type": "text", "text": "..."}                     a typed caller turn (Milestone 4, with the agent)
    {"type": "interrupt", "reason": "..."}              barge-in (Milestone 3 moves this server-side, from VAD)
    {"type": "playback", "segment_id": 3, "samples": 4800}   how much of a segment the speaker has played
    {"type": "hangup"}
Client -> server, binary frames: microphone PCM16 little-endian, 16 kHz mono, any length (20 ms is typical).
    The client sends continuously, silence included: the listener counts silence on the audio clock.

Server -> client, JSON: ready, segment_start, flush, turn_trace, error, and from Milestone 2:
    {"type": "vad", "speech": true|false, "turn_id": "u1"}             caller started / paused speaking
    {"type": "user_turn", "text": "...", "backchannel": bool, "trace": {...}}   caller's turn ended, timings
and from Milestone 3:
    {"type": "duck"} / {"type": "unduck"}       lower / restore the agent's volume (caller is talking over it)
    {"type": "barge_in", "turn_id": "u3"}       the agent was interrupted (a flush comes with it)
and from Milestone 4 (dialog = agent):
    {"type": "dialog", "state": ..., "event": ..., "tools": [...], "filler": bool, ...}   what the agent did
    {"type": "dialog", "show": {"demo_otp": "123456"}}   values the spec marks to show (the demo passcode)
    {"type": "end_call", "reason": "completed"} the agent ended the call; the server closes the connection
Server -> client, binary: 8-byte header (uint32 epoch, uint32 segment_id, little-endian) + PCM16 24 kHz mono.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass

from websockets.asyncio.server import ServerConnection
from websockets.exceptions import ConnectionClosed

from ..config import Settings
from ..dialog.agent import Agent
from ..dialog.echo import echo_reply
from ..dialog.llm import DialogLLM
from ..dialog.runner import DialogRunner
from ..frames import FRAME_SAMPLES_OUT, SAMPLE_RATE_OUT, AudioOut, pack_audio
from ..orchestrator.controller import TurnController
from ..orchestrator.listener import ListenModels, UserTurn
from ..orchestrator.session import Session
from ..services.base import TTSService

log = logging.getLogger(__name__)


@dataclass
class DialogDeps:
    """What every call's agent shares: the spec, the backend client and the LLM client."""
    spec: object
    backend: object
    llm: object | None
    max_wait_429_s: float = 0.0


def make_handler(tts: TTSService, settings: Settings, sessions: dict | None = None,
                 listen: ListenModels | None = None, dialog: DialogDeps | None = None):
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
        controller = None
        runner: DialogRunner | None = None
        if listen is not None:
            async def reply(ut: UserTurn) -> str | None:
                if runner is not None:
                    await runner.on_caller(ut.text, ut.trace)
                    return None
                return echo_reply(ut) if settings.dialog == "echo" else None

            controller = TurnController(s, listen, send_event, reply, barge_in_ms=settings.barge_in_ms,
                                        half_duplex=settings.half_duplex)
        if dialog is not None and settings.dialog == "agent":
            agent = Agent(dialog.spec, dialog.backend,
                          DialogLLM(dialog.llm, dialog.spec.agent, dialog.max_wait_429_s)
                          if dialog.llm is not None else None, call_id=f"lv-{s.id}")

            async def end_call() -> None:
                await ws.close()

            async def speak(text) -> str:
                return await (s.say(text) if isinstance(text, str) else s.say_stream(text))

            runner = DialogRunner(s, agent, send_event, controller.speak if controller else speak, end_call,
                                  in_caller_turn=(lambda: controller.listener.in_turn) if controller else (lambda: False))
            if controller is not None:
                controller.listener.turn_hint = runner.turn_complete    # dialog-aware end of turn
        await send_event({"type": "ready", "session_id": s.id, "sample_rate": SAMPLE_RATE_OUT,
                          "frame_samples": FRAME_SAMPLES_OUT, "audio_header": "<II epoch, segment_id",
                          "dialog": settings.dialog if (runner or settings.dialog != "agent") else "none"})
        if runner is not None:
            t = asyncio.create_task(runner.start())
            pending.add(t)
            t.add_done_callback(pending.discard)
        log.info("session %s connected", s.id)
        mic_bytes = 0
        try:
            async for msg in ws:
                if isinstance(msg, bytes):
                    mic_bytes += len(msg)
                    if controller is not None:
                        controller.feed(msg)
                    continue
                try:
                    m = json.loads(msg)
                    kind = m.get("type")
                    if kind == "say":
                        t = asyncio.create_task(s.say(str(m["text"])))
                        pending.add(t)
                        t.add_done_callback(pending.discard)
                    elif kind == "text":
                        if runner is None:
                            await send_event({"type": "error", "error": "typed turns need the agent (--dialog agent)"})
                        else:
                            t = asyncio.create_task(runner.on_caller(str(m["text"]), None, typed=True))
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
            if runner is not None:
                await runner.close()
            for t in pending:
                t.cancel()
            if controller is not None:
                await controller.close()
            await s.close()
            if sessions is not None:
                sessions.pop(s.id, None)
            log.info("session %s closed (%d mic bytes received)", s.id, mic_bytes)

    return handler
