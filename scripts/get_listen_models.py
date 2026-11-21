"""Fetch the three listening models into vendor/ (Milestone 2).

    python scripts/get_listen_models.py

- vendor/silero/silero_vad.onnx                Silero VAD v5.1.2 (MIT), 2.3 MB, from the project's GitHub tag
- vendor/smart_turn/smart-turn-v3.2-cpu.onnx   Smart Turn v3.2 int8 (BSD-2), 8.7 MB, from pipecat-ai/smart-turn-v3
- vendor/stt_hi120m/                           Hindi IndicConformer 120M, ONNX fp32 (MIT), about 480 MB, from
                                               OpenVoiceOS/ai4bharat-indicconformer-hi-onnx. Copied from
                                               m0/out/hi120m if Milestone 0 already downloaded it.
Files already in place are skipped.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor"

SILERO_URL = "https://raw.githubusercontent.com/snakers4/silero-vad/v5.1.2/src/silero_vad/data/silero_vad.onnx"
SILERO_SHA256 = "2623a2953f6ff3d2c1e61740c6cdb7168133479b267dfef114a4a3cc5bdd788f"
SMART_TURN = ("pipecat-ai/smart-turn-v3", "smart-turn-v3.2-cpu.onnx")
STT_REPO = "OpenVoiceOS/ai4bharat-indicconformer-hi-onnx"
STT_FILES = ["config.json", "vocab.txt", "model.onnx", "model.onnx?data"]


def get_silero() -> Path:
    import httpx

    dest = VENDOR / "silero" / "silero_vad.onnx"
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"downloading Silero VAD from {SILERO_URL}")
        r = httpx.get(SILERO_URL, follow_redirects=True, timeout=60)
        r.raise_for_status()
        dest.write_bytes(r.content)
    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
    if digest != SILERO_SHA256:
        dest.unlink()
        raise SystemExit(f"Silero VAD checksum mismatch ({digest}); deleted it, run again")
    return dest


def get_smart_turn() -> Path:
    from huggingface_hub import hf_hub_download

    dest = VENDOR / "smart_turn" / SMART_TURN[1]
    if not dest.exists():
        print(f"downloading {SMART_TURN[1]} from {SMART_TURN[0]}")
        hf_hub_download(SMART_TURN[0], SMART_TURN[1], local_dir=dest.parent)
    return dest


def get_stt() -> Path:
    from huggingface_hub import snapshot_download

    dest = VENDOR / "stt_hi120m"
    if (dest / "model.onnx").exists():
        return dest
    dest.mkdir(parents=True, exist_ok=True)
    m0 = ROOT / "m0" / "out" / "hi120m"
    if (m0 / "model.onnx").exists():
        print(f"copying the STT model from {m0}")
        for p in m0.iterdir():
            if p.is_file() and "uint8" not in p.name:
                shutil.copy2(p, dest / p.name)
    else:
        print(f"downloading the STT model from {STT_REPO} (about 480 MB)")
        snapshot_download(STT_REPO, local_dir=dest, allow_patterns=STT_FILES)
    return dest


def main():
    for name, fn in (("Silero VAD", get_silero), ("Smart Turn", get_smart_turn), ("STT", get_stt)):
        p = fn()
        size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.is_dir() else p.stat().st_size
        print(f"{name:10}: {p.relative_to(ROOT)} ({size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
