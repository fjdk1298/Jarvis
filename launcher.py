"""Background launcher for clap-to-open Jarvis on Windows.

This module starts at Windows login, listens for a local multi-clap trigger,
and launches the full Jarvis app without requiring a terminal.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from config import CLAP_DETECTION_ENABLED, CLAP_TRIGGER_COUNT, PHRASE_LIMIT, SILENCE_TIMEOUT
from listen import MicrophoneError, listen_for_clap_trigger
from runtime import JARVIS_LAUNCHER_MUTEX_NAME, SingleInstanceMutex, is_jarvis_running

_BASE_DIR = Path(__file__).resolve().parent
_LAUNCHER_LOG_PATH = _BASE_DIR / "data" / "launcher.log"
_LAUNCH_COOLDOWN_SECONDS = 8.0


def _log(line: str) -> None:
    """Append launcher activity to a small local log file for troubleshooting."""
    try:
        _LAUNCHER_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with _LAUNCHER_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] {line}\n")
    except Exception:
        return


def _resolve_pythonw() -> str:
    """Return the best interpreter path for hidden background launches."""
    scripts_dir = _BASE_DIR / ".venv" / "Scripts"
    pythonw_path = scripts_dir / "pythonw.exe"
    if pythonw_path.exists():
        return str(pythonw_path)

    python_path = scripts_dir / "python.exe"
    if python_path.exists():
        return str(python_path)

    return "pythonw.exe"


def _launch_jarvis() -> bool:
    """Start the main Jarvis app hidden from the terminal."""
    python_exec = _resolve_pythonw()
    main_path = _BASE_DIR / "main.py"

    try:
        subprocess.Popen(
            [python_exec, str(main_path)],
            cwd=str(_BASE_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        _log(f"Launched Jarvis after {CLAP_TRIGGER_COUNT} clap trigger.")
        return True
    except Exception as exc:
        _log(f"Failed to launch Jarvis: {exc}")
        return False


def main() -> None:
    """Run the hidden clap listener loop for desktop startup use."""
    if not CLAP_DETECTION_ENABLED:
        _log("Clap launcher is disabled in config. Exiting.")
        return

    launcher_lock = SingleInstanceMutex(JARVIS_LAUNCHER_MUTEX_NAME)
    if not launcher_lock.acquire():
        return

    cooldown_until = 0.0
    _log("Background clap launcher started.")

    try:
        while True:
            if is_jarvis_running():
                time.sleep(2.0)
                continue

            now = time.monotonic()
            if now < cooldown_until:
                time.sleep(0.5)
                continue

            try:
                if listen_for_clap_trigger(SILENCE_TIMEOUT, PHRASE_LIMIT, CLAP_TRIGGER_COUNT):
                    if not is_jarvis_running() and _launch_jarvis():
                        cooldown_until = time.monotonic() + _LAUNCH_COOLDOWN_SECONDS
                    else:
                        cooldown_until = time.monotonic() + 2.0
            except MicrophoneError as exc:
                _log(f"Microphone unavailable in launcher: {exc}")
                time.sleep(5.0)
    finally:
        _log("Background clap launcher stopped.")
        launcher_lock.close()


if __name__ == "__main__":
    """Run the clap launcher when executed directly."""
    main()
