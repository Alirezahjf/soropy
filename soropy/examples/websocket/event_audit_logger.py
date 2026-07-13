"""Audit logger برای eventهای WebSocket در SoroPy.

رویدادها را در فایل JSONL ذخیره می‌کند، payload حساس را sanitize می‌کند
و در پایان می‌تواند خلاصه را به یک chat گزارش دهد.

envها:
  SOROPY_PHONE
  SOROPY_SESSION_DIR
  SOROPY_AUDIT_LOG
  SOROPY_AUDIT_REPORT_TO
"""

from __future__ import annotations

import json
import os
import signal
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Set

PHONE = os.getenv("SOROPY_PHONE", "09123456789")
SESSION_DIR = os.getenv("SOROPY_SESSION_DIR", "soropy_ws_sessions")
AUDIT_LOG = os.getenv(
    "SOROPY_AUDIT_LOG",
    str(Path(SESSION_DIR) / "events_audit.jsonl"),
)
AUDIT_REPORT_TO = os.getenv("SOROPY_AUDIT_REPORT_TO", "").strip()

AUDITED_EVENTS = (
    "connected",
    "auth_success",
    "new_message",
    "message_sent",
    "chat_updated",
    "unread_changed",
    "error",
    "disconnected",
)

SENSITIVE_KEYS = {
    "phone",
    "token",
    "access_token",
    "refresh_token",
    "auth_key",
    "code",
}


def sanitize_payload(payload: Any, sensitive: Optional[Iterable[str]] = None) -> Any:
    """Recursively mask sensitive keys in dict/list payloads."""
    keys: Set[str] = {item.casefold() for item in (sensitive or SENSITIVE_KEYS)}
    return _sanitize(payload, keys)


def _sanitize(value: Any, keys: Set[str]) -> Any:
    if isinstance(value, dict):
        cleaned: Dict[str, Any] = {}
        for key, item in value.items():
            if str(key).casefold() in keys:
                cleaned[key] = "***"
            else:
                cleaned[key] = _sanitize(item, keys)
        return cleaned
    if isinstance(value, list):
        return [_sanitize(item, keys) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item, keys) for item in value]
    return value


class JsonlAuditLogger:
    """Thread-safe JSONL audit logger with counters."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)
        self._lock = threading.RLock()
        self.counts: Dict[str, int] = {name: 0 for name in AUDITED_EVENTS}
        self.total = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event_name: str, payload: Any = None) -> Dict[str, Any]:
        record = {
            "timestamp": int(time.time()),
            "event": event_name,
            "data": sanitize_payload(payload if payload is not None else {}),
        }
        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            self.total += 1
            if event_name in self.counts:
                self.counts[event_name] += 1
            else:
                self.counts[event_name] = self.counts.get(event_name, 0) + 1
        return record

    def summary(self) -> str:
        with self._lock:
            lines = [f"total={self.total}"]
            for name in AUDITED_EVENTS:
                lines.append(f"{name}={self.counts.get(name, 0)}")
            extras = sorted(
                key for key in self.counts if key not in AUDITED_EVENTS
            )
            for name in extras:
                lines.append(f"{name}={self.counts[name]}")
            return "Audit summary: " + ", ".join(lines)

    def counts_snapshot(self) -> Dict[str, int]:
        with self._lock:
            return dict(self.counts)


class EventAuditBot:
    def __init__(self, client: Any, logger: Optional[JsonlAuditLogger] = None):
        self.client = client
        self.logger = logger or JsonlAuditLogger(AUDIT_LOG)
        self.stop_event = threading.Event()

    def on_event(self, event: Any) -> None:
        name = getattr(event, "name", None) or "unknown"
        data = getattr(event, "data", None)
        try:
            self.logger.write(str(name), data)
        except Exception as exc:
            print(f"ثبت audit ناموفق بود: {exc}")

    def register(self) -> None:
        for name in AUDITED_EVENTS:
            self.client.on(name, self.on_event)

    def report_summary(self) -> None:
        if not AUDIT_REPORT_TO:
            return
        text = self.logger.summary()
        try:
            self.client.send_message(AUDIT_REPORT_TO, text)
        except Exception as exc:
            print(f"ارسال خلاصه audit ناموفق بود: {exc}")


def main() -> None:
    from soropy import SoroushClient

    client = SoroushClient(
        PHONE,
        backend="websocket",
        session_dir=SESSION_DIR,
        auto_reply_private_only=True,
    )
    bot = EventAuditBot(client)

    def _shutdown(_signum: int, _frame: Any) -> None:
        bot.stop_event.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        bot.register()
        client.login(code_callback=lambda: input("کد پیامک‌شده: ").strip())
        print(f"Audit logger فعال شد → {bot.logger.path}")
        print("برای خروج Ctrl+C بزنید.")
        while not bot.stop_event.is_set():
            time.sleep(0.5)
    finally:
        bot.report_summary()
        print(bot.logger.summary())
        client.close()


if __name__ == "__main__":
    main()
