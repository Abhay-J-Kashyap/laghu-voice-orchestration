"""Milestone 2: the listening path in real time on Laghu's clips (m2/DECISION_RULES.md).

    python m2/probe_listen.py                    # 30 male whole-sentence clips from Milestone 0
    python m2/probe_listen.py --no-turn-model    # same, ending turns on silence alone (for comparison)

Each clip is streamed into the server's own Listener (Silero VAD, Smart Turn, IndicConformer 120M) in 20 ms
frames at real-time pace: 0.5 s of silence, the clip resampled to 16 kHz, then 2.5 s of silence. "True end of
speech" is when the last 20 ms frame louder than -40 dBFS (or 35 dB under the clip's loudest frame, if that is
higher) was fed in. Writes m2/out/listen_runs.jsonl.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import math
import statistics
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from laghu_voice.obs.trace import now_ns  # noqa: E402
from laghu_voice.orchestrator.listener import Listener, ListenConfig  # noqa: E402

FRAME = 320
SR = 16_000


def m0_scoring():
    spec = importlib.util.spec_from_file_location("probe_stt", ROOT / "m0" / "probe_stt.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def pct(xs, p):
    xs = sorted(x for x in xs if x is not None)
    return xs[max(0, math.ceil(p / 100 * len(xs)) - 1)] if xs else None


def load16k(path):
    import soundfile as sf
    from scipy.signal import resample_poly

    x, sr = sf.read(path, dtype="float32")
    if x.ndim > 1:
        x = x.mean(1)
    g = math.gcd(sr, SR)
    return resample_poly(x, SR // g, sr // g).astype(np.float32) if sr != SR else x


async def run_clip(listener, turns, x, lead_s=0.5, trail_s=2.5):
    audio = np.concatenate([np.zeros(int(lead_s * SR), np.float32), x, np.zeros(int(trail_s * SR), np.float32)])
    db = [20 * math.log10(np.sqrt(np.mean(audio[i:i + FRAME] ** 2)) + 1e-12) for i in range(0, len(audio), FRAME)]
    floor = max(-40.0, max(db) - 35.0)       # -40 dBFS, or 35 dB under the loudest frame if that is higher
    loud = [k * FRAME for k, d in enumerate(db) if d > floor]
    last_loud = loud[-1] if loud else None
    true_end_ns = None
    before = len(turns)
    t_next = time.perf_counter()
    for i in range(0, len(audio), FRAME):
        t = now_ns()
        listener.feed_float(audio[i:i + FRAME], t)
        if i == last_loud:
            true_end_ns = t
        t_next += FRAME / SR
        await asyncio.sleep(max(0.0, t_next - time.perf_counter()))
    for _ in range(100):                     # let a turn that ended near the end of the trail finish decoding
        if listener.in_turn is False and len(turns) > before:
            break
        await asyncio.sleep(0.02)
    return turns[before:], true_end_ns


async def main_async(a):
    from laghu_voice.audio.turn import SmartTurn
    from laghu_voice.audio.vad import SileroVAD
    from laghu_voice.services.stt_indic import IndicConformerSTT

    vendor = ROOT / "vendor"
    vad = SileroVAD(vendor / "silero" / "silero_vad.onnx")
    turn = None if a.no_turn_model else SmartTurn(vendor / "smart_turn" / "smart-turn-v3.2-cpu.onnx")
    print(f"loading STT ({a.stt_threads} threads) ...")
    stt = IndicConformerSTT(vendor / "stt_hi120m", threads=a.stt_threads, pad_s=a.stt_pad_s)
    turns = []

    async def on_turn(t):
        turns.append(t)
    lis = Listener(vad, stt, turn, on_turn, None, "probe",
                   ListenConfig(spec_ms=a.spec_ms, tail_ms=a.tail_ms, max_segment_s=a.max_segment_s,
                                dump_dir=a.dump))
    sc = m0_scoring()
    manifest = [json.loads(l) for l in open(ROOT / "m0" / "out" / f"laghu_{a.voice}" / "manifest.jsonl",
                                            encoding="utf-8")]
    clips = [r for r in manifest if r["variant"] == "sentence"]
    rows = []
    for r in clips:
        got, true_end = await run_clip(lis, turns, load16k(ROOT / "m0" / r["path"]))
        recs = [t.trace.to_record() for t in got]
        text = " ".join(t.text for t in got).strip()
        ref, hyp = sc.std_norm(r["model_text"]), sc.std_norm(text)
        row = {"id": r["id"], "rendition": r["rendition"], "turns": len(got), "text": text,
               "err": sc.lev(ref, hyp), "len": len(ref)}
        if got:
            last = got[-1].trace.marks
            row["long_cuts"] = sum(len(x.get("long_cuts", [])) for x in recs)
            row.update({
                "true_end_to_transcript_ms": round((last["stt_final"] - true_end) / 1e6, 1) if true_end else None,
                "true_end_to_turn_end_ms": round((last["turn_end"] - true_end) / 1e6, 1) if true_end else None,
                "vad_end_to_transcript_ms": recs[-1]["latency_ms"]["speech_end_to_transcript"],
                "end_reason": recs[-1]["end_reason"], "turn_checks": recs[-1]["turn_checks"],
                "segments": recs[-1]["segments"], "wasted_decodes": sum(x["wasted_decodes"] for x in recs)})
        rows.append(row)
        print(f"{r['id']} r{r['rendition']}: {len(got)} turn(s), transcript "
              f"{row.get('true_end_to_transcript_ms')} ms, turn end {row.get('true_end_to_turn_end_ms')} ms "
              f"({row.get('end_reason')}) | {text}")
    out = HERE / "out"
    out.mkdir(exist_ok=True)
    name = ("listen_runs" + ("" if a.voice == "male" else f"_{a.voice}")
            + ("_no_turn_model" if a.no_turn_model else "") + ("_diag" if a.dump else "") + ".jsonl")
    with (out / name).open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    ok = [r for r in rows if r["turns"] == 1]
    heard = [r for r in rows if r["turns"] >= 1]       # Amendment 1: M2-1 uses every clip's last turn
    tr = [r["true_end_to_transcript_ms"] for r in heard]
    te = [r["true_end_to_turn_end_ms"] for r in heard]
    cer = 100 * sum(r["err"] for r in rows) / sum(r["len"] for r in rows)
    bad = [f"{r['id']} r{r['rendition']} ({r['turns']} turns)" for r in rows if r["turns"] != 1]
    reasons = {k: sum(1 for r in heard if r["end_reason"] == k) for k in {r["end_reason"] for r in heard}}
    probs = [c["prob"] for r in heard for c in r["turn_checks"][:1]]
    st_ms = [c["ms"] for r in heard for c in r["turn_checks"]]
    print(f"\n{len(rows)} clips, {a.voice} voice, STT {a.stt_threads} threads, "
          f"{'no turn model' if a.no_turn_model else 'Smart Turn v3.2'}, spec {a.spec_ms} ms, tail {a.tail_ms} ms, "
          f"segments cut at {a.max_segment_s} s, {a.stt_pad_s} s of silence around each")
    print(f"M2-1 end of speech -> final transcript: p50 {pct(tr, 50)} ms, p95 {pct(tr, 95)} ms -> "
          f"{'met' if tr and pct(tr, 95) <= 400 else 'not met'} (limit 400)")
    print(f"M2-2 in-loop CER (standard): {cer:.2f}% -> {'met' if cer <= 3.68 else 'not met'} (limit 3.68%)")
    print(f"M2-3 clips with exactly one turn: {len(ok)}/{len(rows)} -> {'met' if len(rows) - len(ok) <= 1 else 'not met'}"
          + (f"; not one turn: {', '.join(bad)}" if bad else ""))
    print(f"report: end of speech -> turn end p50 {pct(te, 50)} ms, p95 {pct(te, 95)} ms; ended by {reasons}")
    if probs:
        print(f"report: Smart Turn first answer: median prob {statistics.median(probs):.2f}, "
              f"{sum(p >= 0.5 for p in probs)}/{len(probs)} said 'done'; inference p50 {pct(st_ms, 50)} ms, "
              f"p95 {pct(st_ms, 95)} ms")
    print(f"report: wasted speculative decodes {sum(r.get('wasted_decodes', 0) for r in heard)}; VAD "
          f"{lis.vad_ns / max(1, lis.windows) / 1e3:.0f} us per 32 ms window")
    print(f"wrote {out / name}")
    stt.close()
    await lis.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--voice", default="male")
    ap.add_argument("--no-turn-model", action="store_true")
    ap.add_argument("--stt-threads", type=int, default=4)
    ap.add_argument("--spec-ms", type=int, default=96)
    ap.add_argument("--tail-ms", type=int, default=96)
    ap.add_argument("--max-segment-s", type=float, default=10.0)
    ap.add_argument("--stt-pad-s", type=float, default=0.25, help="silence added around each segment")
    ap.add_argument("--dump", help="diagnostics: save every decoded segment as a WAV in this folder")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
