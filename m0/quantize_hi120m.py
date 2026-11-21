"""Milestone 0: make our own int8 copy of the Hindi-only 120M IndicConformer (Amendment 6).

    python m0/quantize_hi120m.py
    python m0/probe_stt.py --stt hi120m-uint8

The int8 file that OpenVoiceOS ships doesn't load on ONNX Runtime's CPU build ("Could not find an
implementation for ConvInteger"). This script downloads the fp32 export into m0/out/hi120m/ and quantizes
only the MatMul weights (attention and feed-forward, most of the compute) to unsigned int8, leaving every
convolution in fp32. The result is m0/out/hi120m/model.uint8.onnx, next to the fp32 files onnx-asr needs.
Needs: pip install onnx-asr onnx
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = "OpenVoiceOS/ai4bharat-indicconformer-hi-onnx"
OUT = HERE / "out" / "hi120m"


def main():
    from huggingface_hub import snapshot_download
    from onnxruntime.quantization import QuantType, quantize_dynamic

    OUT.mkdir(parents=True, exist_ok=True)
    print(f"downloading the fp32 model from {REPO} into {OUT} ...")
    snapshot_download(REPO, local_dir=OUT, allow_patterns=["config.json", "vocab.txt", "model.onnx", "model.onnx?data"])
    src, dst = OUT / "model.onnx", OUT / "model.uint8.onnx"
    if not src.exists():
        sys.exit(f"{src} not found after download; the repo layout may have changed. Send me the folder listing.")
    print("quantizing MatMul weights to uint8 (convolutions stay fp32) ...")
    quantize_dynamic(str(src), str(dst), weight_type=QuantType.QUInt8, op_types_to_quantize=["MatMul"])
    fp32 = sum(p.stat().st_size for p in OUT.glob("model.onnx*"))
    print(f"wrote {dst}: {dst.stat().st_size / 1e6:.0f} MB (fp32: {fp32 / 1e6:.0f} MB)")
    print("next: python m0/probe_stt.py --stt hi120m-uint8")


if __name__ == "__main__":
    main()
