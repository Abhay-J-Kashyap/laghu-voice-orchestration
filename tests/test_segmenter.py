from laghu_voice.text.segmenter import Segmenter


def feed_all(seg, pieces):
    out = []
    for p in pieces:
        out += seg.feed(p)
    return out + seg.flush()


def test_sentences_split_on_danda_and_question_mark():
    assert feed_all(Segmenter(), ["नमस्ते। आप कैसे हैं? ठीक है"]) == ["नमस्ते।", "आप कैसे हैं?", "ठीक है"]


def test_streamed_tokens_give_same_segments_as_whole_text():
    text = "आपका लोन अप्रूव हो गया है। आपकी EMI ₹12,500 होगी। धन्यवाद!"
    whole = feed_all(Segmenter(), [text])
    pieces = feed_all(Segmenter(), [text[i:i + 3] for i in range(0, len(text), 3)])
    assert whole == pieces == ["आपका लोन अप्रूव हो गया है।", "आपकी EMI ₹12,500 होगी।", "धन्यवाद!"]


def test_decimal_point_is_not_a_sentence_end_even_when_split_across_pieces():
    assert feed_all(Segmenter(), ["ब्याज दर 10.", "5% है. बस"]) == ["ब्याज दर 10.5% है.", "बस"]


def test_trailing_period_waits_for_next_character():
    s = Segmenter()
    assert s.feed("दर 10.") == []
    assert s.feed(" अगला") == ["दर 10."]


def test_first_clause_cut_only_for_first_segment():
    s = Segmenter(first_clause=True, min_clause_words=4)
    out = feed_all(s, ["जी हाँ, आपका आवेदन मिल गया है, और हम इसे देख रहे हैं।"])
    assert out[0] == "जी हाँ, आपका आवेदन मिल गया है,"   # "जी हाँ" alone is too short to cut
    assert out[1:] == ["और हम इसे देख रहे हैं।"]


def test_long_run_without_sentence_end_is_cut_at_a_comma():
    s = Segmenter(max_chars=40)
    out = s.feed("यह एक बहुत लंबा वाक्य है, जिसमें कोई पूर्ण विराम नहीं है और यह चलता ही जा रहा है")
    assert out == ["यह एक बहुत लंबा वाक्य है,"]


def test_commas_inside_amounts_never_cut_a_clause():
    s = Segmenter(first_clause=True, min_clause_words=2)
    out = feed_all(s, ["आपके लोन की राशि ₹2,", "50,000 है, और ब्याज दर 10.5% सालाना है।"])
    assert out == ["आपके लोन की राशि ₹2,50,000 है,", "और ब्याज दर 10.5% सालाना है।"]


def test_long_run_cut_skips_number_commas():
    s = Segmenter(max_chars=30)
    out = s.feed("कुल राशि ₹12,50,000 तय हुई और आगे की बात बाद में होगी")
    assert out == []   # the only commas are inside the amount


def test_flush_on_empty_buffer_returns_nothing():
    assert Segmenter().flush() == []
