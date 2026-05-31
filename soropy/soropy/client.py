"""
SoroushClient – the main high-level API.

This is the class users interact with directly.
"""

import time
import json
import threading
from typing import Optional, List, Dict, Callable

from soropy.browser import BrowserManager
from soropy.auth import Authenticator
from soropy.chat import ChatManager
from soropy.contacts import ContactManager
from soropy.channel import ChannelManager
from soropy.auto_reply import AutoReplyEngine, ReplyRule
from soropy.message_tracker import MessageTracker
from soropy.session import SessionManager
from soropy.types import (
    ChatCollection,
    ChatInfo,
    ContactInfo,
    SendResult,
    UnreadChat,
    MessageInfo,
    LoginStatus,
)
from soropy.utils import get_logger, normalize_phone
from soropy.exceptions import SoroPyError, LoginError
from soropy import constants as C

logger = get_logger("soropy.client")


class SoroushClient:
    """
    High-level Soroush Plus web client.

    Parameters
    ----------
    phone : str
        Phone number in any Iranian format.
    headless : bool
        Run Chrome without a visible window.
    session_dir : str
        Directory to store persistent sessions.
    tracker_path : str or None
        Path to the message-tracker JSON file.
        If None, defaults to ``<session_dir>/<phone>_tracker.json``.
    log_file : str or None
        Optional log file path.
    chrome_binary : str or None
        Path to Chrome/Chromium binary.
    chromedriver_path : str or None
        Path to chromedriver executable.
    extra_chrome_args : list or None
        Extra command-line arguments for Chrome.

    Example
    -------
    >>> client = SoroushClient("+989123456789", headless=True)
    >>> client.login()
    >>> chats = client.get_chats()
    >>> client.send_message("علی", "سلام!")
    >>> client.close()
    """

    def __init__(
        self,
        phone: str,
        headless: bool = False,
        session_dir: str = C.DEFAULT_SESSIONS_DIR,
        tracker_path: Optional[str] = None,
        log_file: Optional[str] = None,
        chrome_binary: Optional[str] = None,
        chromedriver_path: Optional[str] = None,
        extra_chrome_args: Optional[list] = None,
    ):
        self._phone = normalize_phone(phone)
        self._headless = headless
        self._log_file = log_file

        if log_file:
            # Re-configure logger with file handler
            from soropy.utils import get_logger as _gl
            _gl(f"soropy.{self._phone}", log_file)

        self._session_mgr = SessionManager(session_dir)

        if tracker_path is None:
            safe = self._phone.replace("+", "plus_")
            tracker_path = f"{session_dir}/{safe}_tracker.json"
        self._tracker = MessageTracker(db_path=tracker_path)

        self._browser_mgr = BrowserManager(
            phone=self._phone,
            headless=headless,
            session_manager=self._session_mgr,
            chrome_binary=chrome_binary,
            chromedriver_path=chromedriver_path,
            extra_args=extra_chrome_args or [],
        )

        self._auth: Optional[Authenticator] = None
        self._chat: Optional[ChatManager] = None
        self._contacts: Optional[ContactManager] = None
        self._channel: Optional[ChannelManager] = None
        self._auto_reply: Optional[AutoReplyEngine] = None

        self._chats_cache: Optional[ChatCollection] = None
        self._is_logged_in = False
        self._monitor_stop = threading.Event()

    # ════════════════════════════════════════════════════
    #  Properties
    # ════════════════════════════════════════════════════

    @property
    def phone(self) -> str:
        return self._phone

    @property
    def is_logged_in(self) -> bool:
        return self._is_logged_in

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
    #  Lifecycle
    # ════════════════════════════════════════════════════

    def login(
        self,
        code_callback: Optional[Callable[[], str]] = None,
    ) -> LoginStatus:
        """
        Start the browser and log in.

        Parameters
        ----------
        code_callback : callable, optional
            Function that returns the SMS verification code.
            Default: ``input()`` prompt.

        Returns
        -------
        LoginStatus
        """
        driver = self._browser_mgr.start()

        self._auth = Authenticator(driver)
        self._chat = ChatManager(driver)
        self._contacts = ContactManager(driver, self._chat)
        self._channel = ChannelManager(driver, self._chat)

        if self._auto_reply is None:
            self._auto_reply = AutoReplyEngine(tracker=self._tracker)

        has_session = self._session_mgr.exists(self._phone)

        if has_session:
            logger.info("Existing session found for %s", self._phone)
            driver.get(C.SPLUS_WEB_URL)
            from soropy.utils import wait_page_load
            wait_page_load(driver, 15)

            if self._auth.is_logged_in():
                self._is_logged_in = True
                logger.info("Session restored – already logged in")
                return LoginStatus.SESSION_RESTORED

        status = self._auth.login(self._phone, code_callback)
        if status in (LoginStatus.SUCCESS, LoginStatus.ALREADY_LOGGED_IN):
            self._is_logged_in = True
        time.sleep(3)
        return status

    def close(self) -> None:
        """Stop the browser and clean up."""
        self._monitor_stop.set()
        self._browser_mgr.stop()
        self._is_logged_in = False
        logger.info("Client closed for %s", self._phone)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ════════════════════════════════════════════════════
    #  Chat operations
    # ════════════════════════════════════════════════════

    def _ensure_chat(self):
        if self._chat is None:
            raise SoroPyError("Not logged in. Call login() first.")

    def get_chats(self, save_to: Optional[str] = None) -> ChatCollection:
        """
        Extract all chats across tabs.

        Parameters
        ----------
        save_to : str, optional
            JSON file path to persist results.

        Returns
        -------
        ChatCollection
        """
        self._ensure_chat()
        collection = self._chat.get_all_chats()
        self._chats_cache = collection

        if save_to:
            with open(save_to, "w", encoding="utf-8") as f:
                json.dump(collection.to_dict(), f, ensure_ascii=False, indent=2)
            logger.info("Chats saved to %s", save_to)

        return collection

    def send_message(self, chat_name: str, message: str) -> SendResult:
        """Send a single message to a specific chat."""
        self._ensure_chat()
        self._chat.click_bottom_tab(C.TAB_CHAT)
        time.sleep(1)

        if not self._chat.click_on_chat(chat_name):
            return SendResult(False, chat_name, message, "Chat not found")

        time.sleep(2)
        if not self._chat.type_and_send(message):
            return SendResult(False, chat_name, message, "Send failed")

        self._chat.go_back()
        return SendResult(True, chat_name, message)

    def send_bulk_messages(
        self,
        chat_names: List[str],
        message: str,
        delay: float = 3.0,
    ) -> List[SendResult]:
        """Send *message* to multiple personal chats."""
        self._ensure_chat()
        return self._chat.send_to_personal_chats(chat_names, message, delay)

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
        self._ensure_chat()
        if self._channel is None:
            raise SoroPyError("Not logged in")
        return self._channel.send_to_channel(channel_url, message)

    # ════════════════════════════════════════════════════
    #  Contact operations
    # ════════════════════════════════════════════════════

    def get_contacts(self) -> List[str]:
        """List all contact names."""
        self._ensure_chat()
        if self._contacts is None:
            raise SoroPyError("Not logged in")
        self._contacts.open_contacts_section()
        time.sleep(2)
        names = self._contacts.list_contacts()
        self._chat.go_back()
        self._chat.click_bottom_tab(C.TAB_CHAT)
        return names

    def add_contact(
        self,
        phone: str,
        first_name: str,
        last_name: str = "",
    ) -> bool:
        """Add a new contact."""
        self._ensure_chat()
        if self._contacts is None:
            raise SoroPyError("Not logged in")
        self._contacts.open_contacts_section()
        time.sleep(2)
        result = self._contacts.add_contact(phone, first_name, last_name)
        self._chat.go_back()
        self._chat.click_bottom_tab(C.TAB_CHAT)
        return result

    def search_contacts(self, query: str) -> List[str]:
        """Search contacts by name or number."""
        self._ensure_chat()
        if self._contacts is None:
            raise SoroPyError("Not logged in")
        self._contacts.open_contacts_section()
        time.sleep(2)
        results = self._contacts.search(query)
        self._chat.go_back()
        self._chat.click_bottom_tab(C.TAB_CHAT)
        return results

    # ════════════════════════════════════════════════════
    #  Saved Messages
    # ════════════════════════════════════════════════════

    def go_to_saved_messages(self) -> bool:
        """Navigate to Saved Messages."""
        self._ensure_chat()
        return self._chat.go_to_saved_messages()

    # ════════════════════════════════════════════════════
    #  Auto-reply (single pass)
    # ════════════════════════════════════════════════════

    def check_and_reply(self) -> Dict[str, List[SendResult]]:
        """
        Check all personal chats for unread messages and auto-reply
        using the configured rules.  Skips messages already replied to.

        Returns
        -------
        dict  chat_name → list of SendResult
        """
        self._ensure_chat()
        engine = self.auto_reply_engine
        results: Dict[str, List[SendResult]] = {}

        self._chat.click_bottom_tab(C.TAB_CHAT)
        time.sleep(2)
        self._chat.click_chat_tab(C.TAB_PERSONAL)
        time.sleep(2)

        unread = self._chat.get_unread_personal_chats()
        if not unread:
            logger.info("No unread messages")
            return results

        logger.info("%d chats with unread messages", len(unread))

        for uc in unread:
            chat_results: List[SendResult] = []

            if not self._chat.click_on_chat(uc.name):
                chat_results.append(
                    SendResult(False, uc.name, "", "Chat not found")
                )
                results[uc.name] = chat_results
                continue

            time.sleep(2)
            messages = self._chat.get_unread_messages_in_chat(uc.count)

            if not messages:
                # No readable messages – send a default if not duplicate
                reply = engine.get_reply("", uc.name, 1)
                if reply:
                    ok = self._chat.type_and_send(reply)
                    if ok:
                        engine.mark_replied(uc.name, "")
                    chat_results.append(SendResult(ok, uc.name, reply))
            else:
                for idx, msg in enumerate(messages, 1):
                    reply = engine.get_reply(msg.text, uc.name, idx)
                    if reply is None:
                        # Already replied
                        logger.debug(
                            "Skipping duplicate in '%s': %s",
                            uc.name,
                            msg.text[:30],
                        )
                        continue

                    ok = self._chat.reply_to_message(msg.element_index, reply)
                    if ok:
                        engine.mark_replied(uc.name, msg.text)
                    chat_results.append(
                        SendResult(ok, uc.name, reply, "" if ok else "Reply failed")
                    )
                    time.sleep(2)

            results[uc.name] = chat_results
            self._chat.go_back()
            time.sleep(1)
            self._chat.click_chat_tab(C.TAB_PERSONAL)
            time.sleep(1)

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
            t = threading.Thread(target=_loop, daemon=True, name=f"monitor-{self._phone}")
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
        return self._session_mgr.delete(self._phone)

    @property
    def has_session(self) -> bool:
        return self._session_mgr.exists(self._phone)