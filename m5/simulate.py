"""Milestone 5's simulated calls: a spec, its description, a fresh set of 8 callers, N runs each.

    python m5/simulate.py agents/mba_admissions.yaml m5/use_cases/mba.md            # development: 1 run each
    python m5/simulate.py agents/x.yaml held_out/x.md --runs 2 --label judged        # the judged run (16 calls)

Results go to m5/out/sim/<spec name>/<label>.jsonl, one call per line, and the summary is printed. A run that
stops (Groq's daily limit) resumes where it left off: run the same command again. Calls are made one at a time
and paced to stay under Groq's 8,000 tokens a minute.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from laghu_voice.dialog.spec import load_spec  # noqa: E402
from laghu_voice.services.paced import DailyLimit  # noqa: E402
from laghu_voice.setup.simulate import Persona, judge, run_call, summary, write_personas  # noqa: E402
from laghu_voice.setup.tool import build_clients  # noqa: E402


async def main_async(a) -> None:
    spec = load_spec(a.spec)
    name = Path(a.spec).stem
    out_dir = ROOT / "m5" / "out" / "sim" / name
    out_dir.mkdir(parents=True, exist_ok=True)
    rows_path = out_dir / f"{a.label}.jsonl"
    personas_path = out_dir / f"{a.label}_personas.json"
    description = Path(a.description).read_text(encoding="utf-8")
    setup_llm, agent_llm, caller_llm = build_clients()
    try:
        if personas_path.exists():
            personas = [Persona(**p) for p in json.loads(personas_path.read_text(encoding="utf-8"))]
        else:
            # a separate request from the ones setup used, so these callers are new to the spec
            personas = await write_personas(setup_llm, description, spec, seed=f"Fresh callers for run '{a.label}'.")
            personas_path.write_text(json.dumps([p.__dict__ for p in personas], ensure_ascii=False, indent=1),
                                     encoding="utf-8")
        done = set()
        rows = []
        if rows_path.exists():
            for line in rows_path.read_text(encoding="utf-8").splitlines():
                r = json.loads(line)
                rows.append(r)
                done.add((r["persona"]["id"], r["run"]))
        only = set(a.only.split(",")) if a.only else None
        for run in range(1, a.runs + 1):
            for p in personas:
                if (p.id, run) in done or (only and p.id not in only):
                    continue
                print(f"{name} {p.id} ({p.kind}) run {run} ...", flush=True)
                rec, agent, dlm = await run_call(spec, name, agent_llm, caller_llm, p, run)
                rec.verdict = judge(spec, rec, agent, dlm)
                row = rec.__dict__
                rows.append(row)
                with rows_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                v = rec.verdict
                print(f"   {'ok' if v['success'] else 'FAILED'}: ended {rec.outcome} ({rec.end}); "
                      f"{sum(1 for x in v['facts'].values() if x == 'matched')}/{len(v['facts'])} facts; "
                      f"{rec.seconds:.0f} s; tokens agent {rec.tokens['agent']}, caller {rec.tokens['caller']}"
                      + (f"; SAFETY {v['safety']}" if v["safety"] else ""), flush=True)
    except DailyLimit as e:
        print(f"\nGroq's daily limit was reached ({str(e)[:160]}). Run the same command again tomorrow: it resumes.")
    finally:
        for c in {id(x): x for x in (setup_llm, agent_llm, caller_llm)}.values():
            await c.aclose()
    print("\n" + summary(rows) if rows else "no calls yet")
    print(f"\n{rows_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec")
    ap.add_argument("description")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--label", default="dev")
    ap.add_argument("--only", help="persona ids, e.g. P1,P4")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
