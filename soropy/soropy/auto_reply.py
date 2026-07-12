"""
Auto-reply engine with rule matching and duplicate prevention.
"""

import threading
from typing import List, Optional, Dict
from dataclasses import dataclass

from soropy.utils import get_logger
from soropy.message_tracker import MessageTracker

logger = get_logger("soropy.auto_reply")


@dataclass
class ReplyRule:
    """A single keyword → response mapping."""
    keyword: str
    response: str
    case_sensitive: bool = False
    exact_match: bool = False
    priority: int = 0  # higher = matched first

    def matches(self, text: str) -> bool:
        if self.case_sensitive:
            src, kw = text.strip(), self.keyword
        else:
            src, kw = text.strip().lower(), self.keyword.lower()

        if self.exact_match:
            return src == kw
        return kw in src


class AutoReplyEngine:
    """
    Rule-based auto-reply engine with duplicate message tracking.

    Usage:
        engine = AutoReplyEngine()
        engine.add_rule("سلام", "علیک سلام")
        engine.default_reply = "پیامت دریافت شد"

        reply = engine.get_reply("سلام دوست من", "علی")
        # → "علیک سلام"

        # Won't return a reply for the same message twice:
        reply2 = engine.get_reply("سلام دوست من", "علی")
        # → None  (already replied)
    """

    def __init__(
        self,
        tracker: Optional[MessageTracker] = None,
        default_reply: Optional[str] = None,
        default_prefix: str = "جواب",
        use_numbered_fallback: bool = False,
    ):
        """
        Parameters
        ----------
        tracker : MessageTracker, optional
            Duplicate-prevention store.
        default_reply : str or None
            Used when no rule matches.  ``None`` means *no* automatic
            default (return None) unless ``use_numbered_fallback`` is True.
        default_prefix : str
            Prefix for the legacy numbered fallback (``"جواب 1"``).
        use_numbered_fallback : bool
            If True and ``default_reply`` is None, fall back to
            ``f"{default_prefix} {msg_index}"``.  Default False so an
            unset default does not spam numbered replies.
        """
        self._rules: List[ReplyRule] = []
        self._tracker = tracker or MessageTracker()
        self._default_reply: Optional[str] = default_reply
        self.default_prefix = default_prefix
        self.use_numbered_fallback = use_numbered_fallback
        self._lock = threading.Lock()
        self.enabled: bool = True

    # ── default_reply property ─────────────────────────

    @property
    def default_reply(self) -> Optional[str]:
        return self._default_reply

    @default_reply.setter
    def default_reply(self, value: Optional[str]) -> None:
        """Set the default reply text (or None to disable)."""
        if value is None or (isinstance(value, str) and not value.strip()):
            self._default_reply = None
        else:
            self._default_reply = str(value)

    # ── Rule management ────────────────────────────────

    def add_rule(
        self,
        keyword: str,
        response: str,
        case_sensitive: bool = False,
        exact_match: bool = False,
        priority: int = 0,
    ) -> None:
        """Add a reply rule."""
        rule = ReplyRule(
            keyword=keyword,
            response=response,
            case_sensitive=case_sensitive,
            exact_match=exact_match,
            priority=priority,
        )
        with self._lock:
            self._rules.append(rule)
            self._rules.sort(key=lambda r: r.priority, reverse=True)
        logger.debug("Rule added: '%s' → '%s'", keyword, response)

    def remove_rule(self, keyword: str) -> bool:
        """Remove the first rule matching *keyword*."""
        with self._lock:
            for i, rule in enumerate(self._rules):
                if rule.keyword == keyword:
                    self._rules.pop(i)
                    return True
        return False

    def clear_rules(self) -> None:
        """Remove all rules."""
        with self._lock:
            self._rules.clear()

    @property
    def rules(self) -> List[ReplyRule]:
        with self._lock:
            return list(self._rules)

    def load_rules_from_dict(self, mapping: Dict[str, str]) -> None:
        """Bulk-load keyword→response pairs from a dict."""
        for kw, resp in mapping.items():
            self.add_rule(kw, resp)

    def export_rules_to_dict(self) -> Dict[str, str]:
        """Export rules as keyword→response dict."""
        with self._lock:
            return {r.keyword: r.response for r in self._rules}

    def has_rules(self) -> bool:
        """True when at least one rule or a default_reply is configured."""
        with self._lock:
            return bool(self._rules) or bool(self._default_reply)

    # ── Reply generation ───────────────────────────────

    def get_reply(
        self,
        message_text: str,
        chat_name: str,
        msg_index: int = 1,
        skip_duplicate_check: bool = False,
    ) -> Optional[str]:
        """
        Determine the reply for *message_text* from *chat_name*.

        Returns None if:
        * engine is disabled
        * message already replied to
        * no rule matches and no default is set
        """
        if not self.enabled:
            return None

        text = (message_text or "").strip()
        if not text:
            # Empty text: only reply if default is set (poll fallback path)
            if not skip_duplicate_check and self._tracker.is_replied(chat_name, ""):
                return None
            if self._default_reply:
                return self._default_reply
            if self.use_numbered_fallback:
                return f"{self.default_prefix} {msg_index}"
            return None

        # Duplicate check
        if not skip_duplicate_check and self._tracker.is_replied(chat_name, text):
            logger.debug("Duplicate detected, skipping: %s / %s", chat_name, text[:30])
            return None

        # Match rules
        with self._lock:
            for rule in self._rules:
                if rule.matches(text):
                    return rule.response

        # User-configured default_reply takes priority
        if self._default_reply is not None:
            return self._default_reply

        # Optional legacy numbered fallback (off by default)
        if self.use_numbered_fallback:
            return f"{self.default_prefix} {msg_index}"

        return None

    def mark_replied(self, chat_name: str, message_text: str) -> None:
        """Record that we replied to this message (prevents duplicates)."""
        self._tracker.mark_replied(chat_name, message_text)

    # ── Tracker access ─────────────────────────────────

    @property
    def tracker(self) -> MessageTracker:
        return self._tracker

    def prune_old_entries(self) -> int:
        """Remove expired tracker entries."""
        return self._tracker.prune()
