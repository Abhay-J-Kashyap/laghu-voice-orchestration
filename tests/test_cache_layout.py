"""Milestone 5, Amendment 2: prompt size. The cache-friendly layout was measured on Groq and dropped (it was 1.9x
larger, and Groq's cache served 0% of a cold call and 36% of a warm one). This keeps the compact prompts from
growing back unnoticed: one typed gym call (m5/cache_probe.py, free stand-in) stays under a fixed budget."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_s = importlib.util.spec_from_file_location("cache_probe", ROOT / "m5" / "cache_probe.py")
probe = importlib.util.module_from_spec(_s)
_s.loader.exec_module(probe)

BUDGET_CHARS = 26_000          # measured 23,264 on 21 Nov 2026 (8 requests); the cached layout was 43,410


async def test_one_gym_call_stays_within_the_prompt_budget():
    agent, dlm = await probe.run_call(probe.StandIn())
    assert agent.ended == "booked"
    total = sum(len(probe.render(r["messages"])) for r in dlm.requests)
    assert total <= BUDGET_CHARS, f"{total} characters of prompt in one gym call (budget {BUDGET_CHARS})"
