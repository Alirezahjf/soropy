"""
Persistent storage for WebSocket auth credentials.

Unlike Selenium (which reuses a Chrome profile directory), the WS backend
stores lightweight JSON credentials per phone number.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from soropy.utils import get_logger

logger = get_logger("soropy.ws.session")


@dataclass
class WsCredentials:
    """
    Auth material needed to open an authenticated WebSocket.

    Fields marked *observed* should be filled after reverse-engineering
    the real ``web.splus.ir`` handshake.
    """

    phone: str
    # TODO(protocol): map these to real token names from Network → WS / cookies
    access_token: str = ""
    refresh_token: str = ""
    user_id: str = ""
    device_id: str = ""
    session_id: str = ""
    # Extra opaque fields captured from the web client
    extra: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def is_valid(self) -> bool:
        """Heuristic: at least one auth field present."""
        return bool(self.access_token or self.session_id or self.extra)

    def touch(self) -> None:
        self.updated_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WsCredentials":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


class WsSessionStore:
    """
    File-backed credential store.

    Layout::

        <base_dir>/
            plus_98912...json
            plus_98918...json
    """

    def __init__(self, base_dir: str = "soropy_ws_sessions"):
        self._base_dir = os.path.abspath(base_dir)
        os.makedirs(self._base_dir, exist_ok=True)
        self._lock = threading.RLock()

    @property
    def base_dir(self) -> str:
        return self._base_dir

    def _path(self, phone: str) -> str:
        safe = phone.replace("+", "plus_").replace(" ", "")
        return os.path.join(self._base_dir, f"{safe}.json")

    def exists(self, phone: str) -> bool:
        path = self._path(phone)
        if not os.path.isfile(path):
            return False
        creds = self.load(phone)
        return bool(creds and creds.is_valid())

    def load(self, phone: str) -> Optional[WsCredentials]:
        path = self._path(phone)
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return WsCredentials.from_dict(data)
        except Exception as exc:
            logger.warning("Failed to load WS session for %s: %s", phone, exc)
            return None

    def save(self, creds: WsCredentials) -> None:
        path = self._path(creds.phone)
        creds.touch()
        with self._lock:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(creds.to_dict(), f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        logger.info("WS session saved for %s", creds.phone)

    def delete(self, phone: str) -> bool:
        path = self._path(phone)
        if os.path.isfile(path):
            os.remove(path)
            logger.info("WS session deleted for %s", phone)
            return True
        return False

    def list_sessions(self) -> List[str]:
        phones: List[str] = []
        if not os.path.isdir(self._base_dir):
            return phones
        for name in os.listdir(self._base_dir):
            if name.endswith(".json") and not name.endswith(".tmp"):
                phone = name[:-5].replace("plus_", "+")
                phones.append(phone)
        return phones
