"""What the setup LLM is told about specs: the format, and the lessons Milestone 4 learnt by hand (each one is
also a checker rule, so a draft that forgets one is sent back)."""

GUIDE = """A spec is a JSON object for a Hindi phone agent. The engine runs it; nothing else is programmed.

The engine already provides, so don't define them unless the business needs other words:
- lines: unclear, not_heard, was_asking, repeat, not_heard_guard, are_you_there, hold_ok, filler, pick_one,
  scope, question_fallback, transfer, transfer_failed, tech_problem, hangup_silence, low_confidence,
  out_of_scope, goodbye;
- states: goodbye (ends declined), handover -> transfer (transferred) or transfer_failed (failed),
  low_confidence, out_of_scope, tech_problem (each says its line, then hands over), hangup_silence;
- global routes: human -> handover, stop -> goodbye, silence, off-topic, low confidence.

agent: {"name": "लघु", "company": "<the company in Devanagari>", "company_en": "<the company>", "gender":
  "male", "persona": "<English: who the agent is, who it calls and why, what the call achieves, the tone>"}
knowledge: {"key": "English fact with numbers as digits"}: every price, timing, rule and count the agent may
  ever say. State counts ("3 programs: ..."). Only facts the description or the owner's answers give, and all of
  them: every schedule and rule (who works on which days and hours) goes in.
slots: {"name": {"type": ..., "describe": "English"}}. Types:
  name (the caller's name), text (a city, a college, a company: read by the LLM),
  choice ("options": {"key": [3-8 Hindi phrases a caller would say for this option, Devanagari, short forms
          too ("पूरा समय", "फुल टाइम"), no hyphens]},
          "labels": {"key": "Hindi label"}, "reask": {"ambiguous": "<line asking to pick one>"}),
  number ("min", "max"), money (rupees; "min", "max"),
  duration ("unit": "days" or "months"; "min", "max"; "reask": {"out_of_range": "<line>", "range": "<line>"}),
  time (ONE slot for a day and part of the day, for an appointment or a callback: callers say कल शाम,
        शनिवार सुबह, पाँच दिसंबर दोपहर; "min", "max": days from today, e.g. "max": 14),
  date (only a date of birth, with "min_age"), email, digits ("length").
  Only slots a state asks for; never the phone number the agent is calling.
  An option's phrases are words for that option only, never a word the question itself uses (a question
  "आपका फ़िटनेस लक्ष्य क्या है?" means "फ़िटनेस" can't be a phrase: callers repeat the question's words).
intents: {"name": {"describe": "English", "phrases": ["Hindi trigger words"]}}: the use case's own requests
  (a trial, a discount, a callback, a brochure). Never the built-in ones: answer, yes, no, human, repeat,
  question, off_topic, stop, unclear, hold.
tools: {"name": {"mock": [{"if": {"<slot>": "<value>"}, "outcome": "ok", "data": {...}}, ..., {"outcome": "ok"}],
  "save": {"<var>": "data.<field>"}, "events": [{"if": {"outcome": "ok"}, "then": "<event>"}, {"then": "error"}],
  "commits": true}}: mock answers stand in for the business's system. A condition on a choice slot uses the
  option KEY ("full_time", not its label), and the list ends with an answer without "if": when nothing
  matches, the tool fails and the call is handed over. "commits": true for a tool that books,
  registers, pays or promises; it may run only straight after a yes to a confirming question.
  Lines only speak: a value comes from the caller's answer or from a tool. A tool's "save": {"<slot>":
  "data.<field>"} sets that slot, for a value the business works out (the doctor from the problem and the age).
  A rule over several answers (which doctor fits; whether that doctor works on the chosen day and part of the
  day) is a tool that doesn't commit, run before the read-back. Its mock answers list what is allowed; a time
  slot is testable as <slot>_weekday (mon, tue, wed, thu, fri, sat, sun) and <slot>_part (morning, afternoon,
  evening, night); a number with {"lt": 14} or {"ge": 14}. Example: "mock": [{"if": {"doctor": "khan",
  "visit_weekday": ["mon", "wed", "fri"], "visit_part": ["morning"]}, "outcome": "ok"}, ..., {"outcome":
  "unavailable"}], "events": [{"if": {"outcome": "ok"}, "then": "ok"}, {"if": {"outcome": "unavailable"},
  "then": "unavailable", "clear": ["visit"]}, {"then": "error"}]; "unavailable" leads to a state that says when
  it is possible (from knowledge) and then asks for the time again. To route by what a caller describes, use a
  choice slot of categories (skin, child, general) that the LLM reads.
states: {"name": {...}}, each with exactly one of:
  "expect": a slot name or "yes_no", with "say": a line key and "on": {"answer": state} for a slot, or
    {"yes": state, "no": state} for yes_no, plus the spec's own intents;
  "tool": a tool name, with "on": {event: state} for every event of the tool (error -> "tech_problem");
  "next": a state, after saying "say";
  "end": a short reason, with "outcome": success | declined | transferred | no_contact | failed.
  Optional: "skip_if": a slot (skip a question already answered), "also": [slots also read from the same
  answer], "corrections": [slots the caller may correct here].
  The first state is "greet": expect yes_no, "also": [the name slot], says "greeting"; yes leads to the first
  question, no to a polite ending (outcome declined). The name question has "skip_if" on the name slot.
  Before any tool that commits there is a "confirm" state: says a template reading back every collected
  detail, expect yes_no, "corrections": [those slots], "on": {"yes": <the commit tool's state>, "no": "fix",
  "corrected": "confirm"}. And a "fix" state: says an llm line asking whether to go ahead (yes) or not now (no),
  and that they can also just say the detail to change; expect yes_no, "corrections": [the same slots], "on":
  {"corrected": "confirm", "yes": "confirm", "no": "goodbye"}. (Asking "what should change?" alone makes
  "nothing" sound like a no.)
  "reask" values are KEYS of lines you define in "lines" (never the sentence itself).
  Every state with "end" also has "outcome" beside it, e.g. {"say": "booked", "end": "booked", "outcome":
  "success"}. success: the call's goal was reached (a booking, or a callback the use case counts as done);
  declined: the caller said no; transferred: handed to a person because the agent couldn't help.
global: {"<intent>": state} for the spec's intents that may come at any point. The state must exist: define it, or
  use a built-in one (goodbye, handover). Never define a tool called handover; it is built in.
  An intent the agent must not answer itself (a discount or scholarship, a guarantee, a complaint) goes to a
  state of your own that says an llm line (a counsellor or the team will help with that; never answer it,
  never promise) and then "next": "back", which returns to the question the caller was on, so the call goes
  on. Example: "global": {"scholarship": "scholarship_help"}, "states": {"scholarship_help": {"say":
  "scholarship_line", "next": "back"}}. Hand over ("next": "handover") only if the owner says so; a caller
  asking for a person is the built-in human intent.
  A state whose line asks a question waits for the answer (expect). An offer ("shall I book a free session?")
  is an expect yes_no state: yes -> the first question of the booking, no -> the alternative or a goodbye.
  A state with "next" says a statement only. Don't confirm each answer with its own question: the read-back
  before the commit confirms them all, and takes corrections.
lines: {"key": "fixed Hindi"} | {"key": "Hindi template with {slot:format}"} | {"key": {"llm": "English goal",
  "example": "Hindi example of what to say"}}.
  Formats (every slot in a line has one): {x:label} a choice's Hindi label, {x:words} a number in Hindi words,
  {x:time} a time slot's day and part (said as "शनिवार, पाँच दिसंबर सुबह"), {x:hi} a name or text in
  Devanagari; {agent} and {company}.
  Fixed: the greeting and closings. Templates: read-backs and amounts. LLM lines: questions and reactions.
  Hindi rules: Devanagari only, no English letters (an acronym is written as its letters: MBA is एमबीए, and a
  word like "online" as ऑनलाइन), no digits (numbers as words), never नमस्ते, male first
  person (करता हूँ, सकता हूँ), polite आप, short spoken sentences, at most two per line. The greeting starts
  "मैं {agent}, {company} से बात कर रहा हूँ।" and asks if they can talk now. A question offering choices names
  each option once, and nowhere else in the line. Never state a number that isn't in knowledge."""
