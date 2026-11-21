"""Run the voice server.

    python -m laghu_voice.server --tts stub                      # no model needed: speaks a tone
    python -m laghu_voice.server --tts laghu                     # Laghu from vendor/laghu (scripts/get_laghu.py)
    python -m laghu_voice.server --tts laghu --listen full       # + listening: Silero, Smart Turn, IndicConformer
    python -m laghu_voice.server --tts stub --listen stub        # listening without any model (for testing)
    python -m laghu_voice.server --tts laghu --dialog agent      # the loan agent (Milestone 4): needs GROQ_API_KEY
                                                                 # and the onboarding backend on ONBOARDING_URL
    python -m laghu_voice.server --tts laghu --dialog agent --agent-spec agents/emi_reminder.yaml
                                                                 # another use case: EMI reminder, mock tools
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from websockets.asyncio.server import serve

from .config import DEFAULT_LAGHU_DIR, Settings
from .transport.ws_server import DialogDeps, make_handler

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


async def build_dialog(settings: Settings, tts):
    """The agent's shared parts. Fails at startup, with the reason, if the spec, Groq or the backend is missing.
    Returns (deps, tts): the TTS wrapped so the agent's fixed lines play from memory."""
    if settings.dialog != "agent":
        return None, tts
    import httpx

    from .dialog.backend import BackendClient
    from .dialog.spec import load_spec
    from .services.llm_openai import OpenAICompatLLM
    from .services.tts_cache import CachedTTS

    spec = load_spec(settings.agent_spec)
    if not settings.llm_api_key:
        raise SystemExit("--dialog agent needs GROQ_API_KEY (in the environment or .env)")
    llm = OpenAICompatLLM(settings.llm_base_url, settings.llm_api_key, settings.llm_model, settings.llm_extra)
    backend = None
    if spec.http:
        backend = BackendClient(settings.backend_url, settings.backend_api_key)
        try:
            (await backend.client.get(spec.backend.get("health", "/healthz"))).raise_for_status()
        except (httpx.HTTPError, OSError) as e:
            raise SystemExit(f"{spec.path.name}'s backend isn't reachable at {settings.backend_url} ({e!r}). "
                             "Start it first (README: Milestone 4), or set ONBOARDING_URL.")
    cached = CachedTTS(tts)
    if settings.tts_prewarm:
        lines = spec.fixed_lines()
        logging.info("pre-rendering %d fixed lines of %s ...", len(lines), settings.agent_spec.name)
        filler = spec.lines["filler"].text or spec.lines["filler"].example
        took = await cached.prewarm(lines, first_clause=settings.first_clause, trim=[filler])
        logging.info("pre-rendered %d segments in %.1f s", len(cached.cache), took)
    logging.info("agent: %s, backend %s, LLM %s", settings.agent_spec.name,
                 settings.backend_url if spec.http else "mock (answers in the spec)", settings.llm_model)
    return DialogDeps(spec, backend, llm), cached


async def main_async(settings: Settings) -> None:
    tts = build_tts(settings)
    listen = build_listen(settings)
    dialog, tts = await build_dialog(settings, tts)
    async with serve(make_handler(tts, settings, listen=listen, dialog=dialog), settings.host, settings.port,
                     max_size=2**20) as server:
        logging.info("listening on ws://%s:%d (TTS: %s, listening: %s%s, %s, dialog: %s, traces in %s)",
                     settings.host, settings.port, settings.tts_backend, settings.listen,
                     "" if listen is None or listen.turn is not None else " without turn model",
                     "half duplex" if settings.half_duplex else f"barge-in after {settings.barge_in_ms:.0f} ms",
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
    ap.add_argument("--dialog", default=s.dialog, choices=["agent", "echo", "none"],
                    help="agent: the loan agent (agents/loan_onboarding.yaml); echo: say back the transcript; "
                         "none: only listen")
    ap.add_argument("--agent-spec", default=str(s.agent_spec), help="default: agents/loan_onboarding.yaml")
    ap.add_argument("--backend-url", default=s.backend_url, help="the onboarding backend (default %(default)s)")
    ap.add_argument("--no-prewarm", action="store_true", help="don't pre-render the agent's fixed lines")
    ap.add_argument("--half-duplex", action="store_true",
                    help="ignore the mic while the agent speaks (no barge-in; for a speaker instead of headphones)")
    ap.add_argument("--barge-in-ms", type=float, default=s.barge_in_ms,
                    help="speech over the agent for this long interrupts it (default 250)")
    a = ap.parse_args()
    s.listen, s.dialog = a.listen, a.dialog
    s.agent_spec, s.backend_url, s.tts_prewarm = Path(a.agent_spec), a.backend_url, s.tts_prewarm and not a.no_prewarm
    s.half_duplex, s.barge_in_ms = a.half_duplex or s.half_duplex, a.barge_in_ms
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
