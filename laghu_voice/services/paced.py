"""An LLM client that stays under Groq's free-tier limits (Milestone 5), for batch work: the setup tool and the
simulated calls. Live calls don't use it.

- Tokens per minute: before each request it waits until the tokens used in the last 60 s plus this request's
  estimate fit under the budget (Groq allows 8,000 a minute on the free tier; the default budget is 7,000).
- A 429 that asks for a short wait (up to 90 s) is waited out and the request retried, so a burst never turns
  into a fallback line in a simulated call.
- A 429 for the daily limit (tokens or requests per day) raises DailyLimit, so a long run can stop cleanly and
  resume later.
- A dropped connection or a reply slower than the client's timeout is tried again after 5, 15 and 45 s
  (Milestone 5: two setup runs were lost to one ConnectError and one ReadTimeout).
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from collections.abc import AsyncIterator

import httpx

from .llm_openai import LLMError, LLMStats

NET_RETRIES = (5.0, 15.0, 45.0)     # a dropped connection or a slow reply (ConnectError, ReadTimeout): wait, try again


class DailyLimit(RuntimeError):
    pass


def _estimate(messages: list[dict], max_tokens: int) -> int:
    """A cautious token estimate: about 3 characters a token for mixed English and Devanagari, plus the reply."""
    return len(json.dumps(messages, ensure_ascii=False)) // 3 + max_tokens // 2


def _daily(e: LLMError) -> bool:
    text = str(e).lower()
    return "per day" in text or "tpd" in text or "rpd" in text or (e.retry_after_s or 0) > 90


class PacedLLM:
    def __init__(self, llm, tokens_per_minute: int = 7000, max_wait_s: float = 90.0):
        self.llm = llm
        self.model = getattr(llm, "model", "?")
        self.budget = tokens_per_minute
        self.max_wait_s = max_wait_s
        self.window: deque[tuple[float, int]] = deque()
        self.used_total = 0
        self.cached_total = 0
        self.requests = 0
        self.waited_s = 0.0
        self.net_retries = 0

    async def _room(self, need: int) -> None:
        while True:
            now = time.monotonic()
            while self.window and now - self.window[0][0] > 60:
                self.window.popleft()
            used = sum(n for _, n in self.window)
            if used + need <= self.budget or not self.window:
                return
            wait = 60 - (now - self.window[0][0]) + 0.2
            self.waited_s += wait
            await asyncio.sleep(wait)

    def _record(self, est: int, stats: LLMStats) -> None:
        u = stats.usage or {}
        n = (u.get("prompt_tokens") or 0) + (u.get("completion_tokens") or 0)
        cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
        n = (n - cached) if n else est
        self.window.append((time.monotonic(), n))
        self.used_total += n
        self.cached_total += cached
        self.requests += 1

    async def complete(self, messages: list[dict], *, stats: LLMStats | None = None, max_tokens: int = 300,
                       **kw) -> str:
        stats = stats if stats is not None else LLMStats()
        est = _estimate(messages, max_tokens)
        waited, net = 0.0, 0
        while True:
            await self._room(est)
            try:
                out = await self.llm.complete(messages, stats=stats, max_tokens=max_tokens, **kw)
                self._record(est, stats)
                return out
            except httpx.TransportError:
                if net >= len(NET_RETRIES):
                    raise
                await asyncio.sleep(NET_RETRIES[net])
                net += 1
                self.net_retries += 1
            except LLMError as e:
                if e.status != 429:
                    raise
                if _daily(e):
                    raise DailyLimit(str(e)) from e
                wait = e.retry_after_s if e.retry_after_s is not None else 5.0
                if waited + wait > self.max_wait_s:
                    raise
                self.waited_s += wait
                waited += wait
                await asyncio.sleep(wait)

    async def stream(self, messages: list[dict], *, stats: LLMStats | None = None, max_tokens: int = 200,
                     **kw) -> AsyncIterator[str]:
        stats = stats if stats is not None else LLMStats()
        est = _estimate(messages, max_tokens)
        waited, net = 0.0, 0
        while True:
            await self._room(est)
            started = False
            try:
                async for piece in self.llm.stream(messages, stats=stats, max_tokens=max_tokens, **kw):
                    started = True
                    yield piece
                self._record(est, stats)
                return
            except httpx.TransportError:
                if started or net >= len(NET_RETRIES):
                    raise
                await asyncio.sleep(NET_RETRIES[net])
                net += 1
                self.net_retries += 1
            except LLMError as e:
                if started or e.status != 429:
                    raise
                if _daily(e):
                    raise DailyLimit(str(e)) from e
                wait = e.retry_after_s if e.retry_after_s is not None else 5.0
                if waited + wait > self.max_wait_s:
                    raise
                self.waited_s += wait
                waited += wait
                await asyncio.sleep(wait)
            finally:
                if started and not stats.t_done_ns:
                    self._record(est, stats)        # the reader stopped early: count the estimate

    async def aclose(self) -> None:
        if hasattr(self.llm, "aclose"):
            await self.llm.aclose()
