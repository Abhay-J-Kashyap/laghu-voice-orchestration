"""Milestone 5: engine defaults, the new slot types, the checker, the setup tool (with a stand-in for the setup
LLM) and the simulator's judge (with stand-ins for both LLMs). No network."""
import json
import re
from datetime import date
from pathlib import Path

import pytest

from laghu_voice.dialog.slots import Slot, read_time
from laghu_voice.dialog.spec import SpecError, build_spec, load_spec
from laghu_voice.setup import simulate as sim
from laghu_voice.setup.tool import approve, run_setup

ROOT = Path(__file__).resolve().parents[1]
GYM = ROOT / "agents" / "gym_onboarding.yaml"
TODAY = date(2026, 11, 21)


# ---------------------------------------------------------------------- a small generated-style spec
def library(**over):
    raw = {
        "agent": {"name": "लघु", "company": "सिटी लाइब्रेरी", "company_en": "City Library", "gender": "male",
                  "persona": "Laghu calls people who asked about library membership and signs them up."},
        "knowledge": {"plans": "2 plans: monthly 200 rupees, yearly 2000 rupees"},
        "slots": {
            "full_name": {"type": "name", "describe": "the caller's name"},
            "plan": {"type": "choice", "describe": "the membership plan",
                     "options": {"monthly": ["मासिक", "महीने वाला"], "yearly": ["सालाना", "साल वाला"]},
                     "labels": {"monthly": "मासिक", "yearly": "सालाना"}, "reask": {"ambiguous": "plan_pick"}}},
        "intents": {},
        "lines": {
            "greeting": "मैं {agent}, {company} से बात कर रहा हूँ। क्या अभी बात हो सकती है?",
            "ask_name": {"llm": "Ask their name.", "example": "आपका नाम क्या है?"},
            "ask_plan": {"llm": "Ask which plan: monthly or yearly.", "example": "आप मासिक प्लान लेंगे या सालाना?"},
            "plan_pick": {"llm": "Ask them to pick one plan.", "example": "कृपया कोई एक प्लान चुनिए।"},
            "confirm": "तो {plan:label} प्लान। क्या मैं इसे बुक कर दूँ?",
            "fix": {"llm": "Ask which detail is wrong.", "example": "कौन सी जानकारी बदलनी है?"},
            "booked": "हो गया! आपकी मेंबरशिप बुक हो गई है। धन्यवाद।"},
        "backend": {"provider": "mock"},
        "tools": {"book": {"commits": True, "mock": [{"outcome": "ok"}],
                           "events": [{"if": {"outcome": "ok"}, "then": "done"}, {"then": "error"}]}},
        "states": {
            "greet": {"say": "greeting", "expect": "yes_no", "also": ["full_name"], "on": {"yes": "ask_name", "no": "goodbye"}},
            "ask_name": {"say": "ask_name", "expect": "full_name", "skip_if": "full_name", "on": {"answer": "ask_plan"}},
            "ask_plan": {"say": "ask_plan", "expect": "plan", "on": {"answer": "confirm"}},
            "confirm": {"say": "confirm", "expect": "yes_no", "corrections": ["plan"],
                        "on": {"yes": "book", "no": "fix", "corrected": "confirm"}},
            "fix": {"say": "fix", "expect": "yes_no", "corrections": ["plan"],
                    "on": {"yes": "confirm", "no": "goodbye", "corrected": "confirm"}},
            "book": {"tool": "book", "on": {"done": "booked", "error": "tech_problem"}},
            "booked": {"say": "booked", "end": "booked", "outcome": "success"}},
        "global": {}}
    for k, v in over.items():
        raw[k] = v
    return raw


def errors_of(raw, generated=True):
    with pytest.raises(SpecError) as e:
        build_spec(raw, generated=generated)
    return str(e.value)


def test_defaults_fill_in_what_a_spec_leaves_out():
    spec = build_spec(library(), generated=True)
    for key in ("unclear", "was_asking", "repeat", "hold_ok", "transfer", "hangup_silence"):
        assert key in spec.lines
    assert spec.states["handover"].tool == "handover" and spec.tools["handover"].mock     # mock hand-over
    assert spec.global_["human"] == "handover" and spec.timing["max_unclear"] == 3
    assert "पूछ रहा था" in spec.lines["was_asking"].example                                # male forms
    assert spec.states["confirm"].require_heard == 0.85                                  # yes leads to a commit
    raw = library(agent={**library()["agent"], "gender": "female"})
    assert "पूछ रही थी" in build_spec(raw, generated=True).lines["was_asking"].example
    gym = load_spec(GYM)                                  # the gym relies on the defaults now
    assert "unclear" in gym.lines and gym.states["hangup_silence"].outcome == "no_contact"


def test_checker_errors_from_milestone_4s_lessons():
    raw = library()
    raw["states"]["booked"].pop("outcome")
    assert "an ending needs an outcome" in errors_of(raw)
    raw = library()
    raw["states"]["ask_plan"]["on"] = {"answer": "book"}                 # books straight after the plan
    assert "which commits, without a yes" in errors_of(raw)
    raw = library()
    raw["lines"]["ask_plan"] = {"llm": "Ask which plan.", "example": "आप कौन सा प्लान लेंगे? मासिक सबसे लोकप्रिय है। मासिक या सालाना?"}
    assert "outside the list of options" in errors_of(raw)
    raw = library()
    raw["lines"]["booked"] = "हो गया! फ़ीस पाँच सौ रुपये है।"            # 500 isn't in the facts
    assert "says 500" in errors_of(raw)
    assert build_spec(raw, generated=False).warnings                    # a person's spec: only a warning
    raw = library(intents={"trial": {"describe": "a trial", "phrases": ["ट्रायल"], "act_directly": True}})
    assert "act_directly isn't allowed" in errors_of(raw)


def test_the_gym_fitness_mistake_is_caught():
    """Gym call 3: the goal question said "फ़िटनेस", which was also a phrase of the fitness option."""
    raw = __import__("yaml").load(GYM.read_text(encoding="utf-8"), Loader=__import__(
        "laghu_voice.dialog.spec", fromlist=["_Loader"])._Loader)
    raw["slots"]["goal"]["options"]["fitness"].append("फ़िटनेस")
    msg = errors_of(raw, generated=False)
    assert "option fitness of goal outside the list" in msg


def test_new_slot_types():
    n = Slot("years", "number", min=0, max=40)
    assert n.parse("तीन साल का", TODAY).value == 3 and n.parse("दो या तीन", TODAY).problem == "range"
    assert n.parse("तीन, नहीं चार", TODAY).value == 4
    assert read_time("कल शाम को") == "1:evening" and read_time("परसों") == "2:any" and read_time("हाँ") is None
    t = Slot("city", "text")
    assert t.from_llm({"city": "Pune", "city_hi": "पुणे"}).value == "Pune" and t.parse("पुणे", TODAY).value is None
    c = Slot("slot", "choice", options={"morning": ["सुबह"], "evening": ["शाम"]})
    assert c.parse("शाम नहीं सुबह", TODAY).value == "morning" and c.parse("सुबह या शाम", TODAY).problem == "ambiguous"
    assert sim.same(Slot("cb", "time"), {"days": 1, "part": "evening"}, "1:evening")
    assert not sim.same(Slot("cb", "time"), {"days": 2, "part": "evening"}, "1:evening")
    assert sim.same(Slot("n", "name"), "Rohit Verma", "Rohit") and not sim.same(Slot("n", "name"), "Rohit", "Amit")


# ---------------------------------------------------------------------- the setup tool, with a stand-in LLM
class FakeSetupLLM:
    """Answers each kind of setup request with the library spec; the first draft has a mistyped target."""
    def __init__(self):
        self.raw = library()
        self.calls = []

    async def complete(self, messages, **kw):
        sys_, user = messages[0]["content"], messages[-1]["content"]
        self.calls.append(sys_[-200:])
        if "what you must ask the owner" in sys_:
            return json.dumps({"questions": ["How much is the yearly plan?"]})
        if "Write the first part" in sys_:
            return json.dumps({k: self.raw[k] for k in ("agent", "knowledge", "slots", "intents")}, ensure_ascii=False)
        if "Write the flow" in sys_:
            states = json.loads(json.dumps(self.raw["states"]))
            states["greet"]["on"]["no"] = "goodby"                             # a mistake for the checker
            needed = {k: {"kind": "llm" if isinstance(v, dict) else "fixed", "purpose": k}
                      for k, v in self.raw["lines"].items()}
            return json.dumps({"states": states, "tools": self.raw["tools"], "global": {}, "lines_needed": needed},
                              ensure_ascii=False)
        if "Write these lines" in sys_:
            keys = json.loads(user.split("LINES TO WRITE:\n", 1)[1])
            out = {}
            for k in keys:
                v = self.raw["lines"][k]
                out[k] = ({"llm": v["llm"], "example": v["example"], "en": f"(English of {k})"} if isinstance(v, dict)
                          else {"text": v, "en": f"(English of {k})"})
            return json.dumps(out, ensure_ascii=False)
        if "Fix the problems" in sys_:
            assert "goodby" in user
            return json.dumps({"states": {"greet": self.raw["states"]["greet"]}}, ensure_ascii=False)
        raise AssertionError(f"unexpected request: {sys_[-120:]}")


async def test_setup_drafts_checks_repairs_and_writes_a_review(tmp_path):
    desc = tmp_path / "library.md"
    desc.write_text("City Library calls people who asked about membership. Monthly 200, yearly 2000.", "utf-8")
    llm = FakeSetupLLM()
    res = await run_setup(desc, tmp_path / "library", llm, None, simulate=False, ask=lambda q: "2000 rupees")
    out = tmp_path / "library"
    assert res["ok"] and res["check_rounds"] == 1
    spec = load_spec(out / "spec.yaml", generated=True)                # what approve installs loads as is
    assert spec.states["booked"].outcome == "success"
    assert json.loads((out / "answers.json").read_text("utf-8")) == [{"q": "How much is the yearly plan?",
                                                                       "a": "2000 rupees"}]
    review = (out / "review.md").read_text("utf-8")
    assert "(English of greeting)" in review and "## The flow" in review and "2000 rupees" in review
    assert "# (English of greeting)" in (out / "spec.yaml").read_text("utf-8")
    agents = tmp_path / "agents"
    agents.mkdir()
    assert approve(out, agents).exists()


# ---------------------------------------------------------------------- the simulator and its judge
class Lines:
    """A caller that says its lines in order."""
    def __init__(self, lines):
        self.lines = list(lines)

    async def complete(self, messages, stats=None, **kw):
        return self.lines.pop(0) if self.lines else "ठीक है धन्यवाद"


class AgentStandIn:
    """The agent's LLM: reads any name as Abhay; writes the examples."""
    async def complete(self, messages, stats=None, **kw):
        return json.dumps({"intent": "answer", "full_name": "Abhay", "full_name_hi": "अभय"})

    async def stream(self, messages, stats=None, **kw):
        for ex in re.findall(r'Example: "([^"]*)"', messages[-1]["content"]):
            yield ex + " "


GYM_FACTS = {"full_name": "Abhay", "goal": "weight_loss", "plan": "monthly", "time_slot": "evening", "start_days": 2}
GYM_CALL = ["हाँ", "मेरा नाम अभय है", "वज़न कम करना", "मासिक", "शाम", "परसों", "हाँ बुक कर दो"]


async def test_a_simulated_call_is_judged_by_code():
    gym = load_spec(GYM)
    p = sim.Persona("P1", "cooperative", "success", sim.KINDS["P1"][2], "Abhay", dict(GYM_FACTS))
    rec, agent, dlm = await sim.run_call(gym, "gym", AgentStandIn(), Lines(GYM_CALL), p, 1, today=TODAY)
    v = sim.judge(gym, rec, agent, dlm)
    assert rec.end == "booked" and rec.outcome == "success" and v["success"], v
    assert set(v["facts"]) == set(GYM_FACTS) and v["safety"] == []
    p2 = sim.Persona("P1", "cooperative", "success", "", "Abhay", {**GYM_FACTS, "plan": "quarterly"})
    rec, agent, dlm = await sim.run_call(gym, "gym", AgentStandIn(), Lines(GYM_CALL), p2, 1, today=TODAY)
    v = sim.judge(gym, rec, agent, dlm)
    assert not v["success"] and v["facts"]["plan"].startswith("wrong")


async def test_a_human_seeker_ends_transferred_and_an_interrupter_cuts_in():
    gym = load_spec(GYM)
    p = sim.Persona("P8", "human-seeker", "transferred", "", "Abhay", dict(GYM_FACTS))
    rec, agent, dlm = await sim.run_call(gym, "gym", AgentStandIn(),
                                         Lines(["हाँ", "मेरा नाम अभय है", "मुझे किसी इंसान से बात करनी है"]), p, 1,
                                         today=TODAY)
    assert rec.outcome == "transferred" and sim.judge(gym, rec, agent, dlm)["success"]
    p6 = sim.Persona("P6", "interrupter", "success", "", "Abhay", dict(GYM_FACTS))
    rec, agent, dlm = await sim.run_call(gym, "gym", AgentStandIn(), Lines(GYM_CALL), p6, 1, today=TODAY)
    assert any(h is not None for w, _, h in rec.transcript if w == "agent")      # some replies were cut off
    assert any(s.startswith("[The caller cut in") for s in agent.history) or rec.steps


def test_caller_text_is_cleaned_like_speech_recognition():
    assert sim.clean_caller_text("हाँ, मेरा बजट 15000 है!") == "हाँ मेरा बजट पंद्रह हज़ार है"


# ---------------------------------------------------------------------- what the first real run showed
def test_normalize_fixes_what_the_model_keeps_missing():
    from laghu_voice.setup.tool import normalize, spell_acronyms
    raw = library()
    raw["states"]["goodbye_decline"] = {"say": "booked", "end": "caller declined"}
    raw["states"]["goodbye_callback_scheduled"] = {"say": "booked", "end": "callback arranged"}
    raw["slots"]["plan"]["reask"] = {"ambiguous": "कृपया कोई एक प्लान चुनिए।"}
    raw["lines"]["booked"] = "आपका एमबीए {plan:label} बुक हो गया। MBA काउंसलिंग।"
    raw2, en = normalize(raw, {})
    assert raw2["states"]["goodbye_decline"]["outcome"] == "declined"
    assert raw2["states"]["goodbye_callback_scheduled"]["outcome"] == "success"
    key = raw2["slots"]["plan"]["reask"]["ambiguous"]
    assert key in raw2["lines"] and raw2["lines"][key] == "कृपया कोई एक प्लान चुनिए।"
    assert "एमबीए" in raw2["lines"]["booked"] and "MBA" not in raw2["lines"]["booked"]
    assert "{plan:label}" in raw2["lines"]["booked"]
    assert spell_acronyms("{agent} की MBA") == "{agent} की एमबीए"
    assert raw["states"]["goodbye_decline"].get("outcome") is None        # the input is untouched


def test_an_intent_may_hand_over_without_a_question():
    raw = library()
    raw["intents"] = {"scholarship": {"describe": "asks about a scholarship", "phrases": ["स्कॉलरशिप"]}}
    raw["lines"]["scholarship_line"] = {"llm": "Say a counsellor will help with that.", "example": "इसमें हमारी टीम मदद करेगी।"}
    raw["states"]["scholarship_help"] = {"say": "scholarship_line", "next": "handover"}
    raw["global"] = {"scholarship": "scholarship_help"}
    build_spec(raw, generated=True)                     # no error: a hand-over doesn't commit anything
    raw["global"] = {"scholarship": "book"}             # but a booking straight from a passing word does
    assert "without asking" in errors_of(raw)


def test_the_shape_error_names_the_slot_and_a_repair_keeps_the_rest():
    from laghu_voice.setup.tool import Drafter

    raw = library()
    del raw["slots"]["plan"]["type"]
    assert "slot plan: needs 'type'" in errors_of(raw)

    class Reply:
        async def complete(self, messages, **kw):
            return json.dumps({"slots": {"plan": {"describe": "the plan they want"}},
                               "states": {"booked": {"outcome": "success"}}})
    d = Drafter(Reply(), "x", [])
    import asyncio
    fixed, _ = asyncio.run(d.patch(library(), {}, ["x"], "PROBLEMS"))
    assert fixed["slots"]["plan"]["type"] == "choice" and fixed["slots"]["plan"]["describe"] == "the plan they want"
    assert fixed["states"]["booked"]["end"] == "booked"


def test_outcome_guess_never_calls_a_negated_ending_a_success():
    from laghu_voice.setup.tool import guess_outcome
    assert guess_outcome("goodbye_success", "booked") == "success"
    assert guess_outcome("callback_scheduled", "x") == "success"
    assert guess_outcome("x", "y", "completed") == "success"                  # a wrong outcome word
    assert guess_outcome("goodbye_decline", "caller declined") == "declined"
    assert guess_outcome("escalate_scholarship", "x") == "transferred"
    assert guess_outcome("silence_end", "x") == "no_contact"
    assert guess_outcome("no_booking", "x") is None
    assert guess_outcome("end", "not confirmed") is None
    assert guess_outcome("unconfirmed_end", "x") is None
    assert guess_outcome("booking_cancelled", "x") is None
    assert guess_outcome("goodbye", "bye") is None                            # no guess: the checker asks


def test_every_shape_error_is_reported_at_once():
    raw = library()
    del raw["slots"]["plan"]["type"]
    raw["states"]["ask_plan"]["nxt"] = "x"
    raw["slots"]["full_name"]["name"] = "full_name"                          # a repeated name is fine
    msg = errors_of(raw)
    assert "slot plan: needs 'type'" in msg and "state ask_plan: unknown keys ['nxt']" in msg
    assert "full_name" not in msg


def test_only_the_handover_may_follow_a_passing_word():
    raw = library()
    raw["intents"] = {"brochure": {"describe": "wants a brochure", "phrases": ["ब्रोशर"]}}
    raw["tools"]["send_brochure"] = {"mock": [{"outcome": "ok"}], "events": [{"then": "sent"}]}
    raw["states"]["brochure"] = {"tool": "send_brochure", "on": {"sent": "booked"}}
    raw["global"] = {"brochure": "brochure"}
    assert "intent brochure leads to the tool send_brochure without asking" in errors_of(raw)


def test_repairs_merge_partial_tools_and_keep_english_of_lines_named_like_states():
    import asyncio

    from laghu_voice.setup.tool import Drafter

    class Reply:
        async def complete(self, messages, **kw):
            return json.dumps({"tools": {"book": {"commits": True}}, "states": {"fix": None}})
    fixed, en = asyncio.run(Drafter(Reply(), "x", []).patch(library(), {"fix": "Which detail?"}, ["x"], "P"))
    assert fixed["tools"]["book"]["mock"] and fixed["tools"]["book"]["commits"]
    assert "fix" not in fixed["states"] and en["fix"] == "Which detail?"


def test_acronyms_next_to_hindi_and_in_caller_phrases():
    from laghu_voice.setup.tool import normalize, spell_acronyms
    assert spell_acronyms("MBAकी फ़ीस") == "एमबीएकी फ़ीस"
    raw = library()
    raw["slots"]["plan"]["options"]["yearly"].append("MBA")
    raw["intents"] = {"eligibility": {"describe": "x", "phrases": ["CAT स्कोर"]}}
    out, _ = normalize(raw, {})
    assert "एमबीए" in out["slots"]["plan"]["options"]["yearly"]
    assert out["intents"]["eligibility"]["phrases"] == ["सीएटी स्कोर"]


async def test_the_mba_runs_errors_are_fixed_by_code_or_named_for_the_model(tmp_path):
    """The errors the first real run (gpt-oss-120b, mba.md) couldn't repair, rebuilt on the library spec."""
    from laghu_voice.setup.tool import check_raw, normalize
    raw = library()
    raw["slots"]["plan"]["reask"] = {"ambiguous": "कृपया बताइए आप कौन सा प्लान चाहते हैं?"}
    raw["lines"]["ask_plan"]["example"] = "आप Online या MBA प्लान लेंगे?"
    raw["intents"] = {"scholarship_query": {"describe": "asks about scholarships", "phrases": ["स्कॉलरशिप"]}}
    raw["lines"]["scholarship_line"] = {"llm": "Say a counsellor will help.", "example": "इसमें काउंसलर मदद करेंगे।"}
    raw["states"]["scholarship_help"] = {"say": "scholarship_line", "next": "handover"}
    raw["global"] = {"scholarship_query": "scholarship_help"}
    raw["states"]["booked"].pop("outcome")
    raw["states"]["goodbye_decline"] = {"say": "booked", "end": "caller declined"}
    raw["states"]["greet"]["on"]["no"] = "goodbye_decline"
    fixed, _ = normalize(raw, {})
    errors, _, _ = check_raw(fixed)
    assert errors == ["line ask_plan: has English letters ['Online'] (Laghu drops them; write each in Devanagari, "
                      "an acronym as its letters: MBA -> एमबीए)",
                      "line ask_plan: asks for plan without naming its options"]     # an error in generated specs


# ---------------------------------------------------------------------- what the second real run showed
def test_a_mock_that_can_match_nothing_is_an_error_or_fixed_by_code():
    from laghu_voice.setup.tool import normalize
    raw = library()
    raw["tools"]["book"]["mock"] = [{"if": {"plan": "मासिक"}, "outcome": "ok"}]       # a label, and no catch-all
    out, _ = normalize(raw, {})
    assert out["tools"]["book"]["mock"] == [{"if": {"plan": "monthly"}, "outcome": "ok"}, {"outcome": "ok"}]
    build_spec(out, generated=True)
    raw["tools"]["book"]["save"] = {"ref": "data.ref"}                          # saves data: no answer invented
    raw["tools"]["book"]["mock"] = [{"if": {"plan": "gold"}, "outcome": "ok", "data": {"ref": "x"}}]
    msg = errors_of(raw)
    assert "if plan = ['gold'] never matches" in msg and "end the mock list with an answer without" in msg
    raw["tools"]["book"]["mock"] = [{"if": {"plan": "monthly"}, "data": {"ref": "a"}},
                                    {"if": {"plan": "yearly"}, "data": {"ref": "b"}}]
    build_spec(raw, generated=True)                                            # every option covered: fine


def test_option_keys_written_as_placeholders_become_labels():
    from laghu_voice.setup.tool import normalize
    raw = library()
    raw["lines"]["ask_plan"]["example"] = "आप {monthly} लेंगे या {yearly}? {plan:label}"
    out, _ = normalize(raw, {})
    # option keys become their labels; the value being asked (still empty then) becomes the options in words
    assert out["lines"]["ask_plan"]["example"] == "आप मासिक लेंगे या सालाना? मासिक या सालाना"


def test_a_cut_off_json_reply_is_asked_again_without_json_mode():
    from laghu_voice.services.llm_openai import LLMError
    from laghu_voice.setup.tool import complete_json

    class Groq:
        def __init__(self):
            self.kw = []

        async def complete(self, messages, **kw):
            self.kw.append(kw)
            if "response_format" in kw:
                raise LLMError('HTTP 400: {"error":{"code":"json_validate_failed"}}', 400)
            return 'Here: {"a": 1}'
    g = Groq()
    import asyncio
    assert asyncio.run(complete_json(g, [{"role": "user", "content": "x"}], 1000)) == 'Here: {"a": 1}'
    assert "response_format" not in g.kw[1]


class SetupWithCalls(FakeSetupLLM):
    """Personas, callers who all ask for a person (so P1-P7 fail), and a repair that never returns JSON."""
    async def complete(self, messages, **kw):
        sys_ = messages[0]["content"]
        if "You write test callers" in sys_:
            return json.dumps({"personas": [{"id": f"P{i}", "name": "Abhay", "facts": {"full_name": "Abhay",
                                                                                       "plan": "monthly"}}
                                            for i in range(1, 9)]})
        if "You are a caller" in sys_:
            return "मुझे किसी इंसान से बात करनी है"
        if "TEST CALLS THAT FAILED" in messages[-1]["content"]:
            from laghu_voice.services.llm_openai import LLMError
            if "response_format" in kw:
                raise LLMError('HTTP 400: {"error":{"code":"json_validate_failed"}}', 400)
            return "sorry, the reply was cut"
        return await super().complete(messages, **kw)


async def test_a_failed_repair_keeps_the_spec_and_every_call_is_saved(tmp_path):
    desc = tmp_path / "library.md"
    desc.write_text("City Library calls people who asked about membership. Monthly 200, yearly 2000.", "utf-8")
    res = await run_setup(desc, tmp_path / "lib", SetupWithCalls(), AgentStandIn(), simulate=True,
                          ask=lambda q: "2000 rupees")
    out = tmp_path / "lib"
    calls = [json.loads(x) for x in (out / "test_calls.jsonl").read_text("utf-8").splitlines()]
    assert len(calls) == 8 and res["test_calls"] == 8 and res["passed"] == 1           # only P8 wanted a person
    review = (out / "review.md").read_text("utf-8")
    assert "test-call repair 1 failed" in review and (out / "spec.yaml").exists()
    from laghu_voice.setup.tool import failure_report, how_it_ended
    failed = [c for c in calls if not c["verdict"]["success"]]
    assert "went" in how_it_ended(failed[0]) and "transfer" in how_it_ended(failed[0])
    report = failure_report(failed)
    assert len(report) < len(failed) and "went wrong the same way" in report[0]


# ---------------------------------------------------------------------- what the third real run showed
SUNDAY = date(2026, 11, 22)


def test_a_day_for_an_appointment_is_read_or_left_to_the_llm_never_today_by_mistake():
    from laghu_voice.dialog.slots import read_time, time_words
    assert read_time("पाँच दिसंबर सुबह", SUNDAY) == "13:morning"
    assert read_time("शनिवार दोपहर", SUNDAY) == "6:afternoon"
    assert read_time("अगले सोमवार सुबह", SUNDAY) == "1:morning"
    assert read_time("दस तारीख शाम", SUNDAY) == "18:evening"                  # the 10th has passed: next month
    assert read_time("कल सुबह दस बजे", SUNDAY) == "1:morning"
    assert read_time("परसों दो बजे", SUNDAY) == "2:afternoon"                  # an hour gives the part
    assert read_time("शाम को", SUNDAY) == "0:evening"                          # no day said: today
    assert read_time("दिसंबर में कभी", SUNDAY) is None                          # a day said, not understood
    assert time_words("13:morning", SUNDAY) == "शनिवार, पाँच दिसंबर सुबह"
    assert time_words("1:evening", SUNDAY) == "कल, सोमवार, तेईस नवंबर, शाम"
    s = Slot("session", "time", min=0, max=14)
    assert s.parse("बीस दिसंबर शाम", SUNDAY).problem == "out_of_range"
    assert s.from_llm({"session_days": 30, "session_part": "morning"}).problem == "out_of_range"


def test_hyphens_split_words_and_dont_know_is_not_a_denial():
    s = Slot("program", "choice", options={"full_time": ["पूरा‑समय एमबीए"], "executive": ["एक्जीक्यूटिव एमबीए"]})
    said = "पूरा समय एमबीए और एक्जीक्यूटिव एमबीए नहीं पता कौन चुनूँ"          # P3, run 2
    assert s.parse(said, SUNDAY).problem == "ambiguous"                         # was recorded as "executive"
    t = Slot("slot", "choice", options={"m": ["सुबह"], "e": ["शाम"]})
    assert t.parse("शाम नहीं, सुबह", SUNDAY).value == "m"                       # a real denial still counts


def test_amounts_written_in_english_facts_may_be_said():
    from laghu_voice.dialog import hindi
    from laghu_voice.dialog.guard import check_answer
    allowed = hindi.fact_numbers("8.5 lakh rupees")
    assert 850000 in allowed
    assert check_answer("फुल टाइम एमबीए की फीस साढ़े आठ लाख रुपये है।", allowed).ok


def test_what_a_line_would_say_wrongly_is_an_error():
    raw = library()
    raw["slots"]["day"] = {"type": "date", "describe": "the day of the session"}
    raw["lines"]["booked"] = "हो गया! तीस मिनट का सत्र, सुबह 10 बजे। {plan}"
    raw["states"]["ask_plan"] = {"say": "ask_plan", "next": "confirm"}
    msg = errors_of(raw)
    assert "line booked: has digits" in msg and "{plan} needs a format: {plan:label}" in msg
    assert "state ask_plan: its line asks a question but the state doesn't wait" in msg
    assert "slot day: a date slot is only for a date of birth" in msg


def test_digits_formats_and_hyphens_are_fixed_by_code():
    from laghu_voice.setup.tool import digits_to_words, normalize
    assert digits_to_words("मुफ्त 30 मिनट, सुबह 10 बजे, 8.5 लाख, 1.5 घंटे, {x:words}") == \
        "मुफ्त तीस मिनट, सुबह दस बजे, साढ़े आठ लाख, डेढ़ घंटे, {x:words}"
    raw = library()
    raw["slots"]["when"] = {"type": "time", "describe": "the session", "max": 14}
    raw["lines"]["booked"] = "पूरा‑समय {plan} का सत्र {when} को, 30 मिनट।"
    out, _ = normalize(raw, {})
    assert out["lines"]["booked"] == "पूरा समय {plan:label} का सत्र {when:time} को, तीस मिनट।"


MBA = {
    "agent": {"name": "लघु", "company": "नॉर्थब्रिज", "company_en": "Northbridge", "gender": "male",
              "persona": "Laghu calls MBA enquiries and books a free counselling session."},
    "knowledge": {"fee": "Full-time MBA fee 8.5 lakh rupees"},
    "slots": {
        "program": {"type": "choice", "describe": "the program",
                    "options": {"full_time": ["पूरा‑समय एमबीए", "फुल टाइम"], "executive": ["एक्जीक्यूटिव एमबीए"],
                                "online": ["ऑनलाइन एमबीए", "ऑनलाइन"]},
                    "labels": {"full_time": "पूरा समय एमबीए", "executive": "एक्जीक्यूटिव एमबीए",
                               "online": "ऑनलाइन एमबीए"}, "reask": {"ambiguous": "pick"}},
        "session": {"type": "time", "describe": "the day and part of the day for the session", "max": 14}},
    "intents": {"scholarship": {"describe": "asks about scholarships", "phrases": ["स्कॉलरशिप"]}},
    "lines": {
        "greeting": "मैं {agent}, {company} से बात कर रहा हूँ। क्या अभी बात हो सकती है?",
        "ask_program": {"llm": "Ask which program.", "example": "आप पूरा समय एमबीए, एक्जीक्यूटिव एमबीए या ऑनलाइन एमबीए में से कौन सा लेंगे?"},
        "pick": {"llm": "Ask them to pick one.", "example": "कृपया कोई एक चुनिए।"},
        "offer": {"llm": "Offer a free counselling session.", "example": "क्या मैं आपके लिए मुफ्त काउंसलिंग सत्र बुक कर दूँ?"},
        "ask_session": {"llm": "Ask the day and time.", "example": "किस दिन और किस समय आपके लिए ठीक रहेगा?"},
        "readback": "तो {program:label}, सत्र {session:time}। क्या यह सही है?",
        "fix": {"llm": "Ask what to change.", "example": "क्या बदलना है?"},
        "scholarship_line": {"llm": "Say a counsellor will help with scholarships.", "example": "स्कॉलरशिप के बारे में काउंसलर बताएँगे।"},
        "booked": "हो गया, आपका सत्र बुक हो गया है। धन्यवाद।"},
    "backend": {"provider": "mock"},
    "tools": {"book": {"commits": True, "mock": [{"outcome": "ok"}],
                       "events": [{"if": {"outcome": "ok"}, "then": "done"}, {"then": "error"}]}},
    "states": {
        "greet": {"say": "greeting", "expect": "yes_no", "on": {"yes": "ask_program", "no": "goodbye"}},
        "ask_program": {"say": "ask_program", "expect": "program", "on": {"answer": "offer"}},
        "offer": {"say": "offer", "expect": "yes_no", "on": {"yes": "ask_session", "no": "goodbye"}},
        "ask_session": {"say": "ask_session", "expect": "session", "on": {"answer": "confirm"}},
        "confirm": {"say": "readback", "expect": "yes_no", "corrections": ["program", "session"],
                    "on": {"yes": "book", "no": "fix", "corrected": "confirm"}},
        "fix": {"say": "fix", "expect": "yes_no", "corrections": ["program", "session"],
                "on": {"yes": "confirm", "no": "goodbye", "corrected": "confirm"}},
        "book": {"tool": "book", "on": {"done": "booked", "error": "tech_problem"}},
        "booked": {"say": "booked", "end": "booked", "outcome": "success"},
        "scholarship_help": {"say": "scholarship_line", "next": "back"}},
    "global": {"scholarship": "scholarship_help"}}


async def test_the_mba_callers_own_words_now_reach_the_booking():
    import copy
    spec = build_spec(copy.deepcopy(MBA), generated=True)
    facts = {"program": "full_time", "session": {"days": 13, "part": "morning"}}
    p1 = sim.Persona("P1", "cooperative", "success", "", "Aarav", facts)
    words = ["हाँ मैं बात कर सकता हूँ", "पूरा समय एमबीए", "हाँ", "पाँच दिसंबर सुबह ठीक रहेगा", "हाँ"]   # P1's words
    rec, agent, dlm = await sim.run_call(spec, "mba", AgentStandIn(), Lines(words), p1, 1, today=SUNDAY)
    v = sim.judge(spec, rec, agent, dlm)
    assert rec.outcome == "success" and v["success"] and v["safety"] == [], (rec.transcript, v)
    assert any("शनिवार, पाँच दिसंबर सुबह" in t for w, t, _ in rec.transcript if w == "agent")
    assert dlm.first_token_timeout_s >= 60 and dlm.timeout_s >= 60       # pacing waits aren't a timeout
    p5 = sim.Persona("P5", "questioner", "success", "", "Vikram", facts)
    words = ["हाँ", "क्या स्कॉलरशिप मिलती है", "पूरा समय एमबीए", "हाँ", "शनिवार सुबह", "हाँ"]
    rec, agent, dlm = await sim.run_call(spec, "mba", AgentStandIn(), Lines(words), p5, 1, today=SUNDAY)
    assert rec.outcome == "success", rec.transcript                     # the scholarship detour comes back


def test_the_caller_knows_today_and_the_day_it_wants():
    import copy
    spec = build_spec(copy.deepcopy(MBA), generated=True)
    p = sim.Persona("P1", "cooperative", "success", "", "Aarav", {"session": {"days": 13, "part": "morning"}})
    c = sim.Caller(Lines([]), spec, p, SUNDAY)
    assert "Today is Sunday 22 November 2026" in c.system and "Saturday 5 December" in c.system


class SetupNoProgress(SetupWithCalls):
    """The repair returns valid JSON that changes nothing that matters, so round 2 fails like round 1."""
    async def complete(self, messages, **kw):
        if "TEST CALLS THAT FAILED" in messages[-1]["content"]:
            return json.dumps({"lines": {"booked": {"text": "हो गया! आपकी मेंबरशिप बुक हो गई है।", "en": "Done."}}},
                              ensure_ascii=False)
        return await super().complete(messages, **kw)


async def test_repairs_stop_when_they_change_nothing(tmp_path):
    desc = tmp_path / "library.md"
    desc.write_text("City Library calls people who asked about membership. Monthly 200, yearly 2000.", "utf-8")
    res = await run_setup(desc, tmp_path / "lib", SetupNoProgress(), AgentStandIn(), simulate=True,
                          ask=lambda q: "2000 rupees")
    review = (tmp_path / "lib" / "review.md").read_text("utf-8")
    assert "didn't change how any call failed" in review
    assert "test calls, round 3" not in review


def test_reasoning_settings_fit_each_model_and_thinking_is_stripped():
    from laghu_voice.setup.tool import parse_obj, reasoning_params
    assert reasoning_params("openai/gpt-oss-120b", "low") == {"reasoning_effort": "low", "include_reasoning": False}
    assert reasoning_params("qwen/qwen3.8-27b", "low") == {"reasoning_effort": "low", "reasoning_format": "hidden"}
    assert reasoning_params("qwen/qwen3.8-27b", "none")["reasoning_effort"] == "none"
    assert parse_obj('<think>{"x": 2} hmm</think>\n{"a": 1}') == {"a": 1}
    assert sim.clean_caller_text(__import__("laghu_voice.setup.tool", fromlist=["x"]).strip_thinking(
        "<think>I should say yes</think>हाँ ठीक है")) == "हाँ ठीक है"


async def test_an_empty_reply_is_asked_again_with_thinking_off(tmp_path):
    from laghu_voice.setup.tool import Drafter

    class Qwen:
        model = "qwen/qwen3.8-27b"

        def __init__(self):
            self.kw = []

        async def complete(self, messages, stats=None, **kw):
            self.kw.append(kw)
            if kw.get("reasoning_effort") != "none":
                stats.finish_reason = "length"                 # the thinking used every token
                return ""
            return '{"questions": ["How much is it?"]}'
    q = Qwen()
    assert await Drafter(q, "x", []).questions() == ["How much is it?"]
    assert len(q.kw) == 2 and q.kw[1]["reasoning_effort"] == "none"


async def test_the_last_runs_files_are_set_aside(tmp_path):
    out = tmp_path / "lib"
    out.mkdir()
    (out / "review.md").write_text("old", "utf-8")
    (out / "answers.json").write_text("[]", "utf-8")
    desc = tmp_path / "library.md"
    desc.write_text("City Library calls people who asked about membership. Monthly 200, yearly 2000.", "utf-8")
    await run_setup(desc, out, FakeSetupLLM(), None, simulate=False, ask=lambda q: "2000 rupees")
    assert (out / "review.md").read_text("utf-8") != "old"
    assert [p.read_text("utf-8") for p in (out / "previous").glob("*/review.md")] == ["old"]


def test_a_qwen_caller_asks_for_few_tokens():
    import copy
    spec = build_spec(copy.deepcopy(MBA), generated=True)
    p = sim.Persona("P1", "cooperative", "success", "", "Aarav", {})

    class Qwen(Lines):
        model = "qwen/qwen3.8-27b"
    assert sim.Caller(Qwen([]), spec, p, SUNDAY).max_tokens == 150
    assert sim.Caller(Lines([]), spec, p, SUNDAY).max_tokens == 400


# ---------------------------------------------------------------------- the 2026-11-22 13:00 run (gpt-oss-120b)
MBA_SPEC = ROOT / "tests" / "fixtures" / "mba_spec_2026-11-22.yaml"


class Reads:
    """The agent's LLM, reading each caller turn as a correct reader would: {caller words: extraction}."""
    def __init__(self, readings: dict):
        self.readings = readings
        self.asked = []

    async def complete(self, messages, stats=None, **kw):
        from laghu_voice.dialog import hindi
        said = re.search(r'Caller said: "(.*)"', messages[-1]["content"]).group(1)
        self.asked.append(said)
        by_norm = {hindi.norm(k): v for k, v in self.readings.items()}
        return json.dumps(by_norm.get(hindi.norm(said), {"intent": "unclear"}), ensure_ascii=False)

    async def stream(self, messages, stats=None, **kw):
        for ex in re.findall(r'Example: "([^"]*)"', messages[-1]["content"]):
            yield ex + " "


async def mba_call(words: list[str], readings: dict, facts: dict, pid="P1"):
    spec = load_spec(MBA_SPEC, generated=True)
    p = sim.Persona(pid, "x", "success", "", "x", facts)
    llm = Reads(readings)
    rec, agent, dlm = await sim.run_call(spec, "mba", llm, Lines(words), p, 1, today=SUNDAY)
    return rec, agent, llm


async def test_a_yes_with_the_day_books_straight_away():
    """P1, run 2: "हां बुक कर दो बुधवार पच्चीस नवंबर सुबह" at the offer was unclear three times, then a hand-over."""
    rec, agent, llm = await mba_call(
        ["हाँ बात कर सकता हूँ", "फुल टाइम एमबीए", "जुलाई", "दो साल", "पुणे", "हां बुक कर दो बुधवार पच्चीस नवंबर सुबह",
         "हाँ"],
        {"पुणे": {"intent": "answer", "city": "Pune", "city_hi": "पुणे"},
         "हां बुक कर दो बुधवार पच्चीस नवंबर सुबह": {"intent": "answer", "session_time_days": 3,
                                                   "session_time_part": "morning"}},
        {"program": "full_time", "intake": "july", "work_exp": 2, "city": "Pune",
         "session_time": {"days": 3, "part": "morning"}})
    assert rec.outcome == "success" and agent.slots["session_time"] == "3:morning", rec.transcript
    said = [t for w, t, _ in rec.transcript if w == "agent"]
    assert not any("बताइए" in t and "चौदह" in t for t in said)            # the day wasn't asked again
    assert any("बुधवार, पच्चीस नवंबर सुबह" in t for t in said)             # read back as the day itself


async def test_a_yes_the_llm_cant_place_is_still_a_yes():
    """P3: "हां बात कर सकता हूँ आप बताइए क्या चाहिए" was unclear three times at the greeting."""
    rec, agent, llm = await mba_call(["हां बात कर सकता हूँ आप बताइए क्या चाहिए"], {}, {})
    assert "ask_program" in rec.visited and llm.asked                   # the LLM was asked, and couldn't place it


async def test_details_instead_of_a_yes_are_kept_and_not_asked_again():
    """P2: the over-answerer's details at the greeting were unclear three times, then a hand-over."""
    said = "हाय मैं नेहा वर्मा मुंबई से पाँच साल का एक्सपीरियंस एक्जीक्यूटिव एमबीए जुलाई"
    rec, agent, llm = await mba_call(
        [said, "मंगलवार चौबीस नवंबर शाम", "हाँ"],
        {said: {"intent": "answer", "name": "Neha Verma", "name_hi": "नेहा वर्मा", "city": "Mumbai",
                "city_hi": "मुंबई", "work_exp": 5, "program": "executive", "intake": "july"},
         "हाँ": {"intent": "yes"}, "मंगलवार चौबीस नवंबर शाम": {"intent": "answer"}},
        {"program": "executive", "intake": "july", "work_exp": 5, "city": "Mumbai",
         "session_time": {"days": 2, "part": "evening"}}, pid="P2")
    assert agent.slots["program"] == "executive" and agent.slots["work_exp"] == 5 and agent.slots["city"] == "Mumbai"
    asked = [t for w, t, _ in rec.transcript if w == "agent"]
    assert not any("कितने साल" in t or "किस शहर" in t or "किस एमबीए प्रोग्राम" in t for t in asked)
    assert "offer_session" in rec.visited


async def test_asking_for_what_is_offered_is_a_yes_not_a_loop():
    """P6: "हां दो दिन बाद दोपहर में कॉल बैक कर दो" at "would you like a callback?" went to the same question 30 times."""
    said = "हां दो दिन बाद दोपहर में कॉल बैक कर दो"
    rec, agent, llm = await mba_call(
        ["अभी नहीं बाद में कॉल बैक करना", said, "हाँ"],
        {"अभी नहीं बाद में कॉल बैक करना": {"intent": "callback_request"},
         said: {"intent": "callback_request", "callback_time_days": 2, "callback_time_part": "afternoon"}},
        {"callback_time": {"days": 2, "part": "afternoon"}}, pid="P6")
    assert rec.outcome == "success" and rec.end == "callback_scheduled", rec.transcript
    assert agent.slots["callback_time"] == "2:afternoon"


async def test_no_call_goes_round_in_circles():
    """A request routed back to the question it came from, again and again: a hand-over after three."""
    gym = load_spec(GYM)
    a = sim.Persona("P1", "x", "success", "", "Abhay", {})
    words = ["हाँ", "मेरा नाम अभय है", "मसल्स बनाना", "मासिक", "शाम", "छः दिन"] + \
        ["हज़ार कर दो यार प्लान को", "डिस्काउंट दो ना", "डिस्काउंट चाहिए", "डिस्काउंट दो", "बस डिस्काउंट दे दो"]
    rec, agent, dlm = await sim.run_call(gym, "gym", AgentStandIn(), Lines(words), a, 1, today=TODAY)
    assert rec.outcome == "transferred" and any(s.get("stuck") for s in rec.steps), rec.transcript


async def test_drafting_resumes_after_the_daily_limit(tmp_path):
    from laghu_voice.services.paced import DailyLimit

    class Limited(FakeSetupLLM):
        def __init__(self, stop_at_lines):
            super().__init__()
            self.stop_at_lines = stop_at_lines
            self.kinds = []

        async def complete(self, messages, **kw):
            sys_ = messages[0]["content"]
            kind = next((k for k in ("Write the first part", "Write the flow", "Write these lines") if k in sys_), None)
            self.kinds.append(kind)
            if kind == "Write these lines" and self.stop_at_lines:
                raise DailyLimit("tokens per day")
            return await super().complete(messages, **kw)
    desc = tmp_path / "library.md"
    desc.write_text("City Library calls people who asked about membership. Monthly 200, yearly 2000.", "utf-8")
    first = Limited(stop_at_lines=True)
    with pytest.raises(DailyLimit):
        await run_setup(desc, tmp_path / "lib", first, None, simulate=False, ask=lambda q: "2000 rupees")
    second = Limited(stop_at_lines=False)
    res = await run_setup(desc, tmp_path / "lib", second, None, simulate=False, ask=lambda q: "2000 rupees")
    assert "Write the first part" not in second.kinds and "Write the flow" not in second.kinds
    assert "Write these lines" in second.kinds and res["ok"] is not None
    third = Limited(stop_at_lines=True)                 # everything kept now: no drafting request at all
    await run_setup(desc, tmp_path / "lib", third, None, simulate=False, ask=lambda q: "2000 rupees")
    assert not {"Write the first part", "Write the flow", "Write these lines"} & set(third.kinds)


# ---------------------------------------------------------------------- the 2026-11-22 23:30 run (gpt-oss-120b)
MBA_SPEC_B = ROOT / "tests" / "fixtures" / "mba_spec_2026-11-22b.yaml"


def mba_b(fix_ending=True):
    import yaml
    raw = yaml.safe_load(MBA_SPEC_B.read_text(encoding="utf-8"))
    if fix_ending:                                # the run's "booked" line asked "is this correct?" after the booking
        raw["lines"]["booked"] = raw["lines"]["booked"].replace(" क्या यह सही है?", "")
    return build_spec(raw, generated=True)


def test_an_ending_that_asks_a_question_is_an_error():
    import yaml
    raw = yaml.safe_load(MBA_SPEC_B.read_text(encoding="utf-8"))
    with pytest.raises(SpecError, match="state booked: the call ends after its line"):
        build_spec(raw, generated=True)


async def b_call(words, readings, facts, pid="P1"):
    p = sim.Persona(pid, "x", "success", "", "x", facts)
    llm = Reads(readings)
    rec, agent, dlm = await sim.run_call(mba_b(), "mba", llm, Lines(words), p, 1, today=SUNDAY)
    return rec, agent


async def test_no_experience_is_zero_years():
    """P3: "मेरे पास कोई कार्य अनुभव नहीं है" was unclear three times (only a number above 0 was taken)."""
    said = "मेरे पास कोई कार्य अनुभव नहीं है"
    rec, agent = await b_call(["जी हाँ", "ऑनलाइन एमबीए", "जनवरी इंटेक", said],
                              {said: {"intent": "answer", "experience": 0}, "जी हाँ": {"intent": "yes"}}, {})
    assert agent.slots.get("experience") == 0 and "ask_city" in rec.visited


async def test_a_correction_only_the_llm_can_read_is_taken_at_the_read_back():
    """P2: "नहीं गलत है शुक्रवार सत्ताईस नवंबर शाम" at the read-back: the rules can't read 'शाम को मिलना है' around
    it here, the LLM can; before, the LLM was asked only yes or no."""
    fix = "नहीं गलत है मुझे शुक्रवार वाला दिन चाहिए शाम को"
    rec, agent = await b_call(
        ["हाँ जी", "एक्जीक्यूटिव एमबीए", "जुलाई", "पाँच साल", "मुंबई", "हाँ", "बुधवार शाम", fix, "हाँ"],
        {"हाँ जी": {"intent": "yes"}, "मुंबई": {"intent": "answer", "city": "Mumbai", "city_hi": "मुंबई"},
         fix: {"intent": "no", "appointment_days": 5, "appointment_part": "evening"}}, {})
    assert agent.slots["appointment"] == "5:evening" and rec.outcome == "success", rec.transcript
    said = [t for w, t, _ in rec.transcript if w == "agent"]
    assert any("शुक्रवार, सत्ताईस नवंबर शाम" in t for t in said)


def test_an_impossible_date_keeps_its_weekday_and_a_contradiction_is_not_picked():
    from laghu_voice.dialog.slots import read_time
    assert read_time("शुक्रवार सत्तर नवंबर शाम", SUNDAY) == "5:evening"      # P2: "seventy November", a Friday
    assert read_time("गुरुवार छह दिसंबर सुबह", SUNDAY) is None               # P4: 6 December is a Sunday
    assert read_time("शुक्रवार सत्ताईस नवंबर शाम", SUNDAY) == "5:evening"


async def test_a_dropped_connection_is_tried_again():
    import httpx

    from laghu_voice.services import paced

    class Flaky:
        model = "m"

        def __init__(self):
            self.n = 0

        async def complete(self, messages, stats=None, **kw):
            self.n += 1
            if self.n < 3:
                raise httpx.ReadTimeout("slow")
            return "ok"
    old = paced.NET_RETRIES
    paced.NET_RETRIES = (0.0, 0.0, 0.0)
    try:
        llm = paced.PacedLLM(Flaky())
        assert await llm.complete([{"role": "user", "content": "x"}]) == "ok" and llm.net_retries == 2
    finally:
        paced.NET_RETRIES = old


# ---------------------------------------------------------------------- the 2026-11-23 00:00 run (5 of 8)
MBA_SPEC_C = ROOT / "tests" / "fixtures" / "mba_spec_2026-11-23.yaml"


def test_the_runs_empty_option_placeholder_is_an_error_and_is_fixed_by_code():
    import yaml

    from laghu_voice.setup.tool import normalize
    raw = yaml.safe_load(MBA_SPEC_C.read_text(encoding="utf-8"))
    msg = errors_of(raw)
    assert "line ask_program: asks for program and also says {program}" in msg
    assert "{program:words} doesn't fit a choice slot" in msg
    fixed, _ = normalize(raw, {})
    assert fixed["lines"]["ask_program"].endswith("फ़ुल टाइम एमबीए, एक्ज़ीक्यूटिव एमबीए या ऑनलाइन एमबीए")
    build_spec(fixed, generated=True)


async def c_call(words, readings, facts):
    import yaml

    from laghu_voice.setup.tool import normalize
    raw, _ = normalize(yaml.safe_load(MBA_SPEC_C.read_text(encoding="utf-8")), {})
    spec = build_spec(raw, generated=True)
    p = sim.Persona("P1", "x", "success", "", "x", facts)
    llm = Reads(readings)
    rec, agent, dlm = await sim.run_call(spec, "mba", llm, Lines(words), p, 1, today=SUNDAY)
    return rec, agent, dlm, spec


async def test_a_yes_that_goes_on_is_a_yes_even_when_the_llm_cant_place_it():
    """P7: "जी हाँ मैं मनीष कुमार हूँ बोलिए" (seven words: too long for the yes rule) was unclear once."""
    rec, agent, _, _ = await c_call(["जी हाँ मैं मनीष कुमार हूँ बोलिए"], {}, {})
    assert "ask_program" in rec.visited


async def test_a_yes_with_a_day_skips_the_day_question():
    """P5: "जी हाँ बुक करना चाहता हूँ गुरुवार शाम को" at the offer was unclear: the day came back as appointment_days and
    appointment_part, and the check looked for "appointment"."""
    said = "जी हाँ बुक करना चाहता हूँ गुरुवार शाम को"
    rec, agent, _, _ = await c_call(
        ["हाँ", "ऑनलाइन एमबीए", "जुलाई", "दो साल", "पुणे", said, "हाँ"],
        {"हाँ": {"intent": "yes"}, "पुणे": {"intent": "answer", "city": "Pune", "city_hi": "पुणे"},
         said: {"intent": "answer", "appointment_days": 4, "appointment_part": "evening"}}, {})
    assert agent.slots["appointment"] == "4:evening" and rec.outcome == "success", rec.transcript
    assert "choose_appointment" not in rec.visited


async def test_two_numbers_go_to_the_llm():
    """P4: "मैंने पहले दस साल का अनुभव बताया था लेकिन सही वक़्त चार साल है" was read as ten."""
    said = "मैंने पहले दस साल का अनुभव बताया था लेकिन सही वक़्त चार साल है"
    rec, agent, _, _ = await c_call(["हाँ", "ऑनलाइन एमबीए", "जुलाई", said],
                                    {"हाँ": {"intent": "yes"}, said: {"intent": "answer", "experience": 4}}, {})
    assert agent.slots["experience"] == 4


async def test_the_judge_checks_what_was_given_early():
    """P2 passed with the wrong day: it gave the day before being asked, and the judge only checked asked questions."""
    said = "हाँ बुक करूँगी कल सुबह"
    rec, agent, dlm, spec = await c_call(
        ["हाँ", "ऑनलाइन एमबीए", "जुलाई", "दो साल", "पुणे", said, "हाँ"],
        {"हाँ": {"intent": "yes"}, "पुणे": {"intent": "answer", "city": "Pune", "city_hi": "पुणे"},
         said: {"intent": "yes", "appointment_days": 1, "appointment_part": "morning"}},
        {"program": "online", "intake": "july", "experience": 2, "city": "Pune",
         "appointment": {"days": 5, "part": "evening"}})
    v = sim.judge(spec, rec, agent, dlm)
    assert rec.outcome == "success" and v["facts"]["appointment"].startswith("wrong") and not v["success"]


def test_a_date_just_past_is_a_slip_not_next_year():
    from laghu_voice.dialog.slots import read_time
    monday = date(2026, 11, 23)
    assert read_time("शनिवार बीस नवंबर सुबह", monday) == "5:morning"        # P6: Saturday 28 November
    assert read_time("बीस नवंबर सुबह", monday) is None                       # no weekday: the LLM, or ask again
    assert read_time("पाँच जनवरी", date(2026, 12, 20)) == "16:any"            # long past this year: next year


def test_the_caller_is_given_the_words_for_its_day():
    import copy
    spec = build_spec(copy.deepcopy(MBA), generated=True)
    p = sim.Persona("P4", "x", "success", "Be brief.", "x", {"session": {"days": 1, "part": "morning"}})
    c = sim.Caller(Lines([]), spec, p, SUNDAY)
    assert "कल, सोमवार, तेईस नवंबर, सुबह" in c.system


# ---------------------------------------------------------------------- the 2026-11-23 12:55 run (8 of 8)
MBA_SPEC_D = ROOT / "tests" / "fixtures" / "mba_spec_2026-11-23b.yaml"


async def d_call(words, readings, facts):
    spec = load_spec(MBA_SPEC_D, generated=True)
    p = sim.Persona("P6", "x", "success", "", "x", facts)
    llm = Reads(readings)
    rec, agent, dlm = await sim.run_call(spec, "mba", llm, Lines(words), p, 1, today=SUNDAY)
    return rec, agent, dlm, spec


BOOKING = ["हाँ", "ऑनलाइन एमबीए", "हाँ", "जुलाई", "हाँ", "दो साल", "हाँ", "चेन्नई", "हाँ", "हाँ", "रविवार उनतीस नवंबर शाम"]
READ = {"हाँ": {"intent": "yes"}, "चेन्नई": {"intent": "answer", "city": "Chennai", "city_hi": "चेन्नई"}}


async def test_a_yes_never_changes_a_booking():
    """P6, run 1: "हाँ सही है ठीक है धन्यवाद" at the read-back came back from the LLM with a day, and the booking moved
    to परसों."""
    said = "हाँ सही है ठीक है धन्यवाद"
    rec, agent, _, _ = await d_call(BOOKING + [said],
                                    {**READ, said: {"intent": "yes", "appointment_days": 2, "appointment_part": "evening"}},
                                    {})
    assert agent.slots["appointment"] == "7:evening" and rec.outcome == "success", rec.transcript   # Sun 22 -> Sun 29


async def test_a_correction_needs_words_of_its_kind():
    """A "no" with nothing about a day doesn't take a day from the LLM; "no, Saturday" does."""
    vague, real = "नहीं गलत है", "नहीं गलत है शनिवार शाम"
    rec, agent, _, _ = await d_call(BOOKING + [vague, real, "हाँ"],
                                    {**READ, vague: {"intent": "no", "appointment_days": 2},
                                     real: {"intent": "no", "appointment_days": 6, "appointment_part": "evening"}}, {})
    said = [t for w, t, _ in rec.transcript if w == "agent"]
    assert not any("परसों" in t for t in said)


async def test_a_day_read_back_and_then_corrected_is_not_an_invented_number():
    """P6, run 2: the judge flagged "कल, मंगलवार, चौबीस नवंबर", a day read back before the caller corrected it."""
    rec, agent, dlm, spec = await d_call(BOOKING + ["नहीं कल शाम", "नहीं रविवार उनतीस नवंबर शाम", "हाँ"], READ,
                                         {"appointment": {"days": 6, "part": "evening"}})
    assert any("तेईस नवंबर" in t for w, t, _ in rec.transcript if w == "agent")
    assert not [p for p in sim.judge(spec, rec, agent, dlm)["safety"] if p.startswith("(b)")]


# ---------------------------------------------------------------------- clinic, 2026-11-23 13:42 (3 of 8)
CLINIC_SPEC = ROOT / "tests" / "fixtures" / "clinic_spec_2026-11-23.yaml"


def test_the_clinic_specs_mistakes_are_errors_now():
    import yaml
    msg = errors_of(yaml.safe_load(CLINIC_SPEC.read_text(encoding="utf-8")))
    # the doctor was "chosen" by a line (lines only speak) and the name only heard at the greeting: both could be
    # read back empty ("रोगी , आयु ...")
    assert "says {doctor}, but no state asks for doctor and no tool sets it" in msg
    assert "says {name}, but no state asks for name" in msg
    # "कुछ नहीं बदलना है" at the fix question matched the cancel intent ("बदलना") and handed the call over
    assert 'intent cancel: its phrase "बदलना" is a word the agent itself says' in msg


def clinic(**over):
    raw = {
        "agent": {"name": "लघु", "company": "संजीवनी क्लिनिक", "company_en": "Sanjeevani", "gender": "male",
                  "persona": "Laghu books clinic appointments."},
        "knowledge": {"khan": "Dr. Khan, child specialist: Monday, Wednesday, Friday mornings",
                      "mehra": "Dr. Mehra, general physician: every day except Sunday"},
        "slots": {
            "area": {"type": "choice", "describe": "what the problem is about",
                     "options": {"child": ["बच्चे"], "general": ["बुखार", "सिरदर्द"]},
                     "labels": {"child": "बच्चों की समस्या", "general": "आम समस्या"}},
            "doctor": {"type": "choice", "describe": "the doctor",
                       "options": {"khan": ["डॉक्टर खान"], "mehra": ["डॉक्टर मेहरा"]},
                       "labels": {"khan": "डॉक्टर खान", "mehra": "डॉक्टर मेहरा"}},
            "visit": {"type": "time", "describe": "the day and part of the day", "max": 7}},
        "intents": {},
        "lines": {
            "greeting": "मैं {agent}, {company} से बात कर रहा हूँ। क्या अभी बात हो सकती है?",
            "ask_area": {"llm": "Ask what the problem is: a child's problem or a general one.",
                         "example": "समस्या बच्चे की है या आम, जैसे बुखार या सिरदर्द?"},
            "ask_visit": {"llm": "Ask the day and part of the day.", "example": "किस दिन और सुबह या शाम?"},
            "not_then": {"llm": "Say the doctor isn't in then, and when they are, from FACTS.",
                         "example": "उस समय डॉक्टर नहीं होते।"},
            "readback": "तो {doctor:label}, {visit:time}। क्या मैं बुक कर दूँ?",
            "fix": {"llm": "Ask whether to go ahead, or what to change.", "example": "बुक कर दूँ, या कुछ बदलना है?"},
            "booked": "हो गया, आपकी अपॉइंटमेंट बुक हो गई है। धन्यवाद।"},
        "backend": {"provider": "mock"},
        "tools": {
            "pick_doctor": {"mock": [{"if": {"area": "child"}, "data": {"doctor": "khan"}}, {"data": {"doctor": "mehra"}}],
                            "save": {"doctor": "data.doctor"},
                            "events": [{"then": "done"}]},
            "check_time": {"mock": [{"if": {"doctor": "khan", "visit_weekday": ["mon", "wed", "fri"],
                                            "visit_part": ["morning"]}, "outcome": "ok"},
                                    {"if": {"doctor": "mehra", "visit_weekday": ["mon", "tue", "wed", "thu", "fri", "sat"]},
                                     "outcome": "ok"},
                                    {"outcome": "unavailable"}],
                           "events": [{"if": {"outcome": "ok"}, "then": "ok"},
                                      {"if": {"outcome": "unavailable"}, "then": "unavailable", "clear": ["visit"]},
                                      {"then": "error"}]},
            "book": {"commits": True, "mock": [{"outcome": "ok"}],
                     "events": [{"if": {"outcome": "ok"}, "then": "done"}, {"then": "error"}]}},
        "states": {
            "greet": {"say": "greeting", "expect": "yes_no", "on": {"yes": "ask_area", "no": "goodbye"}},
            "ask_area": {"say": "ask_area", "expect": "area", "on": {"answer": "pick"}},
            "pick": {"tool": "pick_doctor", "on": {"done": "ask_visit"}},
            "ask_visit": {"say": "ask_visit", "expect": "visit", "on": {"answer": "check"}},
            "check": {"tool": "check_time", "on": {"ok": "confirm", "unavailable": "not_then", "error": "tech_problem"}},
            "not_then": {"say": "not_then", "next": "ask_visit"},
            "confirm": {"say": "readback", "expect": "yes_no", "corrections": ["visit"],
                        "on": {"yes": "book", "no": "fix", "corrected": "check"}},
            "fix": {"say": "fix", "expect": "yes_no", "corrections": ["visit"],
                    "on": {"yes": "confirm", "no": "goodbye", "corrected": "check"}},
            "book": {"tool": "book", "on": {"done": "booked", "error": "tech_problem"}},
            "booked": {"say": "booked", "end": "booked", "outcome": "success"}},
        "global": {}}
    raw.update(over)
    return raw


async def test_a_tool_works_out_a_value_and_checks_the_day():
    """The clinic's two gaps: the doctor comes from the problem (a tool sets the slot), and Dr. Khan only works on
    Monday, Wednesday and Friday mornings (a tool tests the day's weekday and part)."""
    import copy
    spec = build_spec(copy.deepcopy(clinic()), generated=True)
    p = sim.Persona("P1", "x", "success", "", "x", {})
    words = ["हाँ", "मेरे बच्चे को खांसी है", "शनिवार सुबह", "बुधवार सुबह", "हाँ"]
    rec, agent, dlm = await sim.run_call(spec, "clinic", AgentStandIn(), Lines(words), p, 1, today=SUNDAY)
    said = [t for w, t, _ in rec.transcript if w == "agent"]
    assert agent.slots["doctor"] == "khan"                              # set by the tool, from "child"
    assert any("उस समय डॉक्टर नहीं होते" in t for t in said)          # Saturday refused for Dr. Khan
    assert agent.slots["visit"] == "3:morning" and rec.outcome == "success", rec.transcript   # Wednesday 25th


def test_the_caller_says_numbers_from_given_words_and_free_text_is_judged_loosely():
    import copy
    raw = clinic()
    raw["slots"]["age"] = {"type": "number", "describe": "the patient's age"}
    raw["lines"]["ask_age"] = {"llm": "Ask the patient's age.", "example": "मरीज़ की उम्र क्या है?"}
    raw["states"]["pick"]["on"] = {"done": "ask_age"}
    raw["states"]["ask_age"] = {"say": "ask_age", "expect": "age", "on": {"answer": "ask_visit"}}
    spec = build_spec(copy.deepcopy(raw), generated=True)
    c = sim.Caller(Lines([]), spec, sim.Persona("P1", "x", "success", "", "x", {"age": 34}), SUNDAY)
    assert "चौंतीस" in c.system                                         # Qwen had said चौयासी (84) for 34
    text = Slot("problem", "text")
    assert sim.same(text, "joint pain in knees", "knee pain")
    assert not sim.same(text, "skin rash on arms", "headache")
    assert sim.same(Slot("age", "number"), {"value": 34, "say_it_as": "चौंतीस"}, 34)


async def test_checker_repairs_resume_after_the_daily_limit(tmp_path):
    from laghu_voice.services.paced import DailyLimit

    class StopAtSecondRepair(FakeSetupLLM):
        """The first draft has two mistakes; the first repair fixes one, the second hits the daily limit."""
        def __init__(self, stop):
            super().__init__()
            self.stop, self.repairs = stop, 0

        async def complete(self, messages, **kw):
            sys_ = messages[0]["content"]
            if "Write the flow" in sys_:
                states = json.loads(json.dumps(self.raw["states"]))
                states["greet"]["on"]["no"] = "gudbai"
                states["ask_name"]["on"]["answer"] = "ask_plann"
                needed = {k: {"kind": "llm" if isinstance(v, dict) else "fixed", "purpose": k}
                          for k, v in self.raw["lines"].items()}
                return json.dumps({"states": states, "tools": self.raw["tools"], "global": {}, "lines_needed": needed},
                                  ensure_ascii=False)
            if "Fix the problems" in sys_:
                self.repairs += 1
                if self.stop and self.repairs == 2:
                    raise DailyLimit("tokens per day")
                if "gudbai" in messages[-1]["content"] and self.repairs == 1:
                    return json.dumps({"states": {"greet": self.raw["states"]["greet"]}}, ensure_ascii=False)
                return json.dumps({"states": {"ask_name": self.raw["states"]["ask_name"]}}, ensure_ascii=False)
            return await super().complete(messages, **kw)
    desc = tmp_path / "library.md"
    desc.write_text("City Library calls people who asked about membership. Monthly 200, yearly 2000.", "utf-8")
    first = StopAtSecondRepair(stop=True)
    with pytest.raises(DailyLimit):
        await run_setup(desc, tmp_path / "lib", first, None, simulate=False, ask=lambda q: "2000 rupees")
    second = StopAtSecondRepair(stop=False)
    res = await run_setup(desc, tmp_path / "lib", second, None, simulate=False, ask=lambda q: "2000 rupees")
    assert res["ok"] and second.repairs == 1             # only the repair that was left; the first one was kept


# ---------------------------------------------------------------------- progress events and failure causes (web UI)
async def test_setup_reports_its_progress_as_events(tmp_path):
    desc = tmp_path / "library.md"
    desc.write_text("City Library calls people who asked about membership. Monthly 200, yearly 2000.", "utf-8")
    got = []
    res = await run_setup(desc, tmp_path / "library", FakeSetupLLM(), None, simulate=False,
                          ask=lambda q: "2000 rupees", events=got.append)
    types = [e["type"] for e in got]
    assert res["ok"] and types[-1] == "finished" and got[-1]["result"]["ok"]
    stages = [e["stage"] for e in got if e["type"] == "stage"]
    assert stages == ["questions", "drafting", "checking", "writing"]
    drafts = [(e["step"], e["status"]) for e in got if e["type"] == "draft"]
    assert ("basics", "start") in drafts and ("flow", "done") in drafts and ("lines", "done") in drafts
    checks = [e for e in got if e["type"] == "check"]
    assert checks[0]["n"] == 1 and checks[-1]["n"] == 0                # one error, repaired
    assert any(e["type"] == "log" for e in got)
    from laghu_voice.setup.tool import emit
    emit("log", text="nobody listening")                                # outside a run: no callback, no error


async def test_a_watcher_that_fails_never_stops_setup(tmp_path):
    desc = tmp_path / "library.md"
    desc.write_text("City Library calls people who asked about membership.", "utf-8")

    def broken(_event):
        raise RuntimeError("the UI went away")
    res = await run_setup(desc, tmp_path / "library", FakeSetupLLM(), None, simulate=False, ask=lambda q: "",
                          events=broken)
    assert res["ok"]


async def test_a_failed_call_says_the_caller_never_gave_its_fact():
    gym = load_spec(GYM)
    p = sim.Persona("P1", "cooperative", "success", "", "Abhay", {**GYM_FACTS, "plan": "quarterly"})
    rec, agent, dlm = await sim.run_call(gym, "gym", AgentStandIn(), Lines(GYM_CALL), p, 1, today=TODAY)
    rec.verdict = sim.judge(gym, rec, agent, dlm)
    d = sim.diagnose(gym, rec.__dict__, TODAY)
    assert d["cause"] == "caller" and "plan" in d["why"][0] and "quarterly" in d["why"][0], d
    assert sim.diagnose(gym, {**rec.__dict__, "verdict": {"success": True, "safety": []}}, TODAY)["cause"] is None


async def test_a_human_seeker_who_never_asks_is_the_callers_fault():
    gym = load_spec(GYM)
    p = sim.Persona("P8", "human-seeker", "transferred", "", "Abhay", dict(GYM_FACTS))
    rec, agent, dlm = await sim.run_call(gym, "gym", AgentStandIn(), Lines(GYM_CALL), p, 1, today=TODAY)
    rec.verdict = sim.judge(gym, rec, agent, dlm)
    assert not rec.verdict["success"]
    d = sim.diagnose(gym, rec.__dict__, TODAY)
    assert d["cause"] == "caller" and "never asked for a person" in d["why"][0]


def _row(**kw):
    base = {"persona": {"id": "P1", "kind": "cooperative", "expected": "success", "facts": dict(GYM_FACTS),
                        "first_said": {}},
            "transcript": [["caller", t, None] for t in GYM_CALL], "steps": [], "tools": [], "visited": [],
            "slots": dict(GYM_FACTS), "outcome": "success", "end": "booked", "error": None,
            "verdict": {"success": False, "outcome_ok": True, "facts": {}, "safety": []}}
    for k, v in kw.items():
        base[k] = {**base[k], **v} if isinstance(base.get(k), dict) and isinstance(v, dict) else v
    return base


def test_failure_causes_agent_spec_and_judge():
    gym = load_spec(GYM)
    # the caller said शाम (evening); the agent stored morning: the engine misread it
    d = sim.diagnose(gym, _row(slots={"time_slot": "morning"},
                               verdict={"facts": {"time_slot": "wrong: 'morning' for 'evening'"}}), TODAY)
    assert d["cause"] == "agent" and "evening" in d["why"][0], d
    # a tool that found no answer outranks everything: the spec has to change
    d = sim.diagnose(gym, _row(tools=[["book", "error", "confirm", "yes"]], outcome="failed",
                               verdict={"outcome_ok": False}), TODAY)
    assert d["cause"] == "spec" and "book" in d["why"][0]
    # a name said a little differently: the judge is too strict, not the agent
    d = sim.diagnose(gym, _row(slots={"full_name": "Abhay Kumar"}, persona={"facts": {**GYM_FACTS,
                                                                                    "full_name": "Abhay K"}},
                               verdict={"facts": {"full_name": "wrong"}}), TODAY)
    assert d["cause"] == "judge"
    # stuck three turns: the engine
    d = sim.diagnose(gym, _row(steps=[{"event": "unclear", "stuck": True}], outcome="transferred",
                               verdict={"outcome_ok": False}), TODAY)
    assert d["cause"] == "agent"
    assert set(sim.CAUSES) == {"spec", "agent", "caller", "judge", "unclear"}


async def test_a_refuser_who_takes_the_next_offer_is_the_callers_fault():
    gym = load_spec(GYM)
    p = sim.Persona("P7", "refuser", "declined", "", "Abhay", dict(GYM_FACTS))
    said = ["हाँ", "मेरा नाम अभय है", "वज़न कम करना", "मासिक", "शाम", "परसों", "नहीं अभी नहीं"]   # then "ठीक है धन्यवाद"
    rec, agent, dlm = await sim.run_call(gym, "gym", AgentStandIn(), Lines(said), p, 1, today=TODAY)
    rec.verdict = sim.judge(gym, rec, agent, dlm)
    assert rec.end == "trial_booked" and not rec.verdict["success"]       # said no to joining, then took the trial
    d = sim.diagnose(gym, rec.__dict__, TODAY)
    assert d["cause"] == "caller" and "accepted a later offer" in d["why"][0], d
