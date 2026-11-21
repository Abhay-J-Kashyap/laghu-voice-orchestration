"""Runs the agent inside a live call: turns in, speech out (design doc: Dialog layer, in the runtime).

- Caller turns (from the listener, or typed) are handled one at a time, in order.
- The reply is streamed: its first sentence is spoken while the LLM still writes the rest. If the first
  sentence isn't ready `filler_after_ms` after the turn (an LLM call, a slow backend), the filler line
  ("जी, एक पल।", pre-rendered) is said first, so the caller isn't left in silence.
- If the caller cut off the agent's last reply, the agent is told what fraction they heard (from the client's
  playback reports): the LLM sees the reply marked [interrupted], and a yes to a question that wasn't heard
  in full doesn't count where the spec says so (consent).
- Silence after the agent finishes: "are you there?" after `reprompt_after_s`, the call ends after
  `hangup_after_reprompts` of those.
- When the agent ends the call, the closing line is played to the end, then the client gets `end_call`.

Every turn writes a `kind: dialog` record to the session's trace (same file as the audio turns): the user
turn and agent turns it links, when the reply was ready, whether the filler played, and what the engine did.
"""
from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
from collections.abc import Awaitable, Callable

from collections.abc import AsyncIterable, AsyncIterator

from ..obs.trace import Turn, now_ns
from ..orchestrator.session import Session
from .agent import Agent, Reply

log = logging.getLogger(__name__)


class DialogRunner:
    def __init__(self, session: Session, agent: Agent, send_event: Callable[[dict], Awaitable[None]],
                 speak: Callable[[AsyncIterable[str]], Awaitable[str]], end_call: Callable[[], Awaitable[None]],
                 in_caller_turn: Callable[[], bool] = lambda: False):
        self.s = session
        self.agent = agent
        self.send_event = send_event
        self.speak = speak
        self.end_call = end_call
        self.in_caller_turn = in_caller_turn
        t = agent.spec.timing
        self.filler_s = float(t.get("filler_after_ms", 500)) / 1000
        self.reprompt_s = float(t.get("reprompt_after_s", 6))
        self.filler_text = agent.spec.lines["filler"].text or agent.spec.lines["filler"].example
        self.lock = asyncio.Lock()
        self.last_reply_turns: list[str] = []
        self.last_activity_ns = now_ns()
        self.ended = False
        self._ids = itertools.count(1)
        self._tasks: set[asyncio.Task] = set()
        self._shown: dict = {}
        self._waiting = 0               # caller turns waiting for the one being handled
        self._stale = False             # the last reply was dropped: the caller didn't hear its question
        self.hold_s = float(t.get("hold_s", 20))

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        async with self.lock:
            d = Turn(self.s.id, f"d{next(self._ids)}", self.s.epoch)
            d.mark("dialog_start")
            await self._produce(self.agent.start(), d)
        self._spawn(self._watch())

    async def close(self) -> None:
        self.ended = True
        for t in list(self._tasks):
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    # ------------------------------------------------------------------ caller turns
    def turn_complete(self, text: str) -> bool:
        """The listener's hint: does this transcript already answer the question? Never while a turn is still
        being handled (the question is about to change)."""
        if self.ended or self._waiting or self.lock.locked():
            return False
        return self.agent.turn_complete(text)

    async def on_caller(self, text: str, user_trace: Turn | None = None, typed: bool = False) -> None:
        self.last_activity_ns = now_ns()
        if self.ended:
            return
        if typed and self.s.agent_busy(echo_tail_ms=0):
            await self.s.interrupt("typed")              # typing over the agent counts as a barge-in
        self._waiting += 1
        async with self.lock:
            self._waiting -= 1
            if self.ended:
                return
            d = Turn(self.s.id, f"d{next(self._ids)}", self.s.epoch)
            d.set(kind="dialog", user_turn_id=user_trace.turn_id if user_trace else None, typed=typed)
            if user_trace is not None:
                for k in ("speech_end", "turn_end", "stt_final"):
                    if k in user_trace.marks:
                        d.mark(f"user_{k}", user_trace.marks[k])
            d.mark("dialog_start")
            heard, frac = self._prompt_heard()
            if not heard:
                self.agent.note_interrupted(frac)
            await self._produce(self.agent.handle(text, prompt_heard=heard, heard_fraction=frac), d)
            self.last_activity_ns = max(self.last_activity_ns, now_ns())

    async def _produce(self, decide, d: Turn) -> None:
        """Decide the reply, then speak it as it is written; the filler first if the first sentence is late."""
        async def first_sentence():
            reply = await decide
            stream = self.agent.stream(reply).__aiter__()
            try:
                first = await stream.__anext__()
            except StopAsyncIteration:
                first = None
            return reply, stream, first

        task = asyncio.create_task(first_sentence())
        filler_tid = None
        try:
            reply, stream, first = await asyncio.wait_for(asyncio.shield(task), self.filler_s)
        except asyncio.TimeoutError:
            d.mark("filler_start")
            filler_tid = await self.speak(_once(self.filler_text))
            reply, stream, first = await task
        d.mark("reply_ready")                  # the first sentence, ready to speak
        tid = None
        if first is not None and (self._waiting or self.in_caller_turn()):
            # the caller is already speaking again (or has finished another turn): this reply answers a turn
            # they've moved past, so it isn't said. Its question counts as not heard on the next turn.
            d.set(stale=True)
            self._stale = True
            await stream.aclose()
            first = None
        if first is not None:
            async def pieces() -> AsyncIterator[str]:
                yield first
                async for p in stream:
                    yield p
            async with contextlib.aclosing(stream):
                tid = await self.speak(pieces())
            self.last_reply_turns = [tid]
        d.mark("reply_done")
        await self._respond(reply, d, filler_tid, tid)
        if reply.step.get("hold"):           # "एक सेकंड": give them longer before "are you there?"
            self.last_activity_ns = now_ns() + int((self.hold_s - self.reprompt_s) * 1e9)

    def _prompt_heard(self) -> tuple[bool, float]:
        """Did the caller hear all of the agent's last reply? If not, about what fraction of it."""
        if self._stale:
            self._stale = False
            return False, 0.0
        if not self.last_reply_turns:
            return True, 1.0
        total = heard = 0
        cut = False
        for tid in self.last_reply_turns:
            ts = self.s.turns.get(tid)
            if ts is None:
                continue
            text = ts.trace.fields.get("text", "")
            total += len(text)
            if ts.trace.fields.get("outcome") == "interrupted":
                cut = True
                h = ts.trace.fields.get("heard") or {}
                heard += len((h.get("text_estimate") or "").rstrip("…"))
            else:
                heard += len(text)
        if not cut:
            return True, 1.0
        return False, (heard / total if total else 0.0)

    async def _respond(self, reply: Reply, d: Turn, filler_tid: str | None, tid: str | None) -> None:
        step = {k: v for k, v in reply.step.items() if k != "caller"}
        d.set(kind="dialog", reply_turn_id=tid, filler_turn_id=filler_tid, step=step, end=reply.end)
        rec = self.s.trace.write(d)
        for name, value in self.agent.shown.items():
            if self._shown.get(name) != value:
                self._shown[name] = value
                await self._event({"type": "dialog", "show": {name: value}})
        await self._event({"type": "dialog", "state": reply.step.get("state_out"), "event": reply.step.get("event"),
                           "path": reply.step.get("path"), "tools": reply.step.get("tools"),
                           "llm_ms": [round(c.get("ms", 0)) for c in reply.step.get("llm", [])],
                           "filler": filler_tid is not None, "ms": rec["ms"], "end": reply.end})
        if reply.end:
            self.ended = True
            self._spawn(self._finish(reply.end))

    async def _finish(self, reason: str) -> None:
        """Let the closing line play out, then end the call."""
        await asyncio.sleep(0.2)
        for _ in range(1200):                            # at most 60 s
            if not self.s.agent_busy(echo_tail_ms=0):
                break
            await asyncio.sleep(0.05)
        await self._event({"type": "end_call", "reason": reason, "backend_session": self.agent.vars.get("session_id")})
        await asyncio.sleep(0.2)
        await self.end_call()

    # ------------------------------------------------------------------ silence
    async def _watch(self) -> None:
        while not self.ended:
            await asyncio.sleep(0.25)
            if self.lock.locked() or self.s.agent_busy() or self.in_caller_turn():
                self.last_activity_ns = now_ns()
                continue
            if (now_ns() - self.last_activity_ns) / 1e9 < self.reprompt_s:
                continue
            async with self.lock:
                if self.ended:
                    return
                d = Turn(self.s.id, f"d{next(self._ids)}", self.s.epoch)
                d.set(kind="dialog", silence=True)
                d.mark("dialog_start")
                await self._produce(self.agent.on_silence(), d)
            self.last_activity_ns = now_ns()

    # ------------------------------------------------------------------ helpers
    async def _event(self, ev: dict) -> None:
        with contextlib.suppress(Exception):
            await self.send_event(ev)

    def _spawn(self, coro) -> None:  # noqa: D401
        t = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)


async def _once(text: str) -> AsyncIterator[str]:
    yield text
