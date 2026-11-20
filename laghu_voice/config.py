"""Settings, read from environment variables (a .env file is loaded if python-dotenv is installed).

Every setting has a default that works for local development with the stub TTS.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # optional
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


# Where scripts/get_laghu.py puts Laghu's code and weights
DEFAULT_LAGHU_DIR = Path(__file__).resolve().parents[1] / "vendor" / "laghu"


@dataclass
class Settings:
    # Server
    host: str = field(default_factory=lambda: _env("LV_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(_env("LV_PORT", "8765")))

    # TTS: "laghu" (real model) or "stub" (a tone, for tests and for running without the model)
    tts_backend: str = field(default_factory=lambda: _env("LV_TTS", "stub"))
    laghu_dir: Path = field(default_factory=lambda: Path(_env("LAGHU_DIR", str(DEFAULT_LAGHU_DIR))))
    laghu_voice: str = field(default_factory=lambda: _env("LAGHU_VOICE", "female"))
    laghu_cfg: float = field(default_factory=lambda: float(_env("LAGHU_CFG", "2.0")))

    # Audio pacing: how far ahead of the listener the server may send audio (see design doc, Runtime model)
    pacer_lead_ms: int = field(default_factory=lambda: int(_env("LV_PACER_LEAD_MS", "200")))

    # Segmenter: cut the first segment of a reply at a clause boundary (off until Milestone 0 says it's safe)
    first_clause: bool = field(default_factory=lambda: _env("LV_FIRST_CLAUSE", "0") == "1")

    # LLM (any OpenAI-compatible endpoint; Groq by default)
    llm_base_url: str = field(default_factory=lambda: _env("LLM_BASE_URL", "https://api.groq.com/openai/v1"))
    llm_api_key: str = field(default_factory=lambda: _env("GROQ_API_KEY", _env("LLM_API_KEY", "")))
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", "openai/gpt-oss-20b"))
    llm_extra: dict = field(default_factory=lambda: json.loads(_env("LLM_EXTRA_JSON", "{}")))

    # Observability
    trace_dir: Path = field(default_factory=lambda: Path(_env("LV_TRACE_DIR", "traces")))
