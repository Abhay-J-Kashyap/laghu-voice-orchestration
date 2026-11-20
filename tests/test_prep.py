"""Banking text through Laghu's real frontend plus our two fixes (PAN digits, loanwords)."""
import pytest

from laghu_voice.text.prep import TextPrep, spell_pan


@pytest.fixture(scope="module")
def prep(laghu_dir):
    return TextPrep(laghu_dir)


def test_spell_pan_spaces_every_character():
    assert spell_pan("PAN ABCDE1234F है") == "PAN A B C D E 1 2 3 4 F है"
    assert spell_pan("XABCDE1234F") == "XABCDE1234F"   # not a PAN on its own


@pytest.mark.parametrize("text, expected", [
    ("आपका PAN ABCDE1234F है।", "आपका पी ए एन ए बी सी डी ई एक दो तीन चार एफ़ है."),
    ("आपका loan approve हो गया है।", "आपका लोन अप्रूव हो गया है."),
    ("आपका OTP 482913 है।", "आपका ओ टी पी चार आठ दो नौ एक तीन है."),
    ("लोन ₹12,50,000 का है।", "लोन बारह लाख पचास हज़ार रुपये का है."),
])
def test_banking_sentences(prep, text, expected):
    r = prep(text)
    assert r.model_text == expected
    assert not r.bad_chars and not r.dropped_words


def test_unknown_latin_words_are_dropped_and_reported(prep):
    r = prep("blorptastic ऑफ़र है।")
    assert r.dropped_words == ["blorptastic"]
    assert "blorptastic" not in r.model_text and not r.bad_chars
