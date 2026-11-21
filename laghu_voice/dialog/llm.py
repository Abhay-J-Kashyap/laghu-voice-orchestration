"""The LLM's jobs in a call (design doc: Dialog layer):

- extract: what the caller meant (an intent, and any non-private values), as JSON. When the next thing to say
  is an LLM line the engine can foresee, the same call also writes it (`reply`), so a turn never costs two
  round trips.
- generate: write the agent's next words from the spec's goals, streamed sentence by sentence.

Everything goes through one gate:
- Nothing private leaves: every request is checked against the caller's PAN, passcode and date of birth,
  read the way the parsers read them so any spelling counts (`hindi.Secrets`), and refused if one appears.
  The transcripts were already masked (`hindi.mask_for_llm`); this is the second lock.
- Output is checked: extraction must be valid JSON with a known intent, retried once; written words pass the
  guardrail (guard.py) sentence by sentence before Laghu speaks them.
- Every request actually sent is kept (`requests`), so an evaluation can check the first point by itself.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from ..services.llm_openai import LLMError, LLMStats
from .hindi import Secrets, leaks
from .slots import Slot
from .spec import BUILTIN_INTENTS, Intent

INTENT_HELP = {
    "answer": "the caller gives what the agent asked for (even partly)",
    "yes": "the caller agrees or confirms (for a yes-or-no question)",
    "no": "the caller refuses or says it's wrong (for a yes-or-no question)",
    "human": "wants to talk to a person, an agent, a colleague or customer care",
    "repeat": "asks the agent to say it again",
    "question": "asks something about this call, the product or the process, including yes-or-no questions "
                "(\"can I tell you later?\", \"can I change it afterwards?\")",
    "off_topic": "wants something unrelated to this call",
    "stop": "wants to end the call",
    "unclear": "anything else, or you can't tell",
    "hold": "asks the agent to wait a moment (one second, five seconds, hold on), and doesn't answer or ask "
            "anything else in this turn (\"yes I'm here, just five seconds\" is hold)",
}

EXTRACT_SYSTEM = """You read one turn of a Hindi phone call. {persona} The caller's words come from speech \
recognition and may contain mistakes. [...] marks private details removed on purpose: never guess them.

Reply with JSON only. "intent" is one of:
{intents}
Other fields, only if the caller said them in this turn, else null:
{fields}{reply_help}"""

REPLY_HELP = """
"reply": what the agent says next, in Hindi, for the intent you chose, following NEXT below. {style}"""

STYLE = ("Write as {name}, a {gender} agent: {gender} first person ({example_verbs}). Devanagari only: no English "
         "letters, no digits (numbers in Hindi words). Never say नमस्ते. Short, warm, spoken sentences; at most "
         "{max_sentences} sentences in all. Never promise approval, an amount, a rate or a time. State a number "
         "only if it is in FACTS or in an example. React briefly to what the caller said when it helps; don't "
         "repeat their private details, and don't repeat their words back to them: speech recognition may have "
         "misheard them. Never repeat a sentence the agent already said in this call: word it differently.")

GENERATE_SYSTEM = """You are {name} on a Hindi phone call. {persona}

Say what the agent says next, following the steps in order. {style}

FACTS: {facts}"""


@dataclass
class LLMCall:
    kind: str
    ms: float = 0.0
    ttft_ms: float | None = None
    attempts: int = 0
    ok: bool = False
    error: str | None = None
    rate_limited_s: float = 0.0
    blocked: bool = False


@dataclass
class Extraction:
    intent: str = "unclear"
    fields: dict = field(default_factory=dict)
    reply: str | None = None
    call: LLMCall | None = None


class LeakBlocked(RuntimeError):
    pass


def style(agent: dict, max_sentences: int) -> str:
    male = agent.get("gender", "male") == "male"
    return STYLE.format(name=agent["name"], gender="male" if male else "female", max_sentences=max_sentences,
                        example_verbs="करता हूँ, सकता हूँ, बताऊँगा" if male else "करती हूँ, सकती हूँ, बताऊँगी")


class DialogLLM:
    def __init__(self, llm, agent: dict, max_wait_429_s: float = 0.0, timeout_s: float = 8.0,
                 first_token_timeout_s: float = 3.0):
        self.llm = llm
        self.agent = agent
        self.max_wait_429_s = max_wait_429_s
        self.timeout_s = timeout_s
        self.first_token_timeout_s = first_token_timeout_s
        self.requests: list[dict] = []
        self.blocked: list[dict] = []

    @property
    def persona(self) -> str:
        return self.agent.get("persona", "")

    # ------------------------------------------------------------------ extract
    async def extract(self, *, asked: str, caller: str, history: list[str], interrupted: bool, expect: str,
                      slots: list[Slot], intents: list[Intent], next_steps: dict[str, str], facts: dict,
                      secrets: Secrets) -> Extraction:
        names = sorted(BUILTIN_INTENTS) + [i.name for i in intents]
        helps = [f"- {n}: {INTENT_HELP[n]}" for n in sorted(BUILTIN_INTENTS)] + \
                [f"- {i.name}: {i.describe}" for i in intents]
        props: dict = {"intent": {"type": "string", "enum": names}}
        field_help = []
        for s in slots:
            sch = s.llm_schema()
            if sch:
                props.update(sch)
                field_help.append(f"- {s.llm_help()}")
        reply_help = ""
        if next_steps:
            props["reply"] = {"type": ["string", "null"]}
            reply_help = REPLY_HELP.format(style=style(self.agent, 3))
        system = EXTRACT_SYSTEM.format(persona=self.persona, intents="\n".join(helps),
                                       fields="\n".join(field_help) or "(none)", reply_help=reply_help)
        user = self._context(asked, history, interrupted)
        user += f"The agent was asking for: {expect}.\nCaller said: \"{caller}\""
        if next_steps:
            user += "\n\nNEXT (what the reply must do, by intent):\n" + "\n".join(
                f"- {k}: {v}" for k, v in next_steps.items())
            user += f"\nFACTS: {json.dumps(facts, ensure_ascii=False) if facts else 'none'}"
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        schema = {"type": "object", "properties": props, "required": ["intent"], "additionalProperties": False}
        call = LLMCall("extract")
        out = Extraction(call=call)
        t0 = time.perf_counter_ns()
        for _ in range(2):
            try:
                text = await self._complete(messages, secrets, call, max_tokens=500, response_format={
                    "type": "json_schema", "json_schema": {"name": "turn", "strict": False, "schema": schema}})
            except LeakBlocked:
                call.blocked = True
                break
            except (LLMError, asyncio.TimeoutError, OSError) as e:
                call.error = repr(e)[:300]
                if isinstance(e, LLMError) and e.status == 400:
                    continue
                break
            parsed = parse_json(text, names)
            if parsed is not None:
                out.intent = parsed["intent"]
                out.fields = {k: v for k, v in parsed.items() if k not in ("intent", "reply")}
                r = parsed.get("reply")
                out.reply = r.strip() if isinstance(r, str) and r.strip() else None
                call.ok = True
                break
            call.error = f"invalid: {text[:200]}"
        call.ms = (time.perf_counter_ns() - t0) / 1e6
        return out

    # ------------------------------------------------------------------ generate
    async def generate(self, *, history: list[str], caller: str | None, happened: str, steps: list[tuple[str, str]],
                       facts: dict, secrets: Secrets, call: LLMCall, said_before: str = "") -> AsyncIterator[str]:
        """Stream the agent's next words. steps: (goal, example) in order."""
        system = GENERATE_SYSTEM.format(name=self.agent["name"], persona=self.persona,
                                        style=style(self.agent, 2 * len(steps) + 1),
                                        facts=json.dumps(facts, ensure_ascii=False) if facts else "none")
        user = ""
        if history:
            user += "Earlier in the call:\n" + "\n".join(history[-6:]) + "\n"
        if caller is not None:
            user += f"Caller just said: \"{caller}\"\n"
        if happened:
            user += f"What happened: {happened}\n"
        if said_before:
            user += f"The agent has just said (don't repeat it): \"{said_before}\"\n"
        user += "Now say, in this order:\n" + "\n".join(
            f"{k + 1}. {g}" + (f" Example: \"{ex}\"" if ex else "") for k, (g, ex) in enumerate(steps))
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        payload = json.dumps(messages, ensure_ascii=False)
        if leaks(payload, secrets):
            self.blocked.append({"messages": messages})
            call.blocked = True
            return
        t0 = time.perf_counter_ns()
        call.attempts += 1
        self.requests.append({"messages": messages, "t_ns": t0})
        stats = LLMStats()
        self.requests[-1]["stats"] = stats       # Groq's token counts and rate-limit headers, for reports
        it = self.llm.stream(messages, stats=stats, max_tokens=300, temperature=0.4).__aiter__()
        try:
            first = await asyncio.wait_for(it.__anext__(), self.first_token_timeout_s)
            call.ttft_ms = (time.perf_counter_ns() - t0) / 1e6
            yield first
            while True:
                try:
                    piece = await asyncio.wait_for(it.__anext__(), self.timeout_s)
                except StopAsyncIteration:
                    break
                yield piece
            call.ok = True
        except StopAsyncIteration:
            call.error = "empty"
        except (LLMError, asyncio.TimeoutError, OSError) as e:
            call.error = repr(e)[:300]
            if isinstance(e, LLMError) and e.status == 429:
                call.rate_limited_s = -1.0           # marked: this turn waited on (or hit) a rate limit
        finally:
            call.ms = (time.perf_counter_ns() - t0) / 1e6
            if hasattr(it, "aclose"):
                await it.aclose()

    # ------------------------------------------------------------------ plumbing
    @staticmethod
    def _context(asked: str, history: list[str], interrupted: bool) -> str:
        lines = []
        if history:
            lines.append("Earlier in the call:\n" + "\n".join(history[-4:]))
        note = " (the caller interrupted before hearing all of it)" if interrupted else ""
        lines.append(f"The agent's last words{note}: \"{asked}\"")
        return "\n".join(lines) + "\n"

    async def _complete(self, messages: list[dict], secrets: Secrets, call: LLMCall, **kw) -> str:
        payload = json.dumps(messages, ensure_ascii=False)
        if leaks(payload, secrets):
            self.blocked.append({"messages": messages})
            raise LeakBlocked("private value in an LLM request")
        waited = 0.0
        while True:
            call.attempts += 1
            stats = LLMStats()
            self.requests.append({"messages": messages, "t_ns": time.perf_counter_ns(), "stats": stats})
            try:
                return await asyncio.wait_for(self.llm.complete(messages, stats=stats, **kw), self.timeout_s)
            except LLMError as e:
                wait = e.retry_after_s if e.retry_after_s is not None else 2.0
                if e.status == 429 and waited + wait <= self.max_wait_429_s:
                    await asyncio.sleep(wait)
                    waited += wait
                    call.rate_limited_s += wait
                    continue
                raise


def parse_json(text: str, intents: list[str]) -> dict | None:
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(obj, dict) or obj.get("intent") not in intents:
        return None
    return obj
