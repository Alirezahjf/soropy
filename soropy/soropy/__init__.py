"""
SoroPy - Professional Soroush Plus Web Client Library
=====================================================

A comprehensive, production-grade Python library for automating
Soroush Plus (splus.ir) web messenger.

Features:
    - Multi-account simultaneous sessions
    - Headless browser support
    - Auto-reply with rule engine and duplicate prevention
    - Chat extraction, messaging, channel posting
    - Contact management
    - Persistent session management
    - Thread-safe design

Basic Usage:
    >>> from soropy import SoroushClient
    >>> client = SoroushClient("+989123456789")
    >>> client.login()
    >>> chats = client.get_chats()
    >>> client.send_message("علی", "سلام!")
    >>> client.close()

Multi-Account:
    >>> from soropy import MultiAccountManager
    >>> manager = MultiAccountManager()
    >>> manager.add_account("+989123456789")
    >>> manager.add_account("+989187654321")
    >>> manager.login_all()
"""

__version__ = "1.0.0"
__author__ = "SoroPy Team"
__license__ = "MIT"

from soropy.client import SoroushClient
from soropy.auto_reply import AutoReplyEngine, ReplyRule
from soropy.types import (
    ChatInfo,
    ContactInfo,
    MessageInfo,
    UnreadChat,
    SendResult,
    LoginStatus,
)
from soropy.exceptions import (
    SoroPyError,
    LoginError,
    SessionError,
    ChatError,
    MessageError,
    ContactError,
    ChannelError,
    BrowserError,
    TimeoutError as SoroPyTimeoutError,
)
from soropy.session import SessionManager
from soropy.message_tracker import MessageTracker

# Multi-account manager
from soropy.multi import MultiAccountManager

__all__ = [
    "SoroushClient",
    "MultiAccountManager",
    "AutoReplyEngine",
    "ReplyRule",
    "ChatInfo",
    "ContactInfo",
    "MessageInfo",
    "UnreadChat",
    "SendResult",
    "LoginStatus",
    "SessionManager",
    "MessageTracker",
    "SoroPyError",
    "LoginError",
    "SessionError",
    "ChatError",
    "MessageError",
    "ContactError",
    "ChannelError",
    "BrowserError",
    "SoroPyTimeoutError",
]