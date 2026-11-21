"""Slot types: the kinds of value an agent can ask a caller for. A spec declares its slots by type; the engine
knows nothing else about them.

Each type says how to read a value from a Hindi transcript with fixed rules (hindi.py), what problems a reading
can have (each can have its own re-ask line in the spec), whether the LLM may read it (never for private
types), how to send it to a tool, and how to say it back.

    type       value             private  read by          problems
    yes_no     (not a slot; a state's `expect: yes_no`)
    name       English letters   no       LLM only         -
    date       datetime.date     yes      rules            year_ambiguous, invalid
    pan        "ABCDE1234F"      yes      rules            partial
    digits     "482913"          yes      rules            partial
    money      int rupees        no       rules, then LLM  out_of_range, unclear, range
    duration   int (months|days) no       rules, then LLM  out_of_range, range
    (formats for lines: words, rate, tenure, digits, date, spell, iso, days, hi = a name in Devanagari,
     label = a choice's label)
    choice     one option key    no       rules, then LLM  ambiguous (two options named)
    email      address           no       rules, then LLM  -
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from . import hindi

TYPES = {"name", "date", "pan", "digits", "money", "duration", "choice", "email"}
PRIVATE_TYPES = {"date", "pan", "digits"}


@dataclass
class Parsed:
    value: Any = None
    problem: str | None = None          # a re-ask key, or None
    extra: dict = field(default_factory=dict)   # e.g. a name's Devanagari spelling


@dataclass
class Slot:
    name: str
    type: str
    min: float | None = None
    max: float | None = None
    unit: str | None = None              # duration: months or days; money: per month or not
    length: int | None = None            # digits
    options: dict[str, list[str]] = field(default_factory=dict)    # choice: key -> phrases
    labels: dict[str, str] = field(default_factory=dict)            # choice: key -> how to say it ({x:label})
    min_age: int | None = None           # date of birth
    describe: str = ""                   # for the LLM: what this slot is
    reask: dict[str, str] = field(default_factory=dict)   # problem -> line key

    @property
    def private(self) -> bool:
        return self.type in PRIVATE_TYPES

    # ------------------------------------------------------------------ reading
    def parse(self, text: str, today: date, strict_unit: bool = False) -> Parsed:
        """Rules only. strict_unit: the caller wasn't asked for this slot (they said it along with another
        answer), so only a reading with its unit counts ("तीन साल", not a bare "तीन")."""
        t = self.type
        if t == "date":
            r = hindi.find_dob(text, today)
            if r.value and self.min_age is not None:
                limit = date(today.year - self.min_age, today.month, min(today.day, 28))
                if r.value > limit:
                    return Parsed(None, "invalid")
            return Parsed(r.value, None if r.value else (r.problem if r.problem != "not_found" else None))
        if t == "pan":
            p = hindi.find_pan(text)
            if p:
                return Parsed(p)
            n = sum(1 for tok in hindi.tokens(text) if tok in hindi.LETTER_WORDS or tok in hindi.NUMBER_WORDS)
            return Parsed(None, "partial" if n >= 3 else None)
        if t == "digits":
            d = hindi.digit_string(text)
            if d and len(d) == (self.length or len(d)):
                return Parsed(d)
            return Parsed(None, "partial" if d else None)
        if t in ("money", "duration") and hindi.has_range(text):
            return Parsed(None, "range")                  # "एक या दो हफ़्ते": ask for one, don't pick
        if t == "money":
            v = hindi.find_income(text) if self.unit == "month" else hindi.find_amount(text)
            if v is None:
                small = [q for q in hindi.quantities(text) if q.unit in (None, "rupees")]
                return Parsed(None, "unclear" if small and not strict_unit else None)
            return self._range(v)
        if t == "duration":
            v = (hindi.find_days(text, unitless_ok=not strict_unit) if self.unit == "days"
                 else hindi.find_tenure_months(text, unitless_ok=not strict_unit))
            return Parsed(None) if v is None else self._range(v)
        if t == "choice":
            found = self.choices_in(text)
            if len(found) == 1:
                return Parsed(found[0])
            return Parsed(None, "ambiguous" if found else None)    # two options named: ask, don't pick
        if t == "email":
            return Parsed(hindi.find_email(text))
        return Parsed(None)                                  # name: the LLM reads it

    def choices_in(self, text: str) -> list[str]:
        """The options the text names. A phrase inside a longer matched phrase doesn't count ("महीने" inside
        "तीन महीने"), so the longer, more specific option wins."""
        toks = hindi.tokens(text)
        spans = []
        for key, phrases in self.options.items():
            for ph in hindi._phrases("|".join(phrases)):
                for i in range(len(toks)):
                    end = _match_loose(toks, i, ph)
                    if end is not None:
                        spans.append((i, end, key))
        kept = [s for s in spans if not any(o[0] <= s[0] and s[1] <= o[1] and (o[1] - o[0]) > (s[1] - s[0])
                                            for o in spans)]
        return list(dict.fromkeys(k for _, _, k in sorted(kept)))

    def _range(self, v: float) -> Parsed:
        if (self.min is not None and v < self.min) or (self.max is not None and v > self.max):
            return Parsed(None, "out_of_range", {"heard": v})
        return Parsed(int(v))

    def from_llm(self, fields: dict) -> Parsed:
        """A value the LLM read (never for private types)."""
        v = fields.get(self.name)
        if v is None or self.private:
            return Parsed(None)
        t = self.type
        if t == "name":
            if isinstance(v, str) and hindi.re.fullmatch(r"[A-Za-z][A-Za-z .'-]{1,118}", v.strip()):
                hi = fields.get(f"{self.name}_hi")
                return Parsed(" ".join(v.split()), extra={"hi": hi if isinstance(hi, str) else None})
            return Parsed(None)
        if t in ("money", "duration"):
            if isinstance(v, str) and v.strip().isdigit():
                v = int(v)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
                return self._range(v)
            return Parsed(None)
        if t == "choice":
            if v == "several":                        # "वज़न भी कम करना है और मसल भी": ask which one
                return Parsed(None, problem="ambiguous")
            return Parsed(v if v in self.options else None)
        if t == "email":
            v = str(v).strip().lower()
            return Parsed(v if hindi.EMAIL_RE.match(v) else None)
        return Parsed(None)

    def llm_schema(self) -> dict | None:
        """The JSON field(s) the LLM may fill for this slot; None for private slots."""
        if self.private:
            return None
        t = self.type
        if t == "name":
            return {self.name: {"type": ["string", "null"]}, f"{self.name}_hi": {"type": ["string", "null"]}}
        if t in ("money", "duration"):
            return {self.name: {"type": ["integer", "null"]}}
        if t == "choice":
            return {self.name: {"type": ["string", "null"], "enum": list(self.options) + ["several", None]}}
        return {self.name: {"type": ["string", "null"]}}

    def llm_help(self) -> str:
        t = self.type
        base = self.describe or self.name
        if t == "name":
            return (f"{self.name}: {base}, in English letters, e.g. \"Rajesh Kumar\" (no titles; a first name "
                    f"alone is fine, e.g. \"Abhay\"); {self.name}_hi: the same name as written in the caller's words. "
                    f"If the intent is answer, fill both")
        if t == "money":
            return f"{self.name}: {base}, whole rupees (तीन लाख = 300000)"
        if t == "duration":
            return f"{self.name}: {base}, whole {self.unit or 'months'} (तीन साल = 36 months)"
        if t == "choice":
            return (f"{self.name}: {base}, one of {', '.join(self.options)}; \"several\" if the caller wants two or "
                    f"more of them (don't pick one for them)")
        if t == "email":
            return f"{self.name}: {base}, lowercase English (एट = @, डॉट = .)"
        return f"{self.name}: {base}"

    # ------------------------------------------------------------------ writing
    @staticmethod
    def payload(value: Any) -> Any:
        return value.isoformat() if isinstance(value, date) else value


def _match_loose(toks: list[str], i: int, phrase: tuple[str, ...]) -> int | None:
    """Does `phrase` start at toks[i], allowing one extra word between its words ("वज़न भी कम" for "वज़न कम")?
    Returns the end index, or None."""
    if not phrase or toks[i] != phrase[0]:
        return None
    j = i + 1
    for word in phrase[1:]:
        if j < len(toks) and toks[j] == word:
            j += 1
        elif j + 1 < len(toks) and toks[j + 1] == word:
            j += 2
        else:
            return None
    return j


def secrets_of(slots: dict[str, Slot], values: dict, extra: dict[str, set] | None = None) -> hindi.Secrets:
    """The private values a call holds now: private slots' values (all ever heard), plus private tool data."""
    s = hindi.Secrets(set(), set(), set())
    for name, vals in values.items():
        sl = slots.get(name)
        if sl is None:
            continue
        for v in vals:
            {"pan": s.pans, "digits": s.otps, "date": s.dobs}.get(sl.type, set()).add(v)
    for kind, vals in (extra or {}).items():
        {"pan": s.pans, "digits": s.otps, "date": s.dobs}[kind].update(vals)
    return s


def fmt(value: Any, how: str) -> str:
    """How a value is said: {amount:words}, {dob:date}, {pan:spell}, {phone_last4:digits}..."""
    if value is None or value == "":
        return ""
    if how == "words":
        return hindi.num_words(int(value))
    if how == "rate":
        return hindi.rate_words(float(value))
    if how == "tenure":
        return hindi.tenure_words(int(value))
    if how == "digits":
        return hindi.digits_words(str(value))
    if how == "date":
        return hindi.date_words(value if isinstance(value, date) else date.fromisoformat(str(value)))
    if how == "spell":
        v = str(value)
        return hindi.spell_email(v) if "@" in v else hindi.spell_pan(v)
    if how == "iso":
        return value.isoformat() if isinstance(value, date) else str(value)
    if how == "days":
        n = int(value)
        return {0: "आज", 1: "कल", 2: "परसों"}.get(n, f"{hindi.num_words(n)} दिन बाद")
    raise ValueError(f"unknown format {how!r}")


FORMATS = {"words", "rate", "tenure", "digits", "date", "spell", "iso", "days", "hi", "label"}
