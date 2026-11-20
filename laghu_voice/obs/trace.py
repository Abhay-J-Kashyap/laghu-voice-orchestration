"""Per-turn traces written as JSONL, one file per session (design doc: Observability).

Every number this project reports is computed from these records, so each stage boundary gets a mark with
time.perf_counter_ns(), not time.monotonic_ns(): before Python 3.13, monotonic() on Windows ticks in 15.6 ms
steps, which would round every latency in the traces to multiples of 15.6 ms. `ms` in the output is milliseconds since the turn's first mark.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def now_ns() -> int:
    return time.perf_counter_ns()


@dataclass
class Turn:
    session_id: str
    turn_id: str
    epoch: int
    marks: dict[str, int] = field(default_factory=dict)
    fields: dict[str, Any] = field(default_factory=dict)

    def mark(self, name: str, t_ns: int | None = None, *, first_only: bool = True) -> None:
        """Record when `name` happened. By default the first occurrence wins (first audio, first token...)."""
        if first_only and name in self.marks:
            return
        self.marks[name] = now_ns() if t_ns is None else t_ns

    def set(self, **kw: Any) -> None:
        self.fields.update(kw)

    def append(self, key: str, value: Any) -> None:
        self.fields.setdefault(key, []).append(value)

    def to_record(self) -> dict[str, Any]:
        t0 = min(self.marks.values()) if self.marks else 0
        return {
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "epoch": self.epoch,
            "ms": {k: round((v - t0) / 1e6, 2) for k, v in sorted(self.marks.items(), key=lambda kv: kv[1])},
            "t0_ns": t0,
            **self.fields,
        }


class TraceWriter:
    def __init__(self, trace_dir: Path | None, session_id: str):
        self.session_id = session_id
        self.path = None
        if trace_dir is not None:
            trace_dir.mkdir(parents=True, exist_ok=True)
            self.path = trace_dir / f"{session_id}.jsonl"
        self.records: list[dict[str, Any]] = []   # kept in memory too, for tests and the client's latency view

    def write(self, turn: Turn) -> dict[str, Any]:
        rec = turn.to_record()
        self.records.append(rec)
        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec
