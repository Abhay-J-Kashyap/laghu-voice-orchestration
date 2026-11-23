"""The setup tool (Milestone 5): a use case described in plain English becomes a checked, tested agent spec.

    python -m laghu_voice.setup m5/use_cases/mba.md            # ask, draft, check, repair, simulate, review
    python -m laghu_voice.setup m5/use_cases/mba.md --answers answers.json    # questions answered in a file
    python -m laghu_voice.setup approve m5/out/setup/mba        # copy the approved spec to agents/

Steps, each saved in the output folder so a run can be read afterwards:
1. questions.json: up to 8 questions about facts the description lacks; the person answers in the terminal.
   Nothing is ever made up: an unanswered question is a fact the agent won't state.
2. Drafting, in three requests so each fits Groq's per-minute limit: the basics (persona, facts, slots,
   intents), the flow (states, tools, the lines it needs), then the lines in batches.
3. The checker (spec.check, generated mode). Errors go back to the model as a patch request, at most 3 rounds.
4. Simulated calls: one per kind of caller (setup/simulate.py). Failures go back as a patch request, at most 2
   rounds; only the failed callers are rerun, and the checker runs again after each patch.
5. review.md: every Hindi line with its English meaning, the flow, the facts, the warnings, the test calls.
   Nobody edits spec.yaml by hand; `approve` copies it to agents/.
"""
from __future__ import annotations

import argparse
import asyncio
import contextvars
import copy
import json
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

from ..dialog.spec import SpecError, build_spec
from .guide import GUIDE

MAX_QUESTIONS = 8
CHECK_ROUNDS = 5
SIM_ROUNDS = 2
LINE_BATCH = 10


# Progress for a watcher (the web UI): run_setup(events=callback) gets every step as a dict {"type": ..., ...}.
# A context variable, so the Drafter's own messages reach the same callback without passing it everywhere.
_EVENTS: contextvars.ContextVar = contextvars.ContextVar("setup_events", default=None)


def emit(_type: str, **data) -> None:
    cb = _EVENTS.get()
    if cb is not None:
        try:
            cb({**data, "type": _type, "at": round(time.time(), 2)})
        except Exception:                      # noqa: BLE001 - a watcher's failure never stops setup
            pass


def log(msg: str) -> None:
    print(msg, flush=True)
    emit("log", text=msg.strip())


def strip_thinking(text: str) -> str:
    """A model's thinking, if it came back in the answer anyway (<think>...</think>)."""
    return re.sub(r"<think>.*?(?:</think>|$)", "", text or "", flags=re.S).strip()


def parse_obj(text: str) -> dict:
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", strip_thinking(text))
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        raise ValueError(f"no JSON object in: {t[:200]}")
    return json.loads(m.group(0))


class Drafter:
    """The LLM side of setup. `llm` is any client with complete() (Groq gpt-oss-120b, paced)."""

    def __init__(self, llm, description: str, answers: list[dict]):
        self.llm = llm
        self.description = description.strip()
        self.answers = answers
        self.requests = 0

    def _brief(self) -> str:
        qa = "\n".join(f"- {a['q']} -> {a['a'] or 'not known: the agent must not state it'}" for a in self.answers)
        return f"USE CASE (from the business):\n{self.description}\n\nTHE OWNER'S ANSWERS:\n{qa or '(none)'}"

    async def ask(self, system: str, user: str, max_tokens: int = 4000) -> dict:
        from ..services.llm_openai import LLMStats
        self.requests += 1
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        last, why, override = None, "", {}
        for _ in range(3):
            stats = LLMStats()
            text = await complete_json(self.llm, messages, max_tokens, temperature=0.2, stats=stats, **override)
            try:
                return parse_obj(text)
            except (ValueError, json.JSONDecodeError) as e:
                last = e
                why = f"finish_reason {stats.finish_reason}, {len(text or '')} characters"
                # Empty or cut off: the thinking used the reply's tokens. Asking the same again fails the same
                # way, so once more with the thinking off, if the model can turn it off.
                if (not strip_thinking(text) or stats.finish_reason == "length") and not override:
                    override = thinking_off(getattr(self.llm, "model", ""))
                    if override:
                        log(f"   the reply was empty or cut off ({why}); asking again with reasoning off")
        raise RuntimeError(f"the model didn't return JSON ({why}): {last}")

    async def questions(self) -> list[str]:
        sys_ = ("You set up a Hindi phone agent for a business. Before writing it, list what you must ask the "
                "owner: facts the agent needs that the description doesn't give (prices, timings, rules, what "
                "counts as done, when to hand over to a person, what is booked or recorded). Don't ask about "
                "wording or flow; you decide those. At most 8 short questions in English, most important first, "
                'as JSON {"questions": [...]}. An empty list is fine.')
        out = await self.ask(sys_, f"USE CASE:\n{self.description}", max_tokens=1500)
        return [str(q) for q in out.get("questions", [])][:MAX_QUESTIONS]

    async def basics(self) -> dict:
        sys_ = GUIDE + ("\n\nWrite the first part of the spec: agent, knowledge, slots and intents, as one JSON "
                        "object with those four keys. Collect only what the use case needs.")
        out = await self.ask(sys_, self._brief())
        return {k: out.get(k) or {} for k in ("agent", "knowledge", "slots", "intents")}

    async def flow(self, basics: dict) -> dict:
        sys_ = GUIDE + ("\n\nWrite the flow: states, tools and global, as one JSON object with those keys, plus "
                        '"lines_needed": {"<line key>": {"kind": "fixed" | "template" | "llm", "purpose": '
                        '"English: what the line says"}} for every line your states say and every re-ask line '
                        "your slots name (not the engine's own lines).")
        user = self._brief() + "\n\nTHE SPEC SO FAR:\n" + json.dumps(basics, ensure_ascii=False)
        out = await self.ask(sys_, user, max_tokens=5000)
        return {k: out.get(k) or {} for k in ("states", "tools", "global", "lines_needed")}

    async def lines(self, basics: dict, needed: dict, keep: Path | None = None) -> tuple[dict, dict]:
        """The lines, in batches. Returns (lines, English meanings). A batch kept from an earlier run is reused."""
        lines, en = {}, {}
        keys = list(needed)
        ctx = {"agent": basics["agent"], "knowledge": basics["knowledge"],
               "slots": {k: {x: v[x] for x in ("type", "describe", "labels") if x in v}
                         for k, v in basics["slots"].items()}}
        for i in range(0, len(keys), LINE_BATCH):
            batch = {k: needed[k] for k in keys[i:i + LINE_BATCH]}
            kept = keep / f"lines_{i // LINE_BATCH}.json" if keep is not None else None
            if kept is not None and kept.exists():
                got = json.loads(kept.read_text(encoding="utf-8"))
                if set(got["lines"]) >= set(batch):
                    lines.update(got["lines"])
                    en.update(got["en"])
                    log(f"   lines {i + 1}-{i + len(batch)}: kept from the last run")
                    emit("draft", step="lines", status="kept", done=i + len(batch), total=len(keys))
                    continue
            b_lines, b_en = {}, {}
            sys_ = GUIDE + ('\n\nWrite these lines. Answer as JSON {"<key>": {"text": "<Hindi>", "en": "<English '
                            'meaning>"}} for fixed lines and templates, or {"<key>": {"llm": "<English goal>", '
                            '"example": "<Hindi>", "en": "<English meaning of the example>"}} for llm lines.')
            user = (self._brief() + "\n\nCONTEXT:\n" + json.dumps(ctx, ensure_ascii=False) +
                    "\n\nLINES TO WRITE:\n" + json.dumps(batch, ensure_ascii=False))
            emit("draft", step="lines", status="start", done=i, total=len(keys))
            out = await self.ask(sys_, user, max_tokens=4000)
            emit("draft", step="lines", status="done", done=i + len(batch), total=len(keys))
            for k, v in out.items():
                if not isinstance(v, dict):
                    continue
                if "llm" in v:
                    b_lines[k] = {"llm": v["llm"], "example": v.get("example", "")}
                elif "text" in v:
                    b_lines[k] = v["text"]
                b_en[k] = v.get("en", "")
            lines.update(b_lines)
            en.update(b_en)
            if kept is not None:
                kept.parent.mkdir(parents=True, exist_ok=True)
                kept.write_text(json.dumps({"lines": b_lines, "en": b_en}, ensure_ascii=False), encoding="utf-8")
        return lines, en

    async def meanings(self, lines: dict) -> dict:
        """English meanings for lines that have none (a re-ask the code turned into a line, a repair that
        forgot "en"): the review must be readable without Hindi."""
        if not lines:
            return {}
        sys_ = ('Give the English meaning of each Hindi line, as JSON {"<key>": "<English>"}. For an llm line '
                "give the meaning of its example.")
        text = {k: (v if isinstance(v, str) else v.get("example", "")) for k, v in lines.items()}
        out = await self.ask(sys_, json.dumps(text, ensure_ascii=False), max_tokens=1500)
        return {k: str(v) for k, v in out.items() if k in lines and isinstance(v, (str, int, float))}

    async def patch(self, raw: dict, en: dict, problems: list[str], what: str) -> tuple[dict, dict]:
        """Fix problems: the model returns replacements for whole items; null removes one."""
        sys_ = GUIDE + ("\n\nFix the problems listed by changing the spec as little as possible. Answer as JSON "
                        '{"<section>": {"<key>": <the whole new item, or null to remove it>}} with sections among '
                        "agent, knowledge, slots, intents, tools, states, global, lines. A new or changed line "
                        'carries its English meaning: {"lines": {"<key>": {"text" or "llm"+"example": ..., '
                        '"en": "..."}}}. Never add a fact the use case doesn\'t give. Send ONLY the items you '
                        "change (never repeat an unchanged line or state): the reply must stay short.")
        user = (self._brief() + f"\n\n{what}:\n" + "\n".join(f"- {p}" for p in problems) +
                "\n\nTHE SPEC (lines not named in the problems are shortened to their kind):\n" +
                json.dumps(_context_for(raw, problems), ensure_ascii=False))
        out = await self.ask(sys_, user, max_tokens=5000)
        raw = copy.deepcopy(raw)
        en = dict(en)
        for section, items in out.items():
            if section not in raw and section not in ("agent", "knowledge", "slots", "intents", "tools", "states",
                                                       "global", "lines"):
                continue
            if section == "agent" and isinstance(items, dict):
                raw["agent"] = {**raw.get("agent", {}), **items}
                continue
            if not isinstance(items, dict):
                continue
            target = raw.setdefault(section, {})
            for k, v in items.items():
                if v is None:
                    target.pop(k, None)
                    if section == "lines":
                        en.pop(k, None)
                elif section == "lines" and isinstance(v, dict):
                    if "llm" in v:
                        target[k] = {"llm": v["llm"], "example": v.get("example", "")}
                    elif "text" in v:
                        target[k] = v["text"]
                    en[k] = v.get("en", en.get(k, ""))
                elif isinstance(v, dict) and isinstance(target.get(k), dict) and _partial(section, v):
                    merged = {**target[k], **v}      # the model sent only the changed keys: keep the rest
                    target[k] = {a: b for a, b in merged.items() if b is not None}
                else:
                    target[k] = v
        return normalize(raw, en)


def _partial(section: str, item: dict) -> bool:
    """A repair item that carries only some keys of an item (the model sent what it changed): merged into the
    existing item. A whole item replaces it, so a key the model dropped on purpose stays dropped."""
    kinds = {"slots": {"type"}, "states": {"expect", "tool", "next", "end"}, "tools": {"mock", "path", "events"},
             "intents": {"describe"}}.get(section)
    return kinds is not None and not (kinds & set(item))


_LETTERS = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", ["ए", "बी", "सी", "डी", "ई", "एफ", "जी", "एच", "आई", "जे", "के",
                                                    "एल", "एम", "एन", "ओ", "पी", "क्यू", "आर", "एस", "टी", "यू",
                                                    "वी", "डब्ल्यू", "एक्स", "वाई", "ज़ेड"]))
_OUTCOME_WORDS = [("no_contact", ("silence", "no_response", "no_answer", "unreachable", "no_contact")),
                  ("transferred", ("transfer", "handover", "hand_over", "human", "escalat")),
                  ("failed", ("fail", "error", "tech")),
                  ("declined", ("declin", "refus", "not_interest", "no_thanks", "reject", "busy")),
                  ("success", ("success", "book", "confirm", "complet", "done", "schedul", "callback", "regist",
                               "enrol", "enroll"))]
_NEGATION = re.compile(r"(?:^|_)(?:not|no|non|never|without|cancel\w*)(?:_|$)|(?:^|_)un(?:confirm|book|schedul)")


def guess_outcome(*names: str) -> str | None:
    """An ending's outcome from its state name, end reason or a wrong outcome word. A negated name ("no_booking",
    "not_confirmed") is never guessed a success: it stays unset, and the checker sends it back."""
    hay = "_".join(re.sub(r"[^a-z]+", "_", str(n).lower()).strip("_") for n in names if n)
    for outcome, words in _OUTCOME_WORDS:
        if any(w in hay for w in words):
            if outcome == "success" and _NEGATION.search(hay):
                return None
            return outcome
    return None


def spell_acronyms(text: str) -> str:
    """MBA -> एमबीए: Laghu drops English letters, so an acronym is written as its letters' names."""
    def fix(chunk: str) -> str:
        return re.sub(r"(?<![A-Za-z])[A-Z]{2,}(?![A-Za-z])", lambda m: "".join(_LETTERS[c] for c in m.group(0)),
                      chunk)
    return "".join(part if part.startswith("{") else fix(part) for part in re.split(r"(\{[^}]*\})", text))


def normalize(raw: dict, en: dict) -> tuple[dict, dict]:
    """Fix by code what the model keeps getting slightly wrong, so a repair round is spent on real problems:
    an ending's outcome (from its name), a re-ask given as a sentence instead of a line key, acronyms in
    English letters (in lines, labels, and the phrases callers say: transcripts are in Devanagari)."""
    from ..dialog.spec import OUTCOMES
    raw, en = copy.deepcopy(raw), dict(en)
    lines = raw.setdefault("lines", {})
    for name, st in (raw.get("states") or {}).items():
        if not isinstance(st, dict) or st.get("end") is None:
            continue
        if isinstance(st["end"], dict):                    # {end: {reason: .., outcome: ..}}
            inner = st["end"]
            st["end"] = str(inner.get("reason") or name)
            st.setdefault("outcome", inner.get("outcome"))
        if st.get("outcome") not in OUTCOMES:
            guess = guess_outcome(name, st["end"], st.get("outcome") or "")
            if guess is not None:
                st["outcome"] = guess
    for name, slot in (raw.get("slots") or {}).items():
        reask = slot.get("reask") if isinstance(slot, dict) else None
        if not isinstance(reask, dict):
            continue
        for kind, val in list(reask.items()):
            if isinstance(val, str) and val not in lines and re.search(r"[\u0900-\u097F]", val):
                key, n = f"reask_{name}_{kind}", 2
                while key in lines:
                    key, n = f"reask_{name}_{kind}_{n}", n + 1
                lines[key] = val
                reask[kind] = key
    for key, v in list(lines.items()):
        if isinstance(v, str):
            lines[key] = spell_acronyms(v)
        elif isinstance(v, dict) and isinstance(v.get("example"), str):
            v["example"] = spell_acronyms(v["example"])
    for slot in (raw.get("slots") or {}).values():
        if not isinstance(slot, dict):
            continue
        if isinstance(slot.get("labels"), dict):
            slot["labels"] = {k: spell_acronyms(x) if isinstance(x, str) else x for k, x in slot["labels"].items()}
        if isinstance(slot.get("options"), dict):
            slot["options"] = {k: [spell_acronyms(x) if isinstance(x, str) else x for x in xs]
                               if isinstance(xs, list) else xs for k, xs in slot["options"].items()}
    for it in (raw.get("intents") or {}).values():
        if isinstance(it, dict) and isinstance(it.get("phrases"), list):
            it["phrases"] = [spell_acronyms(x) if isinstance(x, str) else x for x in it["phrases"]]
    _option_keys_in_mocks(raw)
    _option_placeholders(raw)
    _spoken_forms(raw)
    _options_in_questions(raw)
    _drop_unused_slots(raw)
    return raw, en


def _options_in_questions(raw: dict) -> None:
    """"आप किस प्रोग्राम में रुचि रखते हैं? {program:words}": the model meant the options, but the value is still empty
    when the question is asked. The options' Hindi labels go there instead ("A, B या C")."""
    slots, lines = raw.get("slots") or {}, raw.get("lines") or {}
    for st in (raw.get("states") or {}).values():
        if not isinstance(st, dict):
            continue
        name, key = st.get("expect"), st.get("say")
        sl = slots.get(name) if isinstance(name, str) else None
        if not isinstance(sl, dict) or sl.get("type") != "choice" or key not in lines:
            continue
        labels = [v for v in (sl.get("labels") or {}).values() if isinstance(v, str)]
        if not labels:
            continue
        words = labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " या " + labels[-1]
        pat = re.compile(r"\{" + re.escape(name) + r"(?::\w+)?\}")
        v = lines[key]
        if isinstance(v, str):
            lines[key] = pat.sub(words, v)
        elif isinstance(v, dict) and isinstance(v.get("example"), str):
            v["example"] = pat.sub(words, v["example"])


def _drop_unused_slots(raw: dict) -> None:
    """A slot no state asks for and nothing reads (the MBA draft's phone, from the owner's answer "phone"): the
    test callers would say it unasked, and a private one is only noise to hide."""
    used = set()
    for st in (raw.get("states") or {}).values():
        if isinstance(st, dict):
            used |= {st.get("expect"), st.get("skip_if")} | set(st.get("also") or []) | set(st.get("corrections") or [])
    text = json.dumps([raw.get("lines"), raw.get("tools"), raw.get("backend")], ensure_ascii=False)
    used |= set(re.findall(r"\{(\w+)", text)) | set(re.findall(r'"if": \{"(\w+)"', text))
    for name in [k for k in (raw.get("slots") or {}) if k not in used]:
        del raw["slots"][name]


_FRACTION_WORDS = {1.5: "डेढ़", 2.5: "ढाई"}


def digits_to_words(text: str) -> str:
    """30 -> तीस, 8.5 -> साढ़े आठ, 1.5 -> डेढ़ (Laghu reads Hindi words, not digits). Other decimals stay, and the
    checker sends them back."""
    from ..dialog import hindi

    def one(m):
        v = float(m.group(0))
        if v.is_integer():
            return hindi.num_words(int(v))
        if v in _FRACTION_WORDS:
            return _FRACTION_WORDS[v]
        if v % 1 == 0.5 and v > 2:
            return "साढ़े " + hindi.num_words(int(v))
        return m.group(0)
    parts = re.split(r"(\{[^}]*\})", text)
    return "".join(x if x.startswith("{") else re.sub(r"\d+(?:\.\d+)?", one, x) for x in parts)


def _spoken_forms(raw: dict) -> None:
    """Lines as the agent will say them: digits as words, the odd hyphens a model writes ("पूरा‑समय") as spaces,
    and a slot placeholder without a format given the one for its type ({session_time} -> {session_time:time})."""
    from ..dialog.spec import DEFAULT_FORMAT
    types = {k: v.get("type") for k, v in (raw.get("slots") or {}).items() if isinstance(v, dict)}

    def fix(text: str) -> str:
        text = re.sub(r"[\u2010\u2011\u2012]", " ", text)
        text = re.sub(r"\{(\w+)\}", lambda m: "{%s:%s}" % (m.group(1), DEFAULT_FORMAT[types[m.group(1)]])
                      if types.get(m.group(1)) in DEFAULT_FORMAT else m.group(0), text)
        return digits_to_words(text)
    lines = raw.get("lines") or {}
    for k, v in lines.items():
        if isinstance(v, str):
            lines[k] = fix(v)
        elif isinstance(v, dict) and isinstance(v.get("example"), str):
            v["example"] = fix(v["example"])
    for sl in (raw.get("slots") or {}).values():
        if isinstance(sl, dict) and isinstance(sl.get("labels"), dict):
            sl["labels"] = {k: fix(x) if isinstance(x, str) else x for k, x in sl["labels"].items()}


def _option_of(slot: dict, value) -> str | None:
    """The option key a mock condition means: the key itself, or its label or a phrase, any case."""
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    for key, phrases in (slot.get("options") or {}).items():
        names = [key, (slot.get("labels") or {}).get(key, "")] + (phrases if isinstance(phrases, list) else [])
        if any(isinstance(n, str) and n.strip().lower() == v for n in names):
            return key
    return None


def _option_keys_in_mocks(raw: dict) -> None:
    """A mock condition on a choice slot written with the label ("Full-time MBA") instead of the key (full_time)
    never matches, so the tool fails on every call. And a tool that saves nothing (a booking) gets an answer for
    any values at the end: the mock stands in for a system that accepts any booking."""
    slots = raw.get("slots") or {}
    for tool in (raw.get("tools") or {}).values():
        mock = tool.get("mock") if isinstance(tool, dict) else None
        if not isinstance(mock, list) or not mock:
            continue
        for m in mock:
            cond = m.get("if") if isinstance(m, dict) else None
            if not isinstance(cond, dict):
                continue
            for k, want in list(cond.items()):
                sl = slots.get(k)
                if not isinstance(sl, dict) or sl.get("type") != "choice":
                    continue
                if isinstance(want, list):
                    cond[k] = [_option_of(sl, w) or w for w in want]
                elif isinstance(want, str) and want != "present":
                    cond[k] = _option_of(sl, want) or want
        if isinstance(mock[-1], dict) and mock[-1].get("if") and not tool.get("save"):
            mock.append({"outcome": "ok"})


def _option_placeholders(raw: dict) -> None:
    """{full_time} in a line, where full_time is an option key and not a slot: the option's Hindi label."""
    slots = raw.get("slots") or {}
    known = set(slots) | {"agent", "company"} | set(raw.get("context") or {}) | {
        v for t in (raw.get("tools") or {}).values() if isinstance(t, dict) for v in (t.get("save") or {})}
    labels = {}
    for sl in slots.values():
        if isinstance(sl, dict) and sl.get("type") == "choice":
            for key, phrases in (sl.get("options") or {}).items():
                lab = (sl.get("labels") or {}).get(key) or (phrases[0] if isinstance(phrases, list) and phrases else None)
                if isinstance(lab, str):
                    labels.setdefault(key, lab)

    def fix(text: str) -> str:
        return re.sub(r"\{(\w+)\}", lambda m: labels[m.group(1)] if m.group(1) in labels and m.group(1) not in known
                      else m.group(0), text)
    lines = raw.get("lines") or {}
    for k, v in lines.items():
        if isinstance(v, str):
            lines[k] = fix(v)
        elif isinstance(v, dict) and isinstance(v.get("example"), str):
            v["example"] = fix(v["example"])


TOKEN_LIMIT = 7500          # Groq's free tier: 8,000 tokens a minute, and one request may not ask for more


async def complete_json(llm, messages: list[dict], max_tokens: int, temperature: float = 0.2, stats=None,
                        **kw) -> str:
    """One JSON request, sized to fit the per-minute limit (prompt + reply), in JSON mode when the model
    takes it. kw overrides the client's settings for this request (reasoning off)."""
    from ..services.llm_openai import LLMError
    est = len(json.dumps(messages, ensure_ascii=False)) // 3
    max_tokens = max(800, min(max_tokens, TOKEN_LIMIT - est))
    if stats is not None:
        kw["stats"] = stats
    try:
        return await llm.complete(messages, max_tokens=max_tokens, temperature=temperature,
                                  response_format={"type": "json_object"}, **kw)
    except LLMError as e:
        # Groq rejects JSON mode outright on some models ("response_format"), and rejects a reply that isn't
        # valid JSON ("json_validate_failed", e.g. cut off at max_tokens). Either way: once more without JSON mode,
        # and parse_obj finds the object in the text.
        if e.status == 400 and ("response_format" in str(e) or "json_validate_failed" in str(e)):
            return await llm.complete(messages, max_tokens=max_tokens, temperature=temperature, **kw)
        raise


def thinking_off(model: str) -> dict:
    """The setting that turns a model's thinking off for one request, if it has one (gpt-oss can't go below low)."""
    return {"reasoning_effort": "none"} if "qwen" in model.lower() else {}


def _context_for(raw: dict, problems: list[str]) -> dict:
    """The spec as the repair request sees it: the flow whole, the lines the problems name whole, the rest
    shortened, so the request stays under Groq's per-request limit."""
    text = " ".join(problems)
    named = {k for k in raw.get("lines", {}) if re.search(rf"\b{re.escape(k)}\b", text)}
    slots_named = {k for k in raw.get("slots", {}) if re.search(rf"\b{re.escape(k)}\b", text)}
    lines = {k: (v if k in named else ("llm: " + v["llm"] if isinstance(v, dict) else "fixed"))
             for k, v in raw.get("lines", {}).items()}
    slots = {k: (v if k in slots_named else {x: v[x] for x in ("type", "describe", "reask") if x in v} |
                 ({"options": list(v["options"])} if "options" in v else {}))
             for k, v in raw.get("slots", {}).items()}
    return {"agent": raw.get("agent"), "knowledge": raw.get("knowledge"), "slots": slots,
            "intents": raw.get("intents"), "tools": raw.get("tools"), "states": raw.get("states"),
            "global": raw.get("global"), "lines": lines}


def assemble(basics: dict, flow: dict, lines: dict) -> dict:
    return {"agent": {**basics["agent"], "gender": "male"}, "knowledge": basics["knowledge"],
            "slots": basics["slots"], "intents": basics["intents"], "lines": lines,
            "backend": {"provider": "mock"}, "tools": flow["tools"], "states": flow["states"],
            "global": flow["global"]}


def check_raw(raw: dict) -> tuple[list[str], list[str], object | None]:
    """(errors, warnings, spec) for a generated spec."""
    try:
        spec = build_spec(copy.deepcopy(raw), generated=True)
    except SpecError as e:
        return [x.strip() for x in e.errors if x.strip()], [], None
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        return [f"spec shape: {e!r}"], [], None
    return [], list(spec.warnings), spec


def dump_yaml(raw: dict, en: dict, header: str) -> str:
    """The spec as YAML, each line with its English meaning beside it."""
    out = [header.rstrip(), ""]
    for section in ("agent", "knowledge", "slots", "intents"):
        if raw.get(section):
            out.append(yaml.safe_dump({section: raw[section]}, allow_unicode=True, sort_keys=False, width=110))
    out.append("lines:")
    for k, v in raw.get("lines", {}).items():
        if isinstance(v, str):
            out.append(f"  {k}: {json.dumps(v, ensure_ascii=False)}")
        else:
            out.append(f"  {k}:")
            out.append(f"    llm: {json.dumps(v['llm'], ensure_ascii=False)}")
            out.append(f"    example: {json.dumps(v['example'], ensure_ascii=False)}")
        if en.get(k):
            out.append(f"  # {en[k]}")
    out.append("")
    for section in ("backend", "tools", "states", "global"):
        if raw.get(section):
            out.append(yaml.safe_dump({section: raw[section]}, allow_unicode=True, sort_keys=False, width=110))
    return "\n".join(out)


# ---------------------------------------------------------------------------------------------- review
def review(raw: dict, en: dict, spec, warnings: list[str], answers: list[dict], sims: list[dict],
           history: list[str]) -> str:
    a = raw["agent"]
    r = [f"# Review: {a.get('company_en') or a.get('company')}", "",
         "Read this, not the YAML. Approve with `python -m laghu_voice.setup approve <this folder>`.", "",
         "## Who the agent is", "", a.get("persona", ""), "", "## What the agent may say as fact", ""]
    r += [f"- **{k}**: {v}" for k, v in raw.get("knowledge", {}).items()] or ["(none)"]
    r += ["", "## Your answers to its questions", ""]
    unknown = "*(not known: the agent won't state it)*"
    r += [f"- {x['q']} → {x['a'] or unknown}" for x in answers] or ["(none)"]
    r += ["", "## What it asks for", ""]
    for k, s in raw.get("slots", {}).items():
        line = f"- **{k}** ({s.get('type')}): {s.get('describe', '')}"
        if s.get("options"):
            line += "; options: " + ", ".join(s["options"])
        r.append(line)
    r += ["", "## The flow", ""]
    for name, st in raw.get("states", {}).items():
        bits = []
        if st.get("say"):
            bits.append(f"says *{st['say']}*")
        if st.get("expect"):
            bits.append(f"waits for {st['expect']}")
        if st.get("tool"):
            bits.append(f"runs {st['tool']}" + (" (commits)" if raw["tools"].get(st["tool"], {}).get("commits") else ""))
        if st.get("on"):
            bits.append("; ".join(f"{e} → {t}" for e, t in st["on"].items()))
        if st.get("next"):
            bits.append(f"then {st['next']}")
        if st.get("end"):
            bits.append(f"ends: {st.get('outcome')}")
        r.append(f"- **{name}**: " + ", ".join(bits))
    r += ["", "## Every line, with its English meaning", "",
          "Fixed lines are said exactly. LLM lines are written fresh each call; the example shows the style and is "
          "said if the LLM's words fail a check.", ""]
    for k, v in raw.get("lines", {}).items():
        if isinstance(v, str):
            r.append(f"- **{k}** (fixed): {v}  \n  *{en.get(k) or '(no English meaning)'}*")
        else:
            r.append(f"- **{k}** (LLM): goal: {v['llm']}  \n  example: {v['example']}  \n  "
                     f"*{en.get(k) or '(no English meaning)'}*")
    r += ["", "## Warnings from the checker", ""] + ([f"- {w}" for w in warnings] or ["(none)"])
    r += ["", "## Test calls", ""]
    if sims:
        from .simulate import summary
        r += ["```", summary(sims), "```"]
    else:
        r.append("(not run)")
    r += ["", "## What setup did", ""] + [f"- {h}" for h in history]
    return "\n".join(r) + "\n"


# ---------------------------------------------------------------------------------------------- the run
async def run_setup(description_path: Path, out: Path, setup_llm, agent_llm, answers_path: Path | None = None,
                    attach: list[Path] | None = None, simulate: bool = True, ask=input, caller_llm=None,
                    events=None) -> dict:
    """events: a callback for every step (see emit), for a watcher such as the web UI."""
    token = _EVENTS.set(events) if events is not None else None
    try:
        return await _run_setup(description_path, out, setup_llm, agent_llm, answers_path, attach, simulate, ask,
                                caller_llm)
    except Exception as e:
        emit("stopped", error=f"{type(e).__name__}: {str(e)[:300]}", daily_limit=type(e).__name__ == "DailyLimit")
        raise
    finally:
        if token is not None:
            _EVENTS.reset(token)


async def _run_setup(description_path: Path, out: Path, setup_llm, agent_llm, answers_path, attach, simulate, ask,
                     caller_llm) -> dict:
    caller_llm = caller_llm or setup_llm          # the simulated callers' turns
    from .simulate import diagnose, judge, run_call, write_personas
    out.mkdir(parents=True, exist_ok=True)
    _set_aside(out)
    t0 = time.monotonic()
    description = description_path.read_text(encoding="utf-8")
    for p in attach or []:
        description += f"\n\nATTACHED ({p.name}):\n" + p.read_text(encoding="utf-8")
    history: list[str] = []

    # 1. questions
    emit("stage", stage="questions")
    if answers_path is not None:
        answers = json.loads(answers_path.read_text(encoding="utf-8"))
        log(f"answers from {answers_path}")
    else:
        drafter = Drafter(setup_llm, description, [])
        qs = await drafter.questions()
        answers = []
        if qs:
            log(f"\n{len(qs)} question(s) about the business (press Enter if you don't know):")
        for k, q in enumerate(qs, 1):
            a = ask(f"\n{k}. {q}\n> ").strip()
            answers.append({"q": q, "a": a})
    (out / "answers.json").write_text(json.dumps(answers, ensure_ascii=False, indent=1), encoding="utf-8")
    history.append(f"{len(answers)} question(s) asked")
    drafter = Drafter(setup_llm, description, answers)

    # 2. draft (each finished step is kept: a run stopped by the daily limit resumes instead of drafting again)
    emit("stage", stage="drafting")
    keep = out / "cache" / _draft_key(description, answers, getattr(setup_llm, "model", ""))
    basics = await _kept(keep, "basics", "persona, facts, slots and intents", drafter.basics)
    flow = await _kept(keep, "flow", "the flow", lambda: drafter.flow(basics))
    log(f"drafting: {len(flow['lines_needed'])} lines ...")
    lines, en = await drafter.lines(basics, flow["lines_needed"], keep=keep)
    raw, en = normalize(assemble(basics, flow, lines), en)
    repaired = keep / "repaired.json"                  # the checker's repairs so far: a stopped run resumes from them
    if repaired.exists():
        got = json.loads(repaired.read_text(encoding="utf-8"))
        raw, en = got["raw"], got["en"]
        log("checker repairs: kept from the last run")
        emit("check", status="kept")
    (out / "draft.json").write_text(json.dumps({"raw": raw, "en": en}, ensure_ascii=False, indent=1), encoding="utf-8")

    # 3. check and repair
    emit("stage", stage="checking")
    errors, warnings, spec = check_raw(raw)
    emit("check", round=0, errors=errors[:20], n=len(errors))
    rounds = 0
    sims: list[dict] = []
    result = {"ok": False, "errors": errors, "warnings": warnings, "check_rounds": 0}
    try:
        while errors and rounds < CHECK_ROUNDS:
            rounds += 1
            log(f"checker: {len(errors)} error(s); repair round {rounds}")
            for e in errors[:8]:
                log(f"   {e}")
            raw, en = await drafter.patch(raw, en, errors, "THE CHECKER'S ERRORS")
            errors, warnings, spec = check_raw(raw)
            emit("check", round=rounds, errors=errors[:20], n=len(errors))
            repaired.write_text(json.dumps({"raw": raw, "en": en}, ensure_ascii=False), encoding="utf-8")
        history.append(f"checker: {rounds} repair round(s); " + ("passed" if not errors else f"{len(errors)} error(s) left"))
        result.update(ok=not errors, errors=errors, warnings=warnings, check_rounds=rounds)
        _write_spec(out, raw, en, description_path)          # what the test calls run, kept even if they crash

        # 4. simulate and repair
        if simulate and spec is not None:
            emit("stage", stage="testing")
            # the persona writer's reply is long (eight callers): on the setup model, not the caller model
            personas = await write_personas(setup_llm, description, spec, seed="Setup test callers.")
            (out / "personas.json").write_text(json.dumps([p.__dict__ for p in personas], ensure_ascii=False,
                                                          indent=1), encoding="utf-8")
            emit("personas", personas=[{"id": p.id, "kind": p.kind, "expected": p.expected, "name": p.name}
                                       for p in personas])
            last_sig: dict = {}
            calls_file = out / "test_calls.jsonl"
            calls_file.write_text("", encoding="utf-8")
            todo = list(personas)
            for sim_round in range(SIM_ROUNDS + 1):
                rows = []
                for p in todo:
                    log(f"test call {p.id} ({p.kind}) ...")
                    emit("call", id=p.id, kind=p.kind, round=sim_round + 1, status="running")
                    rec, agent, dlm = await run_call(spec, out.name, agent_llm, caller_llm, p, sim_round + 1)
                    rec.verdict = judge(spec, rec, agent, dlm)
                    row = {**rec.__dict__, "round": sim_round + 1}
                    row["diagnosis"] = diagnose(spec, row)
                    rows.append(row)
                    with calls_file.open("a", encoding="utf-8") as f:        # every call, as soon as it ends
                        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                    log(f"   {'ok' if rec.verdict['success'] else 'FAILED'}: ended {rec.outcome} ({rec.end})"
                        + ("" if rec.verdict["success"] else f"; {how_it_ended(row)}")
                        + (f"; likely cause: {row['diagnosis']['cause']}" if row["diagnosis"]["cause"] else ""))
                    emit("call", id=p.id, kind=p.kind, round=sim_round + 1, status="done",
                         ok=bool(rec.verdict["success"] and not rec.verdict["safety"]), outcome=rec.outcome,
                         end=rec.end, expected=p.expected, cause=row["diagnosis"]["cause"],
                         why=row["diagnosis"]["why"][:4], seconds=rec.seconds)
                sims = [x for x in sims if x["persona"]["id"] not in {r["persona"]["id"] for r in rows}] + rows
                failed = [r for r in rows if not r["verdict"]["success"] or r["verdict"]["safety"]]
                history.append(f"test calls, round {sim_round + 1}: {len(rows) - len(failed)}/{len(rows)} passed")
                if not failed or sim_round == SIM_ROUNDS:
                    break
                sig = {r["persona"]["id"]: _failure_sig(r) for r in failed}
                if sim_round and all(last_sig.get(k) == v for k, v in sig.items()):
                    history.append("the last repair didn't change how any call failed: the problem is likely in the "
                                   "engine, not the spec; stopped repairing (see the calls' ends above)")
                    log("   the repair changed nothing: stopping (likely an engine problem, not the spec)")
                    break
                last_sig = sig
                log(f"{len(failed)} test call(s) failed; repair round {sim_round + 1}")
                emit("repair", round=sim_round + 1, failed=[r["persona"]["id"] for r in failed])
                try:
                    new_raw, new_en = await drafter.patch(raw, en, failure_report(failed),
                                                          "TEST CALLS THAT FAILED (expected vs what happened)")
                    errs, warns, new_spec = check_raw(new_raw)
                    fix = 0
                    while errs and fix < CHECK_ROUNDS:
                        fix += 1
                        new_raw, new_en = await drafter.patch(new_raw, new_en, errs, "THE CHECKER'S ERRORS")
                        errs, warns, new_spec = check_raw(new_raw)
                except Exception as e:                      # noqa: BLE001 - keep the spec that ran, say why
                    if type(e).__name__ == "DailyLimit":
                        raise
                    history.append(f"test-call repair {sim_round + 1} failed ({str(e)[:200]}); kept the previous spec")
                    log(f"   the repair failed: {str(e)[:200]}")
                    break
                if errs:
                    history.append("a test-call repair broke the checker; kept the previous spec")
                    break
                raw, en, spec, warnings = new_raw, new_en, new_spec, warns
                _write_spec(out, raw, en, description_path)
                ids = {r["persona"]["id"] for r in failed}
                todo = [p for p in personas if p.id in ids]
    except Exception as e:                                  # noqa: BLE001 - write what there is, then re-raise
        history.append(f"setup stopped: {type(e).__name__}: {str(e)[:300]}")
        result.update(ok=False, stopped=f"{type(e).__name__}: {str(e)[:300]}")
        _finish(out, raw, en, spec, warnings, answers, sims, history, result, description_path, t0, drafter)
        raise
    result["warnings"] = warnings

    # 5. write out
    emit("stage", stage="writing")
    missing = {k: v for k, v in raw.get("lines", {}).items() if not en.get(k)}
    if missing:
        try:
            en.update(await drafter.meanings(missing))
        except Exception as e:                       # noqa: BLE001 - the review says which lines lack English
            history.append(f"English meanings for {len(missing)} line(s) failed: {e}")
    return _finish(out, raw, en, spec, warnings, answers, sims, history, result, description_path, t0, drafter)


def _draft_key(description: str, answers: list, model: str) -> str:
    """Drafting steps are reused only for the same description, answers, guide and model."""
    import hashlib
    blob = json.dumps([description, answers, GUIDE, model], ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


async def _kept(keep: Path, name: str, what: str, make) -> dict:
    f = keep / f"{name}.json"
    if f.exists():
        log(f"drafting: {what} (kept from the last run)")
        emit("draft", step=name, status="kept")
        return json.loads(f.read_text(encoding="utf-8"))
    log(f"drafting: {what} ...")
    emit("draft", step=name, status="start")
    value = await make()
    emit("draft", step=name, status="done")
    keep.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return value


OUTPUTS = ("draft.json", "spec.yaml", "en.json", "personas.json", "test_calls.jsonl", "review.md", "setup.json")


def _set_aside(out: Path) -> None:
    """A run's results start empty: the last run's move to previous/<time>, so a run that stops early is never
    mistaken for the last one (answers.json stays: --answers may point at it)."""
    old = [out / f for f in OUTPUTS if (out / f).exists()]
    if not old:
        return
    dest = out / "previous" / datetime.fromtimestamp(max(f.stat().st_mtime for f in old)).strftime("%Y-%m-%d_%H%M%S")
    dest.mkdir(parents=True, exist_ok=True)
    for f in old:
        shutil.move(str(f), str(dest / f.name))


def _write_spec(out: Path, raw: dict, en: dict, description_path: Path) -> None:
    header = (f"# Generated by the setup tool from {description_path.name} on {datetime.now():%Y-%m-%d %H:%M}.\n"
              f"# Don't edit by hand: change the description or the answers and run setup again.")
    (out / "spec.yaml").write_text(dump_yaml(raw, en, header), encoding="utf-8")
    (out / "en.json").write_text(json.dumps(en, ensure_ascii=False, indent=1), encoding="utf-8")


def _finish(out, raw, en, spec, warnings, answers, sims, history, result, description_path, t0, drafter) -> dict:
    _write_spec(out, raw, en, description_path)
    (out / "review.md").write_text(review(raw, en, spec, warnings, answers, sims, history), encoding="utf-8")
    result.update(minutes=round((time.monotonic() - t0) / 60, 1), requests=drafter.requests,
                  test_calls=len(sims), passed=sum(1 for s in sims if s["verdict"]["success"]))
    (out / "setup.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    if not result.get("stopped"):
        emit("finished", result=result)
    return result


def _ending(r: dict) -> tuple[list[str], list[str]]:
    """(tools that failed, the last states the call went through)."""
    failed = [t[0] for t in r.get("tools", []) if t[1] == "error"]
    states: list[str] = []
    for st in r.get("steps", [])[-3:]:
        for x in (st.get("state_in"), st.get("state_out")):
            if x and (not states or states[-1] != x):
                states.append(x)
    return failed, states[-4:]


def _failure_sig(r: dict) -> tuple:
    """How a call failed, for spotting a repair that changed nothing: outcome, failed tools, where it ended, why."""
    tools, states = _ending(r)
    last = (r.get("steps") or [{}])[-1]
    return r["outcome"], tuple(tools), tuple(states[-2:]), last.get("event"), last.get("problem")


def how_it_ended(r: dict) -> str:
    """Why a call ended where it did, in a few words: a tool that failed, the last states, the caller's last event."""
    failed, states = _ending(r)
    bits = [f"tool {t} failed (no mock answer matched, or the backend erred)" for t in dict.fromkeys(failed)]
    if r.get("end") and (not states or states[-1] != r["end"]):
        states = states + [f"end {r['end']}"]
    if states:
        bits.append("went " + " -> ".join(states))
    steps = r.get("steps", [])
    last = steps[-1] if steps else {}
    if last.get("event"):
        bits.append(f"last caller event {last['event']}" + (f" ({last['problem']})" if last.get("problem") else ""))
    if last.get("stuck"):
        bits.append("handed over: three turns in a row changed nothing")
    if r.get("error"):
        bits.append(str(r["error"]))
    return "; ".join(bits)


def failure_report(failed: list[dict], keep: int = 3) -> list[str]:
    """The failed calls for the repair request, short enough to leave room for the reply: calls that went wrong
    the same way (same outcome, same failed tool, same last states) are counted, and the first is shown whole."""
    groups: dict[tuple, list[dict]] = {}
    for r in failed:
        tools, states = _ending(r)
        groups.setdefault((r["outcome"], tuple(tools), tuple(states[-2:])), []).append(r)
    out = []
    for rows in groups.values():
        more = ""
        if len(rows) > 1:
            more = (f" (and {len(rows) - 1} more call(s) went wrong the same way: "
                    + ", ".join(x["persona"]["id"] for x in rows[1:]) + ")")
        out.append(_failure_text(rows[0]) + more)
    return out[:keep]


def _failure_text(r: dict) -> str:
    v = r["verdict"]
    why = []
    if not v["outcome_ok"]:
        why.append(f"ended {r['outcome']} ({r['end']}), expected {r['persona']['expected']}")
    why += [f"{k}: {x}" for k, x in v["facts"].items() if x not in ("matched", "no persona value")]
    why += v["safety"]
    if v.get("error"):
        why.append(v["error"])
    why.append(how_it_ended(r))
    tail = " | ".join(f"{w}: {t}" for w, t, _ in r["transcript"][-6:])
    return (f"caller {r['persona']['id']} ({r['persona']['kind']}; facts {json.dumps(r['persona']['facts'], ensure_ascii=False)}): "
            + "; ".join(x for x in why if x) + f". States passed: {', '.join(r['visited'])}. End of the call: {tail}")


def approve(folder: Path, agents_dir: Path) -> Path:
    res = json.loads((folder / "setup.json").read_text(encoding="utf-8"))
    if not res.get("ok"):
        raise SystemExit("this spec still has checker errors; it can't be approved")
    dest = agents_dir / f"{folder.name.replace('-', '_')}.yaml"
    shutil.copyfile(folder / "spec.yaml", dest)
    res["approved"] = {"at": datetime.now().isoformat(timespec="seconds"), "as": str(dest)}
    (folder / "setup.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return dest


def build_clients():
    import os

    from ..config import Settings
    from ..services.llm_openai import OpenAICompatLLM
    from ..services.paced import PacedLLM
    s = Settings()
    if not s.llm_api_key:
        raise SystemExit("GROQ_API_KEY isn't set (.env)")
    setup_model = os.environ.get("SETUP_MODEL", "openai/gpt-oss-120b")
    effort = os.environ.get("SETUP_REASONING", "low")      # medium thinks longer, but often runs past 8,000/min
    setup = PacedLLM(OpenAICompatLLM(s.llm_base_url, s.llm_api_key, setup_model, reasoning_params(setup_model, effort)))
    agent = PacedLLM(OpenAICompatLLM(s.llm_base_url, s.llm_api_key, s.llm_model, s.llm_extra))
    caller_model = os.environ.get("CALLER_MODEL")   # the test callers on another model, with its own daily limit
    caller = (PacedLLM(OpenAICompatLLM(s.llm_base_url, s.llm_api_key, caller_model,
                                       reasoning_params(caller_model, "none")))
              if caller_model and caller_model != setup_model else setup)
    log(f"setup model {setup_model}, agent model {s.llm_model}, caller model {caller_model or setup_model}")
    return setup, agent, caller


def reasoning_params(model: str, effort: str) -> dict:
    """Groq's reasoning settings differ by model (console.groq.com/docs/reasoning, read 2026-11-22): gpt-oss takes
    effort low/medium/high and include_reasoning; Qwen takes effort none/default/low/medium/high and
    reasoning_format (hidden keeps the thinking out of the answer). Other models get none."""
    m = model.lower()
    if "gpt-oss" in m:
        return {"reasoning_effort": "low" if effort == "none" else effort, "include_reasoning": False}
    if "qwen" in m:
        return {"reasoning_effort": effort, "reasoning_format": "hidden"}
    return {}


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    root = Path(__file__).resolve().parents[2]
    if argv and argv[0] == "approve":
        ap = argparse.ArgumentParser(prog="python -m laghu_voice.setup approve")
        ap.add_argument("folder")
        a = ap.parse_args(argv[1:])
        dest = approve(Path(a.folder), root / "agents")
        print(f"approved: {dest}\nrun it: python -m laghu_voice.server --tts laghu --dialog agent --agent-spec {dest}")
        return
    ap = argparse.ArgumentParser(prog="python -m laghu_voice.setup", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("description", help="the use case in plain English (a .md or .txt file)")
    ap.add_argument("--out", help="output folder (default m5/out/setup/<description name>)")
    ap.add_argument("--answers", help="answers to the questions, as JSON [{q, a}] (skips asking)")
    ap.add_argument("--attach", nargs="*", default=[], help="text files with more facts (fees, FAQ)")
    ap.add_argument("--no-sim", action="store_true", help="don't run the test calls")
    a = ap.parse_args(argv)
    desc = Path(a.description)
    out = Path(a.out) if a.out else root / "m5" / "out" / "setup" / desc.stem
    setup_llm, agent_llm, caller_llm = build_clients()

    async def go():
        try:
            return await run_setup(desc, out, setup_llm, agent_llm, Path(a.answers) if a.answers else None,
                                   [Path(p) for p in a.attach], simulate=not a.no_sim, caller_llm=caller_llm)
        finally:
            for c in {id(x): x for x in (setup_llm, agent_llm, caller_llm)}.values():
                await c.aclose()
    from ..services.paced import DailyLimit
    try:
        res = asyncio.run(go())
    except DailyLimit as e:
        raise SystemExit(f"\nGroq's daily token limit for this model was reached ({str(e)[:160]}).\nIt counts the last 24 "
                         f"hours, so tokens free up 24 hours after they were used: check console.groq.com/settings/"
                         f"limits. Run the same command again then; the drafting done so far is kept and reused.") from e
    except Exception as e:                                 # noqa: BLE001 - say where the work so far is
        have = [f for f in OUTPUTS if (out / f).exists()]
        raise SystemExit(f"\nsetup stopped: {type(e).__name__}: {str(e)[:400]}\n"
                         + (f"What it wrote so far ({', '.join(have)}) is in {out}." if have else
                            "It stopped before writing anything.")) from e
    all_passed = not res.get("test_calls") or res["passed"] == res["test_calls"]
    print(f"\n{'OK' if res['ok'] and all_passed else 'NOT OK'}: {out / 'review.md'}")
    if res.get("test_calls"):
        print(f"test calls: {res['passed']}/{res['test_calls']} passed")
    if res["errors"]:
        print("checker errors left:\n  " + "\n  ".join(res["errors"]))
    print(f"{res['minutes']} min, {res['requests']} drafting requests; tokens used: setup model "
          f"{setup_llm.used_total}, agent model {agent_llm.used_total}"
          + (f", caller model {caller_llm.used_total}" if caller_llm is not setup_llm else ""))
