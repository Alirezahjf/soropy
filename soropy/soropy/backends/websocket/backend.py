"""
WebSocket / MTProto backend for Soroush Plus.

Uses the real production transport:

    wss://im-server.splus.ir:443/apiws
    Origin: https://web.splus.ir
    Codec: obfuscated MTProto abridged (via SPlusthon)

High-level API matches :class:`BaseBackend` so ``SoroushClient`` stays
transport-agnostic.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List, Optional

from soropy.backends.base import (
    BaseBackend,
    BackendCapability,
    EventHandler,
)
from soropy.backends.websocket.events import EventBus, IncomingMessage, SplusEvent
from soropy.backends.websocket.mtproto_engine import MtprotoEngine, require_splusthon
from soropy.exceptions import LoginError, SoroPyError, TransportError
from soropy.types import (
    ChatCollection,
    LoginStatus,
    MessageInfo,
    SendResult,
    UnreadChat,
)
from soropy.utils import get_logger
from soropy import constants as C

logger = get_logger("soropy.backends.websocket")


class WebSocketBackend(BaseBackend):
    """
    Event-driven Soroush Plus client over MTProto/WebSocket.

    Parameters
    ----------
    phone : str
        Normalised phone (``+98…``).
    session_dir : str
        Directory for SQLite MTProto session files.
    """

    def __init__(
        self,
        phone: str,
        session_dir: str = "soropy_ws_sessions",
        # unused selenium kwargs accepted for factory compatibility
        headless: bool = False,
        tracker=None,
        chrome_binary: Optional[str] = None,
        chromedriver_path: Optional[str] = None,
        extra_chrome_args: Optional[list] = None,
        ws_url: Optional[str] = None,
        origin: Optional[str] = None,
        **_extra,
    ):
        self._phone = phone
        self._session_dir = session_dir
        self._bus = EventBus()
        self._engine: Optional[MtprotoEngine] = None
        self._logged_in = False
        self._lock = threading.RLock()

        self._chat_index: Dict[str, str] = {}  # name → id
        self._unread: Dict[str, int] = {}
        self._chats_cache: Optional[ChatCollection] = None

    # ── identity ───────────────────────────────────────

    @property
    def name(self) -> str:
        return "websocket"

    @property
    def is_connected(self) -> bool:
        return bool(
            self._logged_in
            and self._engine is not None
            and self._engine.is_connected
            and self._engine.is_authorized
        )

    def capabilities(self) -> frozenset:
        return frozenset(
            {
                BackendCapability.REALTIME_EVENTS,
                BackendCapability.HEADLESS,
                BackendCapability.MULTI_ACCOUNT,
                BackendCapability.CONTACTS,
                BackendCapability.CHANNELS,
                BackendCapability.AUTO_REPLY,
                BackendCapability.SESSION_PERSIST,
                BackendCapability.REPLY_TO_MESSAGE,
            }
        )

    @property
    def event_bus(self) -> EventBus:
        return self._bus

    @property
    def session_store(self):
        """Duck-type compatibility with older session API."""
        return _SessionFacade(self)

    # ── events ─────────────────────────────────────────

    def on(self, event: str, handler: EventHandler) -> None:
        self._bus.on(event, handler)

    def off(self, event: str, handler: Optional[EventHandler] = None) -> None:
        self._bus.off(event, handler)

    def emit(self, event: str, data: Optional[Dict[str, Any]] = None) -> None:
        self._bus.emit(event, data)

    # ── lifecycle ──────────────────────────────────────

    def login(
        self,
        phone: str,
        code_callback: Optional[Callable[[], str]] = None,
    ) -> LoginStatus:
        require_splusthon()
        self._phone = phone
        self._bus.emit(SplusEvent.CONNECTING.value, {"phone": phone})

        self._engine = MtprotoEngine(
            phone=phone,
            session_dir=self._session_dir,
            on_message=self._on_incoming,
        )

        try:
            self._engine.connect()
            self._bus.emit(SplusEvent.CONNECTED.value, {"phone": phone})
        except Exception as exc:
            self._bus.emit(SplusEvent.ERROR.value, {"error": str(exc)})
            # Clean up half-open engine
            try:
                self._engine.disconnect()
            except Exception:
                pass
            self._engine = None
            raise LoginError(
                f"MTProto connect failed: {exc}. "
                "Ensure network can reach im-server.splus.ir:443 "
                "(DNS/VPN/firewall) and splusthon is installed "
                "(pip install soropy[ws])."
            ) from exc

        try:
            if self._engine.is_authorized:
                self._logged_in = True
                self._bus.emit(
                    SplusEvent.AUTH_SUCCESS.value,
                    {"phone": phone, "status": "session_restored"},
                )
                return LoginStatus.SESSION_RESTORED

            result = self._engine.login(code_callback=code_callback)
            self._logged_in = True
            status = (
                LoginStatus.SESSION_RESTORED
                if result == "session_restored"
                else LoginStatus.SUCCESS
            )
            self._bus.emit(
                SplusEvent.AUTH_SUCCESS.value,
                {"phone": phone, "status": status.value},
            )
            return status
        except LoginError:
            self._bus.emit(SplusEvent.AUTH_FAILED.value, {"phone": phone})
            self.close()
            raise
        except Exception as exc:
            self._bus.emit(SplusEvent.ERROR.value, {"error": str(exc)})
            self.close()
            raise LoginError(str(exc)) from exc

    def close(self) -> None:
        self._logged_in = False
        if self._engine is not None:
            try:
                self._engine.disconnect()
            except Exception:
                pass
            self._engine = None
        self._bus.emit(SplusEvent.DISCONNECTED.value, {"phone": self._phone})
        logger.info("WebSocket/MTProto backend closed for %s", self._phone)

    # ── incoming messages ──────────────────────────────

    def _on_incoming(self, msg: IncomingMessage) -> None:
        if msg.chat_id and msg.chat_name:
            self._chat_index[msg.chat_name] = msg.chat_id
        if not msg.is_outgoing and msg.chat_name:
            self._unread[msg.chat_name] = self._unread.get(msg.chat_name, 0) + 1
            self._bus.emit(
                SplusEvent.UNREAD_CHANGED.value,
                {"chat_name": msg.chat_name, "count": self._unread[msg.chat_name]},
            )
        self._bus.emit(SplusEvent.NEW_MESSAGE.value, msg.to_event_data())

    # ── chats ──────────────────────────────────────────

    def get_chats(self) -> ChatCollection:
        self._ensure_ready()
        assert self._engine is not None
        dialogs = self._engine.get_dialogs(limit=200)
        collection = ChatCollection()
        for d in dialogs:
            name = d["name"]
            self._chat_index[name] = d["id"]
            collection.all.append(name)
            kind = d["type"]
            if kind == "channel":
                collection.channels.append(name)
            elif kind == "group":
                collection.groups.append(name)
            else:
                collection.personal.append(name)
            if d.get("unread"):
                self._unread[name] = int(d["unread"])
        self._chats_cache = collection
        self._bus.emit(
            SplusEvent.CHAT_UPDATED.value,
            {
                "all": list(collection.all),
                "personal": list(collection.personal),
                "groups": list(collection.groups),
                "channels": list(collection.channels),
            },
        )
        return collection

    def send_message(self, chat_name: str, message: str) -> SendResult:
        self._ensure_ready()
        assert self._engine is not None
        try:
            info = self._engine.send_message(chat_name, message)
            self._bus.emit(
                SplusEvent.MESSAGE_SENT.value,
                {
                    "chat_name": chat_name,
                    "text": message,
                    "id": info.get("id"),
                },
            )
            return SendResult(True, chat_name, message)
        except Exception as exc:
            return SendResult(False, chat_name, message, str(exc))

    def get_unread_personal_chats(self) -> List[UnreadChat]:
        # Prefer live unread from dialogs when possible
        if self._engine and self._logged_in:
            try:
                dialogs = self._engine.get_dialogs(limit=100)
                unread = []
                for d in dialogs:
                    if d["type"] == "personal" and d.get("unread", 0) > 0:
                        self._unread[d["name"]] = d["unread"]
                        unread.append(UnreadChat(name=d["name"], count=d["unread"]))
                if unread:
                    return unread
            except Exception as exc:
                logger.debug("refresh unread failed: %s", exc)
        return [
            UnreadChat(name=n, count=c)
            for n, c in self._unread.items()
            if c > 0
        ]

    def get_unread_messages(self, chat_name: str, count: int = 10) -> List[MessageInfo]:
        self._ensure_ready()
        assert self._engine is not None
        try:
            items = self._engine.get_messages(
                chat_name, limit=max(count, 10), incoming_only=True
            )
        except Exception as exc:
            logger.error("get_messages failed: %s", exc)
            return []
        messages: List[MessageInfo] = []
        for i, item in enumerate(items[-count:]):
            messages.append(
                MessageInfo(
                    text=item.get("text") or "",
                    element_index=i,
                    is_outgoing=False,
                    message_id=str(item.get("id") or ""),
                )
            )
        self._unread.pop(chat_name, None)
        try:
            self._engine.mark_read(chat_name)
        except Exception:
            pass
        return messages

    def reply_to_message(
        self,
        chat_name: str,
        message_id: str,
        reply_text: str,
        element_index: int = 0,
    ) -> SendResult:
        self._ensure_ready()
        assert self._engine is not None
        try:
            reply_to = int(message_id) if message_id and str(message_id).isdigit() else None
            self._engine.send_message(chat_name, reply_text, reply_to=reply_to)
            return SendResult(True, chat_name, reply_text)
        except Exception as exc:
            return SendResult(False, chat_name, reply_text, str(exc))

    # ── contacts ───────────────────────────────────────

    def get_contacts(self) -> List[str]:
        self._ensure_ready()
        assert self._engine is not None
        contacts = self._engine.get_contacts()
        return [c["name"] for c in contacts]

    def add_contact(self, phone: str, first_name: str, last_name: str = "") -> bool:
        self._ensure_ready()
        assert self._engine is not None
        return self._engine.add_contact(phone, first_name, last_name)

    def search_contacts(self, query: str) -> List[str]:
        q = query.strip().lower()
        return [n for n in self.get_contacts() if q in n.lower()]

    # ── channels ───────────────────────────────────────

    def send_to_channel(self, channel_url: str, message: str) -> bool:
        result = self.send_message(channel_url, message)
        return result.success

    # ── session helpers ────────────────────────────────

    def get_session_token(self) -> Optional[str]:
        if self._engine and self._engine.session_exists():
            return self._engine._session_path()
        return None

    def delete_session(self) -> bool:
        if self._engine:
            return self._engine.delete_session()
        # offline delete
        eng = MtprotoEngine(phone=self._phone, session_dir=self._session_dir)
        return eng.delete_session()

    def get_me(self) -> Optional[Dict[str, Any]]:
        if not self._engine:
            return None
        return self._engine.get_me()

    # ── guards ─────────────────────────────────────────

    def _ensure_ready(self) -> None:
        if not self._logged_in or self._engine is None:
            raise SoroPyError("Not logged in. Call login() first.")
        if not self._engine.is_connected:
            raise TransportError("MTProto transport is not connected")


class _SessionFacade:
    """Minimal façade so ``client.has_session`` works for WS backend."""

    def __init__(self, backend: WebSocketBackend):
        self._backend = backend

    def exists(self, phone: str) -> bool:
        eng = self._backend._engine
        if eng is not None:
            return eng.session_exists()
        try:
            tmp = MtprotoEngine(
                phone=phone,
                session_dir=self._backend._session_dir,
            )
            return tmp.session_exists()
        except Exception:
            return False
