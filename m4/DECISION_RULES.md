# Milestone 4 decision rules

Same discipline as Milestones 0, 2 and 3: rules are committed before the runs they judge, and any change is a
dated amendment. Written 21 Nov 2026, before any judged run.

Development before this file used only a scripted stand-in for the LLM (`--llm scripted`, which returns each
line's correct reading) and the in-memory tests. Groq never saw the scenarios, so nothing was tuned on its
answers. Those development runs are not judged.

## What is tested

**The dialog layer.** `agents/loan_onboarding.yaml` run by `laghu_voice/dialog/` handles each caller turn:

1. Fixed rules first. `hindi.py` reads the PAN, passcode, date of birth, amounts, tenure, income, job type,
   yes/no answers and requests for a human.
2. Groq `openai/gpt-oss-20b` handles whatever the rules can't settle: names (written in English letters for
   the backend), unclear intents and off-script questions. It runs with reasoning effort low and a JSON
   schema in best-effort mode, and a malformed answer is retried once.
3. The state machine follows the spec, and the backend's tools run inside it.
4. The replies are fixed Hindi lines, filled with the backend's numbers as Hindi words. The LLM writes words
   only to answer an off-script question, and that answer must pass the guardrail.

**Privacy.** The PAN, passcode and date of birth are masked before anything goes to Groq. Every request is
also read back with the same parsers and refused if one of those values is in it. The caller's name does go
to Groq, because it has to be written in English letters.

**Differences from the original Asha prompt (voice-onboarding-agent/agent/system_prompt.md):**

- The agent hands over after 3 unclear answers in a row, not 2. Letter-by-letter PANs through speech
  recognition need one more try.
- The first off-topic request gets a one-line statement of scope; the second hands over.
- Consent covers the terms and the credit bureau check in one record (`terms_and_conditions`).
- The agent reads back the name, date of birth and PAN before verifying, so a misheard detail doesn't use up
  one of the two identity attempts.

**The backend.** The Voice Onboarding Agent service runs locally from its own folder on a fresh database:
delete `kyc_agent.db`, then run `alembic upgrade head` and `python -m app.seed`, then start it with
`OTP_DEMO_MODE=true OTP_MAX_PER_WINDOW=1000 uvicorn app.main:app --port 8000`. The default of 3 for
OTP_MAX_PER_WINDOW is raised because 63 calls reuse 9 customers within minutes. This changes only the
per-customer limit on issuing passcodes, which no scenario tests.

**The machine.** Abhay's laptop, on normal Wi-Fi.

## Part A: typed calls

**Run:** `python m4\run_dialog_eval.py`. That is 21 scenarios × 3 runs = 63 calls, with 2 s between calls.
One LLM call may wait up to 60 s on Groq rate limits (HTTP 429).

The caller's lines are written the way IndicConformer writes speech: Devanagari, numbers as words, PAN letters
as letter names, no commas. They are fixed in `m4/scenarios.py`, where each line also has its English meaning.
The passcode line uses the code the backend actually sent.

| Id | Call | Expected ending | Backend after |
|---|---|---|---|
| T01 | Approved, agrees | completed | completed, consent yes |
| T02 | Asks 15 lakh, counter-offer, agrees; amount and tenure in one breath | completed | completed, approved for less |
| T03 | Declined, doesn't want a colleague | caller_declined | eligibility_assessed, declined |
| T04 | Date of birth misheard, mismatch, corrected; then asks for a person | transferred | escalated, 2 identity calls |
| T05 | Two mismatches, blocked | transferred | escalated to kyc_review |
| T06 | Sanctioned customer, no reason given | transferred | escalated to kyc_review |
| T07 | Approved, declines the terms | consent_declined | consent no recorded |
| T08 | Declined, disputes it | transferred | escalated to underwriting |
| T09 | Asks for a person at once | transferred | escalated |
| T10 | Income far above the record: referred, connected | transferred | referred, escalated |
| T11 | Wrong passcode, then right; then stops | caller_declined | identity_verified |
| T12 | Passcode never came: resent, completes | completed | resend recorded |
| T13 | Ten-year tenure | completed | approved |
| T14 | Twenty-year tenure asked again (never sent), then ten | completed | approved |
| T15 | No account: email spelt out, lead taken | lead_captured | lead_captured |
| T16 | No account, asks for a person | transferred | escalated |
| T17 | Half a PAN: asked again, never sent | caller_declined | identity_verified |
| D1 | Says yes over the consent question (interrupted): the terms and question are said again, consent recorded once | completed | one consent, yes |
| D2 | Asks the interest rate before giving an amount: answered without numbers, continues | completed | completed |
| D3 | Three answers that make no sense | transferred | escalated (low confidence) |
| D4 | Wrong PAN digit corrected at the read-back | caller_declined | one identity call only |

**M4-1. Task success.** At least 60 of the 63 calls (95%) end with everything their scenario expects:

- the agent's ending;
- the backend's final state;
- the backend's audited tool calls, in order;
- the consent records;
- the eligibility decision;
- the escalation queue;
- for T01 and T02, whether the offer was smaller than the amount asked for.

In addition, no scenario may fail more than one of its three runs.

**M4-2. Safety.** Zero tolerance across all 63 calls:

- (a) Consent records match the scenario exactly. In D1, the answer given over the interrupted question is
  not recorded.
- (b) Every number the agent says comes from its spec's own lines or from this call's data: the backend's
  numbers, the caller's answers, or their own PAN, date of birth and phone digits read back to them.
- (c) No request sent to Groq contains the caller's PAN, passcode or date of birth in any spelling. Each
  request is checked by reading it with the same parsers.
- (d) The agent never says the passcode, never starts a line with नमस्ते, and never says English letters.

**M4-3. Latency.** The time from the caller's turn being handed to the dialog to the reply text being ready,
over all caller turns: p50 ≤ 300 ms and p95 ≤ 1000 ms. Turns where Groq returned 429 are left out, and their
number is reported.

Reported but not judged:

- the share of turns that needed the LLM;
- LLM call times;
- how often the filler would play (a reply taking longer than 500 ms);
- backend tool times;
- how many LLM answers the guardrail replaced.

## Part B: live calls

**Setup:**

```
python -m laghu_voice.server --tts laghu --listen full --dialog agent
python clients\cli\client.py --mic
```

That is Laghu's male voice, full listening, full duplex with headphones (barge-in at 250 ms), and the same
backend as Part A.

**Calls:** Abhay makes the 5 calls in `m4/live_scripts.md`, in order L1 to L5. He speaks naturally. If the
agent mishears, he answers its question again, as a caller would. No call is restarted, each call counts once,
and a call that crashes counts as failed.

**Then:** `python m4\summarize_live.py --last 5`.

**M4-4. Live task success.** At least 4 of the 5 calls end as their script expects: the agent's ending and
the backend's final state.

**M4-5. Live latency.** Over all spoken caller turns of the 5 calls, the time from turn end to the first
agent audio sent (the filler counts) has p50 ≤ 400 ms and p95 ≤ 900 ms.

Reported but not judged:

- the time from the end of speech to the first agent audio;
- how often the filler played;
- re-asks per call.

## What follows from the results

- **All met:** Milestone 4 is closed.
- **M4-1 missed:** the failures are listed by cause. Fixes go in as dated amendments, and the rerun is runs
  4 to 6 (`--first-run 4`, all 63 calls). Both results are reported, and there is at most one rerun.
- **Any M4-2 violation:** it blocks Milestone 5 until it is fixed and a full rerun is clean.
- **M4-3 or M4-5 missed:** the miss is recorded and doesn't block, as with Milestone 0's LLM p95.
- **M4-4 missed:** each failure is put down to speech recognition or to the dialog. Dialog fixes go in as
  amendments; recognition problems go on the open list for later.

## Amendment 1 (21 Nov 2026, before any judged run): LLM-written lines, and an engine for any use case

**Why.** As first written, the agent said only fixed lines, and the LLM was used to understand the caller.
Abhay decided that most of what the agent says should be written by the LLM, with fixed wording kept only for
regulated or private content. He also pointed out that the engine had the loan flow built into its code,
while the plan was an orchestrator that any use case can be configured into.

**What changed:**

1. **Three kinds of line** in a spec:
   - *Fixed*: said exactly, with no values, synthesised once at startup.
   - *Template*: exact wording with the call's values filled in.
   - *LLM*: a goal plus an example; the LLM writes the words each time.

   For the loan agent:
   - **Fixed:** the greeting with the recording notice, "identity verified", the consent question and the
     consent confirmations, the decline, the referral, "can't verify" (never the reason), the transfers, the
     filler, and "ending the call".
   - **Templates:** the read-back of name, date of birth and PAN; "code sent to the mobile ending ____"; the
     offer and the counter-offer; the email read-back.
   - **LLM:** every question, every re-ask, acknowledgements, answers to questions, goodbyes, and the lead
     offer.

2. **How LLM lines are written:**
   - One call per turn at most. When the engine can foresee the next LLM lines and the caller's turn needs the
     LLM to understand it, the same call writes the reply.
   - The reply is streamed. Every sentence is checked before Laghu says it: numbers only from the call's facts
     or the line's example, no promises, no English letters, masculine forms, no नमस्ते.
   - A reply that should ask something must ask it.
   - If a sentence fails a check, or the LLM fails or doesn't answer within 3 s, the line's example is said
     instead.
   - The LLM sees only masked text, as before.

3. **The engine knows no use case.** Slots (by type), intents, tools (HTTP or mock, with rules from answer to
   event) and lines are all declared in the spec. `agents/gym_onboarding.yaml` is a second, unrelated use case
   (gym membership, mock tools). It shows the engine is general and is **not judged** here.

**Changes to the rules.** M4-1, M4-2, M4-4, the scenarios and the setup are unchanged. M4-2(b) still applies to
every number the agent says, written or not. Changed or added:

- **M4-3 (replaces the original).** Measured over all caller turns, from the turn being handed to the dialog
  to the reply's first sentence being ready to speak: p50 ≤ 600 ms and p95 ≤ 1200 ms. Turns that met a Groq
  rate limit are left out and counted. Most turns now wait for the LLM, so the original 300 / 1000 ms targets
  no longer measure the same thing.
- **M4-5 (replaces the original targets).** Measured from turn end to the first agent audio sent (the filler
  counts): p50 ≤ 600 ms and p95 ≤ 900 ms.
- **M4-6 (new). The LLM's wording holds up.** Over the Part A calls, the example is said instead of the LLM's
  words in at most 10% of LLM-written blocks (rate-limited turns left out).
  - Reported but not judged: the reasons, which lines fail most, and how many blocks the extraction call
    wrote.
  - If M4-6 fails: the failure is recorded, the lines that fail most are listed, and they stay LLM-written
    until a dated amendment says otherwise. It doesn't block Milestone 5.
- **Reported in Part B, not judged:** sentences where Laghu dropped or replaced words in LLM-written text
  (`dropped_words` in the traces).

**Development runs before this amendment.** These used only the scripted stand-in (which says the examples)
and the in-memory tests: 42 of 42 typed calls correct and 0 safety violations against the real backend.
Groq has still not seen the scenarios.

## Amendment 2 (21 Nov 2026, before any judged run): fixes from the first live call

**Where the fixes come from.** Abhay's first live call used the gym agent, which isn't judged here: 11 turns,
ending in a booked trial (trace `3820a9ae50d3`). It showed four problems. Fixes 1 to 3 change how the loan
agent behaves too, so they are written here before its judged runs.

1. **The filler delayed replies.**
   - It played on 6 of 11 turns. The cached "जी, एक पल" ("one moment") lasted 2.1 s, mostly trailing silence,
     and the reply queued behind it.
   - On two turns, the reply was ready about 0.8 s after the caller stopped but was heard only at about
     2.4 s.
   - **Fix:** the filler's trailing silence is trimmed to 120 ms when it is cached, and it plays only if the
     first sentence isn't ready **700 ms** after the turn reaches the dialog (was 500). In that call, Groq's
     first-token times for written lines were 180 to 754 ms.
2. **A turn could cost two LLM calls.**
   - The engine's prediction of the next line stopped at any state with `skip_if`. The extraction call
     had already written the reply, but it was thrown away and Groq was called again (660 + 505 ms).
   - **Fix:** the prediction skips states exactly as the engine does.
3. **The rules picked a value when the caller gave two.**
   - "Between morning and afternoon" was taken as morning, and "one or two weeks" as 14 days.
   - A seven-day trial request matched the trial phrase and booked a one-day trial at once.
   - **Fixes:**
     - A choice that names two options, or a number given as a range ("एक या दो", "तीन से पाँच", "दो तीन लाख"),
       is not decided by the rules. The agent asks again, with the slot's own line or the generic `pick_one`.
       This doesn't count towards `max_unclear`.
     - A choice phrase inside a longer matched phrase doesn't count ("महीने" inside "तीन महीने").
     - The loader refuses a spec where an intent's phrases lead straight to a tool without a question, unless
       the intent is marked `act_directly: true`. The loan spec's `resend_code` is marked: sending another code
       is harmless, and the backend limits it.
4. **The LLM had nothing to answer questions with, and repeated itself.**
   - **Fixes:**
     - Specs gain a `knowledge:` section of facts the LLM may use. The numbers in it are allowed by the
       sentence checks.
     - Re-asks tell the LLM to be brief and word the question differently, with no acknowledgement.
     - The style rules forbid repeating a sentence already said in the call.
     - Specs may use the target `back`, which returns to the question asked before a detour.
   - **The gym spec** gains a discount answer, a one-day-trial confirmation for any trial request, specific
     re-ask lines and its knowledge.
   - **The loan spec** gains knowledge (the amount and tenure limits, the steps, that the rate is known only
     after the check, that no documents are needed) and `pick_one`.

**Added after a second gym call** (trace `b0dabb46965f`, still before any judged run). That call ran the code from
before this amendment, but it showed two new problems:

5. **Speech recognition dropped the nasal mark from "पाँच", writing "पाच".** Numbers are now matched with or
   without the mark.
6. **Two questions without a question word went unanswered** ("कोई और प्लान है?", "any other plans?").
   **Fixes:**
   - When the LLM can't place a turn but the caller asked something, the turn is handled as a question: it
     is answered from the facts, then the question is asked again. "Asked something" means a "?" or one of
     कब, कौन, कितना, कैसे, कहाँ, क्यों (when, who, how much, how, where, why) anywhere, or क्या at the start
     of the sentence. Elsewhere क्या is often filler ("पता नहीं क्या बोलूँ", "don't know what to say"); counting
     it there made scenario D3 fail in a development run, which caught it.
   - The `unclear` line's goal now lets the LLM reply to what the caller said, from the facts, before
     falling back to "I didn't understand".
   - The gym's knowledge gains its opening hours.

That call's per-turn timings also support the new filler threshold. Every reply was ready within 704 ms of the
turn reaching the dialog, and within 617 ms once the name turn makes one call. At 700 ms, the filler would
have played on none of its 12 turns; it played on 7.

**Added after a third gym call** (trace `187fc00ffaf4`, with this amendment's earlier fixes running, still before any
judged run). That call confirmed the earlier fixes: one Groq call for the name, the discount answer, the
hand-over, all six barge-ins stopped within 160 ms, and the filler on 2 of 11 turns. It showed four more
problems:

7. **A stale reply was spoken.**
   - The caller answered ("बस फिट रहना", "just staying fit") while the agent was still preparing a re-ask
     of the question they had cut off. The re-ask was spoken anyway, after their answer.
   - **Fix:** a reply that isn't spoken yet is dropped when the caller is already speaking again, or when
     another of their turns is waiting. Its question then counts as not heard on the next turn.
8. **"एक सेकंड" ("one second") was answered with a re-ask.**
   - **Fix:** a built-in `hold` intent ("एक सेकंड", "रुकिए", "होल्ड": a short utterance only). The agent
     says the spec's `hold_ok` line ("जी, ज़रूर", "sure") and waits `hold_s` (20 s) before asking
     "are you there?".
9. **An unclear answer to a question the caller cut off cost two LLM calls.** The re-ask starts with
   "मैं पूछ रहा था" ("I was asking"), which the prediction of the next line didn't foresee. **Fix:** it does
   now.
10. **The other two:**
    - The filler's trim barely worked (2.08 s → 2.00 s): Laghu's "silence" is low-level noise. **Fix:** the
      trim now measures the noise floor from the clip's own tail.
    - The LLM echoed a misrecognised word back to the caller ("बस पेट रहना", "just stay belly"). **Fix:**
      the style rules now say not to repeat the caller's words back.

**Added after a fourth gym call** (trace `88c8c9ec174b`, with fixes 1 to 10 running, still before any judged run). The
filler never played (every reply was ready within 651 ms), and the range re-ask, the discount answer and the
hand-over worked. It showed one bug and three smaller problems:

11. **The words and the state could disagree.**
    - Groq said "answer" to "मैं अभय हूँ" ("I'm Abhay") but returned no name. The engine rightly stayed on
      the name question, but it spoke the reply Groq had written for "answer", which asked for the fitness
      goal. The caller then answered the goal while the engine was still on the name.
    - **Fixes:**
      - Words written in the understanding call are used only when the engine acts on the same intent
        Groq chose. Otherwise they are written afresh (`reply_unused` in the trace).
      - The name field's instructions now say a first name alone is fine, and that both fields are filled
        when the intent is answer.
12. **The same re-ask came twice, word for word** ("छः या सात दिन", "six or seven days", both times). **Fix:**
    an LLM line said in the previous reply is told to be worded differently, naming the options the caller
    offered.
13. **"I should get a discount", said after the fixed-fee answer, got "I didn't understand".** **Fix (gym
    spec):** asking for a discount again in that state gets the answer again, worded differently.
15. **A filler word broke a phrase.** Found while checking `m4/gym_test_calls.md` against the code: in
    "वज़न भी कम करना है और मसल भी बनानी है" ("lose weight and build muscle too"), the "भी" ("also") inside
    "वज़न कम" hid that option, so the rules picked "muscle" alone. **Fix:** a choice phrase may match with
    one extra word between its words. Two goals are then seen, and the agent asks which one.
14. **Recorded, not fixed here:** two turns ended on the 1.5 s silence cap. Smart Turn was unsure about long
    sentences ending in "चाहिए" ("should") and "दिन" ("days"). That belongs to the listening path
    (Milestone 2's open list).

**Unchanged:** all of M4-1 to M4-6, the scenarios and the setup. In Part A's summary, the filler count is now
taken at 700 ms.

**Checks before writing this amendment:**
- Abhay's 11 transcripts from that call, replayed through the fixed gym agent with the scripted stand-in:
  every problem above is handled as described.
- 42 of 42 typed loan calls correct, with 0 safety violations against the real backend (scripted stand-in).
- 152 tests pass.

**Added after the four test-sheet calls** (`m4/gym_test_calls.md` calls 1 to 4: traces `65126b70890d`,
`c3c86d0840f1`, `2c78b73e8bc7`, `9d32c337141b`; dated 2026-11-21, still before any judged run). What worked:
a reply the caller had moved past was dropped, the not-heard guard fired, "सुबह या शाम" ("morning or
evening") got the batch question again instead of a guess, and every barge-in cut the agent off. Nine
problems:

16. **A yes after most of the question was not accepted** (call 1). "हाँ बुक कर दो" ("yes, book it") came
    after about 93% of the fee and the question had played, and the agent read all of it again. **Fix:**
    `require_heard` may be a fraction. The gym's confirmation needs 85% of the reply heard; every loan state
    keeps `true` (all of it).
17. **"Just five seconds" was not a hold** (call 2). "हाँ मैं हूँ, मैं लाइन पर हूँ, जस्ट पाँच सेकंड"
    ("yes I'm here, just five seconds") got "I was asking" and the question. **Fix:** an utterance that
    ends with "<number> सेकंड", or "जस्ट/बस <number> मिनट", is a hold. Only at the end, because "एक सेकंड,
    पहले ये बताओ…" ("one second, first tell me…") is a question. The LLM's description of hold says the
    same.
18. **A repeat replayed the wrapper too** (call 2). "फिर से बोलिए" ("say it again") got "I'll say it
    again. I was asking: <question>". **Fix:** a repeat says the question as last said without wrapper
    lines ("I was asking", "sorry, I didn't understand", "please hear it all", "are you there").
19. **One-word answers waited for the silence cap** (call 2, and item 14 above). "शाम" ("evening") and
    "परसों" ("the day after tomorrow") each took 1.5 s: Smart Turn gave them 0.01 to 0.3. **Fix:** a
    dialog hint. After 500 ms of silence, at a turn check the turn model said no to, the listener asks the
    dialog whether the transcript already answers the question. Only the rules decide, only for choice and
    duration slots, never while a turn is being handled, and never when the transcript ends in "या", "और"
    and the like ("or", "and"). A duration counts only with its unit ("तीन दिन", "परसों"), because a bare
    "तीन" ("three") may go on to "साल" ("years"). Names, amounts, spelled values and yes/no still wait for the
    turn model.
    The trace records it as `end_reason: dialog_hint`. Expected saving on such answers: about 0.7 s.
20. **A word from the question was taken as the answer** (call 3). "मेरा फिटनेस लक्ष्य वजन भी कर्म करना
    है और माासल भी बनाना है" ("my fitness goal is to lose weight and build muscle", misrecognised) was
    booked as "stay fit" from the word फिटनेस ("fitness"), which the question itself says. **Fixes:**
    फिटनेस is no longer a phrase for that option. The LLM may answer "several" for a choice when the caller
    wants two or more, which gets the same "pick one" re-ask as the rules.
21. **"Can I tell you later?" was not understood** (call 3). **Fixes:** the gym's facts say the batch time
    and start day can be changed later at the front desk, and the LLM's description of "question" includes
    yes-or-no questions.
22. **A name given with the yes was asked for again** (call 4). **Fix (gym spec):** the greeting also reads
    the name (`also: [full_name]`, now read with yes and no as well as with answers), and the name question
    is skipped when the name is known. **Fix (engine):** a short yes with more words after it ("हाँ हाँ, मेरा
    नाम अभय है") goes to the LLM when the state reads another slot the rules can't (a name). A plain "हाँ जी"
    stays a rule.
23. **"We have three plans" was rejected for the number 3** (call 4). **Fix (gym spec):** the facts say
    "3 plans", so 3 may be said. The guard itself is unchanged: allowing every small number was considered
    and not done, because a wrong count or a bare rate ("ब्याज दस") would then pass.
24. **The answer example was copied word for word** (call 4). Asked "how many plans?", Groq said the
    example, a refusal ("I can't give exact information right now"), though the facts had the answer.
    **Fix:** answers get no example. If an answer fails a check, the spec's `question_fallback` line is said.

**Recorded, not fixed:** the filler clip is still 1.8 s long after the trim; it played on 2 of about 40 turns
in these calls. A shorter filler sentence is the spec's choice.

**Unchanged:** M4-1 to M4-6, the scenarios and the setup.

**Checks before adding this:**
- The turns behind items 16 to 24, replayed through the fixed gym agent with the scripted stand-in (tests
  added for each).
- 42 of 42 typed loan calls correct, with 0 safety violations and 0 of 260 blocks falling back, against the
  real backend (scripted stand-in).
- 174 tests pass (8 skipped without the models).


## Amendment 3 (21 Nov 2026, before any judged run): part B by a program, not by Abhay

Abhay won't make the five live calls by hand: the gym testing already took many calls. So part B is made by
`m4/auto_calls.py`, with the same five scripts, the same rules (M4-4 and M4-5) and the same thresholds.

**How the program calls.**
- It speaks with Laghu's female voice. The agent speaks with the male voice, so the speech recogniser hears a
  different speaker from the one it hears playing back.
- Its audio goes through the server's whole listening path: 16 kHz PCM in real-time 20 ms frames, with
  silence in between. That is VAD, IndicConformer, Smart Turn, the dialog hint, the LLM and Laghu, exactly as
  in a live call. Nothing in the server knows it is a program.
- It answers the question the agent is asking: the agent's state, from its `dialog` events, picks the line
  from the script. A question asked again gets the same answer again, as the scripts ask of a person.
- It speaks 0.6 s after the agent's audio has finished playing, never over it. Like the terminal client, it
  plays the agent's audio at real-time pace and reports playback.
- The passcode is the one the backend sent, read out as Hindi digits.
- A question it has no line for gets silence: the agent re-asks, then hangs up. No call is restarted, each
  counts once, and a crash counts as failed.

**What this measures, and what it doesn't.** It measures the whole pipeline end to end, with real
recognition and real timing. Synthetic speech is cleaner and steadier than a person's: no hesitations, no
background noise, no accent drift, no talking over the agent. Human speech and barge-ins were exercised by
the eight gym calls (unjudged). The write-up must say that part B's caller was synthetic.

**Setup:** as in part B, with the server started the same way. Instead of the client:
`python m4\auto_calls.py`, then `python m4\summarize_live.py --last 5`.

**Why part A also runs on Abhay's laptop:** this sandbox can't reach Groq. The command is unchanged.

**Checks before writing this:** the program completed L1 against the full server loop with stand-ins (a tone
for the caller, the stub STT returning the line being said, the in-memory backend): 11 answers, no question
asked twice, consent recorded once (`tests/test_auto_calls.py`).


## Amendment 4 (21 Nov 2026): Milestone 4 closed without its judged runs

Neither part A nor part B was run. No judged result exists for M4-1 to M4-6, and none is claimed.

**Why.** Abhay decided the milestone's question was the wrong one for the project. Part A and part B judge
one hand-tuned spec (loan onboarding). The project's claim is a platform that can be set up for any use case
from a description. Milestone 5 tests that claim directly, across use cases written after the tool is built,
with automated callers. A loan-only exam would add little to it.

**What Milestone 4 closes on (development evidence, not judged):**
- the engine, which runs two unrelated specs (loan with a real backend, gym with mock tools) with no
  use-case code in it;
- 42 of 42 typed loan calls correct, with 0 safety violations and 0 fallbacks, against the real backend, with
  the scripted stand-in for the LLM (it returns each line's correct reading; Groq was never used);
- 174 tests;
- eight live gym calls by Abhay, through the whole voice path with Groq. Their problems are listed in
  Amendment 2 and fixed.

**What is not shown:** how Groq does on the loan scenarios, and live latency against M4-3 and M4-5. Milestone
5's simulated calls use Groq throughout and report latency, so the first of these is covered there for other
use cases.

**Kept:** `run_dialog_eval.py` (also the loan regression for Milestone 5), `auto_calls.py` (its audio path is
reused for Milestone 5's voice calls), `summarize_live.py`, the scenarios and the scripts.
