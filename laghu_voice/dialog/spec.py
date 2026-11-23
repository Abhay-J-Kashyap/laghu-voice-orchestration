"""Agent specs (agents/*.yaml): one file per use case. Loaded and checked at startup, so a broken spec fails
before the first call, not during one.

A spec declares everything use-case specific; the engine (agent.py) knows none of it:

    agent     who speaks (name, company, gender) and what the call is for (persona, for the LLM)
    context   values known before the call (an outbound call's customer name...), usable in lines
    knowledge facts the LLM may use to answer questions (plans, fees, timings...); numbers in them may be said
    slots     what the agent may ask for, by type (slots.py), with re-ask lines per problem
    intents   requests besides the built-in ones, with trigger phrases and a description for the LLM
    lines     what the agent says. A string is said exactly (fixed, or a template with {values});
              {llm: goal, example: ...} is written by the LLM each time, the example being the style to aim
              for and what is said if the LLM fails a check or is slow.
    backend   where tools go: http (with a start call that opens the backend's session) or mock
    tools     each tool's request, what to save from the answer, and rules turning the answer into an event
    states    the flow; the target `back` returns to the question asked before a detour. Every ending has an
              outcome: success, declined, transferred, no_contact or failed
    global    where built-in requests (and the spec's own intents) go from any state

What every agent needs (the lines for "didn't understand", "I was asking", hand-over, hang-up...; the timing;
the hand-over states) comes from defaults.yaml, so a spec only says what is particular to its use case. A spec
overrides any default by defining the same key (Milestone 5).

`check()` refuses a spec with errors. Warnings (`spec.warnings`) are things a person should look at.
"""
from __future__ import annotations

import re
import string
from dataclasses import MISSING, dataclass, field
from pathlib import Path

import yaml

from .slots import FORMATS, TYPES, Slot

BUILTIN_INTENTS = {"answer", "yes", "no", "human", "repeat", "question", "off_topic", "stop", "unclear", "hold"}
BUILTIN_VARS = {"agent", "company", "call_id", "session_id", "last_caller_text", "state"}
OUTCOMES = {"success", "declined", "transferred", "no_contact", "failed"}
DEFAULTS = Path(__file__).with_name("defaults.yaml")
_GENDERED = re.compile(r"\[([^|\]]*)\|([^\]]*)\]")
FEMININE_RE = re.compile(r"(?:ती|रही|गई) हू[ँं]|[ूऊ][ँं]गी")
LATIN_RE = re.compile(r"[A-Za-z]")


class SpecError(ValueError):
    """The spec's problems; .errors keeps them one per item (a message may itself contain "; ")."""
    def __init__(self, message: str, errors: list[str] | None = None):
        super().__init__(message)
        self.errors = list(errors) if errors else [message]


@dataclass
class Line:
    key: str
    text: str | None = None            # fixed or template
    goal: str | None = None            # llm
    example: str | None = None         # llm: style and fallback

    @property
    def llm(self) -> bool:
        return self.goal is not None

    def variables(self) -> set[str]:
        out = set()
        for t in (self.text, self.example, self.goal):
            for _, f, spec_, _ in string.Formatter().parse(t or ""):
                if f:
                    out.add(f if not spec_ else f"{f}:{spec_}")
        return out


@dataclass
class Tool:
    name: str
    path: str = ""
    body: dict = field(default_factory=dict)
    save: dict = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    mock: list[dict] = field(default_factory=list)
    commits: bool = False          # books, pays or commits to something: only after a yes (check())

    @property
    def event_names(self) -> set[str]:
        return {e["then"] for e in self.events}


@dataclass
class State:
    name: str
    say: str | None = None
    expect: str | None = None          # a slot name, or yes_no
    on: dict[str, str] = field(default_factory=dict)
    next: str | None = None
    tool: str | None = None
    with_: dict = field(default_factory=dict)
    end: str | None = None
    skip_if: str | None = None
    corrections: list[str] = field(default_factory=list)
    also: list[str] = field(default_factory=list)       # slots also read from the same answer, unit required
    # a yes or no to this question counts only if the caller heard the question: true = all of the reply, a
    # number = at least that fraction of it (the trace's estimate of what played before they cut in)
    require_heard: float | None = None
    outcome: str | None = None         # an ending's outcome: success, declined, transferred, no_contact, failed

    def __post_init__(self):
        if self.require_heard is None:
            return                     # decided after loading (_commit_defaults)
        self.require_heard = float(self.require_heard or 0)
        if not 0 <= self.require_heard <= 1:
            raise ValueError(f"state {self.name}: require_heard must be true, false or a fraction from 0 to 1")


@dataclass
class Intent:
    name: str
    describe: str
    phrases: list[str] = field(default_factory=list)
    act_directly: bool = False     # may its phrases lead straight to a tool? (see check())


@dataclass
class Spec:
    agent: dict
    timing: dict
    context: dict
    knowledge: dict
    slots: dict[str, Slot]
    intents: dict[str, Intent]
    lines: dict[str, Line]
    backend: dict
    tools: dict[str, Tool]
    states: dict[str, State]
    global_: dict[str, str]
    path: Path | None = None
    warnings: list[str] = field(default_factory=list)
    generated: bool = False        # written by the setup tool: some things are refused that a person may do

    start = "greet"

    @property
    def http(self) -> bool:
        return self.backend.get("provider", "http") == "http"

    def fixed_lines(self) -> list[str]:
        """Lines said exactly with no call values: synthesised once at startup and played from memory. Also
        the examples of LLM lines with no values (said when the LLM fails), and the fixed sentences of
        templates (a template's sentences without values are cut and cached the same way)."""
        out = []
        base = {"agent": self.agent["name"], "company": self.agent["company"], **self.context}
        for ln in self.lines.values():
            for t in (ln.text, ln.example):
                if not t:
                    continue
                for sentence in re.findall(r"[^।?!]+[।?!]?", t):
                    names = {f for _, f, _, _ in string.Formatter().parse(sentence) if f}
                    if names <= set(base):
                        out.append(sentence.strip().format(**base))
        return list(dict.fromkeys(s for s in out if s))


class _Loader(yaml.SafeLoader):
    """YAML 1.1 reads `on`, `yes` and `no` as booleans; here only true and false are."""


_Loader.yaml_implicit_resolvers = {
    k: [(tag, rx) for tag, rx in v if tag != "tag:yaml.org,2002:bool"]
    for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
for _ch in "tTfF":
    _Loader.add_implicit_resolver("tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
                                  [_ch])


def _make(cls, name: str, d: dict, what: str, rename: dict | None = None):
    if not isinstance(d, dict) and d is not None:
        raise SpecError(f"{what} {name}: must be an object, not {type(d).__name__}")
    d = {(rename or {}).get(k, k): v for k, v in (d or {}).items()}
    key = "name" if "name" in cls.__dataclass_fields__ else "key"
    d.pop(key, None)                          # a name inside the item repeats the item's key
    unknown = set(d) - set(cls.__dataclass_fields__)
    if unknown:
        raise SpecError(f"{what} {name}: unknown keys {sorted(unknown)}")
    missing = [f.name for f in cls.__dataclass_fields__.values()
               if f.name != key and f.name not in d and f.default is MISSING and f.default_factory is MISSING]
    if missing:
        raise SpecError(f"{what} {name}: needs " + ", ".join(repr(m) for m in missing))
    try:
        return cls(**{key: name}, **d)
    except (TypeError, ValueError) as e:
        raise SpecError(f"{what} {name}: {e}") from e


def _make_all(cls, items, what: str, errors: list[str], rename: dict | None = None) -> dict:
    """Every item of a section, collecting shape errors instead of stopping at the first."""
    out = {}
    for k, v in (items or {}).items():
        try:
            out[k] = _make(cls, k, v, what, rename)
        except SpecError as e:
            errors.append(str(e))
    return out


def _gendered(x, male: bool):
    """[male|female] in the defaults picks one form by the agent's gender."""
    if isinstance(x, str):
        return _GENDERED.sub(lambda m: m.group(1 if male else 2), x)
    if isinstance(x, dict):
        return {k: _gendered(v, male) for k, v in x.items()}
    if isinstance(x, list):
        return [_gendered(v, male) for v in x]
    return x


def _targets(states: dict) -> set[str]:
    out = set()
    for st in states.values():
        out |= set((st or {}).get("on", {}).values())
        if (st or {}).get("next"):
            out.add(st["next"])
    return out


def with_defaults(raw: dict) -> dict:
    """The spec with the engine's defaults filled in where it doesn't say otherwise."""
    male = (raw.get("agent") or {}).get("gender", "male") == "male"
    d = _gendered(yaml.load(DEFAULTS.read_text(encoding="utf-8"), Loader=_Loader), male)  # noqa: S506
    out = dict(raw)
    out["timing"] = {**d["timing"], **(raw.get("timing") or {})}
    out["lines"] = {**d["lines"], **(raw.get("lines") or {})}
    out["global"] = {**d["global"], **(raw.get("global") or {})}
    states = dict(raw.get("states") or {})
    tools = dict(raw.get("tools") or {})
    mock = (raw.get("backend") or {"provider": "mock"}).get("provider", "http") != "http"
    while True:                     # add the default states something reaches, and what they reach in turn
        wanted = (_targets(states) | set(out["global"].values())) - set(states)
        add = {n: d["states"][n] for n in wanted if n in d["states"]}
        if not add:
            break
        states.update(add)
    for st in states.values():
        t = (st or {}).get("tool")
        if t and t not in tools and t in d["tools"] and mock:
            tools[t] = d["tools"][t]
    out["states"], out["tools"] = states, tools
    return out


def load_spec(path: str | Path, generated: bool = False) -> Spec:
    path = Path(path)
    raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_Loader)  # noqa: S506 - a SafeLoader subclass
    return build_spec(raw, path, generated)


def build_spec(raw: dict, path: Path | None = None, generated: bool = False) -> Spec:
    raw = with_defaults(raw)
    lines, bad = {}, []
    for k, v in (raw.get("lines") or {}).items():
        if isinstance(v, str):
            lines[k] = Line(k, text=v)
        elif isinstance(v, dict) and set(v) <= {"llm", "example"} and "llm" in v and "example" in v:
            lines[k] = Line(k, goal=v["llm"], example=v["example"])
        else:
            bad.append(f"line {k}: a string, or {{llm: goal, example: text}}")
    shape: list[str] = bad
    slots = _make_all(Slot, raw.get("slots"), "slot", shape)
    intents = _make_all(Intent, raw.get("intents"), "intent", shape)
    tools = _make_all(Tool, raw.get("tools"), "tool", shape)
    states = _make_all(State, raw.get("states"), "state", shape, {"with": "with_"})
    if "agent" not in raw:
        shape.append("spec shape: no agent")
    if shape:
        raise SpecError("; ".join(shape), shape)
    spec = Spec(
        agent=raw["agent"], timing=raw.get("timing") or {}, context=raw.get("context") or {},
        knowledge=raw.get("knowledge") or {}, slots=slots, intents=intents, lines=lines,
        backend=raw.get("backend") or {"provider": "mock"}, tools=tools, states=states,
        global_=raw.get("global") or {}, path=path, generated=generated)
    _commit_defaults(spec)
    check(spec)
    return spec


def _commit_defaults(spec: Spec) -> None:
    """A yes/no question whose yes leads to a tool that commits needs 85% of it heard, unless the spec says."""
    for st in spec.states.values():
        if st.require_heard is None:
            st.require_heard = 0.85 if (st.expect == "yes_no" and _reaches_commit(spec, st.on.get("yes"))) else 0.0


def _reaches_commit(spec: Spec, name: str | None) -> bool:
    seen = set()
    while name and name in spec.states and name not in seen:
        seen.add(name)
        st = spec.states[name]
        if st.tool:
            return spec.tools.get(st.tool) is not None and spec.tools[st.tool].commits
        if st.expect or st.end:
            return False
        name = st.next
    return False


def check(spec: Spec) -> None:
    errors: list[str] = []
    known_vars = BUILTIN_VARS | set(spec.slots) | set(spec.context) | _saved_names(spec)
    for sl in spec.slots.values():
        if sl.type not in TYPES:
            errors.append(f"slot {sl.name}: unknown type {sl.type}")
        if sl.type == "choice" and not sl.options:
            errors.append(f"slot {sl.name}: a choice needs options")
        for k, lab in sl.labels.items():
            if k not in sl.options or LATIN_RE.search(lab):
                errors.append(f"slot {sl.name}: label {k} must be an option, in Devanagari")
        for problem, line in sl.reask.items():
            if line not in spec.lines:
                errors.append(f"slot {sl.name}: re-ask line {line} does not exist")
    for ln in spec.lines.values():
        for t in (ln.text, ln.example):
            if t is None:
                continue
            if t.strip().startswith("नमस्ते"):
                errors.append(f"line {ln.key}: starts with नमस्ते")
            latin = re.findall(r"[A-Za-z][A-Za-z.\-]*", re.sub(r"\{[\w:]+\}", "", t))
            if latin:
                errors.append(f"line {ln.key}: has English letters {sorted(set(latin))} (Laghu drops them; write "
                              f"each in Devanagari, an acronym as its letters: MBA -> एमबीए)")
            if spec.agent.get("gender") == "male" and FEMININE_RE.search(t):
                errors.append(f"line {ln.key}: feminine first person, but the agent is male")
        for v in ln.variables():
            name, _, how = v.partition(":")
            if name not in known_vars:
                errors.append(f"line {ln.key}: unknown value {{{name}}}")
            if how and how not in FORMATS:
                errors.append(f"line {ln.key}: unknown format :{how}")
            if ln.llm and name in spec.slots and spec.slots[name].private:
                errors.append(f"line {ln.key}: an LLM line can't use the private value {name}")
    events_ok = BUILTIN_INTENTS | set(spec.intents) | {"corrected"}   # corrected: a value changed (corrections)
    for t in spec.tools.values():
        if not t.events or "if" in t.events[-1]:
            errors.append(f"tool {t.name}: the last event rule needs no `if` (a catch-all)")
        if spec.http and not t.path:
            errors.append(f"tool {t.name}: no path")
        if not spec.http and not t.mock:
            errors.append(f"tool {t.name}: mock backend, but no mock answers")
        if not spec.http and t.mock:
            errors += _check_mock(spec, t)
    if spec.start not in spec.states:
        errors.append("no greet state")
    for st in spec.states.values():
        kinds = sum(x is not None for x in (st.expect, st.tool, st.end, st.next))
        if kinds != 1:
            errors.append(f"state {st.name}: needs exactly one of expect, tool, next, end")
        if st.say is not None and st.say not in spec.lines:
            errors.append(f"state {st.name}: unknown line {st.say}")
        if st.expect is not None:
            if st.expect != "yes_no" and st.expect not in spec.slots:
                errors.append(f"state {st.name}: expects unknown slot {st.expect}")
            if st.say is None:
                errors.append(f"state {st.name}: waits for the caller without asking anything")
            bad = set(st.on) - events_ok
            if bad:
                errors.append(f"state {st.name}: unknown events {sorted(bad)}")
            if st.expect == "yes_no" and not {"yes", "no"} <= set(st.on):
                errors.append(f"state {st.name}: needs yes and no")
            if st.expect != "yes_no" and "answer" not in st.on:
                errors.append(f"state {st.name}: no target for answer")
        for s_ in st.corrections + st.also + ([st.skip_if] if st.skip_if else []):
            if s_ not in spec.slots:
                errors.append(f"state {st.name}: unknown slot {s_}")
        if st.tool is not None:
            if st.tool not in spec.tools:
                errors.append(f"state {st.name}: unknown tool {st.tool}")
            elif set(st.on) != spec.tools[st.tool].event_names:
                errors.append(f"state {st.name}: {st.tool} needs targets for exactly "
                              f"{sorted(spec.tools[st.tool].event_names)}")
        for t in list(st.on.values()) + ([st.next] if st.next else []):
            if t not in spec.states and t != "back":
                errors.append(f"state {st.name}: target {t} does not exist")
        for ev, t in st.on.items():
            _check_intent_target(spec, ev, t, f"state {st.name}", errors)
    for key in ("human", "stop", "off_topic_limit", "low_confidence", "silence"):
        if spec.global_.get(key) not in spec.states:
            errors.append(f"global {key}: target {spec.global_.get(key)!r} does not exist")
    for key, t in spec.global_.items():
        if t not in spec.states:
            errors.append(f"global {key}: target {t!r} does not exist")
        elif key in spec.intents:
            _check_intent_target(spec, key, t, "global", errors)
    for key in ("unclear", "not_heard", "repeat", "was_asking", "not_heard_guard", "are_you_there", "scope",
                "question_fallback", "filler", "pick_one"):
        if key not in spec.lines:
            errors.append(f"the engine needs a line called {key}")
    seen, todo = set(), [spec.start] + [v for v in spec.global_.values() if v in spec.states]
    while todo:
        n = todo.pop()
        if n in seen:
            continue
        seen.add(n)
        st = spec.states[n]
        todo += [t for t in list(st.on.values()) + ([st.next] if st.next else []) if t in spec.states]
    errors += [f"state {n}: unreachable" for n in spec.states if n not in seen]
    errors += _check_outcomes_and_commits(spec)
    errors += _check_lines_against_slots_and_facts(spec)
    errors += _check_spoken_form(spec)
    if spec.generated:
        errors += [w for w in _warnings(spec) if "without naming its options" in w]
    spec.warnings = spec.warnings + _warnings(spec)
    if errors:
        raise SpecError("; ".join(errors), errors)


DEFAULT_FORMAT = {"choice": "label", "number": "words", "money": "words", "duration": "words", "time": "time",
                  "date": "date", "name": "hi", "text": "hi", "digits": "digits", "pan": "spell", "email": "spell"}
FITS = {"choice": {"label", "hi"}, "number": {"words"}, "money": {"words"}, "duration": {"words", "tenure", "days"},
        "time": {"time", "days"}, "date": {"date", "iso"}, "name": {"hi"}, "text": {"hi"}, "digits": {"digits"},
        "pan": {"spell"}, "email": {"spell"}}
_DIGIT_IN_LINE = re.compile(r"[0-9\u0966-\u096F]")
_PLACEHOLDER = re.compile(r"\{(\w+)(?::(\w+))?\}")


def _check_spoken_form(spec: Spec) -> list[str]:
    """What a fixed line or a template would make the agent say wrongly (the MBA runs of Milestone 5): digits
    ("30-मिनट" is read as nothing or as English), a slot said raw ("5:morning", "full_time", "Mumbai"), a question
    the flow doesn't wait for, and a date slot used for a day to meet."""
    errors = []
    for ln in spec.lines.values():
        for t in (ln.text, ln.example):
            if not t:
                continue
            if _DIGIT_IN_LINE.search(_PLACEHOLDER.sub(" ", t)):
                errors.append(f"line {ln.key}: has digits; write numbers as Hindi words (तीस, not 30)")
            for name, how in _PLACEHOLDER.findall(t):
                sl = spec.slots.get(name)
                if sl is not None and not how and sl.type in DEFAULT_FORMAT:
                    errors.append(f"line {ln.key}: {{{name}}} needs a format: {{{name}:{DEFAULT_FORMAT[sl.type]}}}")
                elif sl is not None and how and how not in FITS.get(sl.type, {how}):
                    errors.append(f"line {ln.key}: {{{name}:{how}}} doesn't fit a {sl.type} slot; use "
                                  f"{{{name}:{DEFAULT_FORMAT[sl.type]}}}")
    for st in spec.states.values():
        if st.expect in spec.slots and st.say in spec.lines:
            ln = spec.lines[st.say]
            if any(n == st.expect for n, _ in _PLACEHOLDER.findall((ln.text or "") + (ln.example or ""))):
                errors.append(f"line {st.say}: asks for {st.expect} and also says {{{st.expect}}}, which is still empty "
                              f"then; name the options in words")
        if st.next and st.say and st.say in spec.lines:
            ln = spec.lines[st.say]
            if "?" in (ln.text or ln.example or ""):
                errors.append(f"state {st.name}: its line asks a question but the state doesn't wait for the answer "
                              f"(it has next); make it expect yes_no or a slot, with on")
        if st.end is not None and st.say and st.say in spec.lines:
            ln = spec.lines[st.say]
            if "?" in (ln.text or ln.example or ""):
                errors.append(f"state {st.name}: the call ends after its line, so the line must not ask anything "
                              f"(\"क्या यह सही है?\" belongs in the read-back before the booking)")
    asked = {st.expect for st in spec.states.values()} | {n for t in spec.tools.values() for n in t.save}
    for ln in spec.lines.values():
        for t in (ln.text, ln.example):
            for name, _ in _PLACEHOLDER.findall(t or ""):
                if name in spec.slots and name not in asked:
                    errors.append(f"line {ln.key}: says {{{name}}}, but no state asks for {name} and no tool sets it, "
                                  f"so it can be empty (add a question for it, with skip_if: {name})")
    for it in spec.intents.values():
        route, acts = [], False
        st = spec.states.get(spec.global_.get(it.name) or "")
        while st is not None and st.name not in route:
            route.append(st.name)
            if st.expect or st.next == "back":
                break                     # a question first, or a line and back: a passing mention costs nothing
            if st.tool or st.end or st.next == "handover":
                acts = True
                break
            st = spec.states.get(st.next or "")
        if not acts:
            continue
        own = {spec.states[n].say for n in route}
        said = [hindi_tokens(t) for ln in spec.lines.values() if ln.key not in own
                for t in (ln.text, ln.example) if t]
        for ph in it.phrases:
            toks = hindi_tokens(ph)
            if len(toks) == 1 and any(_same_stem(toks[0], w) for line in said for w in line):
                errors.append(f"intent {it.name}: its phrase \"{ph}\" is a word the agent itself says (callers repeat "
                              f"it: \"कुछ नहीं बदलना\" is no cancel), and it acts without asking; use longer phrases")
    for sl in spec.slots.values():
        if sl.type == "date" and sl.min_age is None:
            errors.append(f"slot {sl.name}: a date slot is only for a date of birth (with min_age); a day to meet or "
                          f"to call back is a time slot (the day and part of the day in one), with max: days ahead")
    return errors


def hindi_tokens(text: str) -> list[str]:
    from . import hindi
    return hindi.tokens(_PLACEHOLDER.sub(" ", text))


def _same_stem(a: str, b: str) -> bool:
    """बदलना, बदलनी: the same word in another form."""
    return a == b or (len(a) >= 4 and len(b) >= 4 and a[:-1] == b[:-1])


def _check_mock(spec: Spec, t: Tool) -> list[str]:
    """A mock answer stands in for the business's system. When none matches the call's values the tool fails, and
    the call goes tech_problem -> hand-over: every booking would end "transferred". So a choice slot's condition
    must use its option keys, and the list must end with an answer for any values (or cover every option)."""
    errors = []
    for m in t.mock:
        for k, want in (m.get("if") or {}).items():
            sl = spec.slots.get(k)
            if sl is None or sl.type != "choice":
                continue
            vals = want if isinstance(want, list) else [want]
            bad = [v for v in vals if isinstance(v, str) and v != "present" and v not in sl.options]
            if bad:
                errors.append(f"tool {t.name}: a mock answer's if {k} = {bad} never matches: {k} holds an option "
                              f"key, one of {sorted(sl.options)}")
    if t.mock[-1].get("if") and not _mock_covers(spec, t.mock):
        errors.append(f"tool {t.name}: when no mock answer matches, the tool fails and the call is handed over; end "
                      f"the mock list with an answer without \"if\"")
    return errors


def _mock_covers(spec: Spec, mock: list[dict]) -> bool:
    """Mock answers that each test one choice slot (the same one) and together name every option."""
    keys = {k for m in mock for k in (m.get("if") or {})}
    if len(keys) != 1 or any(len(m.get("if") or {}) != 1 for m in mock):
        return False
    sl = spec.slots.get(next(iter(keys)))
    if sl is None or sl.type != "choice":
        return False
    named = set()
    for m in mock:
        want = next(iter(m["if"].values()))
        named |= set(want) if isinstance(want, list) else {want}
    return set(sl.options) <= named


def _check_outcomes_and_commits(spec: Spec) -> list[str]:
    errors = []
    for st in spec.states.values():
        if st.end is not None and st.outcome not in OUTCOMES:
            errors.append(f"state {st.name}: an ending needs an outcome: add \"outcome\" next to \"end\", one of "
                          f"{', '.join(sorted(OUTCOMES))}")
        if st.end is None and st.outcome is not None:
            errors.append(f"state {st.name}: only an ending has an outcome")
    if spec.generated:
        errors += [f"intent {i.name}: act_directly isn't allowed in a generated spec"
                   for i in spec.intents.values() if i.act_directly]
    # a tool that commits runs only right after a yes to a question
    edges = [(None, "start", spec.start)] + [(None, k, t) for k, t in spec.global_.items()]
    for st in spec.states.values():
        if st.expect:
            edges += [(st, ev, t) for ev, t in st.on.items()]
    for src, ev, target in edges:
        ok = src is not None and src.expect == "yes_no" and ev == "yes"
        todo, seen = [target], set()
        while todo:
            n = todo.pop()
            if n in seen or n not in spec.states:
                continue
            seen.add(n)
            st = spec.states[n]
            if st.expect or st.end:
                continue
            if st.tool:
                tool = spec.tools.get(st.tool)
                if tool is not None and tool.commits and not ok:
                    where = f"state {src.name} on {ev}" if src else f"{ev}"
                    errors.append(f"{where}: reaches {st.tool}, which commits, without a yes to a question first")
                    break
                todo += list(st.on.values())
            if st.next:
                todo.append(st.next)
    return errors


def _numbers_allowed(spec: Spec) -> set[float]:
    from . import hindi
    allowed = {1.0}
    for v in spec.knowledge.values():
        allowed |= hindi.fact_numbers(str(v))
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            allowed.add(float(v))
    for sl in spec.slots.values():
        allowed |= {float(x) for x in (sl.min, sl.max, sl.length) if isinstance(x, (int, float))}
    for t in spec.tools.values():
        for m in t.mock:
            for v in _leaves(m):
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    allowed.add(float(v))
                elif isinstance(v, str):
                    allowed |= hindi.number_values(v)
    return {round(x, 2) for x in allowed}


def _leaves(x):
    if isinstance(x, dict):
        for v in x.values():
            yield from _leaves(v)
    elif isinstance(x, list):
        for v in x:
            yield from _leaves(v)
    else:
        yield x


def _asking_lines(spec: Spec):
    """(state, slot, Hindi text of the line that asks for it)."""
    for st in spec.states.values():
        if st.say and st.expect and st.expect in spec.slots:
            ln = spec.lines.get(st.say)
            text = (ln.text or ln.example or "") if ln else ""
            yield st, spec.slots[st.expect], re.sub(r"\{[\w:]+\}", " ", text)


def _check_lines_against_slots_and_facts(spec: Spec) -> list[str]:
    from . import hindi
    errors: list[str] = []
    number_warnings: list[str] = []
    # Gym call 3: "फिटनेस" was an option phrase and also a word of the question ("आपका फ़िटनेस लक्ष्य"), so a
    # caller repeating the question picked that option. A question names each option once, where it lists them.
    for st, sl, text in _asking_lines(spec):
        if sl.type != "choice":
            continue
        sentences = [x for x in re.split(r"[।?!]", text) if x.strip()]
        named = [{k for _, _, k in sl.option_spans(x)} for x in sentences]
        if not any(len(n) >= 2 for n in named):
            continue                     # no list of options here: nothing to compare with
        for x, n in zip(sentences, named):
            if len(n) == 1:
                errors.append(f"line {st.say}: \"{x.strip()}\" names option {next(iter(n))} of {sl.name} outside "
                              f"the list of options; callers repeat the question's words, so a phrase of it is "
                              f"probably a word of the question")
    allowed = _numbers_allowed(spec)
    for ln in spec.lines.values():
        for t in (ln.text, ln.example):
            if not t:
                continue
            bad = sorted(v for v in hindi.number_values(re.sub(r"\{[\w:]+\}", " ", t))
                         if round(v, 2) not in allowed and not (v <= 10 and float(v).is_integer()))
            if bad:
                msg = (f"line {ln.key}: says {', '.join(f'{v:g}' for v in bad)}, which isn't in the facts, the "
                       f"tools' data or a slot's limits")
                # generated specs: an error (the setup LLM must put every number it states in the facts); written by
                # a person: a warning (an example answer such as "तीन लाख" is fine there)
                (errors if spec.generated else number_warnings).append(msg)
    spec.warnings = number_warnings
    return errors


def _warnings(spec: Spec) -> list[str]:
    from . import hindi
    out = []
    greet = spec.states.get(spec.start)
    if greet is not None and greet.expect == "yes_no":
        nxt = spec.states.get(greet.on.get("yes"))
        if nxt is not None and nxt.expect in spec.slots and spec.slots[nxt.expect].type == "name" \
                and nxt.expect not in greet.also:
            out.append(f"state {greet.name}: callers often give their name with the yes; add also: [{nxt.expect}] "
                       f"and skip_if: {nxt.expect} on {nxt.name}")
    for st, sl, text in _asking_lines(spec):
        if sl.type == "choice" and not sl.option_spans(text):
            out.append(f"line {st.say}: asks for {sl.name} without naming its options")
    for k, v in spec.knowledge.items():
        items = [x for x in str(v).split(",") if x.strip()]
        if len(items) >= 3:
            n = float(len(items))
            if n not in hindi.number_values(str(v)) and str(len(items)) not in str(v):
                out.append(f"knowledge {k}: lists {len(items)} things without saying how many (\"{len(items)} plans\" "
                           f"lets the agent say the count)")
    return out


def _check_intent_target(spec: Spec, event: str, target: str, where: str, errors: list[str]) -> None:
    """An intent found by its phrases fires on a passing mention ("सात दिन का ट्रायल?" contains "ट्रायल"), so it
    must lead to a question, not straight to a tool that acts, unless the spec says the action is harmless."""
    it = spec.intents.get(event)
    if it is None or not it.phrases or it.act_directly:
        return
    st = spec.states.get(target)
    seen = set()
    while st is not None and st.name not in seen:
        seen.add(st.name)
        if st.tool:
            tool = spec.tools.get(st.tool)
            if st.tool == "handover" and not (tool and tool.commits):
                return                    # handing over to a person is the safe answer to anything
            errors.append(f"{where}: intent {event} leads to the tool {st.tool} without asking first ("
                          + ("it commits; " if tool and tool.commits else "") + "add a yes/no question before it"
                          + ("" if spec.generated else ", or act_directly: true if it's harmless") + ")")
            return
        if st.expect or st.end:
            return
        st = spec.states.get(st.next)


def _saved_names(spec: Spec) -> set[str]:
    out = set()
    for t in spec.tools.values():
        out |= set(t.save)
    out |= set((spec.backend.get("start") or {}).get("save", {}))
    for st in spec.states.values():
        out |= set(st.with_)
    return out
