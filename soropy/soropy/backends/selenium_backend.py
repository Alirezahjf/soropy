"""
Selenium backend – wraps the existing Browser / Auth / Chat managers
behind the :class:`BaseBackend` interface.
"""

from __future__ import annotations

import time
from typing import Callable, List, Optional

from soropy import constants as C
from soropy.auth import Authenticator
from soropy.auto_reply import AutoReplyEngine
from soropy.backends.base import BaseBackend, BackendCapability
from soropy.browser import BrowserManager
from soropy.channel import ChannelManager
from soropy.chat import ChatManager
from soropy.contacts import ContactManager
from soropy.exceptions import SoroPyError
from soropy.message_tracker import MessageTracker
from soropy.session import SessionManager
from soropy.types import (
    ChatCollection,
    LoginStatus,
    MessageInfo,
    SendResult,
    UnreadChat,
)
from soropy.utils import get_logger, wait_page_load

logger = get_logger("soropy.backends.selenium")


class SeleniumBackend(BaseBackend):
    """DOM-automation backend using Chrome + Selenium."""

    def __init__(
        self,
        phone: str,
        headless: bool = False,
        session_dir: str = C.DEFAULT_SESSIONS_DIR,
        tracker: Optional[MessageTracker] = None,
        chrome_binary: Optional[str] = None,
        chromedriver_path: Optional[str] = None,
        extra_chrome_args: Optional[list] = None,
        **_ignored,
    ):
        self._phone = phone
        self._session_mgr = SessionManager(session_dir)
        self._tracker = tracker
        self._browser_mgr = BrowserManager(
            phone=phone,
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
        self._logged_in = False

    # ── identity ───────────────────────────────────────

    @property
    def name(self) -> str:
        return "selenium"

    @property
    def is_connected(self) -> bool:
        return self._logged_in and self._browser_mgr.is_running

    def capabilities(self) -> frozenset:
        return frozenset(
            {
                BackendCapability.HEADLESS,
                BackendCapability.MULTI_ACCOUNT,
                BackendCapability.CONTACTS,
                BackendCapability.CHANNELS,
                BackendCapability.AUTO_REPLY,
                BackendCapability.SESSION_PERSIST,
                BackendCapability.REPLY_TO_MESSAGE,
            }
        )

    # ── managers (used by SoroushClient for advanced ops) ─

    @property
    def chat(self) -> ChatManager:
        if self._chat is None:
            raise SoroPyError("Not logged in. Call login() first.")
        return self._chat

    @property
    def contacts(self) -> Optional[ContactManager]:
        return self._contacts

    @property
    def channel(self) -> Optional[ChannelManager]:
        return self._channel

    @property
    def browser(self) -> BrowserManager:
        return self._browser_mgr

    @property
    def session_manager(self) -> SessionManager:
        return self._session_mgr

    # ── lifecycle ──────────────────────────────────────

    def login(
        self,
        phone: str,
        code_callback: Optional[Callable[[], str]] = None,
    ) -> LoginStatus:
        driver = self._browser_mgr.start()

        self._auth = Authenticator(driver)
        self._chat = ChatManager(driver)
        self._contacts = ContactManager(driver, self._chat)
        self._channel = ChannelManager(driver, self._chat)

        has_session = self._session_mgr.exists(phone)

        if has_session:
            logger.info("Existing session found for %s", phone)
            driver.get(C.SPLUS_WEB_URL)
            wait_page_load(driver, 15)

            if self._auth.is_logged_in():
                self._logged_in = True
                logger.info("Session restored – already logged in")
                return LoginStatus.SESSION_RESTORED

        status = self._auth.login(phone, code_callback)
        if status in (LoginStatus.SUCCESS, LoginStatus.ALREADY_LOGGED_IN):
            self._logged_in = True
        time.sleep(3)
        return status

    def close(self) -> None:
        self._browser_mgr.stop()
        self._logged_in = False
        self._auth = None
        self._chat = None
        self._contacts = None
        self._channel = None
        logger.info("Selenium backend closed for %s", self._phone)

    # ── chats ──────────────────────────────────────────

    def get_chats(self) -> ChatCollection:
        return self.chat.get_all_chats()

    def send_message(self, chat_name: str, message: str) -> SendResult:
        chat = self.chat
        chat.click_bottom_tab(C.TAB_CHAT)
        time.sleep(1)

        if not chat.click_on_chat(chat_name):
            return SendResult(False, chat_name, message, "Chat not found")

        time.sleep(2)
        if not chat.type_and_send(message):
            return SendResult(False, chat_name, message, "Send failed")

        chat.go_back()
        return SendResult(True, chat_name, message)

    def send_bulk_messages(
        self,
        chat_names: List[str],
        message: str,
        delay: float = 3.0,
    ) -> List[SendResult]:
        return self.chat.send_to_personal_chats(chat_names, message, delay)

    def get_unread_personal_chats(self) -> List[UnreadChat]:
        self.chat.click_bottom_tab(C.TAB_CHAT)
        time.sleep(2)
        self.chat.click_chat_tab(C.TAB_PERSONAL)
        time.sleep(2)
        return self.chat.get_unread_personal_chats()

    def get_unread_messages(self, chat_name: str, count: int = 10) -> List[MessageInfo]:
        if not self.chat.click_on_chat(chat_name):
            return []
        time.sleep(2)
        msgs = self.chat.get_unread_messages_in_chat(count)
        return msgs

    def reply_to_message(
        self,
        chat_name: str,
        message_id: str,
        reply_text: str,
        element_index: int = 0,
    ) -> SendResult:
        ok = self.chat.reply_to_message(element_index, reply_text)
        return SendResult(ok, chat_name, reply_text, "" if ok else "Reply failed")

    # ── contacts ───────────────────────────────────────

    def get_contacts(self) -> List[str]:
        if self._contacts is None:
            raise SoroPyError("Not logged in")
        self._contacts.open_contacts_section()
        time.sleep(2)
        names = self._contacts.list_contacts()
        self.chat.go_back()
        self.chat.click_bottom_tab(C.TAB_CHAT)
        return names

    def add_contact(self, phone: str, first_name: str, last_name: str = "") -> bool:
        if self._contacts is None:
            raise SoroPyError("Not logged in")
        self._contacts.open_contacts_section()
        time.sleep(2)
        result = self._contacts.add_contact(phone, first_name, last_name)
        self.chat.go_back()
        self.chat.click_bottom_tab(C.TAB_CHAT)
        return result

    def search_contacts(self, query: str) -> List[str]:
        if self._contacts is None:
            raise SoroPyError("Not logged in")
        self._contacts.open_contacts_section()
        time.sleep(2)
        results = self._contacts.search(query)
        self.chat.go_back()
        self.chat.click_bottom_tab(C.TAB_CHAT)
        return results

    # ── channels ───────────────────────────────────────

    def send_to_channel(self, channel_url: str, message: str) -> bool:
        if self._channel is None:
            raise SoroPyError("Not logged in")
        return self._channel.send_to_channel(channel_url, message)

    def go_to_saved_messages(self) -> bool:
        return self.chat.go_to_saved_messages()

    def get_raw_driver(self):
        try:
            return self._browser_mgr.driver
        except Exception:
            return None
