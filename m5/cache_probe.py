"""How much of each LLM request Groq's prompt cache can reuse, and how big the prompts are (Milestone 5).

Amendment 2: an append-only layout made for the cache was tried and dropped. On Groq it was 1.9x larger and
the cache served 0% of a cold call and 36% of a warm one, so it cost more tokens than the compact prompts. The
probe stays, to measure the prompts and to re-test caching if the layout or Groq changes.

    python m5/cache_probe.py                   # free: no Groq, a stand-in LLM; what COULD be cached
    python m5/cache_probe.py --llm groq        # one real gym call (~10 requests): what Groq DID cache
    python m5/cache_probe.py --llm groq --repeat 2   # the same call twice, a minute apart: a warm cache

Groq reuses the start of a request when an earlier request started with exactly the same text. For every
request of one typed gym call, this prints:
- reusable: the share of the request that matches the start of an earlier one (the most the cache can save);
- where the match breaks, and the first words after it;
- with --llm groq: the prompt tokens Groq counted and how many it served from its cache ("-" when the reply
  was cut short after enough sentences, so Groq's count never arrived), and its rate-limit headers.

Nothing is spoken: the caller's lines are typed, and the gym's tools are mock answers in its spec.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from laghu_voice.dialog.agent import Agent, say_all  # noqa: E402
from laghu_voice.dialog.llm import DialogLLM  # noqa: E402
from laghu_voice.dialog.spec import load_spec  # noqa: E402

# A typed gym call: (what the caller says, English, what a correct reading is - for the free stand-in only)
CALL = [
    ("हाँ", "Yes", None),
    ("मेरा नाम अभय है", "My name is Abhay", {"intent": "answer", "full_name": "Abhay", "full_name_hi": "अभय"}),
    ("पहले ये बताओ कितने प्लान हैं", "First tell me, how many plans are there?", {"intent": "question"}),
    ("वज़न कम करना", "Lose weight", None),
    ("मासिक", "Monthly", None),
    ("शाम", "Evening", None),
    ("परसों", "The day after tomorrow", None),
    ("हाँ बुक कर दो", "Yes, book it", None),
]


class StandIn:
    """The free mode's LLM: answers extraction with the line's correct reading, writes the examples."""
    def __init__(self):
        self.hint = None

    async def complete(self, messages, stats=None, **kw):
        return json.dumps(self.hint or {"intent": "unclear"}, ensure_ascii=False)

    async def stream(self, messages, stats=None, **kw):
        import re
        for ex in re.findall(r'Example: "([^"]*)"', messages[-1]["content"]):
            yield ex + " "


def render(messages: list[dict]) -> str:
    return "".join(f"<|{m['role']}|>{m['content']}<|end|>" for m in messages)


def common(a: str, b: str) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def report(requests: list[dict]) -> tuple[list[dict], float]:
    """Per request: how much matches the start of an earlier request (in characters of the rendered prompt)."""
    seen: list[str] = []
    rows, total, reusable = [], 0, 0
    for req in requests:
        text = render(req["messages"])
        best = max((common(text, s) for s in seen), default=0)
        kind = "understand" if "TASK: UNDERSTAND" in req["messages"][-1]["content"] else "write"
        usage = getattr(req.get("stats"), "usage", None) or {}
        rows.append({"kind": kind, "chars": len(text), "reusable": best / len(text) if text else 0.0,
                     "breaks_at": text[best:best + 60].replace("\n", " "),
                     "prompt_tokens": usage.get("prompt_tokens"),
                     "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens")})
        total += len(text)
        reusable += best
        seen.append(text)
    return rows, (reusable / total if total else 0.0)


def append_only(requests: list[dict]) -> list[str]:
    """Problems with the layout: each request must start with the system message and the call so far exactly
    as the previous request had them (everything but its last, TASK message)."""
    problems = []
    for k in range(1, len(requests)):
        prev, cur = requests[k - 1]["messages"][:-1], requests[k]["messages"][:-1]
        if cur[:len(prev)] != prev:
            problems.append(f"request {k + 1} doesn't start with request {k}'s system message and call lines")
    return problems


async def run_call(llm) -> tuple[Agent, DialogLLM]:
    spec = load_spec(ROOT / "agents" / "gym_onboarding.yaml")
    dlm = DialogLLM(llm, spec.agent, max_wait_429_s=30.0)
    agent = Agent(spec, None, dlm, "cache-probe", today=date(2026, 11, 21))
    await say_all(agent, await agent.start())
    for text, en, hint in CALL:
        if isinstance(llm, StandIn):
            llm.hint = hint
        r = await agent.handle(text)
        await say_all(agent, r)
        print(f"  caller: {en}  ->  {r.step.get('event')} ({r.step.get('path')}), now {agent.state or agent.ended}")
        if agent.ended:
            break
    return agent, dlm


def _remaining(requests: list[dict], first: bool) -> str | None:
    for req in (requests if first else reversed(requests)):
        lim = getattr(req.get("stats"), "limits", None) or {}
        v = lim.get("x-ratelimit-remaining-tokens")
        if v is not None:
            return v
    return None


async def main_async(a) -> None:
    if a.llm == "groq":
        from laghu_voice.config import Settings
        from laghu_voice.services.llm_openai import OpenAICompatLLM
        st = Settings()
        if not st.llm_api_key:
            raise SystemExit("GROQ_API_KEY isn't set (.env)")
        llm = OpenAICompatLLM(st.llm_base_url, st.llm_api_key, st.llm_model, st.llm_extra)
    else:
        llm = StandIn()
    for run in range(1, a.repeat + 1):
        if run > 1:
            print(f"\nwaiting {a.pause:.0f} s, so Groq's per-minute token limit refills ...")
            await asyncio.sleep(a.pause)
        print(f"\n=== call {run} of {a.repeat}: " + (f"through Groq ({llm.model})" if a.llm == "groq"
                                                     else "with the free stand-in (no Groq)"))
        agent, dlm = await run_call(llm)
        show(dlm, a.llm == "groq")
    if a.llm == "groq":
        await llm.aclose()


def show(dlm: DialogLLM, groq: bool) -> None:
    rows, share = report(dlm.requests)
    print(f"\n{'#':>2}  {'task':10} {'chars':>6} {'reusable':>8}", end="")
    print(f"  {'tokens':>6} {'cached':>6}" if groq else "", end="")
    print("  the match breaks at")
    for k, r in enumerate(rows, 1):
        print(f"{k:>2}  {r['kind']:10} {r['chars']:>6} {r['reusable']:>8.0%}", end="")
        if groq:
            cached = r["cached_tokens"] if r["cached_tokens"] is not None else ("0" if r["prompt_tokens"] else "-")
            print(f"  {r['prompt_tokens'] or '-':>6} {cached:>6}", end="")
        print(f"  …{r['breaks_at']}")
    print(f"\nreusable within this call: {share:.0%} of the prompt text")
    problems = append_only(dlm.requests)
    print("layout: append-only (every request starts with the previous one's)" if not problems
          else f"layout: not append-only ({len(problems)} of {len(rows) - 1} requests don't start with the previous "
               f"one's); prompt text in all: {sum(r['chars'] for r in rows)} characters")
    if groq:
        pt = sum(r["prompt_tokens"] or 0 for r in rows)
        ct = sum(r["cached_tokens"] or 0 for r in rows)
        n = sum(1 for r in rows if r["prompt_tokens"])
        print(f"Groq: {pt} prompt tokens over the {n} requests it reported, {ct} served from its cache "
              f"({ct / pt:.0%})" if pt else "Groq returned no token counts")
        for label, req in (("first request", dlm.requests[0]), ("last request", dlm.requests[-1])):
            lim = getattr(req.get("stats"), "limits", None) or {}
            if lim:
                print(f"rate-limit headers after the {label}: " +
                      ", ".join(f"{k.replace('x-ratelimit-', '')}={v}" for k, v in sorted(lim.items())))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--llm", default="free", choices=["free", "groq"])
    ap.add_argument("--repeat", type=int, default=1, help="make the same call this many times")
    ap.add_argument("--pause", type=float, default=65.0, help="seconds between calls (Groq's per-minute limit)")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
