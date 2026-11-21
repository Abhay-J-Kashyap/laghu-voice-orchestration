"""One call: the speaking path of Milestone 1 (design doc: Runtime model).

    text --> Segmenter --> text_q --> TTS worker --> AudioPacer --> client
                                         ^               ^
                         interrupt(): epoch + 1, stop event set, queues drained, client told to flush

Every queued item carries the epoch it was made in; after an interrupt every stage drops older items, so
nothing stale reaches the caller even if it was already sitting in a queue.
"""
from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import threading
import uuid
from collections.abc import AsyncIterable, Awaitable, Callable
from dataclasses import dataclass

import numpy as np

from ..config import Settings
from ..frames import FRAME_SAMPLES_OUT, SAMPLE_RATE_OUT, AudioOut, SpeakText
from ..obs.trace import TraceWriter, Turn, now_ns
from ..services.base import TTSResult, TTSService, float_to_pcm16
from ..text.segmenter import Segmenter
from .pacing import AudioPacer

log = logging.getLogger(__name__)


@dataclass
class SegmentState:
    segment_id: int
    turn_id: str
    epoch: int
    text: str
    model_text: str = ""
    samples_sent: int = 0
    samples_played: int = 0        # reported by the client
    done: bool = False


@dataclass
class TurnState:
    trace: Turn
    segment_ids: list[int]
    complete: bool = False         # all text for this turn has been segmented
    finished: bool = False


def heard_estimate(segs: list[SegmentState]) -> dict:
    """What the caller heard before interrupting, from the client's playback reports (sent every 100 ms, so
    up to 100 ms stale). A segment still being synthesised has an unknown length; its text is prorated over
    the audio sent so far, so the estimate errs towards "heard more". Words are cut at a character position
    in proportion to the audio played; this is an estimate, not an alignment."""
    parts, played_s = [], 0.0
    for s in segs:
        if s.samples_played <= 0:
            break
        total = max(s.samples_sent, 1)
        frac = min(1.0, s.samples_played / total)
        played_s += s.samples_played / SAMPLE_RATE_OUT
        if frac >= 0.999 and s.done:
            parts.append(s.text)
        else:
            parts.append(s.text[:round(len(s.text) * frac)] + "…")
            break
    return {"text_estimate": " ".join(parts), "played_s": round(played_s, 2)}


class Session:
    def __init__(self, tts: TTSService, send_audio: Callable[[AudioOut], Awaitable[None]],
                 send_event: Callable[[dict], Awaitable[None]], settings: Settings | None = None,
                 session_id: str | None = None, trace_writer: TraceWriter | None = None):
        self.settings = settings or Settings()
        self.id = session_id or uuid.uuid4().hex[:12]
        self.tts = tts
        self._send_audio = send_audio
        self._send_event = send_event
        self.trace = trace_writer or TraceWriter(self.settings.trace_dir, self.id)
        self.epoch = 0
        self._seg_ids = itertools.count(1)
        self._turn_ids = itertools.count(1)
        self.text_q: asyncio.Queue[SpeakText] = asyncio.Queue()
        self.pacer = AudioPacer(self._send_frame, lambda: self.epoch, lead_ms=self.settings.pacer_lead_ms)
        self.turns: dict[str, TurnState] = {}
        self.segments: dict[int, SegmentState] = {}
        self._stop: threading.Event | None = None
        self._tasks: list[asyncio.Task] = []
        self.playing_until_ns = 0      # when the client will have played everything sent so far (estimate)

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self._tasks = [asyncio.create_task(self._tts_worker(), name=f"tts-{self.id}"),
                       asyncio.create_task(self.pacer.run(), name=f"pacer-{self.id}")]

    async def close(self) -> None:
        if self._stop:
            self._stop.set()
        await self.pacer.close()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        for ts in self.turns.values():
            if not ts.finished:
                self._finish_turn(ts, outcome="session_closed")

    # ------------------------------------------------------------------ input
    async def say(self, text: str) -> str:
        """Speak a complete text (Milestone 1: typed text; later: templated replies)."""
        async def one():
            yield text
        return await self.say_stream(one())

    async def say_stream(self, pieces: AsyncIterable[str], first_piece_mark: str | None = None) -> str:
        """Speak text as it streams in (an LLM reply). Segments are queued as soon as each is complete."""
        turn_id = f"t{next(self._turn_ids)}"
        ts = TurnState(Turn(self.id, turn_id, self.epoch), [])
        self.turns[turn_id] = ts
        ts.trace.mark("text_start")
        epoch = self.epoch
        seg = Segmenter(first_clause=self.settings.first_clause)
        full = []
        async for piece in pieces:
            if epoch != self.epoch:
                break
            if first_piece_mark:
                ts.trace.mark(first_piece_mark)
            full.append(piece)
            for s in seg.feed(piece):
                await self._queue_segment(ts, s, epoch)
        if epoch == self.epoch:
            for s in seg.flush():
                await self._queue_segment(ts, s, epoch)
        ts.trace.set(text="".join(full))
        ts.complete = True
        self._maybe_finish(ts)
        return turn_id

    async def _queue_segment(self, ts: TurnState, text: str, epoch: int) -> None:
        sid = next(self._seg_ids)
        self.segments[sid] = SegmentState(sid, ts.trace.turn_id, epoch, text)
        ts.segment_ids.append(sid)
        ts.trace.mark("first_segment_ready")
        await self.text_q.put(SpeakText(text, epoch, sid, ts.trace.turn_id))

    def on_playback(self, segment_id: int, samples_played: int) -> None:
        s = self.segments.get(segment_id)
        if s is not None:
            s.samples_played = max(s.samples_played, samples_played)

    def agent_busy(self, echo_tail_ms: float = 300.0) -> bool:
        """True while a reply is being produced or its audio is still playing on the client, plus a short tail
        for the room's echo. Milestone 2 keeps the mic closed during that time (half-duplex)."""
        if any(not ts.finished for ts in self.turns.values()):
            return True
        return now_ns() < self.playing_until_ns + echo_tail_ms * 1e6

    async def interrupt(self, reason: str = "barge_in") -> None:
        """Barge-in: cancel everything from the current epoch and tell the client to drop its buffer."""
        t_in = now_ns()
        old = self.epoch
        self.epoch += 1
        if self._stop:
            self._stop.set()
        while not self.text_q.empty():
            self.text_q.get_nowait()
        dropped = self.pacer.flush()
        self.playing_until_ns = now_ns()
        await self._send_event({"type": "flush", "epoch": self.epoch})
        t_out = now_ns()
        for ts in self.turns.values():
            if ts.trace.epoch == old and not ts.finished:
                ts.trace.mark("interrupt_received", t_in)
                ts.trace.mark("flush_sent", t_out)
                ts.trace.set(interrupt_reason=reason, frames_dropped_in_queue=dropped)
                self._finish_turn(ts, outcome="interrupted")

    # ------------------------------------------------------------------ TTS worker
    async def _tts_worker(self) -> None:
        while True:
            st = await self.text_q.get()
            if st.epoch != self.epoch:
                continue
            ts = self.turns[st.turn_id]
            seg = self.segments[st.segment_id]
            stop = threading.Event()
            self._stop = stop
            info = TTSResult()
            buf = np.zeros(0, np.float32)
            offset = 0
            ts.trace.mark("tts_start")
            try:
                async with contextlib.aclosing(self.tts.stream(st.text, stop, info)) as chunks:
                    async for chunk in chunks:
                        seg.model_text = info.model_text   # set now: an interrupt writes the trace mid-segment
                        if st.epoch != self.epoch:
                            break
                        ts.trace.mark("tts_first_audio")
                        buf = np.concatenate([buf, chunk])
                        while len(buf) >= FRAME_SAMPLES_OUT:
                            await self.pacer.q.put(self._frame(st, buf[:FRAME_SAMPLES_OUT], offset))
                            offset += FRAME_SAMPLES_OUT
                            buf = buf[FRAME_SAMPLES_OUT:]
            except Exception as e:  # noqa: BLE001 - one bad segment must not end the call
                log.exception("TTS failed on segment %s", st.segment_id)
                ts.trace.append("errors", f"tts segment {st.segment_id}: {e!r}")
            finally:
                stop.set()
            seg.model_text = info.model_text
            if info.dropped_words:
                ts.trace.append("dropped_words", info.dropped_words)
            if st.epoch == self.epoch:
                await self.pacer.q.put(self._frame(st, buf, offset, last=True))

    def _frame(self, st: SpeakText, x: np.ndarray, offset: int, last: bool = False) -> AudioOut:
        return AudioOut(float_to_pcm16(x), st.epoch, st.segment_id, st.turn_id, offset, last)

    # ------------------------------------------------------------------ output
    async def _send_frame(self, f: AudioOut) -> None:
        seg = self.segments[f.segment_id]
        ts = self.turns[f.turn_id]
        if f.n_samples:
            if seg.samples_sent == 0:
                await self._send_event({"type": "segment_start", "segment_id": f.segment_id,
                                        "turn_id": f.turn_id, "text": seg.text})
            await self._send_audio(f)
            ts.trace.mark("first_audio_sent")
            t = now_ns()     # the client plays continuously from arrival, so this frame ends after the queued ones
            self.playing_until_ns = max(self.playing_until_ns, t) + int(f.n_samples * 1e9 / SAMPLE_RATE_OUT)
            seg.samples_sent += f.n_samples
        if f.last:
            seg.done = True
            self._maybe_finish(ts)

    def _maybe_finish(self, ts: TurnState) -> None:
        if ts.finished or not ts.complete:
            return
        if all(self.segments[s].done for s in ts.segment_ids):
            ts.trace.mark("agent_audio_end_sent")
            self._finish_turn(ts, outcome="completed")

    def _finish_turn(self, ts: TurnState, outcome: str) -> None:
        ts.finished = True
        segs = [self.segments[s] for s in ts.segment_ids]
        ts.trace.set(outcome=outcome, segments=[
            {"segment_id": s.segment_id, "text": s.text, "model_text": s.model_text,
             "samples_sent": s.samples_sent, "samples_played": s.samples_played} for s in segs])
        if outcome == "interrupted":
            ts.trace.set(heard=heard_estimate(segs))
        rec = self.trace.write(ts.trace)
        asyncio.get_running_loop().create_task(self._safe_event({"type": "turn_trace", "trace": rec}))

    async def _safe_event(self, ev: dict) -> None:
        try:
            await self._send_event(ev)
        except Exception:  # noqa: BLE001 - the client may already be gone
            pass
