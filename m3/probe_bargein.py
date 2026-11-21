"""Milestone 3 part B: barge-in and backchannels with the real models (m3/DECISION_RULES.md).

    python m3/probe_bargein.py

Laghu (male) speaks a fixed reply to a stand-in client that plays it in real time; a stand-in caller talks
over it: 20 female sentence clips (should interrupt) and 20 short backchannels synthesised by Laghu's female
voice (should not). Writes m3/out/bargein_runs.jsonl and m3/out/backchannels/*.wav.
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import importlib.util
import json
import math
import random
import sys
import threading
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from laghu_voice.config import Settings  # noqa: E402
from laghu_voice.frames import SAMPLE_RATE_OUT  # noqa: E402
from laghu_voice.obs.trace import TraceWriter, now_ns  # noqa: E402
from laghu_voice.orchestrator.controller import TurnController  # noqa: E402
from laghu_voice.orchestrator.listener import ListenModels  # noqa: E402
from laghu_voice.orchestrator.session import Session  # noqa: E402
from laghu_voice.services.base import TTSResult  # noqa: E402

SR = 16_000
FRAME = 320
AGENT_TEXT = ("आपके पर्सनल लोन का आवेदन हमें मिल गया है। अब मैं आपको आगे की प्रक्रिया के बारे में बताता हूँ। "
              "सबसे पहले हमें आपके पैन कार्ड और आधार कार्ड की ज़रूरत होगी। उसके बाद हम आपकी आय की जाँच करेंगे, "
              "और फिर लोन की राशि तय की जाएगी।")
BACKCHANNELS = ["हाँ।", "हम्म।", "जी।", "अच्छा।", "ठीक है।"]


def pct(xs, p):
    xs = sorted(x for x in xs if x is not None)
    return xs[max(0, math.ceil(p / 100 * len(xs)) - 1)] if xs else None


def to16k(x, sr):
    from scipy.signal import resample_poly

    g = math.gcd(sr, SR)
    return resample_poly(x, SR // g, sr // g).astype(np.float32) if sr != SR else x.astype(np.float32)


def loud_frames(x):
    db = [20 * math.log10(np.sqrt(np.mean(x[i:i + FRAME] ** 2)) + 1e-12) for i in range(0, len(x), FRAME)]
    floor = max(-40.0, max(db) - 35.0)
    return [k for k, d in enumerate(db) if d > floor]


class FakeClient:
    """Plays agent audio in real time, reports playback every 100 ms, flushes when told."""

    def __init__(self):
        self.session: Session | None = None
        self.q: collections.deque = collections.deque()
        self.min_epoch = 0
        self.played: dict[int, int] = {}
        self.events: list[tuple[int, dict]] = []
        self.stale_after_flush = 0
        self.first_play_ns: dict[str, int] = {}

    async def audio(self, f) -> None:
        if f.epoch < self.min_epoch:
            self.stale_after_flush += 1          # the server sent audio from an interrupted epoch after its flush
            return
        self.q.append([f, 0])

    async def event(self, ev: dict) -> None:
        self.events.append((now_ns(), ev))
        if ev.get("type") == "flush":
            self.min_epoch = ev["epoch"]
            self.q.clear()

    async def run(self) -> None:
        t_next, last_report = time.perf_counter(), 0.0
        while True:
            n = 480                                # 20 ms at 24 kHz
            while n and self.q:
                item = self.q[0]
                f, pos = item
                take = min(n, f.n_samples - pos)
                self.first_play_ns.setdefault(f.turn_id, now_ns())
                self.played[f.segment_id] = self.played.get(f.segment_id, 0) + take
                item[1] += take
                n -= take
                if item[1] >= f.n_samples:
                    self.q.popleft()
            if time.perf_counter() - last_report >= 0.1 and self.session is not None:
                for sid, k in self.played.items():
                    self.session.on_playback(sid, k)
                last_report = time.perf_counter()
            t_next += 0.02
            await asyncio.sleep(max(0.0, t_next - time.perf_counter()))


class Mic:
    """Feeds the listener 20 ms frames in real time: queued speech, otherwise silence."""

    def __init__(self, controller: TurnController):
        self.c = controller
        self.queue: collections.deque = collections.deque()
        self.fed_ns: dict[str, list[int]] = {}

    def say(self, name: str, x: np.ndarray) -> None:
        self.fed_ns[name] = []
        for i in range(0, len(x), FRAME):
            self.queue.append((name, x[i:i + FRAME]))

    async def run(self) -> None:
        silence = np.zeros(FRAME, np.float32)
        t_next = time.perf_counter()
        while True:
            name, frame = self.queue.popleft() if self.queue else (None, silence)
            if len(frame) < FRAME:
                frame = np.concatenate([frame, silence[:FRAME - len(frame)]])
            t = now_ns()
            self.c.listener.feed_float(frame, t)
            if name is not None:
                self.fed_ns[name].append(t)
            t_next += FRAME / SR
            await asyncio.sleep(max(0.0, t_next - time.perf_counter()))


async def synth(tts, text):
    info, out = TTSResult(), []
    async for c in tts.stream(text, threading.Event(), info):
        out.append(c)
    return np.concatenate(out) if out else np.zeros(0, np.float32)


async def trial(session, client, mic, controller, user_turns, name, x, delay_s):
    while session.agent_busy() or controller.listener.in_turn:
        await asyncio.sleep(0.05)
    n_ev, n_turns = len(client.events), len(user_turns)
    before = set(session.turns)
    say_task = asyncio.create_task(session.say(AGENT_TEXT))
    while not (set(session.turns) - before):
        await asyncio.sleep(0.005)
    turn_id = (set(session.turns) - before).pop()
    while turn_id not in client.first_play_ns:
        await asyncio.sleep(0.01)
    await asyncio.sleep(max(0.0, client.first_play_ns[turn_id] / 1e9 + delay_s - time.perf_counter_ns() / 1e9))
    stale_before = client.stale_after_flush
    loud = loud_frames(x)
    mic.say(name, x)
    while mic.queue:
        await asyncio.sleep(0.05)
    await asyncio.sleep(2.5)
    for _ in range(100):
        if not controller.listener.in_turn:
            break
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.5)
    start_ns = mic.fed_ns[name][loud[0]] if loud else None
    evs = [(t, e) for t, e in client.events[n_ev:]]
    t_of = lambda kind: next((t for t, e in evs if e.get("type") == kind), None)  # noqa: E731
    flush, duck, barge = t_of("flush"), t_of("duck"), t_of("barge_in")
    turns = [u for u in user_turns[n_turns:]]
    agent = session.trace.records
    interrupted = next((r for r in reversed(agent) if r.get("turn_id") == turn_id), None)
    if session.agent_busy():
        await session.interrupt("probe_reset")
    await say_task
    ms = lambda t: round((t - start_ns) / 1e6, 1) if t and start_ns else None  # noqa: E731
    return {"name": name, "delay_s": round(delay_s, 2), "barged_in": barge is not None,
            "duck_ms": ms(duck), "flush_ms": ms(flush), "stale_frames_after_flush": client.stale_after_flush - stale_before,
            "user_turns": len(turns), "text": " ".join(t.text for t, _ in turns).strip(),
            "speech_ms": [r.get("speech_ms") for _, r in turns],
            "backchannel": [r.get("backchannel") for _, r in turns],
            "heard": (interrupted or {}).get("heard"), "agent_outcome": (interrupted or {}).get("outcome")}


async def main_async(a):
    from laghu_voice.audio.turn import SmartTurn
    from laghu_voice.audio.vad import SileroVAD
    from laghu_voice.services.stt_indic import IndicConformerSTT
    from laghu_voice.services.tts_laghu import LaghuTTS

    vendor = ROOT / "vendor"
    settings = Settings()
    print("loading models ...")
    agent_tts = LaghuTTS(settings.laghu_dir, voice="male")
    caller_tts = LaghuTTS(settings.laghu_dir, voice="female")
    models = ListenModels(SileroVAD(vendor / "silero" / "silero_vad.onnx"),
                          IndicConformerSTT(vendor / "stt_hi120m", threads=4, pad_s=0.25),
                          SmartTurn(vendor / "smart_turn" / "smart-turn-v3.2-cpu.onnx"))
    out = HERE / "out"
    (out / "backchannels").mkdir(parents=True, exist_ok=True)
    client = FakeClient()
    session = Session(agent_tts, client.audio, client.event, settings, session_id="bargein",
                      trace_writer=TraceWriter(out, "bargein_traces"))
    client.session = session
    user_turns = []

    async def on_user_turn(ut, rec):
        user_turns.append((ut, rec))
    controller = TurnController(session, models, client.event, reply=None, barge_in_ms=a.barge_in_ms,
                                on_user_turn=on_user_turn)
    session.start()
    mic = Mic(controller)
    bg = [asyncio.create_task(client.run()), asyncio.create_task(mic.run())]

    import soundfile as sf
    rng = random.Random(a.seed)
    manifest = [json.loads(l) for l in open(ROOT / "m0" / "out" / "laghu_female" / "manifest.jsonl", encoding="utf-8")]
    clips = [r for r in manifest if r["variant"] == "sentence" and r["rendition"] in (0, 1)]
    bcs = []
    for word in BACKCHANNELS:
        for k in range(4):
            y = await synth(caller_tts, word)
            sf.write(out / "backchannels" / f"{BACKCHANNELS.index(word)}_{k}.wav", y, SAMPLE_RATE_OUT)
            bcs.append((f"bc {word} r{k}", to16k(y, SAMPLE_RATE_OUT)))
    await synth(agent_tts, "ठीक है।")                         # warm-up
    sc_spec = importlib.util.spec_from_file_location("probe_stt", ROOT / "m0" / "probe_stt.py")
    sc = importlib.util.module_from_spec(sc_spec)
    sc_spec.loader.exec_module(sc)

    rows = []
    for r in clips:
        x, sr = sf.read(ROOT / "m0" / r["path"], dtype="float32")
        row = await trial(session, client, mic, controller, user_turns, f"{r['id']} r{r['rendition']}",
                          to16k(x, sr), rng.uniform(1.0, 2.5))
        ref = sc.std_norm(r["model_text"])
        row.update(kind="barge_in", err=sc.lev(ref, sc.std_norm(row["text"])), len=len(ref))
        rows.append(row)
        print(f"barge-in {row['name']}: {'stopped' if row['barged_in'] else 'NOT stopped'}, duck {row['duck_ms']} ms, "
              f"flush {row['flush_ms']} ms, stale {row['stale_frames_after_flush']} | {row['text']}")
    for name, x in bcs:
        row = await trial(session, client, mic, controller, user_turns, name, x, rng.uniform(1.0, 2.5))
        row.update(kind="backchannel")
        rows.append(row)
        print(f"{name}: {'INTERRUPTED' if row['barged_in'] else 'ignored'}, speech {row['speech_ms']} ms, "
              f"duck {row['duck_ms']} ms | {row['text']}")
    for t in bg:
        t.cancel()
    await controller.close()
    await session.close()
    with (out / "bargein_runs.jsonl").open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    b = [r for r in rows if r["kind"] == "barge_in"]
    c = [r for r in rows if r["kind"] == "backchannel"]
    fl = [r["flush_ms"] for r in b if r["barged_in"]]
    stale = sum(r["stale_frames_after_flush"] for r in rows)
    stopped = sum(r["barged_in"] for r in b)
    b1 = stopped == len(b) and fl and pct(fl, 95) <= 400 and stale == 0
    cer = 100 * sum(r["err"] for r in b) / sum(r["len"] for r in b)
    wrong = sum(r["barged_in"] for r in c)
    print(f"\nbarge-in threshold {a.barge_in_ms:.0f} ms, seed {a.seed}")
    print(f"M3-B1 stopped {stopped}/{len(b)}; speech start -> flush p50 {pct(fl, 50)} ms, p95 {pct(fl, 95)} ms; "
          f"stale frames after flush {stale} -> {'met' if b1 else 'not met'}")
    print(f"M3-B2 backchannels that interrupted: {wrong}/{len(c)} -> {'met' if wrong <= 2 else 'not met'}")
    print(f"M3-B3 CER of barge-in transcripts: {cer:.2f}% -> {'met' if cer <= 4.0 else 'not met'} (limit 4.0%)")
    duck = [r["duck_ms"] for r in rows if r["duck_ms"] is not None]
    print(f"report: duck p50 {pct(duck, 50)} ms, p95 {pct(duck, 95)} ms; backchannel speech ms "
          f"{sorted(s for r in c for s in r['speech_ms'] if s is not None)}")
    print(f"wrote {out / 'bargein_runs.jsonl'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--barge-in-ms", type=float, default=250.0)
    ap.add_argument("--seed", type=int, default=3)
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
