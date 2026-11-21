"""Milestone 2 diagnostic (Amendment 3): how much silence must surround a segment for the STT to read it?

    python m2/pad_sweep.py                       # uses m2/out/dump from probe_listen.py --dump

decode_dump.py showed that the listener hands the model the right audio, and that 0.5 s of silence added at
both ends of each segment brings run 2's CER from 16.56% to 3.80%. This tries several amounts of silence
before and after, on the segments the listener actually kept (speculative decodes it threw away are
skipped), and reports CER against each clip's model text and the decode time. Writes m2/out/pad_sweep.jsonl.
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import math
import re
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

VARIANTS = [(0.0, 0.0), (0.1, 0.1), (0.25, 0.25), (0.5, 0.5), (0.0, 0.25), (0.25, 0.0), (0.0, 0.5), (0.5, 0.0)]


def scoring():
    spec = importlib.util.spec_from_file_location("probe_stt", ROOT / "m0" / "probe_stt.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def pct(xs, p):
    xs = sorted(xs)
    return xs[max(0, math.ceil(p / 100 * len(xs)) - 1)]


def kept_segments(index_rows, runs, model_text):
    """Per clip: its reference text and the segments the listener kept, in order.
    The index is written in decode-completion order; for a turn and a start time the last entry is the one
    that was kept (earlier ones were speculative decodes thrown away when the caller kept talking)."""
    turns: dict[int, dict] = collections.OrderedDict()
    for r in index_rows:
        u = int(re.match(r"probe_u(\d+)_", r["file"])[1])
        turns.setdefault(u, {})[r["start_s"]] = r
    order = sorted(turns)
    clips, i = [], 0
    for run in runs:
        us, i = order[i:i + run["turns"]], i + run["turns"]
        segs = [s for u in us for _, s in sorted(turns[u].items())]
        clips.append({"id": run["id"], "rendition": run["rendition"], "listener_err": run["err"],
                      "ref": model_text[(run["id"], run["rendition"])], "segments": segs})
    return clips


def main():
    import soundfile as sf
    from laghu_voice.services.stt_indic import IndicConformerSTT

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump", default=str(HERE / "out" / "dump"))
    ap.add_argument("--runs", default=str(HERE / "out" / "listen_runs_diag.jsonl"))
    ap.add_argument("--voice", default="male")
    a = ap.parse_args()
    sc = scoring()
    dump = Path(a.dump)
    index_rows = [json.loads(l) for l in open(dump / "index.jsonl", encoding="utf-8")]
    runs = [json.loads(l) for l in open(a.runs, encoding="utf-8")]
    manifest = [json.loads(l) for l in open(ROOT / "m0" / "out" / f"laghu_{a.voice}" / "manifest.jsonl",
                                            encoding="utf-8")]
    model_text = {(r["id"], r["rendition"]): r["model_text"] for r in manifest if r["variant"] == "sentence"}
    clips = kept_segments(index_rows, runs, model_text)
    audio = {s["file"]: sf.read(dump / s["file"], dtype="float32")[0] for c in clips for s in c["segments"]}
    stt = IndicConformerSTT(ROOT / "vendor" / "stt_hi120m")
    out = []
    print(f"{len(clips)} clips, {len(audio)} kept segments")
    for lead, trail in VARIANTS:
        pre, post = np.zeros(int(lead * 16000), np.float32), np.zeros(int(trail * 16000), np.float32)
        err = n = 0
        times = []
        for c in clips:
            texts = []
            for s in c["segments"]:
                t0 = time.perf_counter()
                texts.append(stt.transcribe(np.concatenate([pre, audio[s["file"]], post])))
                times.append(1000 * (time.perf_counter() - t0))
            ref = sc.std_norm(c["ref"])
            err += sc.lev(ref, sc.std_norm(" ".join(t for t in texts if t)))
            n += len(ref)
        row = {"lead_s": lead, "trail_s": trail, "cer": round(100 * err / n, 2),
               "decode_ms_p50": round(pct(times, 50), 1), "decode_ms_p95": round(pct(times, 95), 1)}
        out.append(row)
        print(f"silence before {lead:.2f} s, after {trail:.2f} s: CER {row['cer']:5.2f}%, decode p50 "
              f"{row['decode_ms_p50']:.0f} ms, p95 {row['decode_ms_p95']:.0f} ms")
    with (HERE / "out" / "pad_sweep.jsonl").open("w", encoding="utf-8") as f:
        for row in out:
            f.write(json.dumps(row) + "\n")
    print(f"wrote {HERE / 'out' / 'pad_sweep.jsonl'}")
    stt.close()


if __name__ == "__main__":
    main()
