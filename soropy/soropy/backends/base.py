"""
Abstract backend contract.

Every transport (Selenium, WebSocket, future gRPC, …) implements
``BaseBackend`` so ``SoroushClient`` stays transport-agnostic.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional

from soropy.types import (
    ChatCollection,
    LoginStatus,
    MessageInfo,
    SendResult,
    UnreadChat,
)


class BackendCapability(Enum):
    """Features a backend may or may not support."""

    REALTIME_EVENTS = auto()   # push new_message / typing / …
    HEADLESS = auto()          # no visible UI
    MULTI_ACCOUNT = auto()
    CONTACTS = auto()
    CHANNELS = auto()
    AUTO_REPLY = auto()
    SESSION_PERSIST = auto()
    REPLY_TO_MESSAGE = auto()


@dataclass
class BackendEvent:
    """
    Normalised event emitted by any backend.

    Attributes
    ----------
    name : str
        Event name, e.g. ``"new_message"``, ``"connection"``, ``"error"``.
    data : dict
        Payload (backend-specific keys, always JSON-serialisable when possible).
    """

    name: str
    data: Dict[str, Any] = field(default_factory=dict)


# Type alias for event listeners
EventHandler = Callable[[BackendEvent], None]


class BaseBackend(abc.ABC):
    """
    Transport-agnostic interface used by :class:`soropy.client.SoroushClient`.

    Implementations must be **thread-safe** for concurrent
    ``send_*`` / event-dispatch calls where possible.
    """

    # ── identity / lifecycle ───────────────────────────

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Short backend id: ``\"selenium\"`` or ``\"websocket\"``."""

    @property
    @abc.abstractmethod
    def is_connected(self) -> bool:
        """True when the transport is ready for messaging."""

    @property
    def is_logged_in(self) -> bool:
        return self.is_connected

    @abc.abstractmethod
    def capabilities(self) -> frozenset:
        """Set of :class:`BackendCapability` values this backend supports."""

    def supports(self, cap: BackendCapability) -> bool:
        return cap in self.capabilities()

    @abc.abstractmethod
    def login(
        self,
        phone: str,
        code_callback: Optional[Callable[[], str]] = None,
    ) -> LoginStatus:
        """Authenticate and open a ready session."""

    @abc.abstractmethod
    def close(self) -> None:
        """Tear down transport and release resources."""

    # ── chats ──────────────────────────────────────────

    @abc.abstractmethod
    def get_chats(self) -> ChatCollection:
        """Return categorised chat lists."""

    @abc.abstractmethod
    def send_message(self, chat_name: str, message: str) -> SendResult:
        """Send a text message to *chat_name* (display name or peer id)."""

    def send_bulk_messages(
        self,
        chat_names: List[str],
        message: str,
        delay: float = 3.0,
    ) -> List[SendResult]:
        """Default sequential bulk send; backends may override."""
        import time

        results: List[SendResult] = []
        for i, name in enumerate(chat_names):
            results.append(self.send_message(name, message))
            if delay and i < len(chat_names) - 1:
                time.sleep(delay)
        return results

    # ── unread / history ───────────────────────────────

    def get_unread_personal_chats(self, max_chats: int = 50) -> List[UnreadChat]:
        """Chats that currently have unread messages (personal only preferred)."""
        return []

    def get_unread_messages(self, chat_name: str, count: int = 10) -> List[MessageInfo]:
        """Last *count* incoming messages in *chat_name*."""
        return []

    def reply_to_message(
        self,
        chat_name: str,
        message_id: str,
        reply_text: str,
        element_index: int = 0,
    ) -> SendResult:
        """
        Reply to a specific message.

        Selenium uses *element_index*; WebSocket prefers *message_id*.
        Default falls back to a plain send.
        """
        return self.send_message(chat_name, reply_text)

    # ── contacts ───────────────────────────────────────

    def get_contacts(self) -> List[str]:
        return []

    def add_contact(self, phone: str, first_name: str, last_name: str = "") -> bool:
        return False

    def search_contacts(self, query: str) -> List[str]:
        return []

    # ── channels ───────────────────────────────────────

    def send_to_channel(self, channel_url: str, message: str) -> bool:
        return False

    # ── saved messages ─────────────────────────────────

    def go_to_saved_messages(self) -> bool:
        return False

    # ── events (realtime backends) ─────────────────────

    def on(self, event: str, handler: EventHandler) -> None:
        """Register an event handler. No-op if backend has no event bus."""

    def off(self, event: str, handler: Optional[EventHandler] = None) -> None:
        """Unregister handler(s)."""

    def emit(self, event: str, data: Optional[Dict[str, Any]] = None) -> None:
        """Manually fire an event (mostly for tests)."""

    # ── optional raw access ────────────────────────────

    def get_raw_driver(self) -> Any:
        """Selenium WebDriver if available; else ``None``."""
        return None

    def get_session_token(self) -> Optional[str]:
        """WebSocket / API session token if available."""
        return None
