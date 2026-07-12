"""
SoroushClient – the main high-level API.

Transport-agnostic façade over Selenium or WebSocket backends.
Users interact with this class; backends are an implementation detail.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Callable, Dict, List, Optional

from soropy import constants as C
from soropy.auto_reply import AutoReplyEngine
from soropy.backends import create_backend
from soropy.backends.base import BaseBackend, BackendCapability, BackendEvent
from soropy.exceptions import SoroPyError
from soropy.message_tracker import MessageTracker
from soropy.session import SessionManager
from soropy.types import (
    ChatCollection,
    LoginStatus,
    SendResult,
)
from soropy.utils import get_logger, normalize_phone

logger = get_logger("soropy.client")


class SoroushClient:
    """
    High-level Soroush Plus client.

    Parameters
    ----------
    phone : str
        Phone number in any Iranian format.
    backend : str
        ``"selenium"`` (default) – Chrome DOM automation.
        ``"websocket"`` / ``"ws"`` – direct protocol client (event-driven).
    headless : bool
        Selenium only: run Chrome without a visible window.
    session_dir : str
        Directory for persistent sessions
        (Chrome profiles for selenium, credential JSON for websocket).
    tracker_path : str or None
        Path to the message-tracker JSON file.
    log_file : str or None
        Optional log file path.
    chrome_binary / chromedriver_path / extra_chrome_args
        Selenium-only options.
    ws_url / origin
        WebSocket-only overrides.

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
        **backend_kwargs,
    ):
        self._phone = normalize_phone(phone)
        self._backend_name = (backend or "selenium").strip().lower()
        self._headless = headless
        self._log_file = log_file

        if log_file:
            from soropy.utils import get_logger as _gl
            _gl(f"soropy.{self._phone}", log_file)

        # Default session dir depends on backend
        if session_dir is None:
            if self._backend_name in ("websocket", "ws", "splus", "protocol"):
                session_dir = C.DEFAULT_WS_SESSIONS_DIR
            else:
                session_dir = C.DEFAULT_SESSIONS_DIR
        self._session_dir = session_dir

        # Selenium still uses SessionManager for profile paths / delete_session
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

        Only replies when the auto-reply engine has been configured
        (rules or default_reply) and the message is inbound.
        """
        if self._auto_reply is None:
            return
        data = event.data or {}
        if data.get("is_outgoing"):
            return
        text = (data.get("text") or "").strip()
        chat_name = data.get("chat_name") or data.get("sender_name") or data.get("chat_id") or ""
        if not text or not chat_name:
            return

        reply = self._auto_reply.get_reply(text, chat_name, 1)
        if reply is None:
            return

        msg_id = data.get("message_id") or ""
        result = self._backend.reply_to_message(chat_name, msg_id, reply)
        if result.success:
            self._auto_reply.mark_replied(chat_name, text)
            logger.info("Realtime auto-reply → %s: %s", chat_name, reply[:40])

    # ════════════════════════════════════════════════════
    #  Lifecycle
    # ════════════════════════════════════════════════════

    def login(
        self,
        code_callback: Optional[Callable[[], str]] = None,
    ) -> LoginStatus:
        """
        Authenticate and open a ready session.

        Parameters
        ----------
        code_callback : callable, optional
            Function that returns the SMS verification code.
            Default: ``input()`` prompt.

        Returns
        -------
        LoginStatus
        """
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
        self._backend.close()
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

    def get_chats(self, save_to: Optional[str] = None) -> ChatCollection:
        """
        Extract all chats.

        Parameters
        ----------
        save_to : str, optional
            JSON file path to persist results.

        Returns
        -------
        ChatCollection
        """
        self._ensure_ready()
        collection = self._backend.get_chats()
        self._chats_cache = collection

        if save_to:
            with open(save_to, "w", encoding="utf-8") as f:
                json.dump(collection.to_dict(), f, ensure_ascii=False, indent=2)
            logger.info("Chats saved to %s", save_to)

        return collection

    def send_message(self, chat_name: str, message: str) -> SendResult:
        """Send a single message to a specific chat."""
        self._ensure_ready()
        return self._backend.send_message(chat_name, message)

    def send_bulk_messages(
        self,
        chat_names: List[str],
        message: str,
        delay: float = 3.0,
    ) -> List[SendResult]:
        """Send *message* to multiple personal chats."""
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

    # ════════════════════════════════════════════════════
    #  Channel operations
    # ════════════════════════════════════════════════════

    def send_to_channel(self, channel_url: str, message: str) -> bool:
        """Post *message* to a channel (admin required)."""
        self._ensure_ready()
        return self._backend.send_to_channel(channel_url, message)

    # ════════════════════════════════════════════════════
    #  Contact operations
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

    # ════════════════════════════════════════════════════
    #  Saved Messages
    # ════════════════════════════════════════════════════

    def go_to_saved_messages(self) -> bool:
        """Navigate to Saved Messages (Selenium) / open chat (WS)."""
        self._ensure_ready()
        return self._backend.go_to_saved_messages()

    # ════════════════════════════════════════════════════
    #  Auto-reply (single pass – polling style)
    # ════════════════════════════════════════════════════

    def check_and_reply(self) -> Dict[str, List[SendResult]]:
        """
        Check personal chats for unread messages and auto-reply
        using the configured rules.  Skips messages already replied to.

        Works on both backends:
        * Selenium – scrapes unread badges from the DOM.
        * WebSocket – uses in-memory unread counters + history RPC.

        Returns
        -------
        dict  chat_name → list of SendResult
        """
        self._ensure_ready()
        engine = self.auto_reply_engine
        results: Dict[str, List[SendResult]] = {}

        unread = self._backend.get_unread_personal_chats()
        if not unread:
            logger.info("No unread messages")
            return results

        logger.info("%d chats with unread messages", len(unread))

        for uc in unread:
            chat_results: List[SendResult] = []
            messages = self._backend.get_unread_messages(uc.name, uc.count)

            if not messages:
                reply = engine.get_reply("", uc.name, 1)
                if reply:
                    # Prefer plain send; Selenium may already be inside the chat
                    if self._backend.name == "selenium" and hasattr(self._backend, "chat"):
                        ok = self._backend.chat.type_and_send(reply)  # type: ignore[attr-defined]
                        sr = SendResult(ok, uc.name, reply, "" if ok else "Send failed")
                    else:
                        sr = self._backend.send_message(uc.name, reply)
                    if sr.success:
                        engine.mark_replied(uc.name, "")
                    chat_results.append(sr)
            else:
                for idx, msg in enumerate(messages, 1):
                    reply = engine.get_reply(msg.text, uc.name, idx)
                    if reply is None:
                        logger.debug(
                            "Skipping duplicate in '%s': %s",
                            uc.name,
                            msg.text[:30],
                        )
                        continue

                    sr = self._backend.reply_to_message(
                        uc.name,
                        msg.message_id,
                        reply,
                        element_index=msg.element_index,
                    )
                    if sr.success:
                        engine.mark_replied(uc.name, msg.text)
                    chat_results.append(sr)
                    time.sleep(0.5 if self._backend.name == "websocket" else 2)

            results[uc.name] = chat_results

            # Selenium: return to personal chat list for the next unread
            if self._backend.name == "selenium" and hasattr(self._backend, "chat"):
                try:
                    from soropy import constants as _C
                    self._backend.chat.go_back()  # type: ignore[attr-defined]
                    time.sleep(1)
                    self._backend.chat.click_chat_tab(_C.TAB_PERSONAL)  # type: ignore[attr-defined]
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
        Continuously monitor and auto-reply.

        * Selenium backend: polls every *interval* seconds.
        * WebSocket backend: realtime ``new_message`` handler already
          auto-replies when rules are set; this monitor still runs a
          lightweight safety-net poll (default interval can be higher).

        Parameters
        ----------
        interval : int
            Seconds between each scan.
        blocking : bool
            If True, blocks the calling thread (press Ctrl+C to stop).
            If False, runs in a background thread and returns it.
        on_reply : callable(chat_name, original_msg, reply_msg)
            Optional callback invoked after each successful reply.

        Returns
        -------
        threading.Thread or None
        """
        self._monitor_stop.clear()

        # For WS, realtime path is preferred – still keep poll as fallback
        if (
            self._backend.supports(BackendCapability.REALTIME_EVENTS)
            and interval < 5
        ):
            logger.info(
                "WebSocket backend active: realtime auto-reply is on; "
                "poll interval=%ss is a safety net only",
                interval,
            )

        def _loop():
            cycle = 0
            while not self._monitor_stop.is_set():
                cycle += 1
                logger.info("Monitor cycle %d", cycle)
                try:
                    results = self.check_and_reply()
                    if on_reply:
                        for chat_name, send_results in results.items():
                            for sr in send_results:
                                if sr.success:
                                    on_reply(chat_name, "", sr.message)
                except Exception as e:
                    logger.error("Monitor error: %s", e)

                self._monitor_stop.wait(timeout=interval)

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

    def set_default_reply(self, reply: str) -> None:
        """Set the default reply message."""
        self.auto_reply_engine.default_reply = reply

    def load_reply_rules(self, rules: Dict[str, str]) -> None:
        """Bulk-load reply rules from a dict."""
        self.auto_reply_engine.load_rules_from_dict(rules)

    # ════════════════════════════════════════════════════
    #  Session helpers
    # ════════════════════════════════════════════════════

    def delete_session(self) -> bool:
        """Delete the stored session for this phone number."""
        # Prefer backend-specific storage
        if hasattr(self._backend, "delete_session"):
            try:
                return bool(self._backend.delete_session())  # type: ignore[attr-defined]
            except Exception:
                pass
        return self._session_mgr.delete(self._phone)

    @property
    def has_session(self) -> bool:
        if self._backend.name == "websocket" and hasattr(self._backend, "session_store"):
            return self._backend.session_store.exists(self._phone)  # type: ignore[attr-defined]
        return self._session_mgr.exists(self._phone)
