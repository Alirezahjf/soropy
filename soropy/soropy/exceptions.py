"""
Custom exception hierarchy for SoroPy.

All exceptions inherit from SoroPyError so callers can
catch everything with a single except clause if desired.
"""


class SoroPyError(Exception):
    """Base exception for all SoroPy errors."""

    def __init__(self, message: str = "", details: str = ""):
        self.details = details
        super().__init__(message)


class LoginError(SoroPyError):
    """Raised when login process fails."""
    pass


class SessionError(SoroPyError):
    """Raised when session management fails."""
    pass


class ChatError(SoroPyError):
    """Raised when chat operations fail."""
    pass


class MessageError(SoroPyError):
    """Raised when message sending/reading fails."""
    pass


class ContactError(SoroPyError):
    """Raised when contact operations fail."""
    pass


class ChannelError(SoroPyError):
    """Raised when channel operations fail."""
    pass


class BrowserError(SoroPyError):
    """Raised when browser setup or interaction fails."""
    pass


class TimeoutError(SoroPyError):
    """Raised when an operation times out."""
    pass


class ElementNotFoundError(SoroPyError):
    """Raised when a required DOM element is not found."""
    pass


class DuplicateReplyError(SoroPyError):
    """Raised when attempting to send a duplicate reply."""
    pass


class TransportError(SoroPyError):
    """Raised when the underlying transport (WS / HTTP) fails."""
    pass


class ProtocolError(SoroPyError):
    """Raised when a protocol frame cannot be encoded/decoded."""
    pass


class ProtocolNotReadyError(SoroPyError):
    """
    Raised when a WebSocket/protocol feature is scaffolded but the
    real Soroush Plus wire format has not been filled in yet.
    """
    pass