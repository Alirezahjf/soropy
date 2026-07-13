"""
Data classes representing domain objects.

Using dataclasses keeps the code clean and gives us
__repr__, __eq__, etc. for free.
"""

from dataclasses import dataclass, field
from typing import List, Dict
from enum import Enum


class LoginStatus(Enum):
    """Possible outcomes of a login attempt."""
    SUCCESS = "success"
    ALREADY_LOGGED_IN = "already_logged_in"
    NEED_CODE = "need_code"
    FAILED = "failed"
    SESSION_RESTORED = "session_restored"


@dataclass
class ChatInfo:
    """Represents a chat entry in the chat list."""
    name: str
    category: str = ""            # e.g. شخصی, گروه‌ها, کانال‌ها
    unread_count: int = 0
    is_private: bool = False
    is_group: bool = False
    is_channel: bool = False

    def __str__(self):
        badge = f" ({self.unread_count})" if self.unread_count else ""
        return f"{self.name}{badge} [{self.category}]"


@dataclass
class ContactInfo:
    """Represents a contact."""
    name: str
    family: str = ""
    phone: str = ""

    @property
    def full_name(self) -> str:
        parts = [self.name]
        if self.family:
            parts.append(self.family)
        return " ".join(parts)

    def __str__(self):
        return f"{self.full_name} ({self.phone})" if self.phone else self.full_name


@dataclass
class MessageInfo:
    """Represents a single message read from a chat."""
    text: str
    element_index: int = 0
    is_outgoing: bool = False
    message_id: str = ""          # backend message ID (or hash fallback)

    def __str__(self):
        direction = "→" if self.is_outgoing else "←"
        return f"{direction} {self.text[:60]}"


@dataclass
class UnreadChat:
    """A chat with unread messages."""
    name: str
    count: int = 1

    def __str__(self):
        return f"{self.name} ({self.count} new)"


@dataclass
class SendResult:
    """Outcome of a message-send operation."""
    success: bool
    chat_name: str = ""
    message: str = ""
    error: str = ""

    def __str__(self):
        status = "✅" if self.success else "❌"
        return f"{status} {self.chat_name}: {self.error or self.message[:40]}"


@dataclass
class ChatCollection:
    """Holds categorised chat lists."""
    all: List[str] = field(default_factory=list)
    personal: List[str] = field(default_factory=list)
    groups: List[str] = field(default_factory=list)
    channels: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, List[str]]:
        return {
            "همه": self.all,
            "شخصی": self.personal,
            "گروه‌ها": self.groups,
            "کانال‌ها": self.channels,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, List[str]]) -> "ChatCollection":
        return cls(
            all=data.get("همه", []),
            personal=data.get("شخصی", []),
            groups=data.get("گروه‌ها", []),
            channels=data.get("کانال‌ها", []),
        )

    @property
    def total_count(self) -> int:
        # ``all`` already contains every categorised chat; never double-count.
        return len(self.all) if self.all else (
            len(self.personal) + len(self.groups) + len(self.channels)
        )