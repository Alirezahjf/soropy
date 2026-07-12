"""
Event bus and standard event names for the WebSocket backend.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from soropy.backends.base import BackendEvent, EventHandler
from soropy.utils import get_logger

logger = get_logger("soropy.ws.events")


class SplusEvent(str, Enum):
    """Canonical event names shared across the library."""

    # connection lifecycle
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"
    ERROR = "error"

    # auth
    AUTH_REQUIRED = "auth_required"
    AUTH_SUCCESS = "auth_success"
    AUTH_FAILED = "auth_failed"

    # messaging
    NEW_MESSAGE = "new_message"
    MESSAGE_SENT = "message_sent"
    MESSAGE_ACK = "message_ack"
    MESSAGE_READ = "message_read"
    TYPING = "typing"

    # chats / presence
    CHAT_UPDATED = "chat_updated"
    UNREAD_CHANGED = "unread_changed"
    USER_STATUS = "user_status"

    # raw escape hatch
    RAW_FRAME = "raw_frame"


@dataclass
class IncomingMessage:
    """Normalised inbound message used by handlers and auto-reply."""

    message_id: str
    chat_id: str
    chat_name: str
    text: str
    sender_id: str = ""
    sender_name: str = ""
    is_outgoing: bool = False
    is_private: bool = False
    is_group: bool = False
    is_channel: bool = False
    timestamp: float = 0.0
    reply_to_id: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_event_data(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "chat_id": self.chat_id,
            "chat_name": self.chat_name,
            "text": self.text,
            "sender_id": self.sender_id,
            "sender_name": self.sender_name,
            "is_outgoing": self.is_outgoing,
            "is_private": self.is_private,
            "is_group": self.is_group,
            "is_channel": self.is_channel,
            "timestamp": self.timestamp,
            "reply_to_id": self.reply_to_id,
        }


class EventBus:
    """
    Thread-safe pub/sub bus.

    Supports:
    * named handlers: ``bus.on("new_message", fn)``
    * wildcard: ``bus.on("*", fn)`` receives every event
    """

    def __init__(self) -> None:
        self._handlers: Dict[str, List[EventHandler]] = {}
        self._lock = threading.RLock()

    def on(self, event: str, handler: EventHandler) -> None:
        key = event.value if isinstance(event, SplusEvent) else str(event)
        with self._lock:
            self._handlers.setdefault(key, []).append(handler)
        logger.debug("Handler registered for '%s'", key)

    def off(self, event: str, handler: Optional[EventHandler] = None) -> None:
        key = event.value if isinstance(event, SplusEvent) else str(event)
        with self._lock:
            if key not in self._handlers:
                return
            if handler is None:
                self._handlers.pop(key, None)
            else:
                self._handlers[key] = [
                    h for h in self._handlers[key] if h is not handler
                ]

    def once(self, event: str, handler: EventHandler) -> None:
        """Register a handler that auto-removes after first call."""

        def _wrapper(ev: BackendEvent) -> None:
            self.off(event, _wrapper)
            handler(ev)

        self.on(event, _wrapper)

    def emit(self, event: str, data: Optional[Dict[str, Any]] = None) -> None:
        key = event.value if isinstance(event, SplusEvent) else str(event)
        payload = BackendEvent(name=key, data=data or {})
        with self._lock:
            specific = list(self._handlers.get(key, []))
            wildcards = list(self._handlers.get("*", []))
        for h in specific + wildcards:
            try:
                h(payload)
            except Exception as exc:  # never break the bus
                logger.error("Event handler error on '%s': %s", key, exc)

    def clear(self) -> None:
        with self._lock:
            self._handlers.clear()

    def listener_count(self, event: Optional[str] = None) -> int:
        with self._lock:
            if event is None:
                return sum(len(v) for v in self._handlers.values())
            key = event.value if isinstance(event, SplusEvent) else str(event)
            return len(self._handlers.get(key, []))
