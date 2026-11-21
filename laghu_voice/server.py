"""Run the voice server.

    python -m laghu_voice.server --tts stub                      # no model needed: speaks a tone
    python -m laghu_voice.server --tts laghu                     # Laghu from vendor/laghu (scripts/get_laghu.py)
    python -m laghu_voice.server --tts laghu --listen full       # + listening: Silero, Smart Turn, IndicConformer
    python -m laghu_voice.server --tts stub --listen stub        # listening without any model (for testing)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from websockets.asyncio.server import serve

from .config import DEFAULT_LAGHU_DIR, Settings
from .transport.ws_server import make_handler

VENDOR = DEFAULT_LAGHU_DIR.parent


def build_tts(settings: Settings):
    if settings.tts_backend == "laghu":
        from .services.tts_laghu import LaghuTTS

        return LaghuTTS(settings.laghu_dir, voice=settings.laghu_voice, cfg=settings.laghu_cfg)
    if settings.tts_backend == "stub":
        from .services.tts_stub import StubTTS

        return StubTTS()
    raise SystemExit(f"unknown TTS backend {settings.tts_backend!r} (use laghu or stub)")


def build_listen(settings: Settings):
    from .orchestrator.listener import ListenModels

    if settings.listen == "off":
        return None
    if settings.listen == "stub":
        from .audio.vad import EnergyVAD
        from .services.stt_indic import StubSTT

        return ListenModels(EnergyVAD(), StubSTT(), None)
    if settings.listen != "full":
        raise SystemExit(f"unknown listen mode {settings.listen!r} (use full, stub or off)")
    from .audio.turn import SmartTurn
    from .audio.vad import SileroVAD
    from .services.stt_indic import IndicConformerSTT

    vad = SileroVAD(VENDOR / "silero" / "silero_vad.onnx")
    turn = SmartTurn(VENDOR / "smart_turn" / "smart-turn-v3.2-cpu.onnx") if settings.turn_model else None
    logging.info("loading the STT model (%d threads) ...", settings.stt_threads)
    stt = IndicConformerSTT(VENDOR / "stt_hi120m", threads=settings.stt_threads, pad_s=settings.stt_pad_s)
    return ListenModels(vad, stt, turn)


async def main_async(settings: Settings) -> None:
    tts = build_tts(settings)
    listen = build_listen(settings)
    async with serve(make_handler(tts, settings, listen=listen), settings.host, settings.port,
                     max_size=2**20) as server:
        logging.info("listening on ws://%s:%d (TTS: %s, listening: %s%s, dialog: %s, traces in %s)",
                     settings.host, settings.port, settings.tts_backend, settings.listen,
                     "" if listen is None or listen.turn is not None else " without turn model",
                     settings.dialog, settings.trace_dir.resolve())
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
    ap.add_argument("--listen", default=s.listen, choices=["full", "stub", "off"],
                    help="full: Silero VAD + Smart Turn + IndicConformer (scripts/get_listen_models.py)")
    ap.add_argument("--no-turn-model", action="store_true", help="end turns on silence alone (700 ms)")
    ap.add_argument("--dialog", default=s.dialog, choices=["echo", "none"],
                    help="echo: say back the transcript; none: only listen")
    a = ap.parse_args()
    s.listen, s.dialog = a.listen, a.dialog
    s.turn_model = s.turn_model and not a.no_turn_model
    s.tts_backend, s.laghu_dir, s.laghu_voice = a.tts, Path(a.laghu_dir), a.voice
    s.host, s.port, s.first_clause = a.host, a.port, a.first_clause or s.first_clause
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(main_async(s))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
