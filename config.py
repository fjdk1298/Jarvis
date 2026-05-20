"""Configuration layer for Jarvis voice pipeline.

This module loads environment variables, validates required secrets,
and exposes constants used across the runtime.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict

from dotenv import load_dotenv

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(_BASE_DIR, ".env"))

for _parent in Path(__file__).resolve().parents:
    if (_parent / "shared_cloud_limits.py").exists():
        if str(_parent) not in sys.path:
            sys.path.insert(0, str(_parent))
        break

from shared_cloud_limits import CONTEXT_MESSAGES, MAX_ITERATIONS, MAX_RETRIES, TEMPERATURE

_REQUIRED_KEY_HELP: Dict[str, str] = {
    "ANTHROPIC_API_KEY": "https://console.anthropic.com",
    "OPENROUTER_API_KEY": "https://openrouter.ai/keys",
    "ELEVENLABS_API_KEY": "https://elevenlabs.io/app/settings/api-keys",
    "ELEVENLABS_VOICE_ID": "Run the voice listing command from .env.example to find Charlie's voice ID.",
    "LLM_PROVIDER_KEY": "Set ANTHROPIC_API_KEY, OPENROUTER_API_KEY, or enable LOCAL_LLM_FALLBACK with Ollama.",
}

ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api").strip()
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-4.5").strip()
LOCAL_LLM_FALLBACK = os.getenv("LOCAL_LLM_FALLBACK", "true").strip().lower() in {"1", "true", "yes", "on"}
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip().rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b-instruct").strip()
PREFER_CLOUD_LLM = os.getenv("PREFER_CLOUD_LLM", "false").strip().lower() in {"1", "true", "yes", "on"}
LOCAL_ONLY_MODE = os.getenv("LOCAL_ONLY_MODE", "true").strip().lower() in {"1", "true", "yes", "on"}
ELEVENLABS_KEY = os.getenv("ELEVENLABS_API_KEY", "").strip()
ELEVENLABS_VOICE = os.getenv("ELEVENLABS_VOICE_ID", "").strip()
PICO_KEY = os.getenv("PICOVOICE_ACCESS_KEY", "").strip()
BRAIN_MODEL = OPENROUTER_MODEL if OPENROUTER_KEY else "claude-sonnet-4-5"
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "220"))
LLM_MAX_ITERATIONS = MAX_ITERATIONS
LLM_MAX_RETRIES = MAX_RETRIES

CONVERSATION_HISTORY_LIMIT = CONTEXT_MESSAGES
SILENCE_TIMEOUT = 5
PHRASE_LIMIT = 10
WAKE_SIGNAL_PHRASE_LIMIT = 4
CLAP_DETECTION_ENABLED = os.getenv("CLAP_DETECTION_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
CLAP_MIN_PEAK = int(os.getenv("CLAP_MIN_PEAK", "7000"))
CLAP_ENERGY_RATIO = float(os.getenv("CLAP_ENERGY_RATIO", "4.0"))
CLAP_MIN_GAP_SECONDS = float(os.getenv("CLAP_MIN_GAP_SECONDS", "0.12"))
CLAP_MAX_GAP_SECONDS = float(os.getenv("CLAP_MAX_GAP_SECONDS", "0.85"))
CLAP_MAX_BURST_SECONDS = float(os.getenv("CLAP_MAX_BURST_SECONDS", "0.12"))
TTS_STABILITY = 0.5
TTS_SIMILARITY = 0.8
TTS_STYLE = 0.3
TTS_USE_SPEAKER_BOOST = True
FORCE_OFFLINE_TTS = os.getenv("FORCE_OFFLINE_TTS", "true").strip().lower() in {"1", "true", "yes", "on"}
OFFLINE_TTS_ENGINE = os.getenv("OFFLINE_TTS_ENGINE", "auto").strip().lower()
EDGE_TTS_VOICE = os.getenv("EDGE_TTS_VOICE", "en-GB-RyanNeural").strip()
ENABLE_HUD = os.getenv("ENABLE_HUD", "true").strip().lower() in {"1", "true", "yes", "on"}
REQUIRE_WAKE_PREFIX = os.getenv("REQUIRE_WAKE_PREFIX", "true").strip().lower() in {"1", "true", "yes", "on"}
STARTUP_GREETING_ON_BOOT = os.getenv("STARTUP_GREETING_ON_BOOT", "false").strip().lower() in {"1", "true", "yes", "on"}
LLM_TEMPERATURE = TEMPERATURE


def validate_config() -> None:
    """Validate required environment variables and exit gracefully if missing."""
    missing = []

    if not LOCAL_ONLY_MODE and not ANTHROPIC_KEY and not OPENROUTER_KEY and not LOCAL_LLM_FALLBACK:
        missing.append("LLM_PROVIDER_KEY")
    if not FORCE_OFFLINE_TTS:
        if not ELEVENLABS_KEY:
            missing.append("ELEVENLABS_API_KEY")
        if not ELEVENLABS_VOICE:
            missing.append("ELEVENLABS_VOICE_ID")
    if not missing:
        return

    print("[ERROR] Missing required configuration in .env:")
    for key in missing:
        print(f"[ERROR] - {key}: {_REQUIRED_KEY_HELP[key]}")
    print("[ERROR] Please update jarvis/.env and restart Jarvis.")
    raise SystemExit(1)


def ensure_runtime_ready() -> None:
    """Wrapper to validate configuration at startup."""
    try:
        validate_config()
    except SystemExit:
        raise
    except Exception as exc:
        print(f"[ERROR] Unexpected configuration error: {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    """Allow manual config checks from the command line."""
    ensure_runtime_ready()
    print("[INFO] Configuration looks good.")
    sys.exit(0)
