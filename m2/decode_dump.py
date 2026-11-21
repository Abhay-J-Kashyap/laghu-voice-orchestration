"""Milestone 2 diagnostic (Amendment 2): decode the listener's saved segments again, in a fresh process.

    python m2/probe_listen.py --max-segment-s 3 --dump m2/out/dump      # saves every segment the listener decoded
    python m2/decode_dump.py m2/out/dump

For each saved segment, decodes the same audio with the same model, alone, and compares the text with what
the listener got. Same text: the listener passed the audio through correctly, and any garbage is the model's
answer to that audio. Different text: something in the listener's path (threads, timing, buffers) is wrong.
Then decodes each segment again with 0.5 s of silence added at both ends, to see whether short, abruptly cut
audio is what the model handles badly.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from laghu_voice.services.stt_indic import IndicConformerSTT  # noqa: E402


def main():
    import soundfile as sf

    d = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "m2" / "out" / "dump")
    rows = [json.loads(l) for l in open(d / "index.jsonl", encoding="utf-8")]
    stt = IndicConformerSTT(ROOT / "vendor" / "stt_hi120m")
    pad = np.zeros(8000, np.float32)
    same = 0
    out = []
    for r in rows:
        x, _ = sf.read(d / r["file"], dtype="float32")
        again = stt.transcribe(x)
        padded = stt.transcribe(np.concatenate([pad, x, pad]))
        same += again == r["text"]
        out.append({**r, "again": again, "padded": padded, "seconds": round(len(x) / 16000, 2)})
        flag = "" if again == r["text"] else "   <-- DIFFERENT"
        print(f"{r['file']:40} {len(x) / 16000:4.1f} s | listener: {r['text']}\n{'':40}        | again:    "
              f"{again}{flag}\n{'':40}        | padded:   {padded}")
    with (d / "redecoded.jsonl").open("w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\n{same}/{len(rows)} segments decode to the same text alone. Wrote {d / 'redecoded.jsonl'}")
    stt.close()


if __name__ == "__main__":
    main()
