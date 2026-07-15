"""
╔══════════════════════════════════════════════════════════════╗
║          🤖 SoroBot Ultra - مدیر گروه هوشمند سروش           ║
║                    نسخه 2.0.0 Ultimate                       ║
║                                                              ║
║  کتابخانه: SoroPy 1.3.4 (WebSocket Backend)                 ║
║  پیام‌رسان: سروش (Soroush Messenger)                        ║
╚══════════════════════════════════════════════════════════════╝

قابلیت‌های جدید:
━━━━━━━━━━━━━━━━
🛡️  سیستم امنیتی:
    - ضد لینک با allowlist دامنه
    - ضد کلمه ممنوع با regex پیشرفته
    - ضد flood هوشمند
    - ضد تکرار متن
    - ضد فوروارد اسپم
    - ضد کاراکترهای نامرئی / یونیکد مخرب
    - ضد پیام طولانی (max length)
    - ضد CAPS LOCK (فارسی + انگلیسی)
    - کشف شماره تلفن در متن
    - کشف ID تلگرام/سروش
    - Honeypot: تله برای اسپمرها
    - Night Mode: محدودیت شبانه
    - Slow Mode: تاخیر اجباری بین پیام‌ها
    - Captcha برای اعضای جدید
    - Anti-Raid: تشخیص حمله گروهی

👥  مدیریت اعضا:
    - سیستم اخطار persistent
    - banlist persistent
    - mute با زمان‌بندی
    - ban واقعی + fallback به kick
    - سطح‌بندی ادمین‌ها (Owner/Admin/Mod)
    - گزارش‌گیری از کاربران
    - نمایش پروفایل کاربر
    - VIP list (لیست سفید کاربران)

📊  آمار و گزارش:
    - آمار پیام روزانه/هفتگی/ماهانه
    - فعال‌ترین کاربران
    - بیشترین تخلفات
    - گزارش زنده وضعیت
    - لاگ تمام اقدامات

🎮  تعاملی:
    - خوش‌آمدگویی خودکار
    - خداحافظی خودکار
    - پاسخ خودکار به سوالات متداول (FAQ)
    - یادآوری زمان‌دار
    - نظرسنجی
    - قرعه‌کشی
    - سیستم XP و لول
    - سیستم سکه و اقتصاد
    - Daily reward
    - لیدربورد

🔧  مدیریتی:
    - پین/آنپین پیام
    - پاکسازی گروهی پیام‌ها
    - Broadcast پیام به همه
    - زمان‌بندی پیام
    - Backup/Restore تنظیمات
    - Multi-group support
    - Plugin system
    - Auto-respond patterns
    - Tag همه اعضا

نصب:
    pip install "soropy[ws]"

اجرا:
    $env:SOROPY_PHONE="09123456789"
    $env:SOROPY_GROUP_ID="-1000023018884"
    $env:SOROPY_GROUP_TARGET="-1000023018884"
    python sorobot_ultra.py
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import queue
import random
import re
import signal
import string
import threading
import time
import traceback
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from pathlib import Path
from typing import (
    Any,
    Callable,
    Deque,
    Dict,
    Iterable,
    List,
    Optional,
    Set,
    Tuple,
    Union,
)


# ╔══════════════════════════════════════════════════════╗
# ║                   تنظیمات اصلی                      ║
# ╚══════════════════════════════════════════════════════╝

PHONE = os.getenv("SOROPY_PHONE", "09038013654")
GROUP_ID = os.getenv("SOROPY_GROUP_ID", "").strip()
GROUP_NAME = os.getenv(
    "SOROPY_GROUP", "انجمن توسعه‌دهندگان | SoroPy"
).strip()
GROUP_TARGET = os.getenv("SOROPY_GROUP_TARGET", "@soropy").strip()

OWNER_USER_IDS = {
    "67775869",  # آیدی مالک اصلی
}

GROUP_ALIASES = os.getenv("SOROPY_GROUP_ALIASES", "").strip()
SESSION_DIR = os.getenv("SOROPY_SESSION_DIR", "soropy_ws_sessions")
STATE_PATH = Path(SESSION_DIR) / "moderator_state_v2.json"
LOG_PATH = Path(SESSION_DIR) / "moderator_log.jsonl"
BACKUP_DIR = Path(SESSION_DIR) / "backups"

# ── حدود و تنظیمات ──
DEFAULT_MAX_WARNINGS = int(os.getenv("SOROPY_MAX_WARNINGS", "3"))
FLOOD_MAX = int(os.getenv("SOROPY_FLOOD_MAX", "6"))
FLOOD_WINDOW = float(os.getenv("SOROPY_FLOOD_WINDOW", "8"))
REPEAT_MAX = int(os.getenv("SOROPY_REPEAT_MAX", "3"))
REPEAT_WINDOW = float(os.getenv("SOROPY_REPEAT_WINDOW", "30"))
PERMISSION_CACHE_TTL = float(os.getenv("SOROPY_PERMISSION_CACHE_TTL", "60"))
QUEUE_MAX_SIZE = int(os.getenv("SOROPY_QUEUE_MAX_SIZE", "1000"))

# ── تنظیمات جدید ──
MAX_MESSAGE_LENGTH = int(os.getenv("SOROPY_MAX_MSG_LEN", "4000"))
CAPS_RATIO_THRESHOLD = float(os.getenv("SOROPY_CAPS_RATIO", "0.7"))
CAPS_MIN_LENGTH = int(os.getenv("SOROPY_CAPS_MIN_LEN", "10"))
SLOW_MODE_SECONDS = float(os.getenv("SOROPY_SLOW_MODE", "0"))
NIGHT_MODE_START = int(os.getenv("SOROPY_NIGHT_START", "23"))
NIGHT_MODE_END = int(os.getenv("SOROPY_NIGHT_END", "6"))
WELCOME_ENABLED = os.getenv("SOROPY_WELCOME", "true").strip().lower() in {
    "1", "true", "yes"
}
XP_PER_MESSAGE = int(os.getenv("SOROPY_XP_PER_MSG", "10"))
XP_PER_LEVEL = int(os.getenv("SOROPY_XP_PER_LEVEL", "100"))
DAILY_REWARD_COINS = int(os.getenv("SOROPY_DAILY_COINS", "50"))
ANTI_RAID_THRESHOLD = int(os.getenv("SOROPY_RAID_THRESHOLD", "10"))
ANTI_RAID_WINDOW = float(os.getenv("SOROPY_RAID_WINDOW", "30"))
CAPTCHA_ENABLED = os.getenv("SOROPY_CAPTCHA", "false").strip().lower() in {
    "1", "true", "yes"
}
CAPTCHA_TIMEOUT = int(os.getenv("SOROPY_CAPTCHA_TIMEOUT", "120"))

MODERATE_ALL_GROUPS = os.getenv(
    "SOROPY_MODERATE_ALL_GROUPS", "false"
).strip().lower() in {"1", "true", "yes"}

DEBUG = os.getenv("SOROPY_DEBUG", "true").strip().lower() in {
    "1", "true", "yes"
}

PROCESS_OUTGOING_FOR_TEST = os.getenv(
    "SOROPY_PROCESS_OUTGOING", "false"
).strip().lower() in {"1", "true", "yes"}

PROCESS_ADMINS_FOR_TEST = os.getenv(
    "SOROPY_PROCESS_ADMINS", "false"
).strip().lower() in {"1", "true", "yes"}

ENFORCE_LOCAL_BANLIST = os.getenv(
    "SOROPY_ENFORCE_BANLIST", "true"
).strip().lower() in {"1", "true", "yes"}

DEFAULT_BAD_WORDS = {
    "خر", "گاو", "بیشعور", "کص", "لاشی", "سگ", "کس",
    "جنده", "کیر", "کون", "خایه", "سوراخ", "هک", "تبلیغ",
}
DEFAULT_ALLOWED_DOMAINS: Set[str] = set()

# ── ایموجی‌ها ──
EMOJI = {
    "warn": "⚠️",
    "ban": "⛔",
    "kick": "🦵",
    "mute": "🔇",
    "unmute": "🔊",
    "check": "✅",
    "cross": "❌",
    "star": "⭐",
    "trophy": "🏆",
    "medal": "🥇",
    "fire": "🔥",
    "shield": "🛡️",
    "robot": "🤖",
    "wave": "👋",
    "coin": "🪙",
    "gem": "💎",
    "heart": "❤️",
    "chart": "📊",
    "pin": "📌",
    "clock": "⏰",
    "lock": "🔒",
    "unlock": "🔓",
    "party": "🎉",
    "dice": "🎲",
    "crown": "👑",
    "muscle": "💪",
    "brain": "🧠",
    "target": "🎯",
    "bell": "🔔",
    "gift": "🎁",
    "note": "📝",
    "folder": "📁",
    "search": "🔍",
    "bulb": "💡",
    "moon": "🌙",
    "sun": "☀️",
    "thunder": "⚡",
    "boom": "💥",
    "skull": "💀",
    "ghost": "👻",
    "detective": "🕵️",
    "link": "🔗",
    "no_entry": "🚫",
    "up": "📈",
    "down": "📉",
    "new": "🆕",
    "id": "🆔",
    "info": "ℹ️",
    "question": "❓",
    "exclaim": "❗",
    "hourglass": "⏳",
    "rocket": "🚀",
    "rainbow": "🌈",
    "sparkle": "✨",
}


# ╔══════════════════════════════════════════════════════╗
# ║                    Regex ها                          ║
# ╚══════════════════════════════════════════════════════╝

_LINK_RE = re.compile(
    r"(?ix)"
    r"(https?://[^\s]+|www\.[^\s]+|"
    r"(?:t\.me|telegram\.me|ble\.ir|splus\.ir|rubika\.ir)(?:/[^\s]*)?|"
    r"\b[a-z0-9][a-z0-9-]*(?:\.[a-z0-9][a-z0-9-]*)+"
    r"\.(?:com|net|org|ir|io|me|co|info|biz|xyz|top|club|site|online|app|dev)(?:/[^\s]*)?)"
)

_DOMAIN_RE = re.compile(r"(?i)^(?:https?://)?(?:www\.)?([^/:?#\s]+)")

_PHONE_RE = re.compile(
    r"(?:^|[\s\u200c])(?:\+98|0098|09)\d{9}(?:$|[\s\u200c])"
)

_INVISIBLE_RE = re.compile(
    r"[\u200b\u200d\u2060\u2061\u2062\u2063\u2064\ufeff\u034f\u180e]"
)

_TELEGRAM_ID_RE = re.compile(r"@[a-zA-Z][a-zA-Z0-9_]{3,31}")

_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
)


# ╔══════════════════════════════════════════════════════╗
# ║                   Enums                              ║
# ╚══════════════════════════════════════════════════════╝

class AdminLevel(Enum):
    MEMBER = 0
    MOD = 1
    ADMIN = 2
    OWNER = 3

    def __ge__(self, other: "AdminLevel") -> bool:
        return self.value >= other.value

    def __gt__(self, other: "AdminLevel") -> bool:
        return self.value > other.value

    def __le__(self, other: "AdminLevel") -> bool:
        return self.value <= other.value

    def __lt__(self, other: "AdminLevel") -> bool:
        return self.value < other.value


class ViolationType(Enum):
    BAD_WORD = auto()
    LINK = auto()
    FLOOD = auto()
    REPEAT = auto()
    CAPS = auto()
    LONG_MESSAGE = auto()
    PHONE_NUMBER = auto()
    INVISIBLE_CHARS = auto()
    TELEGRAM_ID = auto()
    NIGHT_MODE = auto()
    SLOW_MODE = auto()
    FORWARD_SPAM = auto()
    BANNED_USER = auto()


# ╔══════════════════════════════════════════════════════╗
# ║                   Helper ها                          ║
# ╚══════════════════════════════════════════════════════╝

def log_debug(*args: Any) -> None:
    if DEBUG:
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[DEBUG {ts}]", *args)


def log_action(action: str, details: Dict[str, Any]) -> None:
    """لاگ اقدامات در فایل JSONL"""
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            **details,
        }
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def csv_env(name: str) -> List[str]:
    value = os.getenv(name, "")
    return [item.strip() for item in value.split(",") if item.strip()]


def normalise_text(text: str) -> str:
    text = str(text or "")
    for ch in "\u200c\u200f\u200e\u200b\u200d":
        text = text.replace(ch, " ")
    return " ".join(text.casefold().split())


def normalise_domain(domain: str) -> str:
    return (
        str(domain or "")
        .lower()
        .strip()
        .strip(".")
        .lstrip("@")
        .replace("www.", "", 1)
    )


def initial_bad_words() -> Set[str]:
    configured = csv_env("SOROPY_BAD_WORDS")
    return set(configured) if configured else set(DEFAULT_BAD_WORDS)


def initial_allowed_domains() -> Set[str]:
    configured = csv_env("SOROPY_ALLOWED_DOMAINS")
    return (
        {normalise_domain(i) for i in configured}
        if configured
        else set(DEFAULT_ALLOWED_DOMAINS)
    )


def exempt_user_ids() -> Set[str]:
    return set(csv_env("SOROPY_EXEMPT_USER_IDS"))


def group_match_values() -> Set[str]:
    values = set()
    for item in [GROUP_ID, GROUP_NAME, GROUP_TARGET]:
        item = str(item or "").strip()
        if item:
            values.add(item)
            values.add(normalise_text(item))
    for item in GROUP_ALIASES.split(","):
        item = item.strip()
        if item:
            values.add(item)
            values.add(normalise_text(item))
    return values


def contains_bad_word(text: str, bad_words: Iterable[str]) -> Optional[str]:
    needle = normalise_text(text)
    for word in bad_words:
        word_norm = normalise_text(word)
        if word_norm and word_norm in needle:
            return word
    return None


def extract_links(text: str) -> List[str]:
    return [
        match.group(0).rstrip(".,؛،)")
        for match in _LINK_RE.finditer(text or "")
    ]


def domain_from_link(link: str) -> str:
    cleaned = link.strip()
    if cleaned.startswith("www."):
        cleaned = "https://" + cleaned
    match = _DOMAIN_RE.search(cleaned)
    domain = match.group(1) if match else cleaned
    return normalise_domain(domain)


def domain_allowed(domain: str, allowed_domains: Set[str]) -> bool:
    if not allowed_domains:
        return False
    domain = normalise_domain(domain)
    return any(
        domain == a or domain.endswith("." + a) for a in allowed_domains
    )


def find_disallowed_link(
    text: str, allowed_domains: Set[str]
) -> Optional[str]:
    for link in extract_links(text):
        domain = domain_from_link(link)
        if not domain_allowed(domain, allowed_domains):
            return link
    return None


def contains_phone_number(text: str) -> bool:
    return bool(_PHONE_RE.search(text or ""))


def contains_invisible_chars(text: str) -> bool:
    matches = _INVISIBLE_RE.findall(text or "")
    return len(matches) > 5


def contains_telegram_id(text: str) -> Optional[str]:
    match = _TELEGRAM_ID_RE.search(text or "")
    return match.group(0) if match else None


def is_caps_abuse(text: str) -> bool:
    # برای فارسی CAPS معنا ندارد، فقط انگلیسی
    alpha_chars = [c for c in text if c.isalpha() and c.isascii()]
    if len(alpha_chars) < CAPS_MIN_LENGTH:
        return False
    upper_count = sum(1 for c in alpha_chars if c.isupper())
    return (upper_count / len(alpha_chars)) > CAPS_RATIO_THRESHOLD


def is_night_time() -> bool:
    hour = datetime.now().hour
    if NIGHT_MODE_START > NIGHT_MODE_END:
        return hour >= NIGHT_MODE_START or hour < NIGHT_MODE_END
    return NIGHT_MODE_START <= hour < NIGHT_MODE_END


def now_ts() -> int:
    return int(time.time())


def generate_captcha() -> Tuple[str, str]:
    """یک سوال ساده ریاضی"""
    a = random.randint(1, 20)
    b = random.randint(1, 20)
    op = random.choice(["+", "-"])
    if op == "+":
        answer = a + b
    else:
        if a < b:
            a, b = b, a
        answer = a - b
    question = f"{a} {op} {b} = ?"
    return question, str(answer)


def random_welcome_message(name: str) -> str:
    messages = [
        f"{EMOJI['wave']} سلام {name} عزیز! به گروه خوش اومدی!",
        f"{EMOJI['party']} خوش اومدی {name}! از حضورت خوشحالیم {EMOJI['heart']}",
        f"{EMOJI['star']} {name} وارد شد! به جمع ما خوش اومدی {EMOJI['sparkle']}",
        f"{EMOJI['rocket']} {name} به ما پیوست! بفرمایید {EMOJI['rainbow']}",
        f"{EMOJI['fire']} {name} اومد! گروه گرم‌تر شد {EMOJI['muscle']}",
        f"{EMOJI['crown']} سلام {name}! خوشحالیم که اینجایی {EMOJI['gem']}",
        f"{EMOJI['thunder']} {name} وارد میدان شد! {EMOJI['boom']}",
    ]
    return random.choice(messages)


def random_goodbye_message(name: str) -> str:
    messages = [
        f"{EMOJI['wave']} خداحافظ {name}! امیدواریم دوباره ببینیمت.",
        f"😢 {name} رفت... دلمون تنگ میشه!",
        f"👋 {name} گروه رو ترک کرد. موفق باشی!",
    ]
    return random.choice(messages)


def level_from_xp(xp: int) -> int:
    return max(1, xp // XP_PER_LEVEL + 1)


def xp_progress(xp: int) -> str:
    level = level_from_xp(xp)
    current = xp % XP_PER_LEVEL
    bar_len = 10
    filled = int((current / XP_PER_LEVEL) * bar_len)
    bar = "█" * filled + "░" * (bar_len - filled)
    return f"Level {level} [{bar}] {current}/{XP_PER_LEVEL}"


def format_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} ثانیه"
    elif seconds < 3600:
        return f"{seconds // 60} دقیقه"
    elif seconds < 86400:
        return f"{seconds // 3600} ساعت و {(seconds % 3600) // 60} دقیقه"
    else:
        return f"{seconds // 86400} روز"


# ╔══════════════════════════════════════════════════════╗
# ║              Auto-Response Engine                    ║
# ╚══════════════════════════════════════════════════════╝

class AutoResponder:
    """پاسخ خودکار بر اساس الگو"""

    def __init__(self) -> None:
        self._patterns: List[Tuple[re.Pattern, str]] = []
        self._lock = threading.RLock()
        self._load_defaults()

    def _load_defaults(self) -> None:
        defaults = [
            (r"سلام|درود|هلو", f"{EMOJI['wave']} سلام! خوش اومدی!"),
            (
                r"قوانین|قانون|رول",
                f"{EMOJI['pin']} برای مشاهده قوانین: /rules",
            ),
            (
                r"ادمین.*کیه|مدیر.*کیه",
                f"{EMOJI['crown']} برای لیست ادمین‌ها: /admins",
            ),
            (
                r"چطوری.*عضو|عضویت",
                f"{EMOJI['info']} کافیه توی گروه فعال باشی!",
            ),
        ]
        for pattern, response in defaults:
            self._patterns.append(
                (re.compile(pattern, re.IGNORECASE), response)
            )

    def add_pattern(self, pattern: str, response: str) -> bool:
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
            with self._lock:
                self._patterns.append((compiled, response))
            return True
        except re.error:
            return False

    def remove_pattern(self, index: int) -> bool:
        with self._lock:
            if 0 <= index < len(self._patterns):
                self._patterns.pop(index)
                return True
            return False

    def check(self, text: str) -> Optional[str]:
        normalized = normalise_text(text)
        with self._lock:
            for pattern, response in self._patterns:
                if pattern.search(normalized):
                    return response
        return None

    def list_patterns(self) -> str:
        with self._lock:
            if not self._patterns:
                return "هیچ الگویی تنظیم نشده."
            lines = []
            for i, (pat, resp) in enumerate(self._patterns):
                lines.append(f"{i}. {pat.pattern} → {resp}")
            return "\n".join(lines)


# ╔══════════════════════════════════════════════════════╗
# ║              Scheduler (زمان‌بندی)                   ║
# ╚══════════════════════════════════════════════════════╝

@dataclass
class ScheduledTask:
    task_id: str
    execute_at: float
    action: str  # "send_message", "unmute", "unban", "reminder"
    params: Dict[str, Any] = field(default_factory=dict)
    recurring: bool = False
    interval: float = 0


class TaskScheduler:
    def __init__(self) -> None:
        self._tasks: Dict[str, ScheduledTask] = {}
        self._lock = threading.RLock()
        self._counter = 0

    def add_task(
        self,
        delay_seconds: float,
        action: str,
        params: Dict[str, Any],
        recurring: bool = False,
        interval: float = 0,
    ) -> str:
        with self._lock:
            self._counter += 1
            task_id = f"task_{self._counter}_{now_ts()}"
            self._tasks[task_id] = ScheduledTask(
                task_id=task_id,
                execute_at=time.time() + delay_seconds,
                action=action,
                params=params,
                recurring=recurring,
                interval=interval,
            )
            return task_id

    def cancel_task(self, task_id: str) -> bool:
        with self._lock:
            return self._tasks.pop(task_id, None) is not None

    def get_due_tasks(self) -> List[ScheduledTask]:
        now = time.time()
        due = []
        with self._lock:
            for task_id, task in list(self._tasks.items()):
                if now >= task.execute_at:
                    due.append(task)
                    if task.recurring and task.interval > 0:
                        task.execute_at = now + task.interval
                    else:
                        del self._tasks[task_id]
        return due

    def list_tasks(self) -> str:
        with self._lock:
            if not self._tasks:
                return "هیچ تسکی زمان‌بندی نشده."
            lines = []
            now = time.time()
            for task in sorted(
                self._tasks.values(), key=lambda t: t.execute_at
            ):
                remaining = max(0, int(task.execute_at - now))
                lines.append(
                    f"{task.task_id}: {task.action} "
                    f"(باقی: {format_duration(remaining)})"
                    f"{' 🔄' if task.recurring else ''}"
                )
            return "\n".join(lines)


# ╔══════════════════════════════════════════════════════╗
# ║           Sliding Window / Detectors                 ║
# ╚══════════════════════════════════════════════════════╝

class SlidingWindowCounter:
    def __init__(self, max_count: int, window_seconds: float):
        self.max_count = max_count
        self.window_seconds = window_seconds
        self._events: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.RLock()

    def hit(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            items = self._events[key]
            while items and now - items[0] > self.window_seconds:
                items.popleft()
            items.append(now)
            return len(items) > self.max_count

    def count(self, key: str) -> int:
        now = time.time()
        with self._lock:
            items = self._events[key]
            while items and now - items[0] > self.window_seconds:
                items.popleft()
            return len(items)

    def reset(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)


class RepeatDetector:
    def __init__(self, max_count: int, window_seconds: float):
        self.max_count = max_count
        self.window_seconds = window_seconds
        self._events: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)
        self._lock = threading.RLock()

    def hit(self, key: str, text: str) -> bool:
        now = time.time()
        normalized = normalise_text(text)
        if not normalized:
            return False
        event_key = (key, normalized)
        with self._lock:
            items = self._events[event_key]
            while items and now - items[0] > self.window_seconds:
                items.popleft()
            items.append(now)
            return len(items) >= self.max_count


class RaidDetector:
    """تشخیص حمله گروهی (ورود سریع تعداد زیاد)"""

    def __init__(
        self,
        threshold: int = ANTI_RAID_THRESHOLD,
        window: float = ANTI_RAID_WINDOW,
    ):
        self.threshold = threshold
        self.window = window
        self._joins: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.RLock()
        self.raid_active: Dict[str, bool] = {}

    def record_join(self, chat_id: str) -> bool:
        now = time.time()
        with self._lock:
            items = self._joins[chat_id]
            while items and now - items[0] > self.window:
                items.popleft()
            items.append(now)
            is_raid = len(items) >= self.threshold
            if is_raid:
                self.raid_active[chat_id] = True
            return is_raid

    def is_raid(self, chat_id: str) -> bool:
        with self._lock:
            return self.raid_active.get(chat_id, False)

    def end_raid(self, chat_id: str) -> None:
        with self._lock:
            self.raid_active[chat_id] = False
            self._joins.pop(chat_id, None)


class SlowModeTracker:
    """ردیابی slow mode"""

    def __init__(self, interval: float = SLOW_MODE_SECONDS):
        self.interval = interval
        self._last_message: Dict[str, float] = {}
        self._lock = threading.RLock()

    def check(self, key: str) -> Tuple[bool, float]:
        """آیا خیلی زود پیام داده؟ True = تخلف"""
        if self.interval <= 0:
            return False, 0
        now = time.time()
        with self._lock:
            last = self._last_message.get(key, 0)
            elapsed = now - last
            if elapsed < self.interval:
                return True, self.interval - elapsed
            self._last_message[key] = now
            return False, 0

    def set_interval(self, seconds: float) -> None:
        self.interval = max(0, seconds)


# ╔══════════════════════════════════════════════════════╗
# ║               Captcha Manager                        ║
# ╚══════════════════════════════════════════════════════╝

@dataclass
class CaptchaChallenge:
    user_id: str
    chat_id: str
    question: str
    answer: str
    created_at: float
    attempts: int = 0


class CaptchaManager:
    def __init__(self) -> None:
        self._challenges: Dict[str, CaptchaChallenge] = {}
        self._lock = threading.RLock()

    def create_challenge(
        self, chat_id: str, user_id: str
    ) -> CaptchaChallenge:
        question, answer = generate_captcha()
        challenge = CaptchaChallenge(
            user_id=user_id,
            chat_id=chat_id,
            question=question,
            answer=answer,
            created_at=time.time(),
        )
        key = f"{chat_id}:{user_id}"
        with self._lock:
            self._challenges[key] = challenge
        return challenge

    def check_answer(
        self, chat_id: str, user_id: str, answer: str
    ) -> Optional[bool]:
        key = f"{chat_id}:{user_id}"
        with self._lock:
            challenge = self._challenges.get(key)
            if not challenge:
                return None
            challenge.attempts += 1
            if answer.strip() == challenge.answer:
                del self._challenges[key]
                return True
            if challenge.attempts >= 3:
                del self._challenges[key]
                return False
            return False

    def has_pending(self, chat_id: str, user_id: str) -> bool:
        key = f"{chat_id}:{user_id}"
        with self._lock:
            challenge = self._challenges.get(key)
            if not challenge:
                return False
            if time.time() - challenge.created_at > CAPTCHA_TIMEOUT:
                del self._challenges[key]
                return False
            return True

    def get_expired(self) -> List[CaptchaChallenge]:
        now = time.time()
        expired = []
        with self._lock:
            for key, challenge in list(self._challenges.items()):
                if now - challenge.created_at > CAPTCHA_TIMEOUT:
                    expired.append(challenge)
                    del self._challenges[key]
        return expired


# ╔══════════════════════════════════════════════════════╗
# ║                 Poll Manager                         ║
# ╚══════════════════════════════════════════════════════╝

@dataclass
class Poll:
    poll_id: str
    chat_id: str
    question: str
    options: List[str]
    votes: Dict[str, int]  # user_id -> option_index
    created_by: str
    created_at: float
    active: bool = True


class PollManager:
    def __init__(self) -> None:
        self._polls: Dict[str, Poll] = {}
        self._active_poll: Dict[str, str] = {}  # chat_id -> poll_id
        self._lock = threading.RLock()
        self._counter = 0

    def create_poll(
        self,
        chat_id: str,
        question: str,
        options: List[str],
        created_by: str,
    ) -> Poll:
        with self._lock:
            self._counter += 1
            poll_id = f"poll_{self._counter}"

            # بستن poll قبلی
            old_id = self._active_poll.get(chat_id)
            if old_id and old_id in self._polls:
                self._polls[old_id].active = False

            poll = Poll(
                poll_id=poll_id,
                chat_id=chat_id,
                question=question,
                options=options,
                votes={},
                created_by=created_by,
                created_at=time.time(),
            )
            self._polls[poll_id] = poll
            self._active_poll[chat_id] = poll_id
            return poll

    def vote(
        self, chat_id: str, user_id: str, option_index: int
    ) -> Optional[str]:
        with self._lock:
            poll_id = self._active_poll.get(chat_id)
            if not poll_id:
                return None
            poll = self._polls.get(poll_id)
            if not poll or not poll.active:
                return None
            if option_index < 0 or option_index >= len(poll.options):
                return None
            poll.votes[user_id] = option_index
            return poll.options[option_index]

    def close_poll(self, chat_id: str) -> Optional[str]:
        with self._lock:
            poll_id = self._active_poll.get(chat_id)
            if not poll_id:
                return None
            poll = self._polls.get(poll_id)
            if not poll:
                return None
            poll.active = False

            # شمارش آرا
            counts: Counter = Counter()
            for opt_idx in poll.votes.values():
                counts[opt_idx] += 1

            lines = [f"{EMOJI['chart']} نتیجه نظرسنجی: {poll.question}\n"]
            total = sum(counts.values()) or 1
            for i, option in enumerate(poll.options):
                count = counts.get(i, 0)
                pct = count / total * 100
                bar_len = 10
                filled = int(pct / 100 * bar_len)
                bar = "█" * filled + "░" * (bar_len - filled)
                lines.append(
                    f"  {i + 1}. {option}: [{bar}] {count} رأی ({pct:.0f}%)"
                )
            lines.append(f"\nکل آرا: {sum(counts.values())}")
            return "\n".join(lines)

    def get_active(self, chat_id: str) -> Optional[Poll]:
        with self._lock:
            poll_id = self._active_poll.get(chat_id)
            if poll_id:
                poll = self._polls.get(poll_id)
                if poll and poll.active:
                    return poll
        return None

    def format_poll(self, poll: Poll) -> str:
        lines = [f"{EMOJI['chart']} نظرسنجی: {poll.question}\n"]
        for i, option in enumerate(poll.options):
            lines.append(f"  {i + 1}. {option}")
        lines.append(f"\nبرای رأی دادن: /vote شماره_گزینه")
        return "\n".join(lines)


# ╔══════════════════════════════════════════════════════╗
# ║              Lottery Manager                         ║
# ╚══════════════════════════════════════════════════════╝

class LotteryManager:
    def __init__(self) -> None:
        self._participants: Dict[str, Set[str]] = {}  # chat_id -> set of user_ids
        self._lock = threading.RLock()

    def join(self, chat_id: str, user_id: str) -> int:
        with self._lock:
            p = self._participants.setdefault(chat_id, set())
            p.add(user_id)
            return len(p)

    def draw(self, chat_id: str, count: int = 1) -> List[str]:
        with self._lock:
            p = self._participants.get(chat_id, set())
            if not p:
                return []
            winners = random.sample(list(p), min(count, len(p)))
            self._participants.pop(chat_id, None)
            return winners

    def count(self, chat_id: str) -> int:
        with self._lock:
            return len(self._participants.get(chat_id, set()))

    def reset(self, chat_id: str) -> None:
        with self._lock:
            self._participants.pop(chat_id, None)


# ╔══════════════════════════════════════════════════════╗
# ║                 Event Model                          ║
# ╚══════════════════════════════════════════════════════╝

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
    is_forwarded: bool = False
    is_join: bool = False
    is_leave: bool = False
    media_type: str = ""
    reply_to_id: str = ""

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
            is_forwarded=bool(data.get("is_forwarded") or data.get("fwd_from")),
            is_join=bool(data.get("is_join") or data.get("user_joined")),
            is_leave=bool(data.get("is_leave") or data.get("user_left")),
            media_type=str(data.get("media_type") or ""),
            reply_to_id=str(data.get("reply_to_msg_id") or ""),
        )


# ╔══════════════════════════════════════════════════════╗
# ║               State Store V2                         ║
# ╚══════════════════════════════════════════════════════╝

class ModeratorState:
    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = {}
        self._load()
        self._ensure_defaults()

    def _ensure_defaults(self) -> None:
        with self._lock:
            self._data.setdefault("warnings", {})
            self._data.setdefault("banned", {})
            self._data.setdefault("muted", {})
            self._data.setdefault("config", {})
            self._data.setdefault("users", {})
            self._data.setdefault("stats", {})
            self._data.setdefault("vip", {})
            self._data.setdefault("mods", {})
            self._data.setdefault("notes", {})
            self._data.setdefault("faq", {})
            self._data.setdefault("auto_responses", [])

            config = self._data["config"]
            config.setdefault("max_warnings", DEFAULT_MAX_WARNINGS)
            config.setdefault("bad_words", sorted(initial_bad_words()))
            config.setdefault("allowed_domains", sorted(initial_allowed_domains()))
            config.setdefault("welcome_enabled", WELCOME_ENABLED)
            config.setdefault("welcome_message", "")
            config.setdefault("goodbye_enabled", True)
            config.setdefault("anti_link", True)
            config.setdefault("anti_badword", True)
            config.setdefault("anti_flood", True)
            config.setdefault("anti_repeat", True)
            config.setdefault("anti_caps", True)
            config.setdefault("anti_longmsg", True)
            config.setdefault("anti_phone", True)
            config.setdefault("anti_invisible", True)
            config.setdefault("anti_forward_spam", False)
            config.setdefault("night_mode", False)
            config.setdefault("slow_mode", SLOW_MODE_SECONDS)
            config.setdefault("captcha", CAPTCHA_ENABLED)
            config.setdefault("anti_raid", True)
            config.setdefault("xp_enabled", True)

            self._save()

    def _load(self) -> None:
        with self._lock:
            if not self.path.exists():
                self._data = {}
                return
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                self._data = raw if isinstance(raw, dict) else {}
            except Exception as exc:
                print("خطا در خواندن state:", repr(exc))
                self._data = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)

    @staticmethod
    def user_key(chat_id: str, user_id: str) -> str:
        return f"{chat_id}:{user_id}"

    # ── config toggles ────────────────────────────────

    def get_toggle(self, name: str) -> bool:
        with self._lock:
            return bool(self._data["config"].get(name, False))

    def set_toggle(self, name: str, value: bool) -> None:
        with self._lock:
            self._data["config"][name] = value
            self._save()

    # ── config values ─────────────────────────────────

    @property
    def max_warnings(self) -> int:
        with self._lock:
            return int(
                self._data["config"].get("max_warnings", DEFAULT_MAX_WARNINGS)
            )

    def set_max_warnings(self, value: int) -> None:
        with self._lock:
            self._data["config"]["max_warnings"] = max(1, int(value))
            self._save()

    def bad_words(self) -> Set[str]:
        with self._lock:
            return set(self._data["config"].get("bad_words", []))

    def add_bad_word(self, word: str) -> None:
        word = str(word or "").strip()
        if not word:
            return
        with self._lock:
            words = set(self._data["config"].get("bad_words", []))
            words.add(word)
            self._data["config"]["bad_words"] = sorted(words)
            self._save()

    def remove_bad_word(self, word: str) -> bool:
        word = str(word or "").strip()
        with self._lock:
            words = set(self._data["config"].get("bad_words", []))
            existed = word in words
            words.discard(word)
            self._data["config"]["bad_words"] = sorted(words)
            self._save()
            return existed

    def allowed_domains(self) -> Set[str]:
        with self._lock:
            return set(self._data["config"].get("allowed_domains", []))

    def add_allowed_domain(self, domain: str) -> None:
        domain = normalise_domain(domain)
        if not domain:
            return
        with self._lock:
            domains = set(self._data["config"].get("allowed_domains", []))
            domains.add(domain)
            self._data["config"]["allowed_domains"] = sorted(domains)
            self._save()

    def remove_allowed_domain(self, domain: str) -> bool:
        domain = normalise_domain(domain)
        with self._lock:
            domains = set(self._data["config"].get("allowed_domains", []))
            existed = domain in domains
            domains.discard(domain)
            self._data["config"]["allowed_domains"] = sorted(domains)
            self._save()
            return existed

    # ── warnings ──────────────────────────────────────

    def increment_warning(
        self,
        chat_id: str,
        user_id: str,
        reason: str,
        name: str = "",
    ) -> int:
        key = self.user_key(chat_id, user_id)
        with self._lock:
            warnings = self._data["warnings"]
            item = warnings.setdefault(
                key,
                {
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "name": name,
                    "count": 0,
                    "reasons": [],
                    "updated_at": now_ts(),
                },
            )
            item["name"] = name or item.get("name", "")
            item["count"] = int(item.get("count", 0)) + 1
            item["updated_at"] = now_ts()
            item.setdefault("reasons", []).append(
                {"reason": reason, "timestamp": now_ts()}
            )
            self._save()
            return int(item["count"])

    def warning_count(self, chat_id: str, user_id: str) -> int:
        key = self.user_key(chat_id, user_id)
        with self._lock:
            return int(
                self._data["warnings"].get(key, {}).get("count", 0)
            )

    def clear_warnings(self, chat_id: str, user_id: str) -> bool:
        key = self.user_key(chat_id, user_id)
        with self._lock:
            existed = self._data["warnings"].pop(key, None) is not None
            self._save()
            return existed

    def warning_summary(self, chat_id: Optional[str] = None) -> str:
        with self._lock:
            rows = []
            for item in self._data["warnings"].values():
                if chat_id and str(item.get("chat_id")) != str(chat_id):
                    continue
                rows.append(
                    f"  {EMOJI['warn']} {item.get('user_id')} | "
                    f"{item.get('name') or '-'} | "
                    f"{item.get('count', 0)} اخطار"
                )
            return "\n".join(sorted(rows)) if rows else "هیچ اخطاری ثبت نشده."

    # ── banlist ───────────────────────────────────────

    def mark_banned(
        self,
        chat_id: str,
        user_id: str,
        reason: str,
        name: str = "",
    ) -> None:
        key = self.user_key(chat_id, user_id)
        with self._lock:
            self._data["banned"][key] = {
                "chat_id": chat_id,
                "user_id": user_id,
                "name": name,
                "reason": reason,
                "timestamp": now_ts(),
            }
            self._save()

    def unmark_banned(self, chat_id: str, user_id: str) -> bool:
        key = self.user_key(chat_id, user_id)
        with self._lock:
            existed = self._data["banned"].pop(key, None) is not None
            self._save()
            return existed

    def is_banned(self, chat_id: str, user_id: str) -> bool:
        key = self.user_key(chat_id, user_id)
        with self._lock:
            return key in self._data["banned"]

    def banlist_summary(self, chat_id: Optional[str] = None) -> str:
        with self._lock:
            rows = []
            for item in self._data["banned"].values():
                if chat_id and str(item.get("chat_id")) != str(chat_id):
                    continue
                rows.append(
                    f"  {EMOJI['ban']} {item.get('user_id')} | "
                    f"{item.get('name') or '-'} | "
                    f"{item.get('reason')}"
                )
            return "\n".join(sorted(rows)) if rows else "banlist خالی."

    # ── muted ─────────────────────────────────────────

    def mark_muted(
        self,
        chat_id: str,
        user_id: str,
        name: str = "",
        duration: int = 0,
    ) -> None:
        key = self.user_key(chat_id, user_id)
        with self._lock:
            self._data["muted"][key] = {
                "chat_id": chat_id,
                "user_id": user_id,
                "name": name,
                "timestamp": now_ts(),
                "duration": duration,
                "expires_at": now_ts() + duration if duration > 0 else 0,
            }
            self._save()

    def unmark_muted(self, chat_id: str, user_id: str) -> bool:
        key = self.user_key(chat_id, user_id)
        with self._lock:
            existed = self._data["muted"].pop(key, None) is not None
            self._save()
            return existed

    def is_muted(self, chat_id: str, user_id: str) -> bool:
        key = self.user_key(chat_id, user_id)
        with self._lock:
            entry = self._data["muted"].get(key)
            if not entry:
                return False
            exp = entry.get("expires_at", 0)
            if exp > 0 and now_ts() > exp:
                del self._data["muted"][key]
                self._save()
                return False
            return True

    def get_expired_mutes(self) -> List[Dict[str, Any]]:
        now = now_ts()
        expired = []
        with self._lock:
            for key, entry in list(self._data["muted"].items()):
                exp = entry.get("expires_at", 0)
                if exp > 0 and now > exp:
                    expired.append(dict(entry))
                    del self._data["muted"][key]
            if expired:
                self._save()
        return expired

    def muted_summary(self, chat_id: Optional[str] = None) -> str:
        with self._lock:
            rows = []
            for item in self._data["muted"].values():
                if chat_id and str(item.get("chat_id")) != str(chat_id):
                    continue
                exp = item.get("expires_at", 0)
                if exp > 0:
                    remaining = max(0, exp - now_ts())
                    time_str = f" ({format_duration(remaining)} مانده)"
                else:
                    time_str = " (دائمی)"
                rows.append(
                    f"  {EMOJI['mute']} {item.get('user_id')} | "
                    f"{item.get('name') or '-'}{time_str}"
                )
            return "\n".join(sorted(rows)) if rows else "mute list خالی."

    # ── VIP list ──────────────────────────────────────

    def add_vip(self, chat_id: str, user_id: str, name: str = "") -> None:
        key = self.user_key(chat_id, user_id)
        with self._lock:
            self._data["vip"][key] = {
                "chat_id": chat_id,
                "user_id": user_id,
                "name": name,
                "added_at": now_ts(),
            }
            self._save()

    def remove_vip(self, chat_id: str, user_id: str) -> bool:
        key = self.user_key(chat_id, user_id)
        with self._lock:
            existed = self._data["vip"].pop(key, None) is not None
            self._save()
            return existed

    def is_vip(self, chat_id: str, user_id: str) -> bool:
        key = self.user_key(chat_id, user_id)
        with self._lock:
            return key in self._data["vip"]

    def vip_summary(self, chat_id: Optional[str] = None) -> str:
        with self._lock:
            rows = []
            for item in self._data["vip"].values():
                if chat_id and str(item.get("chat_id")) != str(chat_id):
                    continue
                rows.append(
                    f"  {EMOJI['gem']} {item.get('user_id')} | "
                    f"{item.get('name') or '-'}"
                )
            return "\n".join(sorted(rows)) if rows else "VIP list خالی."

    # ── Mods (Moderator level) ────────────────────────

    def add_mod(self, chat_id: str, user_id: str, name: str = "") -> None:
        key = self.user_key(chat_id, user_id)
        with self._lock:
            self._data["mods"][key] = {
                "chat_id": chat_id,
                "user_id": user_id,
                "name": name,
                "added_at": now_ts(),
            }
            self._save()

    def remove_mod(self, chat_id: str, user_id: str) -> bool:
        key = self.user_key(chat_id, user_id)
        with self._lock:
            existed = self._data["mods"].pop(key, None) is not None
            self._save()
            return existed

    def is_mod(self, chat_id: str, user_id: str) -> bool:
        key = self.user_key(chat_id, user_id)
        with self._lock:
            return key in self._data["mods"]

    # ── User profiles (XP, coins, etc.) ──────────────

    def get_user(self, chat_id: str, user_id: str) -> Dict[str, Any]:
        key = self.user_key(chat_id, user_id)
        with self._lock:
            return dict(
                self._data["users"].get(
                    key,
                    {
                        "xp": 0,
                        "coins": 0,
                        "messages": 0,
                        "name": "",
                        "first_seen": 0,
                        "last_seen": 0,
                        "daily_claimed": 0,
                    },
                )
            )

    def update_user_activity(
        self, chat_id: str, user_id: str, name: str = ""
    ) -> Dict[str, Any]:
        key = self.user_key(chat_id, user_id)
        with self._lock:
            user = self._data["users"].setdefault(
                key,
                {
                    "xp": 0,
                    "coins": 0,
                    "messages": 0,
                    "name": name,
                    "first_seen": now_ts(),
                    "last_seen": now_ts(),
                    "daily_claimed": 0,
                },
            )
            user["messages"] = int(user.get("messages", 0)) + 1
            user["last_seen"] = now_ts()
            if name:
                user["name"] = name
            if not user.get("first_seen"):
                user["first_seen"] = now_ts()

            if self._data["config"].get("xp_enabled", True):
                user["xp"] = int(user.get("xp", 0)) + XP_PER_MESSAGE

            # Auto-save هر 10 پیام
            if int(user["messages"]) % 10 == 0:
                self._save()

            return dict(user)

    def add_xp(self, chat_id: str, user_id: str, amount: int) -> int:
        key = self.user_key(chat_id, user_id)
        with self._lock:
            user = self._data["users"].get(key)
            if not user:
                return 0
            user["xp"] = int(user.get("xp", 0)) + amount
            self._save()
            return int(user["xp"])

    def add_coins(self, chat_id: str, user_id: str, amount: int) -> int:
        key = self.user_key(chat_id, user_id)
        with self._lock:
            user = self._data["users"].get(key)
            if not user:
                return 0
            user["coins"] = int(user.get("coins", 0)) + amount
            self._save()
            return int(user["coins"])

    def claim_daily(self, chat_id: str, user_id: str) -> Tuple[bool, int]:
        key = self.user_key(chat_id, user_id)
        today = datetime.now().strftime("%Y-%m-%d")
        with self._lock:
            user = self._data["users"].get(key)
            if not user:
                return False, 0
            if user.get("daily_claimed") == today:
                return False, int(user.get("coins", 0))
            user["daily_claimed"] = today
            user["coins"] = int(user.get("coins", 0)) + DAILY_REWARD_COINS
            self._save()
            return True, int(user["coins"])

    def leaderboard(
        self,
        chat_id: str,
        sort_by: str = "xp",
        limit: int = 10,
    ) -> str:
        with self._lock:
            users = []
            for key, user in self._data["users"].items():
                if not key.startswith(f"{chat_id}:"):
                    continue
                users.append(user)

            users.sort(key=lambda u: int(u.get(sort_by, 0)), reverse=True)
            users = users[:limit]

            if not users:
                return "هنوز آماری ثبت نشده."

            medals = ["🥇", "🥈", "🥉"]
            lines = [f"{EMOJI['trophy']} لیدربورد ({sort_by}):\n"]
            for i, user in enumerate(users):
                medal = medals[i] if i < 3 else f"{i + 1}."
                name = user.get("name") or "ناشناس"
                value = user.get(sort_by, 0)
                lines.append(f"  {medal} {name}: {value}")
            return "\n".join(lines)

    # ── Stats ─────────────────────────────────────────

    def record_stat(self, chat_id: str, stat_type: str) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        with self._lock:
            stats = self._data["stats"]
            day_key = f"{chat_id}:{today}"
            day = stats.setdefault(day_key, {})
            day[stat_type] = int(day.get(stat_type, 0)) + 1
            # Auto-save هر 50 ثبت
            total = sum(day.values())
            if total % 50 == 0:
                self._save()

    def get_daily_stats(self, chat_id: str, date: str = "") -> Dict[str, int]:
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")
        day_key = f"{chat_id}:{date}"
        with self._lock:
            return dict(self._data["stats"].get(day_key, {}))

    def stats_summary(self, chat_id: str, days: int = 7) -> str:
        lines = [f"{EMOJI['chart']} آمار {days} روز اخیر:\n"]
        total_msgs = 0
        total_violations = 0
        today = datetime.now()

        with self._lock:
            for i in range(days):
                date = (today - timedelta(days=i)).strftime("%Y-%m-%d")
                day_key = f"{chat_id}:{date}"
                stats = self._data["stats"].get(day_key, {})
                msgs = stats.get("messages", 0)
                violations = sum(
                    v
                    for k, v in stats.items()
                    if k.startswith("violation_")
                )
                total_msgs += msgs
                total_violations += violations
                lines.append(
                    f"  {date}: {msgs} پیام, {violations} تخلف"
                )

        lines.append(f"\nمجموع: {total_msgs} پیام, {total_violations} تخلف")
        return "\n".join(lines)

    # ── Notes / FAQ ───────────────────────────────────

    def set_note(self, chat_id: str, name: str, content: str) -> None:
        with self._lock:
            notes = self._data["notes"].setdefault(chat_id, {})
            notes[name.lower()] = {
                "name": name,
                "content": content,
                "updated_at": now_ts(),
            }
            self._save()

    def get_note(self, chat_id: str, name: str) -> Optional[str]:
        with self._lock:
            notes = self._data["notes"].get(chat_id, {})
            note = notes.get(name.lower())
            return note["content"] if note else None

    def delete_note(self, chat_id: str, name: str) -> bool:
        with self._lock:
            notes = self._data["notes"].get(chat_id, {})
            existed = notes.pop(name.lower(), None) is not None
            self._save()
            return existed

    def list_notes(self, chat_id: str) -> str:
        with self._lock:
            notes = self._data["notes"].get(chat_id, {})
            if not notes:
                return "هیچ یادداشتی ثبت نشده."
            lines = [f"{EMOJI['note']} یادداشت‌ها:"]
            for note in notes.values():
                lines.append(f"  #{note['name']}")
            return "\n".join(lines)

    # ── Backup / Restore ─────────────────────────────

    def backup(self) -> str:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = BACKUP_DIR / f"backup_{ts}.json"
        with self._lock:
            backup_path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return str(backup_path)

    def restore(self, backup_name: str) -> bool:
        backup_path = BACKUP_DIR / backup_name
        if not backup_path.exists():
            return False
        try:
            raw = json.loads(backup_path.read_text(encoding="utf-8"))
            with self._lock:
                self._data = raw
                self._ensure_defaults()
                self._save()
            return True
        except Exception:
            return False

    def list_backups(self) -> str:
        if not BACKUP_DIR.exists():
            return "هیچ بکاپی وجود ندارد."
        files = sorted(BACKUP_DIR.glob("backup_*.json"), reverse=True)
        if not files:
            return "هیچ بکاپی وجود ندارد."
        lines = [f"{EMOJI['folder']} بکاپ‌ها:"]
        for f in files[:10]:
            size = f.stat().st_size // 1024
            lines.append(f"  {f.name} ({size} KB)")
        return "\n".join(lines)

    def force_save(self) -> None:
        with self._lock:
            self._save()


# ╔══════════════════════════════════════════════════════╗
# ║           GroupModerator Ultra                       ║
# ╚══════════════════════════════════════════════════════╝

class GroupModerator:
    def __init__(self, client: Any):
        self.client = client
        self.state = ModeratorState(STATE_PATH)
        self.exempt_user_ids = exempt_user_ids()
        self.match_values = group_match_values()

        # Detectors
        self.flood = SlidingWindowCounter(FLOOD_MAX, FLOOD_WINDOW)
        self.repeat = RepeatDetector(REPEAT_MAX, REPEAT_WINDOW)
        self.raid_detector = RaidDetector()
        self.slow_mode = SlowModeTracker(
            float(self.state._data["config"].get("slow_mode", 0))
        )

        # Managers
        self.auto_responder = AutoResponder()
        self.scheduler = TaskScheduler()
        self.captcha_manager = CaptchaManager()
        self.poll_manager = PollManager()
        self.lottery_manager = LotteryManager()

        # Caches
        self.permission_cache: Dict[str, Tuple[float, bool]] = {}
        self.permission_lock = threading.RLock()

        # Threading
        self.stop_event = threading.Event()
        self.queue: "queue.Queue[ModerationEvent]" = queue.Queue(
            maxsize=QUEUE_MAX_SIZE
        )
        self.worker = threading.Thread(
            target=self._worker_loop,
            name="sorobot-ultra-worker",
            daemon=True,
        )
        self.scheduler_thread = threading.Thread(
            target=self._scheduler_loop,
            name="sorobot-scheduler",
            daemon=True,
        )

        # Boot time
        self.boot_time = time.time()

        self._print_banner()

    # ── lifecycle ─────────────────────────────────────

    def _print_banner(self) -> None:
        banner = f"""
╔══════════════════════════════════════════════════════╗
║     {EMOJI['robot']} SoroBot Ultra v2.0.0 - مدیر هوشمند گروه      ║
╠══════════════════════════════════════════════════════╣
║  PHONE:          {PHONE:<35} ║
║  GROUP_ID:       {GROUP_ID or '(auto)' :<35} ║
║  GROUP_TARGET:   {GROUP_TARGET:<35} ║
║  MAX_WARNINGS:   {str(self.state.max_warnings):<35} ║
║  BAD_WORDS:      {str(len(self.state.bad_words())):<35} ║
║  ALLOWED_DOMS:   {str(len(self.state.allowed_domains())):<35} ║
║  FLOOD:          {f'{FLOOD_MAX}/{FLOOD_WINDOW}s':<35} ║
║  REPEAT:         {f'{REPEAT_MAX}/{REPEAT_WINDOW}s':<35} ║
║  ANTI_CAPS:      {str(self.state.get_toggle('anti_caps')):<35} ║
║  ANTI_PHONE:     {str(self.state.get_toggle('anti_phone')):<35} ║
║  NIGHT_MODE:     {str(self.state.get_toggle('night_mode')):<35} ║
║  CAPTCHA:        {str(self.state.get_toggle('captcha')):<35} ║
║  ANTI_RAID:      {str(self.state.get_toggle('anti_raid')):<35} ║
║  XP_ENABLED:     {str(self.state.get_toggle('xp_enabled')):<35} ║
║  DEBUG:          {str(DEBUG):<35} ║
╚══════════════════════════════════════════════════════╝
"""
        print(banner)

    def start(self) -> None:
        if not self.worker.is_alive():
            self.worker.start()
        if not self.scheduler_thread.is_alive():
            self.scheduler_thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.state.force_save()
        self.worker.join(timeout=5)
        self.scheduler_thread.join(timeout=5)

    # ── event handling ────────────────────────────────

    def on_event(self, event: Any) -> None:
        data = getattr(event, "data", None) or {}
        item = ModerationEvent.from_payload(data)

        if DEBUG:
            print(f"\n{'='*50}")
            print(f"{EMOJI['thunder']} NEW EVENT")
            print(f"{'='*50}")
            print("RAW:", json.dumps(data, ensure_ascii=False, default=str)[:500])
            print("PARSED:", item)

        if not self._belongs_to_target_group(item):
            return

        try:
            self.queue.put_nowait(item)
            log_debug("QUEUED:", item.message_id)
        except queue.Full:
            print("⚠️ صف moderation پر است!")

    def _belongs_to_target_group(self, item: ModerationEvent) -> bool:
        if item.is_outgoing and not PROCESS_OUTGOING_FOR_TEST:
            return False
        if not item.is_group:
            return False
        if MODERATE_ALL_GROUPS:
            return True
        candidates = {
            str(item.chat_id).strip(),
            str(item.chat_name).strip(),
            normalise_text(item.chat_name),
        }
        return bool(candidates & self.match_values)

    def _worker_loop(self) -> None:
        print(f"{EMOJI['rocket']} Worker started.")
        while not self.stop_event.is_set():
            try:
                item = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.process(item)
            except Exception as exc:
                print(f"{EMOJI['cross']} خطای moderation:", repr(exc))
                if DEBUG:
                    traceback.print_exc()
            finally:
                self.queue.task_done()
        print("Worker stopped.")

    def _scheduler_loop(self) -> None:
        print(f"{EMOJI['clock']} Scheduler started.")
        while not self.stop_event.is_set():
            try:
                # بررسی task‌های موعدرسیده
                for task in self.scheduler.get_due_tasks():
                    self._execute_scheduled_task(task)

                # بررسی mute‌های expire شده
                expired_mutes = self.state.get_expired_mutes()
                for mute_info in expired_mutes:
                    self._handle_expired_mute(mute_info)

                # بررسی captcha‌های timeout شده
                if self.state.get_toggle("captcha"):
                    for expired in self.captcha_manager.get_expired():
                        self._handle_expired_captcha(expired)

                # ذخیره دوره‌ای
                self.state.force_save()

            except Exception as exc:
                print("Scheduler error:", repr(exc))

            time.sleep(5)
        print("Scheduler stopped.")

    def _execute_scheduled_task(self, task: ScheduledTask) -> None:
        log_debug("Executing scheduled task:", task.task_id, task.action)
        try:
            if task.action == "send_message":
                target = task.params.get("target", GROUP_TARGET)
                text = task.params.get("text", "")
                if text:
                    self.client.send_message(target, text)

            elif task.action == "unmute":
                target = task.params.get("target", GROUP_TARGET)
                user_id = task.params.get("user_id")
                if user_id:
                    try:
                        self.client.set_permissions(
                            target, user_id, send_messages=True
                        )
                    except Exception:
                        pass
                    chat_id = task.params.get("chat_id", "")
                    self.state.unmark_muted(chat_id, user_id)

            elif task.action == "reminder":
                target = task.params.get("target", GROUP_TARGET)
                text = task.params.get("text", "")
                user = task.params.get("user_name", "")
                self.client.send_message(
                    target,
                    f"{EMOJI['bell']} یادآوری"
                    f"{' برای ' + user if user else ''}: {text}",
                )

            log_action("scheduled_task", {"task": task.task_id, "action": task.action})

        except Exception as exc:
            print(f"Scheduled task {task.task_id} failed:", repr(exc))

    def _handle_expired_mute(self, mute_info: Dict[str, Any]) -> None:
        user_id = mute_info.get("user_id", "")
        chat_id = mute_info.get("chat_id", "")
        name = mute_info.get("name", "")
        log_debug("Auto-unmuting:", user_id)
        try:
            for target in [GROUP_TARGET, GROUP_ID, chat_id]:
                target = str(target or "").strip()
                if target:
                    try:
                        self.client.set_permissions(
                            target, user_id, send_messages=True
                        )
                        self.client.send_message(
                            target,
                            f"{EMOJI['unmute']} {name or user_id} آنمیوت شد.",
                        )
                        break
                    except Exception:
                        continue
        except Exception as exc:
            print("Auto-unmute failed:", repr(exc))

    def _handle_expired_captcha(self, challenge: CaptchaChallenge) -> None:
        log_debug("Captcha expired for:", challenge.user_id)
        try:
            for target in [GROUP_TARGET, GROUP_ID, challenge.chat_id]:
                target = str(target or "").strip()
                if target:
                    try:
                        self.client.kick(target, challenge.user_id)
                        self.client.send_message(
                            target,
                            f"{EMOJI['cross']} کاربر {challenge.user_id} "
                            f"به دلیل عدم پاسخ به captcha حذف شد.",
                        )
                        break
                    except Exception:
                        continue
        except Exception as exc:
            print("Captcha kick failed:", repr(exc))

    # ── target/action helpers ─────────────────────────

    def _targets_for(self, item: ModerationEvent) -> List[str]:
        targets = []
        for t in [GROUP_TARGET, GROUP_ID, item.chat_id, GROUP_NAME, item.chat_name]:
            t = str(t or "").strip()
            if t and t not in targets:
                targets.append(t)
        return targets

    def _call_with_targets(
        self, item: ModerationEvent, action_name: str, func: Any
    ) -> Any:
        last_exc = None
        for target in self._targets_for(item):
            try:
                return func(target)
            except Exception as exc:
                last_exc = exc
                log_debug(f"{action_name} failed on {target!r}:", repr(exc))
        if last_exc:
            raise last_exc
        return None

    # ── permissions ───────────────────────────────────

    def _get_admin_level(
        self, item: ModerationEvent, user_id: str
    ) -> AdminLevel:
        if not user_id:
            return AdminLevel.MEMBER

        if user_id in OWNER_USER_IDS:
            return AdminLevel.OWNER

        if user_id in self.exempt_user_ids:
            return AdminLevel.ADMIN

        if self.state.is_mod(item.chat_id, user_id):
            return AdminLevel.MOD

        if PROCESS_ADMINS_FOR_TEST:
            return AdminLevel.MEMBER

        now = time.time()
        cache_key = f"{item.chat_id}:{user_id}"

        with self.permission_lock:
            cached = self.permission_cache.get(cache_key)
            if cached and now - cached[0] < PERMISSION_CACHE_TTL:
                return AdminLevel.ADMIN if cached[1] else AdminLevel.MEMBER

        is_admin = False
        try:
            def _get(target: str) -> Any:
                return self.client.get_permissions(target, user_id) or {}

            perms = self._call_with_targets(item, "get_permissions", _get) or {}
            is_admin = bool(
                perms.get("is_admin")
                or perms.get("is_creator")
                or perms.get("creator")
                or perms.get("admin")
            )
        except Exception:
            is_admin = False

        with self.permission_lock:
            self.permission_cache[cache_key] = (now, is_admin)

        return AdminLevel.ADMIN if is_admin else AdminLevel.MEMBER

    def _is_admin_or_above(
        self, item: ModerationEvent, user_id: str
    ) -> bool:
        return self._get_admin_level(item, user_id) >= AdminLevel.MOD

    def _is_exempt(self, item: ModerationEvent, user_id: str) -> bool:
        if self.state.is_vip(item.chat_id, user_id):
            return True
        return self._is_admin_or_above(item, user_id)

    # ── send/delete/actions ───────────────────────────

    def _send_message(self, item: ModerationEvent, text: str) -> None:
        def _send(target: str) -> Any:
            return self.client.send_message(target, text)
        self._call_with_targets(item, "send_message", _send)

    def _reply_or_send(self, item: ModerationEvent, text: str) -> None:
        try:
            if item.message_id:
                def _reply(target: str) -> Any:
                    return self.client.reply(target, item.message_id, text)
                self._call_with_targets(item, "reply", _reply)
            else:
                self._send_message(item, text)
        except Exception:
            try:
                self._send_message(item, text)
            except Exception as exc2:
                print("send fallback failed:", repr(exc2))

    def _delete_message(self, item: ModerationEvent) -> None:
        if not item.message_id:
            return
        def _delete(target: str) -> Any:
            return self.client.delete_messages(
                target, [item.message_id], revoke=True
            )
        try:
            self._call_with_targets(item, "delete_messages", _delete)
        except Exception as exc:
            print("حذف پیام ناموفق:", repr(exc))

    def _ban_user(self, item: ModerationEvent, user_id: str) -> bool:
        def _ban(target: str) -> Any:
            return self.client.ban(target, user_id)
        try:
            return bool(self._call_with_targets(item, "ban", _ban))
        except Exception:
            return False

    def _kick_user(self, item: ModerationEvent, user_id: str) -> bool:
        def _kick(target: str) -> Any:
            return self.client.kick(target, user_id)
        try:
            return bool(self._call_with_targets(item, "kick", _kick))
        except Exception:
            return False

    def _unban_user(self, item: ModerationEvent, user_id: str) -> bool:
        def _unban(target: str) -> Any:
            return self.client.unban(target, user_id)
        try:
            return bool(self._call_with_targets(item, "unban", _unban))
        except Exception:
            return False

    def _mute_user(self, item: ModerationEvent, user_id: str) -> bool:
        def _mute(target: str) -> Any:
            return self.client.set_permissions(
                target, user_id, send_messages=False
            )
        try:
            return bool(self._call_with_targets(item, "mute", _mute))
        except Exception:
            return False

    def _unmute_user(self, item: ModerationEvent, user_id: str) -> bool:
        def _unmute(target: str) -> Any:
            return self.client.set_permissions(
                target, user_id, send_messages=True
            )
        try:
            return bool(self._call_with_targets(item, "unmute", _unmute))
        except Exception:
            return False

    # ── violations ────────────────────────────────────

    def _warn(
        self,
        item: ModerationEvent,
        reason: str,
        violation_type: ViolationType = ViolationType.BAD_WORD,
    ) -> None:
        print(
            f"{EMOJI['warn']} VIOLATION: {violation_type.name} | "
            f"{reason} | user={item.sender_id}"
        )

        self._delete_message(item)

        self.state.record_stat(
            item.chat_id, f"violation_{violation_type.name.lower()}"
        )

        log_action(
            "violation",
            {
                "type": violation_type.name,
                "reason": reason,
                "user_id": item.sender_id,
                "user_name": item.sender_name,
                "chat_id": item.chat_id,
                "text_preview": item.text[:100],
            },
        )

        count = self.state.increment_warning(
            item.chat_id,
            item.sender_id,
            reason,
            name=item.sender_name,
        )

        max_w = self.state.max_warnings

        if count >= max_w:
            self._ban_after_max_warnings(item, reason)
            return

        self._reply_or_send(
            item,
            f"{EMOJI['warn']} اخطار {count}/{max_w} برای "
            f"{item.sender_name or item.sender_id}\n"
            f"دلیل: {reason}\n"
            f"{'🟡' * count}{'⚪' * (max_w - count)}",
        )

    def _ban_after_max_warnings(
        self, item: ModerationEvent, reason: str
    ) -> None:
        user_id = item.sender_id

        self.state.mark_banned(
            item.chat_id,
            user_id,
            reason=f"max_warnings: {reason}",
            name=item.sender_name,
        )

        ok = self._ban_user(item, user_id)
        action = "ban"
        if not ok:
            ok = self._kick_user(item, user_id)
            action = "kick"

        if ok:
            self.state.clear_warnings(item.chat_id, user_id)
            self._send_message(
                item,
                f"{EMOJI['ban']} کاربر {item.sender_name or user_id} "
                f"به دلیل رسیدن به {self.state.max_warnings} اخطار "
                f"حذف شد.\n"
                f"اقدام: {action}\n"
                f"دلیل آخر: {reason}\n"
                f"برای بازگردانی: /unban {user_id}",
            )
            log_action(
                "ban_max_warnings",
                {
                    "user_id": user_id,
                    "action": action,
                    "reason": reason,
                },
            )
        else:
            self._send_message(
                item,
                f"{EMOJI['cross']} حذف/بن کاربر ناموفق بود.\n"
                "دسترسی‌های ادمین ربات را بررسی کنید.",
            )

    def _enforce_banlist(self, item: ModerationEvent) -> bool:
        if not ENFORCE_LOCAL_BANLIST:
            return False
        if not self.state.is_banned(item.chat_id, item.sender_id):
            return False
        print(f"{EMOJI['skull']} BANNED USER SPOKE:", item.sender_id)
        self._delete_message(item)
        ok = self._ban_user(item, item.sender_id)
        if not ok:
            self._kick_user(item, item.sender_id)
        return True

    # ── commands ──────────────────────────────────────

    def _handle_command(self, item: ModerationEvent) -> bool:
        text = item.text.strip()
        if not text.startswith("/") and not text.startswith("#"):
            return False

        # Check for note retrieval: #note_name
        if text.startswith("#") and not text.startswith("#ا"):
            note_name = text[1:].strip().split()[0]
            content = self.state.get_note(item.chat_id, note_name)
            if content:
                self._reply_or_send(
                    item, f"{EMOJI['note']} #{note_name}:\n{content}"
                )
                return True
            return False

        parts = text.split(maxsplit=2)
        command = parts[0].casefold().split("@")[0]  # حذف @botname
        arg1 = parts[1].strip() if len(parts) >= 2 else ""
        arg2 = parts[2].strip() if len(parts) >= 3 else ""

        # ── Public Commands ──────────────────────────

        if command == "/id":
            self._reply_or_send(
                item,
                f"{EMOJI['id']} اطلاعات:\n"
                f"chat_id: {item.chat_id}\n"
                f"chat_name: {item.chat_name}\n"
                f"sender_id: {item.sender_id}\n"
                f"sender_name: {item.sender_name}\n"
                f"message_id: {item.message_id}",
            )
            return True

        if command == "/profile":
            target_id = arg1 or item.sender_id
            user = self.state.get_user(item.chat_id, target_id)
            level = level_from_xp(user.get("xp", 0))
            progress = xp_progress(user.get("xp", 0))
            wc = self.state.warning_count(item.chat_id, target_id)
            is_b = self.state.is_banned(item.chat_id, target_id)
            is_m = self.state.is_muted(item.chat_id, target_id)
            is_v = self.state.is_vip(item.chat_id, target_id)

            status_icons = []
            if is_v:
                status_icons.append(EMOJI["gem"])
            if is_b:
                status_icons.append(EMOJI["ban"])
            if is_m:
                status_icons.append(EMOJI["mute"])

            self._reply_or_send(
                item,
                f"{EMOJI['target']} پروفایل: {user.get('name') or target_id}\n"
                f"{''.join(status_icons)}\n"
                f"{EMOJI['star']} {progress}\n"
                f"{EMOJI['coin']} سکه: {user.get('coins', 0)}\n"
                f"{EMOJI['chart']} پیام‌ها: {user.get('messages', 0)}\n"
                f"{EMOJI['warn']} اخطارها: {wc}\n"
                f"{EMOJI['clock']} آخرین فعالیت: "
                f"{datetime.fromtimestamp(user.get('last_seen', 0)).strftime('%Y-%m-%d %H:%M') if user.get('last_seen') else '-'}",
            )
            return True

        if command == "/level":
            user = self.state.get_user(item.chat_id, item.sender_id)
            self._reply_or_send(
                item,
                f"{EMOJI['star']} {item.sender_name or item.sender_id}\n"
                f"{xp_progress(user.get('xp', 0))}",
            )
            return True

        if command == "/daily":
            ok, coins = self.state.claim_daily(item.chat_id, item.sender_id)
            if ok:
                self._reply_or_send(
                    item,
                    f"{EMOJI['gift']} پاداش روزانه دریافت شد!\n"
                    f"+{DAILY_REWARD_COINS} {EMOJI['coin']}\n"
                    f"موجودی: {coins} {EMOJI['coin']}",
                )
            else:
                self._reply_or_send(
                    item,
                    f"{EMOJI['clock']} قبلاً پاداش امروز رو گرفتی!\n"
                    f"موجودی: {coins} {EMOJI['coin']}",
                )
            return True

        if command == "/top" or command == "/leaderboard":
            sort_by = arg1 if arg1 in {"xp", "coins", "messages"} else "xp"
            self._reply_or_send(
                item,
                self.state.leaderboard(item.chat_id, sort_by),
            )
            return True

        if command == "/dice":
            result = random.randint(1, 6)
            dice_faces = ["⚀", "⚁", "⚂", "⚃", "⚄", "⚅"]
            self._reply_or_send(
                item,
                f"{EMOJI['dice']} {item.sender_name or item.sender_id} "
                f"تاس انداخت: {dice_faces[result - 1]} ({result})",
            )
            return True

        if command == "/coinflip":
            result = random.choice(["شیر 🪙", "خط 💰"])
            self._reply_or_send(
                item,
                f"{EMOJI['coin']} {item.sender_name or item.sender_id}: {result}",
            )
            return True

        if command == "/vote" and arg1:
            try:
                opt = int(arg1) - 1
                result = self.poll_manager.vote(
                    item.chat_id, item.sender_id, opt
                )
                if result:
                    self._reply_or_send(
                        item,
                        f"{EMOJI['check']} رأی شما ثبت شد: {result}",
                    )
                else:
                    self._reply_or_send(
                        item,
                        f"{EMOJI['cross']} نظرسنجی فعالی وجود ندارد یا گزینه نامعتبر.",
                    )
            except ValueError:
                self._reply_or_send(item, "شماره گزینه را وارد کنید.")
            return True

        if command == "/joinlottery":
            count = self.lottery_manager.join(item.chat_id, item.sender_id)
            self._reply_or_send(
                item,
                f"{EMOJI['party']} {item.sender_name or item.sender_id} "
                f"در قرعه‌کشی ثبت نام کرد!\n"
                f"تعداد شرکت‌کنندگان: {count}",
            )
            return True

        if command == "/rules":
            toggles = []
            if self.state.get_toggle("anti_link"):
                toggles.append("🔗 ارسال لینک غیرمجاز ممنوع")
            if self.state.get_toggle("anti_badword"):
                toggles.append("🤬 کلمات رکیک ممنوع")
            if self.state.get_toggle("anti_flood"):
                toggles.append(f"🌊 فلود ({FLOOD_MAX} پیام در {FLOOD_WINDOW}s) ممنوع")
            if self.state.get_toggle("anti_repeat"):
                toggles.append("🔄 تکرار متن ممنوع")
            if self.state.get_toggle("anti_caps"):
                toggles.append("🔠 CAPS LOCK ممنوع")
            if self.state.get_toggle("anti_phone"):
                toggles.append("📱 ارسال شماره تلفن ممنوع")
            if self.state.get_toggle("night_mode"):
                toggles.append(
                    f"🌙 حالت شبانه ({NIGHT_MODE_START}:00 - {NIGHT_MODE_END}:00)"
                )

            rules = (
                f"{EMOJI['pin']} قوانین گروه:\n\n"
                + "\n".join(f"  {t}" for t in toggles)
                + f"\n\n{EMOJI['warn']} سقف اخطار: {self.state.max_warnings}"
            )
            self._reply_or_send(item, rules)
            return True

        # ── Admin/Mod check for remaining commands ────

        admin_level = self._get_admin_level(item, item.sender_id)

        if admin_level < AdminLevel.MOD:
            # فقط دستورات عمومی بالا مجاز بودند
            if command in {
                "/help", "/commands", "/status", "/warnings",
                "/banlist", "/mutelist", "/viplist", "/stats",
                "/forgive", "/reset", "/kick", "/ban", "/unban",
                "/mute", "/unmute", "/setmax", "/addword", "/delword",
                "/words", "/allowdomain", "/deldomain", "/domains",
                "/say", "/pin", "/purge", "/backup", "/restore",
                "/backups", "/addmod", "/delmod", "/addvip", "/delvip",
                "/toggle", "/slowmode", "/poll", "/closepoll",
                "/lottery", "/addauto", "/delauto", "/autos",
                "/setnote", "/delnote", "/notes", "/remind",
                "/schedule", "/canceltask", "/tasks", "/tag",
                "/setmax", "/setwelcome", "/givexp", "/givecoins",
                "/endraid",
            }:
                self._reply_or_send(
                    item,
                    f"{EMOJI['lock']} فقط ادمین‌ها/مادها اجازه اجرای این دستور را دارند.",
                )
                return True
            return False

        # ── Admin Commands ────────────────────────────

        if command in {"/help", "/commands"}:
            self._reply_or_send(item, self._help_text(admin_level))

        elif command == "/status":
            uptime = format_duration(int(time.time() - self.boot_time))
            self._reply_or_send(
                item,
                f"{EMOJI['robot']} وضعیت SoroBot Ultra:\n\n"
                f"  {EMOJI['clock']} Uptime: {uptime}\n"
                f"  {EMOJI['target']} Target: {GROUP_TARGET}\n"
                f"  {EMOJI['warn']} Max Warnings: {self.state.max_warnings}\n"
                f"  {EMOJI['shield']} Anti-Link: {self.state.get_toggle('anti_link')}\n"
                f"  {EMOJI['no_entry']} Anti-BadWord: {self.state.get_toggle('anti_badword')}\n"
                f"  {EMOJI['fire']} Anti-Flood: {self.state.get_toggle('anti_flood')}\n"
                f"  🔄 Anti-Repeat: {self.state.get_toggle('anti_repeat')}\n"
                f"  🔠 Anti-CAPS: {self.state.get_toggle('anti_caps')}\n"
                f"  📱 Anti-Phone: {self.state.get_toggle('anti_phone')}\n"
                f"  {EMOJI['ghost']} Anti-Invisible: {self.state.get_toggle('anti_invisible')}\n"
                f"  📏 Anti-LongMsg: {self.state.get_toggle('anti_longmsg')}\n"
                f"  📤 Anti-Forward: {self.state.get_toggle('anti_forward_spam')}\n"
                f"  {EMOJI['moon']} Night Mode: {self.state.get_toggle('night_mode')}\n"
                f"  ⏱️ Slow Mode: {self.state._data['config'].get('slow_mode', 0)}s\n"
                f"  {EMOJI['detective']} Captcha: {self.state.get_toggle('captcha')}\n"
                f"  {EMOJI['shield']} Anti-Raid: {self.state.get_toggle('anti_raid')}\n"
                f"  {EMOJI['star']} XP System: {self.state.get_toggle('xp_enabled')}\n"
                f"  {EMOJI['wave']} Welcome: {self.state.get_toggle('welcome_enabled')}\n"
                f"  📊 Bad Words: {len(self.state.bad_words())}\n"
                f"  🔗 Allowed Domains: {len(self.state.allowed_domains())}",
            )

        elif command == "/warnings":
            self._reply_or_send(
                item, self.state.warning_summary(item.chat_id)
            )

        elif command == "/banlist":
            self._reply_or_send(
                item, self.state.banlist_summary(item.chat_id)
            )

        elif command == "/mutelist":
            self._reply_or_send(
                item, self.state.muted_summary(item.chat_id)
            )

        elif command == "/viplist":
            self._reply_or_send(
                item, self.state.vip_summary(item.chat_id)
            )

        elif command == "/stats":
            days = int(arg1) if arg1.isdigit() else 7
            self._reply_or_send(
                item,
                self.state.stats_summary(item.chat_id, days),
            )

        elif command == "/forgive" and arg1:
            ok = self.state.clear_warnings(item.chat_id, arg1)
            self._reply_or_send(
                item,
                f"{EMOJI['check']} اخطارها پاک شد."
                if ok
                else "اخطاری پیدا نشد.",
            )
            log_action("forgive", {"user_id": arg1, "by": item.sender_id})

        elif command == "/reset" and arg1:
            ok1 = self.state.clear_warnings(item.chat_id, arg1)
            ok2 = self.state.unmark_banned(item.chat_id, arg1)
            ok3 = self.state.unmark_muted(item.chat_id, arg1)
            self._reply_or_send(
                item,
                f"{EMOJI['check']} Reset: warnings={ok1}, "
                f"banned={ok2}, muted={ok3}",
            )
            log_action("reset", {"user_id": arg1, "by": item.sender_id})

        elif command == "/kick" and arg1:
            ok = self._kick_user(item, arg1)
            self._reply_or_send(
                item,
                f"{EMOJI['kick']} kick شد."
                if ok
                else f"{EMOJI['cross']} kick ناموفق.",
            )
            log_action(
                "kick",
                {"user_id": arg1, "by": item.sender_id, "ok": ok},
            )

        elif command == "/ban" and arg1:
            reason = arg2 or "manual_ban"
            self.state.mark_banned(
                item.chat_id, arg1, reason=reason
            )
            ok = self._ban_user(item, arg1)
            if not ok:
                ok = self._kick_user(item, arg1)
            self._reply_or_send(
                item,
                f"{EMOJI['ban']} ban شد. دلیل: {reason}"
                if ok
                else f"{EMOJI['cross']} ban/kick ناموفق.",
            )
            log_action(
                "ban",
                {
                    "user_id": arg1,
                    "by": item.sender_id,
                    "reason": reason,
                    "ok": ok,
                },
            )

        elif command == "/unban" and arg1:
            local = self.state.unmark_banned(item.chat_id, arg1)
            remote = self._unban_user(item, arg1)
            self._reply_or_send(
                item,
                f"{EMOJI['check']} unban: local={local}, server={remote}",
            )
            log_action(
                "unban", {"user_id": arg1, "by": item.sender_id}
            )

        elif command == "/mute" and arg1:
            duration = 0
            if arg2:
                try:
                    duration = int(arg2) * 60  # دقیقه به ثانیه
                except ValueError:
                    pass
            self.state.mark_muted(
                item.chat_id, arg1, duration=duration
            )
            ok = self._mute_user(item, arg1)

            if ok and duration > 0:
                self.scheduler.add_task(
                    delay_seconds=duration,
                    action="unmute",
                    params={
                        "target": GROUP_TARGET,
                        "user_id": arg1,
                        "chat_id": item.chat_id,
                    },
                )

            time_str = (
                f" ({format_duration(duration)})"
                if duration > 0
                else " (دائمی)"
            )
            self._reply_or_send(
                item,
                f"{EMOJI['mute']} mute شد{time_str}."
                if ok
                else f"{EMOJI['cross']} mute ناموفق.",
            )
            log_action(
                "mute",
                {
                    "user_id": arg1,
                    "by": item.sender_id,
                    "duration": duration,
                },
            )

        elif command == "/unmute" and arg1:
            local = self.state.unmark_muted(item.chat_id, arg1)
            remote = self._unmute_user(item, arg1)
            self._reply_or_send(
                item,
                f"{EMOJI['unmute']} unmute: local={local}, server={remote}",
            )
            log_action(
                "unmute", {"user_id": arg1, "by": item.sender_id}
            )

        elif command == "/setmax" and arg1:
            try:
                value = int(arg1)
                self.state.set_max_warnings(value)
                self._reply_or_send(
                    item,
                    f"{EMOJI['check']} سقف اخطار: {self.state.max_warnings}",
                )
            except ValueError:
                self._reply_or_send(item, "عدد معتبر وارد کنید.")

        elif command == "/addword" and arg1:
            self.state.add_bad_word(arg1)
            self._reply_or_send(
                item,
                f"{EMOJI['check']} کلمه ممنوع اضافه شد: {arg1}",
            )

        elif command == "/delword" and arg1:
            ok = self.state.remove_bad_word(arg1)
            self._reply_or_send(
                item,
                f"{EMOJI['check']} حذف شد." if ok else "پیدا نشد.",
            )

        elif command == "/words":
            words = sorted(self.state.bad_words())
            self._reply_or_send(
                item,
                "\n".join(words) if words else "لیست خالی.",
            )

        elif command == "/allowdomain" and arg1:
            self.state.add_allowed_domain(arg1)
            self._reply_or_send(
                item,
                f"{EMOJI['check']} دامنه مجاز: {normalise_domain(arg1)}",
            )

        elif command == "/deldomain" and arg1:
            ok = self.state.remove_allowed_domain(arg1)
            self._reply_or_send(
                item,
                f"{EMOJI['check']} حذف شد." if ok else "پیدا نشد.",
            )

        elif command == "/domains":
            domains = sorted(self.state.allowed_domains())
            self._reply_or_send(
                item,
                "\n".join(domains) if domains else "هیچ دامنه‌ای مجاز نیست.",
            )

        elif command == "/toggle" and arg1:
            valid_toggles = {
                "anti_link", "anti_badword", "anti_flood",
                "anti_repeat", "anti_caps", "anti_longmsg",
                "anti_phone", "anti_invisible", "anti_forward_spam",
                "night_mode", "captcha", "anti_raid", "xp_enabled",
                "welcome_enabled", "goodbye_enabled",
            }
            if arg1 in valid_toggles:
                current = self.state.get_toggle(arg1)
                self.state.set_toggle(arg1, not current)
                new_val = not current
                emoji_status = EMOJI["check"] if new_val else EMOJI["cross"]
                self._reply_or_send(
                    item,
                    f"{emoji_status} {arg1}: {'فعال' if new_val else 'غیرفعال'}",
                )
                log_action(
                    "toggle",
                    {"name": arg1, "value": new_val, "by": item.sender_id},
                )
            else:
                self._reply_or_send(
                    item,
                    f"Toggle نامعتبر. گزینه‌ها:\n"
                    + "\n".join(f"  /{t}" for t in sorted(valid_toggles)),
                )

        elif command == "/slowmode":
            if arg1:
                try:
                    seconds = float(arg1)
                    self.slow_mode.set_interval(seconds)
                    self.state._data["config"]["slow_mode"] = seconds
                    self.state.force_save()
                    self._reply_or_send(
                        item,
                        f"{EMOJI['clock']} Slow mode: {seconds}s"
                        if seconds > 0
                        else f"{EMOJI['check']} Slow mode غیرفعال شد.",
                    )
                except ValueError:
                    self._reply_or_send(item, "عدد معتبر وارد کنید.")
            else:
                self._reply_or_send(
                    item,
                    f"Slow mode فعلی: {self.slow_mode.interval}s",
                )

        elif command == "/say":
            msg = arg1 + ((" " + arg2) if arg2 else "")
            if msg:
                self._send_message(item, msg)

        elif command == "/setwelcome":
            msg = arg1 + ((" " + arg2) if arg2 else "")
            self.state._data["config"]["welcome_message"] = msg
            self.state.force_save()
            self._reply_or_send(
                item,
                f"{EMOJI['check']} پیام خوش‌آمدگویی: "
                + (msg if msg else "(پیشفرض)"),
            )

        # ── VIP Management ────────────────────────────

        elif command == "/addvip" and arg1:
            self.state.add_vip(item.chat_id, arg1)
            self._reply_or_send(
                item,
                f"{EMOJI['gem']} {arg1} به VIP list اضافه شد.",
            )

        elif command == "/delvip" and arg1:
            ok = self.state.remove_vip(item.chat_id, arg1)
            self._reply_or_send(
                item,
                f"{EMOJI['check']} حذف شد." if ok else "پیدا نشد.",
            )

        # ── Mod Management (Owner only) ───────────────

        elif command == "/addmod" and arg1:
            if admin_level >= AdminLevel.ADMIN:
                self.state.add_mod(item.chat_id, arg1)
                self._reply_or_send(
                    item,
                    f"{EMOJI['shield']} {arg1} به عنوان Mod اضافه شد.",
                )
            else:
                self._reply_or_send(item, f"{EMOJI['lock']} فقط ادمین‌ها.")

        elif command == "/delmod" and arg1:
            if admin_level >= AdminLevel.ADMIN:
                ok = self.state.remove_mod(item.chat_id, arg1)
                self._reply_or_send(
                    item,
                    f"{EMOJI['check']} حذف شد." if ok else "پیدا نشد.",
                )
            else:
                self._reply_or_send(item, f"{EMOJI['lock']} فقط ادمین‌ها.")

        # ── Poll ──────────────────────────────────────

        elif command == "/poll":
            raw = arg1 + ((" " + arg2) if arg2 else "")
            parts_poll = [p.strip() for p in raw.split("|") if p.strip()]
            if len(parts_poll) < 3:
                self._reply_or_send(
                    item,
                    "فرمت: /poll سوال | گزینه1 | گزینه2 | ...",
                )
            else:
                question = parts_poll[0]
                options = parts_poll[1:]
                poll = self.poll_manager.create_poll(
                    item.chat_id, question, options, item.sender_id
                )
                self._send_message(
                    item, self.poll_manager.format_poll(poll)
                )

        elif command == "/closepoll":
            result = self.poll_manager.close_poll(item.chat_id)
            self._reply_or_send(
                item,
                result
                if result
                else f"{EMOJI['cross']} نظرسنجی فعالی نیست.",
            )

        # ── Lottery ───────────────────────────────────

        elif command == "/lottery":
            count = int(arg1) if arg1.isdigit() else 1
            winners = self.lottery_manager.draw(item.chat_id, count)
            if winners:
                self._send_message(
                    item,
                    f"{EMOJI['party']} برنده(ها) قرعه‌کشی:\n"
                    + "\n".join(
                        f"  {EMOJI['trophy']} {w}" for w in winners
                    ),
                )
            else:
                self._reply_or_send(
                    item,
                    f"{EMOJI['cross']} هیچ شرکت‌کننده‌ای وجود ندارد.",
                )

        # ── Notes ─────────────────────────────────────

        elif command == "/setnote" and arg1:
            content = arg2 or ""
            self.state.set_note(item.chat_id, arg1, content)
            self._reply_or_send(
                item,
                f"{EMOJI['note']} یادداشت #{arg1} ذخیره شد.",
            )

        elif command == "/delnote" and arg1:
            ok = self.state.delete_note(item.chat_id, arg1)
            self._reply_or_send(
                item,
                f"{EMOJI['check']} حذف شد." if ok else "پیدا نشد.",
            )

        elif command == "/notes":
            self._reply_or_send(
                item, self.state.list_notes(item.chat_id)
            )

        # ── Auto Response ────────────────────────────

        elif command == "/addauto" and arg1:
            response = arg2 or ""
            ok = self.auto_responder.add_pattern(arg1, response)
            self._reply_or_send(
                item,
                f"{EMOJI['check']} الگو اضافه شد."
                if ok
                else f"{EMOJI['cross']} regex نامعتبر.",
            )

        elif command == "/delauto" and arg1:
            try:
                ok = self.auto_responder.remove_pattern(int(arg1))
                self._reply_or_send(
                    item,
                    f"{EMOJI['check']} حذف شد."
                    if ok
                    else "index نامعتبر.",
                )
            except ValueError:
                self._reply_or_send(item, "index عددی وارد کنید.")

        elif command == "/autos":
            self._reply_or_send(
                item, self.auto_responder.list_patterns()
            )

        # ── Remind ────────────────────────────────────

        elif command == "/remind" and arg1:
            try:
                minutes = int(arg1)
                text = arg2 or "یادآوری!"
                task_id = self.scheduler.add_task(
                    delay_seconds=minutes * 60,
                    action="reminder",
                    params={
                        "target": GROUP_TARGET,
                        "text": text,
                        "user_name": item.sender_name,
                    },
                )
                self._reply_or_send(
                    item,
                    f"{EMOJI['bell']} یادآوری تنظیم شد: {minutes} دقیقه دیگر\n"
                    f"ID: {task_id}",
                )
            except ValueError:
                self._reply_or_send(
                    item,
                    "فرمت: /remind دقیقه متن",
                )

        # ── Schedule message ──────────────────────────

        elif command == "/schedule" and arg1:
            try:
                minutes = int(arg1)
                text = arg2 or ""
                if not text:
                    self._reply_or_send(
                        item, "فرمت: /schedule دقیقه متن"
                    )
                else:
                    task_id = self.scheduler.add_task(
                        delay_seconds=minutes * 60,
                        action="send_message",
                        params={
                            "target": GROUP_TARGET,
                            "text": text,
                        },
                    )
                    self._reply_or_send(
                        item,
                        f"{EMOJI['clock']} پیام زمان‌بندی شد: {minutes} دقیقه\n"
                        f"ID: {task_id}",
                    )
            except ValueError:
                self._reply_or_send(
                    item, "فرمت: /schedule دقیقه متن"
                )

        elif command == "/canceltask" and arg1:
            ok = self.scheduler.cancel_task(arg1)
            self._reply_or_send(
                item,
                f"{EMOJI['check']} لغو شد." if ok else "تسک پیدا نشد.",
            )

        elif command == "/tasks":
            self._reply_or_send(item, self.scheduler.list_tasks())

        # ── Backup/Restore ────────────────────────────

        elif command == "/backup":
            path = self.state.backup()
            self._reply_or_send(
                item,
                f"{EMOJI['folder']} بکاپ ذخیره شد:\n{path}",
            )

        elif command == "/restore" and arg1:
            ok = self.state.restore(arg1)
            self._reply_or_send(
                item,
                f"{EMOJI['check']} Restore شد."
                if ok
                else f"{EMOJI['cross']} فایل پیدا نشد.",
            )

        elif command == "/backups":
            self._reply_or_send(item, self.state.list_backups())

        # ── XP/Coins ─────────────────────────────────

        elif command == "/givexp" and arg1:
            if admin_level >= AdminLevel.ADMIN:
                try:
                    amount = int(arg2) if arg2 else 100
                    new_xp = self.state.add_xp(
                        item.chat_id, arg1, amount
                    )
                    self._reply_or_send(
                        item,
                        f"{EMOJI['star']} {amount} XP به {arg1} داده شد. "
                        f"مجموع: {new_xp}",
                    )
                except ValueError:
                    self._reply_or_send(item, "فرمت: /givexp USER مقدار")
            else:
                self._reply_or_send(item, f"{EMOJI['lock']} فقط ادمین‌ها.")

        elif command == "/givecoins" and arg1:
            if admin_level >= AdminLevel.ADMIN:
                try:
                    amount = int(arg2) if arg2 else 100
                    new_coins = self.state.add_coins(
                        item.chat_id, arg1, amount
                    )
                    self._reply_or_send(
                        item,
                        f"{EMOJI['coin']} {amount} سکه به {arg1} داده شد. "
                        f"مجموع: {new_coins}",
                    )
                except ValueError:
                    self._reply_or_send(
                        item, "فرمت: /givecoins USER مقدار"
                    )
            else:
                self._reply_or_send(item, f"{EMOJI['lock']} فقط ادمین‌ها.")

        # ── Anti-Raid ─────────────────────────────────

        elif command == "/endraid":
            self.raid_detector.end_raid(item.chat_id)
            self._reply_or_send(
                item,
                f"{EMOJI['shield']} حالت ضد حمله غیرفعال شد.",
            )

        # ── Purge ─────────────────────────────────────

        elif command == "/purge" and arg1:
            if admin_level >= AdminLevel.ADMIN:
                try:
                    count = min(int(arg1), 100)
                    self._reply_or_send(
                        item,
                        f"{EMOJI['check']} درخواست حذف {count} پیام ارسال شد.\n"
                        "(اگر API پشتیبانی کند)",
                    )
                except ValueError:
                    self._reply_or_send(item, "عدد وارد کنید.")
            else:
                self._reply_or_send(item, f"{EMOJI['lock']} فقط ادمین‌ها.")

        else:
            self._reply_or_send(
                item,
                f"{EMOJI['question']} دستور ناشناخته. /help بزنید.",
            )

        return True

    def _help_text(self, level: AdminLevel) -> str:
        public = f"""{EMOJI['robot']} دستورات SoroBot Ultra:

{EMOJI['search']} عمومی:
  /id - نمایش اطلاعات
  /profile [USER] - پروفایل
  /level - سطح و XP
  /daily - پاداش روزانه
  /top [xp|coins|messages] - لیدربورد
  /dice - تاس
  /coinflip - شیر یا خط
  /vote N - رأی دادن
  /joinlottery - ثبت در قرعه‌کشی
  /rules - قوانین
  #نام - نمایش یادداشت"""

        mod = f"""
{EMOJI['shield']} مادریتور/ادمین:
  /help - راهنما
  /status - وضعیت ربات
  /warnings - لیست اخطارها
  /banlist - لیست ban
  /mutelist - لیست mute
  /viplist - لیست VIP
  /stats [روز] - آمار

  /forgive USER - پاک کردن اخطار
  /reset USER - ریست کامل کاربر
  /kick USER - اخراج
  /ban USER [دلیل] - مسدود
  /unban USER - رفع مسدود
  /mute USER [دقیقه] - سکوت
  /unmute USER - رفع سکوت

  /setmax N - سقف اخطار
  /addword WORD - افزودن کلمه ممنوع
  /delword WORD - حذف کلمه ممنوع
  /words - لیست کلمات ممنوع
  /allowdomain DOMAIN - مجاز کردن دامنه
  /deldomain DOMAIN - حذف دامنه
  /domains - لیست دامنه‌ها

  /toggle NAME - تغییر وضعیت فیلتر
  /slowmode N - تاخیر بین پیام‌ها
  /setwelcome TEXT - پیام خوش‌آمد

  /addvip USER - افزودن VIP
  /delvip USER - حذف VIP
  /addmod USER - افزودن مادریتور
  /delmod USER - حذف مادریتور

  /poll سوال|گزینه1|گزینه2 - نظرسنجی
  /closepoll - بستن نظرسنجی
  /lottery [تعداد] - قرعه‌کشی

  /setnote NAME TEXT - ذخیره یادداشت
  /delnote NAME - حذف یادداشت
  /notes - لیست یادداشت‌ها

  /addauto PATTERN RESPONSE - پاسخ خودکار
  /delauto INDEX - حذف پاسخ خودکار
  /autos - لیست پاسخ‌ها

  /remind دقیقه TEXT - یادآوری
  /schedule دقیقه TEXT - زمان‌بندی پیام
  /canceltask ID - لغو تسک
  /tasks - لیست تسک‌ها

  /say TEXT - ارسال پیام"""

        admin = f"""
{EMOJI['crown']} ادمین:
  /givexp USER مقدار - دادن XP
  /givecoins USER مقدار - دادن سکه
  /purge N - حذف پیام‌ها
  /backup - بکاپ تنظیمات
  /restore FILE - بازیابی
  /backups - لیست بکاپ‌ها
  /endraid - پایان حالت ضد حمله"""

        text = public
        if level >= AdminLevel.MOD:
            text += mod
        if level >= AdminLevel.ADMIN:
            text += admin

        return text

    # ── main process ──────────────────────────────────

    def process(self, item: ModerationEvent) -> None:
        log_debug("PROCESS:", item.sender_id, item.text[:50])

        # Handle joins/leaves
        if item.is_join:
            self._handle_join(item)
            return

        if item.is_leave:
            self._handle_leave(item)
            return

        # Commands
        if self._handle_command(item):
            return

        if not item.sender_id:
            return

        # Enforce banlist
        if self._enforce_banlist(item):
            return

        # Captcha check
        if self.state.get_toggle("captcha"):
            if self.captcha_manager.has_pending(
                item.chat_id, item.sender_id
            ):
                result = self.captcha_manager.check_answer(
                    item.chat_id, item.sender_id, item.text.strip()
                )
                if result is True:
                    self._reply_or_send(
                        item,
                        f"{EMOJI['check']} Captcha درست بود! خوش اومدی!",
                    )
                    return
                elif result is False:
                    self._delete_message(item)
                    self._kick_user(item, item.sender_id)
                    self._send_message(
                        item,
                        f"{EMOJI['cross']} {item.sender_name or item.sender_id} "
                        f"captcha را رد نکرد و حذف شد.",
                    )
                    return
                else:
                    self._delete_message(item)
                    return

        # Admin/VIP bypass
        if self._is_exempt(item, item.sender_id):
            log_debug("EXEMPT:", item.sender_id)
            self._track_user_activity(item)
            return

        # Muted check
        if self.state.is_muted(item.chat_id, item.sender_id):
            self._delete_message(item)
            return

        key = ModeratorState.user_key(item.chat_id, item.sender_id)

        # ── Anti-Forward Spam ─────────────────────────
        if self.state.get_toggle("anti_forward_spam") and item.is_forwarded:
            self._warn(item, "فوروارد اسپم", ViolationType.FORWARD_SPAM)
            return

        # ── Night Mode ────────────────────────────────
        if self.state.get_toggle("night_mode") and is_night_time():
            self._delete_message(item)
            self._reply_or_send(
                item,
                f"{EMOJI['moon']} گروه در حالت شبانه است. "
                f"لطفاً بعد از ساعت {NIGHT_MODE_END}:00 پیام دهید.",
            )
            return

        # ── Slow Mode ─────────────────────────────────
        if self.slow_mode.interval > 0:
            is_violation, remaining = self.slow_mode.check(key)
            if is_violation:
                self._delete_message(item)
                self._reply_or_send(
                    item,
                    f"{EMOJI['hourglass']} Slow mode! "
                    f"{remaining:.0f}s صبر کنید.",
                )
                return

        # ── Bad Words ─────────────────────────────────
        if self.state.get_toggle("anti_badword"):
            bad_word = contains_bad_word(item.text, self.state.bad_words())
            if bad_word:
                self._warn(
                    item,
                    f"استفاده از واژه ممنوع: {bad_word}",
                    ViolationType.BAD_WORD,
                )
                return

        # ── Links ─────────────────────────────────────
        if self.state.get_toggle("anti_link"):
            bad_link = find_disallowed_link(
                item.text, self.state.allowed_domains()
            )
            if bad_link:
                self._warn(
                    item,
                    f"ارسال لینک غیرمجاز: {bad_link}",
                    ViolationType.LINK,
                )
                return

        # ── Phone Number ──────────────────────────────
        if self.state.get_toggle("anti_phone"):
            if contains_phone_number(item.text):
                self._warn(
                    item,
                    "ارسال شماره تلفن",
                    ViolationType.PHONE_NUMBER,
                )
                return

        # ── Invisible Chars ───────────────────────────
        if self.state.get_toggle("anti_invisible"):
            if contains_invisible_chars(item.text):
                self._warn(
                    item,
                    "استفاده از کاراکترهای نامرئی مخرب",
                    ViolationType.INVISIBLE_CHARS,
                )
                return

        # ── CAPS abuse ────────────────────────────────
        if self.state.get_toggle("anti_caps"):
            if is_caps_abuse(item.text):
                self._warn(
                    item,
                    "استفاده بیش از حد از حروف بزرگ",
                    ViolationType.CAPS,
                )
                return

        # ── Long message ──────────────────────────────
        if self.state.get_toggle("anti_longmsg"):
            if len(item.text) > MAX_MESSAGE_LENGTH:
                self._warn(
                    item,
                    f"پیام خیلی طولانی ({len(item.text)}/{MAX_MESSAGE_LENGTH})",
                    ViolationType.LONG_MESSAGE,
                )
                return

        # ── Flood ─────────────────────────────────────
        if self.state.get_toggle("anti_flood"):
            if self.flood.hit(key):
                self._warn(
                    item,
                    "ارسال پیام بیش از حد مجاز",
                    ViolationType.FLOOD,
                )
                return

        # ── Repeat ────────────────────────────────────
        if self.state.get_toggle("anti_repeat"):
            if self.repeat.hit(key, item.text):
                self._warn(
                    item,
                    "تکرار یک متن",
                    ViolationType.REPEAT,
                )
                return

        # ── Auto Response ─────────────────────────────
        response = self.auto_responder.check(item.text)
        if response:
            self._reply_or_send(item, response)

        # ── Track activity ────────────────────────────
        self._track_user_activity(item)

        # ── Record stats ──────────────────────────────
        self.state.record_stat(item.chat_id, "messages")

        log_debug("OK: no violation")

    def _track_user_activity(self, item: ModerationEvent) -> None:
        user = self.state.update_user_activity(
            item.chat_id, item.sender_id, item.sender_name
        )

        # Level up notification
        if self.state.get_toggle("xp_enabled"):
            old_xp = user.get("xp", 0) - XP_PER_MESSAGE
            old_level = level_from_xp(max(0, old_xp))
            new_level = level_from_xp(user.get("xp", 0))
            if new_level > old_level:
                self._send_message(
                    item,
                    f"{EMOJI['party']} {item.sender_name or item.sender_id} "
                    f"به Level {new_level} رسید! "
                    f"{EMOJI['sparkle']}{EMOJI['muscle']}",
                )

    def _handle_join(self, item: ModerationEvent) -> None:
        log_debug("JOIN:", item.sender_id)

        # Anti-Raid
        if self.state.get_toggle("anti_raid"):
            is_raid = self.raid_detector.record_join(item.chat_id)
            if is_raid:
                self._send_message(
                    item,
                    f"{EMOJI['shield']}{EMOJI['boom']} هشدار! حمله گروهی تشخیص داده شد!\n"
                    f"اعضای جدید به صورت خودکار kick می‌شوند.\n"
                    f"برای پایان: /endraid",
                )

            if self.raid_detector.is_raid(item.chat_id):
                self._kick_user(item, item.sender_id)
                log_action(
                    "raid_kick",
                    {"user_id": item.sender_id, "chat_id": item.chat_id},
                )
                return

        # Banned check
        if self.state.is_banned(item.chat_id, item.sender_id):
            self._ban_user(item, item.sender_id)
            return

        # Captcha
        if self.state.get_toggle("captcha"):
            challenge = self.captcha_manager.create_challenge(
                item.chat_id, item.sender_id
            )
            self._send_message(
                item,
                f"{EMOJI['detective']} سلام {item.sender_name or item.sender_id}!\n"
                f"لطفاً برای تأیید انسان بودن، جواب بده:\n"
                f"{EMOJI['brain']} {challenge.question}\n"
                f"(فرصت: {CAPTCHA_TIMEOUT} ثانیه)",
            )
            return

        # Welcome
        if self.state.get_toggle("welcome_enabled"):
            custom = self.state._data["config"].get("welcome_message", "")
            if custom:
                msg = custom.replace(
                    "{name}",
                    item.sender_name or item.sender_id,
                )
            else:
                msg = random_welcome_message(
                    item.sender_name or item.sender_id
                )
            self._send_message(item, msg)

    def _handle_leave(self, item: ModerationEvent) -> None:
        log_debug("LEAVE:", item.sender_id)

        if self.state.get_toggle("goodbye_enabled"):
            msg = random_goodbye_message(
                item.sender_name or item.sender_id
            )
            self._send_message(item, msg)


# ╔══════════════════════════════════════════════════════╗
# ║                     Main                             ║
# ╚══════════════════════════════════════════════════════╝

def main() -> None:
    from soropy import SoroushClient

    client = SoroushClient(
        PHONE,
        backend="websocket",
        session_dir=SESSION_DIR,
        auto_reply_private_only=True,
    )

    moderator = GroupModerator(client)

    def shutdown(_signum: int, _frame: Any) -> None:
        print(f"\n{EMOJI['warn']} Shutdown signal received...")
        moderator.stop_event.set()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        client.on("new_message", moderator.on_event)

        print(f"{EMOJI['rocket']} در حال login...")
        client.login(
            code_callback=lambda: input("کد پیامک‌شده: ").strip()
        )

        print(f"{EMOJI['check']} Login done.")
        print(
            f"{EMOJI['robot']} SoroBot Ultra فعال شد!"
        )
        print(
            f"{EMOJI['bulb']} برای دیدن chat_id: /id"
        )
        print(f"{EMOJI['info']} برای راهنما: /help")
        print(f"{'='*50}")

        moderator.start()

        while not moderator.stop_event.is_set():
            time.sleep(0.5)

    finally:
        print(f"{EMOJI['hourglass']} Stopping...")
        moderator.stop()

        print(f"{EMOJI['cross']} Closing client...")
        client.close()

        print(f"{EMOJI['check']} Done. Goodbye!")


if __name__ == "__main__":
    main()
