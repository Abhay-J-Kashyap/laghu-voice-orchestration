"""Milestone 4 typed calls: what the caller says, written the way IndicConformer writes it (Devanagari,
numbers as words, PAN letters as letter names), and what the backend's audit record must show afterwards.

The personas are the backend's seeded customers (voice-onboarding-agent/app/seed.py), plus one unknown PAN.
Each caller line has its English meaning beside it. `llm` is what a correct reading of that line is: only
`--llm scripted` uses it (a stand-in for development runs; the judged runs use Groq and ignore it).
`{otp}` is replaced by the passcode the backend sent (demo mode), spoken as Hindi digit words.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Say:
    text: str
    en: str
    llm: dict | None = None             # the correct extraction (scripted runs only)
    interrupted: bool = False           # the caller cut off the agent's last reply before this turn


@dataclass
class Expect:
    end: str                            # the agent's ending (spec `end:` value)
    state: str                          # the backend session's final state
    tools: list[str]                    # tool calls in the backend's audit, in order
    consents: list[bool] = field(default_factory=list)
    decision: str | None = None
    queue: str | None = None            # escalation queue
    counter_offer: bool | None = None   # approved for less than asked
    no_tool_before_confirm: bool = False


@dataclass
class Scenario:
    id: str
    title: str
    lines: list[Say]
    expect: Expect
    mirrors: str = ""                   # the backend scenario it mirrors


@dataclass
class Persona:
    name_hi: str
    name_en: str
    dob: str
    pan: str


RAJESH = Persona("राजेश कुमार", "Rajesh Kumar", "बारह अप्रैल उन्नीस सौ अठासी", "ए बी सी डी ई एक दो तीन चार एफ़")
PRIYA = Persona("प्रिया शर्मा", "Priya Sharma", "तीन नवंबर उन्नीस सौ चौरानवे", "बी सी डी ई एफ़ दो तीन चार पाँच जी")
IMRAN = Persona("इमरान क़ुरैशी", "Imran Qureshi", "इक्कीस जुलाई उन्नीस सौ इक्यानवे", "सी डी ई एफ़ जी तीन चार पाँच छह एच")
VIKRAM = Persona("विक्रम आनंद", "Vikram Anand", "पंद्रह सितंबर उन्नीस सौ उन्यासी", "ई एफ़ जी एच आई पाँच छह सात आठ जे")
ANITA = Persona("अनीता देसाई", "Anita Desai", "अठारह फ़रवरी उन्नीस सौ नब्बे", "एफ़ जी एच आई जे छह सात आठ नौ के")
SURESH = Persona("सुरेश मेनन", "Suresh Menon", "नौ जून उन्नीस सौ छियासी", "जी एच आई जे के सात आठ नौ शून्य एल")
FATIMA = Persona("फ़ातिमा शेख़", "Fatima Sheikh", "चौबीस दिसंबर उन्नीस सौ तिरानवे", "एच आई जे के एल आठ नौ शून्य एक एम")
KAVYA = Persona("काव्या रेड्डी", "Kavya Reddy", "चौदह अगस्त उन्नीस सौ बानवे", "ज़ेड ज़ेड ज़ेड ज़ेड ज़ेड नौ नौ नौ नौ ज़ेड")

YES = Say("हाँ जी, बताइए", "Yes, go ahead")
CONFIRM = Say("हाँ, सब सही है", "Yes, all correct")
OTP = Say("{otp}", "(reads out the passcode)", {"intent": "answer"})
CONSENT_YES = Say("हाँ, मैं सहमत हूँ", "Yes, I agree")
LATER = Say("अभी नहीं, बाद में बात करेंगे", "Not now, we'll talk later", {"intent": "stop"})


def name(p: Persona, prefix: str = "मेरा नाम", suffix: str = "है") -> Say:
    return Say(f"{prefix} {p.name_hi} {suffix}".strip(), f"My name is {p.name_en}",
               {"intent": "answer", "full_name": p.name_en, "full_name_hi": p.name_hi})


def identity(p: Persona, dob: str | None = None, pan: str | None = None) -> list[Say]:
    return [name(p), Say(dob or p.dob, "(date of birth)"), Say(pan or p.pan, "(PAN, letter by letter)"), CONFIRM]


def loan(amount: str, amount_en: str, tenure: str, tenure_en: str, income: str, income_en: str, job: str,
         job_en: str) -> list[Say]:
    return [Say(amount, amount_en), Say(tenure, tenure_en), Say(income, income_en), Say(job, job_en)]


TYPED = "verify_identity verify_otp check_eligibility record_consent".split()

SCENARIOS: list[Scenario] = [
    Scenario("T01", "Cooperative applicant, approved, agrees", [
        YES, *identity(RAJESH), OTP,
        *loan("तीन लाख रुपये", "Three lakh rupees", "तीन साल के लिए", "For three years", "पचानवे हज़ार",
              "Ninety-five thousand", "मैं नौकरी करता हूँ", "I have a job"),
        CONSENT_YES,
    ], Expect("completed", "completed", TYPED, [True], "approved", counter_offer=False), "S01"),

    Scenario("T02", "Asks for more than they can repay: counter-offer, accepts; amount and tenure in one breath", [
        YES, *identity(PRIYA), OTP,
        Say("पंद्रह लाख तीन साल के लिए", "Fifteen lakh for three years (no comma: STT writes none)"),
        Say("बयालीस हज़ार", "Forty-two thousand"),
        Say("सैलरी मिलती है, नौकरी करती हूँ", "I get a salary, I have a job"),
        Say("हाँ ठीक है", "Yes, okay"),
    ], Expect("completed", "completed", TYPED, [True], "approved", counter_offer=True), "S02"),

    Scenario("T03", "Below the credit floor: declined, doesn't want a colleague", [
        YES, *identity(IMRAN), OTP,
        *loan("दो लाख", "Two lakh", "दो साल", "Two years", "साठ हज़ार", "Sixty thousand", "मेरा अपना बिज़नेस है",
              "I have my own business"),
        Say("नहीं, कोई बात नहीं", "No, never mind"),
    ], Expect("caller_declined", "eligibility_assessed", TYPED[:3], [], "declined"), "S03"),

    Scenario("T04", "Date of birth misheard, mismatch, then corrected; then asks for a person", [
        YES, *identity(RAJESH, dob="इक्कीस अप्रैल उन्नीस सौ अठासी"),
        *identity(RAJESH),
        Say("मुझे किसी इंसान से बात करनी है", "I want to talk to a human", {"intent": "human"}),
    ], Expect("transferred", "escalated", ["verify_identity", "verify_identity", "escalate"],
              queue="general_support"), "S04"),

    Scenario("T05", "Cannot be verified: two mismatches, then blocked and handed over", [
        YES, *identity(RAJESH, dob="एक जनवरी उन्नीस सौ नब्बे"),
        *identity(RAJESH, dob="दो जनवरी उन्नीस सौ नब्बे"),
    ], Expect("transferred", "escalated", ["verify_identity", "verify_identity", "escalate"], queue="kyc_review"),
        "S05"),

    Scenario("T06", "Sanctioned individual: blocked, no reason given, handed over", [
        YES, *identity(VIKRAM),
    ], Expect("transferred", "escalated", ["verify_identity", "escalate"], queue="kyc_review"), "S06"),

    Scenario("T07", "Approved, but declines the terms", [
        YES, *identity(ANITA), OTP,
        *loan("एक लाख", "One lakh", "दो साल", "Two years", "अट्ठासी हज़ार", "Eighty-eight thousand", "नौकरी",
              "A job"),
        Say("नहीं, मुझे सोचना है", "No, I need to think"),
    ], Expect("consent_declined", "eligibility_assessed", TYPED, [False], "approved"), "S07"),

    Scenario("T08", "Declined, disputes the decision: handed to underwriting", [
        YES, *identity(IMRAN), OTP,
        *loan("दो लाख", "Two lakh", "दो साल", "Two years", "साठ हज़ार", "Sixty thousand", "मेरा अपना बिज़नेस है",
              "I have my own business"),
        Say("ये फ़ैसला गलत है, मेरा क्रेडिट स्कोर तो अच्छा है", "This decision is wrong, my credit score is good",
            {"intent": "dispute"}),
    ], Expect("transferred", "escalated", TYPED[:3] + ["escalate"], [], "declined", "underwriting"), "S08"),

    Scenario("T09", "Asks for a person straight away", [
        Say("मुझे किसी इंसान से बात करनी है", "I want to talk to a human", {"intent": "human"}),
    ], Expect("transferred", "escalated", ["escalate"], queue="general_support"), "S09"),

    Scenario("T10", "Declared income far above the record: referred, connected to a colleague", [
        YES, *identity(PRIYA), OTP,
        *loan("एक लाख", "One lakh", "दो साल", "Two years", "ढाई लाख", "Two and a half lakh", "नौकरी करती हूँ",
              "I have a job"),
        Say("हाँ, जोड़ दीजिए", "Yes, connect me"),
    ], Expect("transferred", "escalated", TYPED[:3] + ["escalate"], [], "referred", "general_support"), "S14"),

    Scenario("T11", "Mishears the passcode, then reads it right; then stops", [
        YES, *identity(SURESH),
        Say("एक एक एक एक एक एक", "One one one one one one", {"intent": "answer"}),
        OTP, LATER,
    ], Expect("caller_declined", "identity_verified", ["verify_identity", "verify_otp", "verify_otp"]), "S16"),

    Scenario("T12", "Passcode never arrived: resent, then completes", [
        YES, *identity(FATIMA),
        Say("कोड नहीं आया, दोबारा भेजिए", "The code didn't come, send it again", {"intent": "resend_code"}),
        OTP,
        *loan("पाँच लाख", "Five lakh", "पाँच साल", "Five years", "छिहत्तर हज़ार", "Seventy-six thousand",
              "नौकरी करती हूँ", "I have a job"),
        CONSENT_YES,
    ], Expect("completed", "completed", ["verify_identity", "resend_otp", "verify_otp", "check_eligibility",
                                         "record_consent"], [True], "approved"), "S18"),

    Scenario("T13", "Ten-year tenure is quotable", [
        YES, *identity(SURESH), OTP,
        *loan("पंद्रह लाख", "Fifteen lakh", "दस साल", "Ten years", "एक लाख दस हज़ार", "One lakh ten thousand",
              "प्राइवेट कंपनी में नौकरी करता हूँ", "I work at a private company"),
        CONSENT_YES,
    ], Expect("completed", "completed", TYPED, [True], "approved"), "S20"),

    Scenario("T14", "Tenure beyond policy is asked again, not sent", [
        YES, *identity(FATIMA), OTP,
        Say("पाँच लाख", "Five lakh"),
        Say("बीस साल के लिए", "For twenty years"),
        Say("ठीक है, दस साल", "Okay, ten years"),
        Say("छिहत्तर हज़ार", "Seventy-six thousand"),
        Say("नौकरी करती हूँ", "I have a job"),
        CONSENT_YES,
    ], Expect("completed", "completed", TYPED, [True], "approved"), "S21"),

    Scenario("T15", "No account: details taken as a lead, link emailed", [
        YES, *identity(KAVYA),
        Say("हाँ, भेज दीजिए", "Yes, send it"),
        Say("के ए वी वाई ए डॉट आर ई डी डी वाई एट एग्ज़ाम्पल डॉट कॉम", "kavya.reddy@example.com, spelt out",
            {"intent": "answer", "email": "kavya.reddy@example.com"}),
        Say("हाँ, सही है", "Yes, correct"),
    ], Expect("lead_captured", "lead_captured", ["verify_identity", "capture_lead"]), "S23"),

    Scenario("T16", "No account, asks for a person", [
        YES, *identity(KAVYA),
        Say("नहीं, मुझे किसी इंसान से बात करनी है", "No, I want to talk to a human", {"intent": "human"}),
    ], Expect("transferred", "escalated", ["verify_identity", "escalate"], queue="general_support"), "S25"),

    Scenario("T17", "Half a PAN is asked again, never sent", [
        YES, name(RAJESH), Say(RAJESH.dob, "(date of birth)"),
        Say("ए बी सी डी एक दो तीन", "(PAN with letters and digits missing)", {"intent": "answer"}),
        Say(RAJESH.pan, "(PAN, letter by letter)"), CONFIRM, OTP, LATER,
    ], Expect("caller_declined", "identity_verified", ["verify_identity", "verify_otp"]), "S13"),

    Scenario("D1", "Interrupts the consent question with a yes: asked again, recorded only once heard", [
        YES, *identity(RAJESH), OTP,
        *loan("तीन लाख रुपये", "Three lakh rupees", "तीन साल के लिए", "For three years", "पचानवे हज़ार",
              "Ninety-five thousand", "मैं नौकरी करता हूँ", "I have a job"),
        Say("हाँ हाँ ठीक है", "Yes yes, okay", interrupted=True),
        CONSENT_YES,
    ], Expect("completed", "completed", TYPED, [True], "approved")),

    Scenario("D2", "Asks the interest rate before giving the amount: answered without numbers, then continues", [
        YES, *identity(ANITA), OTP,
        Say("पहले ये बताइए कि ब्याज दर कितनी लगेगी?", "First tell me, what interest rate will it be?",
            {"intent": "question"}),
        *loan("एक लाख", "One lakh", "दो साल", "Two years", "अट्ठासी हज़ार", "Eighty-eight thousand", "नौकरी",
              "A job"),
        CONSENT_YES,
    ], Expect("completed", "completed", TYPED, [True], "approved")),

    Scenario("D3", "Three answers that make no sense: handed over for low confidence", [
        YES, *identity(SURESH), OTP,
        Say("पंद्रह लाख", "Fifteen lakh"), Say("दस साल", "Ten years"),
        Say("वो तो देखिए क्या है ना", "Well, you see, what it is...", {"intent": "unclear"}),
        Say("हम्म वो वाला", "Hmm, that one", {"intent": "unclear"}),
        Say("पता नहीं क्या बोलूँ", "I don't know what to say", {"intent": "unclear"}),
    ], Expect("transferred", "escalated", ["verify_identity", "verify_otp", "escalate"],
              queue="general_support")),

    Scenario("D4", "Wrong PAN digit corrected at the read-back: no verification attempt used", [
        YES, name(RAJESH), Say(RAJESH.dob, "(date of birth)"),
        Say("ए बी सी डी ई एक दो तीन पाँच एफ़", "(PAN with one digit wrong)"),
        Say("नहीं, पैन ए बी सी डी ई एक दो तीन चार एफ़ है", "No, the PAN is ABCDE1234F"),
        CONFIRM, OTP, LATER,
    ], Expect("caller_declined", "identity_verified", ["verify_identity", "verify_otp"])),
]
