"""Send agent audio at real-time pace, never more than `lead_ms` ahead of the listener (design doc: Backpressure).

Audio already sent can't be recalled. If the server pushed a whole reply at once, the client would hold
seconds of audio, and a barge-in would stop the server but not the speaker. So the pacer models the
client's buffer: `buffer_end` is the moment the client runs out of audio. A frame is sent only when the
buffer holds at most `lead_ms`. On flush the buffer is assumed empty (the client drops what it has).
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from ..frames import SAMPLE_RATE_OUT, AudioOut


class AudioPacer:
    def __init__(self, send: Callable[[AudioOut], Awaitable[None]], current_epoch: Callable[[], int],
                 lead_ms: float = 200.0, sample_rate: int = SAMPLE_RATE_OUT, maxsize: int = 25,
                 clock: Callable[[], float] = time.perf_counter, sleep: Callable[[float], Awaitable] = asyncio.sleep):
        self.send = send
        self.current_epoch = current_epoch
        self.lead_s = lead_ms / 1000
        self.sr = sample_rate
        self.clock = clock
        self.sleep = sleep
        self.q: asyncio.Queue[AudioOut | None] = asyncio.Queue(maxsize=maxsize)
        self.buffer_end = 0.0

    def buffered_s(self) -> float:
        return max(0.0, self.buffer_end - self.clock())

    def flush(self) -> int:
        """Forget queued audio and assume the client emptied its buffer. Returns frames dropped here."""
        n = 0
        while not self.q.empty():
            if self.q.get_nowait() is not None:
                n += 1
        self.buffer_end = self.clock()
        return n

    async def close(self) -> None:
        self.flush()
        await self.q.put(None)

    async def run(self) -> None:
        while True:
            f = await self.q.get()
            if f is None:
                return
            if f.epoch != self.current_epoch():
                continue
            ahead = self.buffer_end - self.clock()
            if ahead > self.lead_s:
                await self.sleep(ahead - self.lead_s)
                if f.epoch != self.current_epoch():   # interrupted while waiting
                    continue
            await self.send(f)
            self.buffer_end = max(self.buffer_end, self.clock()) + f.n_samples / self.sr
