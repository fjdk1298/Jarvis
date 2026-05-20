"""Speech capture and transcription for Jarvis.

This module records from the default microphone and transcribes user
speech through Google Speech Recognition.
"""

from __future__ import annotations

from array import array
from dataclasses import dataclass
import re
import sys
import threading

import speech_recognition as sr

from config import (
    CLAP_DETECTION_ENABLED,
    CLAP_ENERGY_RATIO,
    CLAP_MAX_BURST_SECONDS,
    CLAP_MAX_GAP_SECONDS,
    CLAP_MIN_GAP_SECONDS,
    CLAP_MIN_PEAK,
    WAKE_SIGNAL_PHRASE_LIMIT,
)


class MicrophoneError(Exception):
    """Raised when microphone access fails and the caller should recover."""


@dataclass
class WakeSignal:
    """Represent a successful wake trigger from speech or a double clap."""

    kind: str
    text: str | None = None


class SpeechInterrupter:
    """Listen in the background for barge-in speech while Jarvis is talking."""

    def __init__(self, phrase_limit: int = 4) -> None:
        """Initialize recognizer state and interruption buffers."""
        self._recognizer = sr.Recognizer()
        self._recognizer.pause_threshold = 0.45
        self._recognizer.dynamic_energy_threshold = True
        self._phrase_limit = phrase_limit
        self._microphone: sr.Microphone | None = None
        self._stopper = None
        self._captured_text: str | None = None
        self._expected_output = ""
        self._lock = threading.Lock()
        self._interrupt_event = threading.Event()

    @property
    def interrupt_event(self) -> threading.Event:
        """Expose the shared event used to stop playback mid-sentence."""
        return self._interrupt_event

    def start(self) -> bool:
        """Start a background speech listener and return whether it succeeded."""
        try:
            self._microphone = sr.Microphone()
            with self._microphone as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=0.2)
            self._stopper = self._recognizer.listen_in_background(
                self._microphone,
                self._handle_audio,
                phrase_time_limit=self._phrase_limit,
            )
            return True
        except OSError as exc:
            print(f"[INFO] Barge-in microphone unavailable: {exc}")
            return False
        except Exception as exc:
            print(f"[INFO] Barge-in listener unavailable: {exc}")
            return False

    def stop(self) -> None:
        """Stop the background listener and release resources."""
        if self._stopper is not None:
            try:
                self._stopper(wait_for_stop=False)
            except Exception:
                pass
            self._stopper = None
        self._microphone = None

    def set_expected_output(self, text: str) -> None:
        """Update the current Jarvis sentence so echo can be ignored."""
        with self._lock:
            self._expected_output = text or ""

    def consume_text(self) -> str | None:
        """Return the captured interruption text, if any."""
        with self._lock:
            captured = self._captured_text
            self._captured_text = None
            return captured

    def _handle_audio(self, recognizer: sr.Recognizer, audio: sr.AudioData) -> None:
        """Transcribe one background chunk and latch it if it is a real interruption."""
        if self._interrupt_event.is_set():
            return

        try:
            text = recognizer.recognize_google(audio).strip()
        except sr.UnknownValueError:
            return
        except sr.RequestError:
            return
        except Exception:
            return

        if not text or not self._should_capture(text):
            return

        with self._lock:
            if self._captured_text is None:
                self._captured_text = text
                self._interrupt_event.set()
                print(f"[INFO] Barge-in detected: {text}")

    def _should_capture(self, text: str) -> bool:
        """Decide whether recognized speech is likely user barge-in rather than speaker echo."""
        normalized = _normalize_interrupt_text(text)
        if not normalized:
            return False

        if _is_explicit_interrupt_phrase(normalized):
            return True

        if len(normalized) < 5:
            return False

        with self._lock:
            expected = self._expected_output

        return not _looks_like_output_echo(normalized, expected)


def _normalize_interrupt_text(text: str) -> str:
    """Normalize transcribed speech for simple interruption matching."""
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _is_explicit_interrupt_phrase(text: str) -> bool:
    """Check whether a phrase clearly means stop talking right now."""
    normalized = _normalize_interrupt_text(text).strip(" .,!?:;")
    explicit = {
        "stop",
        "jarvis stop",
        "hey jarvis stop",
        "wait",
        "hold on",
        "be quiet",
        "quiet",
        "pause",
        "enough",
    }
    return normalized in explicit


def is_interrupt_phrase(text: str) -> bool:
    """Public helper for checking whether spoken text means stop speaking."""
    return _is_explicit_interrupt_phrase(text)


def _looks_like_output_echo(recognized_text: str, expected_output: str) -> bool:
    """Heuristically filter out phrases that mostly match Jarvis's own speech."""
    heard = _normalize_interrupt_text(recognized_text)
    expected = _normalize_interrupt_text(expected_output)
    if not heard or not expected:
        return False

    if heard in expected or expected in heard:
        return True

    heard_tokens = {token for token in re.findall(r"[a-z0-9']+", heard) if len(token) > 2}
    expected_tokens = {token for token in re.findall(r"[a-z0-9']+", expected) if len(token) > 2}
    if not heard_tokens or not expected_tokens:
        return False

    overlap = len(heard_tokens & expected_tokens)
    overlap_ratio = overlap / max(1, len(heard_tokens))
    return overlap_ratio >= 0.6


def _audio_to_samples(audio: sr.AudioData) -> tuple[array, int]:
    """Convert SpeechRecognition audio into 16-bit PCM samples for local analysis."""
    raw = audio.get_raw_data(convert_rate=16000, convert_width=2)
    samples = array("h")
    samples.frombytes(raw)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples, 16000


def _median(values: list[int]) -> int:
    """Return the integer median of a small numeric list."""
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def _is_double_clap(audio: sr.AudioData) -> bool:
    """Detect a local double-clap pattern from raw microphone audio."""
    if not CLAP_DETECTION_ENABLED:
        return False

    try:
        samples, sample_rate = _audio_to_samples(audio)
    except Exception:
        return False

    if not samples:
        return False

    window_samples = max(1, int(sample_rate * 0.02))
    window_seconds = window_samples / sample_rate
    peaks: list[int] = []

    for index in range(0, len(samples), window_samples):
        window = samples[index : index + window_samples]
        if not window:
            continue
        peaks.append(max(abs(sample) for sample in window))

    if len(peaks) < 2:
        return False

    baseline = _median(peaks)
    threshold = max(CLAP_MIN_PEAK, int(baseline * CLAP_ENERGY_RATIO))
    active_indices = [idx for idx, peak in enumerate(peaks) if peak >= threshold]
    if len(active_indices) < 2:
        return False

    bursts: list[tuple[float, float, int]] = []
    start = active_indices[0]
    end = active_indices[0]
    max_peak = peaks[active_indices[0]]

    for idx in active_indices[1:]:
        if idx == end + 1:
            end = idx
            max_peak = max(max_peak, peaks[idx])
            continue

        bursts.append((start * window_seconds, (end + 1) * window_seconds, max_peak))
        start = idx
        end = idx
        max_peak = peaks[idx]

    bursts.append((start * window_seconds, (end + 1) * window_seconds, max_peak))

    short_bursts = [
        ((burst_start + burst_end) / 2.0, peak)
        for burst_start, burst_end, peak in bursts
        if (burst_end - burst_start) <= CLAP_MAX_BURST_SECONDS
    ]
    if len(short_bursts) < 2:
        return False

    for first_index in range(len(short_bursts) - 1):
        first_time, first_peak = short_bursts[first_index]
        for second_time, second_peak in short_bursts[first_index + 1 :]:
            gap = second_time - first_time
            if CLAP_MIN_GAP_SECONDS <= gap <= CLAP_MAX_GAP_SECONDS:
                if first_peak >= threshold and second_peak >= threshold:
                    return True
            if gap > CLAP_MAX_GAP_SECONDS:
                break

    return False


def listen_for_wake_signal(silence_timeout: int, phrase_limit: int) -> WakeSignal | None:
    """Wait for either a wake phrase or a double-clap and report the trigger."""
    recognizer = sr.Recognizer()
    listen_limit = min(max(1, phrase_limit), WAKE_SIGNAL_PHRASE_LIMIT)

    try:
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.35)
            audio = recognizer.listen(
                source,
                timeout=silence_timeout,
                phrase_time_limit=listen_limit,
            )
    except sr.WaitTimeoutError:
        print("[INFO] Wake listening timed out with no speech or clap.")
        return None
    except OSError as exc:
        raise MicrophoneError(str(exc)) from exc
    except Exception as exc:
        print(f"[ERROR] Wake capture failed: {exc}")
        return None

    if _is_double_clap(audio):
        print("[WAKE] Double clap detected!")
        return WakeSignal(kind="clap")

    try:
        text = recognizer.recognize_google(audio).strip()
        if text:
            print(f"[YOU] {text}")
            return WakeSignal(kind="speech", text=text)
        return None
    except sr.UnknownValueError:
        print("[INFO] Wake signal was detected but not understood.")
        return None
    except sr.RequestError as exc:
        print(f"[ERROR] Google STT request failed during wake listening: {exc}")
        return None


def listen_for_double_clap(silence_timeout: int, phrase_limit: int) -> bool:
    """Listen locally for one double-clap wake attempt without using cloud STT."""
    if not CLAP_DETECTION_ENABLED:
        return False

    recognizer = sr.Recognizer()
    listen_limit = min(max(1, phrase_limit), WAKE_SIGNAL_PHRASE_LIMIT)

    try:
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.25)
            audio = recognizer.listen(
                source,
                timeout=silence_timeout,
                phrase_time_limit=listen_limit,
            )
    except sr.WaitTimeoutError:
        return False
    except OSError as exc:
        raise MicrophoneError(str(exc)) from exc
    except Exception as exc:
        print(f"[ERROR] Double-clap capture failed: {exc}")
        return False

    if _is_double_clap(audio):
        print("[WAKE] Double clap detected!")
        return True

    return False


def listen_for_command(silence_timeout: int, phrase_limit: int) -> str | None:
    """Listen for a spoken command and return transcribed text or None."""
    recognizer = sr.Recognizer()

    try:
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            audio = recognizer.listen(
                source,
                timeout=silence_timeout,
                phrase_time_limit=phrase_limit,
            )
    except sr.WaitTimeoutError:
        print("[INFO] Listening timed out with no speech.")
        return None
    except OSError as exc:
        raise MicrophoneError(str(exc)) from exc
    except Exception as exc:
        print(f"[ERROR] Microphone capture failed: {exc}")
        return None

    try:
        text = recognizer.recognize_google(audio).strip()
        if text:
            print(f"[YOU] {text}")
            return text
        return None
    except sr.UnknownValueError:
        print("[INFO] Speech was detected but not understood.")
        return None
    except sr.RequestError as exc:
        print(f"[ERROR] Google STT request failed: {exc}")
        return None
