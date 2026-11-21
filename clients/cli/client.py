"""Terminal client: talk to the agent, or type Hindi text and hear Laghu say it.

    python clients/cli/client.py --mic                   # speak into the microphone (Milestone 2)
    python clients/cli/client.py                         # no mic: type text; /wav plays a recording as your voice
    python clients/cli/client.py --no-audio --save out.wav   # no sound device: plays silently in real time, saves

Commands: any text = say it (with the agent, --dialog agent: a typed caller turn instead); /say text = make the
agent say it; /file story.txt = say a UTF-8 file; /textfile lines.txt = send the file's next line as a caller
turn; /wav clip.wav = send a recording to the server as if you had spoken it; /stop = interrupt; /quit = hang up.
With the agent, the client prints the demo passcode to read out, and exits when the agent ends the call.
Without --mic the client still sends silence continuously, so the server can tell when a /wav turn ends.
The client keeps a small playback buffer, reports how much of each segment it has played, and drops its
buffer when the server says "flush". Audio from an older epoch is dropped too, as a second safety net.
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import json
import sys
import threading
import time
import wave

import numpy as np
from websockets.asyncio.client import connect

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
from laghu_voice.frames import unpack_audio  # noqa: E402

SR = 24_000
DUCK = 0.3               # agent volume while the caller talks over it
MIC_SR = 16_000
MIC_FRAME = 320          # 20 ms


def load_wav_16k(path: str) -> np.ndarray:
    """Any WAV/FLAC as int16 mono 16 kHz."""
    import soundfile as sf
    from math import gcd

    x, sr = sf.read(path, dtype="float32")
    if x.ndim > 1:
        x = x.mean(1)
    if sr != MIC_SR:
        from scipy.signal import resample_poly

        g = gcd(sr, MIC_SR)
        x = resample_poly(x, MIC_SR // g, sr // g)
    return (np.clip(x, -1, 1) * 32767).astype(np.int16)


class Player:
    """Thread-safe playback buffer shared by the audio callback and the network loop."""

    def __init__(self):
        self.lock = threading.Lock()
        self.chunks: collections.deque = collections.deque()  # [segment_id, int16 array, position]
        self.min_epoch = 0
        self.played: dict[int, int] = {}
        self.recorded: list[np.ndarray] = []
        self.volume = 1.0              # lowered to DUCK while the caller talks over the agent

    def feed(self, epoch: int, segment_id: int, pcm: bytes) -> None:
        x = np.frombuffer(pcm, dtype="<i2")
        with self.lock:
            if epoch < self.min_epoch:
                return
            self.chunks.append([segment_id, x, 0])

    def flush(self, epoch: int) -> None:
        with self.lock:
            self.min_epoch = epoch
            self.chunks.clear()
            self.volume = 1.0

    def pull(self, n: int) -> np.ndarray:
        out = np.zeros(n, dtype=np.int16)
        k = 0
        with self.lock:
            while k < n and self.chunks:
                c = self.chunks[0]
                sid, x, pos = c
                take = min(n - k, len(x) - pos)
                out[k:k + take] = x[pos:pos + take]
                k += take
                c[2] = pos + take
                self.played[sid] = self.played.get(sid, 0) + take
                if c[2] >= len(x):
                    self.chunks.popleft()
        if self.volume != 1.0:
            out = (out.astype(np.float32) * self.volume).astype(np.int16)
        self.recorded.append(out[:k].copy())
        return out


async def main_async(a) -> None:
    player = Player()
    state = {"agent": False, "ended": False, "textfile_pos": {}}
    stream = None
    if not a.no_audio:
        try:
            import sounddevice as sd
        except (ImportError, OSError) as e:
            raise SystemExit(f"sounddevice unavailable ({e}); use --no-audio") from e

        def cb(outdata, frames, _time, _status):
            outdata[:, 0] = player.pull(frames)

        stream = sd.OutputStream(samplerate=SR, channels=1, dtype="int16", blocksize=960, callback=cb)
        stream.start()

    loop = asyncio.get_running_loop()
    mic_q: asyncio.Queue[bytes] = asyncio.Queue()
    mic = None
    if a.mic:
        import sounddevice as sd

        def mic_cb(indata, frames, _time, _status):
            loop.call_soon_threadsafe(mic_q.put_nowait, bytes(indata))

        mic = sd.RawInputStream(samplerate=MIC_SR, channels=1, dtype="int16", blocksize=MIC_FRAME, callback=mic_cb)
        mic.start()
    wav_q: asyncio.Queue[np.ndarray] = asyncio.Queue()

    async with connect(a.url, max_size=2**20) as ws:
        async def send_mic():
            while True:
                await ws.send(await mic_q.get())

        async def send_wav_and_silence():
            """No mic: stream /wav recordings in real time, silence in between (20 ms frames)."""
            silence = np.zeros(MIC_FRAME, np.int16)
            current, pos = None, 0
            t_next = time.perf_counter()
            while True:
                if current is None and not wav_q.empty():
                    current, pos = wav_q.get_nowait(), 0
                if current is not None:
                    frame = current[pos:pos + MIC_FRAME]
                    pos += MIC_FRAME
                    if pos >= len(current):
                        current = None
                    if len(frame) < MIC_FRAME:
                        frame = np.concatenate([frame, silence[:MIC_FRAME - len(frame)]])
                else:
                    frame = silence
                await ws.send(frame.tobytes())
                t_next += MIC_FRAME / MIC_SR
                await asyncio.sleep(max(0.0, t_next - time.perf_counter()))

        async def virtual_playback():  # no sound device: consume audio at real-time pace anyway
            t_last = time.perf_counter()
            while True:
                await asyncio.sleep(0.02)
                now = time.perf_counter()
                player.pull(int((now - t_last) * SR))
                t_last = now

        async def report_playback():
            sent: dict[int, int] = {}
            while True:
                await asyncio.sleep(0.1)
                with player.lock:
                    played = dict(player.played)
                for sid, n in played.items():
                    if sent.get(sid) != n:
                        sent[sid] = n
                        await ws.send(json.dumps({"type": "playback", "segment_id": sid, "samples": n}))

        async def receive():
            async for msg in ws:
                if isinstance(msg, bytes):
                    epoch, sid, pcm = unpack_audio(msg)
                    player.feed(epoch, sid, pcm)
                    continue
                ev = json.loads(msg)
                kind = ev.get("type")
                if kind == "ready":
                    print(f"[connected: session {ev['session_id']}]")
                    if ev.get("dialog") == "agent":
                        state["agent"] = True
                        print("[the agent will speak first. Talk (--mic), /wav a recording, or type a caller turn "
                              "(PowerShell garbles typed Hindi: /textfile file.txt sends a UTF-8 file's line); "
                              "/say makes the agent say text]")
                elif kind == "segment_start":
                    print(f"  > {ev['text']}")
                elif kind == "flush":
                    player.flush(ev["epoch"])
                    print("  [stopped]")
                elif kind == "turn_trace":
                    ms = ev["trace"]["ms"]
                    first = ms.get("first_audio_sent")
                    stop = (ms["flush_sent"] - ms["interrupt_received"]) if "flush_sent" in ms else None
                    parts = [f"{ev['trace']['outcome']}"]
                    heard = ev["trace"].get("heard")
                    if heard:
                        parts.append(f"you heard about {heard['played_s']:.1f} s")
                    if first is not None:
                        parts.append(f"first audio sent {first:.0f} ms after text")
                    if stop is not None:
                        parts.append(f"interrupt handled in {stop:.1f} ms")
                    print("  [" + ", ".join(parts) + "]")
                elif kind == "duck":
                    player.volume = DUCK
                elif kind == "unduck":
                    player.volume = 1.0
                elif kind == "barge_in":
                    print("  [you interrupted: agent stopped]")
                elif kind == "user_turn" and ev.get("backchannel"):
                    print(f"you (over the agent, not an interruption): {ev['text']}")
                elif kind == "user_turn":
                    lat = ev["trace"].get("latency_ms", {})
                    if "speech_start_to_flush_sent" in lat:
                        print(f"  [agent stopped {lat['speech_start_to_flush_sent']:.0f} ms after you started]")
                    print(f"you: {ev['text'] or '(nothing recognised)'}")
                    print(f"  [turn ended by {ev['trace'].get('end_reason')}: transcript ready "
                          f"{lat.get('speech_end_to_transcript', 0):.0f} ms after you stopped, turn ended "
                          f"{lat.get('speech_end_to_turn_end', 0):.0f} ms after]")
                elif kind == "dialog" and ev.get("show"):
                    for k, v in ev["show"].items():
                        print(f"  [{k.replace('_', ' ')}: {' '.join(str(v))}  <- read this out]")
                elif kind == "dialog":
                    tools = ", ".join(f"{t['tool']}: {t['outcome']} ({t['ms']:.0f} ms)" for t in ev.get("tools") or [])
                    if a.show_dialog or tools:
                        llm = f", LLM {'+'.join(map(str, ev['llm_ms']))} ms" if ev.get("llm_ms") else ""
                        filler = ", filler played" if ev.get("filler") else ""
                        print(f"  [agent: {ev.get('event') or 'start'} -> {ev.get('state') or ev.get('end')}"
                              f" ({ev.get('path') or '-'}{llm}{filler}){'; ' + tools if tools else ''}]")
                elif kind == "end_call":
                    print(f"[call ended by the agent: {ev['reason']}; backend session {ev.get('backend_session')}]")
                    state["ended"] = True
                elif kind == "vad" and a.show_vad:
                    print("  (speaking)" if ev["speech"] else "  (pause)")
                elif kind == "error":
                    print(f"  [server error: {ev['error']}]")

        async def read_stdin():
            loop = asyncio.get_running_loop()
            lines: asyncio.Queue[str] = asyncio.Queue()

            def reader():   # a daemon thread, so a blocked readline doesn't keep the client alive at the end
                for raw in sys.stdin:
                    loop.call_soon_threadsafe(lines.put_nowait, raw)
                loop.call_soon_threadsafe(lines.put_nowait, "")

            threading.Thread(target=reader, daemon=True).start()
            while True:
                line = await lines.get()
                if not line:
                    await ws.send(json.dumps({"type": "hangup"}))
                    return
                line = line.strip()
                if not line:
                    continue
                if line == "/quit":
                    await ws.send(json.dumps({"type": "hangup"}))
                    return
                if line == "/stop":
                    await ws.send(json.dumps({"type": "interrupt", "reason": "user_typed_stop"}))
                elif line.startswith("/wav "):
                    if a.mic:
                        print("  [/wav needs the client started without --mic]")
                    else:
                        try:
                            wav_q.put_nowait(await loop.run_in_executor(None, load_wav_16k, line[5:].strip()))
                        except Exception as e:  # noqa: BLE001
                            print(f"  [could not read {line[5:].strip()}: {e}]")
                elif line.startswith("/file "):   # PowerShell can garble typed Hindi; a UTF-8 file can't
                    text = open(line[6:].strip(), encoding="utf-8-sig").read().strip()
                    await ws.send(json.dumps({"type": "say", "text": text}))
                elif line.startswith("/textfile "):   # a caller turn from a file: the next unused line of it
                    path = line[10:].strip()
                    lines = [x.strip() for x in open(path, encoding="utf-8-sig") if x.strip()]
                    k = state["textfile_pos"].get(path, 0)
                    if k >= len(lines):
                        print(f"  [no lines left in {path}]")
                        continue
                    state["textfile_pos"][path] = k + 1
                    print(f"you (typed): {lines[k]}")
                    await ws.send(json.dumps({"type": "text", "text": lines[k]}))
                elif line.startswith("/say "):
                    await ws.send(json.dumps({"type": "say", "text": line[5:]}))
                elif state["agent"]:
                    await ws.send(json.dumps({"type": "text", "text": line}))
                else:
                    await ws.send(json.dumps({"type": "say", "text": line}))

        tasks = [asyncio.create_task(receive()), asyncio.create_task(report_playback()),
                 asyncio.create_task(send_mic() if a.mic else send_wav_and_silence())]
        if stream is None:
            tasks.append(asyncio.create_task(virtual_playback()))
        stdin_task = asyncio.create_task(read_stdin())
        await asyncio.wait([stdin_task, tasks[0]], return_when=asyncio.FIRST_COMPLETED)   # tasks[0]: receive()
        stdin_task.cancel()
        await asyncio.sleep(0.2)
        for t in tasks:
            t.cancel()

    if stream is not None:
        stream.stop()
        stream.close()
    if mic is not None:
        mic.stop()
        mic.close()
    if a.save:
        audio = np.concatenate(player.recorded) if player.recorded else np.zeros(0, np.int16)
        with wave.open(a.save, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(audio.tobytes())
        print(f"saved {len(audio) / SR:.1f} s of played audio to {a.save}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="ws://127.0.0.1:8765")
    ap.add_argument("--no-audio", action="store_true", help="no sound device: play silently in real time")
    ap.add_argument("--save", help="write everything played to this WAV file")
    ap.add_argument("--mic", action="store_true", help="send the microphone (use headphones)")
    ap.add_argument("--show-vad", action="store_true", help="print when the server hears speech start and stop")
    ap.add_argument("--show-dialog", action="store_true", help="print every step of the agent, not only tool calls")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
