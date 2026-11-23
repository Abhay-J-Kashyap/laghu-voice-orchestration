"""Deterministic Hindi understanding for the values a loan call needs (design doc: Dialog layer, validate).

IndicConformer writes what the caller said in Devanagari, with numbers as words: "तीन लाख", "बारह अप्रैल
उन्नीस सौ अठासी", "ए बी सी डी ई एक दो तीन चार एफ़". The values the backend needs (PAN, passcode, date of
birth, amounts, tenure) are read here with fixed rules, never by the LLM, for two reasons:

1. They are exact. A model that "corrects" one digit of a PAN costs the caller a verification attempt.
2. They are private. PAN, passcode and date of birth never go to Groq: `mask_for_llm` replaces them first.

Everything here works on normalised text: nukta and chandrabindu dropped ("हज़ार" == "हजार", "पाँच" ==
"पांच"), Devanagari digits turned into ASCII, punctuation turned into spaces. The other direction
(`num_words`, `date_words`, `spell_pan`...) writes numbers as Hindi words for the agent to say, so nothing
depends on how Laghu's frontend reads digits.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

# ---------------------------------------------------------------------------------------------- normalising

_NUKTA = "़"
_DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_PUNCT_RE = re.compile(r"[।॥,.?!;:\"'()\[\]{}\-\u2010\u2011\u2012–—/\\|*_~`]+")   # any hyphen splits words


BREAK = "§"                     # a pause the writer marked (comma, danda...), kept only for reading numbers


def norm(text: str, keep_breaks: bool = False) -> str:
    """Normalised form used for every comparison (not for display)."""
    s = unicodedata.normalize("NFD", text)
    s = s.replace(_NUKTA, "").replace("ँ", "ं")      # nukta gone, chandrabindu -> anusvara
    s = unicodedata.normalize("NFC", s).translate(_DEV_DIGITS).lower()
    s = re.sub(r"(?<=\d),(?=\d)", "", s)                         # 3,00,000 -> 300000
    s = re.sub(r"(?<=\d)\.(?=\d)", "#", s)                       # keep decimal points through the next line
    if keep_breaks:
        s = re.sub(r"[,।॥?!;]", f" {BREAK} ", s)
    s = _PUNCT_RE.sub(" ", s).replace("#", ".")
    return " ".join(s.split())


def tokens(text: str, keep_breaks: bool = False) -> list[str]:
    return norm(text, keep_breaks).split()


# ---------------------------------------------------------------------------------------------- number words

# Canonical spelling first (used when speaking), then spellings IndicConformer may write instead.
_HINDI_0_99 = """
0 शून्य ज़ीरो जीरो
1 एक
2 दो
3 तीन
4 चार
5 पाँच पांच
6 छह छः छै छे
7 सात
8 आठ
9 नौ
10 दस
11 ग्यारह
12 बारह
13 तेरह
14 चौदह
15 पंद्रह पन्द्रह
16 सोलह
17 सत्रह
18 अठारह
19 उन्नीस
20 बीस
21 इक्कीस
22 बाईस
23 तेईस
24 चौबीस
25 पच्चीस
26 छब्बीस
27 सत्ताईस
28 अट्ठाईस अठाईस
29 उनतीस उन्तीस
30 तीस
31 इकतीस इकत्तीस
32 बत्तीस
33 तैंतीस तेंतीस
34 चौंतीस चौतीस
35 पैंतीस पेंतीस
36 छत्तीस
37 सैंतीस सेंतीस
38 अड़तीस
39 उनतालीस उन्तालीस
40 चालीस
41 इकतालीस
42 बयालीस ब्यालीस
43 तैंतालीस तेंतालीस
44 चवालीस चौवालीस
45 पैंतालीस पेंतालीस
46 छियालीस छयालीस
47 सैंतालीस सेंतालीस
48 अड़तालीस
49 उनचास उन्चास
50 पचास
51 इक्यावन इक्कावन
52 बावन
53 तिरपन तिरेपन
54 चौवन चव्वन
55 पचपन
56 छप्पन
57 सत्तावन
58 अट्ठावन अठावन
59 उनसठ उन्सठ
60 साठ
61 इकसठ
62 बासठ
63 तिरसठ
64 चौंसठ चौसठ
65 पैंसठ पेंसठ
66 छियासठ
67 सड़सठ सरसठ
68 अड़सठ
69 उनहत्तर
70 सत्तर
71 इकहत्तर इकत्तर
72 बहत्तर
73 तिहत्तर
74 चौहत्तर
75 पचहत्तर पचत्तर
76 छिहत्तर छियत्तर
77 सतहत्तर सतत्तर
78 अठहत्तर अठत्तर
79 उन्यासी उनासी
80 अस्सी
81 इक्यासी
82 बयासी ब्यासी
83 तिरासी
84 चौरासी
85 पचासी
86 छियासी
87 सत्तासी
88 अट्ठासी अठासी
89 नवासी
90 नब्बे
91 इक्यानवे इक्यानबे
92 बानवे बानबे
93 तिरानवे तिरानबे
94 चौरानवे चौरानबे
95 पचानवे पंचानवे पचानबे
96 छियानवे छियानबे
97 सत्तानवे सत्तानबे
98 अट्ठानवे अट्ठानबे अठानवे
99 निन्यानवे निन्यानबे
"""
# English number words as IndicConformer writes them. "एट" (eight) is also "at" in an email address; the
# email reader handles that itself.
_ENGLISH = """
1 वन
2 टू
3 थ्री
4 फोर
5 फाइव
6 सिक्स
7 सेवन
8 एट ऐट
9 नाइन
10 टेन
11 इलेवन
12 ट्वेल्व
13 थर्टीन
14 फोर्टीन
15 फिफ्टीन
16 सिक्सटीन
17 सेवनटीन
18 एटीन
19 नाइनटीन
20 ट्वेंटी ट्वेन्टी
30 थर्टी
40 फोर्टी
50 फिफ्टी
60 सिक्सटी
70 सेवनटी
80 एटी
90 नाइनटी
"""


def _table(block: str) -> tuple[dict[str, int], dict[int, str]]:
    words, canon = {}, {}
    for line in block.strip().splitlines():
        n, *ws = line.split()
        canon.setdefault(int(n), ws[0])
        for w in ws:
            words[norm(w)] = int(n)
            # speech recognition sometimes drops the nasal mark: "पाच" for "पाँच", "चौतीस" for "चौंतीस"
            words.setdefault(norm(w).replace("\u0902", ""), int(n))
    return words, canon


HINDI_WORDS, HINDI_CANON = _table(_HINDI_0_99)
ENGLISH_WORDS, _ = _table(_ENGLISH)
ENGLISH_TENS = {norm(w) for w, v in ENGLISH_WORDS.items() if v >= 20}
NUMBER_WORDS = {**ENGLISH_WORDS, **HINDI_WORDS}

MULTIPLIERS = {norm(w): v for w, v in [("सौ", 100), ("सो", 100), ("हंड्रेड", 100), ("हज़ार", 1000),
                                       ("हजार", 1000), ("थाउज़ेंड", 1000), ("थाउजेंड", 1000), ("लाख", 100_000),
                                       ("लाखों", 100_000), ("लैख", 100_000), ("करोड़", 10_000_000)]}
FRACTION_VALUES = {norm("डेढ़"): 1.5, norm("ढाई"): 2.5}
FRACTION_PREFIX = {norm("साढ़े"): 0.5, norm("साढे"): 0.5, norm("सवा"): 0.25, norm("पौने"): -0.25}
REPEATERS = {norm("डबल"): 2, norm("ट्रिपल"): 3}
DECIMAL = {norm("दशमलव"), norm("पॉइंट"), norm("प्वाइंट")}
_CONNECTORS = {norm("और"), norm("एंड")}

UNITS = {}
for _u, _ws in {"rupees": "रुपये रुपए रुपया रूपए रूपये रुपयों रु", "months": "महीने महीना महीनों मंथ मंथ्स माह",
                "years": "साल सालों वर्ष वर्षों बरस ईयर ईयर्स", "percent": "प्रतिशत परसेंट",
                "days": "दिन दिनों डेज़ डेज", "weeks": "हफ़्ते हफ़्ता हफ़्तों सप्ताह वीक वीक्स"}.items():
    for _w in _ws.split():
        UNITS[norm(_w)] = _u


def _is_numeric(tok: str) -> bool:
    return bool(re.fullmatch(r"\d+(\.\d+)?", tok))


def _is_number_token(tok: str) -> bool:
    return (tok in NUMBER_WORDS or tok in MULTIPLIERS or tok in FRACTION_VALUES or tok in FRACTION_PREFIX
            or _is_numeric(tok) or tok in DECIMAL)


@dataclass
class Quantity:
    value: float
    start: int          # token index
    end: int            # exclusive
    unit: str | None    # rupees, months, years, percent, or None

    @property
    def as_int(self) -> int:
        return int(round(self.value))


def _value(tok: str) -> float:
    if tok in FRACTION_VALUES:
        return FRACTION_VALUES[tok]
    if _is_numeric(tok):
        return float(tok)
    return float(NUMBER_WORDS[tok])


def _combine(run: list[str]) -> list[float]:
    """Value(s) of a run of number tokens. Two small numbers side by side ("बारह चार", or "उन्नीस अठासी")
    are separate numbers; an English tens word followed by a unit ("ट्वेंटी वन") is one; "उन्नीस सौ अठासी"
    is 1988 and "साढ़े तीन लाख" is 350000."""
    out: list[float] = []
    total = cur = prefix = 0.0
    have = prev_tens = False

    def flush() -> None:
        nonlocal total, cur, have
        if have:
            out.append(total + cur)
        total = cur = 0.0
        have = False

    for tok in run:
        if tok in FRACTION_PREFIX:
            if have and cur and not total:
                flush()
            prefix += FRACTION_PREFIX[tok]
            continue
        if tok in MULTIPLIERS:
            m = MULTIPLIERS[tok]
            base = (cur or 1.0) + prefix
            prefix = 0.0
            if m == 100:
                cur = base * 100
            else:
                total += base * m
                cur = 0.0
            have, prev_tens = True, False
            continue
        v = _value(tok) + prefix
        prefix = 0.0
        if have:
            if 0 < cur < 100:
                if prev_tens and v < 10 and cur % 10 == 0:
                    cur += v                                 # ट्वेंटी वन = 21
                    prev_tens = False
                    continue
                flush()                                      # two separate numbers
            elif cur >= 100 and cur % 100 == 0 and v < 100:
                cur += v                                     # उन्नीस सौ + अठासी
                prev_tens = tok in ENGLISH_TENS
                continue
            elif cur >= 100 or (total and v >= 1000):
                flush()
        cur = v
        have = True
        prev_tens = tok in ENGLISH_TENS
    flush()
    return out


def quantities(text: str) -> list[Quantity]:
    """Every number in the text, in order, with the unit word that follows it (if any). Token positions are
    those of tokens(text, keep_breaks=True)."""
    toks = tokens(text, keep_breaks=True)
    out: list[Quantity] = []
    i = 0
    while i < len(toks):
        if not _is_number_token(toks[i]) or toks[i] in REPEATERS:
            i += 1
            continue
        j = i
        while j < len(toks) and (_is_number_token(toks[j]) or (toks[j] in _CONNECTORS and j + 1 < len(toks)
                                                                and _is_number_token(toks[j + 1]))):
            j += 1
        run = [t for t in toks[i:j] if t not in _CONNECTORS]
        unit = UNITS.get(toks[j]) if j < len(toks) else None
        tail: list[str] = []
        if unit in ("years", "months"):
            # "पंद्रह लाख तीन साल": speech recognition writes no comma, but the three is the tenure
            big = [k for k, t in enumerate(run) if t in MULTIPLIERS and MULTIPLIERS[t] >= 1000]
            if big and big[-1] < len(run) - 1:
                run, tail = run[:big[-1] + 1], run[big[-1] + 1:]
        dec = [k for k, t in enumerate(run) if t in DECIMAL]
        if dec and 0 < dec[0] < len(run) - 1 and all(NUMBER_WORDS.get(t, 99) < 10 for t in run[dec[0] + 1:]):
            # "दस दशमलव नौ नौ" = 10.99
            left = _combine(run[:dec[0]])
            frac = "".join(str(NUMBER_WORDS[t]) for t in run[dec[0] + 1:])
            values = left[:-1] + [left[-1] + float("0." + frac)]
        else:
            values = _combine([t for t in run if t not in DECIMAL])
        for k, v in enumerate(values):
            out.append(Quantity(v, i, j, unit if k == len(values) - 1 and not tail else None))
        for k, v in enumerate(_combine(tail) if tail else []):
            out.append(Quantity(v, i, j, unit))
        i = j
    return out


def _number_runs(toks: list[str], i: int) -> int:
    """End (exclusive) of a number said with सौ/हज़ार starting at i ("पाँच सौ बारह"), or i if there is none."""
    j = i
    while j + 1 < len(toks) and toks[j + 1] in MULTIPLIERS and MULTIPLIERS[toks[j + 1]] <= 1000:
        j += 1
        if j + 1 < len(toks) and toks[j + 1] in NUMBER_WORDS:
            j += 1
    return j + 1 if j > i else i


def _token_digits(toks: list[str], i: int) -> tuple[str, int]:
    """Digits said by the token(s) at i, and the index after them; ("", i + 1) if they aren't digits."""
    t = toks[i]
    if t in REPEATERS and i + 1 < len(toks) and toks[i + 1] in NUMBER_WORDS and NUMBER_WORDS[toks[i + 1]] < 10:
        return str(NUMBER_WORDS[toks[i + 1]]) * REPEATERS[t], i + 2
    if _is_numeric(t) and "." not in t:
        return t, i + 1
    if t in NUMBER_WORDS:
        j = _number_runs(toks, i)
        if j > i:
            return str(int(_combine(toks[i:j])[0])), j
        v = NUMBER_WORDS[t]
        if t in ENGLISH_TENS and i + 1 < len(toks) and ENGLISH_WORDS.get(toks[i + 1], 99) < 10:
            return str(v + ENGLISH_WORDS[toks[i + 1]]), i + 2
        return str(v), i + 1
    return "", i + 1


def digit_string(text: str) -> str:
    """All digits said in the text, in order, as a string: for passcodes. Words for 10-99 give two digits
    ("बारह चौंतीस" -> "1234"); "डबल पाँच" gives "55"; "पाँच सौ बारह" gives "512"."""
    toks = tokens(text)
    out: list[str] = []
    i = 0
    while i < len(toks):
        d, i = _token_digits(toks, i)
        out.append(d)
    return "".join(out)


# ---------------------------------------------------------------------------------------------- letters, PAN

LETTER_NAMES = {
    "A": "ए", "B": "बी", "C": "सी", "D": "डी", "E": "ई", "F": "एफ़", "G": "जी", "H": "एच", "I": "आई",
    "J": "जे", "K": "के", "L": "एल", "M": "एम", "N": "एन", "O": "ओ", "P": "पी", "Q": "क्यू", "R": "आर",
    "S": "एस", "T": "टी", "U": "यू", "V": "वी", "W": "डब्ल्यू", "X": "एक्स", "Y": "वाई", "Z": "ज़ेड",
}
_LETTER_VARIANTS = {
    "A": "ऐ", "E": "इ", "F": "एफ्", "H": "एड्च एज", "J": "जय", "K": "क", "M": "ऐम", "N": "ऐन", "Q": "क्यु क्यूं",
    "R": "आरु", "S": "ऐस", "U": "यु", "V": "व्ही", "W": "डब्लू डबल्यू डब्ल्यु", "X": "ऐक्स", "Y": "वाय",
    "Z": "जेड ज़ैड ज़ी",
}
LETTER_WORDS: dict[str, str] = {}
for _l, _w in LETTER_NAMES.items():
    LETTER_WORDS[norm(_w)] = _l
for _l, _ws in _LETTER_VARIANTS.items():
    for _w in _ws.split():
        LETTER_WORDS.setdefault(norm(_w), _l)
_LETTER_RUN_RE = re.compile("(?:" + "|".join(sorted(map(re.escape, LETTER_WORDS), key=len, reverse=True)) + ")+")
_LETTER_SPLIT_RE = re.compile("|".join(sorted(map(re.escape, LETTER_WORDS), key=len, reverse=True)))
_PAN_SKIP = {norm(w) for w in ["और", "फिर", "उसके", "बाद", "है", "एंड", "लास्ट", "में", "आखिर"]}
_FOR = {norm("फॉर"), norm("फ़ॉर"), norm("फोर")}
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")


def _letters(tok: str) -> str | None:
    if tok in LETTER_WORDS:
        return LETTER_WORDS[tok]
    if _LETTER_RUN_RE.fullmatch(tok):                     # "एबीसीडीई" written as one word
        return "".join(LETTER_WORDS[m] for m in _LETTER_SPLIT_RE.findall(tok))
    return None


def _pan_items(toks: list[str]) -> list[list[str] | None]:
    """Per spoken unit, what it can stand for inside a PAN (letters or digits); None breaks a PAN."""
    items: list[list[str] | None] = []
    i = 0
    while i < len(toks):
        t = toks[i]
        if t == norm("डबल") and i + 1 < len(toks) and toks[i + 1] in (norm("यू"), norm("यु")):
            items.append(["W"])
            i += 2
            continue
        if t in REPEATERS and i + 1 < len(toks) and _letters(toks[i + 1]):
            items.append([_letters(toks[i + 1]) * REPEATERS[t]])
            i += 2
            continue
        if t in _FOR and items and items[-1] and items[-1][0].isalpha() and i + 1 < len(toks):
            i += 2                                         # "ए फॉर एप्पल": skip the example word
            continue
        c: list[str] = []
        letters = _letters(t)
        if letters:
            c.append(letters)
        if t == norm("ओ"):
            c.append("0")
        digits, j = _token_digits(toks, i) if t not in _FOR else ("", i + 1)
        if digits:
            c.append(digits)
        if not c and re.fullmatch(r"[a-z0-9]+", t):
            c.append(t.upper())
        if c:
            items.append(c)
            i = max(j, i + 1) if digits and not letters else i + 1
            continue
        if t not in _PAN_SKIP:
            items.append(None)
        i += 1
    return items


def find_pan(text: str) -> str | None:
    """The last PAN-shaped sequence of letters and digits in the text (a correction usually comes last)."""
    items = _pan_items(tokens(text))
    found: list[str] = []

    def go(k: int, acc: str) -> None:
        if len(acc) == 10:
            found.append(acc)
            return
        if k >= len(items) or items[k] is None:
            return
        for cand in items[k]:
            if _pan_prefix_ok(acc + cand):
                go(k + 1, acc + cand)

    for s in range(len(items)):
        if items[s] is not None:
            go(s, "")
    return found[-1] if found else None


def _pan_prefix_ok(p: str) -> bool:
    pattern = "AAAAA9999A"
    return len(p) <= 10 and all((ch.isalpha() if pattern[k] == "A" else ch.isdigit()) for k, ch in enumerate(p))


def spell_pan(pan: str) -> str:
    """ABCDE1234F -> "ए बी सी डी ई, एक दो तीन चार, एफ़" (for the agent to read back)."""
    letters = " ".join(LETTER_NAMES[c] for c in pan[:5])
    digits = " ".join(HINDI_CANON[int(c)] for c in pan[5:9])
    return f"{letters}, {digits}, {LETTER_NAMES[pan[9]]}"


# ---------------------------------------------------------------------------------------------- dates

MONTHS = ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर",
          "दिसंबर"]
_MONTH_VARIANTS = [
    "जनवरी जेनुअरी", "फ़रवरी फरवरी फेब्रुअरी", "मार्च", "अप्रैल अप्रेल एप्रिल", "मई मे", "जून",
    "जुलाई जुलाइ", "अगस्त ऑगस्ट", "सितंबर सितम्बर सेप्टेंबर", "अक्टूबर अक्तूबर ऑक्टोबर",
    "नवंबर नवम्बर नोवेंबर", "दिसंबर दिसम्बर डिसेंबर",
]
MONTH_WORDS = {norm(w): k + 1 for k, ws in enumerate(_MONTH_VARIANTS) for w in ws.split()}


@dataclass
class DateParse:
    value: date | None
    problem: str | None = None     # "year_ambiguous", "invalid", "not_found"


def find_dob(text: str, today: date | None = None) -> DateParse:
    """Date of birth from "बारह अप्रैल उन्नीस सौ अठासी", "बारह चार उन्नीस सौ अठासी" or "12 04 1988". A two-digit
    year is not guessed: the caller is asked for the full year."""
    today = today or date.today()
    toks = tokens(text, keep_breaks=True)
    qs = quantities(text)
    month_at = [i for i, t in enumerate(toks) if t in MONTH_WORDS]
    if month_at:
        mi = month_at[-1]
        m = MONTH_WORDS[toks[mi]]
        before = [q.as_int for q in qs if q.end <= mi]
        after = _year_pairs([q.as_int for q in qs if q.start > mi], first_year_at=0)
        if not before:
            return DateParse(None, "not_found")
        if not after:
            return DateParse(None, "year_ambiguous")
        d, y = before[-1], after[0]
    else:
        vals = _year_pairs([q.as_int for q in qs], first_year_at=2)
        if len(vals) < 3:
            return DateParse(None, "not_found")
        d, m, y = vals[-3], vals[-2], vals[-1]
    if y < 1000:
        return DateParse(None, "year_ambiguous")
    try:
        v = date(y, m, d)
    except ValueError:
        return DateParse(None, "invalid")
    if y < 1900 or v > date(today.year - 18, today.month, min(today.day, 28)):
        return DateParse(None, "invalid")
    return DateParse(v)


def _year_pairs(vals: list[int], first_year_at: int) -> list[int]:
    """[.., 19, 88] -> [.., 1988]: a year said as two numbers ("उन्नीस अठासी", "नाइनटीन एटी एट"). Only from
    position `first_year_at` on, so a day of 20 followed by a month isn't read as a year."""
    out: list[int] = []
    for v in vals:
        if out and out[-1] in (19, 20) and v < 100 and len(out) - 1 >= first_year_at:
            out.append(out.pop() * 100 + v)
        else:
            out.append(v)
    return out


def date_words(d: date) -> str:
    """date(1988, 4, 12) -> "बारह अप्रैल, उन्नीस सौ अठासी"."""
    y = d.year
    yw = f"{HINDI_CANON[y // 100]} सौ {HINDI_CANON[y % 100]}" if 1100 <= y < 2000 and y % 100 else num_words(y)
    return f"{HINDI_CANON[d.day]} {MONTHS[d.month - 1]}, {yw}"


# ---------------------------------------------------------------------------------------------- amounts, tenure

def find_amount(text: str, minimum: int = 1000) -> int | None:
    """The first sum of money in the text (a number not followed by months, years or percent, and not part of a
    date: "बारह अप्रैल उन्नीस सौ अठासी" is no amount)."""
    toks = tokens(text, keep_breaks=True)
    for q in quantities(text):
        near_month = (q.start > 0 and toks[q.start - 1] in MONTH_WORDS) or (q.end < len(toks) and toks[q.end] in MONTH_WORDS)
        if q.unit in (None, "rupees") and q.value >= minimum and not near_month:
            return q.as_int
    return None


_ANNUAL = {norm(w) for w in ["सालाना", "साल", "सालभर", "पैकेज", "सीटीसी", "वार्षिक", "ईयरली", "एनुअल"]}


def find_income(text: str) -> int | None:
    """Monthly income. "महीने के पचास हज़ार" and "पचास हज़ार महीना" are both monthly; an amount said per year
    ("साल के बारह लाख", "पैकेज बारह लाख") is divided by 12."""
    toks = tokens(text)
    for q in quantities(text):
        if q.unit in ("percent",) or q.value < 1000:
            continue
        if q.unit == "years" or any(t in _ANNUAL for t in toks):
            return int(round(q.value / 12))
        return q.as_int
    return None


def find_tenure_months(text: str, unitless_ok: bool = False) -> int | None:
    """Tenure in months: "तीन साल" -> 36, "डेढ़ साल" -> 18, "छत्तीस महीने" -> 36. With `unitless_ok` (the
    caller was just asked for the tenure) a bare number up to 10 is years and above 10 is months."""
    for q in quantities(text):
        if q.unit == "years":
            return int(round(q.value * 12))
        if q.unit == "months":
            return q.as_int
    if unitless_ok:
        qs = [q for q in quantities(text) if q.unit is None]
        if qs:
            v = qs[0].value
            return int(round(v * 12)) if v <= 10 else int(round(v))
    return None


_RELATIVE_DAYS = {norm("आज"): 0, norm("कल"): 1, norm("परसों"): 2, norm("नरसों"): 3}


def find_days(text: str, unitless_ok: bool = False) -> int | None:
    """A number of days from now: "तीन दिन में" -> 3, "एक हफ़्ते में" -> 7, "कल" -> 1, "परसों" -> 2."""
    for q in quantities(text):
        if q.unit == "days":
            return q.as_int
        if q.unit == "weeks":
            return int(round(q.value * 7))
    toks = tokens(text)
    if norm("हफ़्ते") in toks or norm("हफ़्ता") in toks:      # "हफ़्ते भर में", "अगले हफ़्ते"
        return 7
    for t in toks:
        if t in _RELATIVE_DAYS:
            return _RELATIVE_DAYS[t]
    if unitless_ok:
        qs = [q for q in quantities(text) if q.unit is None]
        if qs:
            return qs[0].as_int
    return None


WEEKDAYS = ["सोमवार", "मंगलवार", "बुधवार", "गुरुवार", "शुक्रवार", "शनिवार", "रविवार"]
_WEEKDAY_VARIANTS = ["सोमवार मंडे", "मंगलवार ट्यूसडे", "बुधवार वेडनेसडे", "गुरुवार वीरवार बृहस्पतिवार थर्सडे",
                     "शुक्रवार फ्राइडे", "शनिवार सैटरडे", "रविवार इतवार संडे"]
WEEKDAY_WORDS = {norm(w): k for k, ws in enumerate(_WEEKDAY_VARIANTS) for w in ws.split()}
_DATE_WORDS = {norm("तारीख"), norm("तारीक"), norm("डेट")}


def day_ahead(text: str, today: date) -> tuple[int | None, bool]:
    """(days from today, whether the text names a day at all) for an appointment or a callback: "कल" -> 1,
    "शनिवार" -> the coming Saturday, "पाँच दिसंबर" -> 5 December (next year if it has passed), "दस तारीख" -> the
    10th (next month if it has passed), "तीन दिन बाद" -> 3. A day named but not understood gives (None, True), so
    the caller is never booked for today by mistake."""
    toks = tokens(text)
    named = any(t in WEEKDAY_WORDS or t in MONTH_WORDS or t in _DATE_WORDS or t in _RELATIVE_DAYS for t in toks)
    for t in toks:
        if t in _RELATIVE_DAYS:
            return _RELATIVE_DAYS[t], True
    qs = quantities(text)
    weekday = next((WEEKDAY_WORDS[t] for t in toks if t in WEEKDAY_WORDS), None)
    for i, t in enumerate(toks):
        if t in MONTH_WORDS or t in _DATE_WORDS:
            before = [q for q in qs if q.end == i or q.end == i - 1]
            when = None
            if before and float(before[-1].value).is_integer():
                d = before[-1].as_int
                try:
                    if t in MONTH_WORDS:
                        when = date(today.year, MONTH_WORDS[t], d)
                        if when < today and (today - when).days <= 31:
                            when = None              # "शनिवार बीस नवंबर" two days after it: a slip, not next year
                        elif when < today:
                            when = date(today.year + 1, MONTH_WORDS[t], d)
                    else:
                        when = date(today.year, today.month, d)
                        if when < today:
                            y, m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
                            when = date(y, m, d)
                except ValueError:
                    when = None                          # "सत्तर नवंबर": no such date
            if when is None:
                if weekday is None:
                    return None, True
                break                                    # the weekday alone ("शुक्रवार सत्तर नवंबर": Friday)
            if weekday is not None and when.weekday() != weekday:
                return None, True                        # "गुरुवार छह दिसंबर", a Sunday: not ours to pick
            return (when - today).days, True
    if weekday is not None:
        ahead = (weekday - today.weekday()) % 7
        return ahead or 7, True
    days = find_days(text, unitless_ok=False)
    return days, named or days is not None


_HOUR_WORDS = {norm("बजे"), norm("बज")}


def hour_part(text: str) -> str | None:
    """"दस बजे" -> morning, "दो बजे" -> afternoon, "पाँच बजे" -> evening: office hours, when no part is said."""
    toks = tokens(text)
    for q in quantities(text):
        if q.end < len(toks) and toks[q.end] in _HOUR_WORDS and float(q.value).is_integer():
            h = q.as_int
            if 8 <= h <= 11:
                return "morning"
            if h == 12 or 1 <= h <= 3:
                return "afternoon"
            if 4 <= h <= 7:
                return "evening"
    return None


_SCALE_EN = {"lakh": 100000, "lakhs": 100000, "lac": 100000, "lacs": 100000, "crore": 10 ** 7, "crores": 10 ** 7,
             "cr": 10 ** 7, "thousand": 1000, "k": 1000, "hundred": 100}
_EN_AMOUNT = re.compile(r"(\d+(?:\.\d+)?)\s*(lakhs?|lacs?|crores?|cr|thousand|k|hundred)\b", re.I)


def fact_numbers(text: str) -> set[float]:
    """Every number a fact lets the agent say, including English amounts the facts are written in: "8.5 lakh
    rupees" lets it say साढ़े आठ लाख (850000), not only 8.5."""
    out = set(number_values(text))
    for m in _EN_AMOUNT.finditer(text):
        out.add(round(float(m.group(1)) * _SCALE_EN[m.group(2).lower()], 2))
    return out


_RANGE_WORDS = {norm(w) for w in ["या", "से", "टू", "तो"]}


def has_range(text: str) -> bool:
    """Does the caller give a range or a choice of numbers ("एक या दो हफ़्ते", "तीन से पाँच लाख", "दो तीन लाख")
    instead of one number? Then the rules don't pick one."""
    toks = tokens(text)
    num = [t in NUMBER_WORDS or _is_numeric(t) or t in FRACTION_VALUES for t in toks]
    for i in range(len(toks) - 2):
        if num[i] and toks[i + 1] in _RANGE_WORDS and num[i + 2]:
            return True
    for i in range(len(toks) - 1):                        # "दो तीन", "चार पाँच": neighbours said together
        if num[i] and num[i + 1] and toks[i] in HINDI_WORDS and toks[i + 1] in HINDI_WORDS:
            a, b = HINDI_WORDS[toks[i]], HINDI_WORDS[toks[i + 1]]
            if 0 < a < 10 and b == a + 1:
                return True
    return False


def find_otp(text: str, length: int = 6) -> str | None:
    s = digit_string(text)
    return s if len(s) == length else None


# ---------------------------------------------------------------------------------------------- words

def _phrases(words: str) -> list[tuple[str, ...]]:
    return [tuple(norm(p).split()) for p in words.split("|")]


def _has(toks: list[str], phrases: list[tuple[str, ...]]) -> bool:
    for p in phrases:
        n = len(p)
        for i in range(len(toks) - n + 1):
            if tuple(toks[i:i + n]) == p:
                return True
    return False


YES = _phrases("हाँ|हां|हा|जी|जी हाँ|हाँ जी|ठीक है|ठीक|सही|सही है|बिल्कुल|बिलकुल|ज़रूर|जरूर|सहमत|ओके|ओके|यस|"
               "चलेगा|हम्म हाँ|बिल्कुल सही|एकदम सही|हाँ सही|मंज़ूर|मंजूर|एग्री|करिए|कीजिए|कर दीजिए")
NO = _phrases("नहीं|नही|ना|नो|मत|गलत|ग़लत|असहमत|नहीं जी|जी नहीं|नहीं चाहिए|मंज़ूर नहीं")
HUMAN = _phrases("इंसान|किसी इंसान|एजेंट|कस्टमर केयर|किसी से बात|असली इंसान|मैनेजर|सहयोगी से|"
                 "किसी व्यक्ति|ह्यूमन|रिप्रेजेंटेटिव|किसी और से बात|ऑफिसर से")
REPEAT = _phrases("फिर से बोलिए|फिर से बोलो|दोबारा बोलिए|दोबारा बोलो|क्या कहा|क्या बोला|सुनाई नहीं दिया|"
                  "फिर से बताइए|दोबारा बताइए|रिपीट|एक बार और|समझ नहीं आया|समझा नहीं")
RESEND = _phrases("कोड नहीं आया|कोड नहीं मिला|ओटीपी नहीं आया|ओटीपी नहीं मिला|नहीं आया|नहीं मिला|"
                  "दोबारा भेजिए|फिर से भेजिए|नया कोड|दोबारा भेजो|फिर से भेजो|रीसेंड")
STOP = _phrases("फोन रखिए|कॉल काटिए|बाद में बात|अभी नहीं|रहने दीजिए|रहने दो|इंटरेस्ट नहीं|ज़रूरत नहीं|"
                "जरूरत नहीं|बंद कीजिए")
EMP_SELF = _phrases("बिज़नेस|बिजनेस|अपना काम|अपना बिज़नेस|खुद का|ख़ुद का|दुकान|व्यापार|फ्रीलांस|फ्रीलांसर|"
                    "सेल्फ एम्प्लॉयड|सेल्फ|धंधा|प्रैक्टिस|कंसल्टेंट|कंसल्टेंसी|खेती|ठेकेदार|कॉन्ट्रैक्टर")
EMP_NONE = _phrases("बेरोज़गार|बेरोजगार|काम नहीं|नौकरी नहीं|जॉब नहीं|अनएम्प्लॉयड|कुछ नहीं करता|"
                    "कुछ नहीं करती|घर पर|स्टूडेंट|पढ़ाई|पढ़ाई करता|पढ़ाई करती")
EMP_SALARIED = _phrases("नौकरी|सैलरी|सैलरीड|जॉब|तनख्वाह|तनख़्वाह|कंपनी में|सरकारी|प्राइवेट|एम्प्लॉयड|सर्विस|"
                        "वेतन|ऑफिस|कर्मचारी")


def yes_no(text: str, max_tokens: int = 6) -> str | None:
    """"yes", "no", or None when unsure (long or mixed answers go to the LLM)."""
    toks = tokens(text)
    if not toks or len(toks) > max_tokens:
        return None
    if _has(toks, NO):
        return "no"
    if _has(toks, YES):
        return "yes"
    return None


_LEAD_YES = {norm(w) for w in ["हाँ", "हां", "हा", "जी", "बिल्कुल", "बिलकुल", "ज़रूर", "जरूर", "ठीक", "ओके"]}
_TAKES_BACK = {norm(w) for w in ["लेकिन", "मगर", "पर", "परंतु", "बाद", "कभी", "बिज़ी", "व्यस्त"]}


def leading_yes(text: str) -> bool:
    """Does a longer turn start with a yes and take nothing back ("जी हाँ मैं मनीष कुमार हूँ बोलिए", not "हाँ, लेकिन
    अभी नहीं" or "हाँ बाद में करना")?"""
    toks = tokens(text)
    return bool(toks) and toks[0] in _LEAD_YES and not _has(toks, NO) and not (set(toks) & _TAKES_BACK)


def employment(text: str) -> str | None:
    toks = tokens(text)
    if _has(toks, EMP_SELF):
        return "self_employed"
    if _has(toks, EMP_NONE):
        return "unemployed"
    if _has(toks, EMP_SALARIED):
        return "salaried"
    return None


HOLD = _phrases("एक सेकंड|एक सेकेंड|एक मिनट|एक पल|रुको|रुकिए|रुकना|ज़रा रुकिए|जरा रुकिए|होल्ड|वेट|एक मिनट रुकिए")


def keyword_intent(text: str, short: int = 8) -> str | None:
    """Requests that mean the same in every state: a human, a repeat, stopping, or "hold on". Repeat, stop and
    hold only count in a short utterance, so "हाँ, अभी नहीं पता" is not taken as stopping."""
    toks = tokens(text)
    if _has(toks, HUMAN):
        return "human"
    if len(toks) <= short and _has(toks, REPEAT):
        return "repeat"
    if len(toks) <= short and _has(toks, STOP):
        return "stop"
    if len(toks) <= 4 and _has(toks, HOLD):              # "एक सेकंड" alone: wait, don't re-ask
        return "hold"
    if _ends_with_hold(toks):                            # "हाँ, मैं लाइन पर हूँ, जस्ट पाँच सेकंड"
        return "hold"
    return None


_SECONDS = {norm(w) for w in ["सेकंड", "सेकेंड", "सेकण्ड", "सेकंड्स", "सेकेंड्स", "सेकंडस", "सैकंड"]}
_MINUTES = {norm(w) for w in ["मिनट", "मिनिट", "मिनट्स"]}
_JUST = {norm(w) for w in ["जस्ट", "जस्", "बस", "ज़रा", "जरा", "सिर्फ़", "सिर्फ", "बस्"]}


def _ends_with_hold(toks: list[str]) -> bool:
    """The utterance ends by asking for a few seconds: "<number> सेकंड", or "जस्ट/बस <number> मिनट". Only at
    the end ("एक सेकंड, पहले ये बताओ…" is a question), and minutes only after "just" ("हाँ, दो मिनट" answers
    "can we talk for two minutes?")."""
    tail = toks[-3:]
    for i, t in enumerate(tail):
        count = i > 0 and (tail[i - 1] in NUMBER_WORDS or tail[i - 1].isdigit())
        if t in _SECONDS and count:
            return True
        if t in _MINUTES and count and i > 1 and tail[i - 2] in _JUST:
            return True
    return False


def wants_resend(text: str) -> bool:
    return _has(tokens(text), RESEND)


# ---------------------------------------------------------------------------------------------- email

_EMAIL_WORDS = {norm(k): v for k, v in {
    "एट": "@", "ऐट": "@", "एट द रेट": "@", "डॉट": ".", "डोट": ".", "अंडरस्कोर": "_", "डैश": "-", "हाइफन": "-",
    "जीमेल": "gmail", "याहू": "yahoo", "आउटलुक": "outlook", "हॉटमेल": "hotmail", "रेडिफमेल": "rediffmail",
    "रेडिफ": "rediff", "कॉम": "com", "इन": "in", "को": "co", "नेट": "net", "ऑर्ग": "org",
    "एग्जांपल": "example", "एक्जाम्पल": "example", "एग्ज़ाम्पल": "example", "इग्ज़ाम्पल": "example",
    "एग्जाम्पल": "example", "एक्ज़ाम्पल": "example", "इग्जांपल": "example", "आईक्लाउड": "icloud",
}.items()}
EMAIL_RE = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9\-]+(\.[a-z0-9\-]+)+$")


def find_email(text: str) -> str | None:
    """An email address spelt out word by word ("ए बी एट जीमेल डॉट कॉम"). Returns None when any word can't
    be read this way (a name inside the address): the LLM reads those."""
    toks = tokens(text.replace("@", " एट "))
    for lead in (norm("मेरा"), norm("ईमेल"), norm("है"), norm("जी"), norm("आईडी")):
        while toks and toks[0] == lead:
            toks = toks[1:]
    while toks and toks[-1] in (norm("है"), norm("जी")):
        toks = toks[:-1]
    out = []
    for t in toks:
        if t in _EMAIL_WORDS:
            out.append(_EMAIL_WORDS[t])
        elif t in LETTER_WORDS:
            out.append(LETTER_WORDS[t].lower())
        elif t in NUMBER_WORDS and NUMBER_WORDS[t] < 10:
            out.append(str(NUMBER_WORDS[t]))
        elif re.fullmatch(r"[a-z0-9._\-]+", t):
            out.append(t)
        else:
            return None
    e = "".join(out)
    return e if EMAIL_RE.match(e) else None


_SAY_EMAIL = {"@": "एट", ".": "डॉट", "_": "अंडरस्कोर", "-": "डैश"}
_SAY_DOMAIN = {v: k for k, v in {"जीमेल": "gmail", "याहू": "yahoo", "आउटलुक": "outlook", "हॉटमेल": "hotmail",
                                  "कॉम": "com", "इन": "in", "नेट": "net", "ऑर्ग": "org", "को": "co",
                                  "एग्ज़ाम्पल": "example", "रेडिफ़मेल": "rediffmail", "आईक्लाउड": "icloud"}.items()}


def spell_email(email: str) -> str:
    """abhay.jk@gmail.com -> "ए बी एच ए वाई डॉट जे के एट जीमेल डॉट कॉम"."""
    local, _, domain = email.partition("@")
    out = [_spell_chars(local), "एट"]
    for k, part in enumerate(domain.split(".")):
        if k:
            out.append("डॉट")
        out.append(_SAY_DOMAIN.get(part) or _spell_chars(part))
    return " ".join(out)


def _spell_chars(s: str) -> str:
    words = []
    for ch in s:
        if ch.isalpha() and ch.upper() in LETTER_NAMES:
            words.append(LETTER_NAMES[ch.upper()])
        elif ch.isdigit():
            words.append(HINDI_CANON[int(ch)])
        elif ch in _SAY_EMAIL:
            words.append(_SAY_EMAIL[ch])
    return " ".join(words)


# ---------------------------------------------------------------------------------------------- speaking numbers

def num_words(n: int) -> str:
    """Indian grouping in words: 1250000 -> "बारह लाख पचास हज़ार"."""
    n = int(n)
    if n < 100:
        return HINDI_CANON[n]
    parts = []
    for size, word in ((10_000_000, "करोड़"), (100_000, "लाख"), (1000, "हज़ार"), (100, "सौ")):
        if n >= size:
            parts.append(f"{num_words(n // size)} {word}")
            n %= size
    if n:
        parts.append(HINDI_CANON[n])
    return " ".join(parts)


def rate_words(x: float) -> str:
    """11.5 -> "साढ़े ग्यारह", 1.5 -> "डेढ़", 11.25 -> "सवा ग्यारह", 11.75 -> "पौने बारह", 10.99 -> "दस दशमलव
    नौ नौ"."""
    x = round(float(x), 2)
    whole, frac = int(x), round(x - int(x), 2)
    if frac == 0:
        return num_words(whole)
    if frac == 0.5:
        return {1: "डेढ़", 2: "ढाई"}.get(whole, f"साढ़े {num_words(whole)}")
    if frac == 0.25 and whole >= 1:
        return f"सवा {num_words(whole)}"
    if frac == 0.75:
        return f"पौने {num_words(whole + 1)}"
    digits = f"{x:.2f}".split(".")[1].rstrip("0")
    return f"{num_words(whole)} दशमलव " + " ".join(HINDI_CANON[int(c)] for c in digits)


def digits_words(s: str) -> str:
    """"3210" -> "तीन दो एक शून्य" (one word per digit)."""
    return " ".join(HINDI_CANON[int(c)] for c in s if c.isdigit())


def tenure_words(months: int) -> str:
    if months % 12 == 0:
        return f"{num_words(months // 12)} साल"
    return f"{num_words(months)} महीने"


def number_values(text: str) -> set[float]:
    """Every number value said in a text (digits or words), for the guardrail on LLM-written replies."""
    vals = {round(q.value, 2) for q in quantities(text)}
    vals |= {float(x) for x in re.findall(r"\d+(?:\.\d+)?", norm(text))}
    return vals


# ---------------------------------------------------------------------------------------------- masking

MASK = "[…]"


def _sensitive_token(t: str) -> bool:
    return (t in NUMBER_WORDS or t in MULTIPLIERS or t in FRACTION_VALUES or t in FRACTION_PREFIX
            or _is_numeric(t) or t in LETTER_WORDS or t in MONTH_WORDS or t in REPEATERS
            or bool(re.fullmatch(r"[a-z0-9]{1,12}", t)) or bool(_LETTER_RUN_RE.fullmatch(t)))


def mask_for_llm(text: str, strict: bool, dates: bool = True) -> str:
    """Text safe to send to the LLM.

    strict (the caller was asked for a PAN, passcode or date of birth, or is confirming them): every number,
    letter name and month name is replaced by [...]. Otherwise a run of such words is replaced when it could
    be a PAN, a passcode or a date: it names a month, or it says four or more letters and digits without
    सौ/हज़ार/लाख in it. Amounts ("तीन लाख", "पचास हज़ार") stay, and so does a lone "के" or "जी".

    dates=False (the spec collects no date of birth): a month name alone doesn't make a run private, so "पच्चीस
    नवंबर" for a counselling session reaches the LLM. A long run of digits (a phone number, a passcode) still
    doesn't."""
    toks = tokens(text)
    out: list[str] = []
    i = 0
    while i < len(toks):
        if not _sensitive_token(toks[i]):
            out.append(toks[i])
            i += 1
            continue
        j = i
        while j < len(toks) and (_sensitive_token(toks[j]) or (toks[j] in _PAN_SKIP and j + 1 < len(toks)
                                                              and _sensitive_token(toks[j + 1]))):
            j += 1
        run = toks[i:j]
        chars = 0
        for t in run:
            if t in MULTIPLIERS:
                continue
            letters = _letters(t)
            if letters:
                chars += len(letters)
            elif t in NUMBER_WORDS:
                chars += len(str(NUMBER_WORDS[t]))
            elif re.fullmatch(r"[a-z0-9]+", t):
                chars += len(t)
        has_multiplier = any(t in MULTIPLIERS for t in run)
        if strict or (dates and any(t in MONTH_WORDS for t in run)) or (chars >= 4 and not has_multiplier):
            out.append(MASK)
        else:
            out.extend(run)
        i = j
    return " ".join(out)


@dataclass
class Secrets:
    """The caller's private values in this call. `found_in` reads a text the way the parsers would, so any
    spelling of them counts (अठासी or अट्ठासी, digits in pairs, letters run together), not one string."""
    pans: set[str]
    otps: set[str]
    dobs: set[date]

    def found_in(self, text: str) -> list[str]:
        found: list[str] = []
        compact = norm(text).replace(" ", "")
        for p in self.pans:
            if p.lower() in compact or p in _all_pans(text):
                found.append("pan")
        runs = _digit_runs(text)
        for o in self.otps:
            if o in compact or any(o in r for r in runs):
                found.append("passcode")
        dates = _dates_in(text)
        for d in self.dobs:
            if d in dates or norm(d.isoformat()).replace(" ", "") in compact or \
                    f"{d.day:02d}{d.month:02d}{d.year}" in compact:
                found.append("date of birth")
        return found


def _all_pans(text: str) -> set[str]:
    out = set()
    toks = tokens(text)
    for k in range(0, len(toks), 40):                  # long texts in overlapping windows
        p = find_pan(" ".join(toks[max(0, k - 12):k + 40]))
        if p:
            out.add(p)
    return out


def _digit_runs(text: str) -> list[str]:
    """Digits of each stretch of the text made only of number words and digits."""
    runs, cur = [], []
    for t in tokens(text) + ["."]:
        if t in NUMBER_WORDS or _is_numeric(t) or t in REPEATERS or t in MULTIPLIERS:
            cur.append(t)
        elif cur:
            runs.append(digit_string(" ".join(cur)))
            cur = []
    return runs


def _dates_in(text: str) -> set[date]:
    out = set()
    toks = tokens(text, keep_breaks=True)
    qs = quantities(text)
    for i, t in enumerate(toks):
        if t in MONTH_WORDS:
            before = [q.as_int for q in qs if q.end == i]
            after = _year_pairs([q.as_int for q in qs if q.start > i][:2], first_year_at=0)
            if before and after:
                try:
                    out.add(date(after[0], MONTH_WORDS[t], before[-1]))
                except ValueError:
                    pass
    vals = _year_pairs([q.as_int for q in qs], first_year_at=2)
    for k in range(len(vals) - 2):
        try:
            out.add(date(vals[k + 2], vals[k + 1], vals[k]))
        except ValueError:
            pass
    return out


def leaks(text: str, secrets: Secrets) -> list[str]:
    return secrets.found_in(text)
