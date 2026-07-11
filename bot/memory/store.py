"""
Memory Store — storage abstraction for Memory Engine V3.

FUTURE-READY DESIGN:
  The MemoryEngine uses only MemoryStore's interface.
  To migrate from JSON → PostgreSQL, implement MemoryStore
  and swap it in bot.py. No engine logic changes.

Implementations:
  JsonMemoryStore — stores data in a single JSON file (default)
"""

from __future__ import annotations

import json
import logging
import os
import threading
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

# Default file path relative to bot/ when running from bot/
DEFAULT_JSON_PATH = os.path.join(
    os.path.dirname(__file__), "..", "memory_store.json"
)


# ------------------------------------------------------------------ #
# ABSTRACT INTERFACE                                                   #
# ------------------------------------------------------------------ #

class MemoryStore(ABC):
    """
    Storage-agnostic interface for memory persistence.

    All methods operate at the user-level: one user → one list of
    raw memory dicts. The MemoryEngine converts between dicts and
    MemoryItem objects.

    Thread safety: current usage is single-user, single-process.
    """

    @abstractmethod
    def read(self, user_id: str) -> list[dict]:
        """Return all memory dicts for a user (or empty list)."""

    @abstractmethod
    def write(self, user_id: str, items: list[dict]) -> None:
        """Persist the full list of memory dicts for a user."""

    @abstractmethod
    def read_all(self) -> dict[str, list[dict]]:
        """Return all users' memory dicts (for export/backup)."""

    @abstractmethod
    def clear_user(self, user_id: str) -> None:
        """Hard-delete all memories for a user."""


# ------------------------------------------------------------------ #
# JSON IMPLEMENTATION                                                  #
# ------------------------------------------------------------------ #

class JsonMemoryStore(MemoryStore):
    """
    JSON file-based memory store.

    File format:
    {
      "<chat_id>": [
        { "id": "...", "category": "...", "key": "...", ... },
        ...
      ]
    }

    Write strategy: read the full file, update user's section, write back.
    Acceptable for single-user, low-frequency writes.
    """

    def __init__(self, path: str = DEFAULT_JSON_PATH):
        self._path = os.path.abspath(path)
        self._lock = threading.Lock()
        self._cache: dict[str, list[dict]] = self._load_file()

    # -- Public interface -- #

    def read(self, user_id: str) -> list[dict]:
        with self._lock:
            return list(self._cache.get(str(user_id), []))

    def write(self, user_id: str, items: list[dict]) -> None:
        with self._lock:
            self._cache[str(user_id)] = items
            self._flush()

    def read_all(self) -> dict[str, list[dict]]:
        with self._lock:
            return {uid: list(items) for uid, items in self._cache.items()}

    def clear_user(self, user_id: str) -> None:
        with self._lock:
            if str(user_id) in self._cache:
                del self._cache[str(user_id)]
                self._flush()

    # -- Private helpers -- #

    def _load_file(self) -> dict[str, list[dict]]:
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
                total = sum(len(v) for v in data.values())
                logger.info(f"Memory store loaded: {len(data)} users, {total} items from {self._path}")
                return data
        except FileNotFoundError:
            logger.info(f"Memory store not found at {self._path} — starting fresh.")
            return {}
        except json.JSONDecodeError as e:
            logger.error(f"Memory store corrupted: {e} — starting fresh.")
            return {}

    def _flush(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Memory store flush failed: {e}")
