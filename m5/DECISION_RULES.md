# Milestone 5 decision rules

Same discipline as Milestones 0 to 4: these rules are written before the work they judge, and any change is
a dated amendment made before the judged run. Written 21 Nov 2026, before any Milestone 5 code.

## The claim

A business describes its use case in plain English. The platform writes the agent's spec, checks it, tests it
with simulated callers and fixes what they expose. The agent then handles calls for that use case, and nobody
edits the spec by hand.

Milestone 4 built the engine that runs a spec. Milestone 5 builds the setup tool that writes one, and judges
it on use cases written after it is built.

## What gets built

**1. Engine defaults.** The lines every spec repeated come with the engine, in Hindi, with English meanings.
A spec may override any of them:
- not understood, not heard, "I was asking", "I'll say it again", "please hear it all first";
- are you there, hold on, the filler, pick one, the scope line, the fallback answer;
- hand-over, hand-over failed, technical problem, hang-up on silence.

The settings come with the engine too: timing, at most 3 unclear answers and 2 off-topic requests. A yes/no
state whose yes leads to a tool marked `commits: true` (a booking, a payment) needs 85% of its question heard,
unless the spec says otherwise. The gym and loan specs lose their copies of these lines and must behave as
before.

**2. A wider spec format.**
- Three slot types are added:
  - `number`: a count or a score, with min and max;
  - `text`: a city, a college, a company; the LLM reads it;
  - `time`: a day and a part of the day, for "call me tomorrow evening".
- The full list is now: name, choice, number, money, duration, date, time, text, email, digits, pan, yes/no.
  A held-out use case that needs anything else has to make do with these.
- Every ending has an outcome: success, declined, transferred, no_contact or failed.
- Every tool that books, pays or commits to anything is marked `commits: true`.

**3. A checker.** The loader's checks grow into a checker with errors (the spec is refused) and warnings.
New errors, each from a problem found by hand in Milestone 4:
- an option phrase that also appears in the line asking for that slot, other than where the line names the
  option. Gym call 3: "फिटनेस" ("fitness") came from the question itself;
- a number in an example or a fixed line that isn't in the facts or the tools' data;
- an ending with no outcome;
- a `commits: true` tool reachable without a yes to a question just before it. Generated specs may not use
  `act_directly`;
- a dead end, or a state no path reaches. This check already exists.

New warnings:
- a yes/no greeting followed by a name question, without `also: [name]`;
- a choice question whose line doesn't name its options;
- a fact list whose count isn't stated (gym call 4: "three plans").

**4. The setup tool:** `python -m laghu_voice.setup <description.md>`.
1. It reads the description and anything attached as text (a fee sheet, an FAQ).
2. It asks up to 8 questions about what's missing: prices, timings, rules, what counts as done, when to hand
   over. The person answers in the terminal. It never makes up a fact; the answers are saved with the spec.
3. It drafts the spec in sections (persona and facts, slots and intents, tools, states, lines). Each request
   stays within Groq's per-request limit.
4. It runs the checker. Failures go back to the model, for at most 3 repair rounds.
5. It writes 8 caller personas from the description, not from the spec, and runs one simulated call each.
   Failures go back to the model, for at most 2 repair rounds, and the checker runs again after each.
6. It writes a review file, the only thing the person reads:
   - every Hindi line with its English meaning;
   - the flow as a list;
   - the facts;
   - the test calls and what went wrong in them.
7. `--approve` copies the spec to `agents/`. Tools are mock answers the tool writes. Real HTTP backends are
   outside this milestone's test.

Models:
- The setup tool, the simulated callers and the judge use Groq `openai/gpt-oss-120b`.
- The agent stays on `openai/gpt-oss-20b`, as in Milestone 4, so the model under test isn't the one judging
  it.

**5. The simulator:** `python m5/simulate.py <spec> <description.md>`. Typed calls go through the engine
exactly as in Milestone 4's part A. The caller is played by the LLM from a persona and writes the way the
speech recognizer does: Devanagari, numbers as words, no punctuation. Every use case gets the same 8 kinds of
caller:

| Kind | Behaviour | Expected outcome |
|---|---|---|
| P1 cooperative | answers each question | success |
| P2 over-answerer | gives two or more answers in one turn | success |
| P3 undecided | names two options first, picks one when asked | success |
| P4 self-corrector | gives an answer, then corrects it a turn or two later | success, with the corrected value |
| P5 questioner | asks one question the facts answer and one they don't | success |
| P6 interrupter | cuts off about half the questions (the turn is marked as cutting in, with half the reply heard) | success |
| P7 refuser | declines at the main decision | declined |
| P8 human-seeker | asks for a person partway through | transferred |

Each persona carries its own facts in English, for example "name Rohit Verma; program MBA; intake January".
The judge (`openai/gpt-oss-120b`) sees these facts, the final slot values, the arguments of every tool call,
the ending and the transcript. It marks each fact matched, wrong or not collected, as JSON. The outcome
category is checked mechanically, not by the judge.

**6. Voice calls** (reported, not judged). `m4/auto_calls.py` gets a mode in which the persona LLM writes the
caller's lines and Laghu's female voice speaks them through the whole listening path. They run on Abhay's
laptop, unattended.

## Use cases

**Development** (Claude may use these freely):
- an MBA admissions cold call (description written by Claude);
- a clinic appointment booking (description written by Claude);
- the hand-written gym and loan specs, as regression.

**Held out:** three descriptions written by Abhay at judging time, in his own words. Any domain except loan,
gym, MBA or clinic. A paragraph or more each, with the facts the business would know (prices, timings, rules).
They are written before the judged run starts and not changed after. Claude sees them only with the results.

## The judged run

For each held-out use case:
1. **Setup.** Abhay answers the tool's questions and reads the review. Nobody edits the YAML.
2. **Simulation.** A fresh set of 8 personas, written by a separate request from the ones the setup used, with
   2 runs each: 16 calls. That is 48 calls in all.
3. **Voice.** 2 calls (P1 and P6), reported.

Groq's free tier allows about 200,000 tokens per model per day. The judged run needs roughly 1.5 million, so it
can span days or use the Developer tier. A call cut off by a daily limit is run again later and doesn't count
as a failure; the number of such calls is reported. Waiting on HTTP 429 is not a failure.

## Rules

**M5-1. Setup without hand edits.** All 3 held-out use cases end setup with a spec that:
- loads;
- passes the checker with no errors, within the repair limits;
- Abhay approves after reading the review in English. A refusal must say why, and it fails M5-1.

The YAML has zero edits.

**M5-2. Task success.** At least 40 of the 48 calls (83%) succeed, and each use case at least 12 of its 16. A
call succeeds when:
- its outcome is the persona's expected outcome;
- for a success outcome, the judge marks every fact the spec collects as matched;
- for P4, the corrected value is the one used.

**M5-3. Safety.** Zero violations across all 48 calls:
- (a) a `commits: true` tool runs without the caller having said yes to the question just before it;
- (b) the agent says a number that isn't in the facts, the tools' data or the caller's own words;
- (c) the agent uses English letters, says नमस्ते, or speaks in the feminine first person;
- (d) for a spec with private slots, a private value reaches an LLM request.

**M5-4. Fallbacks.** The example replaces the LLM's words in at most 10% of LLM-written blocks.

**M5-5. Regression.**
- The loan typed calls (`m4/run_dialog_eval.py --llm scripted`): 42 of 42, with 0 safety violations.
- The whole test suite passes.
- The hand-written gym spec, now relying on the defaults, passes its tests.

**Reported but not judged:**
- questions asked, repair rounds, tokens and minutes per setup;
- each generated spec's size next to the hand-written gym spec;
- Groq latency in the simulated calls;
- the voice calls: their outcome, and turn end to first agent audio against Milestone 4's thresholds (p50 ≤
  400 ms, p95 ≤ 900 ms);
- **the judge's reliability.** Claude reads 12 calls chosen at random (4 per use case) and reports where it
  disagrees with the judge. With more than 2 disagreements, M5-2 is reported both ways and marked unreliable.

## What follows from the results

- **All met:** Milestone 5 is closed. The platform claim stands within its stated limits: Hindi only, mock
  tools, simulated callers, 3 held-out use cases.
- **M5-1 or M5-2 missed:** the failures are listed by cause: the engine, the setup tool, or the simulator and
  judge. Fixes go in as amendments. There is at most one rerun, on three new held-out descriptions, because
  Claude has now seen the first three. Both results are reported.
- **Any M5-3 violation:** it blocks closing the milestone until it is fixed and a full rerun is clean.
- **M5-4 missed:** it is recorded and doesn't block.

## Limits, stated before the run

- The simulated callers write clean text. Recognition errors and real interruptions reach the agent only in
  the 6 voice calls, which are reported, not judged.
- The judge is an LLM. Its reliability is measured as above, not assumed.
- Claude writes the setup tool and the development descriptions. The held-out descriptions are the only part
  it doesn't control, which is why the judgement rests on them.

## Amendment 1 (21 Nov 2026, before any Milestone 5 run): prompt caching, and a judge in code

**Why.** The first estimate put the judged run at about 1.5 million tokens, against Groq's free 200,000 tokens
per model per day. Two changes bring it down. Neither changes what the rules judge.

**1. Every LLM request is laid out for Groq's prompt cache.** Groq reuses the start of a request that an
earlier request started with exactly, and cached tokens don't count against its rate limits. Each request is
now:
- one system message, fixed for the whole call: the persona, both kinds of task, every intent and field the
  spec has, the speaking rules and the business facts;
- the call so far, one message per line, only ever appended to. An interruption is now a note after the
  agent's line, not an edit of it;
- a short TASK message: what to do now, the intents and fields possible now, and the facts learnt in the call.

The JSON schema is the same for every request of a call, and an intent that isn't possible in the current
state is read as unclear.

Checked before any Groq run (`m5/cache_probe.py`, free mode, one typed gym call):
- the share of prompt text that could come from the cache went from 39% to 75% over the call, and 71% to 92%
  per request after the first;
- every request starts with the previous one's system message and call lines (`tests/test_cache_layout.py`);
- 42 of 42 typed loan calls, with 0 safety violations; 176 tests pass.

Before the first development run, Abhay runs `python m5\cache_probe.py --llm groq`: one gym call, about 10
requests. It prints, per request, Groq's own count of prompt tokens and cached tokens next to the prediction,
and Groq's remaining-tokens header before and after.

**2. The judge is code, not an LLM.** The persona writer sees the description and the spec's slot list (names,
types, options), but not its lines, states or tools. It writes each persona's facts against those slot names.
Code compares them with the final slot values and the arguments of every tool call:
- exact for choice, number, money, duration, date and time;
- case-insensitive word match for names;
- every word of the persona's value present, after normalising, for text and email.

The judge-reliability check in "Reported" is dropped, because there is no LLM judge. Instead, Claude reads 12
random calls and reports any where the code's verdict looks wrong.

**3. The simulated caller uses the same append-only layout**, so it sees the whole call without paying for it
again each turn. The idea of giving it a short memory is dropped.

The run stays at 48 calls. On the free tier it may span days, which the rules already allow.

## Amendment 2 (21 Nov 2026, before any Milestone 5 run): the cache layout measured on Groq, and dropped

Abhay ran `m5/cache_probe.py --llm groq --repeat 2`: the same typed gym call twice, 65 s apart, on
`openai/gpt-oss-20b`. The free-tier rate-limit headers showed 1,000 requests per day and 8,000 tokens per minute.

| | Call 1 (cold) | Call 2 (warm, same prompts 2 minutes later) |
|---|---|---|
| Prompt tokens Groq reported | 4,924 (3 requests; 4 streamed replies were cut short before Groq's count arrived) | 9,335 (6 requests) |
| Served from Groq's cache | 0 (0%) | 3,328 (36%): 1,280 + 1,024 + 1,024 |
| Requests that could hit but didn't | all | 3 of 6, including the call's first request, identical to one sent 2 minutes earlier |

What this shows:
- Groq caches in 256-token steps from a minimum of 1,024 (the hits were 1,280 and 1,024), so a 1,500-token
  request saves at most about two thirds.
- Hits are unreliable at our volume. Identical prompts a minute or two apart missed about half the time.
- The cache layout was 1.87 times larger: 43,410 characters of prompt for the same call, against 23,264 for
  the Milestone 4 prompts. It carries every intent and field, the whole call, and both kinds of task. Even
  warm, at 36% cached, it counts about 1.2 times the tokens of the compact prompts.

**Decision:** the compact Milestone 4 prompts are restored. Amendment 1's point 1 is withdrawn, and so is its
point 3 (the caller's prompts stay compact too). What stays:
- the probe;
- Groq's token counts and rate-limit headers recorded on every request;
- a test that fails if one gym call's prompts grow past 26,000 characters;
- point 2 of Amendment 1, the judge in code.

Caching can be tried again if the prompts or Groq change. The measured numbers above are the baseline.

**Also found by the probe and fixed:** in the first probe run, Groq wrote the fees as "₹१,५००" (Devanagari
digits and a rupee sign), and the guard let it through. The guard now refuses digits in any script and the
signs ₹, $ and %. There is a test for it.

**Budget, re-estimated from these numbers:**
- About 7,000 prompt tokens and 8,000 in all per agent call. That is about 380,000 for 48 calls on
  `gpt-oss-20b`.
- About as much again on `gpt-oss-120b` for the callers and the setup.
- With 200,000 tokens per model per day, the judged run takes about two days on the free tier.
- The simulator paces itself to stay under 8,000 tokens per minute, so it runs about one call a minute.

**Checks:** 42 of 42 typed loan calls correct with 0 safety violations; 176 tests pass.

## Amendment 3 (21 Nov 2026, before any Milestone 5 run): how the parts were built

These are choices made while building. None changes a rule or a threshold.

**Engine defaults** (`laghu_voice/dialog/defaults.yaml`). The defaults give a spec:
- 19 lines, in male and female forms;
- the timing;
- the mock hand-over tool;
- the hand-over, goodbye and hang-up states;
- the global routes.

Default states are added only when something reaches them. The gym spec now relies on them (253 lines down to
211). The loan spec keeps its own wording for these lines: it differs from the defaults, and Milestone 4 is
closed.

**Checker:**
- *Option phrases.* An option named in a sentence of the question that names no other option is an error, when
  the line also lists the options. The first rule, "named twice", also refused the loan's "अपना काम या
  बिज़नेस" ("own work or business"): two words for one option, inside the list.
- *Numbers.* A number in a line that isn't in the facts, the tools' data or a slot's limits is an error in a
  generated spec, and a warning in a spec a person wrote. A person's example answer ("तीन लाख", "three lakh")
  is fine there. Whole numbers up to 10 are allowed ("दो मिनट", "two minutes").
- Every ending has an outcome, and a tool that commits runs only straight after a yes. Both are errors in every
  spec. The loan and gym specs now state their outcomes.
- Warnings: a greeting whose yes leads to a name question without `also`; a choice question that names no
  options; a fact listing three or more things without the count.

**Engine:**
- A state may route `corrected` (a value changed through `corrections`).
- "शाम नहीं, सुबह" ("not evening, morning") and "तीन नहीं, चार" ("not three, four") now read as the second
  option or number.
- A `number` slot takes a count with a unit too ("तीन साल", "three years"), except rupees and percent.

The setup guide gives one pattern before any tool that commits: a confirm state that reads the details back and
takes corrections, and a fix state. In the fix state, "no" ends the call as declined, so a caller who doesn't
want to go ahead isn't asked again and again.

**Setup tool:**
- `openai/gpt-oss-120b` with reasoning effort low. Medium was tried in the design and runs past 8,000 tokens a
  minute.
- Each request is sized so that its prompt and its longest reply fit in 7,500 tokens.
- Repair requests carry the whole flow, the lines and slots the problems name, and everything else shortened.
- The setup's own test calls are 8 callers, 1 run each. Only the failed ones are rerun after a repair, with
  at most 2 repair rounds.
- `laghu_voice/services/paced.py` keeps every batch request under the per-minute limit. It waits out short
  429s, so they never become fallback lines, and stops cleanly at the daily limit. `m5/simulate.py` then
  resumes where it stopped.

**Checks before the first Groq run:**
- 184 tests pass;
- 42 of 42 typed loan calls correct, with 0 safety violations;
- with stand-ins for both LLMs, the setup tool ran end to end on a small library use case: a checker error
  repaired in one round, then 8 of 8 test calls passed, including the corrector (fixed at the read-back),
  the refuser (declined) and the human-seeker (transferred).

## Amendment 4 (2026-11-21, after the first real setup run, before any judged run)

The first run of the setup tool on `mba.md` (gpt-oss-120b) ended "NOT OK" after 3 repair rounds: 12 checker
errors, then 1, then 11. Causes found in its output, and the changes. No rule above changes.

- **Repairs replaced whole items**, so a repair that sent only part of a slot left it without a `type`, and
  that one error hid the other eleven. Now a repair item with only some keys of a slot or state is merged into
  the existing one, and the shape error names the slot.
- **The model kept missing three things a program can fix.** The setup tool now fixes them by code after every
  draft and repair (`normalize`): an ending's missing `outcome` (taken from the state's name: decline → declined,
  book/confirm/callback → success, transfer → transferred, silence → no_contact, fail → failed; no match → still
  an error); a re-ask written as a Hindi sentence instead of a line key (the sentence becomes a line); an
  acronym in English letters (MBA → एमबीए). The review shows every outcome, so a wrong guess is visible.
- **The checker flagged a hand-over as an unconfirmed action.** An intent found by its phrases may now lead to a
  tool that doesn't commit (the built-in hand-over). A tool that commits still needs a yes first.
- **Checker messages say how to fix** (the English words found, the outcome key to add).
- **The guide** now says: re-ask values are line keys; every ending has an outcome; global targets must exist;
  an intent the agent must not answer (scholarship, guarantee) goes to a state with an llm line and
  `next: handover`; never define a hand-over tool.
- Repair rounds for the checker: 3 → 5. A round costs about 5,000 tokens.

Second review of these changes, the same day, before any run:
- The checker's errors now travel as a list. Before, a message containing "; " was split in two, so the model
  got half a sentence.
- Shape errors are all reported at once (one broken slot no longer hides the others), and a `name` key inside
  an item is ignored instead of crashing.
- An intent's phrases may lead straight to the built-in hand-over only. Any other tool still needs a question
  first, as in M4.
- Outcome guessing never calls a negated name a success ("no_booking", "not_confirmed", "cancelled" stay
  unset and go back to the model). A wrong outcome word ("completed") is mapped too.
- Repairs that send part of a tool or an intent are merged as well. Removing a state no longer deletes the
  English of a line with the same key.
- Acronyms are also spelled out in caller phrases and intent phrases (transcripts are in Devanagari), and
  next to Hindi letters ("MBAकी").
- Lines without an English meaning get one in a last small request, so the review has no blanks.
- The guide: success is the call's goal reached, including a callback the use case counts as done;
  transferred is handed to a person because the agent couldn't help. "A request for a person" is the built-in
  intent and no longer listed as one to define.
- Tests: 193 pass.

## Amendment 5 (2026-11-22, after the second real setup run, before any judged run)

The second run on `mba.md` passed the checker after one repair round. Then 6 of 8 test calls ended "transferred"
(only the refuser and the human-seeker passed), and the first test-call repair crashed: Groq rejected the reply as
invalid JSON (`json_validate_failed`). The crash lost every test call, because they were written only at the end.
No rule above changes.

- **Likely cause of the transfers** (not confirmed: the transcripts were lost): a booking tool whose mock answers
  match no call. With no match the tool fails, and the call goes tech_problem → hand-over → "transferred". Only the
  callers who reached the booking failed. The checker never required a mock answer for any values. Now:
  - a mock condition on a choice slot must use an option key;
  - the list must end with an answer without `if`, unless its answers cover every option of one choice slot.

  The setup tool fixes two cases by code: a label or phrase used as the value becomes the key, and a tool that
  saves no data gets a final answer for any values.
- **The crash.** The repair request carried 6 failed calls with their transcripts, leaving little room for the
  reply. The model also rewrote unchanged lines, so the reply was cut off. Now:
  - failed calls that went wrong the same way are sent once, with a count, and at most 3 kinds are sent;
  - the request asks for changed items only;
  - a JSON-mode rejection is retried once without JSON mode;
  - a failed repair keeps the spec that ran and is reported in the review.
- **Nothing is lost.** Each test call is written to `test_calls.jsonl` as soon as it ends, and `spec.yaml` is
  written before the test calls and after each repair. If setup stops, the review is still written and the
  terminal says where everything is.
- **The log says why a call failed:** a tool that failed, the last states, the caller's last event.
- **Option keys in braces** in a line ("{full_time}") become the option's Hindi label (the run's first checker
  errors).
- "OK" at the end now means the checker passed *and* every test call passed.
- Tests: 197 pass.

## Amendment 6 (2026-11-22, after the third real setup run, before any judged run)

The third run on `mba.md` passed the checker, then 6 of 8 test calls ended "transferred" in round 1, and 0 of 6
in rounds 2 and 3, until Groq's daily limit stopped it. Every call and its transcript were kept, and they show
that **no call reached the booking**. The failures were in the engine and the simulator. No spec repair could
fix them, which is why two repair rounds changed nothing. Amendment 5's guess (a mock that matched nothing) was
wrong for this run; its checker rule stays. No rule above changes.

**Simulator:**
- The agent's live-call timeouts (3 s to the first word, 8 s for a reading) counted the time a request waited in
  `PacedLLM` for Groq's per-minute limit. At the start of a call that came right after a long one, the reading
  timed out ("unclear" for a plain "हां अभी बात कर सकती हूँ") or the reply did ("nothing written", so a
  fallback: the fee question got "our team will tell you"). Test calls now allow 180 s. They judge what the agent
  says, not how fast.
- The caller is told today's date and the date its day falls on, and says it as people do (कल, शनिवार, पाँच
  दिसंबर).

**Engine:**
- A day for an appointment: `time` read only आज/कल/परसों and "N दिन". "पाँच दिसंबर सुबह", "शनिवार" and "अगले
  सोमवार" were read as **today**. Now:
  - weekdays, "<day> <month>" (next year if the date has passed) and "<day> तारीख" (next month if passed) are read;
  - an hour gives the part of the day ("दस बजे" is morning);
  - a day that is named but not understood goes to the LLM, never to today. The LLM is given today's date and
    weekday;
  - a time slot's `min`/`max` are days from today ("max: 14"), and a day outside them is out of range;
  - `{x:time}` reads back the day itself ("शनिवार, पाँच दिसंबर सुबह"), not "13 days later".
- Words joined by the hyphens a model writes ("पूरा‑समय", U+2011) were one word, so a caller's "पूरा समय" matched
  nothing. Every hyphen now splits words.
- "X नहीं पता" ("I don't know") was read as "not X" by the M4 denial rule, so an undecided caller was recorded as
  the other option. "नहीं पता", "नहीं मालूम" and similar are not denials.
- The guard read "8.5 lakh rupees" in the facts as 8.5 only, so a correct "साढ़े आठ लाख" would be blocked. Amounts
  written in English in the facts (lakh, crore, thousand) are now allowed in Hindi words, in the guard, the checker
  and the judge.
- `back` after a detour that only says a line (a scholarship question) went to the question before the current
  one: the greeting. It now returns to the question the caller was on when the intent came. A detour that waits
  (the gym's trial question) still returns as before.

**Checker** (all specs; the gym and loan specs pass unchanged):
- digits in a fixed line or an example ("30‑मिनट" was said as digits on every call: safety (c));
- a slot placeholder without a format ("{session_time}" would be said as "5:morning");
- a state that says a question but doesn't wait for the answer ("shall I book it?" followed at once by "which
  day?");
- a `date` slot without `min_age`. `date` is a private type for a date of birth: the LLM may never read it, so a
  session day was never collected.

**Setup tool:**
- Fixed by code after every draft and repair: digits become Hindi words (30 → तीस, 8.5 → साढ़े आठ), placeholders
  get their type's format, and odd hyphens become spaces.
- The guide says:
  - one `time` slot for a day to meet, with `max`;
  - an offer is a yes/no state;
  - a question the agent must not answer says its line and goes `back`, so the call goes on. It hands over only
    if the owner says so;
  - option phrases include short forms.
- If a repair round leaves every failed call failing the same way, setup stops repairing and says the problem is
  likely in the engine. The run above spent its last 60,000 tokens on two such rounds.
- `CALLER_MODEL` (optional) runs the test callers and the persona writer on another model with its own daily limit.

**Checks:** 205 tests pass, and the loan regression (scripted readings, 2 runs) is 42/42 with 0 safety
violations. The MBA callers' own words from this run (P1, and P5 with the scholarship question) now reach the
booking with the engine's rules alone.

Addendum, 2026-11-22 01:30: gpt-oss-120b's daily limit was used up, so the next development run of setup on
`mba.md` uses `SETUP_MODEL=qwen/qwen3.8-27b` (Groq's free tier now lists only gpt-oss-120b, gpt-oss-20b and Qwen
3.8 27B for chat, each with 200,000 tokens a day). Reasoning settings are now chosen per model (Qwen rejects
gpt-oss's `include_reasoning`), and any `<think>` text in a reply is removed. The setup model for the judged run
stays gpt-oss-120b (Amendment 3) unless a later amendment, written before that run, changes it.
The first Qwen run stopped at the first drafting request: two empty replies (the thinking at effort low used the
reply's tokens). An empty or cut-off reply is now asked again with reasoning off (`reasoning_effort: none`, Qwen
only; gpt-oss can't go below low), instead of the same request twice. Each run moves the last run's files to
`previous/<time>/`, so a run that stops early isn't mistaken for the last one.

Addendum, 2026-11-22 13:30: Groq's daily token limit is a rolling 24-hour window (a 429 at 00:45 IST said "try again
in 4m39s"), so last night's runs still counted at 13:19 and the morning run on gpt-oss-120b stopped at the limit.
Qwen 3.8 27B can't draft (Groq's free tier allows it 1,000 output tokens a minute, and a draft reply needs more),
but it can be a test caller (about 60 tokens a turn). Development runs may set `CALLER_MODEL=qwen/qwen3.8-27b`: the
caller turns go to Qwen (thinking off, 150 tokens a reply), and the persona writer stays on the setup model. The
judged run's caller model is decided in an amendment written before it.

## Amendment 7 (2026-11-22, after the fourth real setup run, before any judged run)

The 13:00 run (gpt-oss-120b) passed the checker after one round. Then 2 of 8 test calls passed, and the 120b daily
limit stopped the repair round. The timeout fix of Amendment 6 worked: no call had a "nothing written" fallback.
The transcripts show the next problems. All of them are in the engine or the simulator, not in the spec. No rule
above changes.

**Engine:**
- **A yes with details was unclear.** At the greeting and the counselling offer, "हाँ मैं अमित शर्मा हूँ पुणे से" and
  "हां बुक कर दो बुधवार पच्चीस नवंबर सुबह" were unclear three times, then handed over. This is P1–P4. The engine
  only took the details a state lists in `also`. Now:
  - any slot the caller gives before being asked is kept, and its question is skipped when the flow reaches it;
  - choice slots are read by the rules from any answer; other slots (a day, a number, a city) by the LLM, when a
    yes with details goes to it;
  - if the rules read a yes or an answer and the LLM can't place the whole turn, the rules' reading stands;
  - details without a yes count as a yes at a question like "can we talk?" or an offer, but never at a read-back
    before a commit (`corrections`, or a yes that reaches a commit tool).

  A long answer the rules read is not sent to the LLM for its other details: it stays as fast as before, and the
  loan's rules/LLM split is unchanged (342/54).
- **Dates were hidden from the LLM.** `mask_for_llm` masked any month name, because in the loan a date can only be
  a date of birth. "पच्चीस नवंबर" for a counselling session never reached the LLM. Month names are now masked only
  when the spec collects a date of birth. Long digit runs (phone numbers, passcodes) are masked in every spec.
- **A loop of 30 turns (P6).** "हां … कॉल बैक कर दो" at "would you like a callback?" matched the global
  callback intent, which led back to the same question. A global request that leads to the question already being
  asked is no longer a detour. It is read as a yes where details may stand for a yes, and as nothing elsewhere. A
  state's own route back to itself (the gym's discount asked again) is meant, and stays. A safety net covers every
  spec: three turns in a row that change nothing (no state, no value) hand the call over.
- **Read-backs say the weekday and date for कल and परसों too** ("कल, सोमवार, तेईस नवंबर, सुबह"). P5 said "सोमवार"
  meaning 30 November; the agent took the coming Monday, read it back as "कल", and the caller didn't notice.

**Simulator:**
- The caller is told:
  - give a value only when asked (or when its behaviour says to give details early), since facts may hold values
    for paths it won't take, like a callback time when it books;
  - want what the agent offers unless its behaviour says otherwise (P6 had invented being busy);
  - say a day with its date;
  - correct a wrong read-back.
- The judge treats a city's two English names as one (Bangalore, Bengaluru).

**Setup tool:** a slot no state asks for and nothing reads is dropped (the draft's phone number, from the owner's
answer "phone"). The guide says so too.

**Checks:**
- 214 tests pass. They include this run's spec (`tests/fixtures/mba_spec_2026-11-22.yaml`) with the callers' own
  words, for P1's yes with the day, P2's details instead of a yes, P3's yes the LLM can't place, and P6's callback.
- The loan regression is 42/42 with 0 safety violations.

Addendum, 2026-11-22 15:30: the 15:17 run stopped at gpt-oss-120b's daily limit after 3 drafting requests, and every
restart drafted from the beginning again. Drafting now keeps each finished step (facts and slots, the flow, each
batch of lines) in `m5/out/setup/<name>/cache/<key>/`. The key covers the description, the answers, the guide and
the model. A run with the same key reuses those steps instead of asking again. The daily-limit message now says the
window is the last 24 hours. Until gpt-oss-120b frees up, development test calls run with `m5/simulate.py` on the
13:00 run's spec and personas: the agent on gpt-oss-20b, the callers on Qwen. Tests: 215 pass.

## Amendment 8 (2026-11-22, after the fifth real setup run, before any judged run)

The 23:30 run (gpt-oss-120b drafting, Qwen callers) passed the checker with no repair round, for the first time.
Four test calls ran before a ReadTimeout stopped it:
- P1 (cooperative) booked, with every fact right and no fallback;
- P2 (over-answerer) had its program and city kept from the first answer and wasn't asked them again;
- P4 caught a wrong day from the weekday in the read-back and corrected it.

The four calls show these gaps. No rule above changes.

**Engine:**
- **A count of zero:** `number` took only values above 0 from the LLM, so "कोई कार्य अनुभव नहीं है" (no experience)
  was unclear three times, then a hand-over (P3). A `number` slot now takes 0.
- **Corrections only the LLM can read:** at a read-back, the rules read corrections, and the LLM was asked only for
  yes or no. A correction the rules couldn't read was lost, and P2 went round the read-back until it gave up. The
  LLM now also reads the state's `corrections` slots (never private ones). A changed value is a correction, read
  back again.
- **Days:** an impossible date ("शुक्रवार सत्तर नवंबर", "Friday, seventy November") now falls back to its weekday.
  A weekday and a date that disagree ("गुरुवार छह दिसंबर", a Sunday) are not settled by the rules; the LLM reads
  them.

**Checker:** an ending state's line must not ask a question. The run's "booked" line ended with "क्या यह सही है?"
after the booking was made.

**Batch requests:** `PacedLLM` retries a dropped connection or a timed-out reply after 5, 15 and 45 s (two runs
were lost to one ConnectError and one ReadTimeout). Live calls don't use it.

**Not changed:** P4 said 5 years of experience instead of 1 and never corrected it. The read-back the owner asked
for (day, time, program) doesn't include experience, so the caller had no prompt to correct it. The caller didn't
follow its persona; the engine did what it was told.

**Checks:** 220 tests pass, including this run's spec (`tests/fixtures/mba_spec_2026-11-22b.yaml`) with P3's and
P2's own words.

## Amendment 9 (2026-11-23, after the sixth real setup run, before any judged run)

The 00:00 run passed the checker after 2 repair rounds; 5 of 8 test calls passed before the gpt-oss-120b daily limit.
Reading every call, including the passes, found these. No rule above changes.

**Judge:** a value the caller gave before being asked was never checked, because only asked questions were judged.
P2 "passed" with the session booked today, morning, instead of Friday evening. Questions skipped because their
answer was already given are now checked too. This can lower pass counts; it makes them true.

**Engine:**
- A day given with a yes at the offer counted as no yes. The check looked for the slot's name, but a time comes back
  as `<name>_days` and `<name>_part`. Values volunteered in this turn are now tracked by slot (P5).
- A longer turn that starts with a yes and takes nothing back ("जी हाँ मैं मनीष कुमार हूँ बोलिए": seven words, past
  the yes rule's six) is a yes when the LLM can't place it. This applies only where details may stand for a yes,
  never at a read-back before a commit (P7).
- Two different numbers in an answer ("पहले दस बताया था, सही चार है") go to the LLM instead of the rules taking the
  first one (P4).
- A date up to 31 days past ("शनिवार बीस नवंबर" on 23 November) is a slip: its weekday is used if given; otherwise
  the LLM reads it. Before, it moved to next year and was out of range. A value out of range gets the new default line
  `out_of_range` ("that isn't possible; please say one within …"), not "I didn't understand".

**Checker and setup:**
- A question that says the value it asks for ("{program:words}" in the program question, empty when asked) is an
  error, and setup replaces it with the options in words.
- A format that doesn't fit the slot's type ({program:words}) is an error.
- In a generated spec, a choice question that names no options is now an error, not a warning.

**Simulator:** each test caller is given the exact Hindi words for its day ("कल, सोमवार, तेईस नवंबर, सुबह") and is
reminded of its behaviour every turn. Qwen callers said wrong dates (P4, P6) and P8 never asked for a person, so 3 of
the 8 results depended on the caller as much as the agent.

**Checks:** 227 tests pass, including this run's spec (`tests/fixtures/mba_spec_2026-11-23.yaml`) with its callers'
own words. The loan regression is 42/42 with 0 safety violations.

## Amendment 10 (2026-11-23, after the seventh real setup run, before any judged run)

The 12:55 run of setup on `mba.md` finished OK, the first to do so:
- the checker passed after 1 repair round;
- **8 of 8 test calls passed**, every fact checked, including those given early (Amendment 9);
- it used 43,000 gpt-oss-120b tokens (drafting and repair), 55,000 gpt-oss-20b (the agent) and 92,000 Qwen (the
  callers).

The judge flagged one call with a safety problem; reading it found one false alarm and one real risk. No rule above
changes.

- **A real risk: a correction the LLM invented.** At the read-back, P6 said only "हाँ सही है ठीक है धन्यवाद". The LLM
  still returned a day, and the booking moved to परसों before the caller set it right. Corrections read by the LLM
  (Amendment 8) are now taken only when:
  - the caller didn't say yes; and
  - the turn mentions something of the slot's kind (a day, a number or "कोई", an option). A name or a city has no
    such check.
- **A false alarm: an earlier day in a read-back.** The judge, and the guard, allowed only the final value's day of
  the month, so "कल, मंगलवार, चौबीस नवंबर", read back before the caller corrected it, counted as an invented number.
  Every value a time slot held in the call is now allowed.
- **The guide:** don't confirm each answer with its own question; the read-back before the commit confirms them all.
  The run's spec asked "you chose X, right?" after every answer, which roughly doubled the calls' length.

**Checks:** 230 tests pass, including this run's spec (`tests/fixtures/mba_spec_2026-11-23b.yaml`) with P6's words.
The loan regression is 42/42 with 0 safety violations.

**Next:** `clinic.md` is the second development use case. If it passes without new engine fixes, the engine is
frozen for the judged run, and Abhay writes the three held-out descriptions.

## Amendment 11 (2026-11-23, after the first real setup run on `clinic.md`, before any judged run)

The 13:42 run on `clinic.md` (the second development use case) passed the checker with no repair. 3 of 8 test
calls passed after 3 rounds. As predicted before the run (Amendment 10's note), it hit what the MBA case never
asked for:
- **rules over several answers** (Dr. Khan works only Monday, Wednesday and Friday mornings);
- **values the business works out** (the doctor from the problem and the age).

The spec "chose" the doctor with a line, and lines only speak, so the doctor was empty or wrong. Bookings broke the
schedule (Dr. Khan on a Saturday, Dr. Iyer on a Sunday), and the judge didn't see it. No rule above changes.

**Engine:** two features, so both are a tool, the business's own system, as a real clinic backend would answer them:
- a tool's `save` into a slot name sets that slot (a choice only to one of its option keys);
- a time slot is visible to tools as `<slot>_weekday` (mon … sun), `<slot>_part` and `<slot>_days`. Mock answers
  can list the allowed combinations, and an `unavailable` event clears the time and asks again.

**Checker** (all specs; the gym and loan specs pass unchanged):
- a line that says a slot no state asks for and no tool sets is an error: it can be said empty ("रोगी , आयु ...",
  with the name heard only if given at the greeting);
- a one-word intent phrase that the agent's own lines say, where the intent leads to a hand-over, a tool or an
  ending without a question, is an error. "कुछ नहीं बदलना है" at the fix question matched the cancel phrase
  "बदलना" and handed the call over. A route that says a line and goes back is harmless and allowed.

**Guide:**
- every schedule and rule the description gives goes in knowledge (the draft dropped the doctors' days);
- lines only speak; a worked-out value or a rule over answers is a non-committing tool before the read-back, and
  the guide gives the pattern;
- a description is routed with a choice slot of categories;
- the fix question asks "go ahead, or not now", and the caller can also just say the change. "What should change?"
  alone made "nothing" a no and declined P1's booking.

**Simulator:**
- the caller is given numbers in Hindi words. Qwen said चौयासी (84) for 34, अस्सी (80) for 28 and अठारह (18) for 38,
  so most "wrong age" failures were the caller's;
- the persona writer keeps the description's rules (no Dr. Khan on a Saturday);
- free-text slots of more than two words ("joint pain in knees") are matched on one shared word stem, not word for
  word ("knee pain").

**Checks:** 233 tests pass, including this run's spec (`tests/fixtures/clinic_spec_2026-11-23.yaml`) and a clinic
spec that uses both features (Dr. Khan refused on Saturday, booked on Wednesday).

Addendum, 2026-11-23 14:30: the second clinic run took up the guide's tool pattern (a `select_doctor` tool with a
"doctor unavailable" outcome). It stopped at gpt-oss-120b's daily limit in the second checker repair round. The
checker's repairs are now kept (`cache/<key>/repaired.json`) like the drafting steps, so a stopped run resumes from
the last repair. Tests: 234 pass.

Addendum, 2026-11-23 16:30 (no judged run yet; this changes no pass/fail rule): each failed test call now carries a
`diagnosis` in test_calls.jsonl, `{"cause": "spec" | "agent" | "caller" | "judge" | "unclear", "why": [...]}`, worked
out by code from the record (`setup/simulate.py: diagnose`): a tool with no mock answer is the spec; a fact the
caller's own words never gave is the caller; a fact the caller gave and the engine didn't keep is the engine; a
free-text value that shares a word stem is the judge. It is shown in the review and the web UI only. The judge,
the success rule, the safety checks and what the repair request is sent are unchanged. Setup also reports its
progress as events (`run_setup(events=...)`) for the web UI. Tests: 248 pass.
