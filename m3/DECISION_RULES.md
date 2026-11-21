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

Rules to be written before Part B's runs.

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
