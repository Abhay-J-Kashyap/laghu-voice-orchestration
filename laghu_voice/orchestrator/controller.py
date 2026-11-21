"""Turn controller: who holds the floor (design doc: Turn-taking and barge-in; Milestone 3).

It sits between the listener (the caller's side) and the session (the agent's side):

- The caller starts speaking while the agent's audio is playing: the client is told to duck (lower the
  agent's volume) at once.
- They keep speaking for `barge_in_ms` (250 ms of speech by default): barge-in. The session's epoch goes up,
  synthesis stops, queued audio is dropped and the client flushes its buffer. The trace records what the
  caller had heard (an estimate from the client's playback reports).
- They stop sooner, and the agent is still talking when their turn ends: a backchannel ("haan", "hmm"). The
  volume comes back, nothing is cancelled, and the turn gets no reply.
- Otherwise the turn ends normally and goes to the dialog.

Full duplex needs headphones (or echo cancellation, later): with a speaker the mic hears the agent and it would
interrupt itself. `half_duplex=True` keeps Milestone 2's behaviour: the mic is ignored while the agent speaks.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from .listener import Listener, ListenModels, UserTurn
from .session import Session

log = logging.getLogger(__name__)


@dataclass
class Overlap:
    """The caller's turn, as seen while the agent may be talking."""
    overlap: bool                  # the agent's audio was playing when the caller started
    start_ns: int
    ducked: bool = False
    barged: bool = False
    marks: dict = field(default_factory=dict)


class TurnController:
    def __init__(self, session: Session, models: ListenModels, send_event: Callable[[dict], Awaitable[None]],
                 reply: Callable[[UserTurn], Awaitable[str | None]] | None = None, barge_in_ms: float = 250.0,
                 half_duplex: bool = False, on_user_turn: Callable[[UserTurn, dict], Awaitable[None]] | None = None):
        self.s = session
        self.send_event = send_event
        self.reply = reply
        self.barge_in_ms = barge_in_ms
        self.half_duplex = half_duplex
        self.on_user_turn = on_user_turn
        self.turns: dict[str, Overlap] = {}
        self._tasks: set[asyncio.Task] = set()
        self.listener = Listener(models.vad, models.stt, models.turn, self._turn_ended, self._listener_event,
                                 session.id, models.config, on_speech=self._speech)
        if half_duplex:
            self._spawn(self._gate())

    # ------------------------------------------------------------------ input
    def feed(self, pcm16: bytes) -> None:
        self.listener.feed(pcm16)

    async def close(self) -> None:
        for t in list(self._tasks):
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.listener.close()

    # ------------------------------------------------------------------ listener callbacks
    def _speech(self, turn_id: str, speech_ms: float, t_ns: int) -> None:
        st = self.turns.get(turn_id)
        if st is None:
            st = self.turns[turn_id] = Overlap(self.s.agent_busy(echo_tail_ms=0), t_ns)
            if self.listener.turn is not None:
                self.listener.turn.set(overlap=st.overlap)
        if not st.overlap or st.barged:
            return
        if not st.ducked:
            st.ducked = True
            self._mark("duck_sent")
            self._spawn(self._event({"type": "duck", "turn_id": turn_id}))
        if speech_ms >= self.barge_in_ms:
            if self.s.agent_busy(echo_tail_ms=0):
                st.barged = True
                self._mark("barge_in")
                self._spawn(self._barge_in(turn_id))
            else:                                   # the agent finished on its own meanwhile
                st.overlap = False
                self._unduck(turn_id, st)

    async def _listener_event(self, ev: dict) -> None:
        await self._event(ev)
        st = self.turns.get(ev.get("turn_id", ""))
        if ev.get("type") == "vad" and st is not None and not ev["speech"] and not st.barged:
            self._unduck(ev["turn_id"], st)

    async def _barge_in(self, turn_id: str) -> None:
        turn = self.listener.turn
        await self.s.interrupt("barge_in")
        if turn is not None:
            turn.mark("flush_sent")
        await self._event({"type": "barge_in", "turn_id": turn_id})

    async def _turn_ended(self, ut: UserTurn) -> None:
        st = self.turns.pop(ut.turn_id, None)
        backchannel = bool(st and st.overlap and not st.barged and self.s.agent_busy(echo_tail_ms=0))
        if st is not None:
            self._unduck(ut.turn_id, st)
        ut.trace.set(overlap=bool(st and st.overlap), barged_in=bool(st and st.barged), backchannel=backchannel)
        m = ut.trace.marks
        if "speech_start" in m:
            lat = ut.trace.fields.setdefault("latency_ms", {})
            for k in ("duck_sent", "barge_in", "flush_sent"):
                if k in m:
                    lat[f"speech_start_to_{k}"] = round((m[k] - m["speech_start"]) / 1e6, 1)
        rec = self.s.trace.write(ut.trace)
        await self._event({"type": "user_turn", "text": ut.text, "backchannel": backchannel, "trace": rec})
        if self.on_user_turn is not None:
            await self.on_user_turn(ut, rec)
        if backchannel or self.reply is None:
            return
        text = await self.reply(ut)
        if text:
            await self.speak(text)

    async def speak(self, text) -> str:
        """Say a reply: a string, or text as it streams in (the dialog runner). Returns the agent turn's id."""
        if self.half_duplex:
            self.listener.set_muted(True)
        return await (self.s.say(text) if isinstance(text, str) else self.s.say_stream(text))

    # ------------------------------------------------------------------ helpers
    def _unduck(self, turn_id: str, st: Overlap) -> None:
        if st.ducked:
            st.ducked = False
            self._spawn(self._event({"type": "unduck", "turn_id": turn_id}))

    def _mark(self, name: str) -> None:
        if self.listener.turn is not None:
            self.listener.turn.mark(name)

    async def _gate(self) -> None:
        while True:
            await asyncio.sleep(0.05)
            self.listener.set_muted(self.s.agent_busy())

    async def _event(self, ev: dict) -> None:
        with contextlib.suppress(Exception):
            await self.send_event(ev)

    def _spawn(self, coro) -> asyncio.Task:
        t = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._done)
        return t

    def _done(self, t: asyncio.Task) -> None:
        self._tasks.discard(t)
        if not t.cancelled() and t.exception() is not None:
            log.error("turn controller task failed", exc_info=t.exception())
