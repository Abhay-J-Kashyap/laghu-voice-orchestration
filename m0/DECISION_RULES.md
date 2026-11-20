# Milestone 0: decision rules, written before any probe was run

Commit this file before running the probes. If a rule changes after seeing results, add a dated
amendment below that says why. Don't edit the original rule.

All timings are taken on **Profile A** (the machine you'll benchmark on). Note its CPU, core count and RAM
in `m0/out/machine.txt` before running anything.

## 1. LLM on Groq (`probe_groq.py`)

Candidates: `openai/gpt-oss-20b` (reasoning effort low, reasoning excluded) and `llama-3.3-70b-versatile`.
3 runs × 10 prompts per model, run sequentially, from your usual network.

A model **qualifies** if all three hold:
- p95 time to first token ≤ 600 ms (the latency budget allows 400 ms at p50).
- At least 27 of its 30 phrasing replies contain no Latin letters (Laghu can only read Devanagari
  reliably; TextPrep drops unknown Latin words).
- All 9 extraction runs return valid JSON with the correct `loan_amount_inr` and `wants_callback`.

Pick the qualifying model with the lower p50 time to first token. If neither qualifies, don't pick one.
Write down which rule failed and decide what to change before Milestone 1 ends.

Hindi phrasing quality is judged by reading `groq_replies.jsonl`, not scored. A reply that invents a number
it wasn't given (an EMI, a rate) is a fail for that model, and it's listed in the summary.

## 2. First-clause segments (`probe_laghu.py` then `probe_stt.py --cer`)

10 banking sentences, each spoken whole and, where the server would cut one, as its first clause: the first
segment the server's own Segmenter produces with `first_clause=True` (a comma with at least 4 words before it,
never a comma inside an amount). 7 of the 10 sentences have such a clause. The comparison below is paired:
those 7 clauses against the same 7 sentences spoken whole.

Turn on `LV_FIRST_CLAUSE=1` only if **both** hold:
- Pooled CER on clauses is at most 1.0 percentage point worse than pooled CER on the same sentences spoken
  whole. Scoring: IndicConformer CTC, with the "standard" rules of Laghu's PROTOCOL.md Amendment 13 (reference =
  the model text, NFC, punctuation to spaces, nukta kept; `clean_ctc` on the transcript). The paper-style
  numbers are printed too, but the rule uses standard. 7 sentences × 3 renditions, so 21 clips per side.
- Median time to first audio is lower for clauses. Expect little difference, because Laghu starts audio
  within one frame either way. The real gain comes from not waiting for the LLM to finish the sentence,
  and that's measured in Milestone 2.

10 sentences is a rough screen, not a test. If the CER gap lands between 0.5 and 1.5 points, rerun with
the 100 FLEURS sentences from Laghu's evaluation before deciding.

## 3. STT (`probe_stt.py`)

IndicConformer 600M (CTC), CPU, on Laghu's 10 sentence clips (about 3–6 s each).

Keep it if p95 decode time ≤ 400 ms. Otherwise time a smaller model (Vaani FastConformer Hindi, or
Groq `whisper-large-v3-turbo` with `--groq-whisper`) before Milestone 2. Groq Whisper's time includes
the network round trip, so it's compared on total time, not decode time.

## Amendments

### Amendment 1 (20 Nov 2026), written after run 1 of probe_groq.py

Run 1 can't decide rule 1: 8 of 39 gpt-oss-20b calls hit Groq's free-tier limit (30 requests per minute),
and all 39 calls to `llama-3.3-70b-versatile` returned "model not found" for this API key. Partial result
for the record (31 calls that succeeded): phrasing time to first token p50 474 ms, p95 968 ms; extraction
7 of 7 correct; no Latin letters; no invented numbers.

Reading the replies showed two problems rule 1 didn't check. Because these were seen in run 1's results,
this amendment says so, and the changes apply to both models in run 2:

1. **Agent gender.** Every reply used masculine first-person verbs (बताता हूँ, करूँगा) while Laghu's voice is
   female. The system prompt now says the agent is a woman. `probe_groq.py` flags masculine first-person
   verbs, and a flagged reply doesn't count as a good phrasing reply.
2. **Invented account facts.** 3 of 21 phrasing replies stated things the model couldn't know ("your documents
   haven't been processed", "your loan is in processing"), and 2 more said an application had been received.
   The system prompt now forbids statements about the caller's application, documents, account or status.
   Rule 1 gains a condition: **at most 1 of a model's 30 phrasing replies may state such a fact**. That is
   judged by reading the replies, since the probe can't detect it.
3. **Second model.** `llama-3.3-70b-versatile` is replaced by: `openai/gpt-oss-120b` (picked from the models this key can
   use, before running it).
4. **Rate limits.** The probe waits 2.5 s between calls and retries a call that gets HTTP 429. A rate-limited
   call is a quota problem, not a model failure.

The latency, script and extraction conditions of rule 1 are unchanged.

### Amendment 2 (21 Nov 2026), written after run 2 of probe_groq.py

Run 2 result (30 phrasing and 9 extraction calls per model; no errors, no rate limits). Percentiles are
nearest-rank over the 30 phrasing calls, as the script prints them.

| model | TTFT p50 | TTFT p95 | no Latin | extraction | masculine verbs | invented account facts |
|---|---|---|---|---|---|---|
| openai/gpt-oss-20b | 279 ms | 618 ms | 30/30 | 9/9 | 0 | 0 |
| openai/gpt-oss-120b | 450 ms | 706 ms | 30/30 | 9/9 | 0 | 1 (p07, run 0: "I'll look at the documents you sent again", implying they were already seen) |

**Neither model qualifies under rule 1.** Both fail only the p95 condition. gpt-oss-20b misses it by 18 ms
(2 of 30 replies above 600 ms: 618 ms and 880 ms). The 600 ms limit is not changed, and probe_groq.py is not
rerun to try to pass it.

What changes, decided now:

1. `openai/gpt-oss-20b` is the development LLM for Milestones 2 to 4, recorded as not meeting rule 1. It is
   the faster model at p50 and passes every other condition.
2. The slow tail is handled in the design, not by the threshold. In Milestone 4, if the LLM's first token
   hasn't arrived 500 ms after the end of the caller's turn, the agent plays a short pre-synthesised
   acknowledgement (for example "जी, एक पल") and carries on when the reply arrives. Turns the state machine
   can answer from templates don't call the LLM at all.
3. The latency condition is measured again in Milestone 5: at least 200 phrasing calls, from the machine the
   server runs on, with the Milestone 4 prompts. That measurement decides whether the filler stays.

Seen while reading the replies, not part of the rule (inputs for the Milestone 4 prompt):

- Both models promise actions they can't take ("I'll check your EMI and tell you", "I'll connect you to a
  person"), because the probe gives them no facts and no actions. In the agent, the state machine decides the
  action and supplies the facts; the LLM only phrases them.
- gpt-oss-120b invented a bank name twice ("ABC Bank", "Express Bank") and an agent name once ("Sushma"). The
  prompt must give the bank's and the agent's names.
- gpt-oss-20b never answered "who is speaking?", and once addressed the caller as a woman (चाहती हैं).