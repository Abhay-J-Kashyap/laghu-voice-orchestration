"""Cut streamed LLM text into segments for TTS (design doc: Text-to-speech path, step 1).

Laghu was fine-tuned on whole sentences, so segments end at sentence marks (। . ? !). Two exceptions:
- `first_clause=True`: the FIRST segment of a reply may end at a comma once it holds `min_clause_words`
  words, so audio starts sooner. Off by default until Milestone 0 measures its effect on CER.
- A run of text longer than `max_chars` with no sentence mark is cut at its last comma, so one long LLM
  sentence can't hold back the audio.

A "." directly between two digits (10.5) is a decimal point, not a sentence end. Because text arrives in
pieces, a "." at the very end of the buffer is held until the next character shows which one it is.
"""
from __future__ import annotations

SENTENCE_END = "।.?!\n"
CLAUSE_END = ","


def clause_commas(b: str) -> list[int]:
    """Indices of commas that can end a clause. A comma inside a number (₹2,50,000) can't; a comma right
    after a digit at the end of the buffer isn't decided yet, so it isn't returned either."""
    out = []
    for k, ch in enumerate(b):
        if ch != CLAUSE_END:
            continue
        if k > 0 and b[k - 1].isdigit() and (k + 1 >= len(b) or b[k + 1].isdigit()):
            continue
        out.append(k)
    return out


class Segmenter:
    def __init__(self, first_clause: bool = False, min_clause_words: int = 4, max_chars: int = 160):
        self.first_clause = first_clause
        self.min_clause_words = min_clause_words
        self.max_chars = max_chars
        self._buf = ""
        self._emitted = 0

    def feed(self, piece: str) -> list[str]:
        """Add streamed text; return the segments that are now complete."""
        self._buf += piece
        out: list[str] = []
        while True:
            cut = self._find_cut()
            if cut is None:
                break
            seg, self._buf = self._buf[:cut].strip(), self._buf[cut:]
            if seg:
                out.append(seg)
                self._emitted += 1
        return out

    def flush(self) -> list[str]:
        """End of the reply: whatever is left is the last segment."""
        seg, self._buf = self._buf.strip(), ""
        if seg:
            self._emitted += 1
            return [seg]
        return []

    # ------------------------------------------------------------------
    def _find_cut(self) -> int | None:
        b = self._buf
        sentence_cut, scanned_to = self._sentence_cut(b)
        commas = clause_commas(b)
        if self.first_clause and self._emitted == 0:
            # Earliest comma, before any sentence end, with enough words in front of it.
            limit = sentence_cut if sentence_cut is not None else scanned_to
            for k in commas:
                if k >= limit:
                    break
                if len(b[:k].split()) >= self.min_clause_words:
                    return k + 1
        if sentence_cut is not None:
            return sentence_cut
        if len(b) > self.max_chars:
            ks = [k for k in commas if k < self.max_chars]
            if ks:
                return ks[-1] + 1
        return None

    @staticmethod
    def _sentence_cut(b: str) -> tuple[int | None, int]:
        """(index just after the first sentence end, or None; how far the buffer could be judged)."""
        for i, ch in enumerate(b):
            if ch not in SENTENCE_END:
                continue
            if ch == ".":
                if i + 1 >= len(b):
                    return None, i                   # can't tell a decimal point yet; wait for more text
                if i > 0 and b[i - 1].isdigit() and b[i + 1].isdigit():
                    continue                         # 10.5
            j = i + 1                                # keep runs like "?!" or "..." together
            while j < len(b) and b[j] in SENTENCE_END:
                j += 1
            if j >= len(b) and b[j - 1] == ".":
                return None, i                       # "..." may still be growing
            return j, i
        return None, len(b)
