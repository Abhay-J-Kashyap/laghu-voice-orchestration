"""Terminal client: type Hindi text, hear Laghu say it, type /stop to barge in.

    python clients/cli/client.py                         # plays through your speakers (needs sounddevice)
    python clients/cli/client.py --no-audio --save out.wav   # no sound device: plays silently in real time, saves

Commands: any text = say it; /file story.txt = say a UTF-8 file; /stop = interrupt; /quit = hang up.
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


class Player:
    """Thread-safe playback buffer shared by the audio callback and the network loop."""

    def __init__(self):
        self.lock = threading.Lock()
        self.chunks: collections.deque = collections.deque()  # [segment_id, int16 array, position]
        self.min_epoch = 0
        self.played: dict[int, int] = {}
        self.recorded: list[np.ndarray] = []

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
        self.recorded.append(out[:k].copy())
        return out


async def main_async(a) -> None:
    player = Player()
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

    async with connect(a.url, max_size=2**20) as ws:
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
                    if first is not None:
                        parts.append(f"first audio sent {first:.0f} ms after text")
                    if stop is not None:
                        parts.append(f"interrupt handled in {stop:.1f} ms")
                    print("  [" + ", ".join(parts) + "]")
                elif kind == "error":
                    print(f"  [server error: {ev['error']}]")

        async def read_stdin():
            loop = asyncio.get_running_loop()
            while True:
                line = await loop.run_in_executor(None, sys.stdin.readline)
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
                elif line.startswith("/file "):   # PowerShell can garble typed Hindi; a UTF-8 file can't
                    text = open(line[6:].strip(), encoding="utf-8-sig").read().strip()
                    await ws.send(json.dumps({"type": "say", "text": text}))
                else:
                    await ws.send(json.dumps({"type": "say", "text": line}))

        tasks = [asyncio.create_task(receive()), asyncio.create_task(report_playback())]
        if stream is None:
            tasks.append(asyncio.create_task(virtual_playback()))
        await read_stdin()
        await asyncio.sleep(0.2)
        for t in tasks:
            t.cancel()

    if stream is not None:
        stream.stop()
        stream.close()
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
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
