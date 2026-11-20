"""Milestone 0: time Groq's LLMs from your network and check their Hindi replies (decision rule 1).

    set GROQ_API_KEY=...            (PowerShell: $env:GROQ_API_KEY="...")
    python m0/probe_groq.py                 # prints the plan and the token estimate, calls nothing
    python m0/probe_groq.py --yes           # runs it: 2 models x (10 phrasing + 3 extraction) x 3 runs

Writes m0/out/groq_runs.csv (one row per call) and m0/out/groq_replies.jsonl (every reply, to read).
Uses the same OpenAICompatLLM client as the server, so this also tests that client against the real API.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from laghu_voice.services.llm_openai import LLMError, LLMStats, OpenAICompatLLM  # noqa: E402

LATIN = re.compile(r"[A-Za-z]")
DIGITS = re.compile(r"[0-9०-९]")


def pct(xs, p):
    """Nearest-rank percentile."""
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    return xs[max(0, math.ceil(p / 100 * len(xs)) - 1)]


def parse_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


async def one_call(llm, messages, **kw):
    stats = LLMStats()
    try:
        text = "".join([t async for t in llm.stream(messages, stats=stats, **kw)])
        return text, stats, None
    except (LLMError, Exception) as e:  # noqa: BLE001 - record and continue
        return "", stats, repr(e)[:300]


async def main_async(a):
    spec = json.loads((HERE / "prompts_groq.json").read_text(encoding="utf-8"))
    n_calls = len(a.models) * (len(spec["phrasing"]) + len(spec["extraction"])) * a.runs
    print(f"plan: {len(a.models)} models x ({len(spec['phrasing'])} phrasing + {len(spec['extraction'])} "
          f"extraction) x {a.runs} runs = {n_calls} calls, roughly {n_calls * 350:,} tokens in total")
    if not a.yes:
        print("dry run: nothing called. Add --yes to run it.")
        return
    key = os.environ.get("GROQ_API_KEY", "")
    if not key:
        raise SystemExit("set GROQ_API_KEY first")
    out = HERE / "out"
    out.mkdir(exist_ok=True)
    rows, replies = [], []
    for model in a.models:
        llm = OpenAICompatLLM(a.base_url, key, model)
        # One warm-up call per model (connection setup), not recorded.
        await one_call(llm, [{"role": "user", "content": "नमस्ते"}], max_tokens=5)
        for run in range(a.runs):
            for p in spec["phrasing"]:
                msgs = [{"role": "system", "content": spec["phrasing_system"]}, {"role": "user", "content": p["user"]}]
                text, st, err = await one_call(llm, msgs, max_tokens=120)
                flags = []
                if LATIN.search(text):
                    flags.append("latin_letters")
                if p.get("no_numbers_given") and DIGITS.search(text):
                    flags.append("digits_when_none_given")
                rows.append({"model": model, "run": run, "id": p["id"], "kind": "phrasing",
                             "ttft_ms": st.ttft_ms, "total_ms": st.total_ms, "ok": err is None and not flags,
                             "flags": "|".join(flags), "error": err, **_usage(st)})
                replies.append({"model": model, "run": run, "id": p["id"], "user": p["user"], "reply": text,
                                "flags": flags, "error": err})
                await asyncio.sleep(a.pause)
            for e in spec["extraction"]:
                msgs = [{"role": "system", "content": spec["extraction_system"]}, {"role": "user", "content": e["user"]}]
                text, st, err = await one_call(llm, msgs, max_tokens=120, temperature=0.0,
                                               response_format={"type": "json_object"})
                obj = parse_json(text)
                correct = bool(obj) and all(obj.get(k) == v for k, v in e["expect"].items())
                rows.append({"model": model, "run": run, "id": e["id"], "kind": "extraction",
                             "ttft_ms": st.ttft_ms, "total_ms": st.total_ms, "ok": err is None and correct,
                             "flags": "" if correct else "wrong_or_invalid_json", "error": err, **_usage(st)})
                replies.append({"model": model, "run": run, "id": e["id"], "user": e["user"], "reply": text,
                                "parsed": obj, "expect": e["expect"], "error": err})
                await asyncio.sleep(a.pause)
        await llm.aclose()

    with (out / "groq_runs.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with (out / "groq_replies.jsonl").open("w", encoding="utf-8") as f:
        for r in replies:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print("\nmodel                        TTFT p50  TTFT p95  phrasing ok  extraction ok  errors  -> rule 1")
    for model in a.models:
        mr = [r for r in rows if r["model"] == model]
        ttft = [r["ttft_ms"] for r in mr if r["kind"] == "phrasing"]
        ph = [r for r in mr if r["kind"] == "phrasing"]
        ex = [r for r in mr if r["kind"] == "extraction"]
        p50, p95 = pct(ttft, 50), pct(ttft, 95)
        ph_ok = sum(1 for r in ph if r["ok"])
        no_latin = sum(1 for r in ph if "latin_letters" not in r["flags"] and not r["error"])
        ex_ok = sum(1 for r in ex if r["ok"])
        errors = sum(1 for r in mr if r["error"])
        qualifies = p95 is not None and p95 <= 600 and no_latin >= 27 and ex_ok == len(ex)
        f = lambda x: f"{x:7.0f}" if x is not None else "    n/a"  # noqa: E731
        print(f"{model:28} {f(p50)}   {f(p95)}   {ph_ok:3}/{len(ph):<3}     {ex_ok:3}/{len(ex):<3}       "
              f"{errors:3}    {'qualifies' if qualifies else 'does not qualify'}")
        invented = [r for r in mr if "digits_when_none_given" in r["flags"]]
        if invented:
            print(f"    {len(invented)} replies used digits when no number was given; read them in groq_replies.jsonl")
    print(f"\nwrote {out / 'groq_runs.csv'} and {out / 'groq_replies.jsonl'}. Read the replies before deciding.")


def _usage(st):
    u = st.usage or {}
    return {"prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens")}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", nargs="+", default=["openai/gpt-oss-20b", "llama-3.3-70b-versatile"])
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--pause", type=float, default=0.5, help="seconds between calls (stay under rate limits)")
    ap.add_argument("--base-url", default="https://api.groq.com/openai/v1")
    ap.add_argument("--yes", action="store_true", help="actually call the API")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
