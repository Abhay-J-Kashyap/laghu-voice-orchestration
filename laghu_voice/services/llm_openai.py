"""Streaming chat client for any OpenAI-compatible endpoint: Groq by default, llama.cpp / vLLM / Ollama on Profile B.

Only `delta.content` is yielded. For gpt-oss models on Groq, reasoning is turned down and left out of the
response (`reasoning_effort: "low"`, `include_reasoning: false`, per Groq's reasoning docs); otherwise the
model spends part of the latency budget thinking before the first spoken word.
"""
from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import httpx


def default_extra(model: str) -> dict:
    if model.startswith("openai/gpt-oss"):
        return {"reasoning_effort": "low", "include_reasoning": False}
    return {}


@dataclass
class LLMStats:
    t_request_ns: int = 0
    t_first_token_ns: int = 0
    t_done_ns: int = 0
    n_chunks: int = 0
    usage: dict = field(default_factory=dict)       # includes prompt_tokens_details.cached_tokens on Groq
    limits: dict = field(default_factory=dict)      # the x-ratelimit-* response headers
    finish_reason: str | None = None

    @property
    def ttft_ms(self) -> float | None:
        return (self.t_first_token_ns - self.t_request_ns) / 1e6 if self.t_first_token_ns else None

    @property
    def total_ms(self) -> float | None:
        return (self.t_done_ns - self.t_request_ns) / 1e6 if self.t_done_ns else None


class LLMError(RuntimeError):
    def __init__(self, message: str, status: int = 0, retry_after_s: float | None = None):
        super().__init__(message)
        self.status = status
        self.retry_after_s = retry_after_s


def _retry_after(r: httpx.Response) -> float | None:
    v = r.headers.get("retry-after")
    try:
        return float(v) if v is not None else None
    except ValueError:
        return None


def _limits(r: httpx.Response) -> dict:
    return {k: v for k, v in r.headers.items() if k.lower().startswith("x-ratelimit")}


class OpenAICompatLLM:
    def __init__(self, base_url: str, api_key: str, model: str, extra: dict | None = None,
                 timeout_s: float = 30.0, transport: httpx.AsyncBaseTransport | None = None):
        self.model = model
        self.extra = {**default_extra(model), **(extra or {})}
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.client = httpx.AsyncClient(base_url=base_url.rstrip("/"), headers=headers,
                                        timeout=httpx.Timeout(timeout_s, connect=10.0), transport=transport)

    async def aclose(self) -> None:
        await self.client.aclose()

    async def stream(self, messages: list[dict], *, stats: LLMStats | None = None, max_tokens: int = 200,
                     temperature: float = 0.3, **kw) -> AsyncIterator[str]:
        stats = stats if stats is not None else LLMStats()
        body = {"model": self.model, "messages": messages, "stream": True, "max_tokens": max_tokens,
                "temperature": temperature, "stream_options": {"include_usage": True}, **self.extra, **kw}
        stats.t_request_ns = time.perf_counter_ns()
        async with self.client.stream("POST", "/chat/completions", json=body) as r:
            stats.limits = _limits(r)
            if r.status_code != 200:
                detail = (await r.aread()).decode("utf-8", "replace")[:500]
                raise LLMError(f"HTTP {r.status_code}: {detail}", r.status_code, _retry_after(r))
            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                obj = json.loads(data)
                usage = obj.get("usage") or (obj.get("x_groq") or {}).get("usage")
                if usage:
                    stats.usage = usage
                for choice in obj.get("choices") or []:
                    if choice.get("finish_reason"):
                        stats.finish_reason = choice["finish_reason"]
                    text = (choice.get("delta") or {}).get("content")
                    if text:
                        if not stats.t_first_token_ns:
                            stats.t_first_token_ns = time.perf_counter_ns()
                        stats.n_chunks += 1
                        yield text
        stats.t_done_ns = time.perf_counter_ns()

    async def complete(self, messages: list[dict], *, stats: LLMStats | None = None, max_tokens: int = 300,
                       temperature: float = 0.0, **kw) -> str:
        """One whole reply, not streamed (the dialog's JSON extraction). Reasoning is left out as in stream()."""
        stats = stats if stats is not None else LLMStats()
        body = {"model": self.model, "messages": messages, "stream": False, "max_tokens": max_tokens,
                "temperature": temperature, **self.extra, **kw}
        stats.t_request_ns = time.perf_counter_ns()
        r = await self.client.post("/chat/completions", json=body)
        stats.t_done_ns = stats.t_first_token_ns = time.perf_counter_ns()
        stats.limits = _limits(r)
        if r.status_code != 200:
            raise LLMError(f"HTTP {r.status_code}: {r.text[:500]}", r.status_code, _retry_after(r))
        obj = r.json()
        stats.usage = obj.get("usage") or (obj.get("x_groq") or {}).get("usage") or {}
        choice = (obj.get("choices") or [{}])[0]
        stats.finish_reason = choice.get("finish_reason")
        stats.n_chunks = 1
        return (choice.get("message") or {}).get("content") or ""
