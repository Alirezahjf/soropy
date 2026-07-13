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
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

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

# Soft-skip tokens for poll/auto-reply (don't flood logs)
_SOFT_SKIP_TOKENS = (
    "CHAT_ADMIN_REQUIRED",
    "CHAT_WRITE_FORBIDDEN",
    "CHAT_SEND",
    "USER_BANNED_IN_CHANNEL",
    "CHANNEL_PRIVATE",
    "CHAT_RESTRICTED",
    "RIGHT_FORBIDDEN",
    "ADMIN PRIVILEGES",
)


def _is_soft_skip(err: str) -> bool:
    upper = (err or "").upper()
    return any(t in upper for t in _SOFT_SKIP_TOKENS)


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
        self._ws_url = ws_url or C.WS_URL
        self._origin = origin or C.WS_ORIGIN
        if self._ws_url != C.WS_URL or self._origin != C.WS_ORIGIN:
            logger.warning(
                "SPlusthon currently controls endpoint/origin; custom ws_url/origin "
                "cannot be applied and the official Soroush endpoint will be used."
            )
        self._bus = EventBus()
        self._engine: Optional[MtprotoEngine] = None
        self._logged_in = False
        self._lock = threading.RLock()

        self._chat_index: Dict[str, str] = {}  # name → id
        self._chat_kinds: Dict[str, str] = {}  # name → personal|group|channel
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

    @property
    def engine(self) -> Optional[MtprotoEngine]:
        return self._engine

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
        if self._engine is not None:
            # Re-login on the same object must not leak its old loop/socket or
            # discard event subscriptions.
            try:
                self._engine.disconnect()
            finally:
                self._engine = None
                self._logged_in = False
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
        was_active = self._logged_in or self._engine is not None
        self._logged_in = False
        if self._engine is not None:
            try:
                self._engine.disconnect()
            except Exception as exc:
                logger.debug("engine disconnect: %s", exc)
            self._engine = None
        if was_active:
            self._bus.emit(SplusEvent.DISCONNECTED.value, {"phone": self._phone})
            logger.info("WebSocket/MTProto backend closed for %s", self._phone)
        self._bus.close()

    # ── incoming messages ──────────────────────────────

    def _on_incoming(self, msg: IncomingMessage) -> None:
        unread_count: Optional[int] = None
        with self._lock:
            if msg.chat_id and msg.chat_name:
                self._chat_index[msg.chat_name] = msg.chat_id
            kind = (
                "personal"
                if msg.is_private
                else "channel"
                if msg.is_channel
                else "group"
                if msg.is_group
                else self._chat_kinds.get(msg.chat_name, "personal")
            )
            if msg.chat_name:
                self._chat_kinds[msg.chat_name] = kind
            if not msg.is_outgoing and msg.chat_name and msg.is_private:
                unread_count = self._unread.get(msg.chat_name, 0) + 1
                self._unread[msg.chat_name] = unread_count

        if unread_count is not None:
            self._bus.emit_async(
                SplusEvent.UNREAD_CHANGED.value,
                {"chat_name": msg.chat_name, "count": unread_count},
            )
        # Never execute user callbacks on SPlusthon's receive/ping event loop.
        self._bus.emit_async(SplusEvent.NEW_MESSAGE.value, msg.to_event_data())

    # ── chats ──────────────────────────────────────────

    def get_chats(self) -> ChatCollection:
        self._ensure_ready()
        assert self._engine is not None
        dialogs = self._engine.get_dialogs(limit=200)
        collection = ChatCollection()
        for d in dialogs:
            name = d["name"]
            self._chat_index[name] = d["id"]
            kind = d["type"]
            self._chat_kinds[name] = kind
            collection.all.append(name)
            if kind == "channel":
                collection.channels.append(name)
            elif kind == "group":
                collection.groups.append(name)
            else:
                collection.personal.append(name)
            if d.get("unread") and kind == "personal":
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
            err = str(exc)
            if _is_soft_skip(err):
                logger.debug("send soft-skip %s: %s", chat_name, err)
            return SendResult(False, chat_name, message, err)

    def schedule_send(
        self,
        chat_name: str,
        message: str,
        reply_to: Optional[int] = None,
        on_done: Optional[Callable[[bool, str], None]] = None,
    ) -> None:
        """Non-blocking send for realtime auto-reply."""
        self._ensure_ready()
        assert self._engine is not None
        self._engine.schedule_send(
            chat_name, message, reply_to=reply_to, on_done=on_done
        )

    def get_unread_personal_chats(self, max_chats: int = 5) -> List[UnreadChat]:
        """Return at most *max_chats* server-confirmed personal unread dialogs."""
        if self._engine and self._logged_in:
            try:
                dialogs = self._engine.get_dialogs(limit=100)
                unread: List[UnreadChat] = []
                fresh_counts: Dict[str, int] = {}
                with self._lock:
                    for dialog in dialogs:
                        name = dialog["name"]
                        kind = dialog.get("type") or "personal"
                        self._chat_kinds[name] = kind
                        count = int(dialog.get("unread", 0) or 0)
                        if kind == "personal" and count > 0:
                            fresh_counts[name] = count
                            if len(unread) < max(0, int(max_chats)):
                                unread.append(UnreadChat(name=name, count=count))
                    # A successful refresh is authoritative: discard stale
                    # in-memory counters so old history is never auto-replied.
                    self._unread = fresh_counts
                return unread
            except Exception as exc:
                logger.debug("refresh unread failed; using realtime counters: %s", exc)

        with self._lock:
            snapshot = list(self._unread.items())
            kinds = dict(self._chat_kinds)
        result = []
        for name, count in snapshot:
            if count > 0 and kinds.get(name, "personal") == "personal":
                result.append(UnreadChat(name=name, count=count))
                if len(result) >= max_chats:
                    break
        return result

    def get_unread_messages(self, chat_name: str, count: int = 10) -> List[MessageInfo]:
        self._ensure_ready()
        assert self._engine is not None
        # Guard: never pull history for non-personal during auto-reply poll
        kind = self._chat_kinds.get(chat_name) or self._engine.chat_kind(chat_name)
        if kind and kind != "personal":
            logger.debug("skip non-personal unread pull: %s (%s)", chat_name, kind)
            with self._lock:
                self._unread.pop(chat_name, None)
            return []
        try:
            items = self._engine.get_messages(
                chat_name, limit=max(count, 10), incoming_only=True
            )
        except Exception as exc:
            err = str(exc)
            if _is_soft_skip(err):
                logger.debug("get_messages soft-skip %s: %s", chat_name, err)
            else:
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
        with self._lock:
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
            reply_to = (
                int(message_id) if message_id and str(message_id).isdigit() else None
            )
            self._engine.send_message(chat_name, reply_text, reply_to=reply_to)
            return SendResult(True, chat_name, reply_text)
        except Exception as exc:
            err = str(exc)
            if _is_soft_skip(err):
                logger.debug("reply soft-skip %s: %s", chat_name, err)
            return SendResult(False, chat_name, reply_text, err)

    def schedule_reply(
        self,
        chat_name: str,
        message_id: str,
        reply_text: str,
        on_done: Optional[Callable[[bool, str], None]] = None,
    ) -> None:
        reply_to = (
            int(message_id) if message_id and str(message_id).isdigit() else None
        )
        self.schedule_send(
            chat_name, reply_text, reply_to=reply_to, on_done=on_done
        )

    # ── media / message tools ──────────────────────────

    def send_file(
        self,
        chat_name: str,
        path: str,
        caption: str = "",
        force_document: bool = False,
        reply_to: Union[str, int, None] = None,
    ) -> SendResult:
        self._ensure_ready()
        assert self._engine is not None
        try:
            rt = int(reply_to) if reply_to not in (None, "") else None
            self._engine.send_file(
                chat_name,
                path,
                caption=caption,
                force_document=force_document,
                reply_to=rt,
            )
            return SendResult(True, chat_name, caption or path)
        except Exception as exc:
            return SendResult(False, chat_name, caption or path, str(exc))

    def download_media(
        self,
        chat_name: str,
        message_id: Union[str, int],
        file_path: Optional[str] = None,
    ) -> Optional[str]:
        self._ensure_ready()
        assert self._engine is not None
        return self._engine.download_media(chat_name, message_id, file_path)

    def delete_messages(
        self,
        chat_name: str,
        message_ids: Sequence[Union[str, int]],
        revoke: bool = True,
    ) -> bool:
        self._ensure_ready()
        assert self._engine is not None
        return self._engine.delete_messages(chat_name, message_ids, revoke=revoke)

    def edit_message(
        self, chat_name: str, message_id: Union[str, int], text: str
    ) -> bool:
        self._ensure_ready()
        assert self._engine is not None
        return self._engine.edit_message(chat_name, message_id, text)

    def pin_message(
        self,
        chat_name: str,
        message_id: Union[str, int],
        notify: bool = False,
    ) -> bool:
        self._ensure_ready()
        assert self._engine is not None
        return self._engine.pin_message(chat_name, message_id, notify=notify)

    def unpin_message(
        self,
        chat_name: str,
        message_id: Optional[Union[str, int]] = None,
    ) -> bool:
        self._ensure_ready()
        assert self._engine is not None
        return self._engine.unpin_message(chat_name, message_id)

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
        self._ensure_ready()
        assert self._engine is not None
        return [item["name"] for item in self._engine.search_contacts(query)]

    def block_user(self, user: str) -> bool:
        self._ensure_ready()
        assert self._engine is not None
        return self._engine.block_user(user)

    def unblock_user(self, user: str) -> bool:
        self._ensure_ready()
        assert self._engine is not None
        return self._engine.unblock_user(user)

    def report(
        self, entity: str, reason: str = "spam", message: str = ""
    ) -> bool:
        self._ensure_ready()
        assert self._engine is not None
        return self._engine.report(entity, reason=reason, message=message)

    # ── moderation ─────────────────────────────────────

    def kick(self, chat: str, user: str) -> bool:
        self._ensure_ready()
        assert self._engine is not None
        return self._engine.kick(chat, user)

    def ban(self, chat: str, user: str, **kwargs) -> bool:
        self._ensure_ready()
        assert self._engine is not None
        return self._engine.ban(chat, user, **kwargs)

    def unban(self, chat: str, user: str) -> bool:
        self._ensure_ready()
        assert self._engine is not None
        return self._engine.unban(chat, user)

    def set_permissions(
        self, chat: str, user: Optional[str] = None, **rights
    ) -> bool:
        self._ensure_ready()
        assert self._engine is not None
        return self._engine.set_permissions(chat, user=user, **rights)

    def promote(self, chat: str, user: str, **admin_rights) -> bool:
        self._ensure_ready()
        assert self._engine is not None
        return self._engine.promote(chat, user, **admin_rights)

    def get_participants(self, chat: str, limit: int = 100) -> List[Dict[str, Any]]:
        self._ensure_ready()
        assert self._engine is not None
        return self._engine.get_participants(chat, limit=limit)

    def get_permissions(
        self, chat: str, user: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        self._ensure_ready()
        assert self._engine is not None
        return self._engine.get_permissions(chat, user=user)

    # ── channels / groups ──────────────────────────────

    def send_to_channel(self, channel_url: str, message: str) -> bool:
        result = self.send_message(channel_url, message)
        return result.success

    def send_to_group(self, group: str, message: str) -> SendResult:
        return self.send_message(group, message)

    # ── session helpers ────────────────────────────────

    def get_session_token(self) -> Optional[str]:
        if self._engine and self._engine.session_exists():
            return self._engine._session_path()
        return None

    def delete_session(self) -> bool:
        if self._engine:
            engine = self._engine
            engine.disconnect()
            self._logged_in = False
            self._engine = None
            return engine.delete_session()
        eng = MtprotoEngine(phone=self._phone, session_dir=self._session_dir)
        return eng.delete_session()

    def get_me(self) -> Optional[Dict[str, Any]]:
        if not self._engine:
            return None
        return self._engine.get_me()

    def chat_kind(self, name: str) -> Optional[str]:
        return self._chat_kinds.get(name) or (
            self._engine.chat_kind(name) if self._engine else None
        )

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
