"""Run the voice server.

    python -m laghu_voice.server --tts stub                      # no model needed: speaks a tone
    python -m laghu_voice.server --tts laghu                     # Laghu from vendor/laghu (scripts/get_laghu.py)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from websockets.asyncio.server import serve

from .config import Settings
from .transport.ws_server import make_handler


def build_tts(settings: Settings):
    if settings.tts_backend == "laghu":
        from .services.tts_laghu import LaghuTTS

        return LaghuTTS(settings.laghu_dir, voice=settings.laghu_voice, cfg=settings.laghu_cfg)
    if settings.tts_backend == "stub":
        from .services.tts_stub import StubTTS

        return StubTTS()
    raise SystemExit(f"unknown TTS backend {settings.tts_backend!r} (use laghu or stub)")


async def main_async(settings: Settings) -> None:
    tts = build_tts(settings)
    async with serve(make_handler(tts, settings), settings.host, settings.port, max_size=2**20) as server:
        logging.info("listening on ws://%s:%d (TTS: %s, traces in %s)", settings.host, settings.port,
                     settings.tts_backend, settings.trace_dir.resolve())
        await server.serve_forever()


def main() -> None:
    s = Settings()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tts", default=s.tts_backend, choices=["laghu", "stub"])
    ap.add_argument("--laghu-dir", default=str(s.laghu_dir), help="default: vendor/laghu")
    ap.add_argument("--voice", default=s.laghu_voice)
    ap.add_argument("--host", default=s.host)
    ap.add_argument("--port", type=int, default=s.port)
    ap.add_argument("--first-clause", action="store_true", help="cut a reply's first segment at a comma")
    a = ap.parse_args()
    s.tts_backend, s.laghu_dir, s.laghu_voice = a.tts, Path(a.laghu_dir), a.voice
    s.host, s.port, s.first_clause = a.host, a.port, a.first_clause or s.first_clause
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(main_async(s))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
