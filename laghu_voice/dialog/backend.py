"""HTTP client for an agent's backend (for the loan agent: the Voice Onboarding Agent service's tool API).

Every tool call carries an idempotency key, so a call retried after a timeout is answered from the backend's
record instead of being done twice (a retried verify_otp must not use up an attempt). The key is fixed per
logical call: the retry reuses it, the next real attempt gets a new one.

Every response, success or failure, has the same envelope: {outcome, agent_message, session_state, data}.
The agent never speaks `agent_message` (it is English); it branches on `outcome` and reads numbers from
`data`.
"""
from __future__ import annotations

import itertools
import logging
import time
from dataclasses import dataclass, field

import httpx

log = logging.getLogger(__name__)


@dataclass
class ToolResult:
    tool: str
    outcome: str                   # ok, otp_sent, not_registered, retry, declined, rejected, blocked, error
    data: dict = field(default_factory=dict)
    state: str | None = None
    status: int = 0
    ms: float = 0.0
    attempts: int = 1
    idempotency_key: str = ""


class BackendClient:
    def __init__(self, base_url: str, api_key: str, timeout_s: float = 5.0,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.client = httpx.AsyncClient(base_url=base_url.rstrip("/"), headers={"x-api-key": api_key},
                                        timeout=httpx.Timeout(timeout_s, connect=3.0), transport=transport)

    async def aclose(self) -> None:
        await self.client.aclose()

    async def start_session(self, call_id: str) -> str:
        r = await self.client.post("/v1/sessions", json={"external_call_id": call_id[:64], "channel": "voice",
                                                         "language": "hi-IN"})
        r.raise_for_status()
        return r.json()["session_id"]

    async def audit(self, session_id: str) -> dict:
        r = await self.client.get(f"/v1/sessions/{session_id}")
        r.raise_for_status()
        return r.json()

    async def call(self, tool: str, payload: dict, key: str, trace_id: str = "") -> ToolResult:
        return await self.call_path(f"/v1/tools/{tool}", tool, payload, key, trace_id)

    async def call_path(self, path: str, tool: str, payload: dict, key: str, trace_id: str = "") -> ToolResult:
        """POST a tool call. A timeout or dropped connection is retried once with the same idempotency key."""
        body = {**payload, "idempotency_key": key}
        headers = {"x-trace-id": trace_id} if trace_id else {}
        t0 = time.perf_counter_ns()
        last: Exception | None = None
        for attempt in (1, 2):
            try:
                r = await self.client.post(path, json=body, headers=headers)
                try:
                    j = r.json()
                except ValueError:
                    j = {}
                return ToolResult(tool, str(j.get("outcome") or ("error" if r.status_code >= 400 else "ok")),
                                  j.get("data") or {}, j.get("session_state"), r.status_code,
                                  (time.perf_counter_ns() - t0) / 1e6, attempt, key)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last = e
                log.warning("tool %s attempt %d failed: %r", tool, attempt, e)
        return ToolResult(tool, "error", {"exception": repr(last)}, None, 0, (time.perf_counter_ns() - t0) / 1e6,
                          2, key)


class KeyMaker:
    """Idempotency keys: one per logical tool call in a session."""
    def __init__(self, call_id: str):
        self.call_id = call_id
        self._n = itertools.count(1)

    def __call__(self, tool: str) -> str:
        return f"{self.call_id}:{tool}:{next(self._n)}"[:64]
