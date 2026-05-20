"""HUD bridge for Jarvis.

This module keeps the main voice loop stable by running the Tk HUD in a
separate child process and exchanging events over standard I/O.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
from typing import Optional


class JarvisHUD:
    """Process-backed HUD bridge with a thread-safe API for the main loop."""

    def __init__(self, enabled: bool = True) -> None:
        """Start the HUD child process and background pipe readers."""
        self.enabled = enabled
        self._process: subprocess.Popen[str] | None = None
        self._command_queue: "queue.Queue[str]" = queue.Queue()
        self._event_queue: "queue.Queue[str]" = queue.Queue()
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._lock = threading.Lock()

        if not enabled:
            return

        host_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui_host.py")
        if not os.path.exists(host_path):
            print(f"[INFO] HUD disabled because host file is missing: {host_path}")
            self.enabled = False
            return

        try:
            self._process = subprocess.Popen(
                [sys.executable, host_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
        except Exception as exc:
            print(f"[INFO] HUD unavailable: {exc}")
            self.enabled = False
            return

        self._stdout_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self._stdout_thread.start()
        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self._stderr_thread.start()

    def set_state(self, state: str) -> None:
        """Send a state update to the HUD."""
        self._send("STATE", state)

    def log(self, line: str) -> None:
        """Send a log line to the HUD terminal panel."""
        self._send("LOG", line)

    def show(self) -> None:
        """Bring the HUD window to the foreground when it needs attention."""
        self._send("SHOW", "")

    def poll_text_command(self) -> Optional[str]:
        """Fetch one typed command from the HUD, if available."""
        if not self.enabled:
            return None
        try:
            return self._command_queue.get_nowait()
        except queue.Empty:
            return None

    def poll_event(self) -> Optional[str]:
        """Fetch one control event from the HUD process, if available."""
        if not self.enabled:
            return None
        try:
            return self._event_queue.get_nowait()
        except queue.Empty:
            return None

    def is_alive(self) -> bool:
        """Return whether the HUD process is still running."""
        if not self.enabled:
            return False
        process = self._process
        return process is not None and process.poll() is None

    def restart(self) -> bool:
        """Restart the HUD process after an unexpected exit."""
        self.close()
        self._process = None
        self._stdout_thread = None
        self._stderr_thread = None
        self._command_queue = queue.Queue()
        self._event_queue = queue.Queue()

        host_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui_host.py")
        if not os.path.exists(host_path):
            self.enabled = False
            return False

        try:
            self._process = subprocess.Popen(
                [sys.executable, host_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
        except Exception as exc:
            print(f"[INFO] HUD restart failed: {exc}")
            self.enabled = False
            return False

        self.enabled = True
        self._stdout_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self._stdout_thread.start()
        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self._stderr_thread.start()
        return True

    def close(self) -> None:
        """Request child HUD shutdown and wait briefly for process exit."""
        if not self.enabled:
            return
        self._send("SHUTDOWN", "")
        process = self._process
        if process is None:
            return

        try:
            if process.stdin:
                process.stdin.close()
        except Exception:
            pass

        try:
            process.wait(timeout=2.0)
        except Exception:
            try:
                process.terminate()
            except Exception:
                pass

    def _send(self, kind: str, value: str) -> None:
        """Write one message frame to the HUD process."""
        if not self.enabled:
            return
        process = self._process
        if process is None or process.stdin is None:
            return
        if process.poll() is not None:
            return

        line = f"{kind}\t{value}\n"
        with self._lock:
            try:
                process.stdin.write(line)
                process.stdin.flush()
            except Exception:
                pass

    def _read_stdout(self) -> None:
        """Parse command frames sent from the HUD process."""
        process = self._process
        if process is None or process.stdout is None:
            return

        for raw in process.stdout:
            line = raw.rstrip("\r\n")
            if not line:
                continue
            if line.startswith("CMD\t"):
                command = line[4:].strip()
                if command:
                    self._command_queue.put(command)
            elif line.startswith("EVENT\t"):
                event = line[6:].strip()
                if event:
                    self._event_queue.put(event)

    def _read_stderr(self) -> None:
        """Forward child HUD stderr lines into terminal logs."""
        process = self._process
        if process is None or process.stderr is None:
            return

        for raw in process.stderr:
            line = raw.rstrip("\r\n")
            if line:
                print(f"[INFO] HUD: {line}")
