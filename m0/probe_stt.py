"""Milestone 0: IndicConformer decode time on CPU, and CER of Laghu's clips (decision rules 2 and 3).

    python m0/probe_stt.py                  # decode time + CER, male clips
    python m0/probe_stt.py --voice female   # same for the female clips
    python m0/probe_stt.py --stt hi120m     # Hindi-only 120M IndicConformer (pip install onnx-asr)
    python m0/probe_stt.py --groq-whisper   # also time Groq whisper-large-v3-turbo (uses quota)

Reads m0/out/laghu_<voice>/manifest.jsonl from probe_laghu.py. Loads ai4bharat/indic-conformer-600m-multilingual the
same way Laghu's evaluation notebook does (including its symlink fix), on CPU, CTC decoding. Needs:
    pip install torch transformers huggingface_hub soundfile scipy
and HF_TOKEN set if the model asks you to accept its terms.

Scoring is copied from Laghu's evaluation (compare_small_tts.ipynb / recompute.py): "standard" = PROTOCOL.md
Amendment 13 (NFC, punctuation to spaces, nukta kept, spaces counted); "paper" = nukta and spaces removed.
CER is pooled: total character errors / total reference characters.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import statistics
import sys
import time
import unicodedata
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = "ai4bharat/indic-conformer-600m-multilingual"


# ---- scoring: copied from Laghu's evaluation code, unchanged ----------------------------------------
def paper_norm(t):
    t = unicodedata.normalize("NFC", t).replace("़", "")
    t = "".join(" " if (unicodedata.category(c).startswith("P") or c in "।॥") else c for c in t)
    return re.sub(r"\s+", " ", t).strip()


def std_norm(t):  # Amendment 13: NFC, punctuation -> space, nukta kept
    t = unicodedata.normalize("NFC", t)
    t = "".join(" " if (unicodedata.category(c).startswith("P") or c in "।॥") else c for c in t)
    return re.sub(r"\s+", " ", t).strip()


def clean_ctc(h):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", "", h)).strip()


def lev(a, b):
    d = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(b) + 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (a[i - 1] != b[j - 1]))
    return d[len(b)]
# -----------------------------------------------------------------------------------------------------


def pct(xs, p):
    xs = sorted(xs)
    return xs[max(0, math.ceil(p / 100 * len(xs)) - 1)] if xs else None


def read16k(path):
    import soundfile as sf
    from scipy.signal import resample_poly

    x, sr = sf.read(path, dtype="float32")
    if x.ndim > 1:
        x = x.mean(1)
    if sr != 16000:
        g = math.gcd(sr, 16000)
        x = resample_poly(x, 16000 // g, sr // g).astype(np.float32)
    return x


def load_conformer():
    import torch
    from huggingface_hub import snapshot_download
    from transformers import AutoModel

    snap = snapshot_download(REPO, token=os.environ.get("HF_TOKEN"))
    for root, _, files in os.walk(snap):   # newer onnxruntime refuses external data reached through symlinks
        for fn in files:
            p = os.path.join(root, fn)
            if os.path.islink(p):
                real = os.path.realpath(p)
                os.unlink(p)
                shutil.move(real, p)
    model = AutoModel.from_pretrained(REPO, trust_remote_code=True, token=os.environ.get("HF_TOKEN"))
    try:
        model = model.to("cpu").eval()
    except Exception:  # noqa: BLE001 - ONNX-backed wrappers pick their own device
        pass
    torch.set_num_threads(int(os.environ.get("STT_THREADS", "4")))

    def transcribe(x):
        with torch.no_grad():
            h = model(torch.from_numpy(x)[None], "hi", "ctc")
        return h if isinstance(h, str) else (h[0] if isinstance(h, (list, tuple)) else str(h))
    return transcribe


def groq_whisper(path, key, model="whisper-large-v3-turbo", retries=4):
    """One transcription -> (text, ms). Retries HTTP 429 (free tier: 20 requests per minute), waiting as long as Groq asks."""
    import httpx

    for attempt in range(retries + 1):
        t0 = time.perf_counter()
        with open(path, "rb") as f:
            r = httpx.post("https://api.groq.com/openai/v1/audio/transcriptions",
                           headers={"Authorization": f"Bearer {key}"}, timeout=30,
                           data={"model": model, "language": "hi", "response_format": "json"},
                           files={"file": (Path(path).name, f, "audio/wav")})
        if r.status_code == 429 and attempt < retries:
            wait = float(r.headers.get("retry-after", "5"))
            print(f"    rate-limited, waiting {wait + 0.5:.1f} s")
            time.sleep(wait + 0.5)
            continue
        r.raise_for_status()
        return r.json()["text"], 1000 * (time.perf_counter() - t0)   # time of the successful call only


def save(rows, manifest, name="stt_results.jsonl"):
    out = Path(manifest).with_name(name)
    with out.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return out


HI120M = "OpenVoiceOS/ai4bharat-indicconformer-hi-onnx"   # ONNX export of ai4bharat's Hindi-only 120M model


def load_hi120m(quantization=None, path=None):
    """Hindi-only IndicConformer (120M, CTC/RNNT hybrid) through the onnx-asr library: pip install onnx-asr.
    No NeMo, no torch. quantization="int8" uses the int8 weights the repo also ships."""
    import onnx_asr
    import onnxruntime as ort

    so = ort.SessionOptions()
    so.intra_op_num_threads = int(os.environ.get("STT_THREADS", "4"))
    try:
        model = onnx_asr.load_model(HI120M, path, quantization=quantization, sess_options=so)
    except Exception as e:  # noqa: BLE001
        if path is not None and not Path(path, f"model.{quantization}.onnx").exists():
            sys.exit(f"{path} has no model.{quantization}.onnx: run python m0/quantize_hi120m.py first")
        if quantization:
            sys.exit(f"could not load the {quantization} model ({e}).\n"
                     "Some int8 exports need a ConvInteger kernel ONNX Runtime's CPU build doesn't have; use --stt hi120m.")
        raise

    def transcribe(x):
        out = model.recognize(x, sample_rate=16000)
        return out if isinstance(out, str) else getattr(out, "text", str(out))
    return transcribe


STT_MODELS = {   # name -> (description, loader, results file)
    "multi600m": (f"{REPO} (600M, CTC)", lambda: load_conformer(), "stt_results.jsonl"),
    "hi120m": (f"{HI120M} (120M, fp32)", lambda: load_hi120m(), "stt_results_hi120m.jsonl"),
    "hi120m-int8": (f"{HI120M} (120M, int8)", lambda: load_hi120m("int8"), "stt_results_hi120m-int8.jsonl"),
    "hi120m-uint8": ("hi120m, our int8 copy (MatMul weights uint8, convolutions fp32)",
                     lambda: load_hi120m("uint8", HERE / "out" / "hi120m"), "stt_results_hi120m-uint8.jsonl"),
}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--voice", default="male", help="reads m0/out/laghu_<voice>/manifest.jsonl")
    ap.add_argument("--manifest", default=None, help="overrides --voice")
    ap.add_argument("--stt", default="multi600m", choices=list(STT_MODELS),
                    help="multi600m: the 600M multilingual model (rule 3's first candidate); hi120m / hi120m-int8: "
                         "the Hindi-only 120M model, needs pip install onnx-asr")
    ap.add_argument("--groq-whisper", action="store_true", help="also time Groq whisper-large-v3-turbo (uses quota)")
    ap.add_argument("--pause", type=float, default=3.5, help="seconds between Groq calls (free tier: 20 per minute)")
    a = ap.parse_args()
    a.manifest = a.manifest or str(HERE / "out" / f"laghu_{a.voice}" / "manifest.jsonl")
    rows = [json.loads(l) for l in open(a.manifest, encoding="utf-8")]
    desc, loader, results_name = STT_MODELS[a.stt]
    if os.environ.get("STT_THREADS", "4") != "4":      # keep runs with other thread counts apart
        results_name = results_name.replace(".jsonl", f"_t{os.environ['STT_THREADS']}.jsonl")
    print(f"{len(rows)} clips from {a.manifest}; loading {desc} on CPU, "
          f"{os.environ.get('STT_THREADS', '4')} threads ...")
    transcribe = loader()
    transcribe(read16k(HERE / rows[0]["path"]))           # warm-up, not recorded
    for r in rows:
        x = read16k(HERE / r["path"])
        t0 = time.perf_counter()
        r["hyp"] = clean_ctc(transcribe(x))
        r["decode_ms"] = round(1000 * (time.perf_counter() - t0), 1)
        for mode, norm in (("standard", std_norm), ("paper", paper_norm)):
            ref, hyp = norm(r["model_text"]), norm(r["hyp"])
            if mode == "paper":
                ref, hyp = ref.replace(" ", ""), hyp.replace(" ", "")
            r[f"err_{mode}"], r[f"len_{mode}"] = lev(ref, hyp), len(ref)
        print(f"{r['id']} {r['variant']:8} r{r['rendition']}: {r['decode_ms']:7.1f} ms for {r['audio_s']:.1f} s | "
              f"{r['hyp']}")

    sent = [r for r in rows if r["variant"] == "sentence"]
    d = [r["decode_ms"] for r in sent]
    print(f"\n{desc} decode on CPU, whole sentences ({len(sent)} clips, "
          f"{statistics.median(r['audio_s'] for r in sent):.1f} s median length): "
          f"p50 {pct(d, 50):.0f} ms, p95 {pct(d, 95):.0f} ms -> rule 3: "
          f"{'keep' if pct(d, 95) <= 400 else 'too slow, try a smaller model'}")
    cer = {}
    paired = {r["id"] for r in rows if r["variant"] == "clause"}     # rule 2: same sentences on both sides
    print(f"rule 2 compares the {len(paired)} sentences that have a clause, both ways:")
    for variant in ("sentence", "clause"):
        v = [r for r in rows if r["variant"] == variant and r["id"] in paired]
        cer[variant] = {m: 100 * sum(r[f"err_{m}"] for r in v) / sum(r[f"len_{m}"] for r in v)
                        for m in ("standard", "paper")}
        print(f"CER {variant:8}: standard {cer[variant]['standard']:.1f}%, paper-style {cer[variant]['paper']:.1f}% "
              f"({len(v)} clips)")
    gap = cer["clause"]["standard"] - cer["sentence"]["standard"]
    print(f"clause minus sentence (standard): {gap:+.1f} points -> rule 2 CER part: "
          f"{'met' if gap <= 1.0 else 'not met'}{' (between 0.5 and 1.5: rerun on FLEURS)' if 0.5 <= gap <= 1.5 else ''}")

    out = save(rows, a.manifest, results_name)   # IndicConformer results are kept even if the Groq part fails
    print(f"wrote {out}")

    if a.groq_whisper:
        key = os.environ.get("GROQ_API_KEY") or sys.exit("set GROQ_API_KEY")
        times = []
        for r in sent:
            r["groq_hyp"], ms = groq_whisper(HERE / r["path"], key)
            times.append(ms)
            time.sleep(a.pause)
        print(f"Groq whisper-large-v3-turbo, total time incl. network: p50 {pct(times, 50):.0f} ms, "
              f"p95 {pct(times, 95):.0f} ms")
        save(rows, a.manifest, results_name)
        print(f"added Groq transcripts to {out}")


if __name__ == "__main__":
    main()
