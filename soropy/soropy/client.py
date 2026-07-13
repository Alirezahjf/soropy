"""
SoroushClient – the main high-level API.

Transport-agnostic façade over Selenium or WebSocket backends.
Users interact with this class; backends are an implementation detail.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from soropy import constants as C
from soropy.auto_reply import AutoReplyEngine
from soropy.backends import create_backend
from soropy.backends.base import BaseBackend, BackendCapability, BackendEvent
from soropy.exceptions import LoginError, SoroPyError
from soropy.message_tracker import MessageTracker
from soropy.session import SessionManager
from soropy.types import (
    ChatCollection,
    LoginStatus,
    SendResult,
)
from soropy.utils import get_logger, validate_phone

logger = get_logger("soropy.client")

# Soft-skip admin/permission errors during poll
_SOFT_SKIP = (
    "CHAT_ADMIN_REQUIRED",
    "CHAT_WRITE_FORBIDDEN",
    "CHAT_SEND",
    "USER_BANNED_IN_CHANNEL",
    "CHANNEL_PRIVATE",
    "CHAT_RESTRICTED",
    "RIGHT_FORBIDDEN",
    "ADMIN PRIVILEGES",
)

# Recommended minimum poll interval for WebSocket safety-net
WS_MIN_MONITOR_INTERVAL = 120
# Max personal chats processed per poll cycle on WS
WS_MAX_UNREAD_PER_CYCLE = 5


def _is_soft_skip_error(err: str) -> bool:
    upper = (err or "").upper()
    return any(t in upper for t in _SOFT_SKIP)


class SoroushClient:
    """
    High-level Soroush Plus client.

    Parameters
    ----------
    phone : str
        Phone number in any Iranian format.
    backend : str
        ``\"selenium\"`` (default) – Chrome DOM automation.
        ``\"websocket\"`` / ``\"ws\"`` – direct protocol client (event-driven).
    headless : bool
        Selenium only: run Chrome without a visible window.
    session_dir : str
        Directory for persistent sessions
        (Chrome profiles for selenium, SQLite for websocket).
    tracker_path : str or None
        Path to the message-tracker JSON file.
    log_file : str or None
        Optional log file path.
    auto_reply_private_only : bool
        When True (default), realtime + poll auto-reply only targets
        private/personal chats – never groups or channels.
    chrome_binary / chromedriver_path / extra_chrome_args
        Selenium-only options.
    ws_url / origin
        Reserved WebSocket settings. Current SPlusthon transport uses the
        official endpoint/origin and logs when custom values cannot be applied.

    Example
    -------
    >>> client = SoroushClient("+989123456789", backend="selenium")
    >>> client.login()
    >>> client.send_message("علی", "سلام!")
    >>> client.close()

    >>> # Realtime (WebSocket backend)
    >>> client = SoroushClient("0912...", backend="websocket")
    >>> client.on("new_message", lambda e: print(e.data))
    >>> client.login()
    """

    def __init__(
        self,
        phone: str,
        backend: str = "selenium",
        headless: bool = False,
        session_dir: Optional[str] = None,
        tracker_path: Optional[str] = None,
        log_file: Optional[str] = None,
        chrome_binary: Optional[str] = None,
        chromedriver_path: Optional[str] = None,
        extra_chrome_args: Optional[list] = None,
        ws_url: Optional[str] = None,
        origin: Optional[str] = None,
        auto_reply_private_only: bool = True,
        **backend_kwargs,
    ):
        # Soft normalise for construction; hard validate at login()
        self._phone_raw = str(phone or "").strip()
        try:
            self._phone = validate_phone(phone)
            self._phone_invalid_hint = False
        except ValueError:
            # Keep original raw string so login() can re-validate with a clear error
            # (do NOT strip placeholders like 0912xxxxxxx into a short +98912).
            self._phone = self._phone_raw
            self._phone_invalid_hint = True

        self._backend_name = (backend or "selenium").strip().lower()
        self._headless = headless
        self._log_file = log_file
        self.auto_reply_private_only = auto_reply_private_only
        self.auto_reply_enabled = True

        if log_file:
            from soropy.utils import get_logger as _gl
            _gl(f"soropy.{self._phone}", log_file)

        if session_dir is None:
            if self._backend_name in ("websocket", "ws", "splus", "protocol"):
                session_dir = C.DEFAULT_WS_SESSIONS_DIR
            else:
                session_dir = C.DEFAULT_SESSIONS_DIR
        self._session_dir = session_dir

        self._session_mgr = SessionManager(session_dir)

        if tracker_path is None:
            safe = self._phone.replace("+", "plus_")
            tracker_path = f"{session_dir}/{safe}_tracker.json"
        self._tracker = MessageTracker(db_path=tracker_path)

        self._backend: BaseBackend = create_backend(
            self._backend_name,
            phone=self._phone,
            headless=headless,
            session_dir=session_dir,
            tracker=self._tracker,
            chrome_binary=chrome_binary,
            chromedriver_path=chromedriver_path,
            extra_chrome_args=extra_chrome_args,
            ws_url=ws_url,
            origin=origin,
            **backend_kwargs,
        )

        self._auto_reply: Optional[AutoReplyEngine] = None
        self._chats_cache: Optional[ChatCollection] = None
        self._is_logged_in = False
        self._monitor_stop = threading.Event()
        self._event_handlers: Dict[str, list] = {}
        self._realtime_reply_lock = threading.Lock()

        # Wire realtime auto-reply when backend supports events
        if self._backend.supports(BackendCapability.REALTIME_EVENTS):
            self._backend.on("new_message", self._on_backend_new_message)

    # ════════════════════════════════════════════════════
    #  Properties
    # ════════════════════════════════════════════════════

    @property
    def phone(self) -> str:
        return self._phone

    @property
    def backend_name(self) -> str:
        return self._backend.name

    @property
    def backend(self) -> BaseBackend:
        """Access the underlying transport backend."""
        return self._backend

    @property
    def is_logged_in(self) -> bool:
        return self._is_logged_in and self._backend.is_logged_in

    @property
    def auto_reply_engine(self) -> AutoReplyEngine:
        """Access the auto-reply engine to add/remove rules."""
        if self._auto_reply is None:
            self._auto_reply = AutoReplyEngine(tracker=self._tracker)
        return self._auto_reply

    @property
    def tracker(self) -> MessageTracker:
        return self._tracker

    @property
    def cached_chats(self) -> Optional[ChatCollection]:
        return self._chats_cache

    # ════════════════════════════════════════════════════
    #  Event API (works best with websocket backend)
    # ════════════════════════════════════════════════════

    def on(self, event: str, handler: Callable) -> None:
        """
        Subscribe to a backend event.

        Common events (WebSocket backend):
            ``new_message``, ``message_sent``, ``connected``,
            ``disconnected``, ``error``, ``auth_success``.

        Handler signature: ``handler(event: BackendEvent) -> None``
        where ``event.data`` is a dict payload.
        """
        self._event_handlers.setdefault(event, []).append(handler)
        self._backend.on(event, handler)

    def off(self, event: str, handler: Optional[Callable] = None) -> None:
        """Unsubscribe from an event."""
        if handler is None:
            self._event_handlers.pop(event, None)
        else:
            lst = self._event_handlers.get(event, [])
            self._event_handlers[event] = [h for h in lst if h is not handler]
        self._backend.off(event, handler)

    def _on_backend_new_message(self, event: BackendEvent) -> None:
        """
        Realtime auto-reply hook for WebSocket backend.

        * Only private chats by default (``auto_reply_private_only``).
        * Sends via async schedule so the event loop is never blocked.
        * Soft-skips CHAT_ADMIN_REQUIRED etc.
        """
        if not self.auto_reply_enabled:
            return
        if self._auto_reply is None or not self._auto_reply.has_rules():
            return
        data = event.data or {}
        if data.get("is_outgoing"):
            return

        is_private = data.get("is_private")
        is_group = data.get("is_group")
        is_channel = data.get("is_channel")

        if self.auto_reply_private_only:
            # Prefer explicit flag; if missing, refuse group/channel
            if is_private is False or is_group or is_channel:
                return
            if is_private is not True:
                # Unknown events are denied by default; only an explicit cached
                # personal classification may opt them into auto-reply.
                chat_name_probe = (
                    data.get("chat_name")
                    or data.get("sender_name")
                    or data.get("chat_id")
                    or ""
                )
                kind = None
                if hasattr(self._backend, "chat_kind"):
                    try:
                        kind = self._backend.chat_kind(chat_name_probe)  # type: ignore
                    except Exception:
                        kind = None
                if kind != "personal":
                    return

        text = (data.get("text") or "").strip()
        chat_name = (
            data.get("chat_name")
            or data.get("sender_name")
            or data.get("chat_id")
            or ""
        )
        if not text or not chat_name:
            return

        msg_id = str(data.get("message_id") or "")
        # Selection + reservation must be atomic because EventBus may process
        # several incoming messages concurrently.
        reply_lock = getattr(self, "_realtime_reply_lock", None)
        if reply_lock is None:  # compatibility for manually constructed clients
            reply_lock = self._realtime_reply_lock = threading.Lock()
        with reply_lock:
            reply = self._auto_reply.get_reply(
                text, chat_name, 1, message_id=msg_id
            )
            if reply is None:
                return
            # Reserve before queueing. This closes the realtime-vs-poll race
            # even if delivery takes several seconds.
            self._auto_reply.mark_replied(chat_name, text, message_id=msg_id)

        logger.info("Realtime auto-reply queued → %s: %s", chat_name, reply[:40])

        def _deliver() -> None:
            try:
                result = self._backend.reply_to_message(chat_name, msg_id, reply)
                if result.success:
                    logger.info(
                        "Realtime auto-reply delivered → %s: %s",
                        chat_name,
                        reply[:40],
                    )
                elif result.error and _is_soft_skip_error(result.error):
                    logger.debug(
                        "Realtime auto-reply soft-skip %s: %s",
                        chat_name,
                        result.error,
                    )
                else:
                    self._auto_reply.unmark_replied(chat_name, text, message_id=msg_id)
                    logger.warning(
                        "Realtime auto-reply failed → %s: %s",
                        chat_name,
                        result.error or "send failed",
                    )
            except Exception as exc:
                if _is_soft_skip_error(str(exc)):
                    logger.debug("Realtime auto-reply soft-skip %s: %s", chat_name, exc)
                else:
                    self._auto_reply.unmark_replied(chat_name, text, message_id=msg_id)
                    logger.warning("Realtime auto-reply failed → %s: %s", chat_name, exc)

        try:
            # Crucially, LoopRunner.run() is called by this daemon worker, not
            # by SPlusthon's asyncio receive thread.
            threading.Thread(
                target=_deliver,
                daemon=True,
                name=f"soropy-reply-{msg_id or 'message'}",
            ).start()
        except Exception as exc:
            logger.debug("auto-reply worker unavailable, using async fallback: %s", exc)
            if hasattr(self._backend, "schedule_reply"):
                try:
                    self._backend.schedule_reply(  # type: ignore[attr-defined]
                        chat_name,
                        msg_id,
                        reply,
                        on_done=lambda ok, err: logger.info(
                            "Realtime auto-reply delivered → %s: %s", chat_name, reply[:40]
                        ) if ok else logger.warning(
                            "Realtime auto-reply failed → %s: %s", chat_name, err
                        ),
                    )
                except Exception as fallback_exc:
                    logger.warning(
                        "Realtime auto-reply failed → %s: %s",
                        chat_name,
                        fallback_exc,
                    )

    # ════════════════════════════════════════════════════
    #  Lifecycle
    # ════════════════════════════════════════════════════

    def login(
        self,
        code_callback: Optional[Callable[[], str]] = None,
    ) -> LoginStatus:
        """
        Authenticate and open a ready session.

        Validates the phone number before contacting the server.
        """
        try:
            self._phone = validate_phone(self._phone_raw or self._phone)
            self._phone_invalid_hint = False
        except ValueError as exc:
            raise LoginError(str(exc)) from exc

        if self._auto_reply is None:
            self._auto_reply = AutoReplyEngine(tracker=self._tracker)

        status = self._backend.login(self._phone, code_callback)
        if status in (
            LoginStatus.SUCCESS,
            LoginStatus.ALREADY_LOGGED_IN,
            LoginStatus.SESSION_RESTORED,
        ):
            self._is_logged_in = True
        return status

    def close(self) -> None:
        """Stop the transport and clean up."""
        self._monitor_stop.set()
        try:
            self._backend.close()
        except Exception as exc:
            logger.debug("backend close: %s", exc)
        self._is_logged_in = False
        logger.info("Client closed for %s (%s)", self._phone, self._backend.name)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ════════════════════════════════════════════════════
    #  Chat operations
    # ════════════════════════════════════════════════════

    def _ensure_ready(self):
        if not self._is_logged_in:
            raise SoroPyError("Not logged in. Call login() first.")
        if not self._backend.is_logged_in:
            # Keep the logical login flag: SPlusthon may auto-reconnect shortly.
            # A later operation should work again without forcing re-auth.
            raise SoroPyError(
                "Transport is temporarily disconnected. Wait for auto-reconnect or call login() again; "
                "if the auth key is invalid, delete_session() first."
            )

    def _require_ws(self, method: str) -> None:
        if self._backend.name != "websocket":
            raise SoroPyError(
                f"{method}() requires backend='websocket'. "
                f"Current backend is '{self._backend.name}'. "
                "Create the client with SoroushClient(phone, backend='websocket')."
            )

    def get_chats(self, save_to: Optional[str] = None) -> ChatCollection:
        """Extract all chats."""
        self._ensure_ready()
        collection = self._backend.get_chats()
        self._chats_cache = collection

        if save_to:
            with open(save_to, "w", encoding="utf-8") as f:
                json.dump(collection.to_dict(), f, ensure_ascii=False, indent=2)
            logger.info("Chats saved to %s", save_to)

        return collection

    def send_message(self, chat_name: str, message: str) -> SendResult:
        """Send a single message to a specific chat (personal / group / channel)."""
        self._ensure_ready()
        return self._backend.send_message(chat_name, message)

    def reply(
        self,
        chat_name: str,
        message_id: Union[str, int],
        text: str,
    ) -> SendResult:
        """Reply to a specific message by id."""
        self._ensure_ready()
        return self._backend.reply_to_message(chat_name, str(message_id), text)

    def send_bulk_messages(
        self,
        chat_names: List[str],
        message: str,
        delay: float = 3.0,
    ) -> List[SendResult]:
        """Send *message* to multiple chats."""
        self._ensure_ready()
        return self._backend.send_bulk_messages(chat_names, message, delay)

    def send_to_personal(
        self,
        message: str = "سلام",
        max_count: int = 10,
    ) -> List[SendResult]:
        """Send *message* to the first *max_count* personal chats."""
        if not self._chats_cache or not self._chats_cache.personal:
            self.get_chats()
        targets = (self._chats_cache.personal or [])[:max_count]
        return self.send_bulk_messages(targets, message)

    def send_to_group(self, group: str, message: str) -> SendResult:
        """Send text to a group / supergroup."""
        self._ensure_ready()
        if hasattr(self._backend, "send_to_group"):
            return self._backend.send_to_group(group, message)  # type: ignore
        return self._backend.send_message(group, message)

    # ════════════════════════════════════════════════════
    #  Channel operations
    # ════════════════════════════════════════════════════

    def send_to_channel(self, channel_url: str, message: str) -> bool:
        """Post *message* to a channel (admin required)."""
        self._ensure_ready()
        return self._backend.send_to_channel(channel_url, message)

    # ════════════════════════════════════════════════════
    #  Media / message tools
    # ════════════════════════════════════════════════════

    def send_file(
        self,
        chat: str,
        path: str,
        caption: str = "",
        force_document: bool = False,
        reply_to: Union[str, int, None] = None,
    ) -> SendResult:
        """Send a file / photo to *chat* (WebSocket backend)."""
        self._ensure_ready()
        if hasattr(self._backend, "send_file"):
            return self._backend.send_file(  # type: ignore[attr-defined]
                chat,
                path,
                caption=caption,
                force_document=force_document,
                reply_to=reply_to,
            )
        raise SoroPyError(
            "send_file() is only available on backend='websocket'. "
            "Install soropy[ws] and use SoroushClient(..., backend='websocket')."
        )

    def download_media(
        self,
        chat: str,
        message_id: Union[str, int],
        file_path: Optional[str] = None,
    ) -> Optional[str]:
        """Download media from a message; returns local file path."""
        self._ensure_ready()
        if hasattr(self._backend, "download_media"):
            return self._backend.download_media(  # type: ignore[attr-defined]
                chat, message_id, file_path
            )
        raise SoroPyError("download_media() requires backend='websocket'.")

    def delete_messages(
        self,
        chat: str,
        message_ids: Sequence[Union[str, int]],
        revoke: bool = True,
    ) -> bool:
        """Delete one or more messages."""
        self._ensure_ready()
        if hasattr(self._backend, "delete_messages"):
            return self._backend.delete_messages(  # type: ignore[attr-defined]
                chat, message_ids, revoke=revoke
            )
        raise SoroPyError("delete_messages() requires backend='websocket'.")

    def edit_message(
        self,
        chat: str,
        message_id: Union[str, int],
        text: str,
    ) -> bool:
        """Edit a previously sent message."""
        self._ensure_ready()
        if hasattr(self._backend, "edit_message"):
            return self._backend.edit_message(  # type: ignore[attr-defined]
                chat, message_id, text
            )
        raise SoroPyError("edit_message() requires backend='websocket'.")

    def pin_message(
        self,
        chat: str,
        message_id: Union[str, int],
        notify: bool = False,
    ) -> bool:
        """Pin a message in a chat."""
        self._ensure_ready()
        if hasattr(self._backend, "pin_message"):
            return self._backend.pin_message(  # type: ignore[attr-defined]
                chat, message_id, notify=notify
            )
        raise SoroPyError("pin_message() requires backend='websocket'.")

    def unpin_message(
        self,
        chat: str,
        message_id: Optional[Union[str, int]] = None,
    ) -> bool:
        """Unpin a message (or all, if message_id is None)."""
        self._ensure_ready()
        if hasattr(self._backend, "unpin_message"):
            return self._backend.unpin_message(  # type: ignore[attr-defined]
                chat, message_id
            )
        raise SoroPyError("unpin_message() requires backend='websocket'.")

    # ════════════════════════════════════════════════════
    #  Contact / user operations
    # ════════════════════════════════════════════════════

    def get_contacts(self) -> List[str]:
        """List all contact names."""
        self._ensure_ready()
        return self._backend.get_contacts()

    def add_contact(
        self,
        phone: str,
        first_name: str,
        last_name: str = "",
    ) -> bool:
        """Add a new contact."""
        self._ensure_ready()
        return self._backend.add_contact(phone, first_name, last_name)

    def search_contacts(self, query: str) -> List[str]:
        """Search contacts by name or number."""
        self._ensure_ready()
        return self._backend.search_contacts(query)

    def block_user(self, user: str) -> bool:
        """Block a user."""
        self._ensure_ready()
        if hasattr(self._backend, "block_user"):
            return self._backend.block_user(user)  # type: ignore[attr-defined]
        raise SoroPyError("block_user() requires backend='websocket'.")

    def unblock_user(self, user: str) -> bool:
        """Unblock a user."""
        self._ensure_ready()
        if hasattr(self._backend, "unblock_user"):
            return self._backend.unblock_user(user)  # type: ignore[attr-defined]
        raise SoroPyError("unblock_user() requires backend='websocket'.")

    def report(
        self,
        entity: str,
        reason: str = "spam",
        message: str = "",
    ) -> bool:
        """
        Report a peer.

        reason: spam | violence | porn | copyright | other | fake | child | geo
        """
        self._ensure_ready()
        if hasattr(self._backend, "report"):
            return self._backend.report(  # type: ignore[attr-defined]
                entity, reason=reason, message=message
            )
        raise SoroPyError("report() requires backend='websocket'.")

    # ════════════════════════════════════════════════════
    #  Moderation (group / channel – admin required)
    # ════════════════════════════════════════════════════

    def kick(self, chat: str, user: str) -> bool:
        """Kick a user from a group/channel (admin)."""
        self._ensure_ready()
        if hasattr(self._backend, "kick"):
            return self._backend.kick(chat, user)  # type: ignore[attr-defined]
        raise SoroPyError("kick() requires backend='websocket'.")

    def ban(self, chat: str, user: str, **kwargs) -> bool:
        """Ban a user in a group/channel (admin)."""
        self._ensure_ready()
        if hasattr(self._backend, "ban"):
            return self._backend.ban(chat, user, **kwargs)  # type: ignore[attr-defined]
        raise SoroPyError("ban() requires backend='websocket'.")

    def unban(self, chat: str, user: str) -> bool:
        """Unban a user (admin)."""
        self._ensure_ready()
        if hasattr(self._backend, "unban"):
            return self._backend.unban(chat, user)  # type: ignore[attr-defined]
        raise SoroPyError("unban() requires backend='websocket'.")

    def set_permissions(
        self,
        chat: str,
        user: Optional[str] = None,
        **rights,
    ) -> bool:
        """Set restricted permissions on a user or default chat rights."""
        self._ensure_ready()
        if hasattr(self._backend, "set_permissions"):
            return self._backend.set_permissions(  # type: ignore[attr-defined]
                chat, user=user, **rights
            )
        raise SoroPyError("set_permissions() requires backend='websocket'.")

    def promote(self, chat: str, user: str, **admin_rights) -> bool:
        """Promote a user to admin (admin rights required)."""
        self._ensure_ready()
        if hasattr(self._backend, "promote"):
            return self._backend.promote(  # type: ignore[attr-defined]
                chat, user, **admin_rights
            )
        raise SoroPyError("promote() requires backend='websocket'.")

    def get_participants(self, chat: str, limit: int = 100) -> List[Dict[str, Any]]:
        """List participants of a group/channel."""
        self._ensure_ready()
        if hasattr(self._backend, "get_participants"):
            return self._backend.get_participants(chat, limit=limit)  # type: ignore
        raise SoroPyError("get_participants() requires backend='websocket'.")

    def get_permissions(
        self,
        chat: str,
        user: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Get permissions for self or a specific user in *chat*."""
        self._ensure_ready()
        if hasattr(self._backend, "get_permissions"):
            return self._backend.get_permissions(chat, user=user)  # type: ignore
        raise SoroPyError("get_permissions() requires backend='websocket'.")

    # ════════════════════════════════════════════════════
    #  Saved Messages
    # ════════════════════════════════════════════════════

    def go_to_saved_messages(self) -> bool:
        """Navigate to Saved Messages (Selenium) / open chat (WS)."""
        self._ensure_ready()
        return self._backend.go_to_saved_messages()

    def get_me(self) -> Optional[Dict[str, Any]]:
        """Return basic info about the logged-in account (WS)."""
        self._ensure_ready()
        if hasattr(self._backend, "get_me"):
            return self._backend.get_me()  # type: ignore[attr-defined]
        return {"phone": self._phone, "backend": self._backend.name}

    # ════════════════════════════════════════════════════
    #  Auto-reply (single pass – polling style)
    # ════════════════════════════════════════════════════

    def check_and_reply(self) -> Dict[str, List[SendResult]]:
        """
        Check **personal** chats for unread messages and auto-reply.

        Groups and channels are never targeted when
        ``auto_reply_private_only`` is True (default).

        Admin / write-forbidden errors are soft-skipped (debug log only).
        """
        self._ensure_ready()
        if not self.auto_reply_enabled:
            return {}

        engine = self.auto_reply_engine
        if not engine.has_rules():
            logger.debug("No auto-reply rules/default configured; skip poll")
            return {}

        results: Dict[str, List[SendResult]] = {}

        def _reserve_reply(
            message_text: str, chat_name: str, index: int, message_id: str = ""
        ):
            with self._realtime_reply_lock:
                selected = engine.get_reply(
                    message_text, chat_name, index, message_id=message_id
                )
                if selected is not None:
                    engine.mark_replied(
                        chat_name, message_text, message_id=message_id
                    )
                return selected

        # Cap unread chats on WS to avoid thrashing 80+ dialogs
        max_chats = (
            WS_MAX_UNREAD_PER_CYCLE
            if self._backend.name == "websocket"
            else 50
        )
        if hasattr(self._backend, "get_unread_personal_chats"):
            try:
                unread = self._backend.get_unread_personal_chats(  # type: ignore
                    max_chats=max_chats
                )
            except TypeError:
                unread = self._backend.get_unread_personal_chats()
                unread = unread[:max_chats]
        else:
            unread = self._backend.get_unread_personal_chats()
            unread = unread[:max_chats]

        if not unread:
            logger.info("No unread personal messages")
            return results

        logger.info("%d personal chats with unread (cap=%d)", len(unread), max_chats)

        for uc in unread:
            # Double-check kind if backend exposes it
            if self.auto_reply_private_only and hasattr(self._backend, "chat_kind"):
                kind = self._backend.chat_kind(uc.name)  # type: ignore
                if kind and kind != "personal":
                    logger.debug("Skip non-personal in poll: %s (%s)", uc.name, kind)
                    continue

            chat_results: List[SendResult] = []
            try:
                messages = self._backend.get_unread_messages(uc.name, uc.count)
            except Exception as exc:
                if _is_soft_skip_error(str(exc)):
                    logger.debug("get_unread soft-skip %s: %s", uc.name, exc)
                else:
                    logger.warning("get_unread failed %s: %s", uc.name, exc)
                continue

            if not messages:
                reply = _reserve_reply("", uc.name, 1)
                if reply:
                    try:
                        if self._backend.name == "selenium" and hasattr(
                            self._backend, "chat"
                        ):
                            ok = self._backend.chat.type_and_send(reply)  # type: ignore
                            sr = SendResult(
                                ok, uc.name, reply, "" if ok else "Send failed"
                            )
                        else:
                            sr = self._backend.send_message(uc.name, reply)
                        if not sr.success:
                            engine.unmark_replied(uc.name, "")
                            if sr.error and _is_soft_skip_error(sr.error):
                                logger.debug(
                                    "poll send soft-skip %s: %s", uc.name, sr.error
                                )
                        chat_results.append(sr)
                    except Exception as exc:
                        engine.unmark_replied(uc.name, "")
                        if _is_soft_skip_error(str(exc)):
                            logger.debug("poll soft-skip %s: %s", uc.name, exc)
                        else:
                            logger.warning("poll send error %s: %s", uc.name, exc)
            else:
                for idx, msg in enumerate(messages, 1):
                    reply = _reserve_reply(
                        msg.text, uc.name, idx, message_id=msg.message_id
                    )
                    if reply is None:
                        logger.debug(
                            "Skipping (no rule/duplicate) in '%s': %s",
                            uc.name,
                            (msg.text or "")[:30],
                        )
                        continue

                    try:
                        sr = self._backend.reply_to_message(
                            uc.name,
                            msg.message_id,
                            reply,
                            element_index=msg.element_index,
                        )
                        if not sr.success:
                            engine.unmark_replied(uc.name, msg.text, message_id=msg.message_id)
                            if sr.error and _is_soft_skip_error(sr.error):
                                logger.debug(
                                    "poll reply soft-skip %s: %s", uc.name, sr.error
                                )
                        chat_results.append(sr)
                    except Exception as exc:
                        engine.unmark_replied(uc.name, msg.text, message_id=msg.message_id)
                        if _is_soft_skip_error(str(exc)):
                            logger.debug("poll soft-skip %s: %s", uc.name, exc)
                        else:
                            logger.warning("poll reply error %s: %s", uc.name, exc)
                    time.sleep(0.5 if self._backend.name == "websocket" else 2)

            results[uc.name] = chat_results

            # Selenium: return to personal chat list for the next unread
            if self._backend.name == "selenium" and hasattr(self._backend, "chat"):
                try:
                    self._backend.chat.go_back()  # type: ignore[attr-defined]
                    time.sleep(1)
                    self._backend.chat.click_chat_tab(C.TAB_PERSONAL)  # type: ignore
                    time.sleep(1)
                except Exception:
                    pass

        return results

    # ════════════════════════════════════════════════════
    #  Auto-reply monitor (continuous)
    # ════════════════════════════════════════════════════

    def start_monitor(
        self,
        interval: int = 30,
        blocking: bool = True,
        on_reply: Optional[Callable[[str, str, str], None]] = None,
    ) -> Optional[threading.Thread]:
        """
        Continuously monitor and auto-reply (**personal chats only**).

        * Selenium: polls every *interval* seconds.
        * WebSocket: realtime ``new_message`` already auto-replies when
          rules are set; this monitor is only a safety-net poll.
          Interval is raised to at least ``WS_MIN_MONITOR_INTERVAL`` (120s)
          to avoid thrashing dialogs.
        """
        self._monitor_stop.clear()

        effective = int(interval)
        if self._backend.supports(BackendCapability.REALTIME_EVENTS):
            if effective < WS_MIN_MONITOR_INTERVAL:
                logger.info(
                    "WebSocket backend: raising poll interval %ss → %ss "
                    "(realtime auto-reply is primary; poll is safety-net only)",
                    effective,
                    WS_MIN_MONITOR_INTERVAL,
                )
                effective = WS_MIN_MONITOR_INTERVAL

        def _loop():
            cycle = 0
            while not self._monitor_stop.is_set():
                cycle += 1
                logger.info("Monitor cycle %d (interval=%ss)", cycle, effective)
                try:
                    results = self.check_and_reply()
                    if on_reply:
                        for chat_name, send_results in results.items():
                            for sr in send_results:
                                if sr.success:
                                    on_reply(chat_name, "", sr.message)
                except Exception as e:
                    if _is_soft_skip_error(str(e)):
                        logger.debug("Monitor soft-skip: %s", e)
                    else:
                        logger.error("Monitor error: %s", e)

                self._monitor_stop.wait(timeout=effective)

            logger.info("Monitor stopped")

        if blocking:
            try:
                _loop()
            except KeyboardInterrupt:
                self._monitor_stop.set()
                logger.info("Monitor interrupted by user")
            return None
        else:
            t = threading.Thread(
                target=_loop, daemon=True, name=f"monitor-{self._phone}"
            )
            t.start()
            return t

    def stop_monitor(self) -> None:
        """Signal the monitor loop to stop."""
        self._monitor_stop.set()

    # ════════════════════════════════════════════════════
    #  Auto-reply rule shortcuts
    # ════════════════════════════════════════════════════

    def add_reply_rule(
        self,
        keyword: str,
        response: str,
        **kwargs,
    ) -> None:
        """Shortcut to add a rule to the auto-reply engine."""
        self.auto_reply_engine.add_rule(keyword, response, **kwargs)

    def remove_reply_rule(self, keyword: str) -> bool:
        """Shortcut to remove a rule."""
        return self.auto_reply_engine.remove_rule(keyword)

    def set_default_reply(self, reply: Optional[str]) -> None:
        """Set the default reply message (or None to disable)."""
        self.auto_reply_engine.default_reply = reply

    def load_reply_rules(self, rules: Dict[str, str]) -> None:
        """Bulk-load reply rules from a dict."""
        self.auto_reply_engine.load_rules_from_dict(rules)

    def set_auto_reply_enabled(self, enabled: bool) -> None:
        """Enable/disable auto-reply globally (realtime + poll)."""
        self.auto_reply_enabled = bool(enabled)
        self.auto_reply_engine.enabled = bool(enabled)

    def set_private_only(self, private_only: bool) -> None:
        """If True, auto-reply only targets personal chats."""
        self.auto_reply_private_only = bool(private_only)

    # ════════════════════════════════════════════════════
    #  Session helpers
    # ════════════════════════════════════════════════════

    def delete_session(self) -> bool:
        """Delete the stored session for this phone number."""
        if hasattr(self._backend, "delete_session"):
            try:
                return bool(self._backend.delete_session())  # type: ignore[attr-defined]
            except Exception:
                pass
        return self._session_mgr.delete(self._phone)

    @property
    def has_session(self) -> bool:
        if self._backend.name == "websocket" and hasattr(
            self._backend, "session_store"
        ):
            return self._backend.session_store.exists(self._phone)  # type: ignore
        return self._session_mgr.exists(self._phone)
