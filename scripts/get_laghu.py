"""Download what the server needs from Laghu's Hugging Face repo into vendor/laghu/ (about 31 MB).

    python scripts/get_laghu.py

Fetches the speaking model and the five code files its runtime imports. It skips the voice-cloning
encoder (encoder.onnx, 39 MB), the samples and the evaluation folder. vendor/laghu/ is in .gitignore:
the files come from Hugging Face, so the repo never carries a second copy of them.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ID = "Abhay2310/laghu-tts-7m-hindi"
DEST = Path(__file__).resolve().parents[1] / "vendor" / "laghu"

FILES = [
    # code: the streaming runtime and the text frontend it imports
    "runtime_onnx.py", "text_chunking.py", "devanagari_text.py", "hindi_numbers.py", "spelling_map.py",
    # licences that must travel with the code and weights
    "LICENSE", "LICENSE-CODE", "LICENSE_pocket_tts",
    # the speaking model
    "model/meta.json", "model/tables.npz", "model/tokenizer.model",
    "model/lm_step.onnx", "model/head.onnx", "model/decoder.onnx",
    "model/voices/*.npy",
]


def missing(dest: Path = DEST) -> list[str]:
    out = [f for f in FILES if "*" not in f and not (dest / f).exists()]
    if not list((dest / "model" / "voices").glob("*.npy")):
        out.append("model/voices/*.npy")
    return out


def main() -> None:
    from huggingface_hub import snapshot_download

    snapshot_download(REPO_ID, allow_patterns=FILES, local_dir=DEST)
    gone = missing()
    if gone:
        sys.exit(f"download incomplete, still missing: {', '.join(gone)}")
    size = sum(p.stat().st_size for p in DEST.rglob("*") if p.is_file() and ".cache" not in p.parts)
    voices = sorted(p.stem for p in (DEST / "model" / "voices").glob("*.npy"))
    print(f"Laghu ready in {DEST} ({size / 1e6:.1f} MB), voices: {', '.join(voices)}")


if __name__ == "__main__":
    main()
