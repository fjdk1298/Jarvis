"""Main orchestration loop for Jarvis.

This module initializes all subsystems and runs the always-listening
voice pipeline from wake detection through speech playback.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable, Iterable

import pyaudio
import pygame
from anthropic import Anthropic
from elevenlabs import ElevenLabs

from actions import ActionResult, get_live_web_context, get_runtime_time_context, handle_local_action, should_fetch_web_context
from brain import think
from config import (
    ANTHROPIC_KEY,
    CLAP_DETECTION_ENABLED,
    ENABLE_HUD,
    ELEVENLABS_KEY,
    ELEVENLABS_VOICE,
    FORCE_OFFLINE_TTS,
    LOCAL_LLM_FALLBACK,
    LOCAL_ONLY_MODE,
    OPENROUTER_BASE_URL,
    OPENROUTER_KEY,
    PHRASE_LIMIT,
    PICO_KEY,
    REQUIRE_WAKE_PREFIX,
    SILENCE_TIMEOUT,
    ensure_runtime_ready,
)
from listen import MicrophoneError, SpeechInterrupter, is_interrupt_phrase, listen_for_command, listen_for_wake_signal
from memory import ConversationMemory
from runtime import JARVIS_MAIN_MUTEX_NAME, SingleInstanceMutex
from speak import build_offline_tts_engine, initialize_audio_mixer, play_sound, speak_sentence
from ui import JarvisHUD
from wake import WakeWordDetector

_DIRECT_WAKE_PATTERN = re.compile(
    r"^\s*(?:(?:hey|hi|ok|okay)\s+)?(?:jarvis|jervis|jarviss|jarves|jarvies|j\W*a\W*r\W*v\W*i\W*s)\b[\s,!.:-]*",
    re.IGNORECASE,
)
_DIRECT_WAKE_SESSION_SECONDS = float("inf")


def _print_banner() -> None:
    """Print a clean startup banner in an Iron Man inspired style."""
    banner = r"""
      _   ___      _______   ________
     | | / / \    / /  _/ | / / ____/
     | |/ / _ \  / // //  |/ / / __
     |   / ___ \/ // // /|  / /_/ /
     |_|_/_/  \_/___/_/_/ |_|\____/

        J A R V I S   V O I C E   C O R E
    """
    print(banner)


def _extract_direct_wake_command(text: str) -> tuple[bool, str]:
    """Detect direct wake phrase variants and return remaining command text."""
    if not text:
        return False, ""

    compact = re.sub(r"\s+", " ", text.strip())
    match = _DIRECT_WAKE_PATTERN.match(compact)
    if not match:
        return False, compact

    cleaned = f"{compact[:match.start()]} {compact[match.end():]}".strip(" ,.!?-")
    return True, cleaned


def _normalize_spoken_command(text: str) -> str:
    """Remove common filler words and punctuation noise from spoken commands."""
    compact = re.sub(r"\s+", " ", (text or "").strip())
    compact = re.sub(r"^(?:okay|ok|well|please|sir)\b[\s,.:;-]*", "", compact, flags=re.IGNORECASE)
    compact = compact.strip(" ,.!?-")
    return compact


def main() -> None:
    """Initialize services and run the continuous Jarvis voice loop."""
    instance_lock = SingleInstanceMutex(JARVIS_MAIN_MUTEX_NAME)
    if not instance_lock.acquire():
        print("[INFO] Jarvis is already running.")
        return

    hud = JarvisHUD(enabled=ENABLE_HUD)
    shutdown_requested = False
    hud_was_visible = hud.enabled

    def _log(line: str) -> None:
        """Write logs to terminal and HUD consistently."""
        try:
            print(line)
        except OSError:
            pass
        hud.log(line)

    def _set_state(state: str) -> None:
        """Update the visual HUD state when enabled."""
        hud.set_state(state)

    _log("[BOOT] Starting Jarvis voice pipeline...")
    ensure_runtime_ready()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    wake_sound = os.path.join(base_dir, "sounds", "wake_chime.mp3")
    error_sound = os.path.join(base_dir, "sounds", "error_tone.mp3")

    wake_detector = None
    audio_interface = None
    offline_engine = None
    elevenlabs_client = None
    mixer_ready = False
    tts_remote_enabled = not FORCE_OFFLINE_TTS
    direct_awake_until = 0.0
    pending_command: str | None = None

    def _queue_barge_in_command(interrupted_text: str | None) -> bool:
        """Treat interruption speech as either a stop request or the next command."""
        nonlocal pending_command, direct_awake_until

        normalized = _normalize_spoken_command(interrupted_text or "")
        if not normalized:
            return False

        direct_awake_until = time.monotonic() + _DIRECT_WAKE_SESSION_SECONDS
        if is_interrupt_phrase(normalized):
            _log("[INFO] Speech interrupted by user.")
            return True

        pending_command = normalized
        return True

    def _speak_lines(
        lines: Iterable[str],
        allow_barge_in: bool = True,
        before_speak: Callable[[str], None] | None = None,
    ) -> tuple[list[str], str | None]:
        """Speak one or more lines and capture any user interruption mid-response."""
        nonlocal tts_remote_enabled

        spoken_lines: list[str] = []
        interrupter = SpeechInterrupter() if allow_barge_in else None
        interrupter_started = interrupter.start() if interrupter is not None else False
        interrupted_text: str | None = None

        try:
            for raw_line in lines:
                line = (raw_line or "").strip()
                if not line:
                    continue

                if before_speak is not None:
                    before_speak(line)

                spoken_lines.append(line)
                if interrupter_started and interrupter is not None:
                    interrupter.set_expected_output(line)

                _set_state("SPEAKING")
                tts_remote_enabled = speak_sentence(
                    line,
                    elevenlabs_client if tts_remote_enabled else None,
                    ELEVENLABS_VOICE,
                    audio_interface,
                    offline_engine,
                    error_sound,
                    interrupt_event=interrupter.interrupt_event if interrupter_started and interrupter is not None else None,
                )

                if interrupter_started and interrupter is not None:
                    interrupted_text = interrupter.consume_text()
                    if interrupted_text:
                        break

            return spoken_lines, interrupted_text
        finally:
            if interrupted_text and hasattr(lines, "close"):
                try:
                    lines.close()
                except Exception:
                    pass
            if interrupter_started and interrupter is not None:
                interrupter.stop()
            _set_state("LISTENING")

    try:
        _set_state("THINKING")
        _log("[BOOT] Initializing audio mixer...")
        mixer_ready = initialize_audio_mixer()
        if not mixer_ready:
            _log("[INFO] Audio mixer is unavailable. Jarvis will continue without UI sound effects.")

        _print_banner()
        hud.log("[SYS] Jarvis HUD online.")

        _log("[BOOT] Initializing memory...")
        memory = ConversationMemory()

        if PICO_KEY:
            _log("[BOOT] Initializing wake detector...")
            wake_detector = WakeWordDetector(PICO_KEY)
        else:
            _log("[INFO] PICOVOICE_ACCESS_KEY not set. Wake word is disabled; running in direct-listen mode.")

        _log("[BOOT] Initializing API clients...")
        anthropic_client = None
        if LOCAL_ONLY_MODE:
            _log("[INFO] Local-only mode is enabled. Cloud LLMs will be skipped.")
        elif OPENROUTER_KEY:
            _log(f"[INFO] Using OpenRouter at {OPENROUTER_BASE_URL}.")
            anthropic_client = Anthropic(
                auth_token=OPENROUTER_KEY,
                base_url=OPENROUTER_BASE_URL,
            )
        elif ANTHROPIC_KEY:
            _log("[INFO] Using Anthropic direct API.")
            anthropic_client = Anthropic(api_key=ANTHROPIC_KEY)
        elif LOCAL_LLM_FALLBACK:
            _log("[INFO] No cloud key detected. Running with local LLM fallback mode.")
        else:
            _log("[ERROR] No cloud key or local fallback is configured.")

        if not FORCE_OFFLINE_TTS:
            elevenlabs_client = ElevenLabs(api_key=ELEVENLABS_KEY)
        else:
            elevenlabs_client = None
        audio_interface = pyaudio.PyAudio()
        offline_engine = build_offline_tts_engine()
        if FORCE_OFFLINE_TTS:
            _log("[INFO] FORCE_OFFLINE_TTS is enabled. Using offline speech output only.")

        _log("[INFO] Jarvis is online.")
        if wake_detector is None:
            direct_awake_until = time.monotonic() + _DIRECT_WAKE_SESSION_SECONDS
        hud.show()
        _, interrupted_text = _speak_lines(
            ["Good morning sir. Jarvis is online and ready."],
            allow_barge_in=True,
        )
        _queue_barge_in_command(interrupted_text)

        while True:
            if hud.enabled:
                event = hud.poll_event()
                if event == "WINDOW_CLOSED":
                    _log("[INFO] HUD window closed. Shutting Jarvis down cleanly.")
                    shutdown_requested = True
                    break
                if not hud.is_alive():
                    _log("[ERROR] HUD window exited unexpectedly. Restarting visual shell...")
                    if hud.restart():
                        hud_was_visible = True
                        _log("[INFO] HUD window restored.")
                    else:
                        _log("[ERROR] HUD restart failed. Shutting down to avoid hidden background mode.")
                        shutdown_requested = True
                        break

            from_ui_input = False
            command_logged = False
            if pending_command:
                command = pending_command
                pending_command = None
                _log(f"[YOU] {command}")
                command_logged = True
            else:
                command = hud.poll_text_command()
                if command:
                    from_ui_input = True
                    _log(f"[YOU] {command}")
                    command_logged = True
                else:
                    if wake_detector is not None:
                        _set_state("SLEEPING")
                        _log("[SLEEPING] Waiting for wake word...")
                        wake_triggered = wake_detector.detect()
                        if not wake_triggered:
                            continue
                        play_sound(wake_sound)
                        _set_state("LISTENING")
                        _log("[AWAKE] Listening for command...")
                    else:
                        _set_state("LISTENING")
                        session_awake = time.monotonic() < direct_awake_until
                        if REQUIRE_WAKE_PREFIX and not session_awake:
                            if CLAP_DETECTION_ENABLED:
                                _log("[SLEEPING] Waiting for wake signal: double clap or 'Hey Jarvis'...")
                            else:
                                _log("[SLEEPING] Waiting for wake phrase: 'Hey Jarvis'...")
                        else:
                            _log("[SLEEPING] Listening for command...")

                    try:
                        if wake_detector is None and REQUIRE_WAKE_PREFIX and time.monotonic() >= direct_awake_until:
                            wake_signal = listen_for_wake_signal(SILENCE_TIMEOUT, PHRASE_LIMIT)
                            if wake_signal is None:
                                command = None
                            elif wake_signal.kind == "clap":
                                direct_awake_until = time.monotonic() + _DIRECT_WAKE_SESSION_SECONDS
                                hud.show()
                                play_sound(wake_sound)
                                _, interrupted_text = _speak_lines(
                                    ["Yes sir. I'm awake."],
                                    allow_barge_in=True,
                                )
                                if _queue_barge_in_command(interrupted_text):
                                    continue
                                _log("[AWAKE] Listening for command...")
                                command = listen_for_command(SILENCE_TIMEOUT, PHRASE_LIMIT)
                            else:
                                command = wake_signal.text
                        else:
                            command = listen_for_command(SILENCE_TIMEOUT, PHRASE_LIMIT)
                    except MicrophoneError as exc:
                        _log(f"[ERROR] Microphone not found or unavailable: {exc}")
                        play_sound(error_sound)
                        _, interrupted_text = _speak_lines(
                            ["Sir, I appear to be having trouble with the microphone."],
                            allow_barge_in=True,
                        )
                        _queue_barge_in_command(interrupted_text)
                        time.sleep(0.4)
                        continue

            if command is None:
                if wake_detector is not None:
                    _, interrupted_text = _speak_lines(["I didn't quite catch that sir."], allow_barge_in=True)
                    _queue_barge_in_command(interrupted_text)
                continue

            if not isinstance(command, str):
                _log("[ERROR] Ignoring invalid command payload from input pipeline.")
                continue

            if not from_ui_input and not command_logged:
                hud.log(f"[YOU] {command}")
            if wake_detector is None and not from_ui_input:
                session_awake = time.monotonic() < direct_awake_until
                has_wake, stripped_command = _extract_direct_wake_command(command)
                if has_wake:
                    command = _normalize_spoken_command(stripped_command)
                    direct_awake_until = time.monotonic() + _DIRECT_WAKE_SESSION_SECONDS
                    hud.show()
                    if not session_awake:
                        _, interrupted_text = _speak_lines(
                            ["Yes sir. I'm awake."],
                            allow_barge_in=True,
                        )
                        if _queue_barge_in_command(interrupted_text):
                            continue
                elif REQUIRE_WAKE_PREFIX and not session_awake:
                    continue

                if has_wake and not command:
                    _, interrupted_text = _speak_lines(["Yes sir?"], allow_barge_in=True)
                    if _queue_barge_in_command(interrupted_text):
                        continue
                    _log("[AWAKE] Listening for command...")
                    try:
                        follow_up = listen_for_command(SILENCE_TIMEOUT, PHRASE_LIMIT)
                    except MicrophoneError as exc:
                        _log(f"[ERROR] Microphone not found or unavailable: {exc}")
                        play_sound(error_sound)
                        _, interrupted_text = _speak_lines(
                            ["Sir, I appear to be having trouble with the microphone."],
                            allow_barge_in=True,
                        )
                        _queue_barge_in_command(interrupted_text)
                        continue

                    if follow_up is None:
                        continue
                    command = _normalize_spoken_command(follow_up)
                    if not command:
                        continue
                    direct_awake_until = time.monotonic() + _DIRECT_WAKE_SESSION_SECONDS

            command = _normalize_spoken_command(command)
            if not command:
                continue

            lowered_command = command.lower().strip()
            if wake_detector is None and any(token in lowered_command for token in ["go to sleep", "sleep mode", "stand by"]):
                direct_awake_until = 0.0
                _, interrupted_text = _speak_lines(
                    ["Understood sir. Returning to wake-word standby."],
                    allow_barge_in=True,
                )
                _queue_barge_in_command(interrupted_text)
                continue

            action_result: ActionResult = handle_local_action(command)
            if action_result.handled:
                spoken = action_result.response or "Done, sir."
                memory.add_user(command)
                memory.add_assistant(spoken)
                _log(f"[JARVIS] {spoken}")
                _, interrupted_text = _speak_lines([spoken], allow_barge_in=True)
                _queue_barge_in_command(interrupted_text)
                continue

            memory.add_user(command)

            if "forget everything" in command.lower():
                memory.clear()
                _, interrupted_text = _speak_lines(
                    ["Understood sir. I have cleared our conversation history."],
                    allow_barge_in=True,
                )
                _queue_barge_in_command(interrupted_text)
                continue

            runtime_context = get_runtime_time_context()
            live_web_context = get_live_web_context(command) if should_fetch_web_context(command) else None
            _set_state("THINKING")
            response_stream = think(
                command,
                memory,
                anthropic_client,
                runtime_context=runtime_context,
                live_web_context=live_web_context,
            )
            spoken_parts, interrupted_text = _speak_lines(
                response_stream,
                allow_barge_in=True,
                before_speak=lambda sentence: play_sound(error_sound) if "technical difficulty" in sentence.lower() else None,
            )
            if spoken_parts:
                hud.log(f"[JARVIS] {' '.join(spoken_parts)}")
            if _queue_barge_in_command(interrupted_text):
                continue

    except KeyboardInterrupt:
        _log("\n[INFO] Shutdown requested by user.")
        if audio_interface is not None:
            try:
                _speak_lines(["Goodbye sir. Jarvis signing off."], allow_barge_in=False)
            except Exception as exc:
                _log(f"[ERROR] Failed to play shutdown message: {exc}")

    except Exception as exc:
        _log(f"[ERROR] Fatal runtime error: {exc}")
        play_sound(error_sound)

    finally:
        if shutdown_requested and audio_interface is not None:
            try:
                _speak_lines(["Goodbye sir. Jarvis signing off."], allow_barge_in=False)
            except Exception as exc:
                _log(f"[ERROR] Failed to play shutdown message: {exc}")

        if wake_detector is not None:
            wake_detector.cleanup()

        if audio_interface is not None:
            try:
                audio_interface.terminate()
            except Exception as exc:
                _log(f"[ERROR] Failed to terminate PyAudio: {exc}")

        try:
            pygame.mixer.quit()
        except Exception:
            pass

        _set_state("OFFLINE")
        if hud_was_visible:
            _log("[INFO] Jarvis has shut down cleanly.")
        hud.close()
        instance_lock.close()


if __name__ == "__main__":
    """Run Jarvis when this file is executed directly."""
    main()
