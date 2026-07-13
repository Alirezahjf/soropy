"""
Message tracker – prevents duplicate replies.

Stores hashes of (chat_name, message_id) when an ID is available, with
(chat_name, message_text) as a compatibility fallback. Persists to JSON so
restarts do not cause duplicate replies.
"""

import json
import os
import time
import threading


from soropy.utils import hash_message, get_logger

logger = get_logger("soropy.tracker")


class MessageTracker:
    """
    Thread-safe tracker that remembers which messages have been
    answered.  Backed by an on-disk JSON file.
    """

    def __init__(self, db_path: str = "soropy_tracker.json", max_age: int = 86400):
        """
        Parameters
        ----------
        db_path : str
            Path to the JSON persistence file.
        max_age : int
            Seconds after which old entries are pruned (default 24 h).
        """
        self._db_path = os.path.abspath(db_path)
        self._max_age = max_age
        self._lock = threading.Lock()
        self._replied: dict = {}  # hash -> timestamp
        self._load()

    # ── public API ─────────────────────────────────────

    @staticmethod
    def _key(chat_name: str, text: str, message_id: str = "") -> str:
        identity = f"message-id:{message_id}" if message_id else text
        return hash_message(chat_name, identity)

    def is_replied(self, chat_name: str, text: str, message_id: str = "") -> bool:
        """Return True for this message ID, falling back to its text."""
        h = self._key(chat_name, text, str(message_id or ""))
        with self._lock:
            return h in self._replied

    def mark_replied(self, chat_name: str, text: str, message_id: str = "") -> None:
        """Record that a message was reserved/delivered."""
        h = self._key(chat_name, text, str(message_id or ""))
        with self._lock:
            self._replied[h] = time.time()
            self._save()

    def mark_batch_replied(self, chat_name: str, texts: list) -> None:
        """Mark several messages at once (single disk write)."""
        with self._lock:
            for text in texts:
                h = hash_message(chat_name, text)
                self._replied[h] = time.time()
            self._save()

    def unmark_replied(
        self, chat_name: str, text: str, message_id: str = ""
    ) -> bool:
        """Release a reservation after a real delivery failure."""
        h = self._key(chat_name, text, str(message_id or ""))
        with self._lock:
            existed = self._replied.pop(h, None) is not None
            if existed:
                self._save()
            return existed

    def prune(self) -> int:
        """Remove entries older than max_age.  Returns count removed."""
        cutoff = time.time() - self._max_age
        with self._lock:
            before = len(self._replied)
            self._replied = {
                h: ts for h, ts in self._replied.items() if ts > cutoff
            }
            removed = before - len(self._replied)
            if removed:
                self._save()
            return removed

    def clear(self) -> None:
        """Wipe all tracked messages."""
        with self._lock:
            self._replied.clear()
            self._save()

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._replied)

    # ── persistence ────────────────────────────────────

    def _load(self) -> None:
        if os.path.isfile(self._db_path):
            try:
                with open(self._db_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._replied = data
                    logger.debug(
                        "Loaded %d tracked messages from %s",
                        len(self._replied),
                        self._db_path,
                    )
            except Exception as e:
                logger.warning("Failed to load tracker DB: %s", e)
                self._replied = {}

    def _save(self) -> None:
        try:
            parent = os.path.dirname(self._db_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            tmp = self._db_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._replied, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self._db_path)
        except Exception as e:
            logger.warning("Failed to save tracker DB: %s", e)