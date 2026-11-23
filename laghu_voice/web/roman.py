"""Devanagari in Latin letters, the way people type Hindi in chats ("mera naam abhay hai"), so someone who can't
read the script can still follow a transcript. Not a scholarly transliteration: readable, not reversible.

The one Hindi-specific rule is the dropped "a": a consonant's built-in vowel is not said at the end of a word
(नाम naam, not naama) or between two sounded syllables (समझना samajhna). Clusters keep it (धन्यवाद dhanyavaad).
"""
from __future__ import annotations

import re

_CONS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "ng", "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "ny",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh",
    "ष": "sh", "स": "s", "ह": "h", "ळ": "l",
    "क़": "q", "ख़": "kh", "ग़": "g", "ज़": "z", "ड़": "r", "ढ़": "rh", "फ़": "f", "य़": "y",
}
_NUKTA = {"क": "क़", "ख": "ख़", "ग": "ग़", "ज": "ज़", "ड": "ड़", "ढ": "ढ़", "फ": "फ़", "य": "य़"}
_VOWELS = {"अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ऋ": "ri", "ए": "e", "ऐ": "ai",
           "ओ": "o", "औ": "au", "ऑ": "o", "ऍ": "e"}
_SIGNS = {"ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "ृ": "ri", "े": "e", "ै": "ai", "ो": "o",
          "ौ": "au", "ॉ": "o", "ॅ": "e"}
_END = {"aa": "a", "ee": "i"}             # at a word's end: "karna", "nahi", as people type them
_VIRAMA, _NUKTA_SIGN = "्", "़"
_NASAL = {"ं": "n", "ँ": "n"}
_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_WORD = re.compile(r"[ऀ-ॿ]+")


def _syllables(word: str) -> list[list]:
    """[consonants, vowel, vowel is the built-in a, nasal] per syllable."""
    out: list[list] = []
    cluster: list[str] = []
    i = 0
    while i < len(word):
        ch = word[i]
        if i + 1 < len(word) and word[i + 1] == _NUKTA_SIGN and ch in _NUKTA:
            ch = _NUKTA[ch]
            i += 1
        if ch in _CONS:
            cluster.append(_CONS[ch])
            nxt = word[i + 1] if i + 1 < len(word) else ""
            if nxt == _VIRAMA:
                i += 2
                continue
            if nxt in _SIGNS:
                out.append([cluster, _SIGNS[nxt], False, ""])
                i += 2
            else:
                out.append([cluster, "a", True, ""])
                i += 1
            cluster = []
            continue
        if cluster:                                   # a dead consonant before something else: keep it as is
            out.append([cluster, "", False, ""])
            cluster = []
        if ch in _VOWELS:
            out.append([[], _VOWELS[ch], False, ""])
        elif ch in _NASAL or ch == "ः":
            if out:
                out[-1][3] += "n" if ch in _NASAL else "h"
        i += 1
    if cluster:
        out.append([cluster, "", False, ""])
    return out


def _word(word: str) -> str:
    syl = _syllables(word)
    n = len(syl)
    if n > 1 and syl[-1][2] and not syl[-1][3]:
        syl[-1][1] = ""                               # final built-in a: नाम naam
    for i in range(n - 2, 0, -1):                     # between two sounded syllables: समझना samajhna
        s = syl[i]
        if s[2] and not s[3] and len(s[0]) == 1 and syl[i - 1][1] and syl[i + 1][1] and not syl[i + 1][2]:
            s[1] = ""
    parts = []
    for k, (cons, vowel, _inherent, nasal) in enumerate(syl):
        if k == n - 1 and not nasal:
            vowel = _END.get(vowel, vowel)
        parts.append("".join(cons) + vowel + nasal)
    return "".join(parts)


def romanize(text: str) -> str:
    """Devanagari words in Latin letters; everything else (English, digits, punctuation) as it is."""
    if not text:
        return ""
    t = text.translate(_DIGITS).replace("।", ".").replace("॥", ".")
    return _WORD.sub(lambda m: _word(m.group(0)), t)
