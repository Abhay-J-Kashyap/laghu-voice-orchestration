# laghu-voice

A from-scratch voice agent runtime around **Laghu TTS 7M Hindi**: streaming speech out, barge-in, per-turn
latency traces. No Pipecat or LiveKit. Design: see the design plan doc (Laghu Voice Orchestrator: Design Plan).

## Where it stands

| Part | Status |
| --- | --- |
| Speaking path: text in, streamed Laghu audio out, real-time pacing | Built, tested with a stub TTS. Needs one run with the real model (below) |
| Barge-in: epochs, flush, nothing stale sent after a stop | Built, tested over a real WebSocket |
| Banking text: PAN digits, English loanwords | Built on top of Laghu's own frontend, tested |
| Per-turn traces (JSONL) | Built |
| Groq LLM client (streaming, gpt-oss reasoning turned down) | Built, tested against a mocked API. Not yet called for real |
| Milestone 0 probes (Groq, Laghu, IndicConformer) | Written, wiring checked with fakes. **Yours to run** |
| Listening path (VAD, Smart Turn, STT), dialog, eval | Not started (Milestones 2–5) |

Nothing here has run against the real Laghu weights, Groq or IndicConformer yet: the build machine couldn't
reach Hugging Face. The first run of each is yours, and so is the first run of `scripts/get_laghu.py`.

## Setup (Windows PowerShell)

```powershell
cd laghu-voice
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python scripts\get_laghu.py
```

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
Expect `34 passed`. The last of them runs the real model. To see its timing, run it on its own:

```powershell
python -m pytest tests/test_laghu_adapter.py -k real -s
```
It prints Laghu's time to first audio through the server's adapter. Send me that line.

## Talk to it

Terminal 1 (the server):
```powershell
python -m laghu_voice.server --tts laghu
```
Terminal 2 (the client):
```powershell
python clients\cli\client.py
```
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

# 2. Laghu: whole sentences vs first clauses, 3 renditions each, saved as WAVs
python m0\probe_laghu.py

# 3. IndicConformer on CPU: decode time, and CER of the clips from step 2
python -m pip install -r m0\requirements-m0.txt
python m0\probe_stt.py
python m0\probe_stt.py --groq-whisper     # optional: also time Groq's Whisper on the same clips
```
Send me the printed summaries and `m0\out\groq_replies.jsonl`. Listen to a few WAVs in `m0\out\laghu\clause`
before believing any CER number.

## Layout

```
laghu_voice/
  config.py              settings from environment / .env
  frames.py              frames between stages; audio wire format (8-byte header + PCM16)
  server.py              python -m laghu_voice.server
  orchestrator/
    session.py           one call: segmenter -> TTS worker -> pacer; epochs and interrupt
    pacing.py            real-time sending, at most 200 ms ahead of the listener
  services/
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
m0/                      Milestone 0 probes and decision rules
tests/                   pytest suite
```

## Protocol (WebSocket, JSON control + binary audio)

Client to server: `{"type":"say","text":...}`, `{"type":"interrupt"}`, `{"type":"playback","segment_id":3,"samples":4800}`,
`{"type":"hangup"}`. Binary: microphone PCM16 at 16 kHz (accepted, used from Milestone 2).

Server to client: `ready`, `segment_start`, `flush`, `turn_trace`, `error`. Binary: `uint32 epoch, uint32 segment_id`
(little-endian) followed by PCM16 mono 24 kHz. The client drops audio from an epoch older than the last flush.
