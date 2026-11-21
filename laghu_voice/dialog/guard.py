"""Guardrails on what the agent says (design doc: Dialog layer, guardrails).

`check_answer` judges a reply the LLM wrote (only off-script questions get one). It fails, and the fixed
fallback line is said instead, when the reply:
- states a number that isn't in the call's facts (amounts, rate, instalment, tenure from the backend's
  answer or the caller's own slots). "एक" alone is allowed: it is also the article "a";
- promises something (गारंटी, पक्का, वादा...);
- has English letters (Laghu drops them), starts with नमस्ते, or speaks in the feminine first person;
- is empty. More than two sentences are cut to two.

`check_answer` runs on every sentence the LLM writes, before Laghu says it. `check_spoken` is the last check
on everything the agent says, LLM or not: no passcode, no नमस्ते, no English letters. A failure there is a
bug in a spec or the engine; the evaluation counts it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .hindi import digits_words, norm, number_values
from .spec import FEMININE_RE, LATIN_RE

PROMISES = [norm(w) for w in ["गारंटी", "पक्का", "वादा", "निश्चित रूप से", "ज़रूर मिलेगा", "जरूर मिलेगा",
                              "मंज़ूर हो जाएगा", "अप्रूव हो जाएगा", "सौ प्रतिशत"]]
ALWAYS_ALLOWED = {1.0}
DIGIT_RE = re.compile(r"[0-9\u0966-\u096F₹$%]")
SENTENCE_RE = re.compile(r"[^।?!.]+[।?!.]?")


@dataclass
class GuardResult:
    ok: bool
    text: str
    reasons: list[str] = field(default_factory=list)


def check_answer(text: str, allowed_numbers: set[float]) -> GuardResult:
    t = " ".join((text or "").split())
    sentences = [s.strip() for s in SENTENCE_RE.findall(t) if s.strip()]
    t = " ".join(sentences[:2])
    reasons = []
    if not t:
        reasons.append("empty")
    if LATIN_RE.search(t):
        reasons.append("english_letters")
    if DIGIT_RE.search(t):
        reasons.append("digits")             # "₹१,५००": numbers must be words, in any script
    if norm(t).startswith(norm("नमस्ते")) or norm("नमस्ते") in norm(t):
        reasons.append("namaste")
    if FEMININE_RE.search(t):
        reasons.append("feminine")
    n = norm(t)
    for p in PROMISES:
        if p in n:
            reasons.append(f"promise:{p}")
    allowed = {round(float(v), 2) for v in allowed_numbers} | ALWAYS_ALLOWED
    for v in sorted(number_values(t)):
        if round(v, 2) not in allowed:
            reasons.append(f"number:{v:g}")
    return GuardResult(not reasons, t, reasons)


_REQUEST = re.compile(r"(?:इए|िए|िये|इये|ाएँ|ाएं|ें)(?=[\s।.!?,]|$)")
_APOLOGY = re.compile(r"माफ़? कीजिए|माफ़? करें|माफ़? करना")


def asks_question(text: str) -> bool:
    """Does the text ask the caller for something: a question mark, or a polite request ("बताइए", "बोलिए",
    "दीजिए", "बताएँ")?"""
    text = _APOLOGY.sub("", text)                      # "माफ़ कीजिए" (sorry) asks for nothing
    return "?" in text or bool(_REQUEST.search(text)) or "कृपया" in text


def check_spoken(text: str, secrets=None) -> list[str]:
    """The last check on everything the agent says. A failure here is a bug in a spec or the engine."""
    problems = []
    if LATIN_RE.search(text):
        problems.append("english_letters")
    if norm(text).startswith(norm("नमस्ते")):
        problems.append("namaste")
    if secrets is not None:
        for o in secrets.otps:
            if o in text or norm(digits_words(o)) in norm(text):
                problems.append("passcode_spoken")
    return problems
