"""Speech output layer for Jarvis.

This module plays short UI sounds and streams ElevenLabs TTS audio
in real time, with Edge/SAPI/PowerShell offline fallbacks.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
import threading
import time
from typing import Any

import pyaudio
import pygame
from elevenlabs import VoiceSettings

from config import EDGE_TTS_VOICE, OFFLINE_TTS_ENGINE, TTS_SIMILARITY, TTS_STABILITY, TTS_STYLE, TTS_USE_SPEAKER_BOOST


def initialize_audio_mixer() -> bool:
    """Initialize pygame mixer with Windows-friendly fallbacks."""
    if pygame.mixer.get_init() is not None:
        return True

    original_driver = os.environ.get("SDL_AUDIODRIVER")
    candidates: list[str | None] = [original_driver]

    if os.name == "nt":
        candidates.extend(["directsound", "winmm", None])
    else:
        candidates.append(None)

    seen: set[str | None] = set()
    ordered_candidates: list[str | None] = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        ordered_candidates.append(candidate)

    last_error = ""
    for candidate in ordered_candidates:
        try:
            pygame.mixer.quit()
        except Exception:
            pass

        try:
            if candidate:
                os.environ["SDL_AUDIODRIVER"] = candidate
            elif "SDL_AUDIODRIVER" in os.environ:
                del os.environ["SDL_AUDIODRIVER"]

            pygame.mixer.init()
            if candidate:
                print(f"[INFO] Audio mixer initialized with SDL_AUDIODRIVER={candidate}.")
            else:
                print("[INFO] Audio mixer initialized with default SDL audio driver.")
            return True
        except Exception as exc:
            last_error = str(exc)

    if original_driver:
        os.environ["SDL_AUDIODRIVER"] = original_driver
    elif "SDL_AUDIODRIVER" in os.environ:
        del os.environ["SDL_AUDIODRIVER"]

    print(f"[INFO] Audio mixer unavailable. Continuing without sound effects: {last_error}")
    return False


def build_offline_tts_engine() -> Any | None:
    """Create a pyttsx3 engine for local fallback speech when available."""
    engines: dict[str, Any] = {}

    try:
        import pyttsx3

        engine = pyttsx3.init()
        engine.setProperty("rate", 185)
        engines["pyttsx3"] = engine
    except Exception as exc:
        print(f"[INFO] pyttsx3 offline TTS unavailable: {exc}")

    try:
        import win32com.client

        speaker = win32com.client.Dispatch("SAPI.SpVoice")
        speaker.Rate = 0
        engines["sapi"] = speaker
    except Exception as exc:
        print(f"[INFO] Windows SAPI fallback unavailable: {exc}")

    try:
        import edge_tts  # noqa: F401

        engines["edge"] = True
    except Exception as exc:
        print(f"[INFO] Edge TTS fallback unavailable: {exc}")

    engines["powershell"] = True

    if not engines:
        print("[ERROR] No offline TTS backends are available.")
        return None

    return engines


def play_sound(filepath: str) -> None:
    """Play a short sound file with pygame in a non-blocking manner."""
    if not os.path.exists(filepath):
        print(f"[ERROR] Sound file not found: {filepath}")
        return

    if pygame.mixer.get_init() is None and not initialize_audio_mixer():
        return

    try:
        sound = pygame.mixer.Sound(filepath)
        sound.play()
    except Exception as exc:
        print(f"[ERROR] Failed to play sound '{filepath}': {exc}")


def _run_interruptible_pyttsx3(engine: Any, sentence: str, interrupt_event: threading.Event | None) -> bool:
    """Speak through pyttsx3 on a worker thread so the engine can be stopped."""
    completed = threading.Event()
    error_box: dict[str, Exception] = {}

    def _worker() -> None:
        """Run the blocking pyttsx3 event loop in the background."""
        try:
            engine.say(sentence)
            engine.runAndWait()
        except Exception as exc:
            error_box["error"] = exc
        finally:
            completed.set()

    threading.Thread(target=_worker, daemon=True).start()
    while not completed.wait(0.05):
        if interrupt_event is not None and interrupt_event.is_set():
            try:
                engine.stop()
            except Exception:
                pass
            completed.wait(1.0)
            return True

    if error_box:
        raise error_box["error"]
    return True


def _speak_offline(
    sentence: str,
    offline_engine: Any | None,
    interrupt_event: threading.Event | None = None,
) -> None:
    """Speak a sentence through local backends, honoring interruption when possible."""
    if interrupt_event is not None and interrupt_event.is_set():
        return

    if offline_engine is None:
        _speak_with_powershell(sentence, interrupt_event=interrupt_event)
        return

    preferred = OFFLINE_TTS_ENGINE if OFFLINE_TTS_ENGINE in {"auto", "edge", "pyttsx3", "sapi", "powershell"} else "auto"

    if isinstance(offline_engine, dict):
        if preferred == "auto":
            backends = ("edge", "powershell", "pyttsx3", "sapi")
        elif preferred == "edge":
            backends = ("edge", "powershell", "pyttsx3", "sapi")
        elif preferred == "pyttsx3":
            backends = ("pyttsx3", "edge", "sapi", "powershell")
        elif preferred == "sapi":
            backends = ("sapi", "edge", "powershell", "pyttsx3")
        else:
            backends = ("powershell", "edge", "pyttsx3", "sapi")

        for backend in backends:
            if backend == "edge" and offline_engine.get("edge"):
                if _speak_with_edge(sentence, interrupt_event=interrupt_event):
                    return

            if backend == "powershell" and offline_engine.get("powershell"):
                if _speak_with_powershell(sentence, interrupt_event=interrupt_event):
                    return

            if backend == "pyttsx3":
                pyttsx3_engine = offline_engine.get("pyttsx3")
                if pyttsx3_engine is None:
                    continue
                try:
                    if _run_interruptible_pyttsx3(pyttsx3_engine, sentence, interrupt_event):
                        return
                except Exception as exc:
                    print(f"[ERROR] pyttsx3 fallback failed: {exc}")

            if backend == "sapi":
                sapi_speaker = offline_engine.get("sapi")
                if sapi_speaker is None:
                    continue
                try:
                    sapi_speaker.Speak(sentence)
                    return
                except Exception as exc:
                    print(f"[ERROR] SAPI fallback failed: {exc}")

    else:
        try:
            if _run_interruptible_pyttsx3(offline_engine, sentence, interrupt_event):
                return
        except Exception as exc:
            print(f"[ERROR] Offline TTS fallback failed: {exc}")

    print("[ERROR] Offline TTS could not speak this sentence.")


def _speak_with_edge(sentence: str, interrupt_event: threading.Event | None = None) -> bool:
    """Use Microsoft Edge neural voices as a natural-sounding free fallback."""
    tmp_path = ""
    try:
        import edge_tts

        async def _render_to_file(path: str) -> None:
            communicator = edge_tts.Communicate(text=sentence, voice=EDGE_TTS_VOICE)
            await communicator.save(path)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
            tmp_path = tmp.name

        asyncio.run(_render_to_file(tmp_path))

        if pygame.mixer.get_init() is None and not initialize_audio_mixer():
            return False

        pygame.mixer.music.load(tmp_path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            if interrupt_event is not None and interrupt_event.is_set():
                pygame.mixer.music.stop()
                return True
            pygame.time.wait(30)
        return True
    except Exception as exc:
        print(f"[ERROR] Edge TTS fallback failed: {exc}")
        return False
    finally:
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def _speak_with_powershell(sentence: str, interrupt_event: threading.Event | None = None) -> bool:
    """Use built-in Windows SpeechSynthesizer via PowerShell as final fallback."""
    escaped = sentence.replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$s.Rate = 0; "
        f"$text = '{escaped}'; "
        "if ([string]::IsNullOrWhiteSpace($text)) { exit 2 }; "
        "$s.Speak($text) | Out-Null;"
    )
    process = None
    start_time = time.monotonic()
    try:
        process = subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        while True:
            if interrupt_event is not None and interrupt_event.is_set():
                try:
                    process.terminate()
                    process.wait(timeout=1.0)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass
                return True

            if process.poll() is not None:
                stdout, stderr = process.communicate(timeout=0.2)
                if process.returncode != 0:
                    message = (stderr or stdout or "").strip()
                    if message:
                        print(f"[ERROR] PowerShell speech returned {process.returncode}: {message}")
                    return False
                return True

            if time.monotonic() - start_time > 30:
                try:
                    process.terminate()
                except Exception:
                    pass
                print("[ERROR] PowerShell speech fallback timed out.")
                return False

            time.sleep(0.05)
    except Exception as exc:
        print(f"[ERROR] PowerShell speech fallback failed: {exc}")
        return False


def _close_stream_safely(playback_stream) -> None:
    """Stop and close a PyAudio playback stream without surfacing cleanup errors."""
    if playback_stream is None:
        return
    try:
        playback_stream.stop_stream()
    except Exception as exc:
        print(f"[ERROR] Failed to stop audio stream: {exc}")
    try:
        playback_stream.close()
    except Exception as exc:
        print(f"[ERROR] Failed to close audio stream: {exc}")


def _is_plan_limited_error(exc: Exception) -> bool:
    """Check whether ElevenLabs rejected the request due to plan restrictions."""
    text = str(exc).lower()
    return "paid_plan_required" in text or "payment_required" in text


def speak_sentence(
    sentence: str,
    elevenlabs_client,
    voice_id: str,
    audio_interface: pyaudio.PyAudio,
    offline_engine: Any | None,
    error_sound_path: str | None = None,
    interrupt_event: threading.Event | None = None,
) -> bool:
    """Stream one sentence from ElevenLabs and play audio chunks immediately."""
    if not sentence.strip():
        return True

    playback_stream = None
    audio_chunks = None

    try:
        if elevenlabs_client is None or not voice_id.strip():
            _speak_offline(sentence, offline_engine, interrupt_event=interrupt_event)
            return False

        audio_chunks = elevenlabs_client.text_to_speech.stream(
            voice_id=voice_id,
            text=sentence,
            model_id="eleven_turbo_v2_5",
            output_format="pcm_22050",
            voice_settings=VoiceSettings(
                stability=TTS_STABILITY,
                similarity_boost=TTS_SIMILARITY,
                style=TTS_STYLE,
                use_speaker_boost=TTS_USE_SPEAKER_BOOST,
            ),
        )

        playback_stream = audio_interface.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=22050,
            output=True,
            frames_per_buffer=1024,
        )

        for chunk in audio_chunks:
            if interrupt_event is not None and interrupt_event.is_set():
                break
            if isinstance(chunk, bytes) and chunk:
                playback_stream.write(chunk)
            if interrupt_event is not None and interrupt_event.is_set():
                break

        return True

    except Exception as exc:
        plan_limited = _is_plan_limited_error(exc)
        if plan_limited:
            print("[INFO] ElevenLabs plan does not allow this voice via API. Switching to offline TTS mode.")
        else:
            print(f"[ERROR] ElevenLabs streaming failed, using offline fallback: {exc}")
        if error_sound_path and not plan_limited:
            play_sound(error_sound_path)
        _speak_offline(sentence, offline_engine, interrupt_event=interrupt_event)
        return not plan_limited
    finally:
        close_method = getattr(audio_chunks, "close", None)
        if callable(close_method):
            try:
                close_method()
            except Exception:
                pass
        _close_stream_safely(playback_stream)
