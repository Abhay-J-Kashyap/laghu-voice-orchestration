# laghu-voice

A from-scratch voice agent runtime around **Laghu TTS 7M Hindi**: streaming speech out, barge-in, per-turn
latency traces. No Pipecat or LiveKit. Design: see the design plan doc (Laghu Voice Orchestrator: Design Plan).

## Where it stands

| Part | Status |
| --- | --- |
| Speaking path: text in, streamed Laghu audio out, real-time pacing | Built; 34 ms to first audio with the real model (Milestone 1) |
| Barge-in: epochs, flush, nothing stale sent after a stop | Built; 0.22 ms server-side with the real model |
| Banking text: PAN digits, English loanwords | Built on top of Laghu's own frontend, tested |
| Per-turn traces (JSONL) | Built, for agent turns and caller turns |
| Milestone 0 probes and decisions | Done: see `m0\DECISION_RULES.md`, Amendment 7 |
| Listening path: Silero VAD, Smart Turn, IndicConformer 120M, speculative STT, echo reply | Built (Milestone 2), tested with stand-ins. **First real run is yours** (below) |
| Barge-in from the caller's voice, dialog, eval | Not started (Milestones 3–5) |

The build machine can't reach Hugging Face, so Smart Turn and IndicConformer have only run on your machine;
Silero VAD and the mel features were checked here (the mel features match Whisper's to 6e-6).

## Setup (Windows PowerShell)

```powershell
cd laghu-voice
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python scripts\get_laghu.py
python scripts\get_listen_models.py
```

`get_listen_models.py` puts the listening models in `vendor\`: Silero VAD (2.3 MB, from its GitHub release,
checksum verified), Smart Turn v3.2 int8 (8.7 MB) and the Hindi IndicConformer 120M (about 480 MB; copied from
`m0\out\hi120m` if Milestone 0 already downloaded it).

The last line downloads Laghu from its Hugging Face repo into `vendor\laghu\`, about 31 MB:

| Files | Why |
| --- | --- |
| `model\meta.json`, `tables.npz`, `tokenizer.model` | Settings, text embeddings, tokenizer |
| `model\lm_step.onnx`, `head.onnx`, `decoder.onnx` | The speaking model: transformer, flow head, Mimi decoder |
| `model\voices\*.npy` | The built-in voices (female, male) |
| `runtime_onnx.py`, `text_chunking.py` | The streaming runtime the server calls |
| `devanagari_text.py`, `hindi_numbers.py`, `spelling_map.py` | Laghu's text frontend (₹ amounts, OTPs, dates) |
| `LICENSE`, `LICENSE-CODE`, `LICENSE_pocket_tts` | Licences that have to travel with the files |

The code files are needed as well as the weights, because the server runs Laghu's own runtime and frontend
instead of a rewrite. Not downloaded: `encoder.onnx` (39 MB, voice cloning only), the samples and the
evaluation folder. `vendor\` is in `.gitignore`, so these files are never committed. To use a voice you made
with `clone.py`, copy its `.npy` into `vendor\laghu\model\voices\` and set `LAGHU_VOICE` to its name.

## Check it works

```powershell
python -m pytest
```
Expect `48 passed`. Tests that need a model you haven't downloaded are skipped, and say which script to run. To see its timing, run it on its own:

```powershell
python -m pytest tests/test_laghu_adapter.py -k real -s
```
It prints Laghu's time to first audio through the server's adapter. Send me that line.

## Talk to it

**By voice (Milestone 2).** Use headphones: the server ignores the mic while the agent speaks, but a speaker
next to the mic still leaks.

Terminal 1 (the server):
```powershell
python -m laghu_voice.server --tts laghu
```
Terminal 2 (the client):
```powershell
python clients\cli\client.py --mic
```
Speak a Hindi sentence and stop. The agent says back what it heard ("मैंने सुना: ..."), and the client prints
the transcript, what ended the turn, and how long after you stopped the transcript and the turn end came.
`--show-vad` also prints when the server hears you start and pause.

No mic, or to repeat a test exactly: start the client without `--mic` and type
`/wav m0\out\laghu_male\sentence\s04_r0.wav`. The client sends the recording as your voice, in real time.

Server options: `--listen stub` (no listening models: loudness VAD and a fixed transcript), `--listen off`
(Milestone 1 behaviour), `--no-turn-model` (end turns after 700 ms of silence), `--dialog none` (listen only).

**By typing (Milestone 1).** Start the server with `--listen off` and the client without `--mic`.
Type Hindi and press Enter to hear it. `/stop` interrupts, `/file story.txt` speaks a UTF-8 file (PowerShell can
garble typed Hindi), `/quit` hangs up. After each turn the client prints its outcome and timing. Every turn is
also written to `traces\<session>.jsonl`.

No speakers or no `sounddevice`? Use `--no-audio --save out.wav`. Without the model, use `--tts stub` on the
server (it speaks a tone with Laghu's measured timing).

## Milestone 0: run the probes

Rules first. `m0\DECISION_RULES.md` says what each result decides. Commit it before running anything, and
note your machine (CPU, cores, RAM) in `m0\out\machine.txt`.

```powershell
# 1. Groq: time to first token and Hindi replies. First run prints the plan only; --yes calls the API.
$env:GROQ_API_KEY = "gsk_..."
python m0\probe_groq.py
python m0\probe_groq.py --yes

# 2. Laghu: whole sentences vs first clauses, 3 renditions each, saved as WAVs in m0\out\laghu_<voice>
python m0\probe_laghu.py                  # male voice (decides rule 2)
python m0\probe_laghu.py --voice female   # for the record

# 3. IndicConformer on CPU: decode time, and CER of the clips from step 2
python -m pip install -r m0\requirements-m0.txt
python m0\probe_stt.py --groq-whisper     # male clips; --groq-whisper also times Groq's Whisper
python m0\probe_stt.py --voice female     # female clips, for the record
```
Send me the printed summaries and `m0\out\groq_replies.jsonl`. Listen to a few WAVs in `m0\out\laghu_male\clause`
before believing any CER number.

## Milestone 2: the listening probe

Rules first: `m2\DECISION_RULES.md`. Commit it, then:

```powershell
python m2\probe_listen.py
```
It streams the 30 male sentence clips from Milestone 0 into the listener in real time (about 2.5 minutes) and
prints rules M2-1 to M2-3. Send me the printed summary and `m2\out\listen_runs.jsonl`.

## Layout

```
laghu_voice/
  config.py              settings from environment / .env
  frames.py              frames between stages; audio wire format (8-byte header + PCM16)
  server.py              python -m laghu_voice.server
  orchestrator/
    session.py           one call: segmenter -> TTS worker -> pacer; epochs and interrupt
    pacing.py            real-time sending, at most 200 ms ahead of the listener
    listener.py          the caller's side: VAD windows, segments cut at pauses, speculative STT, end of turn
  audio/
    vad.py               Silero VAD v5 (ONNX), one state per call
    turn.py              Smart Turn v3.2: last 8 s of audio -> P(turn finished)
    mel.py               Whisper log-mel features in NumPy (no transformers needed)
  dialog/echo.py         Milestone 2's stand-in dialog: says back the transcript
  services/
    stt_indic.py         IndicConformer Hindi 120M through onnx-asr, one worker thread
    tts_laghu.py         Laghu's OnnxTTS as an async stream with a stop event
    tts_stub.py          stand-in TTS with fixed timing
    llm_openai.py        Groq / any OpenAI-compatible streaming client
  text/
    segmenter.py         sentence cuts; never inside 10.5 or ₹2,50,000
    prep.py              Laghu's to_model_text + PAN digits + loanword lexicon
    lexicon_bfsi.py      English banking words in Devanagari
  transport/ws_server.py WebSocket protocol
  obs/trace.py           per-turn JSONL traces
clients/cli/client.py    terminal client
scripts/                 get_laghu.py, get_listen_models.py
m0/                      Milestone 0 probes and decision rules
m2/                      Milestone 2 listening probe and decision rules
tests/                   pytest suite
```

## Protocol (WebSocket, JSON control + binary audio)

Client to server: `{"type":"say","text":...}`, `{"type":"interrupt"}`, `{"type":"playback","segment_id":3,"samples":4800}`,
`{"type":"hangup"}`. Binary: microphone PCM16 little-endian, 16 kHz mono, sent continuously (silence too: the
listener counts silence on the audio clock).

Server to client: `ready`, `segment_start`, `flush`, `turn_trace`, `error`, `vad` (`speech` true/false),
`user_turn` (`text` and the turn's trace). Binary: `uint32 epoch, uint32 segment_id`
(little-endian) followed by PCM16 mono 24 kHz. The client drops audio from an epoch older than the last flush.
