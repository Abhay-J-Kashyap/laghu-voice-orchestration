"""The dialog engine on the real loan spec (in-memory backend) and the gym spec (mock tools), with a scripted
LLM (no network)."""
import asyncio
import json
import re
from datetime import date
from pathlib import Path

import pytest
from fake_backend import OTP, FakeBackend

from laghu_voice.dialog import hindi
from laghu_voice.dialog.agent import Agent, say_all
from laghu_voice.dialog.backend import BackendClient
from laghu_voice.dialog.guard import asks_question, check_answer
from laghu_voice.dialog.llm import DialogLLM, parse_json
from laghu_voice.dialog.spec import SpecError, load_spec
from laghu_voice.services.llm_openai import LLMError

AGENTS = Path(__file__).resolve().parents[1] / "agents"
SPEC = AGENTS / "loan_onboarding.yaml"
RAJESH_NAME = {"intent": "answer", "full_name": "Rajesh Kumar", "full_name_hi": "राजेश कुमार"}


class Scripted:
    """An LLM from queues: `answers` for extraction (dicts as JSON, or exceptions), `written` for generation
    (else it says the examples it was given). Records every request."""
    def __init__(self, *answers, written=(), delay=0.0):
        self.answers = list(answers)
        self.written = list(written)
        self.delay = delay
        self.sent = []

    async def complete(self, messages, stats=None, **kw):
        self.sent.append(messages)
        await asyncio.sleep(self.delay)
        a = self.answers.pop(0) if self.answers else {"intent": "unclear"}
        if isinstance(a, Exception):
            raise a
        return json.dumps(a, ensure_ascii=False)

    async def stream(self, messages, stats=None, **kw):
        self.sent.append(messages)
        await asyncio.sleep(self.delay)
        if self.written:
            w = self.written.pop(0)
            if isinstance(w, Exception):
                raise w
            for word in w.split(" "):
                yield word + " "
            return
        for ex in re.findall(r'Example: "([^"]*)"', messages[-1]["content"]):
            yield ex + " "


@pytest.fixture
def spec():
    return load_spec(SPEC)


def make(spec, *answers, written=(), delay=0.0):
    fb = FakeBackend()
    llm = Scripted(*answers, written=written, delay=delay)
    agent = Agent(spec, BackendClient("http://fake", "k", transport=fb.transport()),
                  DialogLLM(llm, spec.agent), "test-call", today=date(2026, 11, 21))
    return agent, fb, llm


async def turn(agent, text, heard=True):
    r = await agent.handle(text, prompt_heard=heard)
    await say_all(agent, r)
    return r


async def turns(agent, lines):
    return [await turn(agent, x) for x in lines]


async def start(agent):
    r = await agent.start()
    await say_all(agent, r)
    return r


IDENTITY = ["हाँ जी", "मेरा नाम राजेश कुमार है", "बारह अप्रैल उन्नीस सौ अठासी", "ए बी सी डी ई एक दो तीन चार एफ़", "हाँ सही है"]
LOAN = ["तीन लाख", "तीन साल", "पचानवे हज़ार", "नौकरी करता हूँ"]


async def test_happy_path_completes_with_consent(spec):
    agent, fb, llm = make(spec, RAJESH_NAME)
    r = await start(agent)
    assert r.spoken.startswith("मैं लघु") and "नमस्ते" not in r.spoken
    await turns(agent, IDENTITY + [hindi.digits_words(OTP)] + LOAN)
    assert "पात्र" in agent.spoken[-1] and "तीन लाख" in agent.spoken[-1]
    r = await turn(agent, "हाँ, मैं सहमत हूँ")
    assert r.end == "completed"
    s = next(iter(fb.sessions.values()))
    assert s["tools"] == ["verify_identity", "verify_otp", "check_eligibility", "record_consent"]
    assert s["consents"] == [True]
    assert not agent.problems


async def test_line_kinds(spec):
    """Fixed and template lines are said exactly; LLM lines are written; the read-back is a template."""
    agent, _, llm = make(spec, RAJESH_NAME, written=["बहुत अच्छा! अब मुझे अपना पूरा नाम बताइए।"])
    await start(agent)
    r = await turn(agent, "हाँ जी")
    assert r.spoken == "बहुत अच्छा! अब मुझे अपना पूरा नाम बताइए।"          # written by the LLM
    assert r.step["guard"][0]["source"] == "generate" and r.step["guard"][0]["ok"]
    await turns(agent, IDENTITY[1:4])
    assert agent.spoken[-1].startswith("मैंने यह लिखा है। नाम, राजेश कुमार।")   # template
    assert "ए बी सी डी ई, एक दो तीन चार, एफ़" in agent.spoken[-1]


async def test_nothing_private_reaches_the_llm(spec):
    agent, fb, llm = make(spec, RAJESH_NAME, {"intent": "question"})
    await start(agent)
    await turns(agent, IDENTITY + [hindi.digits_words(OTP), "पहले ये बताइए ब्याज कितना लगेगा"])
    sent = json.dumps(llm.sent, ensure_ascii=False)
    assert not hindi.leaks(sent, agent.secrets())
    assert "[…]" in sent                        # the passcode turn, the read-back and the phone digits
    assert "0001" not in sent                   # the phone's last four digits (private, though not secret)


async def test_leak_check_refuses_to_send(spec, monkeypatch):
    agent, _, llm = make(spec, RAJESH_NAME, {"intent": "answer"})
    await start(agent)
    await turns(agent, IDENTITY + [hindi.digits_words(OTP)] + LOAN[:3])
    assert agent.state == "ask_employment"
    n = len(llm.sent)
    monkeypatch.setattr(hindi, "mask_for_llm", lambda text, strict: text)    # break the first lock
    r = await turn(agent, "वही जो मेरे पैन ए बी सी डी ई एक दो तीन चार एफ़ पर लिखा है")
    assert agent.llm.blocked and r.step["llm"][0]["blocked"] and r.step["event"] == "unclear"
    assert all("ए बी सी डी ई" not in json.dumps(m, ensure_ascii=False) for m in llm.sent[n:])


async def test_written_sentence_with_an_invented_number_is_replaced(spec):
    agent, _, llm = make(spec, RAJESH_NAME, {"intent": "question"})
    await start(agent)
    await turns(agent, IDENTITY + [hindi.digits_words(OTP)])
    llm.written.append("ब्याज दर बारह प्रतिशत होगी। आपको कितनी राशि चाहिए?")
    r = await turn(agent, "पहले ये बताइए ब्याज कितना लगेगा")
    g = r.step["guard"][-1]
    assert not g["ok"] and "number:12" in g["reasons"]
    assert "बारह" not in r.spoken and r.spoken.endswith("आपको कितनी राशि का लोन चाहिए?")


async def test_a_reply_that_forgets_to_ask_gets_the_question(spec):
    agent, _, _ = make(spec, written=["बहुत बढ़िया, धन्यवाद।"])
    await start(agent)
    r = await turn(agent, "हाँ")
    assert r.step["guard"][0]["fallback"] == "question"
    assert r.spoken == "बहुत बढ़िया, धन्यवाद। ठीक है। सबसे पहले, कृपया अपना पूरा नाम बताइए।"


async def test_llm_down_says_the_examples(spec):
    agent, _, _ = make(spec, written=[LLMError("HTTP 500", 500)])
    await start(agent)
    r = await turn(agent, "हाँ")
    assert r.spoken == "ठीक है। सबसे पहले, कृपया अपना पूरा नाम बताइए।"


async def test_extraction_writes_the_reply_in_the_same_call(spec):
    reply = "धन्यवाद राजेश जी। अब अपनी जन्म तिथि बताइए।"
    agent, _, llm = make(spec, {**RAJESH_NAME, "reply": reply})
    await start(agent)
    await turn(agent, "हाँ")
    n = len(llm.sent)
    r = await turn(agent, "मेरा नाम राजेश कुमार है")
    assert r.spoken == reply and len(llm.sent) == n + 1       # one call: understood and answered
    assert r.step["guard"][0]["source"] == "extraction"


async def test_consent_over_an_interrupted_question_is_asked_again(spec):
    agent, fb, _ = make(spec, RAJESH_NAME)
    await start(agent)
    await turns(agent, IDENTITY + [hindi.digits_words(OTP)] + LOAN)
    agent.note_interrupted(0.3)
    r = await turn(agent, "हाँ हाँ", heard=False)
    assert r.step["not_heard_guard"] and r.end is None
    assert "पात्र" in r.spoken                       # the terms are said again, not only the question
    s = next(iter(fb.sessions.values()))
    assert s["consents"] == []
    r = await turn(agent, "हाँ, सहमत हूँ")
    assert r.end == "completed" and s["consents"] == [True]


async def test_wrong_pan_corrected_at_read_back_uses_no_attempt(spec):
    agent, fb, _ = make(spec, RAJESH_NAME)
    await start(agent)
    await turns(agent, ["हाँ", "मेरा नाम राजेश कुमार है", "बारह अप्रैल उन्नीस सौ अठासी", "ए बी सी डी ई एक दो तीन पाँच एफ़"])
    r = await turn(agent, "नहीं, पैन ए बी सी डी ई एक दो तीन चार एफ़ है")
    assert r.step["event"] == "corrected" and "एक दो तीन चार" in r.spoken
    assert fb.calls == []
    await turn(agent, "हाँ")
    assert [c[0] for c in fb.calls] == ["verify_identity"] and agent.state == "ask_otp_phone"


async def test_half_a_pan_is_asked_again(spec):
    agent, _, _ = make(spec, RAJESH_NAME)
    await start(agent)
    await turns(agent, ["हाँ", "मेरा नाम राजेश कुमार है", "बारह अप्रैल उन्नीस सौ अठासी"])
    r = await turn(agent, "ए बी सी डी एक दो तीन")
    assert r.step["event"] == "reask" and r.spoken == spec.lines["pan_not_heard"].example and agent.state == "ask_pan"


async def test_mismatch_then_blocked_hands_over(spec):
    agent, fb, _ = make(spec, RAJESH_NAME, RAJESH_NAME)
    await start(agent)
    wrong = ["मेरा नाम राजेश कुमार है", "एक जनवरी उन्नीस सौ नब्बे", "ए बी सी डी ई एक दो तीन चार एफ़", "हाँ"]
    await turns(agent, ["हाँ"] + wrong)
    assert agent.state == "ask_name_again"
    r = (await turns(agent, wrong))[-1]
    assert r.end == "transferred"
    assert [c[0] for c in fb.calls] == ["verify_identity", "verify_identity", "escalate"]
    assert fb.calls[-1][1]["reason_code"] == "identity_verification_failed"


async def test_tenure_beyond_policy_is_asked_again(spec):
    agent, _, _ = make(spec, RAJESH_NAME)
    await start(agent)
    await turns(agent, IDENTITY + [hindi.digits_words(OTP), "तीन लाख"])
    r = await turn(agent, "बीस साल के लिए")
    assert r.spoken == spec.lines["tenure_out_of_range"].example and agent.state == "ask_tenure"


async def test_amount_and_tenure_together_skip_the_tenure_question(spec):
    agent, _, _ = make(spec, RAJESH_NAME)
    await start(agent)
    await turns(agent, IDENTITY + [hindi.digits_words(OTP), "पंद्रह लाख तीन साल के लिए"])
    assert agent.slots["amount"] == 1_500_000 and agent.slots["tenure_months"] == 36
    assert agent.state == "ask_income"


async def test_three_unclear_answers_hand_over(spec):
    agent, fb, _ = make(spec, RAJESH_NAME, {"intent": "unclear"}, {"intent": "unclear"}, {"intent": "unclear"})
    await start(agent)
    await turns(agent, IDENTITY + [hindi.digits_words(OTP), "तीन लाख", "तीन साल"])
    r = (await turns(agent, ["वो तो देखिए", "हम्म वो", "पता नहीं"]))[-1]
    assert r.end == "transferred" and fb.calls[-1][1]["reason_code"] == "low_confidence_transcription"


async def test_declined_then_dispute_goes_to_underwriting(spec):
    agent, fb, _ = make(spec, {"intent": "answer", "full_name": "Imran Qureshi", "full_name_hi": "इमरान क़ुरैशी"},
                        {"intent": "dispute"})
    await start(agent)
    await turns(agent, ["हाँ", "मेरा नाम इमरान क़ुरैशी है", "इक्कीस जुलाई उन्नीस सौ इक्यानवे",
                        "सी डी ई एफ़ जी तीन चार पाँच छह एच", "हाँ", hindi.digits_words(OTP), "दो लाख", "दो साल",
                        "साठ हज़ार", "मेरा अपना बिज़नेस है"])
    assert agent.state == "declined"
    r = await turn(agent, "ये फ़ैसला गलत है, मेरा क्रेडिट स्कोर तो अच्छा है")
    assert r.end == "transferred" and fb.sessions[agent.vars["session_id"]]["escalation"]["queue"] == "underwriting"


async def test_silence_reprompts_then_hangs_up(spec):
    agent, _, _ = make(spec)
    await start(agent)
    for _ in range(3):
        r = await agent.on_silence()
        await say_all(agent, r)
        assert r.spoken.startswith("क्या आप लाइन पर हैं?") and r.end is None
    r = await agent.on_silence()
    await say_all(agent, r)
    assert r.end == "no_response" and r.spoken == spec.lines["hangup_silence"].text


async def test_passcode_resend_and_wrong_code(spec):
    agent, fb, _ = make(spec, RAJESH_NAME)
    await start(agent)
    await turns(agent, IDENTITY)
    assert agent.shown["demo_otp"] == OTP
    r = await turn(agent, "कोड नहीं आया, दोबारा भेजिए")
    assert r.spoken == spec.lines["otp_resent"].example
    await turn(agent, "एक एक एक एक एक एक")
    await turn(agent, hindi.digits_words(OTP))
    assert agent.state == "ask_amount"
    assert [c[0] for c in fb.calls] == ["verify_identity", "resend_otp", "verify_otp", "verify_otp"]


async def test_extraction_failure_is_unclear_not_a_crash(spec):
    agent, _, _ = make(spec, LLMError("HTTP 500", 500), LLMError("HTTP 500", 500))
    await start(agent)
    await turn(agent, "हाँ")
    r = await turn(agent, "मेरा नाम राजेश कुमार है")
    assert r.step["event"] == "unclear" and agent.state == "ask_name"


async def test_no_backend_ends_politely(spec):
    class Down:
        client = None
    agent = Agent(spec, Down(), None, "x")
    r = await start(agent)
    assert r.end == "transfer_failed" and r.spoken == spec.lines["transfer_failed"].text


# ---------------------------------------------------------------------- a second use case
async def test_gym_onboarding_books_a_membership_on_mock_tools():
    gym = load_spec(AGENTS / "gym_onboarding.yaml")
    assert not gym.http
    agent = Agent(gym, None, DialogLLM(Scripted({"intent": "answer", "full_name": "Neha Verma",
                                                 "full_name_hi": "नेहा वर्मा"}), gym.agent), "gym-1")
    r = await start(agent)
    assert "फ़िटज़ोन जिम" in r.spoken
    await turns(agent, ["हाँ बोलिए", "मेरा नाम नेहा वर्मा है", "मुझे वज़न कम करना है", "तीन महीने वाला, सुबह का बैच"])
    assert agent.slots == {**agent.slots, "goal": "weight_loss", "plan": "quarterly", "time_slot": "morning"}
    assert agent.state == "ask_start"                           # the batch time came with the plan
    r = await turn(agent, "कल से")
    assert r.spoken == "तिमाही प्लान की फ़ीस चार हज़ार रुपये है। तो आपकी मेंबरशिप कल से, सुबह के बैच में शुरू होगी। क्या मैं इसे बुक कर दूँ?"
    r = await turn(agent, "हाँ कर दीजिए")
    assert r.end == "booked" and [t.tool for t in agent.tool_log] == ["quote_plan", "book_membership"]


async def test_gym_trial_from_anywhere_and_no_invented_fee():
    gym = load_spec(AGENTS / "gym_onboarding.yaml")
    llm = Scripted({"intent": "question"})
    agent = Agent(gym, None, DialogLLM(llm, gym.agent), "gym-2")
    await start(agent)
    await turns(agent, ["हाँ"])
    llm.written.append("फ़ीस सिर्फ़ एक हज़ार रुपये है। अपना नाम बताइए।")
    r = await turn(agent, "फ़ीस कितनी है?")                     # no fee known yet: the made-up one is refused
    assert not r.step["guard"][0]["ok"] and "हज़ार" not in r.spoken
    r = await turn(agent, "पहले मैं फ्री ट्रायल लेना चाहूँगी")
    assert agent.state == "confirm_trial" and r.end is None     # asked first, never booked on a phrase
    r = await turn(agent, "हाँ")
    assert r.end == "trial_booked"


# ---------------------------------------------------------------------- pieces
def test_parse_json_validates():
    assert parse_json('```json\n{"intent": "answer", "full_name": "Rajesh Kumar"}\n```', ["answer"]) == \
        {"intent": "answer", "full_name": "Rajesh Kumar"}
    assert parse_json('{"intent": "maybe"}', ["answer"]) is None
    assert parse_json("not json", ["answer"]) is None


async def test_rate_limit_waits_only_as_long_as_allowed(spec):
    llm = Scripted(LLMError("HTTP 429", 429, 0.01), {"intent": "yes"})
    d = DialogLLM(llm, spec.agent, max_wait_429_s=1.0)
    none = hindi.Secrets(set(), set(), set())
    kw = dict(asked="", caller="हम्म", history=[], interrupted=False, expect="a yes or no", slots=[], intents=[],
              next_steps={}, facts={}, secrets=none)
    ex = await d.extract(**kw)
    assert ex.intent == "yes" and ex.call.rate_limited_s > 0
    d = DialogLLM(Scripted(LLMError("HTTP 429", 429, 5.0)), spec.agent, max_wait_429_s=1.0)
    ex = await d.extract(**kw)
    assert ex.intent == "unclear" and "429" in ex.call.error


def test_guard():
    assert check_answer("यह आपकी पात्रता पर निर्भर करेगा।", set()).ok
    assert not check_answer("आपका लोन पक्का मंज़ूर होगा।", set()).ok
    assert not check_answer("Your loan is fine.", set()).ok
    assert not check_answer("मैं बता सकती हूँ।", set()).ok
    assert check_answer("ब्याज साढ़े बारह प्रतिशत है।", {12.5}).ok
    assert check_answer("एक सहयोगी मदद करेंगे।", set()).ok           # एक as the article
    assert check_answer("इसकी पक्की जानकारी मैं नहीं दे सकता।", set()).ok
    assert asks_question("कृपया अपना नाम बताइए।") and asks_question("अब जन्म तिथि बताइए, दिन और साल।")
    assert not asks_question("माफ़ कीजिए, मैं समझ नहीं पाया।")


def test_spec_rules(tmp_path):
    text = SPEC.read_text(encoding="utf-8")
    p = tmp_path / "bad.yaml"
    for old, new, msg in [
        ('verified: "धन्यवाद,', 'verified: "नमस्ते, धन्यवाद,', "नमस्ते"),
        ("on: {yes: ask_name, no: not_now}", "on: {yes: ask_nam, no: not_now}", "ask_nam does not exist"),
        ('example: "आपको कितनी राशि का लोन चाहिए?"', 'example: "आपका पैन {pan} है?"', "private value pan"),
        ("{phone_last4:digits}", "{phone_last4:shout}", "unknown format"),
    ]:
        assert old in text, old
        p.write_text(text.replace(old, new, 1), encoding="utf-8")
        with pytest.raises(SpecError, match=msg):
            load_spec(p)


def test_both_specs_load_and_cache_their_fixed_sentences():
    for name in ("loan_onboarding.yaml", "gym_onboarding.yaml"):
        s = load_spec(AGENTS / name)
        fixed = s.fixed_lines()
        assert "जी, एक पल।" in fixed and not any("{" in x for x in fixed)


# ---------------------------------------------------------------------- fixes from Abhay's first gym call
GYM = AGENTS / "gym_onboarding.yaml"
ABHAY = {"intent": "answer", "full_name": "Abhay", "full_name_hi": "अभय"}


async def gym_agent(*answers):
    gym = load_spec(GYM)
    llm = Scripted(*answers)
    a = Agent(gym, None, DialogLLM(llm, gym.agent), "gym")
    await start(a)
    return a, llm, gym


async def test_one_llm_call_when_the_next_question_is_skippable():
    reply = "धन्यवाद अभय जी! आपका फ़िटनेस लक्ष्य क्या है?"
    a, llm, _ = await gym_agent({**ABHAY, "reply": reply})
    await turn(a, "हाँ")
    n = len(llm.sent)
    r = await turn(a, "मेरा नाम अभय है")       # ask_goal has skip_if: the reply must still be foreseen
    assert len(llm.sent) == n + 1 and r.spoken == reply


async def test_two_options_named_are_asked_again_not_guessed():
    a, _, gym = await gym_agent(ABHAY)
    await turns(a, ["हाँ", "मेरा नाम अभय है", "मसल्स बनाना", "सालाना"])
    r = await turn(a, "सुबह और दोपहर के बीच अः ठीक रहेगा")
    assert r.step["problem"] == "ambiguous" and "time_slot" not in a.slots
    assert r.spoken == gym.lines["time_pick"].example
    assert a.unclear == 0                       # the caller was clear; it doesn't count towards a hand-over


async def test_a_range_is_asked_again_not_guessed():
    a, _, gym = await gym_agent(ABHAY)
    await turns(a, ["हाँ", "मेरा नाम अभय है", "मसल्स बनाना", "सालाना", "सुबह"])
    r = await turn(a, "हओ अः कुछ दिन बाद लीके अः एक या दो वीक बाद")
    assert r.step["problem"] == "range" and "start_days" not in a.slots
    r = await turn(a, "एक हफ़्ते बाद")
    assert a.slots["start_days"] == 7 and "सात दिन बाद" in r.spoken


async def test_discount_and_longer_trial_are_answered_and_confirmed():
    a, _, gym = await gym_agent(ABHAY, {"intent": "trial"})
    await turns(a, ["हाँ", "मेरा नाम अभय है", "मसल्स बनाना", "सालाना", "सुबह", "एक हफ़्ते बाद"])
    r = await turn(a, "प्लान का फीस थोड़ा कम कर दो जाए")
    assert r.step["event"] == "discount" and a.state == "no_discount"
    await turn(a, "नहीं")
    r = await turn(a, "एक वीक का मुफ़्त प्लान कर सकते हो")
    assert a.state == "confirm_trial" and r.end is None and not [t for t in a.tool_log if t.tool == "book_trial"]
    r = await turn(a, "नहीं")                   # no: back to the question before the detour
    assert a.state == "offer_trial"


async def test_reasks_are_told_to_be_brief_and_different():
    a, llm, _ = await gym_agent(ABHAY, {"intent": "unclear"})
    await turns(a, ["हाँ", "मेरा नाम अभय है"])
    await turn(a, "वो देखिए")
    assert "Ask this again, briefly and in different words" in llm.sent[-1][-1]["content"]


async def test_knowledge_reaches_the_llm_and_its_numbers_may_be_said():
    a, llm, _ = await gym_agent(ABHAY, {"intent": "question"})
    await turns(a, ["हाँ", "मेरा नाम अभय है", "मसल्स बनाना"])
    llm.written.append("हमारे पास मासिक प्लान पंद्रह सौ रुपये का है। आप कौन सा प्लान लेंगे?")
    r = await turn(a, "और क्याक्या प्लान है तुम्हारे पास")
    assert "1500 rupees" in json.dumps(llm.sent[-2], ensure_ascii=False)
    assert r.step["guard"][-1]["ok"] and "पंद्रह सौ" in r.spoken


def test_an_intent_phrase_cannot_act_without_asking(tmp_path):
    text = GYM.read_text(encoding="utf-8").replace("trial: confirm_trial               #", "trial: book_trial  #")
    p = tmp_path / "bad.yaml"
    p.write_text(text, encoding="utf-8")
    with pytest.raises(SpecError, match="intent trial leads to the tool book_trial without asking"):
        load_spec(p)


def test_choice_overlap_and_ranges():
    gym = load_spec(GYM)
    assert gym.slots["plan"].choices_in("तीन महीने वाला") == ["quarterly"]       # not monthly too
    assert gym.slots["plan"].choices_in("बारह महीने का") == ["yearly"]
    assert gym.slots["goal"].choices_in("वज़न भी कम करना है और मसल भी बनानी है") == ["weight_loss", "muscle"]
    assert hindi.has_range("दो तीन लाख") and hindi.has_range("तीन से पाँच लाख")
    assert not hindi.has_range("पंद्रह लाख तीन साल") and not hindi.has_range("बारह चार उन्नीस सौ अठासी")


def test_filler_tail_is_trimmed_even_when_the_silence_is_noise():
    import numpy as np

    from laghu_voice.services.tts_cache import trim_tail
    rng = np.random.default_rng(0)
    speech = 0.3 * np.sin(np.arange(9600) / 5).astype(np.float32)                  # 0.4 s of sound
    noise = (0.012 * rng.standard_normal(24000)).astype(np.float32)               # 1 s of noise above 0.01
    y = trim_tail(np.concatenate([speech, noise]), 24000)
    assert len(y) <= 9600 + int(24000 * 0.12) + 480


async def test_second_gym_call_fixes():
    """From Abhay's second gym call (b0dabb46965f): a number with its nasal mark dropped by speech recognition,
    and a question the LLM couldn't place."""
    a, llm, _ = await gym_agent(ABHAY, {"intent": "unclear"})
    await turns(a, ["हाँ", "मेरा नाम अभय है", "मसल्स बनाना", "मासिक"])
    r = await turn(a, "ये बताओ अ तुम्हारा जिम कब क्लोस होता है")
    assert r.step["event"] == "question" and r.step["unclear_as_question"]
    assert "open every day from 6 am to 10 pm" in json.dumps(llm.sent[-1], ensure_ascii=False)
    await turn(a, "सुबह")
    await turn(a, "पाच दिन बाद शुरू कर दूँंगा")          # "पाच" = पाँच without its nasal mark
    assert a.slots["start_days"] == 5 and a.state == "ask_confirm"


# ---------------------------------------------------------------------- fixes from Abhay's third gym call
async def test_hold_on_gets_a_short_sure_and_no_reask():
    a, llm, gym = await gym_agent(ABHAY)
    await turns(a, ["हाँ", "मेरा नाम अभय है"])
    n = len(llm.sent)
    r = await turn(a, "एक सेकंड", heard=False)
    assert r.step["event"] == "hold" and r.spoken == "जी, ज़रूर।" and a.state == "ask_goal"
    assert len(llm.sent) == n                         # no LLM call
    r = await turn(a, "बस फिट रहना जल्दी करो")
    assert a.slots["goal"] == "fitness"


async def test_one_call_for_an_unclear_answer_to_a_cut_off_question():
    reply = "जी, मैं पूछ रहा था, आपका लक्ष्य क्या है?"
    a, llm, _ = await gym_agent(ABHAY, {"intent": "unclear", "reply": reply})
    await turns(a, ["हाँ", "मेरा नाम अभय है"])
    n = len(llm.sent)
    r = await turn(a, "बस पेट रहना", heard=False)
    assert len(llm.sent) == n + 1 and r.spoken == reply       # foreseen with "I was asking", not "unclear"


async def test_a_reply_the_caller_moved_past_is_not_said():
    """Turn 3-4 of the third gym call: the caller answered while the agent was still preparing a re-ask."""
    from laghu_voice.dialog.runner import DialogRunner
    from laghu_voice.obs.trace import TraceWriter

    class FakeSession:
        id, epoch, turns, playing_until_ns = "s", 0, {}, 0
        trace = TraceWriter(None, "s")

        def agent_busy(self, echo_tail_ms=300):
            return False

    said = []

    async def speak(pieces):
        said.append("".join([p async for p in pieces]) if not isinstance(pieces, str) else pieces)
        return f"t{len(said)}"

    async def nothing(*a, **k):
        return None

    gym = load_spec(GYM)
    agent = Agent(gym, None, DialogLLM(Scripted(ABHAY, delay=0.05), gym.agent), "stale")
    speaking = {"now": False}
    runner = DialogRunner(FakeSession(), agent, nothing, speak, nothing, in_caller_turn=lambda: speaking["now"])
    await runner.start()
    await runner.on_caller("हाँ")
    await runner.on_caller("मेरा नाम अभय है")
    n = len(said)
    speaking["now"] = True                              # the caller starts talking again before the reply
    await runner.on_caller("वो देखिए")
    assert len(said) == n                               # nothing said
    speaking["now"] = False
    assert runner._prompt_heard() == (False, 0.0)       # its question counts as not heard
    await runner.close()


def test_question_detection_ignores_filler_kya():
    from laghu_voice.dialog.agent import _asks
    assert _asks("क्या और प्लान है तुम्हारे पास") and _asks("ये बताओ अ तुम्हारा जिम कब क्लोस होता है")
    assert _asks("हाँ क्या तीन दिन का ट्रायल है")
    assert not _asks("वो तो देखिए क्या है ना") and not _asks("पता नहीं क्या बोलूँ")


# ---------------------------------------------------------------------- fixes from Abhay's fourth gym call
async def test_words_written_for_another_intent_are_not_said():
    """Groq said "answer" but gave no name: the engine stays on the name question, so the words Groq wrote for
    the next question must not be said."""
    a, llm, gym = await gym_agent({"intent": "answer", "reply": "अभय जी, आपका फ़िटनेस लक्ष्य क्या है?"})
    await turn(a, "हाँ")
    r = await turn(a, "मैं अभय हूँ")
    assert a.state == "ask_name" and r.step["event"] == "unclear" and r.step["reply_unused"]
    assert "लक्ष्य" not in r.spoken and r.spoken.endswith(gym.lines["ask_name"].example.split("। ")[-1])


async def test_the_same_reask_twice_is_told_to_differ():
    a, llm, _ = await gym_agent(ABHAY)
    await turns(a, ["हाँ", "मेरा नाम अभय है", "मसल्स बनाना", "मासिक", "शाम"])
    await turn(a, "छः या सात दिन")
    first = llm.sent[-1][-1]["content"]
    await turn(a, "छः या सात दिन")
    second = llm.sent[-1][-1]["content"]
    assert "Ask this again" not in first.split("Now say")[1] and "Ask this again" in second.split("Now say")[1]


async def test_asking_for_a_discount_again_gets_the_answer_again():
    a, llm, gym = await gym_agent(ABHAY, {"intent": "discount"})
    await turns(a, ["हाँ", "मेरा नाम अभय है", "मसल्स बनाना", "मासिक", "शाम", "छः दिन", "हज़ार कर दो यार प्लान को"])
    assert a.state == "no_discount"
    r = await turn(a, "हाँ तो मैं एक स्पेशल कस्टमर हूँ मुझे डिस्काउंट मिलना चाहिए")
    assert r.step["event"] == "discount" and a.state == "no_discount" and "समझ नहीं" not in r.spoken
    assert "Ask this again" in llm.sent[-1][-1]["content"]


# ---------------------------------------------------------------------- fixes from the test-sheet calls (gym_test_calls.md)
async def gym_confirm(*answers):
    a, llm, gym = await gym_agent(ABHAY, *answers)
    await turns(a, ["हाँ", "मेरा नाम अभय है", "वज़न कम करना", "तीन महीने वाला सुबह का बैच", "कल से"])
    assert a.state == "ask_confirm"
    return a, llm, gym


async def test_a_yes_after_most_of_the_question_counts_in_the_gym_not_the_loan():
    """Test call 1: "हाँ बुक कर दो" after about 93% of the fee and question got the whole thing again."""
    a, _, _ = await gym_confirm()
    r = await a.handle("हाँ बुक कर दो", prompt_heard=False, heard_fraction=0.93)
    await say_all(a, r)
    assert a.ended == "booked" and not r.step.get("not_heard_guard") and r.step["heard_fraction"] == 0.93
    a, _, _ = await gym_confirm()
    r = await a.handle("हाँ बुक कर दो", prompt_heard=False, heard_fraction=0.5)
    await say_all(a, r)
    assert a.state == "ask_confirm" and r.step["not_heard_guard"]
    loan = load_spec(SPEC)
    assert all(st.require_heard in (0.0, 1.0) for st in loan.states.values())   # the loan stays strict


def test_a_few_seconds_at_the_end_is_hold():
    assert hindi.keyword_intent("हाँ मैं हूँ अः मैं लाइन पर हूँ जस् पाँच सेकंड") == "hold"     # test call 2
    assert hindi.keyword_intent("बस दो मिनट") == "hold"
    assert hindi.keyword_intent("हाँ दो मिनट") is None             # answers "can we talk for two minutes?"
    assert hindi.keyword_intent("एक सेकंड एक सेकंड पहले ये बताओ कितने प्लान हैं तुम्हारे पास") is None


async def test_repeat_says_the_question_without_i_was_asking():
    """Test call 2: "फिर से बोलिए" replayed "जी, मैं पूछ रहा था।" too."""
    a, _, gym = await gym_agent(ABHAY, {"intent": "unclear"})
    await turns(a, ["हाँ", "मेरा नाम अभय है"])
    asked = a._last_said[0]
    r = await turn(a, "अः मैं हूँ", heard=False)                  # unclear, cut off: "I was asking" + the question
    assert r.spoken.startswith(gym.lines["was_asking"].example)
    r = await turn(a, "फिर से बोलिए")
    assert r.spoken == gym.lines["repeat"].text + " " + asked


async def test_a_word_from_the_question_is_not_an_answer_and_two_goals_are_asked_again():
    """Test call 3: "मेरा फिटनेस लक्ष्य वजन भी कर्म करना है और माासल भी बनाना है" was booked as "fitness"
    from the word फिटनेस, which the question itself says."""
    a, _, gym = await gym_agent(ABHAY, {"intent": "answer", "goal": "several"})
    await turns(a, ["हाँ", "मेरा नाम अभय है"])
    r = await turn(a, "तो यार मेरा फिटनेस लक्ष्य वजन भी कर्म करना है और माासल भी बनाना है")
    assert "goal" not in a.slots and r.step["problem"] == "ambiguous" and a.state == "ask_goal"
    assert gym.slots["goal"].llm_schema()["goal"]["enum"][-2] == "several"


async def test_changing_later_is_in_the_facts():
    a, llm, _ = await gym_agent(ABHAY, {"intent": "question"})
    await turns(a, ["हाँ", "मेरा नाम अभय है", "मसल्स बनाना", "सालाना"])
    await turn(a, "मैं श्योर नहीं हूँ तो क्या मैं बाद में बता सकता हूँ")
    assert "front desk" in llm.sent[-1][0]["content"] + llm.sent[-1][-1]["content"]


async def test_a_name_given_with_the_yes_skips_the_name_question():
    """Test call 4: "हाँ हाँ … मेरा नाम अभय है …" at the greeting, then "पहले अपना नाम बताइए"."""
    a, llm, gym = await gym_agent({"intent": "yes", "full_name": "Abhay", "full_name_hi": "अभय"})
    r = await turn(a, "हाँ हाँ मैंने वेबसाइट पर मेंबरशिप में इंट्रेस दिखाया था और मेरा नाम अभय है वो क अः गोवल")
    assert a.slots["full_name"] == "Abhay" and a.state == "ask_goal" and "नाम बताइए" not in r.spoken


async def test_a_count_from_the_knowledge_may_be_said():
    """Test call 4: "हमारे पास तीन प्रकार के प्लान हैं" was rejected for the number 3."""
    said = "अभय जी, हमारे पास तीन प्रकार के प्लान हैं: मासिक, तिमाही और सालाना।"
    a, llm, gym = await gym_agent(ABHAY, {"intent": "question"})
    await turns(a, ["हाँ", "मेरा नाम अभय है"])
    llm.written = [said + " आपका फ़िटनेस लक्ष्य क्या है?"]
    r = await turn(a, "पहले ये बताओ कितने प्लान हैं तुम्हारे पास")
    assert r.spoken.startswith(said) and all(g["ok"] for g in r.step["guard"])


async def test_an_answer_has_no_refusal_to_copy_and_falls_back_to_the_spec_line():
    """Test call 4: Groq copied the answer example (a refusal) word for word."""
    a, llm, gym = await gym_agent(ABHAY, {"intent": "question"})
    await turns(a, ["हाँ", "मेरा नाम अभय है"])
    llm.written = ["आपको सौ प्रतिशत छूट मिलेगी।"]                   # a promise: rejected
    r = await turn(a, "कितने प्लान हैं")
    prompt = llm.sent[-1][-1]["content"]
    assert "पक्की जानकारी मैं अभी नहीं" not in prompt
    assert r.spoken.startswith(gym.lines["question_fallback"].text)


async def test_the_turn_hint_reads_one_word_answers_only():
    a, _, _ = await gym_agent(ABHAY)
    assert not a.turn_complete("हाँ")              # yes/no waits for the turn model ("हाँ… लेकिन")
    await turns(a, ["हाँ", "मेरा नाम अभय है"])
    assert not a.turn_complete("अभय")                                         # names wait for the turn model
    await turns(a, ["मसल्स बनाना", "मासिक"])
    assert a.state == "ask_time" and a.turn_complete("शाम") and not a.turn_complete("सुबह या")
    assert not a.turn_complete("सुबह या शाम")                                # two options: not an answer
    await turn(a, "शाम")
    assert a.turn_complete("परसों") and not a.turn_complete("एक या दो हफ़्ते")
    assert not a.turn_complete("तीन") and a.turn_complete("तीन दिन बाद")     # a bare number may go on
    assert a.slots == {"full_name": "Abhay", "goal": "muscle", "plan": "monthly", "time_slot": "evening"}


async def test_a_short_yes_with_a_name_goes_to_the_llm_for_the_name():
    a, llm, _ = await gym_agent({"intent": "yes", "full_name": "Abhay", "full_name_hi": "अभय"})
    n = len(llm.sent)
    await turn(a, "हाँ हाँ मेरा नाम अभय है")
    assert a.slots["full_name"] == "Abhay" and a.state == "ask_goal" and a._step["path"] == "llm"
    a, llm, _ = await gym_agent()
    await turn(a, "हाँ जी")                                 # a plain yes stays a rule
    assert a.state == "ask_name" and a._step["path"] == "rule"


def test_digits_in_any_script_are_refused():
    """Cache probe call: Groq wrote "मासिक ₹१,५००" (Devanagari digits and a rupee sign); numbers must be words."""
    assert check_answer("मासिक ₹१,५०० है।", {1500.0}).reasons == ["digits"]
    assert check_answer("मासिक 1500 है।", {1500.0}).reasons == ["digits"]
    assert check_answer("मासिक एक हज़ार पाँच सौ रुपये है।", {1500.0}).ok
