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
