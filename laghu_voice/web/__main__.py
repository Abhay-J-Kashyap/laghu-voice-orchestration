"""python -m laghu_voice.web [--port 8000] [--host 127.0.0.1]"""
from __future__ import annotations

import argparse

import uvicorn

from .app import create_app


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m laghu_voice.web")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    print(f"laghu-voice setup UI: http://{a.host}:{a.port}  (the API is under /api)")
    uvicorn.run(create_app(), host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
