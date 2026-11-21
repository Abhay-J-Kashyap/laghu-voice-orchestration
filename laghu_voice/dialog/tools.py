"""Running a spec's tools: build the request from the call's values, send it (HTTP) or look up the answer (mock),
save what the spec says to save, and turn the answer into one event by the spec's rules.

Request bodies: a value "{amount}" is replaced by the value itself (a number stays a number, true stays true);
"{dob:iso}" applies a format; any other string is filled in as text.

Event rules are tried in order; the first whose `if` matches gives the event:

    events:
      - {if: {outcome: otp_sent, data.phone_last4: present}, then: otp_sent_phone}
      - {if: {data.decision: approved, data.approved_amount: {lt: "{amount}"}}, then: counter}
      - {if: {outcome: retry}, then: retry, clear: [full_name, dob, pan]}
      - {then: error}                       # the last rule has no `if`

A condition's value is an exact value, a list (any of), `present`, or {lt|le|gt|ge: value}. Keys are
`outcome`, `status` or `data.<field>` (HTTP), and for mock answers' own `if`, the call's values.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .backend import BackendClient, KeyMaker, ToolResult
from .slots import fmt
from .spec import Spec, Tool

_ONE = re.compile(r"^\{([\w]+)(?::(\w+))?\}$")
_ANY = re.compile(r"\{([\w]+)(?::(\w+))?\}")


def resolve(value: Any, vars: dict) -> Any:
    if isinstance(value, dict):
        return {k: resolve(v, vars) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, vars) for v in value]
    if not isinstance(value, str):
        return value
    m = _ONE.match(value)
    if m:
        v = vars.get(m.group(1))
        return fmt(v, m.group(2)) if m.group(2) else (v.isoformat() if hasattr(v, "isoformat") else v)
    return _ANY.sub(lambda m: str(fmt(vars.get(m.group(1)), m.group(2)) if m.group(2) else vars.get(m.group(1), "")),
                    value)


def lookup(answer: dict, key: str) -> Any:
    cur: Any = answer
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def matches(cond: dict, get, vars: dict) -> bool:
    for key, want in (cond or {}).items():
        have = get(key)
        if want == "present":
            if have in (None, ""):
                return False
        elif isinstance(want, dict):
            for op, ref in want.items():
                ref = resolve(ref, vars)
                if have is None or ref is None:
                    return False
                ok = {"lt": have < ref, "le": have <= ref, "gt": have > ref, "ge": have >= ref}[op]
                if not ok:
                    return False
        elif isinstance(want, list):
            if have not in want:
                return False
        elif have != want and str(have) != str(want):
            return False
    return True


@dataclass
class ToolOutcome:
    event: str
    result: ToolResult
    saved: dict = field(default_factory=dict)
    clear: list[str] = field(default_factory=list)


class ToolRunner:
    def __init__(self, spec: Spec, backend: BackendClient | None, call_id: str):
        self.spec = spec
        self.backend = backend
        self.keys = KeyMaker(call_id)
        self.call_id = call_id

    async def start(self, vars: dict) -> dict:
        """Open the backend's session (HTTP specs with a `start`); returns the values to save."""
        start = self.spec.backend.get("start")
        if not self.spec.http or not start:
            return {}
        r = await self.backend.client.post(start["path"], json=resolve(start.get("body", {}), vars))
        r.raise_for_status()
        answer = r.json()
        return {k: lookup(answer, src) for k, src in start.get("save", {}).items()}

    async def run(self, tool: Tool, vars: dict, trace_id: str = "") -> ToolOutcome:
        body = resolve(tool.body, vars)
        if self.spec.http:
            r = await self.backend.call_path(tool.path, tool.name, body, self.keys(tool.name), trace_id)
        else:
            r = self._mock(tool, vars)
        answer = {"outcome": r.outcome, "status": r.status, "data": r.data}
        saved = {}
        for name, src in tool.save.items():
            src = src["from"] if isinstance(src, dict) else src
            v = lookup(answer, src)
            if v is not None:
                saved[name] = v
        for rule in tool.events:
            if matches(rule.get("if"), lambda k: lookup(answer, k), {**vars, **saved}):
                return ToolOutcome(rule["then"], r, saved, list(rule.get("clear", [])))
        raise RuntimeError(f"tool {tool.name}: no event rule matched")   # the spec check makes this impossible

    def _mock(self, tool: Tool, vars: dict) -> ToolResult:
        for ans in tool.mock:
            if matches(ans.get("if"), lambda k: resolve(f"{{{k}}}", vars), vars):
                return ToolResult(tool.name, ans.get("outcome", "ok"), resolve(ans.get("data", {}), vars),
                                  None, int(ans.get("status", 200)), 0.0, 1, "")
        return ToolResult(tool.name, "error", {}, None, 500, 0.0, 1, "")
