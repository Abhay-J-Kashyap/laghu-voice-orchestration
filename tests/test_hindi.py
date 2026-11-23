"""Reading values from Hindi transcripts (laghu_voice/dialog/hindi.py), and writing numbers as Hindi words."""
import random
from datetime import date

import pytest

from laghu_voice.dialog import hindi as h

TODAY = date(2026, 11, 21)


@pytest.mark.parametrize("text, value", [
    ("तीन लाख", 300_000), ("साढ़े तीन लाख रुपये", 350_000), ("ढाई लाख", 250_000), ("डेढ़ हज़ार", 1500),
    ("एक लाख पचास हज़ार", 150_000), ("पंद्रह लाख", 1_500_000), ("पचानवे हजार", 95_000), ("सवा लाख", 125_000),
    ("3,00,000 रुपये", 300_000), ("दो करोड़", 20_000_000), ("ट्वेंटी फाइव थाउजेंड", 25_000),
])
def test_amounts(text, value):
    assert h.find_amount(text) == value


def test_a_date_is_not_an_amount():
    assert h.find_amount("बारह अप्रैल उन्नीस सौ अठासी") is None


def test_every_number_said_by_num_words_reads_back():
    random.seed(0)
    for n in list(range(1000)) + [random.randrange(1, 50_000_000) for _ in range(500)]:
        q = h.quantities(h.num_words(n))
        assert [x.as_int for x in q] == [n], h.num_words(n)


@pytest.mark.parametrize("x, words", [(11.5, "साढ़े ग्यारह"), (12.75, "पौने तेरह"), (13.25, "सवा तेरह"),
                                      (1.5, "डेढ़"), (2.5, "ढाई"), (10.99, "दस दशमलव नौ नौ"), (14.0, "चौदह")])
def test_rates_in_words_and_back(x, words):
    assert h.rate_words(x) == words
    assert h.number_values(words) == {x}


@pytest.mark.parametrize("text, months", [
    ("तीन साल के लिए", 36), ("डेढ़ साल", 18), ("छत्तीस महीने", 36), ("दस साल", 120), ("पंद्रह लाख तीन साल", 36),
])
def test_tenure(text, months):
    assert h.find_tenure_months(text) == months


def test_bare_tenure_number_is_years_up_to_ten():
    assert h.find_tenure_months("तीन", unitless_ok=True) == 36
    assert h.find_tenure_months("चौबीस", unitless_ok=True) == 24
    assert h.find_tenure_months("तीन") is None


def test_amount_and_tenure_in_one_breath_without_a_comma():
    qs = h.quantities("पंद्रह लाख तीन साल के लिए")
    assert [(q.value, q.unit) for q in qs] == [(1_500_000, None), (3, "years")]


def test_income_monthly_and_yearly():
    assert h.find_income("पचानवे हज़ार") == 95_000
    assert h.find_income("पचास हज़ार महीना") == 50_000
    assert h.find_income("साल के बारह लाख") == 100_000


@pytest.mark.parametrize("text, otp", [
    ("एक दो तीन चार पाँच छह", "123456"), ("बारह चौंतीस छप्पन", "123456"), ("डबल पाँच एक दो तीन चार", "551234"),
    ("फोर फाइव सिक्स वन टू थ्री", "456123"), ("मेरा कोड है शून्य नौ आठ सात छह पाँच", "098765"),
])
def test_passcode(text, otp):
    assert h.find_otp(text) == otp


def test_numbers_without_their_nasal_mark():
    assert h.find_otp("एक दो तीन चार पाच छह") == "123456"
    assert h.find_days("पाच दिन बाद") == 5 and h.find_amount("पाच लाख") == 500_000


def test_passcode_needs_exactly_six_digits():
    assert h.find_otp("एक दो तीन चार पाँच") is None


@pytest.mark.parametrize("text, pan", [
    ("मेरा पैन है ए बी सी डी ई एक दो तीन चार एफ़", "ABCDE1234F"),
    ("ए बी सी डी ई बारह चौंतीस एफ", "ABCDE1234F"),            # digits said in pairs
    ("जी, ए बी सी डी ई एक दो तीन चार एफ", "ABCDE1234F"),      # "जी" is also the letter G
    ("ए फॉर एप्पल बी सी डी ई एक दो तीन चार एफ", "ABCDE1234F"),   # "A for apple"
    ("एबीसीडीई बारह सौ चौंतीस एफ", "ABCDE1234F"),              # letters run together; 1234 as a number
    ("सी डी ई एफ जी तीन चार पाँच छह एच", "CDEFG3456H"),
    ("नहीं, पैन ए बी सी डी ई एक दो तीन पाँच एफ़ नहीं ए बी सी डी ई एक दो तीन चार एफ़ है", "ABCDE1234F"),  # last one wins
    ("ज़ेड ज़ेड ज़ेड ज़ेड ज़ेड नौ नौ नौ नौ ज़ेड", "ZZZZZ9999Z"),
    ("डबल यू ए बी सी डी एक दो तीन चार ई", "WABCD1234E"),
])
def test_pan(text, pan):
    assert h.find_pan(text) == pan


def test_half_a_pan_is_not_a_pan():
    assert h.find_pan("ए बी सी डी एक दो तीन") is None


@pytest.mark.parametrize("text, d", [
    ("बारह अप्रैल उन्नीस सौ अठासी", date(1988, 4, 12)), ("तीन नवंबर उन्नीस सौ चौरानवे", date(1994, 11, 3)),
    ("बारह चार उन्नीस सौ अठासी", date(1988, 4, 12)), ("बीस चार उन्नीस अठासी", date(1988, 4, 20)),
    ("चौदह अगस्त नाइनटीन नाइनटी टू", date(1992, 8, 14)), ("पाँच जनवरी दो हज़ार एक", date(2001, 1, 5)),
    ("बारह अप्रैल, उन्नीस सौ अठासी", date(1988, 4, 12)),
])
def test_dob(text, d):
    assert h.find_dob(text, TODAY).value == d


def test_dob_problems():
    assert h.find_dob("बारह अप्रैल अठासी", TODAY).problem == "year_ambiguous"
    assert h.find_dob("इकतीस फ़रवरी उन्नीस सौ नब्बे", TODAY).problem == "invalid"
    assert h.find_dob("पाँच जनवरी दो हज़ार पंद्रह", TODAY).problem == "invalid"     # under 18
    assert h.find_dob("पता नहीं", TODAY).problem == "not_found"


def test_date_words_read_back():
    for d in [date(1988, 4, 12), date(2001, 1, 5), date(1990, 12, 31)]:
        assert h.find_dob(h.date_words(d), TODAY).value == d


@pytest.mark.parametrize("text, yn", [("हाँ जी", "yes"), ("जी नहीं", "no"), ("ठीक है", "yes"), ("हां, सही है", "yes"),
                                      ("नहीं, मुझे सोचना है", "no"), ("बिल्कुल", "yes"),
                                      ("हाँ लेकिन पहले ये बताइए कि ब्याज कितना लगेगा", None)])
def test_yes_no(text, yn):
    assert h.yes_no(text) == yn


@pytest.mark.parametrize("text, kind", [("मैं नौकरी करता हूँ", "salaried"), ("मेरी अपनी दुकान है", "self_employed"),
                                        ("अभी काम नहीं करता", "unemployed"),
                                        ("नौकरी नहीं, अपना बिज़नेस है", "self_employed")])
def test_employment(text, kind):
    assert h.employment(text) == kind


def test_keyword_intents():
    assert h.keyword_intent("मुझे किसी इंसान से बात करनी है") == "human"
    assert h.keyword_intent("फिर से बोलिए") == "repeat"
    assert h.keyword_intent("अभी नहीं, बाद में बात करेंगे") == "stop"
    assert h.wants_resend("कोड नहीं आया, दोबारा भेजिए")


def test_email_spelt_out_and_read_back():
    e = h.find_email("के ए वी वाई ए डॉट आर ई डी डी वाई एट एग्ज़ाम्पल डॉट कॉम")
    assert e == "kavya.reddy@example.com"
    assert h.find_email(h.spell_email(e)) == e
    assert h.find_email("काव्या डॉट रेड्डी एट जीमेल डॉट कॉम") is None      # a name inside: the LLM reads it


def test_spoken_forms():
    assert h.spell_pan("ABCDE1234F") == "ए बी सी डी ई, एक दो तीन चार, एफ़"
    assert h.num_words(1_250_000) == "बारह लाख पचास हज़ार"
    assert h.digits_words("3210") == "तीन दो एक शून्य"
    assert h.tenure_words(36) == "तीन साल" and h.tenure_words(18) == "अठारह महीने"


def test_mask_hides_pan_passcode_date_but_keeps_amounts():
    assert h.mask_for_llm("हाँ मेरा पैन ए बी सी डी ई एक दो तीन चार एफ है", strict=False) == "हां मेरा पैन […] है"
    assert h.mask_for_llm("कोड है बारह चौंतीस", strict=False) == "कोड है […]"
    assert h.mask_for_llm("बारह अप्रैल उन्नीस सौ अठासी", strict=False) == "[…]"
    assert h.mask_for_llm("बुधवार पच्चीस नवंबर सुबह", strict=False, dates=False) == "बुधवार पच्चीस नवंबर सुबह"
    assert h.mask_for_llm("फोन नौ आठ सात छह पाँच चार", strict=False, dates=False) == "फोन […]"
    assert h.mask_for_llm("तीन लाख तीन साल के लिए", strict=False) == "तीन लाख तीन साल के लिए"
    # strict: every number and letter name goes, even the postposition के (it is also the letter K)
    assert h.mask_for_llm("तीन साल के लिए", strict=True) == "[…] साल […] लिए"


def test_leak_check_finds_every_spelling():
    secrets = h.Secrets({"ABCDE1234F"}, {"482913"}, {date(1988, 4, 12)})
    for text in ["pan ABCDE1234F", "ए बी सी डी ई एक दो तीन चार एफ़", "एबीसीडीई बारह चौंतीस एफ", "कोड चार आठ दो नौ एक तीन",
                 "4 8 2 9 1 3", "अड़तालीस उनतीस तेरह", "1988-04-12", "बारह अप्रैल उन्नीस सौ अठासी",
                 "बारह अप्रैल उन्नीस सौ अट्ठासी", "बारह चार उन्नीस अठासी"]:
        assert h.leaks(text, secrets), text
    assert not h.leaks("तीन लाख रुपये तीन साल के लिए, बारह अप्रैल को फ़ोन किया", secrets)
