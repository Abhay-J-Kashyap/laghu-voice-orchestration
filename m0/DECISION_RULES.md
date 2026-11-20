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

(none yet)
