"""The listening path of one call (design doc: Turn-taking; Milestone 2).

    mic PCM16 16 kHz --> 32 ms windows --> VAD --> speech / silence
                                               |
              silence 96 ms:  decode the open segment speculatively (STT worker)
              silence 200 ms: close the segment; ask Smart Turn whether the caller has finished
              Smart Turn says done, or silence reaches the cap: end of turn -> UserTurn

The caller's audio is transcribed in segments, cut at pauses of 200 ms or more. A segment is decoded as soon
as its pause starts, so when the caller stops, only the last segment is left to decode, and that decode began
96 ms into the final silence. If the caller speaks again within 200 ms, that speculative decode is thrown
away. If they speak again after 200 ms, the closed segment stays decoded and a new one opens. The final
transcript is the segments joined in order.

Everything runs on the audio clock (windows counted), so the logic is the same in real time and in tests.
Wall-clock marks (time.perf_counter_ns) go into the trace: "speech_end" is when the last window with speech
reached the server, and Milestone 2's STT rule is measured from there to "stt_final".
"""
from __future__ import annotations

import asyncio
import collections
import contextlib
import itertools
import logging
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np

from ..obs.trace import Turn, now_ns

log = logging.getLogger(__name__)

SR = 16_000
WIN = 512
WIN_MS = WIN * 1000 / SR      # 32 ms


@dataclass
class ListenConfig:
    vad_on: float = 0.5           # a window at or above this is speech
    vad_off: float = 0.35         # once speaking, a window has to drop below this to count as silence
    min_speech_ms: int = 96       # speech must last this long before a turn starts (filters clicks)
    preroll_ms: int = 320         # audio kept from before the speech started
    spec_ms: int = 96             # silence before the open segment is decoded speculatively
    commit_ms: int = 200          # silence that closes a segment and asks the turn model
    tail_ms: int = 96             # audio kept after the last speech window in a segment
    recheck_ms: int = 400         # if the turn model says "not done", ask again after this much more silence
    silence_cap_ms: int = 1500    # end the turn after this much silence whatever the turn model says
    silence_only_ms: int = 700    # end of turn when there is no turn model
    turn_threshold: float = 0.5
    max_segment_s: float = 10.0   # while the caller keeps talking, cut the open segment at its quietest point
                                  # once it is this long. 3 s was tried twice and cost accuracy both times, with and
                                  # without the STT's silence padding (Milestone 3, Amendment 2)
    dump_dir: str | None = None   # diagnostics: save every decoded segment as a WAV, with its transcript


@dataclass
class ListenModels:
    """The models every call shares: VAD, STT (with its worker thread) and the turn model (None = silence only)."""
    vad: object
    stt: object
    turn: object | None
    config: ListenConfig = field(default_factory=ListenConfig)


@dataclass
class Segment:
    index: int
    start: int                    # samples into the turn's audio
    end: int
    task: asyncio.Task | None = None
    text: str = ""
    decode_ms: float = 0.0
    queued_ns: int = 0
    done_ns: int = 0


@dataclass
class UserTurn:
    turn_id: str
    text: str
    end_reason: str               # "turn_model", "silence_cap", "silence_only"
    audio: np.ndarray
    trace: Turn
    segments: list[Segment] = field(default_factory=list)


class Listener:
    def __init__(self, vad_model, stt, turn_model, on_turn: Callable[[UserTurn], Awaitable[None]],
                 on_event: Callable[[dict], Awaitable[None]] | None = None, session_id: str = "",
                 config: ListenConfig | None = None):
        self.cfg = config or ListenConfig()
        self.vad = vad_model.stream()
        self.stt = stt
        self.turn_model = turn_model
        self.on_turn = on_turn
        self.on_event = on_event
        self.session_id = session_id
        self._ids = itertools.count(1)
        self._last_rms = 0.0
        self._pending = np.zeros(0, np.float32)
        self._preroll: collections.deque = collections.deque(maxlen=max(1, round(self.cfg.preroll_ms / WIN_MS)))
        self._speech_run: list[np.ndarray] = []
        self._turn_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="turn")
        self._tasks: set[asyncio.Task] = set()
        self.muted = False
        self.windows = 0
        self.vad_ns = 0
        self._reset_turn()

    # ------------------------------------------------------------------ public
    def feed(self, pcm16: bytes, t_ns: int | None = None) -> None:
        """Mic audio as it arrives: PCM16 little-endian, 16 kHz mono, any length."""
        t_ns = now_ns() if t_ns is None else t_ns
        x = np.frombuffer(pcm16, dtype="<i2").astype(np.float32) / 32768.0
        self.feed_float(x, t_ns)

    def feed_float(self, x: np.ndarray, t_ns: int | None = None) -> None:
        if self.muted:
            return
        t_ns = now_ns() if t_ns is None else t_ns
        self._pending = np.concatenate([self._pending, x.astype(np.float32)])
        while len(self._pending) >= WIN:
            w, self._pending = self._pending[:WIN], self._pending[WIN:]
            t0 = now_ns()
            p = self.vad.prob(w)
            self.vad_ns += now_ns() - t0
            self.windows += 1
            self._step(w, p, t_ns)

    def set_muted(self, muted: bool) -> None:
        """Ignore the mic (Milestone 2 is half-duplex: the agent's own voice must not start a turn)."""
        if muted == self.muted:
            return
        self.muted = muted
        if not muted:
            self.vad.reset()
            self._pending = np.zeros(0, np.float32)
            self._preroll.clear()
            self._speech_run = []

    @property
    def in_turn(self) -> bool:
        return self.turn is not None

    async def close(self) -> None:
        for t in list(self._tasks):
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._turn_pool.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------ state machine
    def _reset_turn(self) -> None:
        self.turn: Turn | None = None
        self.audio: list[np.ndarray] = []
        self.n = 0                       # samples in the turn so far
        self.segments: list[Segment] = []
        self.seg_start = 0
        self.speaking = False
        self.silence_ms = 0.0
        self.speech_end = 0              # sample index just after the last speech window
        self.spec: Segment | None = None # speculative decode of the open segment, not yet committed
        self.committed = True            # nothing open
        self.next_check_ms: float | None = None
        self.check_gen = 0               # bumped whenever speech resumes: older turn-model answers are stale
        self.checks: list[dict] = []
        self.wasted = 0
        self.ending = False
        self.open_rms: list[float] = []  # loudness of each window in the open segment (for cutting long ones)

    def _step(self, w: np.ndarray, p: float, t_ns: int) -> None:
        if self.turn is None:
            self._preroll.append(w)
            if p >= self.cfg.vad_on:
                self._speech_run.append(w)
                if len(self._speech_run) * WIN_MS >= self.cfg.min_speech_ms:
                    self._start_turn(t_ns)
            else:
                self._speech_run = []
            return
        if self.ending:
            return
        self._last_rms = float(np.sqrt(np.mean(np.square(w))))
        self.audio.append(w)
        self.n += WIN
        is_speech = p >= (self.cfg.vad_off if self.speaking else self.cfg.vad_on)
        if is_speech:
            self._on_speech(p, t_ns)
        else:
            self._on_silence(p, t_ns)

    def _start_turn(self, t_ns: int) -> None:
        turn_id = f"u{next(self._ids)}"
        self.turn = Turn(self.session_id, turn_id, 0)
        self.turn.set(kind="user")
        self.turn.mark("speech_start", t_ns)
        pre = list(self._preroll)
        self.audio = pre[:]
        self.n = WIN * len(pre)
        self.speaking = True
        self.committed = False
        self.speech_end = self.n
        self.turn.mark("speech_end", t_ns, first_only=False)
        self._preroll.clear()
        self._speech_run = []
        self._emit({"type": "vad", "speech": True, "turn_id": turn_id})

    def _on_speech(self, p: float, t_ns: int) -> None:
        if not self.speaking:
            self.speaking = True
            if self.spec is not None and not self.spec_committed:
                self.wasted += 1          # resumed within commit_ms: the speculative decode is stale
                self.spec = None
            if self.committed:          # the last segment is closed: open a new one
                self.committed = False
                self.seg_start = self.segments[-1].end if self.segments else self.seg_start
                self.spec = None
                self.open_rms = []
            self.check_gen += 1
            self.next_check_ms = None
            self._emit({"type": "vad", "speech": True, "turn_id": self.turn.turn_id})
        self.silence_ms = 0.0
        self.speech_end = self.n
        self.turn.mark("speech_end", t_ns, first_only=False)
        self.open_rms.append(self._last_rms)
        if (self.n - self.seg_start) / SR > self.cfg.max_segment_s:
            self._cut_long_segment()

    @property
    def spec_committed(self) -> bool:
        return bool(self.segments) and self.spec is self.segments[-1]

    def _on_silence(self, p: float, t_ns: int) -> None:
        if self.speaking:
            self.speaking = False
            self._emit({"type": "vad", "speech": False, "turn_id": self.turn.turn_id})
        self.silence_ms += WIN_MS
        self.open_rms.append(self._last_rms)
        if not self.committed:
            if self.spec is None and self.silence_ms >= self.cfg.spec_ms:
                end = min(self.n, self.speech_end + round(self.cfg.tail_ms * SR / 1000))
                self.spec = self._decode(self.seg_start, end, "pause")
                self.turn.mark("final_decode_start", first_only=False)
            if self.silence_ms >= self.cfg.commit_ms:
                if self.spec is None:
                    end = min(self.n, self.speech_end + round(self.cfg.tail_ms * SR / 1000))
                    self.spec = self._decode(self.seg_start, end, "pause")
                    self.turn.mark("final_decode_start", first_only=False)
                self.segments.append(self.spec)
                self.committed = True
                self.turn.mark("silence_commit", t_ns, first_only=False)
                self.next_check_ms = self.silence_ms
        if self.committed and self.next_check_ms is not None and self.silence_ms >= self.next_check_ms:
            self.next_check_ms = None
            self._ask_turn_model()
        limit = self.cfg.silence_cap_ms if self.turn_model is not None else self.cfg.silence_only_ms
        if self.committed and self.silence_ms >= limit:
            self._end_turn("silence_cap" if self.turn_model is not None else "silence_only")

    def _cut_long_segment(self) -> None:
        """Close the open segment at the quietest window of its last 2 s (usually a gap between words)."""
        look = min(len(self.open_rms), round(2000 / WIN_MS))
        recent = self.open_rms[-look:]
        k = int(np.argmin(recent))
        cut = self.n - WIN * (look - k) + WIN // 2
        seg = self._decode(self.seg_start, cut, "cut")
        self.segments.append(seg)
        self.seg_start = cut
        self.open_rms = self.open_rms[-(look - k):]
        self.turn.append("long_cuts", round(cut / SR, 2))

    # ------------------------------------------------------------------ STT and turn model
    def _decode(self, start: int, end: int, kind: str) -> Segment:
        seg = Segment(len(self.segments), start, end, queued_ns=now_ns())
        audio = self._slice(start, end)
        turn_id = self.turn.turn_id
        n_dump = self._dumped = getattr(self, "_dumped", 0) + 1

        async def run():
            text, ms = await self.stt.decode(audio)
            seg.text, seg.decode_ms, seg.done_ns = text, ms, now_ns()
            if self.cfg.dump_dir:
                self._dump(audio, f"{self.session_id}_{turn_id}_{n_dump:03d}_{kind}", text, ms, start, end)
            return text
        seg.task = self._spawn(run())
        return seg

    def _dump(self, audio, name, text, ms, start, end) -> None:
        import json
        from pathlib import Path

        import soundfile as sf

        d = Path(self.cfg.dump_dir)
        d.mkdir(parents=True, exist_ok=True)
        sf.write(d / f"{name}.wav", audio, SR, subtype="FLOAT")
        with (d / "index.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"file": f"{name}.wav", "text": text, "decode_ms": round(ms, 1),
                                "start_s": round(start / SR, 3), "end_s": round(end / SR, 3)},
                               ensure_ascii=False) + "\n")

    def _slice(self, start: int, end: int) -> np.ndarray:
        return np.concatenate(self.audio)[start:end] if self.audio else np.zeros(0, np.float32)

    def _ask_turn_model(self) -> None:
        if self.turn_model is None:
            return
        gen = self.check_gen
        turn = self.turn
        audio = self._slice(0, self.n)
        silence = self.silence_ms

        async def run():
            t0 = now_ns()
            prob = await asyncio.get_running_loop().run_in_executor(self._turn_pool, self.turn_model.probability,
                                                                    audio)
            t1 = now_ns()
            if self.turn is not turn or self.ending:
                return                        # that turn has already ended
            self.checks.append({"silence_ms": round(silence), "prob": round(prob, 3),
                                "ms": round((t1 - t0) / 1e6, 1), "stale": gen != self.check_gen})
            if gen != self.check_gen:
                return                        # the caller spoke again while the model was thinking
            self.turn.mark("turn_check", t1, first_only=False)
            if prob >= self.cfg.turn_threshold:
                self._end_turn("turn_model")
            else:
                self.next_check_ms = self.silence_ms + self.cfg.recheck_ms
        self._spawn(run())

    def _end_turn(self, reason: str) -> None:
        if self.ending:
            return
        self.ending = True
        turn = self.turn
        tail = self.audio[-self._preroll.maxlen:]
        turn.mark("turn_end")
        segments = list(self.segments)
        audio = self._slice(0, self.n)
        stats = {"wasted_decodes": self.wasted, "turn_checks": list(self.checks)}
        self._emit({"type": "vad", "speech": False, "turn_id": turn.turn_id, "turn_end": reason})

        async def finish():
            await asyncio.gather(*(s.task for s in segments if s.task is not None), return_exceptions=True)
            turn.mark("stt_final", max([s.done_ns for s in segments if s.done_ns] or [now_ns()]))
            text = " ".join(s.text for s in segments if s.text).strip()
            m = turn.marks
            turn.set(text=text, end_reason=reason, audio_s=round(len(audio) / SR, 2), **stats,
                     segments=[{"start_s": round(s.start / SR, 2), "end_s": round(s.end / SR, 2), "text": s.text,
                                "decode_ms": round(s.decode_ms, 1),
                                "wait_ms": round((s.done_ns - s.queued_ns) / 1e6 - s.decode_ms, 1) if s.done_ns
                                else None} for s in segments],
                     latency_ms={
                         "speech_end_to_transcript": round((m["stt_final"] - m["speech_end"]) / 1e6, 1),
                         "speech_end_to_turn_end": round((m["turn_end"] - m["speech_end"]) / 1e6, 1),
                         "transcript_after_turn_end": round(max(0, m["stt_final"] - m["turn_end"]) / 1e6, 1)})
            await self.on_turn(UserTurn(turn.turn_id, text, reason, audio, turn, segments))
        self._reset_turn()
        # The caller may already have started speaking again while the turn model was deciding: those windows
        # went into the old turn. Seed the next turn's pre-roll with them, or its first syllable is lost.
        self._preroll.extend(tail)
        self._spawn(finish())

    # ------------------------------------------------------------------ helpers
    def _spawn(self, coro) -> asyncio.Task:
        t = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._done)
        return t

    def _done(self, t: asyncio.Task) -> None:
        self._tasks.discard(t)
        if not t.cancelled() and t.exception() is not None:
            log.error("listener task failed", exc_info=t.exception())

    def _emit(self, ev: dict) -> None:
        if self.on_event is not None:
            self._spawn(self._safe(ev))

    async def _safe(self, ev: dict) -> None:
        with contextlib.suppress(Exception):
            await self.on_event(ev)
