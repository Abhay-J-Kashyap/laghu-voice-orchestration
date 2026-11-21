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

### Amendment 3 (21 Nov 2026), written after listening to probe_laghu.py clips, before any CER was computed

The agent's voice changes from female to male. Listening to some of the female clips from probe_laghu.py,
the male voice sounded clearer. That was judged by ear, before any clip was transcribed or scored.

1. Rules 2 and 3 are decided on the male clips (`m0/out/laghu_male`). The female clips are scored with the
   same script for the record only, which checks the by-ear choice with a number. If the female voice
   scores clearly better, that is written down here, but it doesn't reverse this amendment.
2. The agent prompt now says the agent is a man (`"agent_gender": "male"` in prompts_groq.json), and
   probe_groq.py flags replies that use the other gender's first-person verbs. probe_groq.py is not rerun
   for this. Run 1, which had no gender instruction, used masculine verbs in every reply, and reply gender is
   checked again when the Milestone 4 prompt is written. Amendment 2's latency result doesn't depend on the voice.
3. The server's default voice (`LAGHU_VOICE`) is now male.

### Amendment 4 (21 Nov 2026), written after listening to probe_laghu.py clips, before any CER was computed

Both voices mispronounce नमस्ते, so the agent will never say it. Three test sentences change to match what
the agent will actually say:

- s01 "नमस्ते, यह कॉल आपके पर्सनल लोन के बारे में है।" becomes "मैं लघु हूँ और यह कॉल आपके पर्सनल लोन के बारे
  में है।" (the agent introduces itself by name instead of greeting).
- s06 and s08 change their first-person verbs to masculine (पाई → पाया, सकती → सकता) for the male voice.

s01 and s08 have no first clause, before or after the change, so they are outside rule 2's paired set.
s06 is in it (its clause ends at the second comma); its one-word change appears in both its clause and its
whole sentence, so the pairing stays like for like. Rule 2 still compares the same 7 sentences. Known weakness for the record: Laghu mispronounces नमस्ते in both voices. The phrasing prompt now forbids
it; the Milestone 4 prompt and greeting templates must too.

### Amendment 5 (21 Nov 2026), results of probe_laghu.py and probe_stt.py (run 1), written before any further run

Clips: 10 sentences, 3 renditions, both voices. STT: IndicConformer 600M multilingual, CTC, CPU, 4 threads.
CER is pooled, "standard" scoring unless marked.

**Rule 2 (male voice, decides).** Paired 7 sentences, 21 clips each side: whole sentences 1.92%, first clauses
2.55%, gap **+0.63 points**. Median time to first audio: sentences 25.3 ms, clauses 21.8 ms. The CER gap is
within 1.0 but inside the 0.5 to 1.5 band, so the rule says to rerun on FLEURS before turning clauses on.
Decision: `LV_FIRST_CLAUSE` stays off (the default). The FLEURS rerun moves to Milestone 2 and is done only if
Milestone 2 shows that sending the first clause early saves real time waiting for the LLM; here it saved 3.5 ms.
For the record, not used for the decision: the paper-style gap is +0.08 points, and most of the standard gap
is the STT writing "ईएमआई" as one word in clauses and "ई एम आई" in sentences (s05).

**Rule 3 (decides).** Whole-sentence decode time (2.6 to 7.5 s of audio): p50 1157 ms, **p95 1547 ms**, far
above 400 ms. IndicConformer 600M is not kept for the live path. Per the rule, a smaller model is timed before
Milestone 2. The candidate is named here before it runs: the Hindi-only IndicConformer, 120M parameters,
ONNX export `OpenVoiceOS/ai4bharat-indicconformer-hi-onnx` (fp32, and int8 if it loads), run with
`probe_stt.py --stt hi120m` / `--stt hi120m-int8` on the same male clips, same scoring, same 400 ms limit. It
replaces "Vaani FastConformer Hindi" in rule 3, because it needs no NeMo and runs on Windows. Groq
whisper-large-v3-turbo was timed in the same run; its time is added below when recorded.

**Female voice (for the record, per Amendment 3).** All 10 sentences: male 2.45%, female 2.40%; paired
sentences: male 1.92%, female 2.12%. No measurable difference at this size, so the by-ear choice is neither
confirmed nor contradicted. The female run was slower throughout (first audio p50 35 ms vs 24 ms; 7.3x vs
11.5x real time), most likely machine load rather than the voice. Amendment 3 stands.

Seen while reading the transcripts, not part of any rule:

- The agent's own opening line (s01) is the weakest sentence. Male voice: "पर्सनल लोन" heard as "पोस्टल रोन"
  in 2 of 3 clips by IndicConformer and in 3 of 3 by Groq Whisper (female: 0 of 3). "लघु" is misheard in most
  clips of both voices. Fixed lines like the greeting should be rendered ahead of time and checked, not
  synthesised live (Milestone 4).
- Groq Whisper writes numbers as digits and some English words in Latin script, so its CER needs number
  normalisation before it means anything. It heard "लोन" as "रोन"/"रून" in 5 of 6 clips of s01 and s07, and once
  wrote the interest rate 10.5% as "10.95": a wrong number, the worst kind of error for a banking agent.

### Amendment 6 (21 Nov 2026), result of the 120M run, and the last STT candidates, written before running them

`probe_stt.py --stt hi120m` (Hindi-only IndicConformer 120M, ONNX fp32, CPU, 4 threads, male clips):
whole-sentence decode **p50 393 ms, p95 569 ms**: three times faster than the 600M model (75 vs 221 ms per
second of audio) but still above 400 ms, so it is not kept as it stands. CER over all 10 sentences: 3.18%
(600M: 2.45%); most extra errors are spellings (रुपएे, कीजिएे, एगज़ेकुटिव) rather than wrong words. Rule 2 on
this model: clauses 1.9% vs sentences 2.2%. The export loads as a CTC model (one `model.onnx`), which
settles Amendment 5's open question. OpenVoiceOS's int8 file does not load on ONNX Runtime's CPU build
(missing ConvInteger kernel).

Last candidates before Milestone 2, named before they run, same male clips, same scoring:

1. Our own int8 copy of the same model (`quantize_hi120m.py`: MatMul weights to uint8, convolutions left
   fp32), run as `--stt hi120m-uint8` with 4 threads.
2. If the machine has more than 4 physical cores: the same two models (fp32 and uint8) with `STT_THREADS`
   set to the number of physical cores in `m0/out/machine.txt`.

A candidate is kept if its whole-sentence decode p95 is ≤ 400 ms **and** its all-10 CER is at most 0.5 points
above the 120M fp32 result (so ≤ 3.68%). If several pass, the one with the lowest CER is kept.

If none passes, the 400 ms limit is not loosened for whole-utterance decoding. Instead the fastest model
within the CER condition goes into Milestone 2, which transcribes speculatively while the caller is still
speaking, and rule 3 is judged there on what the caller actually waits for: p95 time from end of speech to
final transcript ≤ 400 ms.

