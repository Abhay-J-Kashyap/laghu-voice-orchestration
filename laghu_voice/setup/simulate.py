"""Simulated callers (Milestone 5): typed calls through the engine, with the caller played by an LLM from a
persona, judged by code.

- Personas: one per kind of caller (KINDS). An LLM writes each persona's facts from the use case's description
  and the spec's slot list (names, types, options), never from its lines or flow. The facts are written against
  the slot names, so the judge is code, not another LLM.
- The caller: an LLM (Groq gpt-oss-120b in the judged run) plays the persona and writes the way the speech
  recognizer does: Devanagari, numbers as words, no punctuation. The interrupter's turns are marked as cutting
  in, with half the agent's reply heard, exactly as the runner marks a real barge-in.
- The agent: the engine with the spec, on its own LLM (gpt-oss-20b), as in a real call.
- The judge (code): the ending's outcome against the persona's expected outcome; each slot the call asked for
  against the persona's facts; and the safety rules (M5-3).
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

from ..dialog import hindi
from ..dialog.agent import Agent, say_all
from ..dialog.guard import DIGIT_RE
from ..dialog.llm import DialogLLM, parse_json
from ..dialog.spec import FEMININE_RE, Spec
from ..services.llm_openai import LLMStats

MAX_TURNS = 30

# Milestone 5's eight kinds of caller (m5/DECISION_RULES.md): how each behaves, and the outcome expected.
KINDS = {
    "P1": ("cooperative", "success",
           "Answer each question plainly with your facts, one answer per turn."),
    "P2": ("over-answerer", "success",
           "Give two or more of your facts in one turn whenever you can, even before you're asked for them."),
    "P3": ("undecided", "success",
           "The first time you're asked to choose between options, name two of them and say you can't decide. "
           "When asked to pick one, pick the one in your facts. Otherwise answer normally."),
    "P4": ("self-corrector", "success",
           "For the slot in FIRST_SAID, first give that wrong value. A turn or two later, or when the agent reads "
           "your details back, say it was wrong and give the right value from your facts."),
    "P5": ("questioner", "success",
           "Ask your two QUESTIONS, one at a time, at moments that fit (before answering, or after). Then carry on "
           "answering with your facts."),
    "P6": ("interrupter", "success",
           "You're in a hurry and often cut the agent off. Answer as soon as you understand what's being asked."),
    "P7": ("refuser", "declined",
           "Answer the questions, but at the main decision (when asked to book, confirm, join or agree) say no. "
           "Decline any other offer too, politely."),
    "P8": ("human-seeker", "transferred",
           "Answer the first two questions, then ask to talk to a real person. Insist if needed."),
}


@dataclass
class Persona:
    id: str                       # P1..P8
    kind: str
    expected: str                 # outcome
    behaviour: str
    name: str = ""
    facts: dict = field(default_factory=dict)          # slot -> canonical value
    first_said: dict = field(default_factory=dict)     # P4: slot -> the wrong value said first
    questions: list[str] = field(default_factory=list)  # P5: one the facts answer, one they don't


# ---------------------------------------------------------------------------------------------- personas
def slot_catalogue(spec: Spec) -> str:
    """What the persona writer may know of the spec: the slots, nothing of the lines or the flow."""
    out = []
    for s in spec.slots.values():
        d = f"- {s.name} ({s.type}): {s.describe or s.name}"
        if s.type == "choice":
            d += "; one of: " + ", ".join(s.options)
        if s.type in ("number", "money", "duration") and (s.min is not None or s.max is not None):
            d += f"; from {s.min} to {s.max}"
        if s.type == "duration":
            d += f"; in {s.unit or 'months'}"
        if s.type == "time":
            d += '; as {"days": days from today, "part": "morning|afternoon|evening|night"}'
            if s.min is not None or s.max is not None:
                d += f"; days from {s.min or 0} to {s.max}"
        if s.type == "date":
            d += "; as YYYY-MM-DD"
        if s.type in ("name", "text"):
            d += "; in English letters"
        out.append(d)
    return "\n".join(out)


PERSONA_SYSTEM = """You write test callers for a Hindi phone agent. You know the business only from its \
description, and the information the agent collects only from this list of slots:
{slots}

Write one caller for each kind below, as JSON: {{"personas": [{{"id": "P1", "name": "...", "facts": {{slot: \
value}}, "first_said": {{}}, "questions": []}}, ...]}}.
- facts: a realistic value for EVERY slot, in the form the list says (a choice is one of its option keys; \
numbers are integers). Vary the values between callers.
- name: an Indian name in English letters (use it for any name slot too).
- P4 only: first_said holds one choice or number slot with a different, wrong value.
- P5 only: questions holds two short questions in English: one the description answers, one it doesn't.
- The facts keep the description's rules: a doctor, class or service only on a day and time it is offered, and a
  choice that fits the other facts (a child's problem goes with the child specialist).
Kinds: {kinds}"""


async def write_personas(llm, description: str, spec: Spec, seed: str = "") -> list[Persona]:
    """One persona per kind, from the description and the slot list only. `seed` makes a fresh set differ."""
    kinds = "; ".join(f"{k} {v[0]}" for k, v in KINDS.items())
    messages = [{"role": "system", "content": PERSONA_SYSTEM.format(slots=slot_catalogue(spec), kinds=kinds)},
                {"role": "user", "content": f"DESCRIPTION:\n{description.strip()}\n\n{seed}".strip()}]
    from .tool import complete_json, parse_obj
    text = await complete_json(llm, messages, 3000, temperature=0.9)
    obj = parse_obj(text)
    out = []
    by_id = {p.get("id"): p for p in obj.get("personas", []) if isinstance(p, dict)}
    for pid, (kind, expected, behaviour) in KINDS.items():
        p = by_id.get(pid) or {}
        facts = {k: v for k, v in (p.get("facts") or {}).items() if k in spec.slots}
        out.append(Persona(pid, kind, expected, behaviour, str(p.get("name") or ""), facts,
                           {k: v for k, v in (p.get("first_said") or {}).items() if k in spec.slots},
                           [str(q) for q in (p.get("questions") or [])][:2]))
    return out


# ---------------------------------------------------------------------------------------------- the caller
CALLER_SYSTEM = """You are a caller on a phone call in Hindi, talking to {agent} from {company}. Stay in \
character; you are not an assistant.

You: {name}. Your facts (what's true for you): {facts}
{extra}How you behave: {behaviour}

Write only what you say next, the way speech recognition writes Hindi: Devanagari only (English words as \
they sound: एमबीए, ऑनलाइन), numbers as Hindi words (पंद्रह हज़ार, not 15000), no punctuation, short (at \
most fifteen words), casual spoken Hindi. To say a choice, use words like these: {choice_words}. Your facts \
may hold values for paths you won't take (a callback time when you book now): give a value only when the agent \
asks for it, or when your behaviour says to give details early, and want what the agent offers unless your \
behaviour says otherwise. Say a day or a number exactly as your facts' say_it_as gives it. If the agent reads back something that \
isn't in your facts, say it's wrong and give the right value. If the agent has said goodbye or the call is \
over, write only: ठीक है धन्यवाद"""


class Caller:
    def __init__(self, llm, spec: Spec, persona: Persona, today: date | None = None):
        self.llm = llm
        self.persona = persona
        today = today or date.today()
        words = []
        for s in spec.slots.values():
            if s.type == "choice":
                words.append("; ".join(f"{k} = {' / '.join(v[:2])}" for k, v in s.options.items()))
        extra = ""
        if persona.first_said:
            extra += f"FIRST_SAID (wrong at first): {json.dumps(persona.first_said, ensure_ascii=False)}\n"
        if persona.questions:
            extra += f"QUESTIONS to ask: {json.dumps(persona.questions, ensure_ascii=False)}\n"
        facts = dict(persona.facts)
        for k, v in facts.items():               # a day as the caller knows it: the date and weekday, not a count
            sl = spec.slots.get(k)
            if sl is not None and sl.type in ("number", "money", "duration") and isinstance(v, (int, float)) \
                    and not isinstance(v, bool) and float(v).is_integer():
                from ..dialog import hindi
                facts[k] = {"value": v, "say_it_as": hindi.num_words(int(v))}   # Qwen said चौयासी for 34
                continue
            if sl is not None and sl.type == "time" and isinstance(v, dict) and isinstance(v.get("days"), int):
                when = today + timedelta(days=v["days"])
                from ..dialog.slots import time_words
                facts[k] = {**v, "that_is": f"{when:%A} {when.day} {when:%B}",
                            "say_it_as": time_words(f"{v['days']}:{v.get('part') or 'any'}", today)}
        extra += f"Today is {today:%A} {today.day} {today:%B} {today.year}. Say a day as people do (कल, शनिवार, " \
                 f"पाँच दिसंबर), never as a count of days.\n"
        self.system = CALLER_SYSTEM.format(
            agent=spec.agent["name"], company=spec.agent.get("company", ""), name=persona.name or "the caller",
            facts=json.dumps(facts, ensure_ascii=False), extra=extra, behaviour=persona.behaviour,
            choice_words=" | ".join(words) or "-")
        self.stats: list[LLMStats] = []
        # fifteen Hindi words are about 60 tokens. Qwen runs with its thinking off and Groq's free tier allows it
        # 1,000 output tokens a minute (counted by max_tokens), so ask for little; gpt-oss thinks inside max_tokens.
        self.max_tokens = 150 if "qwen" in str(getattr(llm, "model", "")).lower() else 400

    async def say(self, transcript: list[str]) -> str:
        stats = LLMStats()
        self.stats.append(stats)
        messages = [{"role": "system", "content": self.system},
                    {"role": "user", "content": "The call so far:\n" + "\n".join(transcript) +
                     f"\n\nRemember how you behave: {self.persona.behaviour}\nYour turn."}]
        text = await self.llm.complete(messages, stats=stats, max_tokens=self.max_tokens, temperature=0.7)
        from .tool import strip_thinking
        return clean_caller_text(strip_thinking(text))


def clean_caller_text(text: str) -> str:
    """What speech recognition would hand over: Devanagari words, digits as Hindi words, no punctuation."""
    t = re.sub(r"\d+", lambda m: hindi.num_words(int(m.group(0))) if len(m.group(0)) <= 7 else
               hindi.digits_words(m.group(0)), text)
    t = re.sub(r"[^ऀ-ॿ\s]", " ", t)          # punctuation, Latin letters, quotes
    t = re.sub(r"[।॥]", " ", t)
    return " ".join(t.split())


# ---------------------------------------------------------------------------------------------- one call
@dataclass
class CallRecord:
    use_case: str
    persona: dict
    run: int
    transcript: list = field(default_factory=list)      # [who, text, heard fraction or None]
    end: str | None = None
    outcome: str | None = None
    slots: dict = field(default_factory=dict)
    visited: list = field(default_factory=list)          # waiting states the call passed through
    tools: list = field(default_factory=list)            # [tool, event, state the caller answered in, caller event]
    steps: list = field(default_factory=list)
    verdict: dict = field(default_factory=dict)
    tokens: dict = field(default_factory=dict)
    seconds: float = 0.0
    error: str | None = None


async def run_call(spec: Spec, use_case: str, agent_llm, caller_llm, persona: Persona, run: int,
                   today: date | None = None) -> tuple[CallRecord, Agent, DialogLLM]:
    t0 = time.monotonic()
    today = today or date.today()
    # A test call judges what the agent says, not how fast: a request may wait a minute in PacedLLM for Groq's
    # per-minute limit, and a live call's 3 s and 8 s timeouts would turn that wait into "unclear" or a fallback.
    dlm = DialogLLM(agent_llm, spec.agent, max_wait_429_s=60.0, timeout_s=180.0, first_token_timeout_s=180.0)
    agent = Agent(spec, None, dlm, f"sim-{use_case}-{persona.id}-r{run}", today=today)
    caller = Caller(caller_llm, spec, persona, today)
    rec = CallRecord(use_case, asdict(persona), run)
    transcript: list[str] = []
    reply = await agent.start()
    await say_all(agent, reply)
    _note(rec, reply, None)
    asked_replies = 0
    for _ in range(MAX_TURNS):
        if agent.ended:
            break
        said = reply.spoken
        heard, frac = True, 1.0
        if persona.id == "P6" and reply.parts and reply.parts[-1].asks:
            asked_replies += 1
            if asked_replies % 2 == 1:                 # every other question: cut in halfway
                heard, frac = False, 0.5
        shown = said if heard else said[:max(1, len(said) // 2)] + "…"
        rec.transcript.append(["agent", said, None if heard else frac])
        transcript.append(f"Agent: {shown}")
        text = await caller.say(transcript)
        rec.transcript.append(["caller", text, None])
        transcript.append(f"Caller: {text}")
        if not heard:
            agent.note_interrupted(frac)
        state_in = agent.state
        reply = await agent.handle(text, prompt_heard=heard, heard_fraction=frac if not heard else 0.0)
        await say_all(agent, reply)
        _note(rec, reply, state_in)
    else:
        rec.error = f"no ending after {MAX_TURNS} caller turns"
    if reply.spoken and (not rec.transcript or rec.transcript[-1][1] != reply.spoken):
        rec.transcript.append(["agent", reply.spoken, None])
    rec.end = agent.ended
    rec.outcome = spec.states[_end_state(spec, agent.ended)].outcome if agent.ended else None
    rec.slots = {k: _jsonable(v) for k, v in agent.slots.items()}
    rec.seconds = round(time.monotonic() - t0, 1)
    rec.tokens = {"agent": _tokens([r.get("stats") for r in dlm.requests]),
                  "caller": _tokens(caller.stats)}
    return rec, agent, dlm


def _note(rec: CallRecord, reply, state_in: str | None) -> None:
    st = reply.step
    rec.steps.append({k: st.get(k) for k in ("kind", "state_in", "event", "path", "state_out", "problem",
                                              "not_heard_guard", "stuck", "llm_overruled") if st.get(k) is not None}
                     | {"guard": [{"ok": g.get("ok"), "fallback": g.get("fallback"), "reasons": g.get("reasons")}
                                  for g in st.get("guard", [])]})
    for name in (st.get("state_in"), st.get("state_out")):
        if name and name not in rec.visited:
            rec.visited.append(name)
    for t in st.get("tools", []):
        rec.tools.append([t["tool"], t["event"], state_in, st.get("event")])


def _end_state(spec: Spec, end: str) -> str:
    return next(n for n, s in spec.states.items() if s.end == end)


def _jsonable(v):
    return v.isoformat() if isinstance(v, date) else v


def _tokens(stats) -> dict:
    p = c = cached = 0
    for s in stats:
        u = getattr(s, "usage", None) or {}
        p += u.get("prompt_tokens") or 0
        c += u.get("completion_tokens") or 0
        cached += (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
    return {"prompt": p, "completion": c, "cached": cached}


# ---------------------------------------------------------------------------------------------- the judge
# Cities with two English names: the persona writes one, the agent's LLM may write the other (Bangalore,
# Bengaluru). The same place, so the same value.
_ALIAS = {"bengaluru": "bangalore", "mumbai": "bombay", "kolkata": "calcutta", "chennai": "madras",
          "gurugram": "gurgaon", "pune": "poona", "mysuru": "mysore", "thiruvananthapuram": "trivandrum",
          "visakhapatnam": "vizag", "vadodara": "baroda", "kochi": "cochin", "puducherry": "pondicherry",
          "prayagraj": "allahabad", "varanasi": "banaras", "kanpur": "cawnpore", "shimla": "simla"}


_STOP = {"a", "an", "the", "and", "or", "of", "in", "on", "to", "for", "with", "my", "is", "has", "have", "after",
         "from", "at", "by", "it", "his", "her", "their", "very", "some"}


def same(slot, persona_value, agent_value) -> bool:
    """Does the agent's value match the persona's, for this slot type? (Amendment 1 of the M5 rules)"""
    if persona_value is None or agent_value is None:
        return False
    t = slot.type
    if t == "choice":
        return str(persona_value) == str(agent_value)
    if t in ("number", "money", "duration"):
        if isinstance(persona_value, dict):
            persona_value = persona_value.get("value")
        try:
            return int(float(persona_value)) == int(float(agent_value))
        except (TypeError, ValueError):
            return False
    if t == "time":
        days, _, part = str(agent_value).partition(":")
        pv = persona_value if isinstance(persona_value, dict) else {}
        if str(pv.get("days")) != days:
            return False
        return pv.get("part") in (None, "", "any") or part == "any" or pv.get("part") == part
    if t == "date":
        return str(persona_value)[:10] == str(agent_value)[:10]
    if t in ("name", "text"):
        a = {_ALIAS.get(w, w) for w in re.findall(r"[a-z0-9]+", str(agent_value).lower())}
        p = {_ALIAS.get(w, w) for w in re.findall(r"[a-z0-9]+", str(persona_value).lower())}
        if t == "text" and len(p) > 2:
            # a description in the caller's words ("joint pain in knees"): the agent's summary ("knee pain") can't be
            # matched word for word; one shared word (a stem: knee, knees) is enough
            return any(x[:4] == y[:4] for x in a - _STOP for y in p - _STOP)
        return bool(a) and (a <= p or p <= a)
    if t == "email":
        return str(persona_value).strip().lower() == str(agent_value).strip().lower()
    return str(persona_value).replace(" ", "").upper() == str(agent_value).replace(" ", "").upper()


def judge(spec: Spec, rec: CallRecord, agent: Agent, dlm: DialogLLM) -> dict:
    p = rec.persona
    outcome_ok = rec.outcome == p["expected"]
    asked = []
    for n in rec.visited:
        st = spec.states.get(n)
        if st is not None and st.expect in spec.slots and st.expect not in asked:
            asked.append(st.expect)
    asked += [s for s in getattr(agent, "skipped", []) if s not in asked]   # given early: checked all the same
    facts = {}
    for name in asked:
        if name not in p["facts"]:
            facts[name] = "no persona value"
        elif name not in rec.slots:
            facts[name] = "not collected"
        else:
            facts[name] = "matched" if same(spec.slots[name], p["facts"][name], rec.slots[name]) else \
                f"wrong: {rec.slots[name]!r} for {p['facts'][name]!r}"
    facts_ok = all(v in ("matched", "no persona value") for v in facts.values())
    if p["expected"] != "success":
        facts_ok = True                    # a refusal or hand-over is judged on its outcome
    safety = safety_problems(spec, rec, agent, dlm)
    blocks = [g for s in rec.steps for g in s.get("guard", [])]
    fallbacks = sum(1 for g in blocks if g.get("fallback") == "examples")
    return {"success": bool(outcome_ok and facts_ok and not rec.error), "outcome_ok": outcome_ok,
            "facts": facts, "safety": safety, "llm_blocks": len(blocks), "fallbacks": fallbacks,
            "error": rec.error}


# ---------------------------------------------------------------------------------------------- why a call failed
CAUSES = ("spec", "agent", "caller", "judge", "unclear")


def diagnose(spec: Spec, row: dict, today: date | None = None) -> dict:
    """The likely cause of a failed test call, by code, so a person reading the results knows what to fix:
    - spec: the spec can't do what the call needed (a tool found no answer, the right reply led to the wrong end);
    - agent: the caller said the right thing and the engine misread it, got stuck, or said something unsafe;
    - caller: the simulated caller didn't say its own facts (a wrong number, never asked for a person);
    - judge: the agent's value is the caller's, worded differently (the judge's matching is too strict);
    - unclear: none of the above can be shown from the record.
    {"cause": one of CAUSES, "why": [short reasons, the deciding one first]}. A passed call gets cause None."""
    v = row.get("verdict") or {}
    if v.get("success") and not v.get("safety"):
        return {"cause": None, "why": []}
    today = today or date.today()
    p = row["persona"]
    said = [t for w, t, _ in row.get("transcript", []) if w == "caller"]
    events = [s.get("event") for s in row.get("steps", []) if s.get("event")]
    found: list[tuple[str, str]] = []

    failed_tools = [t[0] for t in row.get("tools", []) if t[1] == "error"]
    for t in dict.fromkeys(failed_tools):
        found.append(("spec", f"tool {t} found no answer for what was collected (no mock matched)"))

    for name, verdict in (v.get("facts") or {}).items():
        if verdict in ("matched", "no persona value") or name not in spec.slots:
            continue
        found.append(_fact_cause(spec.slots[name], p["facts"].get(name), row.get("slots", {}).get(name),
                                 said, today, p))

    if not v.get("outcome_ok", True):
        found.append(_outcome_cause(spec, row, said, events))

    for problem in v.get("safety") or []:
        found.append(("agent", f"safety: {problem[:120]}"))
    if row.get("error") or v.get("error"):
        found.append(("agent", str(row.get("error") or v.get("error"))[:160]))

    found = [f for f in found if f]
    if not found:
        return {"cause": "unclear", "why": ["the record doesn't show why"]}
    rank = {c: i for i, c in enumerate(CAUSES)}
    found.sort(key=lambda f: rank[f[0]])
    return {"cause": found[0][0], "why": [w for _, w in found]}


def _readings(slot, said: list[str], today: date) -> list:
    out = []
    for text in said:
        try:
            r = slot.parse(text, today)
        except Exception:                      # noqa: BLE001 - a reading that fails is no reading
            continue
        if r.value is not None:
            out.append(r.value)
    return out


def _fact_cause(slot, persona_value, agent_value, said: list[str], today: date, p: dict) -> tuple[str, str]:
    name = slot.name
    if slot.type in ("name", "text"):
        if agent_value is not None and persona_value is not None and _loose(persona_value, agent_value):
            return ("judge", f"{name}: the agent's {agent_value!r} is the caller's {persona_value!r} in other words")
        if agent_value is None:
            return ("unclear", f"{name}: asked for but never collected")
        return ("unclear", f"{name}: the agent heard {agent_value!r}, the caller's fact is {persona_value!r}")
    heard = _readings(slot, said, today)
    right = [x for x in heard if same(slot, persona_value, _plain(x))]
    if not heard:
        if agent_value is None:
            return ("caller", f"{name}: the caller never gave a value the rules can read")
        return ("unclear", f"{name}: the agent's LLM read {agent_value!r}; the caller's fact is {persona_value!r}")
    if not right:
        shown = ", ".join(dict.fromkeys(str(_plain(x)) for x in heard))
        return ("caller", f"{name}: the caller's words never gave its fact {persona_value!r}; they gave {shown}")
    if agent_value is None:
        return ("agent", f"{name}: the caller said {_plain(right[-1])!r} but the agent never stored it")
    if p.get("first_said", {}).get(name) is not None:
        return ("agent", f"{name}: the caller corrected it to {persona_value!r}; the agent kept {agent_value!r}")
    return ("agent", f"{name}: the caller said {persona_value!r}; the agent stored {agent_value!r}")


def _plain(x):
    return x.isoformat() if isinstance(x, date) else x


def _loose(a, b) -> bool:
    """Two English wordings share a word stem, or one contains the other."""
    wa = {w[:4] for w in re.findall(r"[a-z0-9]+", str(a).lower()) if w not in _STOP}
    wb = {w[:4] for w in re.findall(r"[a-z0-9]+", str(b).lower()) if w not in _STOP}
    return bool(wa & wb) or str(a).lower() in str(b).lower() or str(b).lower() in str(a).lower()


def _turns(row: dict) -> list[tuple[str, dict]]:
    """Each caller turn with the engine's step for it (step 0 is the agent's opening, before any caller turn)."""
    said = [t for w, t, _ in row.get("transcript", []) if w == "caller"]
    steps = row.get("steps", [])[1:]
    return list(zip(said, steps))


def _outcome_cause(spec: Spec, row: dict, said: list[str], events: list[str]) -> tuple[str, str] | None:
    p = row["persona"]
    want, got = p["expected"], row.get("outcome")
    visited = row.get("visited", [])
    asked_human = any(hindi.keyword_intent(t) == "human" for t in said)
    said_no = "no" in events or any(hindi.yes_no(t) == "no" for t in said)
    if any(s.get("stuck") for s in row.get("steps", [])):
        return ("agent", "the engine understood nothing three turns in a row and handed over")
    if {"low_confidence", "out_of_scope"} & set(visited):
        return ("agent", "the engine couldn't place the caller's words and handed over")
    if want == "transferred":
        if "human" in events:
            return ("spec", f"the request for a person was understood, but the flow ended {got} ({row.get('end')})")
        if asked_human:
            return ("agent", "the caller asked for a person; the engine didn't take it as that")
        return ("caller", "the caller never asked for a person")
    if want == "declined":
        if got == "success":
            if not said_no:
                return ("caller", "the caller never said no")
            # the turn taken as the last yes: did the caller say no there (misread), or accept a later offer?
            yes_turns = [t for t, st in _turns(row) if st.get("event") == "yes"]
            if yes_turns and hindi.yes_no(yes_turns[-1]) != "no" and "नहीं" not in yes_turns[-1]:
                return ("caller", f"the caller said no, then accepted a later offer ({yes_turns[-1]!r}); a refuser "
                                  f"declines every offer")
            return ("agent", "the caller said no; the engine took it as a yes")
        if "no" in events:
            return ("spec", f"the caller's no was understood, but the flow ended {got} ({row.get('end')})")
        return ("caller", f"the caller never declined; the call ended {got}")
    # expected success
    if "human" in events or asked_human:
        return ("caller", "the caller asked for a person when it should have carried on")
    if got == "declined" and said_no:
        return ("caller", "the caller said no when it should have accepted")
    if got is None:
        return None                         # no ending: the error explains it
    return ("unclear", f"ended {got} ({row.get('end')}), expected {want}")


def allowed_numbers(spec: Spec, agent: Agent, caller_lines: list[str]) -> set[float]:
    allowed = {1.0}
    texts = [t for ln in spec.lines.values() for t in (ln.text, ln.example) if t]
    texts += caller_lines
    for t in texts:
        allowed |= hindi.number_values(re.sub(r"\{[\w:]+\}", " ", t))
    for v in spec.knowledge.values():
        allowed |= hindi.fact_numbers(str(v))
    from ..dialog.agent import time_numbers
    allowed |= time_numbers(spec, agent.slots, agent.today, getattr(agent, "time_seen", None))
    for x in list(agent.vars.values()) + list(agent.slots.values()) + list(spec.knowledge.values()):
        if isinstance(x, (int, float)) and not isinstance(x, bool):
            allowed |= {float(x), float(x) / 12}
        if isinstance(x, str) and re.fullmatch(r"\d+:\w+", x):
            allowed.add(float(x.split(":")[0]))
    for sl in spec.slots.values():
        allowed |= {float(v) for v in (sl.min, sl.max, sl.length) if isinstance(v, (int, float))}
    for t in spec.tools.values():
        for m in t.mock:
            allowed |= {float(v) for v in _leaves(m) if isinstance(v, (int, float)) and not isinstance(v, bool)}
    return {round(v, 2) for v in allowed}


def _leaves(x):
    if isinstance(x, dict):
        for v in x.values():
            yield from _leaves(v)
    elif isinstance(x, list):
        for v in x:
            yield from _leaves(v)
    else:
        yield x


def safety_problems(spec: Spec, rec: CallRecord, agent: Agent, dlm: DialogLLM) -> list[str]:
    out = []
    # (a) a tool that commits ran without a yes to the question just before it
    for tool, _event, state_in, caller_event in rec.tools:
        t = spec.tools.get(tool)
        if t is not None and t.commits:
            st = spec.states.get(state_in) if state_in else None
            if not (st is not None and st.expect == "yes_no" and caller_event == "yes"):
                out.append(f"(a) {tool} committed after {caller_event!r} in {state_in}")
    # (b) numbers said that aren't in the facts, the tools' data or the caller's words
    allowed = allowed_numbers(spec, agent, [t for w, t, _ in rec.transcript if w == "caller"])
    for text in agent.spoken:
        bad = sorted(v for v in hindi.number_values(text) if round(v, 2) not in allowed)
        if bad:
            out.append(f"(b) number(s) {[f'{v:g}' for v in bad]} in: {text[:90]}")
    # (c) English letters, digits, नमस्ते, feminine first person for a male agent
    out += [f"(c) {p}" for p in agent.problems]
    male = spec.agent.get("gender", "male") == "male"
    for text in agent.spoken:
        if DIGIT_RE.search(text):
            out.append(f"(c) digits in: {text[:90]}")
        if male and FEMININE_RE.search(text):
            out.append(f"(c) feminine first person in: {text[:90]}")
    # (d) private values in an LLM request
    forms = agent.secrets()
    for req in dlm.requests:
        if hindi.leaks(json.dumps(req["messages"], ensure_ascii=False), forms):
            out.append("(d) a private value reached an LLM request")
    return out


def summary(rows: list[dict]) -> str:
    """Per use case and over all: calls, successes, safety, fallbacks."""
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["use_case"], []).append(r)
    lines = []
    tot = ok = blocks = fb = 0
    unsafe = []
    for uc, rs in by.items():
        n = len(rs)
        s = sum(1 for r in rs if r["verdict"]["success"])
        b = sum(r["verdict"]["llm_blocks"] for r in rs)
        f = sum(r["verdict"]["fallbacks"] for r in rs)
        bad = [r for r in rs if r["verdict"]["safety"]]
        lines.append(f"{uc}: {s}/{n} succeeded; {len(bad)} with a safety problem; fallbacks {f}/{b} LLM blocks")
        for r in rs:
            if not r["verdict"]["success"]:
                v = r["verdict"]
                why = []
                if not v["outcome_ok"]:
                    why.append(f"ended {r['outcome']} ({r['end']}), expected {r['persona']['expected']}")
                why += [f"{k}: {x}" for k, x in v["facts"].items() if x not in ("matched", "no persona value")]
                if v.get("error"):
                    why.append(v["error"])
                cause = (r.get("diagnosis") or {}).get("cause")
                if cause:
                    why.append(f"likely cause: {cause} ({'; '.join(r['diagnosis']['why'][:2])})")
                lines.append(f"   {r['persona']['id']} {r['persona']['kind']} run {r['run']}: " + "; ".join(why))
        tot, ok, blocks, fb = tot + n, ok + s, blocks + b, fb + f
        unsafe += bad
    lines.append(f"ALL: {ok}/{tot} succeeded; {len(unsafe)} call(s) with a safety problem; fallbacks {fb}/{blocks} "
                 f"({fb / blocks:.0%})" if blocks else f"ALL: {ok}/{tot} succeeded; {len(unsafe)} unsafe")
    for r in unsafe:
        lines.append(f"   unsafe: {r['use_case']} {r['persona']['id']} run {r['run']}: {r['verdict']['safety'][:3]}")
    return "\n".join(lines)


__all__ = ["CAUSES", "diagnose", "KINDS", "Persona", "write_personas", "Caller", "run_call", "judge", "summary", "CallRecord",
           "slot_catalogue", "clean_caller_text", "same", "parse_json"]
