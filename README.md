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
| Listening path: Silero VAD, Smart Turn, IndicConformer 120M, speculative STT, echo reply | Built and measured (Milestone 2, `m2\DECISION_RULES.md`) |
| Barge-in: duck at once, interrupt after 250 ms of speech, backchannels ignored | Built and measured (Milestone 3, `m3\DECISION_RULES.md`) |
| Dialog: an engine for any use case, configured by a spec (slots, intents, tools, lines); fixed, template and LLM-written lines, checked sentence by sentence; filler | Built and tested with stand-ins (Milestone 4). Two agents: loan onboarding (your backend) and gym onboarding (mock tools). Closed without its judged runs (Amendment 4) |
| Setup from a description: the platform writes and tests the spec | Rules written (Milestone 5, `m5\DECISION_RULES.md`); being built |

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
Expect `248 passed`. Tests that need a model you haven't downloaded are skipped, and say which script to run. To see its timing, run it on its own:

```powershell
python -m pytest tests/test_laghu_adapter.py -k real -s
```
It prints Laghu's time to first audio through the server's adapter. Send me that line.

## Talk to it

**By voice.** Use headphones: you can interrupt the agent by talking over it (barge-in), so a speaker next to
the mic would make it interrupt itself. With a speaker, start the server with `--half-duplex` (the mic is
ignored while the agent speaks, as in Milestone 2).

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

Talking over the agent lowers its volume at once; keep talking for a quarter of a second and it stops and
listens. A short "haan" over it is treated as a backchannel: the volume comes back and it carries on.

Server options: `--listen stub` (no listening models: loudness VAD and a fixed transcript), `--listen off`
(Milestone 1 behaviour), `--no-turn-model` (end turns after 700 ms of silence), `--dialog none` (listen only),
`--half-duplex` (no barge-in), `--barge-in-ms 250` (how long you must talk over the agent to stop it).

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

## Milestone 4: agents

An agent is one YAML file in `agents\`. The engine (`laghu_voice\dialog\`) knows no use case; the spec
declares everything:

- **slots:** what to ask for, by type (name, date, pan, digits, money, duration, choice, email), with a
  re-ask line for each problem.
- **intents:** requests of its own, with trigger phrases (for example "कोड नहीं आया", "the code didn't come").
- **tools:** HTTP calls, or mock answers, plus rules that turn each answer into an event.
- **states:** the flow.
- **knowledge:** facts the LLM may use to answer questions (plans, fees, timings). Their numbers may be said.
- **lines:** what the agent says, in three kinds:
  - `"text"` is said exactly. With no `{values}` it is synthesised once at startup; with values it is filled
    in during the call (template).
  - `{llm: goal, example: "text"}` is written by Groq each time. Every sentence is checked before Laghu says
    it, and the example is said if a check fails.

The loader refuses a spec with नमस्ते, English letters, feminine forms for a male agent, an LLM line that
uses a private value, or a missing target. Every Hindi line has its English meaning beside it.

| Agent | Tools | Run with |
| --- | --- | --- |
| `loan_onboarding.yaml` (judged in Milestone 4) | your Voice Onboarding Agent backend | `--dialog agent` |
| `gym_onboarding.yaml` (a made-up gym, to show the engine is general) | mock answers in the spec, no backend | `--dialog agent --agent-spec agents\gym_onboarding.yaml` |

Try the gym agent first: it needs only `GROQ_API_KEY`. `m4\gym_test_calls.md` has seven test calls
(Hindi in English letters) aimed at its edge cases. Answer its questions about your fitness goal, the plan
(monthly, quarterly or yearly), the batch time and when to start. Ask it about the plans, ask for a discount, or
ask for a free trial at any point: it explains that the trial is one day only and asks before booking.

When the rules hear two options ("between morning and afternoon") or a range ("one or two weeks"), they don't
pick one: the agent asks again. An intent found by its phrases can't trigger a tool (a booking) without a
question first, unless the spec marks it `act_directly: true`; the loader checks this.

**Milestone 4 is closed without its judged runs** (`m4\DECISION_RULES.md`, Amendment 4): the goal moved
from "does the loan agent work" to "can the platform set up any use case", which Milestone 5 tests. The
evidence it closed on: 42 of 42 typed loan calls with a scripted stand-in for Groq against the real backend,
the test suite, and eight live gym calls. `m4\run_dialog_eval.py` and `m4\auto_calls.py` still work if you
want to run them.

## Milestone 5: set up an agent from a description

Rules: `m5\DECISION_RULES.md`. You write a use case in plain English; the setup tool asks you what's missing,
writes the spec, checks it, tests it with simulated callers, and writes a review in English.

```powershell
python -m laghu_voice.setup m5\use_cases\mba.md          # about 15-25 minutes; answer its questions, then wait
# read m5\out\setup\mba\review.md, then:
python -m laghu_voice.setup approve m5\out\setup\mba     # copies the spec to agents\mba.yaml
python m5\simulate.py agents\mba.yaml m5\use_cases\mba.md  # fresh simulated callers against it
```

Uses Groq: `openai/gpt-oss-120b` writes the spec and plays the callers; the agent stays on `gpt-oss-20b`. Every
request is paced to Groq's free-tier limits; at the daily limit it stops and tells you to run the same command
tomorrow (the simulator resumes where it stopped). `python m5\cache_probe.py` measures the prompts.

### The setup UI in the browser

The same setup tool, as a web page: describe the call, answer its questions, watch the build and the eight test
calls live (each failed call labelled with its likely cause: spec, engine, test caller or judge), read every line
and transcript in Latin letters with the English meaning, and approve. Runs made from the command line show up too.

```powershell
pip install -r requirements.txt                 # adds fastapi and uvicorn
python -m laghu_voice.web                       # http://localhost:8000 (the built page is in web\dist)
```

To change the page, or to add the Dot Matrix loaders (until then a small dot grid stands in), you need Node.js:

```powershell
cd web
npm install
npx shadcn@latest add @dotmatrix/dotm-square-3 @dotmatrix/dotm-circular-20 @dotmatrix/dotm-square-18 @dotmatrix/dotm-3x3-1
npm run dev        # http://localhost:5173, with python -m laghu_voice.web running for the API
npm run build      # writes web\dist, which python -m laghu_voice.web serves
```

The landing page's pictures are made by scripts, so they can be changed. With `npm run dev` running:
`python web\tools\halftone\shoot.py` renders the hero's two looks of `web\tools\halftone\photo.jpg` (Paper's
halftone dots: the dithered default and the colour mosaic the cursor reveals), `python web\tools\grains\shoot.py`
renders the grain cards, and `python web\tools\sprites\make_sprites.py` writes the index icons.

Setup jobs run one at a time (Groq's per-minute limit is per model). Progress is written to
`m5\out\setup\<agent>\events.jsonl` as it happens, so reloading the page or restarting the server loses nothing.

## Milestone 3 part B: the barge-in probe

```powershell
python m3\probe_bargein.py
```

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
    controller.py        who holds the floor: duck, barge-in, backchannels, replies
  audio/
    vad.py               Silero VAD v5 (ONNX), one state per call
    turn.py              Smart Turn v3.2: last 8 s of audio -> P(turn finished)
    mel.py               Whisper log-mel features in NumPy (no transformers needed)
  dialog/
    agent.py             the engine: rules first, LLM second, spec transitions, tools, streamed replies
    spec.py              loads and checks agents/*.yaml
    slots.py             slot types: how each is read, checked, sent to a tool and said back
    tools.py             a spec's tools: request bodies, HTTP or mock, answer -> event rules
    hindi.py             reading PAN / passcode / dates / amounts / days from Hindi; numbers as words; masking
    llm.py               understanding (JSON, may write the reply too) and streamed writing; leak check
    guard.py             checks on every LLM-written sentence, and on everything spoken
    backend.py           HTTP with idempotency keys, one retry on timeout
    runner.py            the agent inside a call: filler, interruptions, silence re-prompts, end of call
    echo.py              Milestone 2's stand-in dialog: says back the transcript
  services/
    stt_indic.py         IndicConformer Hindi 120M through onnx-asr, one worker thread
    tts_laghu.py         Laghu's OnnxTTS as an async stream with a stop event
    tts_stub.py          stand-in TTS with fixed timing
    tts_cache.py         fixed lines synthesised once at startup
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
m3/                      Milestone 3 decision rules and barge-in probe
m4/                      Milestone 4 decision rules, typed-call scenarios and eval, live scripts and summary
agents/                  agent specs: loan_onboarding.yaml, gym_onboarding.yaml
tests/                   pytest suite
```

## Protocol (WebSocket, JSON control + binary audio)

Client to server: `{"type":"say","text":...}`, `{"type":"text","text":...}` (a typed caller turn), `{"type":"interrupt"}`, `{"type":"playback","segment_id":3,"samples":4800}`,
`{"type":"hangup"}`. Binary: microphone PCM16 little-endian, 16 kHz mono, sent continuously (silence too: the
listener counts silence on the audio clock).

Server to client: `ready`, `segment_start`, `flush`, `turn_trace`, `error`, `vad` (`speech` true/false),
`user_turn` (`text`, `backchannel` and the turn's trace), `duck`, `unduck`, `barge_in`, `dialog` (what the agent did;
`demo_otp` in demo mode), `end_call`. Binary: `uint32 epoch, uint32 segment_id`
(little-endian) followed by PCM16 mono 24 kHz. The client drops audio from an epoch older than the last flush.
