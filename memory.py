"""Conversation memory manager for Jarvis.

This module keeps short-term chat history for model context and persists
that history to disk so conversations survive restarts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from config import CONVERSATION_HISTORY_LIMIT


class ConversationMemory:
    """Store, trim, and persist conversational exchanges."""

    def __init__(self) -> None:
        """Initialize history storage and load previous session state."""
        self._messages: List[Dict[str, str]] = []
        self._storage_path = Path(__file__).resolve().parent / "data" / "session_history.json"
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_from_disk()

    def add_user(self, text: str) -> None:
        """Append a user message and persist updated history."""
        self._messages.append({"role": "user", "content": text})
        self._trim_in_place()
        self._persist()

    def add_assistant(self, text: str) -> None:
        """Append an assistant message and persist updated history."""
        self._messages.append({"role": "assistant", "content": text})
        self._trim_in_place()
        self._persist()

    def get_history(self) -> List[Dict[str, str]]:
        """Return the most recent message pairs up to configured limits."""
        max_messages = CONVERSATION_HISTORY_LIMIT * 2
        return self._messages[-max_messages:]

    def clear(self) -> None:
        """Reset memory in RAM and on disk for a fresh context window."""
        self._messages.clear()
        self._persist()

    def _trim_in_place(self) -> None:
        """Trim internal message buffer to avoid unbounded memory growth."""
        max_messages = CONVERSATION_HISTORY_LIMIT * 2
        if len(self._messages) > max_messages:
            self._messages = self._messages[-max_messages:]

    def _load_from_disk(self) -> None:
        """Load history from disk if available and structurally valid."""
        if not self._storage_path.exists():
            return

        try:
            payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                return

            cleaned: List[Dict[str, str]] = []
            for row in payload:
                if not isinstance(row, dict):
                    continue
                role = str(row.get("role", "")).strip()
                content = str(row.get("content", "")).strip()
                if role not in {"user", "assistant"} or not content:
                    continue
                cleaned.append({"role": role, "content": content})

            self._messages = cleaned
            self._trim_in_place()
        except Exception as exc:
            print(f"[ERROR] Failed to load memory from disk: {exc}")

    def _persist(self) -> None:
        """Persist the in-memory history to disk safely."""
        try:
            self._storage_path.write_text(
                json.dumps(self._messages, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            print(f"[ERROR] Failed to persist memory to disk: {exc}")
