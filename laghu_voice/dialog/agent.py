"""The dialog engine: runs any agent spec (agents/*.yaml) for one call (design doc: Dialog layer).

It knows nothing about loans or any other use case. Each caller turn:

1. understand: fixed rules first (the expected slot's parser, yes/no, requests for a human, the spec's own
   intent phrases). What they can't settle goes to the LLM, with private values masked.
2. validate: the slot type checks the value (range, shape); a bad value gets the spec's re-ask line for that
   problem, not a guess.
3. transition: the spec says where the answer leads; tools run on the way and their answer picks the next
   state. A backend still enforces its own rules.
4. respond: the lines of the states passed through. Fixed and template lines are said exactly; LLM lines
   are written from their goal, in one streamed call per turn (or in the same call as step 1, when the
   engine could foresee them), each sentence checked before it's spoken, the example said if a check fails.

`handle()` decides; `stream()` produces the words (so the first sentence can be spoken while the rest is
written).
"""
from __future__ import annotations

import logging
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import date

from ..text.segmenter import Segmenter
from . import hindi
from .guard import asks_question, check_answer, check_spoken
from .llm import DialogLLM, Extraction, LLMCall
from .slots import fmt, secrets_of
from .spec import Spec, State
from .tools import ToolRunner

log = logging.getLogger(__name__)
ANSWER_GOAL = ("Answer the caller's question in one or two sentences, using only FACTS; if FACTS don't have it, "
               "say that a colleague can help with that.")
# No example for answers: Groq copied the old one (a refusal) word for word even when FACTS had the answer
# (gym call 4, "कितने प्लान हैं?"). If the answer fails a check, the spec's question_fallback is said instead.
ANSWER_EXAMPLE = ""
AGAIN = ("Ask this again, briefly and in different words from before, with no acknowledgement or compliment "
         "(if the caller offered two or more options, name them and ask which one): ")
NOT_UNCLEAR = {"out_of_range", "range", "ambiguous"}      # the caller was clear; the value just can't be used
FOLLOWED_BY_PROMPT = {"unclear", "pick_one"}              # re-ask lines that don't ask the question themselves
# lines that only wrap a question ("I was asking:", "please hear it all"): a repeat says the question without them
WRAPPERS = {"was_asking", "unclear", "not_heard", "not_heard_guard", "repeat", "are_you_there", "hold_ok", "scope",
            "pick_one", "filler"}
# slot types whose answer, once the rules can read it, means the caller is done ("शाम", "परसों"); names, amounts
# and spelled values are often said in pieces, so they wait for the turn model
HINT_TYPES = {"choice", "duration"}
_VAR = re.compile(r"\{(\w+)(?::(\w+))?\}")


@dataclass
class Part:
    key: str
    text: str | None = None          # said exactly
    masked: str | None = None        # the same with private values as [...]
    goal: str | None = None          # written by the LLM from this goal
    example: str = ""                # ...in this style; said instead when the LLM fails
    asks: bool = False               # the question the caller must answer next
    fallback: str | None = None      # said instead when the LLM fails, if not the example


@dataclass
class Reply:
    parts: list[Part]
    end: str | None = None
    step: dict = field(default_factory=dict)
    caller: str | None = None        # masked
    happened: str = ""
    prefilled: dict = field(default_factory=dict)    # block keys -> words the extraction call already wrote
    spoken: str = ""                 # filled by stream()


class Agent:
    def __init__(self, spec: Spec, backend, llm: DialogLLM | None, call_id: str, today: date | None = None,
                 context: dict | None = None):
        self.spec = spec
        self.llm = llm
        self.call_id = call_id
        self.today = today or date.today()
        self.tools = ToolRunner(spec, backend, call_id)
        self.context = {**spec.context, **(context or {})}
        self.vars: dict = {}                 # saved tool values and the backend session
        self.private_saved: dict[str, str] = {}    # saved name -> secret kind (digits/pan/date)
        self.slots: dict = {}
        self.extras: dict = {}               # e.g. a name's Devanagari spelling
        self.heard: dict[str, set] = {}      # every value ever heard for each private slot
        self.private_values: dict[str, set] = {"pan": set(), "digits": set(), "date": set()}
        self.shown: dict = {}                # values the client may show (demo passcode)
        self.state: str | None = None
        self.ended: str | None = None
        self.history: list[str] = []
        self.tool_log: list = []
        self.spoken: list[str] = []
        self.problems: list[str] = []
        self.unclear = self.off_topic = self.reprompts = 0
        self.last_caller_text = ""
        self._last_said: tuple[str, str] = ("", "")
        self._arrival: list[Part] = []
        self._prev_waiting: str | None = None
        self._last_keys: set[str] = set()              # the lines of the previous reply
        self._core_said: dict[str, tuple[str, str]] = {}    # state -> its question as last said, without wrappers
        self._full_prompt = False
        self._heard_enough = True
        self._step: dict = {}
        t = spec.timing
        self.max_unclear = int(t.get("max_unclear", 3))
        self.max_off_topic = int(t.get("max_off_topic", 2))
        self.hangup_after = int(t.get("hangup_after_reprompts", 3))

    # ================================================================== deciding
    async def start(self) -> Reply:
        self._step = {"kind": "start", "tools": [], "llm": [], "guard": []}
        t0 = time.perf_counter_ns()
        out: list[Part] = []
        try:
            self.vars.update(await self.tools.start(self._vars()))
        except Exception as e:  # noqa: BLE001 - no backend: nothing useful can happen on this call
            log.error("backend session failed: %r", e)
            self._step["error"] = repr(e)[:300]
            await self._run(self.spec.global_.get("unavailable", "transfer_failed"), out)
            return self._reply(out, t0)
        self._step["backend_session"] = self.vars.get("session_id")
        await self._run(self.spec.start, out)
        return self._reply(out, t0)

    async def handle(self, text: str, prompt_heard: bool = True, heard_fraction: float = 0.0) -> Reply:
        """One caller turn. `prompt_heard` is False when the caller cut off the agent's last reply;
        `heard_fraction` is then about how much of it played."""
        t0 = time.perf_counter_ns()
        self._step = {"kind": "turn", "state_in": self.state, "caller": text, "prompt_heard": prompt_heard,
                      "tools": [], "llm": [], "guard": []}
        if self.ended or self.state is None:
            return Reply([], self.ended, self._step)
        st = self.spec.states[self.state]
        self.reprompts = 0
        self.last_caller_text = text
        # a state that needs its question heard: enough of it played? (the gym asks 85%, the loan all of it)
        self._heard_enough = prompt_heard or (st.require_heard > 0 and heard_fraction >= st.require_heard)
        self._full_prompt = bool(st.require_heard) and not self._heard_enough
        if not prompt_heard and self._heard_enough and st.require_heard:
            self._step["heard_fraction"] = round(heard_fraction, 2)
        masked = hindi.mask_for_llm(text, strict=self._strict(st))
        self.history.append(f"Caller: {masked}")
        out: list[Part] = []
        event, line, ex = await self._understand(st, text, prompt_heard, masked)
        self._step["event"] = event
        await self._dispatch(st, event, line, text, prompt_heard, out)
        r = self._reply(out, t0, caller=masked)
        if ex is not None and ex.reply:
            # the extraction call wrote words for the intent IT chose; use them only if the engine acted on that
            # same intent and is about to say the lines they were written for. (Groq once said "answer" without
            # the name: the engine stayed on "name" while the words asked the next question.)
            keys = self._first_llm_block(out)
            if keys and keys == ex.call_keys.get(event) and ex.intent == event:
                r.prefilled[keys] = ex.reply
            else:
                self._step["reply_unused"] = True
        return r

    async def on_silence(self) -> Reply:
        t0 = time.perf_counter_ns()
        self._step = {"kind": "silence", "state_in": self.state, "tools": [], "llm": [], "guard": []}
        if self.ended or self.state is None:
            return Reply([], self.ended, self._step)
        out: list[Part] = []
        self.reprompts += 1
        if self.reprompts > self.hangup_after:
            await self._run(self.spec.global_["silence"], out)
        else:
            out.append(self._part("are_you_there"))
            out.extend(self._prompts())
        return self._reply(out, t0, happened="the caller has been silent")

    def note_interrupted(self, heard_fraction: float) -> None:
        for k in range(len(self.history) - 1, -1, -1):
            if self.history[k].startswith("Agent: "):
                body = self.history[k][len("Agent: "):]
                self.history[k] = f"Agent: {body[:max(0, round(len(body) * heard_fraction))]}… [interrupted]"
                return

    def secrets(self) -> hindi.Secrets:
        return secrets_of(self.spec.slots, self.heard, self.private_values)

    # ------------------------------------------------------------------ understanding
    def _strict(self, st: State) -> bool:
        names = ([st.expect] if st.expect in self.spec.slots else []) + st.corrections
        return any(self.spec.slots[n].private for n in names)

    def _intent_by_phrase(self, st: State, text: str) -> str | None:
        toks = hindi.tokens(text)
        for it in self.spec.intents.values():
            if it.phrases and (it.name in st.on or it.name in self.spec.global_) and \
                    hindi._has(toks, hindi._phrases("|".join(it.phrases))):
                return it.name
        return None

    async def _understand(self, st: State, text: str, heard: bool, masked: str):
        """(event, line, extraction): event is a key of the state's `on`, a global request, or one of
        corrected, reask, not_heard, unclear, repeat, question, off_topic; line is the re-ask line."""
        if not text.strip():
            return "not_heard", None, None
        kw = hindi.keyword_intent(text)
        if kw in ("human", "repeat", "hold"):
            self._step["path"] = "rule"
            return kw, None, None
        custom = self._intent_by_phrase(st, text)
        if custom:
            self._step["path"] = "rule"
            return custom, None, None
        rule = self._rules(st, text)
        if rule is not None:
            self._step["path"] = "rule"
            return rule[0], rule[1], None
        if kw == "stop":
            self._step["path"] = "rule"
            return "stop", None, None
        if self.llm is None:
            self._step["path"] = "none"
            return "unclear", None, None
        self._step["path"] = "llm"
        ex = await self._extract(st, masked, heard)
        event, line = self._from_llm(st, ex)
        if event == "unclear" and _asks(text):
            # the LLM couldn't place it, but the caller asked something: answer from the facts, then ask again
            # (better than "I didn't understand" for "कोई और प्लान है तुम्हारे पास?")
            self._step["unclear_as_question"] = True
            event = "question"
        return event, line, ex

    def _set(self, name: str, value, extra: dict | None = None) -> None:
        self.slots[name] = value
        if extra:
            self.extras[name] = extra
        if self.spec.slots[name].private:
            self.heard.setdefault(name, set()).add(value)

    def _rules(self, st: State, text: str):
        if st.corrections:
            changed = False
            for name in st.corrections:
                p = self.spec.slots[name].parse(text, self.today)
                if p.value is not None and p.value != self.slots.get(name):
                    self._set(name, p.value)
                    changed = True
            if changed:
                return "corrected", None
        if st.expect == "yes_no":
            yn = hindi.yes_no(text)
            if yn:
                self._also(st, text)
                if len(hindi.tokens(text)) > 2 and any(n not in self.slots for n in st.also):
                    # "हाँ हाँ, मेरा नाम अभय है": more than a yes, and the rules can't read the rest (a name); the
                    # LLM reads both. Its call also writes the reply, so it costs about nothing.
                    return None
            return (yn, None) if yn else None
        slot = self.spec.slots.get(st.expect)
        if slot is None:
            return None
        p = slot.parse(text, self.today)
        if p.value is not None:
            self._set(slot.name, p.value, p.extra or None)
            self._also(st, text)
            return "answer", None
        if p.problem:
            return "reask", self._reask_line(slot, p.problem)
        return None

    def _reask_line(self, slot, problem: str) -> str:
        self._step["problem"] = problem
        default = "pick_one" if problem in ("range", "ambiguous") else "unclear"
        return slot.reask.get(problem, default)

    def _also(self, st: State, text: str) -> None:
        for name in st.also:
            p = self.spec.slots[name].parse(text, self.today, strict_unit=True)
            if p.value is not None:
                self._set(name, p.value)

    async def _extract(self, st: State, masked: str, heard: bool) -> Extraction:
        slot = self.spec.slots.get(st.expect)
        slots = [s for s in [slot] + [self.spec.slots[n] for n in st.also] if s is not None]
        intents = [i for i in self.spec.intents.values() if i.name in st.on or i.name in self.spec.global_]
        expect = "a yes or no" if st.expect == "yes_no" else (slot.describe or slot.name)
        if slot is not None and slot.private:
            expect += " (hidden from you as [...]; if they gave it, the intent is answer)"
        steps, keys = self._foresee(st, heard)
        ex = await self.llm.extract(asked=self._last_said[1], caller=masked, history=self.history[:-2],
                                    interrupted=not heard, expect=expect, slots=slots, intents=intents,
                                    next_steps=steps, facts=self._facts(), secrets=self.secrets())
        ex.call_keys = keys
        self._step["llm"].append({**ex.call.__dict__, "intent": ex.intent, "fields": sorted(ex.fields),
                                  "reply": ex.reply is not None})
        return ex

    def _from_llm(self, st: State, ex: Extraction):
        i, e = ex.intent, st.expect
        if i == "answer":
            slot = self.spec.slots.get(e)
            if slot is None:
                return "unclear", None
            if slot.private:                           # said, but the rules couldn't read it
                return "reask", self._reask_line(slot, "partial")
            p = slot.from_llm(ex.fields)
            if p.value is not None:
                self._set(slot.name, p.value, p.extra or None)
                self._also_llm(st, ex)
                return "answer", None
            if p.problem:
                return "reask", self._reask_line(slot, p.problem)
            return "unclear", None
        if i in ("yes", "no"):
            if e != "yes_no":
                return "unclear", None
            self._also_llm(st, ex)              # "हाँ, मेरा नाम अभय है": yes, and the name too
            return i, None
        if i in self.spec.intents:
            return (i, None) if (i in st.on or i in self.spec.global_) else ("unclear", None)
        return i, None                                  # human, repeat, question, off_topic, stop, unclear

    def _also_llm(self, st: State, ex: Extraction) -> None:
        for name in st.also:
            q = self.spec.slots[name].from_llm(ex.fields)
            if q.value is not None:
                self._set(name, q.value, q.extra or None)

    def turn_complete(self, text: str) -> bool:
        """Does this (speculative) transcript already answer the question being asked? The listener asks while
        the turn model still thinks the caller may go on, so a one-word answer ("शाम") needn't wait for the
        silence cap. Only the rules decide, and nothing is changed."""
        st = self.spec.states.get(self.state) if self.state and not self.ended else None
        if st is None or not text.strip():
            return False
        slot = self.spec.slots.get(st.expect)          # yes/no: no hint ("हाँ… लेकिन" is common)
        if slot is None or slot.type not in HINT_TYPES:
            return False
        toks = hindi.tokens(text)
        if toks and toks[-1] in _GOES_ON:                    # "सुबह या…": they're still talking
            return False
        # with its unit only: a bare "तीन" may be the start of "तीन… साल"
        return slot.parse(text, self.today, strict_unit=True).value is not None

    # ------------------------------------------------------------------ foreseeing the reply
    def _foresee(self, st: State, heard: bool = True) -> tuple[dict[str, str], dict[str, tuple]]:
        """For each likely intent, the LLM lines the engine would say next if no tool runs first, so the
        extraction call can write them too. Returns (instructions by intent, block keys by intent)."""
        steps, keys = {}, {}
        events = list(st.on) if st.expect == "yes_no" else ["answer"]
        for ev in events:
            block = self._walk(st.on.get(ev))
            if block:
                steps[ev], keys[ev] = self._describe(block), tuple(p.key for p in block)
        prompt = self._prompt_of(st) if st.say else None
        # an unclear answer to a question the caller cut off is re-asked with "I was asking", as _dispatch does
        unclear_first = self._part("unclear" if heard else "was_asking")
        for ev, first in (("unclear", unclear_first), ("question", self._answer_part())):
            block = [first] + ([prompt] if prompt else [])
            if all(p.goal for p in block):
                steps[ev], keys[ev] = self._describe(block), tuple(p.key for p in block)
        return steps, keys

    def _walk(self, name: str | None) -> list[Part] | None:
        """The first LLM lines said from state `name` on, if no tool or ending comes before them."""
        out: list[Part] = []
        for _ in range(10):
            if name is None or name == "back":
                return out or None
            st = self.spec.states[name]
            if st.skip_if and self.slots.get(st.skip_if) is not None:
                name = st.on.get("answer")           # skipped, as _run would
                continue
            if st.tool or st.end:
                return out if out else None
            if st.say:
                ln = self.spec.lines[st.say]
                if not ln.llm:
                    return out if out else None
                out.append(self._part(st.say, asks=st.expect is not None))
            if st.expect:
                return out or None
            name = st.next
        return None

    @staticmethod
    def _describe(block: list[Part]) -> str:
        return " Then: ".join(p.goal + (f" (e.g. \"{p.example}\")" if p.example else "") for p in block)

    @staticmethod
    def _first_llm_block(parts: list[Part]) -> tuple | None:
        keys = []
        for p in parts:
            if p.goal is not None:
                keys.append(p.key)
            elif keys:
                break
        return tuple(keys) or None

    # ------------------------------------------------------------------ acting
    async def _dispatch(self, st: State, event: str, line: str | None, text: str, heard: bool,
                        out: list[Part]) -> None:
        if event in st.on:
            if st.require_heard and not self._heard_enough and event in ("yes", "no"):
                self._step["not_heard_guard"] = True
                out.append(self._part("not_heard_guard"))
                out.extend(self._prompts(full=True))
                return
            self.unclear = 0
            await self._run(st.on[event], out)
            return
        if event in self.spec.global_ and event not in ("off_topic_limit", "low_confidence", "silence"):
            await self._run(self.spec.global_[event], out)
            return
        if event == "corrected":
            await self._run(self.state, out)
            return
        if event == "reask":
            if self._step.get("problem") not in NOT_UNCLEAR:
                self.unclear += 1
                if self.unclear >= self.max_unclear:
                    await self._run(self.spec.global_["low_confidence"], out)
                    return
            if line in FOLLOWED_BY_PROMPT:
                out.append(self._part(line))
                out.extend(self._prompts())
            else:
                out.append(self._part(line, asks=True))
            return
        if event in ("not_heard", "unclear"):
            if event == "unclear" and not heard:
                out.append(self._part("was_asking"))
                out.extend(self._prompts())
                return
            self.unclear += 1
            if self.unclear >= self.max_unclear:
                await self._run(self.spec.global_["low_confidence"], out)
                return
            out.append(self._part(event))
            out.extend(self._prompts())
            return
        if event == "hold":                               # "एक सेकंड": a short "sure", then wait
            self._step["hold"] = True
            if "hold_ok" in self.spec.lines:
                out.append(self._part("hold_ok"))
            return
        if event == "repeat":
            # the question as last said, without "I was asking" and the like (gym call 2 replayed them all)
            out.append(self._part("repeat"))
            spoken, masked = self._core_said.get(self.state) or self._last_said
            out.append(Part("__repeat__", text=spoken, masked=masked, asks=True) if spoken else self._prompt())
            return
        if event == "off_topic":
            self.off_topic += 1
            if self.off_topic >= self.max_off_topic:
                await self._run(self.spec.global_["off_topic_limit"], out)
                return
            out.append(self._part("scope"))
            out.extend(self._prompts())
            return
        if event == "question":
            out.append(self._answer_part() if self.llm else self._part("question_fallback"))
            out.extend(self._prompts())
            return
        await self._dispatch(st, "unclear", None, text, heard, out)

    async def _run(self, name: str, out: list[Part]) -> None:
        start = len(out)
        for _ in range(30):
            if name == "back":                       # return to the question asked before a detour
                name = self._prev_waiting or self.spec.start
            st = self.spec.states[name]
            if st.skip_if and self.slots.get(st.skip_if) is not None:
                name = st.on["answer"]
                continue
            if st.tool:
                name = st.on[await self._tool(st)]
                continue
            if st.say:
                out.append(self._part(st.say, asks=st.expect is not None))
            if st.next:
                name = st.next
                continue
            if st.end:
                self.ended, self.state = st.end, None
                return
            if self.state != name:
                self.unclear = 0
                if self.state is not None:
                    self._prev_waiting = self.state
            self.state = name
            self._arrival = out[start:]
            return
        raise RuntimeError(f"agent spec loops at {name}")

    async def _tool(self, st: State) -> str:
        tool = self.spec.tools[st.tool]
        vars = {**self._vars(), **{k: v for k, v in st.with_.items()}}
        o = await self.tools.run(tool, vars, trace_id=f"{self.call_id}-{len(self.tool_log)}")
        self.tool_log.append(o.result)
        for name, v in o.saved.items():
            opt = tool.save[name] if isinstance(tool.save[name], dict) else {}
            self.vars[name] = v
            if opt.get("private"):
                self.private_saved[name] = opt["private"]
                if opt["private"] in self.private_values:          # digits/pan/date: also leak-checked
                    self.private_values[opt["private"]].add(str(v))
            if opt.get("show"):
                self.shown[name] = v
        for name in o.clear:
            self.slots.pop(name, None)
            self.extras.pop(name, None)
        self._step["tools"].append({"tool": tool.name, "outcome": o.result.outcome, "status": o.result.status,
                                    "ms": round(o.result.ms, 1), "attempts": o.result.attempts, "event": o.event,
                                    "state": o.result.state})
        return o.event

    # ------------------------------------------------------------------ lines
    def _vars(self) -> dict:
        return {"agent": self.spec.agent["name"], "company": self.spec.agent["company"], "call_id": self.call_id,
                "state": self.state or "", "last_caller_text": (self.last_caller_text or "-")[:500],
                **self.context, **self.vars, **{k: self.slots[k] for k in self.slots}}

    def _private(self, name: str) -> bool:
        s = self.spec.slots.get(name)
        return bool(s and s.private) or name in self.private_saved

    def _fill(self, text: str, masked: bool) -> str:
        vars = self._vars()

        def one(m):
            name, how = m.group(1), m.group(2)
            if masked and self._private(name):
                return hindi.MASK
            if how == "hi":
                return (self.extras.get(name) or {}).get("hi") or ""
            if how == "label":
                sl = self.spec.slots.get(name)
                return sl.labels.get(str(vars.get(name)), "") if sl else ""
            v = vars.get(name)
            return fmt(v, how) if how else ("" if v is None else str(v))
        return _VAR.sub(one, text)

    def _part(self, key: str, asks: bool = False) -> Part:
        ln = self.spec.lines[key]
        if ln.llm:
            goal = self._fill(ln.goal, True)
            if key in self._last_keys:                     # said in the previous reply too: don't say it the same way
                goal = AGAIN + goal
            return Part(key, goal=goal, example=self._fill(ln.example, False), asks=asks)
        return Part(key, text=self._fill(ln.text, False), masked=self._fill(ln.text, True), asks=asks)

    def _answer_part(self) -> Part:
        ln = self.spec.lines["question_fallback"]
        return Part("__answer__", goal=ANSWER_GOAL, example=ANSWER_EXAMPLE,
                    fallback=self._fill((ln.example if ln.llm else ln.text) or "", False))

    def _prompt(self) -> Part:
        """The current question, asked again (an LLM line is told to be brief and to word it differently)."""
        return self._prompt_of(self.spec.states[self.state])

    def _prompt_of(self, st: State) -> Part:
        p = self._part(st.say, asks=True)
        if p.goal is not None and not p.goal.startswith(AGAIN):
            p.goal = AGAIN + p.goal
        return p

    def _prompts(self, full: bool = False) -> list[Part]:
        st = self.spec.states[self.state]
        if (full or self._full_prompt) and st.require_heard and self._arrival:
            return list(self._arrival)
        return [self._prompt()]

    def _facts(self) -> dict:
        f = dict(self.spec.knowledge)
        for k, v in {**self.context, **self.vars, **self.slots}.items():
            if k in ("session_id",) or self._private(k) or k in self.shown:
                continue
            if isinstance(v, (int, float, str)) and not isinstance(v, bool):
                f[k] = v
        return f

    def _reply(self, out: list[Part], t0: int, caller: str | None = None, happened: str = "") -> Reply:
        if not happened:
            bits = [f"the caller's answer was understood as: {self._step.get('event')}"] if "event" in self._step else []
            bits += [f"{t['tool']} returned {t['event']}" for t in self._step.get("tools", [])]
            happened = "; ".join(bits)
        self._step.update(state_out=self.state, end=self.ended, ms=round((time.perf_counter_ns() - t0) / 1e6, 1))
        self._last_keys = {p.key for p in out}
        return Reply(out, self.ended, self._step, caller, happened)

    # ================================================================== speaking
    async def stream(self, reply: Reply) -> AsyncIterator[str]:
        """The reply's words, sentence by sentence. LLM blocks are written now, each sentence checked before
        it's yielded. Whatever was yielded is recorded, even if the caller interrupts and the rest is dropped."""
        said: list[str] = []
        said_masked: list[str] = []
        current: list[str] = []
        pieces: list[tuple[tuple, str, str]] = []        # (line keys, text, masked), for a later repeat
        try:
            parts, i, first_block = reply.parts, 0, True
            while i < len(parts):
                p = parts[i]
                if p.text is not None:
                    said.append(p.text)
                    said_masked.append(p.masked or p.text)
                    pieces.append(((p.key,), p.text, p.masked or p.text))
                    yield p.text + " "
                    i += 1
                    continue
                j = i
                while j < len(parts) and parts[j].text is None:
                    j += 1
                block, i = parts[i:j], j
                keys = tuple(p.key for p in block)
                pre = reply.prefilled.get(keys) if first_block else None
                first_block = False
                current = []
                async for sentence in self._write(block, reply, pre, " ".join(said_masked)):
                    current.append(sentence)
                    yield sentence + " "
                said.append(" ".join(current))
                said_masked.append(" ".join(current))
                pieces.append((keys, " ".join(current), " ".join(current)))
                current = []
        finally:
            if current:
                said.append(" ".join(current))
                said_masked.append(" ".join(current))
                pieces.append((keys, " ".join(current), " ".join(current)))
            self._remember_core(pieces)
            text = " ".join(s for s in said if s)
            reply.spoken = text
            if text:
                self.spoken.append(text)
                masked = " ".join(s for s in said_masked if s)
                self.history.append(f"Agent: {masked}")
                self._last_said = (text, masked)
                problems = check_spoken(text, secrets=self.secrets())
                if problems:
                    self.problems += problems
                    log.error("spoken-text check failed: %s", problems)

    def _remember_core(self, pieces: list[tuple[tuple, str, str]]) -> None:
        """Keep the current question as said, without wrapper lines. A wrapper written in the same LLM block
        as the question can't be cut out, so such a reply leaves the earlier wording in place."""
        if not self.state or any(set(k) & WRAPPERS and set(k) - WRAPPERS for k, _, _ in pieces):
            return
        core = [(t, m) for k, t, m in pieces if t and not set(k) & WRAPPERS]
        if core:
            self._core_said[self.state] = (" ".join(t for t, _ in core), " ".join(m for _, m in core))

    async def _write(self, block: list[Part], reply: Reply, pre: str | None, before: str = "") -> AsyncIterator[str]:
        """One LLM block: the extraction's words if it wrote them, else a streamed generation; every sentence
        checked; the examples if anything fails."""
        allowed = self._allowed_numbers(block)
        examples = " ".join(p.fallback or p.example for p in block)
        max_sentences = 2 * len(block) + 1
        record = {"keys": list(block_keys(block)), "source": None, "ok": True, "reasons": []}
        self._step.setdefault("guard", []).append(record)
        if self.llm is None:
            record.update(source="example")
            for s in _split(examples):
                yield s
            return
        call = None
        if pre is not None:
            record["source"] = "extraction"
            source = _one(pre)
        else:
            record["source"] = "generate"
            call = LLMCall("generate")
            self._step["llm"].append(call.__dict__)
            steps = [(p.goal, p.example) for p in block]
            source = self.llm.generate(history=self.history[:-1] if reply.caller else self.history,
                                       caller=reply.caller, happened=reply.happened, steps=steps,
                                       facts=self._facts(), secrets=self.secrets(), call=call, said_before=before)
        written: list[str] = []
        seg = Segmenter()
        try:
            async for piece in source:
                for s in seg.feed(piece):
                    g = check_answer(s, allowed)
                    if not g.ok:
                        record.update(ok=False, reasons=g.reasons, rejected=s)
                        break
                    written.append(g.text)
                    yield g.text
                    if len(written) >= max_sentences:
                        break
                if not record["ok"] or len(written) >= max_sentences:
                    break
            else:
                for s in seg.flush():
                    g = check_answer(s, allowed)
                    if not g.ok:
                        record.update(ok=False, reasons=g.reasons, rejected=s)
                        break
                    written.append(g.text)
                    yield g.text
        finally:
            if hasattr(source, "aclose"):
                await source.aclose()
            if call is not None:
                self._step["llm"][-1] = call.__dict__
        if not written:
            record.update(ok=False, reasons=record["reasons"] or ["nothing written"])
            record["fallback"] = "examples"
            for s in _split(examples):
                yield s
        elif block[-1].asks and not asks_question(" ".join(written)):
            record["fallback"] = "question"           # the caller must still be asked
            for s in _split(block[-1].fallback or block[-1].example):
                yield s

    def _allowed_numbers(self, block: list[Part]) -> set[float]:
        allowed = set()
        for v in self._facts().values():
            if isinstance(v, (int, float)):
                allowed.add(float(v))
        if "tenure_months" in self.slots:
            allowed.add(self.slots["tenure_months"] / 12)
        for p in block:
            allowed |= hindi.number_values(p.example) | hindi.number_values(p.goal or "")
        for v in self.spec.knowledge.values():
            allowed |= hindi.number_values(str(v))
        return allowed


_GOES_ON = {hindi.norm(w) for w in ["या", "और", "लेकिन", "पर", "तो", "कि", "मतलब", "अः", "अ", "उम", "उम्म",
                                     "फिर", "वो", "नहीं", "बल्कि", "एंड", "ऑर"]}
_QUESTION_WORDS = {hindi.norm(w) for w in ["कौन", "कौनसा", "कब", "कितना", "कितनी", "कितने", "कैसे", "कहाँ",
                                            "क्यों", "किस", "किसका"]}
_LEADING = {hindi.norm(w) for w in ["अः", "अ", "हाँ", "हां", "तो", "अच्छा", "जी", "यार", "सुनो", "और", "भाई"]}


def _asks(text: str) -> bool:
    """A question the LLM couldn't place? "?" or a question word; "क्या" only at the start ("क्या और प्लान है"),
    because elsewhere it is often filler ("वो तो देखिए क्या है ना", "पता नहीं क्या बोलूँ")."""
    toks = hindi.tokens(text)
    while toks and toks[0] in _LEADING:
        toks = toks[1:]
    return "?" in text or bool(toks and toks[0] == hindi.norm("क्या")) or any(t in _QUESTION_WORDS for t in toks)


def block_keys(block: list[Part]) -> tuple:
    return tuple(p.key for p in block)


def _split(text: str) -> list[str]:
    seg = Segmenter()
    return seg.feed(text) + seg.flush()


async def _one(text: str) -> AsyncIterator[str]:
    yield text


async def say_all(agent: Agent, reply: Reply) -> str:
    """Consume a reply's stream (tests and the typed evaluation)."""
    async for _ in agent.stream(reply):
        pass
    return reply.spoken
