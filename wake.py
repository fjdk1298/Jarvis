"""Wake-word detection layer for Jarvis.

This module runs Porcupine with the built-in 'jarvis' keyword and
exposes a detector class used by the main orchestration loop.
"""

from __future__ import annotations

import time
from threading import Event, Thread

import pvporcupine
from pvrecorder import PvRecorder


class WakeWordDetector:
    """Continuously listen for the Jarvis wake word using Porcupine."""

    def __init__(self, access_key: str) -> None:
        """Initialize Porcupine and microphone recorder resources."""
        self._porcupine = None
        self._recorder = None
        self._stop_event = Event()
        self._detected_event = Event()
        self._worker = None

        try:
            self._porcupine = pvporcupine.create(access_key=access_key, keywords=["jarvis"])
            self._recorder = PvRecorder(device_index=-1, frame_length=self._porcupine.frame_length)
            self._recorder.start()
            self._worker = Thread(target=self._run_detection_loop, daemon=True)
            self._worker.start()
            print("[INFO] Wake detector initialized.")
        except FileNotFoundError as exc:
            print(
                "[ERROR] Porcupine keyword file was not found. "
                "Please verify your Picovoice setup in https://console.picovoice.ai."
            )
            raise SystemExit(1) from exc
        except Exception as exc:
            print(f"[ERROR] Failed to initialize wake detector: {exc}")
            raise SystemExit(1) from exc

    def detect(self) -> bool:
        """Block until the wake word is detected, then return True."""
        if self._porcupine is None or self._recorder is None:
            print("[ERROR] Wake detector is not initialized.")
            return False

        while not self._stop_event.is_set():
            if self._detected_event.wait(timeout=0.1):
                self._detected_event.clear()
                return True

        return False

    def _run_detection_loop(self) -> None:
        """Run continuous wake-word checks on a background thread."""
        if self._porcupine is None or self._recorder is None:
            return

        while not self._stop_event.is_set():
            try:
                pcm_frame = self._recorder.read()
                keyword_index = self._porcupine.process(pcm_frame)
                if keyword_index >= 0:
                    print("[WAKE] Wake word detected!")
                    self._detected_event.set()
            except Exception as exc:
                print(f"[ERROR] Wake detection error: {exc}")
                time.sleep(0.2)

    def cleanup(self) -> None:
        """Release Porcupine and recorder resources safely."""
        self._stop_event.set()

        try:
            if self._worker is not None and self._worker.is_alive():
                self._worker.join(timeout=1.0)
        except Exception as exc:
            print(f"[ERROR] Wake worker cleanup issue: {exc}")

        try:
            if self._recorder is not None:
                self._recorder.stop()
                self._recorder.delete()
                self._recorder = None
        except Exception as exc:
            print(f"[ERROR] Recorder cleanup issue: {exc}")

        try:
            if self._porcupine is not None:
                self._porcupine.delete()
                self._porcupine = None
        except Exception as exc:
            print(f"[ERROR] Porcupine cleanup issue: {exc}")
