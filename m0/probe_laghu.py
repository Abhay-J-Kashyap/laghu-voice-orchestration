"""Milestone 0: time Laghu through the server's own adapter, whole sentences vs first clauses (decision rule 2).

    python m0/probe_laghu.py                  # male voice (the default)
    python m0/probe_laghu.py --voice female

For each of the 10 sentences in m0/sentences_bfsi.txt, speaks the whole sentence and its first clause
(text up to the first comma), 3 renditions each (Laghu samples, so renditions differ). Saves every clip as
m0/out/laghu_<voice>/<variant>/<id>_r<k>.wav plus m0/out/laghu_<voice>/manifest.jsonl, which probe_stt.py reads for CER.
Two warm-up calls are made first and not recorded.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import threading
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from laghu_voice.config import DEFAULT_LAGHU_DIR  # noqa: E402
from laghu_voice.services.base import TTSResult  # noqa: E402
from laghu_voice.services.tts_laghu import LaghuTTS  # noqa: E402
from laghu_voice.text.segmenter import Segmenter  # noqa: E402


def first_clause(s: str) -> str:
    """The first segment the server itself would send with LV_FIRST_CLAUSE=1 (same Segmenter, same rules:
    at least 4 words before the comma, never a comma inside an amount)."""
    seg = Segmenter(first_clause=True)
    return (seg.feed(s) + seg.flush())[0]


async def speak(tts: LaghuTTS, text: str):
    info = TTSResult()
    t0 = time.perf_counter()
    first = None
    chunks = []
    async for c in tts.stream(text, threading.Event(), info):
        first = first if first is not None else time.perf_counter() - t0
        chunks.append(c)
    total = time.perf_counter() - t0
    audio = np.concatenate(chunks) if chunks else np.zeros(0, np.float32)
    return audio, info, first, total


async def main_async(a):
    import soundfile as sf

    tts = LaghuTTS(Path(a.laghu_dir), voice=a.voice, lm_threads=a.lm_threads, decoder_threads=a.decoder_threads)
    sents = [s.strip() for s in (HERE / "sentences_bfsi.txt").read_text(encoding="utf-8").splitlines() if s.strip()]
    out = HERE / "out" / f"laghu_{a.voice}"
    for _ in range(2):
        await speak(tts, sents[0])
    rows = []
    for i, s in enumerate(sents, 1):
        clause = first_clause(s)
        variants = [("sentence", s)] + ([("clause", clause)] if clause != s else [])
        if clause == s:
            print(f"s{i:02d}: no comma with 4+ words before it, so the server would send it whole (no clause clip)")
        for variant, text in variants:
            for k in range(a.renditions):
                audio, info, first, total = await speak(tts, text)
                path = out / variant / f"s{i:02d}_r{k}.wav"
                path.parent.mkdir(parents=True, exist_ok=True)
                sf.write(path, audio, 24000)
                dur = len(audio) / 24000
                rows.append({"voice": a.voice, "id": f"s{i:02d}", "variant": variant, "rendition": k, "path": str(path.relative_to(HERE)),
                             "text": text, "model_text": info.model_text, "dropped_words": info.dropped_words,
                             "first_audio_ms": round(1000 * (first or total), 1), "total_ms": round(1000 * total, 1),
                             "audio_s": round(dur, 3), "x_real_time": round(dur / total, 2) if total else None})
                print(f"s{i:02d} {variant:8} r{k}: first audio {rows[-1]['first_audio_ms']:6.1f} ms, "
                      f"{dur:4.1f} s audio, {rows[-1]['x_real_time']}x real time")
    with (out / "manifest.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nthreads: transformer {a.lm_threads}, decoder {a.decoder_threads}")
    for variant in ("sentence", "clause"):
        v = [r for r in rows if r["variant"] == variant]
        print(f"{variant:8}: median first audio {statistics.median(r['first_audio_ms'] for r in v):.1f} ms, "
              f"median {statistics.median(r['x_real_time'] for r in v):.1f}x real time ({len(v)} clips)")
    print(f"\nwrote {out / 'manifest.jsonl'}. Next: python m0/probe_stt.py --voice {a.voice}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--laghu-dir", default=str(DEFAULT_LAGHU_DIR), help="default: vendor/laghu (scripts/get_laghu.py)")
    ap.add_argument("--voice", default="male", help="male or female; clips go to m0/out/laghu_<voice>/")
    ap.add_argument("--renditions", type=int, default=3)
    ap.add_argument("--lm-threads", type=int, default=1)
    ap.add_argument("--decoder-threads", type=int, default=1)
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
