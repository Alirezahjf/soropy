"""
SoroPy - Professional Soroush Plus Web Client Library
=====================================================

A comprehensive, production-grade Python library for automating
Soroush Plus (splus.ir) web messenger.

Features:
    - Dual backends: Selenium (UI) and WebSocket (protocol)
    - Multi-account simultaneous sessions
    - Headless browser support
    - Auto-reply with rule engine and duplicate prevention
    - Realtime events on WebSocket backend
    - Chat extraction, messaging, channel posting
    - Contact management
    - Persistent session management
    - Thread-safe design

Basic Usage (Selenium – default)::

    >>> from soropy import SoroushClient
    >>> client = SoroushClient("+989123456789")
    >>> client.login()
    >>> chats = client.get_chats()
    >>> client.send_message("علی", "سلام!")
    >>> client.close()

WebSocket backend (event-driven)::

    >>> client = SoroushClient("0912...", backend="websocket")
    >>> client.on("new_message", lambda e: print(e.data))
    >>> client.login()

Multi-Account::

    >>> from soropy import MultiAccountManager
    >>> manager = MultiAccountManager(backend="selenium")
    >>> manager.add_account("+989123456789")
    >>> manager.login_all()
"""

__version__ = "1.3.3"
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
    TransportError,
    ProtocolError,
    ProtocolNotReadyError,
)
from soropy.session import SessionManager
from soropy.message_tracker import MessageTracker

# Multi-account manager
from soropy.multi import MultiAccountManager

# Backend plumbing (advanced)
from soropy.backends import create_backend, BaseBackend, BackendCapability
from soropy.backends.base import BackendEvent

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
    "TransportError",
    "ProtocolError",
    "ProtocolNotReadyError",
    "create_backend",
    "BaseBackend",
    "BackendCapability",
    "BackendEvent",
]