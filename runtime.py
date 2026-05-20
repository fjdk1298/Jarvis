"""Single-instance runtime guards for Jarvis processes.

This module uses Windows named mutexes so the background clap launcher
and the main Jarvis app can avoid duplicate instances cleanly.
"""

from __future__ import annotations

import ctypes
import sys

JARVIS_MAIN_MUTEX_NAME = "Local\\JarvisVoiceCoreMain"
JARVIS_LAUNCHER_MUTEX_NAME = "Local\\JarvisVoiceCoreLauncher"
_ERROR_ALREADY_EXISTS = 183
_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True) if sys.platform.startswith("win") else None

if _KERNEL32 is not None:
    _KERNEL32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    _KERNEL32.CreateMutexW.restype = ctypes.c_void_p
    _KERNEL32.CloseHandle.argtypes = [ctypes.c_void_p]
    _KERNEL32.CloseHandle.restype = ctypes.c_bool

class SingleInstanceMutex:
    """Hold a named mutex so only one copy of a process role stays active."""

    def __init__(self, name: str) -> None:
        """Store the mutex name and defer acquisition until requested."""
        self.name = name
        self._handle: int | None = None

    def acquire(self) -> bool:
        """Try to acquire the named mutex and report whether this is the first instance."""
        if _KERNEL32 is None:
            return True

        ctypes.set_last_error(0)
        handle = _KERNEL32.CreateMutexW(None, False, self.name)
        if not handle:
            raise OSError("Failed to create Windows mutex handle.")

        if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
            _KERNEL32.CloseHandle(handle)
            return False

        self._handle = int(handle)
        return True

    def close(self) -> None:
        """Release the held mutex handle when the process exits."""
        if _KERNEL32 is None or self._handle is None:
            return
        _KERNEL32.CloseHandle(ctypes.c_void_p(self._handle))
        self._handle = None

    def __enter__(self) -> SingleInstanceMutex:
        """Acquire the mutex when used as a context manager."""
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """Release the mutex when leaving a context manager block."""
        self.close()


def is_named_instance_running(name: str) -> bool:
    """Check whether some other process already holds the named mutex."""
    if _KERNEL32 is None:
        return False

    ctypes.set_last_error(0)
    handle = _KERNEL32.CreateMutexW(None, False, name)
    if not handle:
        return False

    already_running = ctypes.get_last_error() == _ERROR_ALREADY_EXISTS
    _KERNEL32.CloseHandle(handle)
    return bool(already_running)


def is_jarvis_running() -> bool:
    """Return whether the main Jarvis application is already active."""
    return is_named_instance_running(JARVIS_MAIN_MUTEX_NAME)
