"""مدیر گروه WebSocket برای SoroPy 1.3.4.

این مثال یک moderator واقعی و قابل اجرا برای گروه‌های سروش‌پلاس است:
ضدلینک، ضدواژه، ضد flood، ضد تکرار متن، سه اخطار و kick.

قبل از اجرا مقدارهای SOROPY_PHONE و SOROPY_GROUP را تنظیم کنید و حتماً
ابتدا روی یک گروه آزمایشی تست بگیرید.
"""

from __future__ import annotations

import json
import os
import queue
import re
import signal
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Optional, Set, Tuple

PHONE = os.getenv("SOROPY_PHONE", "09123456789")
GROUP_NAME = os.getenv(
    "SOROPY_GROUP",
    "نام دقیق گروه خود را اینجا بنویسید",
)
GROUP_TARGET = os.getenv("SOROPY_GROUP_TARGET", GROUP_NAME)
SESSION_DIR = os.getenv(
    "SOROPY_SESSION_DIR",
    "soropy_ws_sessions",
)
MAX_WARNINGS = int(
    os.getenv("SOROPY_MAX_WARNINGS", "3")
)

DEFAULT_BAD_WORDS = {
    "کلمه_ممنوع_۱",
    "کلمه_ممنوع_۲",
}

FLOOD_MAX = int(os.getenv("SOROPY_FLOOD_MAX", "6"))
FLOOD_WINDOW = float(os.getenv("SOROPY_FLOOD_WINDOW", "8"))
REPEAT_MAX = int(os.getenv("SOROPY_REPEAT_MAX", "3"))
REPEAT_WINDOW = float(os.getenv("SOROPY_REPEAT_WINDOW", "30"))
PERMISSION_CACHE_TTL = 60.0
QUEUE_MAX_SIZE = 1000

_LINK_RE = re.compile(
    r"(?ix)"
    r"(https?://[^\s]+|www\.[^\s]+|"
    r"(?:t\.me|telegram\.me|ble\.ir|splus\.ir|rubika\.ir)(?:/[^\s]*)?|"
    r"\b[a-z0-9][a-z0-9-]*(?:\.[a-z0-9][a-z0-9-]*)+"
    r"\.(?:com|net|org|ir|io|me|co)(?:/[^\s]*)?)"
)
_DOMAIN_RE = re.compile(r"(?i)^(?:https?://)?(?:www\.)?([^/:?#\s]+)")


def _csv_env(name: str) -> List[str]:
    value = os.getenv(name, "")
    return [item.strip() for item in value.split(",") if item.strip()]


def load_bad_words() -> Set[str]:
    configured = _csv_env("SOROPY_BAD_WORDS")
    return set(configured) if configured else set(DEFAULT_BAD_WORDS)


def load_allowed_domains() -> Set[str]:
    return {domain.lower().lstrip("@") for domain in _csv_env("SOROPY_ALLOWED_DOMAINS")}


def load_exempt_user_ids() -> Set[str]:
    return set(_csv_env("SOROPY_EXEMPT_USER_IDS"))


def _normalise_text(text: str) -> str:
    return " ".join(str(text or "").casefold().split())


def contains_bad_word(text: str, bad_words: Optional[Iterable[str]] = None) -> bool:
    needle = _normalise_text(text)
    words = set(bad_words) if bad_words is not None else load_bad_words()
    return any(_normalise_text(word) in needle for word in words if word)


def extract_links(text: str) -> List[str]:
    return [match.group(0).rstrip(".,؛،)") for match in _LINK_RE.finditer(text or "")]


def _domain_from_link(link: str) -> str:
    cleaned = link.strip()
    if cleaned.startswith("www."):
        cleaned = "https://" + cleaned
    match = _DOMAIN_RE.search(cleaned)
    return (match.group(1) if match else cleaned).lower().strip(".")


def _domain_allowed(domain: str, allowed_domains: Set[str]) -> bool:
    if not allowed_domains:
        return False
    return any(domain == allowed or domain.endswith("." + allowed) for allowed in allowed_domains)


def contains_disallowed_link(
    text: str,
    allowed_domains: Optional[Iterable[str]] = None,
) -> bool:
    allowed = {item.lower().strip(".") for item in (allowed_domains or load_allowed_domains())}
    for link in extract_links(text):
        if not _domain_allowed(_domain_from_link(link), allowed):
            return True
    return False


class WarningStore:
    """Persistent and thread-safe warning counter with atomic JSON writes."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._data: Dict[str, Dict[str, Any]] = {}
        self._load()

    @staticmethod
    def key(chat_id: str, sender_id: str) -> str:
        return f"{chat_id}:{sender_id}"

    def _load(self) -> None:
        with self._lock:
            if not self.path.exists():
                self._data = {}
                return
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                self._data = raw if isinstance(raw, dict) else {}
            except Exception:
                self._data = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)

    def increment(self, chat_id: str, sender_id: str, reason: str) -> int:
        key = self.key(chat_id, sender_id)
        with self._lock:
            item = self._data.setdefault(
                key,
                {"chat_id": chat_id, "sender_id": sender_id, "count": 0, "reasons": []},
            )
            item["count"] = int(item.get("count", 0)) + 1
            item.setdefault("reasons", []).append(
                {"reason": reason, "timestamp": int(time.time())}
            )
            self._save()
            return int(item["count"])

    def get(self, chat_id: str, sender_id: str) -> int:
        with self._lock:
            return int(self._data.get(self.key(chat_id, sender_id), {}).get("count", 0))

    def clear(self, chat_id: str, sender_id: str) -> bool:
        with self._lock:
            removed = self._data.pop(self.key(chat_id, sender_id), None) is not None
            self._save()
            return removed

    def summary(self, chat_id: Optional[str] = None) -> str:
        with self._lock:
            rows = []
            for item in self._data.values():
                if chat_id and str(item.get("chat_id")) != str(chat_id):
                    continue
                rows.append(f"{item.get('sender_id')}: {item.get('count', 0)} اخطار")
            return "\n".join(sorted(rows)) if rows else "هیچ اخطاری ثبت نشده است."


class SlidingWindowCounter:
    def __init__(self, max_count: int, window_seconds: float):
        self.max_count = max_count
        self.window_seconds = window_seconds
        self._events: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.RLock()

    def hit(self, key: str, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        with self._lock:
            items = self._events[key]
            while items and now - items[0] > self.window_seconds:
                items.popleft()
            items.append(now)
            return len(items) > self.max_count


class RepeatDetector:
    def __init__(self, max_count: int, window_seconds: float):
        self.max_count = max_count
        self.window_seconds = window_seconds
        self._events: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)
        self._lock = threading.RLock()

    def hit(self, key: str, text: str, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        normalized = _normalise_text(text)
        if not normalized:
            return False
        event_key = (key, normalized)
        with self._lock:
            items = self._events[event_key]
            while items and now - items[0] > self.window_seconds:
                items.popleft()
            items.append(now)
            return len(items) >= self.max_count


@dataclass(frozen=True)
class ModerationEvent:
    message_id: str
    chat_id: str
    chat_name: str
    sender_id: str
    sender_name: str
    text: str
    is_outgoing: bool
    is_group: bool
    is_private: bool
    is_channel: bool

    @classmethod
    def from_payload(cls, data: Dict[str, Any]) -> "ModerationEvent":
        return cls(
            message_id=str(data.get("message_id") or ""),
            chat_id=str(data.get("chat_id") or data.get("chat_name") or ""),
            chat_name=str(data.get("chat_name") or ""),
            sender_id=str(data.get("sender_id") or ""),
            sender_name=str(data.get("sender_name") or ""),
            text=str(data.get("text") or ""),
            is_outgoing=bool(data.get("is_outgoing")),
            is_group=bool(data.get("is_group")),
            is_private=bool(data.get("is_private")),
            is_channel=bool(data.get("is_channel")),
        )


class GroupModerator:
    def __init__(self, client: Any):
        self.client = client
        self.bad_words = load_bad_words()
        self.allowed_domains = load_allowed_domains()
        self.exempt_user_ids = load_exempt_user_ids()
        self.store = WarningStore(Path(SESSION_DIR) / "moderator_warnings.json")
        self.flood = SlidingWindowCounter(FLOOD_MAX, FLOOD_WINDOW)
        self.repeat = RepeatDetector(REPEAT_MAX, REPEAT_WINDOW)
        self.permission_cache: Dict[str, Tuple[float, bool]] = {}
        self.permission_lock = threading.RLock()
        self.stop_event = threading.Event()
        self.queue: "queue.Queue[ModerationEvent]" = queue.Queue(maxsize=QUEUE_MAX_SIZE)
        self.worker = threading.Thread(
            target=self._worker_loop,
            name="soropy-group-moderator",
            daemon=True,
        )

    def start(self) -> None:
        self.worker.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.worker.join(timeout=5)

    def on_event(self, event: Any) -> None:
        data = getattr(event, "data", None) or {}
        item = ModerationEvent.from_payload(data)
        if not self._belongs_to_target_group(item):
            return
        try:
            self.queue.put_nowait(item)
        except queue.Full:
            print("صف moderation پر است؛ پیام جدید نادیده گرفته شد.")

    def _belongs_to_target_group(self, item: ModerationEvent) -> bool:
        if item.is_outgoing or not item.is_group:
            return False
        return item.chat_name == GROUP_NAME or item.chat_id == GROUP_NAME

    def _worker_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                item = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.process(item)
            except Exception as exc:
                print(f"خطای moderation: {exc}")
            finally:
                self.queue.task_done()

    def _is_admin_or_creator(self, sender_id: str) -> bool:
        if not sender_id:
            return False
        if sender_id in self.exempt_user_ids:
            return True
        now = time.time()
        with self.permission_lock:
            cached = self.permission_cache.get(sender_id)
            if cached and now - cached[0] < PERMISSION_CACHE_TTL:
                return cached[1]
        is_admin = False
        try:
            perms = self.client.get_permissions(GROUP_TARGET, sender_id) or {}
            is_admin = bool(perms.get("is_admin") or perms.get("is_creator"))
        except Exception as exc:
            print(f"بررسی دسترسی مدیر برای {sender_id} ناموفق بود: {exc}")
        with self.permission_lock:
            self.permission_cache[sender_id] = (now, is_admin)
        return is_admin

    def _reply_or_send(self, item: ModerationEvent, text: str) -> None:
        try:
            if item.message_id:
                self.client.reply(GROUP_TARGET, item.message_id, text)
            else:
                self.client.send_message(GROUP_TARGET, text)
        except Exception as exc:
            print(f"ارسال پاسخ moderation ناموفق بود: {exc}")

    def _delete_message(self, item: ModerationEvent) -> None:
        if not item.message_id:
            return
        try:
            self.client.delete_messages(GROUP_TARGET, [item.message_id], revoke=True)
        except Exception as exc:
            print(f"حذف پیام {item.message_id} ناموفق بود: {exc}")

    def _warn(self, item: ModerationEvent, reason: str) -> None:
        self._delete_message(item)
        count = self.store.increment(item.chat_id, item.sender_id, reason)
        if count >= MAX_WARNINGS:
            try:
                if self.client.kick(GROUP_TARGET, item.sender_id):
                    self.store.clear(item.chat_id, item.sender_id)
                    self.client.send_message(
                        GROUP_TARGET,
                        f"کاربر {item.sender_id} به دلیل {MAX_WARNINGS} اخطار از گروه حذف شد.",
                    )
                else:
                    self.client.send_message(
                        GROUP_TARGET,
                        "حذف کاربر ناموفق بود. لطفاً دسترسی ادمین ربات را بررسی کنید.",
                    )
            except Exception as exc:
                self.client.send_message(
                    GROUP_TARGET,
                    f"حذف کاربر ناموفق بود؛ دسترسی ادمین را بررسی کنید. خطا: {exc}",
                )
            return
        self._reply_or_send(
            item,
            f"⚠️ اخطار {count}/{MAX_WARNINGS} برای {item.sender_name or item.sender_id}: {reason}",
        )

    def _handle_command(self, item: ModerationEvent) -> bool:
        text = item.text.strip()
        if not text.startswith("/"):
            return False
        if not self._is_admin_or_creator(item.sender_id):
            return True
        parts = text.split(maxsplit=1)
        command = parts[0].casefold()
        arg = parts[1].strip() if len(parts) > 1 else ""
        if command == "/rules":
            self._reply_or_send(
                item,
                "قوانین: ارسال لینک غیرمجاز، واژه ممنوع، flood و تکرار متن ممنوع است.",
            )
        elif command == "/warnings":
            self._reply_or_send(item, self.store.summary(item.chat_id))
        elif command == "/forgive" and arg:
            ok = self.store.clear(item.chat_id, arg)
            self._reply_or_send(item, "اخطارها پاک شد." if ok else "اخطاری یافت نشد.")
        elif command == "/kick" and arg:
            self._reply_or_send(item, "کاربر حذف شد." if self.client.kick(GROUP_TARGET, arg) else "kick ناموفق بود.")
        elif command == "/ban" and arg:
            self._reply_or_send(item, "کاربر ban شد." if self.client.ban(GROUP_TARGET, arg) else "ban ناموفق بود.")
        else:
            return False
        return True

    def process(self, item: ModerationEvent) -> None:
        if self._handle_command(item):
            return
        if not item.sender_id or self._is_admin_or_creator(item.sender_id):
            return
        key = WarningStore.key(item.chat_id, item.sender_id)
        if contains_bad_word(item.text, self.bad_words):
            self._warn(item, "استفاده از واژه ممنوع")
            return
        if contains_disallowed_link(item.text, self.allowed_domains):
            self._warn(item, "ارسال لینک غیرمجاز")
            return
        if self.flood.hit(key):
            self._warn(item, "ارسال پیام بیش از حد مجاز")
            return
        if self.repeat.hit(key, item.text):
            self._warn(item, "تکرار یک متن")


def main() -> None:
    from soropy import SoroushClient

    client = SoroushClient(
        PHONE,
        backend="websocket",
        session_dir=SESSION_DIR,
        auto_reply_private_only=True,
    )
    moderator = GroupModerator(client)

    def _shutdown(_signum: int, _frame: Any) -> None:
        moderator.stop_event.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        client.on("new_message", moderator.on_event)
        client.login(
            code_callback=lambda: input(
                "کد پیامک‌شده: "
            ).strip()
        )
        moderator.start()
        print("مدیر گروه فعال شد. برای خروج Ctrl+C بزنید.")
        while not moderator.stop_event.is_set():
            time.sleep(0.5)
    finally:
        moderator.stop()
        client.close()


if __name__ == "__main__":
    main()
