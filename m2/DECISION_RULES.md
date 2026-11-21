# Milestone 2 decision rules (written before the first run of m2/probe_listen.py)

Same discipline as Milestone 0: these rules are committed before any run. A rule that has to change gets a
dated amendment below that says why, and the original stays as written.

## Setup

`python m2/probe_listen.py` on the Profile A laptop (i5-1335U, Windows), nothing else heavy running. The
30 male whole-sentence clips from Milestone 0 (`m0/out/laghu_male/sentence`, 10 sentences x 3 renditions)
stand in for a caller. Each is streamed in real time, in 20 ms frames, into the server's own `Listener`:
0.5 s of silence, the clip at 16 kHz, then 2.5 s of silence. Models: Silero VAD v5.1.2, Smart Turn v3.2
(int8 CPU export, 1 thread), IndicConformer Hindi 120M ONNX fp32 (4 threads). Listener settings are the
defaults in `laghu_voice/orchestrator/listener.py`: speculative decode at 96 ms of silence, segment closed
and Smart Turn asked at 200 ms, re-asked every 400 ms, silence cap 1500 ms.

**True end of speech** for a clip: the moment its last 20 ms frame louder than -40 dBFS (or 35 dB under the
clip's loudest frame, if that is higher) was fed in.

## Rules

**M2-1. STT latency (rule 3 of Milestone 0, rejudged as Amendments 6 and 7 said).** p95 over the clips of
(final transcript ready - true end of speech) <= 400 ms.

**M2-2. Cutting at pauses doesn't cost accuracy.** Pooled CER ("standard" scoring, as Milestone 0) of the
in-loop transcripts against each clip's model text <= 3.68%, that is at most 0.5 points above the same
model decoding each whole clip in Milestone 0 (3.18%).

**M2-3. One sentence, one turn.** Each clip should give exactly one user turn. At most 1 of the 30 may give
zero turns or more than one.

Reported, not judged: true end of speech to end of turn (p50, p95); how turns ended (Smart Turn or silence
cap); Smart Turn's first probability per clip and its inference time; wasted speculative decodes; VAD time
per window. These clips are complete sentences spoken by Laghu, so they say little about Smart Turn on real
callers who pause mid-thought; the live microphone test covers that by ear.

## If a rule fails

- M2-1: one retune is allowed, decided now: `--spec-ms 64 --tail-ms 64` (decode starts 32 ms sooner and
  each segment is 32 ms shorter). The second run decides. If it still fails, the STT stays and Milestone 3
  goes ahead; the miss is recorded and the next lever (a second STT worker, or a smaller model) is chosen in
  an amendment.
- M2-2 or M2-3: read the failing clips first. Any change is an amendment written before the rerun.

## Live check (not a rule)

With headphones: `python -m laghu_voice.server --tts laghu --listen full` and
`python clients/cli/client.py --mic`. Say ten short Hindi sentences, including one with a long mid-sentence
pause, and note whether each was cut off early, joined to the next, or heard right. The server's trace file
keeps every turn's timings.

## Amendments

### Amendment 1 (21 Nov 2026), written after run 1 and the first live session, before run 2

**Run 1** (defaults; 30 male clips): all three rules failed.

| Rule | Result | Limit |
|---|---|---|
| M2-1 end of speech to transcript, p95 | 502 ms over the 9 one-turn clips; 487 ms over all 30 clips (last turn) | 400 ms |
| M2-2 in-loop CER | 4.32% | 3.68% |
| M2-3 clips with exactly one turn | 9 of 30 | 29 |

Also measured: turn end p50 364 ms, p95 425 ms after the true end of speech; Smart Turn 48 ms p50, 116 ms p95.

**Live session** (Abhay, headphones, 11 caller turns): transcript ready a median 202 ms after he stopped,
433 ms at worst (a 5.6 s PAN read without a pause). Smart Turn held through every long mid-sentence pause
(probabilities 0.005 to 0.25), ended one turn early ("मेरा पैन नंबर है", "my PAN number is", at exactly 0.500),
and left 4 of 11 turns to the 1.5 s silence cap. He found it pleasant to talk to.

**Reading the failures**

1. *M2-3.* Every split (21 clips) is at a comma, where Laghu pauses for 224 ms or more and Smart Turn judged
   the clause finished (0.85 to 0.99). Laghu says a comma with the falling pitch of a sentence end; the live
   session shows Smart Turn does hold through a real speaker's mid-sentence pauses. So on Laghu's clips M2-3
   measures Laghu's commas more than Smart Turn. Nothing changes for it here. Its threshold and the silence
   cap are tuned in Milestone 3 on live turns, under rules written before that data is collected.
2. *A bug behind part of M2-2.* While Smart Turn is deciding (50 to 120 ms), the caller's next words can
   start softly, below the VAD's speech threshold. Those windows went into the old turn, and the next turn's
   pre-roll started empty, so its first syllable was lost: s09 renditions 0 and 1 heard "क्या यह सही है" as
   "क है" (23 of the 83 character errors). Fix: when a turn ends, its last 320 ms seed the next pre-roll.
   `tests/test_listener.py` has a test that fails without the fix.
3. *M2-1.* The slowest clips (502, 487, 402 ms) are 5 to 7 s sentences spoken with no pause of 200 ms, so
   the segment left to decode at the end is the whole sentence (240 to 310 ms of decoding). The retune allowed
   above (spec and tail 64 ms) would save about 32 ms, not enough, and a shorter tail risks clipping word
   endings, so it is not used. The next lever, chosen here: while the caller keeps talking, the open segment
   is cut at its quietest 32 ms window of the last 2 s once it reaches 3 s (`max_segment_s` 10 → 3), so the
   segment decoded after they stop is short.

**Run 2** uses both changes and nothing else, and is the last run in Milestone 2. M2-1 is computed over all
30 clips, each clip's last turn (two thirds of run 1's clips had more than one turn, so "the one-turn clips"
is not a fair sample). If M2-2 fails in run 2 and the new cuts are the cause (its CER is above run 1's), then
`max_segment_s` returns to 10 and M2-1 is recorded as missed.

### Amendment 2 (21 Nov 2026), result of run 2; Milestone 2's rules closed

| Rule | Run 1 | Run 2 (pre-roll fix, 3 s cuts) | Limit |
|---|---|---|---|
| M2-1 end of speech to transcript, p95 (all 30 clips) | 487 ms | 392 ms | 400 ms |
| M2-2 in-loop CER | 4.32% | **16.56%** | 3.68% |
| M2-3 clips with exactly one turn | 9 | 14 | 29 |

The 3 s cuts are the cause of run 2's CER: the 17 clips that had a cut went from 60 to 293 character errors,
the 13 without one from 23 to 25. As Amendment 1 decided, `max_segment_s` returns to 10 and **M2-1 is
recorded as missed (487 ms, run 1)**. **M2-2 and M2-3 are recorded as failed.** The pre-roll fix stays.

Smart Turn took 133 ms per call at p50 in run 2 (48 ms in run 1) while STT decodes ran alongside it on this
2-performance-core CPU. Slower answers let Laghu's next clause start before the turn ended, which is why
fewer clips split. The thread budget is revisited in the Milestone 5 load test.

**Open question carried into Milestone 3, checked before any Milestone 3 rule:** the cut segments decode as
nonsense even when the cut falls in a pause (s07 rendition 0: "आपका लोन अप्रूव हो गया है" came out as
"तो आो है"), and short segments closed by a pause sometimes do too (s09: "क्या यह सही है" as "क है" in five of
six turns over both runs). That could be the model or a bug in the listener's path. Diagnostic, not a judged
run: `probe_listen.py --max-segment-s 3 --dump m2/out/dump` saves every segment the listener decoded, then
`decode_dump.py` decodes the same audio again in a fresh process, alone and with 0.5 s of silence added at
each end. Same text alone means the listener passes audio correctly and the model is the cause.

### Amendment 3 (21 Nov 2026), the diagnostic's answer: it's the model, and silence fixes it

`decode_dump.py` on the 104 segments saved from a diagnostic run with 3 s cuts (same clips and settings as run
2): **104 of 104 decode to exactly the same text alone, in a fresh process.** The listener hands the model
the right audio; the nonsense is the model's answer to that audio.

The same segments with **0.5 s of silence added at both ends**: CER over the 30 clips (segments the listener
kept, joined per clip) falls from **16.56% to 3.80%**, with the 3 s cuts still in place. Examples: "तो आो है"
→ "आपका रोन अप्रूव हो गया है और"; "क है" → "क्या यह सही है" (this one failed in every run, with or without
cuts); "तोवा है" → "मैं लघू हूँ". So this IndicConformer export needs silence around the speech it reads, and
the listener's segments (320 ms of pre-roll, 96 ms of tail, or none at a cut) don't give it enough.

Next, still diagnostic: `pad_sweep.py` tries eight amounts of silence before and after on the same kept
segments and times each. These clips are now used for tuning, so the padding it picks is judged in
Milestone 3 on clips it was not tuned on (the female clips in `m0/out/laghu_female`) and on live speech,
under rules written before those runs.

### Amendment 4 (21 Nov 2026), padding sweep; Milestone 2 closed

`pad_sweep.py`, 82 kept segments from the 3 s-cut diagnostic run (CER over 30 clips; decode time per segment):

| Silence before / after | CER | decode p50 / p95 |
|---|---|---|
| 0 / 0 | 16.56% | 93 / 135 ms |
| 0.1 / 0.1 s | 4.27% | 105 / 204 ms |
| **0.25 / 0.25 s** | **3.85%** | 136 / 185 ms |
| 0.5 / 0.5 s | 3.80% | 212 / 321 ms |
| 0 / 0.25 s | 6.51% | 175 / 250 ms |
| 0.25 / 0 s | 4.84% | 125 / 167 ms |
| 0 / 0.5 s | 7.08% | 136 / 188 ms |
| 0.5 / 0 s | 5.31% | 130 / 188 ms |

Silence is needed on both sides, and 0.25 s gets almost all of what 0.5 s does for less decode time. Chosen:
**0.25 s of silence on each side of every segment, and segments cut at 3 s again.** Both were tuned on these
male clips, so they are judged in Milestone 3 (`m3/DECISION_RULES.md`) on the female clips and on live
speech. The decode times above vary between rows more than padding explains (0 / 0.25 s is slower than
0.25 / 0.25 s), so the in-loop run, not this table, is the latency measurement.

Milestone 2 ends with its own rules recorded as: M2-1 missed (487 ms), M2-2 failed, M2-3 failed, and the
cause of M2-2 found and fixed.
