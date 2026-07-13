"""
Persistent session (Chrome profile) management.

Each phone number gets its own Chrome user-data-dir so
cookies and local storage persist between runs.
"""

import os
from typing import Optional

from soropy.utils import get_logger

logger = get_logger("soropy.session")


class SessionManager:
    """Manages Chrome profile directories for persistent login."""

    def __init__(self, base_dir: str = "soropy_sessions"):
        self._base_dir = os.path.abspath(base_dir)
        os.makedirs(self._base_dir, exist_ok=True)

    @property
    def base_dir(self) -> str:
        return self._base_dir

    def get_path(self, phone: str) -> str:
        """Return the profile directory for *phone*."""
        safe = phone.replace("+", "plus_").replace(" ", "")
        path = os.path.join(self._base_dir, safe)
        os.makedirs(path, exist_ok=True)
        return path

    def exists(self, phone: str) -> bool:
        """True if a non-empty profile directory exists."""
        path = self.get_path(phone)
        return os.path.isdir(path) and bool(os.listdir(path))

    def delete(self, phone: str) -> bool:
        """Delete a stored session."""
        import shutil
        path = self.get_path(phone)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
            logger.info("Session deleted for %s", phone)
            return True
        return False

    def list_sessions(self) -> list:
        """List all phone numbers with stored sessions."""
        sessions = []
        if not os.path.isdir(self._base_dir):
            return sessions
        for name in os.listdir(self._base_dir):
            full = os.path.join(self._base_dir, name)
            if os.path.isdir(full) and os.listdir(full):
                phone = name.replace("plus_", "+")
                sessions.append(phone)
        return sessions