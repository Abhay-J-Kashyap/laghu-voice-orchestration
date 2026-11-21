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
    states    the flow; the target `back` returns to the question asked before a detour
    global    where built-in requests (and the spec's own intents) go from any state
"""
from __future__ import annotations

import re
import string
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .slots import FORMATS, TYPES, Slot

BUILTIN_INTENTS = {"answer", "yes", "no", "human", "repeat", "question", "off_topic", "stop", "unclear", "hold"}
BUILTIN_VARS = {"agent", "company", "call_id", "session_id", "last_caller_text", "state"}
FEMININE_RE = re.compile(r"(?:ती|रही|गई) हू[ँं]|[ूऊ][ँं]गी")
LATIN_RE = re.compile(r"[A-Za-z]")


class SpecError(ValueError):
    pass


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
    require_heard: float = 0.0

    def __post_init__(self):
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
    d = {(rename or {}).get(k, k): v for k, v in (d or {}).items()}
    unknown = set(d) - set(cls.__dataclass_fields__)
    if unknown:
        raise SpecError(f"{what} {name}: unknown keys {sorted(unknown)}")
    return cls(name=name, **d) if "name" in cls.__dataclass_fields__ else cls(key=name, **d)


def load_spec(path: str | Path) -> Spec:
    path = Path(path)
    raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_Loader)  # noqa: S506 - a SafeLoader subclass
    lines = {}
    for k, v in (raw.get("lines") or {}).items():
        if isinstance(v, str):
            lines[k] = Line(k, text=v)
        elif isinstance(v, dict) and set(v) <= {"llm", "example"} and "llm" in v and "example" in v:
            lines[k] = Line(k, goal=v["llm"], example=v["example"])
        else:
            raise SpecError(f"line {k}: a string, or {{llm: goal, example: text}}")
    spec = Spec(
        agent=raw["agent"], timing=raw.get("timing") or {}, context=raw.get("context") or {},
        knowledge=raw.get("knowledge") or {},
        slots={k: _make(Slot, k, v, "slot") for k, v in (raw.get("slots") or {}).items()},
        intents={k: _make(Intent, k, v, "intent") for k, v in (raw.get("intents") or {}).items()},
        lines=lines, backend=raw.get("backend") or {"provider": "mock"},
        tools={k: _make(Tool, k, v, "tool") for k, v in (raw.get("tools") or {}).items()},
        states={k: _make(State, k, v, "state", {"with": "with_"}) for k, v in (raw.get("states") or {}).items()},
        global_=raw.get("global") or {}, path=path)
    check(spec)
    return spec


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
            if LATIN_RE.search(re.sub(r"\{[\w:]+\}", "", t)):
                errors.append(f"line {ln.key}: has English letters (Laghu drops them)")
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
    events_ok = BUILTIN_INTENTS | set(spec.intents)
    for t in spec.tools.values():
        if not t.events or "if" in t.events[-1]:
            errors.append(f"tool {t.name}: the last event rule needs no `if` (a catch-all)")
        if spec.http and not t.path:
            errors.append(f"tool {t.name}: no path")
        if not spec.http and not t.mock:
            errors.append(f"tool {t.name}: mock backend, but no mock answers")
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
    if errors:
        raise SpecError("; ".join(errors))


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
            errors.append(f"{where}: intent {event} leads to the tool {st.tool} without asking first "
                          f"(add a question, or act_directly: true if it's harmless)")
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
