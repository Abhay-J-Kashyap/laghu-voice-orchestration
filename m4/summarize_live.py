"""Milestone 4, part B: judge the live calls from their traces and the backend's audit records.

    python m4/summarize_live.py --last 5                  # the 5 most recent agent calls in traces/
    python m4/summarize_live.py --last 5 --expect L1,L2,L3,L4,L5

Each agent call is one trace file (traces/<session>.jsonl) holding user turns, agent turns and dialog records.
For every spoken caller turn: (turn end -> first agent audio sent) and (speech end -> first agent audio
sent), the first audio being the filler's when it played. The call's ending comes from its last dialog record;
the backend's final state from the audit record of the backend session the call used.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from laghu_voice.dialog.backend import BackendClient  # noqa: E402

# The expected ending of each script in m4/live_scripts.md: (agent ending, backend state)
EXPECTED = {
    "L1": ("completed", "completed"),
    "L2": ("transferred", "escalated"),
    "L3": ("consent_declined", "eligibility_assessed"),
    "L4": ("completed", "completed"),
    "L5": ("lead_captured", "lead_captured"),
}


def abs_ns(rec: dict, mark: str) -> float | None:
    ms = rec.get("ms", {})
    return rec["t0_ns"] + ms[mark] * 1e6 if mark in ms else None


def load_call(path: Path) -> dict | None:
    recs = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    dialog = [r for r in recs if r.get("kind") == "dialog"]
    if not dialog:
        return None
    by_id = {r["turn_id"]: r for r in recs if r.get("kind") not in ("dialog", "user")}
    turns = []
    for d in dialog:
        if not d.get("user_turn_id"):
            continue
        first_id = d.get("filler_turn_id") or d.get("reply_turn_id")
        a = by_id.get(first_id)
        first_audio = abs_ns(a, "first_audio_sent") if a else None
        turn_end, speech_end = abs_ns(d, "user_turn_end"), abs_ns(d, "user_speech_end")
        step = d.get("step", {})
        turns.append({
            "turn_end_to_first_audio": (first_audio - turn_end) / 1e6 if first_audio and turn_end else None,
            "speech_end_to_first_audio": (first_audio - speech_end) / 1e6 if first_audio and speech_end else None,
            "filler": bool(d.get("filler_turn_id")), "path": step.get("path"), "event": step.get("event"),
            "dialog_ms": step.get("ms")})
    start = next((d for d in dialog if d.get("step", {}).get("kind") == "start"), {})  # its backend session
    dropped = sum(len(r.get("dropped_words") or []) for r in by_id.values())
    return {"file": path.name, "mtime": path.stat().st_mtime, "end": dialog[-1].get("end"), "dropped": dropped,
            "backend_session": start.get("step", {}).get("backend_session"), "turns": turns,
            "reasks": sum(1 for t in turns if t["event"] in ("reask", "unclear", "not_heard"))}


def pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


async def main_async(a) -> None:
    files = sorted(Path(a.traces).glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    calls = [c for c in (load_call(p) for p in files) if c]
    calls = calls[-a.last:]
    expect = a.expect.split(",") if a.expect else list(EXPECTED)[:len(calls)]
    backend = BackendClient(a.backend, a.api_key)
    ok = 0
    print(f"{len(calls)} call(s):")
    for c, e in zip(calls, expect):
        state = None
        if c["backend_session"]:
            try:
                state = (await backend.audit(c["backend_session"]))["state"]
            except Exception as ex:  # noqa: BLE001
                state = f"(audit failed: {ex!r})"
        want = EXPECTED.get(e)
        good = want is not None and (c["end"], state) == want
        ok += good
        print(f"  {'ok ' if good else 'BAD'} {e}: {c['file']}: agent ended {c['end']}, backend {state}"
              f"{'' if good else f' (expected {want})'}; {len(c['turns'])} spoken turns, {c['reasks']} re-asked")
    await backend.aclose()
    print(f"M4-4 live task success: {ok}/{len(calls)}")
    turns = [t for c in calls for t in c["turns"]]
    te = [t["turn_end_to_first_audio"] for t in turns if t["turn_end_to_first_audio"] is not None]
    se = [t["speech_end_to_first_audio"] for t in turns if t["speech_end_to_first_audio"] is not None]
    if te:
        print(f"M4-5 turn end -> first agent audio, {len(te)} turns: p50 {pct(te, .5):.0f} ms, p95 {pct(te, .95):.0f} ms, "
              f"max {max(te):.0f} ms")
    if se:
        print(f"  speech end -> first agent audio: p50 {pct(se, .5):.0f} ms, p95 {pct(se, .95):.0f} ms")
    print(f"  words Laghu dropped from the agent's text: {sum(c['dropped'] for c in calls)}")
    print(f"  filler played on {sum(t['filler'] for t in turns)}/{len(turns)} turns; understood by "
          f"{ {p: sum(1 for t in turns if str(t['path']) == p) for p in sorted({str(t['path']) for t in turns})} }")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--traces", default="traces")
    ap.add_argument("--last", type=int, default=5)
    ap.add_argument("--expect", help="script ids of the calls, in order (default L1,L2,...)")
    ap.add_argument("--backend", default="http://127.0.0.1:8000")
    ap.add_argument("--api-key", default="local-dev-key")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
