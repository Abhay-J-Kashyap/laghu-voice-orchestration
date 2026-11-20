"""Text preparation for Laghu (design doc: Normalizer).

Laghu's own frontend, `devanagari_text.to_model_text`, already reads ₹ amounts in lakh and crore, dates,
times, percentages, phone numbers, OTPs and long account numbers, and spells acronyms. This module only
fills the gaps found on banking text (see tests/test_prep.py):

1. PAN numbers: "ABCDE1234F" would read its digits as "एक हज़ार दो सौ चौंतीस". Here every character is
   spaced out first, so each letter and digit is read on its own.
2. Lowercase English loanwords ("loan", "approve"): looked up in a lexicon, passed to to_model_text as its
   `transliterate` hook. Words still unknown are removed rather than spoken as Latin bytes, and reported.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .lexicon_bfsi import BFSI_WORDS

PAN_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z]{5})([0-9]{4})([A-Z])(?![A-Za-z0-9])")
LATIN_WORD_RE = re.compile(r"[A-Za-z]+")


@dataclass
class Prepared:
    model_text: str                 # what Laghu is given (already normalized; call it with normalize=False)
    dropped_words: list[str] = field(default_factory=list)
    bad_chars: set[str] = field(default_factory=set)


def spell_pan(text: str) -> str:
    return PAN_RE.sub(lambda m: " ".join(m.group(0)), text)


class TextPrep:
    def __init__(self, laghu_dir: Path, lexicon: dict[str, str] | None = None):
        if str(laghu_dir) not in sys.path:
            sys.path.insert(0, str(laghu_dir))
        from devanagari_text import to_model_text  # Laghu's frontend; same code as training and evaluation

        self._to_model_text = to_model_text
        self.lexicon = {k.lower(): v for k, v in (lexicon or BFSI_WORDS).items()}

    def _transliterate(self, word: str) -> str:
        return self.lexicon.get(word.lower(), "")

    def __call__(self, text: str) -> Prepared:
        out, bad = self._to_model_text(spell_pan(text), transliterate=self._transliterate)
        dropped = LATIN_WORD_RE.findall(out)
        if dropped:
            out = " ".join(LATIN_WORD_RE.sub(" ", out).split())
            out, bad = self._to_model_text(out, transliterate=self._transliterate)
        return Prepared(model_text=out, dropped_words=dropped, bad_chars=set(bad))
