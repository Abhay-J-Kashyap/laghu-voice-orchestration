# Milestone 3 decision rules

Same discipline as Milestones 0 and 2: rules are committed before the runs they judge; changes are dated
amendments. Milestone 3 has two parts, and each part's rules are written before its runs.

## Part A: the STT settings from Milestone 2, on clips they were not tuned on

Written 21 Nov 2026, before either run below.

Settings under test, chosen on the male clips in Milestone 2 (Amendment 4): 0.25 s of silence added before and
after every segment, segments cut at 3 s while the caller keeps talking, everything else at the listener's
defaults. Held-out set: the 30 female whole-sentence clips in `m0/out/laghu_female` (same 10 sentences, other
voice, never used for tuning).

Runs, in this order:
1. `python m0/probe_stt.py --stt hi120m --voice female`: the same model decoding each whole female clip, as
   Milestone 0 did for the male clips. Its CER is the baseline.
2. `python m2/probe_listen.py --voice female`: the listener in real time on the same clips.

**M3-A1. Latency.** p95 over the 30 clips of (final transcript ready - true end of speech) <= 400 ms (the
Milestone 2 definition, every clip's last turn).

**M3-A2. Accuracy.** In-loop CER (run 2) <= whole-clip CER (run 1) + 0.5 points.

Reported, not judged: turns per clip, turn end latency, Smart Turn timings.

If both pass, the settings stay. If M3-A2 fails, padding stays and `max_segment_s` goes back to 10 (cuts
are the riskier half). If only M3-A1 fails, the settings stay and the miss is recorded. No reruns.

## Part B: barge-in and turn-taking

Written 21 Nov 2026, before any run of `m3/probe_bargein.py`.

**What is tested.** The turn controller (`laghu_voice/orchestrator/controller.py`), full duplex: when the
caller starts speaking over the agent's audio, the client is told to duck at once; after 250 ms of the
caller's speech (counted from the first speech window the VAD hears) the agent is interrupted (epoch + 1,
synthesis stopped, queues drained, client flushed). Speech over the agent that stops sooner is a backchannel:
the volume comes back, nothing is cancelled, and that turn gets no reply.

**Setup.** `python m3/probe_bargein.py` on the same laptop. Everything in one process with the real models:
Laghu (male voice) speaks a fixed four-sentence reply (about 12 s); a stand-in client plays it at real-time
pace, reports its playback position every 100 ms, and flushes when told; the "caller" is audio fed into the
listener in 20 ms frames at real-time pace, silence when nobody talks. No echo: the agent's audio never
reaches the caller's input, as with headphones. In each trial the caller starts 1.0 to 2.5 s (seeded,
uniform) after the reply's first audio was played.

- 20 barge-in trials: the female whole-sentence clips, renditions 0 and 1 of s01 to s10.
- 20 backchannel trials: "हाँ", "हम्म", "जी", "अच्छा", "ठीक है", 4 renditions each, synthesised once by Laghu's
  female voice at the start of the run (saved to `m3/out/backchannels/` so they can be listened to).

**True speech start** of a clip: the first 20 ms frame louder than -40 dBFS (or 35 dB under the clip's
loudest frame, if higher) fed in, the same rule Milestone 2 used for the end.

**M3-B1. Barge-in stops the agent, quickly and cleanly.** All 20 barge-in trials interrupt the agent; the p95
of (flush sent - true speech start) is at most 400 ms; and no audio from an interrupted epoch reaches the
client after its flush, in any trial.

**M3-B2. Backchannels don't.** At most 2 of the 20 backchannel trials interrupt the agent.

**M3-B3. Nothing the caller says is lost.** Pooled CER of the barge-in trials' transcripts (every caller turn
that starts after the clip starts, joined) is at most 4.0%, that is 1.5 points above the same clips decoded
whole (2.50%, Amendment 1). The listener on these clips without any agent speaking measured 3.65%.

Reported, not judged: duck latency; how long each backchannel and each clip's opening was in VAD speech time;
the heard-text estimate per interrupted reply; Laghu, STT and Smart Turn timings while all run together.

**If a rule fails.** B1 or B2: the threshold is the lever. If B1 fails on latency only, `barge_in_ms` goes to
200; if B2 fails, it goes to 350; one rerun of the probe with the new value decides, and if B1 and B2 then
pull in opposite directions the threshold stays at 250 and both results are recorded. B3: read the failing
transcripts before changing anything.

**Live check (not a rule).** With headphones, `python -m laghu_voice.server --tts laghu` and
`python clients/cli/client.py --mic`. Interrupt the agent's reply a few times, and say "haan" over it a few
times; note whether each did what you meant.

## Amendments

### Amendment 1 (21 Nov 2026), baseline, and a run that didn't test the registered settings

Run 1 (whole female clips, 120M fp32): **CER 2.50%**, so M3-A2's limit is 3.00%.

The first in-loop run used an out-of-date `probe_listen.py`: it reported segments cut at 10 s (not 3 s) and
wrote `listen_runs.jsonl` instead of `listen_runs_female.jsonl`, and it can't be told from its output whether
the STT padding was active. It is recorded, not judged: CER 3.65%, transcript p95 425 ms, 13 of 30 clips as
one turn. The judged run is run 2 with the files from this milestone, checked before running.

### Amendment 2 (21 Nov 2026), Part A result; Part A closed

Run 2 (female clips, files checked: 3 s cuts, 0.25 s padding):

| Rule | Result | Limit |
|---|---|---|
| M3-A1 transcript p95 | 408 ms (p50 306 ms) | 400 ms |
| M3-A2 in-loop CER | 4.06% | 3.00% (whole clips 2.50% + 0.5) |

Both fail. The cuts are the cause of A2: the 19 clips with a cut went from 40 character errors (whole-clip
decode) to 66, the 11 without one from 8 to 12. Padding fixed the nonsense, but a cut inside a word still
splits it ("सकता हूँ" became "सकताू दाहूँ"). As Part A decided before the run: **padding stays,
`max_segment_s` returns to 10, and M3-A1 is recorded as missed.** No rerun.

Settings from here: 0.25 s of silence around each segment, segments closed only at pauses of 200 ms or more
(or at 10 s), STT 4 threads. Expected transcript latency is the 425 ms p95 measured without cuts in
Amendment 1. A faster STT path is left for later and is not part of Milestone 3.

### Amendment 3 (21 Nov 2026), Part B result; Milestone 3 closed

`probe_bargein.py`, threshold 250 ms, seed 3:

| Rule | Result | Limit |
|---|---|---|
| M3-B1 barge-in stops the agent | 20 of 20 stopped, 0 stale frames after any flush; speech start to flush p50 334 ms, **p95 585 ms** | all stopped, p95 <= 400 ms, 0 stale |
| M3-B2 backchannels ignored | **6 of 20 interrupted** (all four "ठीक है" at 384 to 416 ms of speech, one "जी" at 256 ms, one "अच्छा" at 288 ms) | at most 2 |
| M3-B3 nothing lost | CER 3.20% | 4.0% |

B1 fails on latency only, and B2 fails, so they pull in opposite directions: as written, **the threshold stays
at 250 ms and both failures are recorded. No rerun.**

What the numbers say, for whoever picks this up:

- *B1.* Once the VAD hears the caller, the stop is quick and steady: duck to flush 130 to 320 ms, flush ~1 ms
  after the decision, and nothing stale reaches the client. The slow trials are six: both renditions of
  s03, s07 and s09, where the VAD heard speech 376 to 468 ms after the loudness-based "true start" (other
  clips: about 100 to 220 ms). Either those clips open softly enough that Silero waits, or the loudness rule
  marks breath or a soft onset as speech. Not resolved here.
- *B2.* Duration alone can't separate a backchannel from an interruption: "ठीक है" lasts about 400 ms of
  speech, longer than "चुप" (288 ms) in the live session, which was meant as an interruption. The design
  doc's v2 idea is the lever: at the threshold, pause the agent instead of flushing, and resume if the
  transcript is a backchannel word. Not built in Milestone 3.

Live session (headphones, 11 caller turns): interruptions with full words ("चुप चुप चुप") stopped the agent
160 ms after the VAD heard them; a short "छुक" (128 ms) was taken as a backchannel; "हाँ" at 256 ms
interrupted. The heard-text estimate matched the interrupted replies.

**Milestone 3 summary.** Part A: STT padding kept, cuts off, A1 and A2 failed and recorded. Part B: barge-in
works and never leaks stale audio; B1 latency and B2 backchannels failed and recorded; B3 met.
