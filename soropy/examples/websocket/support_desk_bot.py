"""میز پشتیبانی ticket-based برای SoroPy WebSocket.

پیام‌های خصوصی به ticket تبدیل می‌شوند و خلاصهٔ آن‌ها برای گروه اپراتورها
ارسال می‌شود. state به‌صورت atomic و thread-safe ذخیره می‌گردد و EventBus
با queue + worker مسدود نمی‌شود.

envها:
  SOROPY_PHONE
  SOROPY_SESSION_DIR
  SOROPY_SUPPORT_GROUP
  SOROPY_SUPPORT_GROUP_TARGET
  SOROPY_SUPPORT_WELCOME
"""

from __future__ import annotations

import json
import os
import queue
import signal
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

PHONE = os.getenv("SOROPY_PHONE", "09123456789")
SESSION_DIR = os.getenv("SOROPY_SESSION_DIR", "soropy_ws_sessions")
SUPPORT_GROUP = os.getenv("SOROPY_SUPPORT_GROUP", "گروه پشتیبانی")
SUPPORT_GROUP_TARGET = os.getenv("SOROPY_SUPPORT_GROUP_TARGET", SUPPORT_GROUP)
WELCOME = os.getenv(
    "SOROPY_SUPPORT_WELCOME",
    "پیام شما ثبت شد. پشتیبانی به‌زودی پاسخ می‌دهد.",
)
QUEUE_MAX_SIZE = 1000
TICKETS_FILENAME = "support_tickets.json"


@dataclass(frozen=True)
class SupportEvent:
    message_id: str
    chat_id: str
    chat_name: str
    sender_id: str
    sender_name: str
    text: str
    is_outgoing: bool
    is_private: bool
    is_group: bool

    @classmethod
    def from_payload(cls, data: Dict[str, Any]) -> "SupportEvent":
        return cls(
            message_id=str(data.get("message_id") or ""),
            chat_id=str(data.get("chat_id") or data.get("chat_name") or ""),
            chat_name=str(data.get("chat_name") or ""),
            sender_id=str(data.get("sender_id") or data.get("chat_id") or ""),
            sender_name=str(data.get("sender_name") or ""),
            text=str(data.get("text") or ""),
            is_outgoing=bool(data.get("is_outgoing")),
            is_private=bool(data.get("is_private")),
            is_group=bool(data.get("is_group")),
        )


def ticket_summary(ticket: Dict[str, Any]) -> str:
    """خلاصهٔ خوانا از یک ticket برای ارسال به گروه اپراتورها."""
    user_id = ticket.get("user_id") or "?"
    name = ticket.get("user_name") or user_id
    status = ticket.get("status") or "open"
    assignee = ticket.get("assignee") or "—"
    count = int(ticket.get("message_count") or 0)
    last = ticket.get("last_message") or ""
    if len(last) > 120:
        last = last[:117] + "..."
    created = ticket.get("created_at") or "?"
    updated = ticket.get("updated_at") or "?"
    return (
        f"🎫 Ticket #{user_id}\n"
        f"کاربر: {name}\n"
        f"وضعیت: {status}\n"
        f"مسئول: {assignee}\n"
        f"پیام‌ها: {count}\n"
        f"آخرین: {last}\n"
        f"ایجاد: {created} | بروزرسانی: {updated}"
    )


class TicketStore:
    """Persistent ticket store with atomic JSON writes and RLock."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._tickets: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        with self._lock:
            if not self.path.exists():
                self._tickets = {}
                return
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                self._tickets = raw if isinstance(raw, dict) else {}
            except Exception:
                self._tickets = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(self._tickets, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)

    def upsert_message(
        self,
        user_id: str,
        user_name: str,
        text: str,
        chat_id: str = "",
        chat_name: str = "",
    ) -> Dict[str, Any]:
        now = int(time.time())
        with self._lock:
            ticket = self._tickets.get(user_id)
            if ticket is None or ticket.get("status") == "closed":
                ticket = {
                    "user_id": user_id,
                    "user_name": user_name or user_id,
                    "chat_id": chat_id or user_id,
                    "chat_name": chat_name or user_name or user_id,
                    "status": "open",
                    "assignee": None,
                    "message_count": 0,
                    "messages": [],
                    "last_message": "",
                    "created_at": now,
                    "updated_at": now,
                    "closed_at": None,
                }
            ticket["user_name"] = user_name or ticket.get("user_name") or user_id
            ticket["chat_id"] = chat_id or ticket.get("chat_id") or user_id
            ticket["chat_name"] = chat_name or ticket.get("chat_name") or ticket["user_name"]
            ticket["status"] = "open"
            ticket["closed_at"] = None
            ticket["message_count"] = int(ticket.get("message_count") or 0) + 1
            ticket["last_message"] = text
            ticket["updated_at"] = now
            messages = ticket.setdefault("messages", [])
            messages.append({"text": text, "timestamp": now})
            if len(messages) > 50:
                del messages[:-50]
            self._tickets[user_id] = ticket
            self._save()
            return dict(ticket)

    def get(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            ticket = self._tickets.get(user_id)
            return dict(ticket) if ticket else None

    def list_open(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                dict(item)
                for item in self._tickets.values()
                if item.get("status") != "closed"
            ]

    def assign(self, user_id: str, operator_name: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            ticket = self._tickets.get(user_id)
            if not ticket:
                return None
            ticket["assignee"] = operator_name
            ticket["updated_at"] = int(time.time())
            if ticket.get("status") == "closed":
                ticket["status"] = "open"
                ticket["closed_at"] = None
            self._save()
            return dict(ticket)

    def close(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            ticket = self._tickets.get(user_id)
            if not ticket:
                return None
            now = int(time.time())
            ticket["status"] = "closed"
            ticket["closed_at"] = now
            ticket["updated_at"] = now
            self._save()
            return dict(ticket)

    def stats(self) -> Dict[str, int]:
        with self._lock:
            open_count = 0
            closed_count = 0
            assigned_count = 0
            total_messages = 0
            for ticket in self._tickets.values():
                if ticket.get("status") == "closed":
                    closed_count += 1
                else:
                    open_count += 1
                if ticket.get("assignee"):
                    assigned_count += 1
                total_messages += int(ticket.get("message_count") or 0)
            return {
                "total": len(self._tickets),
                "open": open_count,
                "closed": closed_count,
                "assigned": assigned_count,
                "messages": total_messages,
            }


class SupportDeskBot:
    def __init__(self, client: Any):
        self.client = client
        self.store = TicketStore(Path(SESSION_DIR) / TICKETS_FILENAME)
        self.stop_event = threading.Event()
        self.queue: "queue.Queue[SupportEvent]" = queue.Queue(maxsize=QUEUE_MAX_SIZE)
        self.worker = threading.Thread(
            target=self._worker_loop,
            name="soropy-support-desk",
            daemon=True,
        )
        self._welcomed: set[str] = set()

    def start(self) -> None:
        self.worker.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.worker.join(timeout=5)

    def on_event(self, event: Any) -> None:
        data = getattr(event, "data", None) or {}
        item = SupportEvent.from_payload(data)
        try:
            self.queue.put_nowait(item)
        except queue.Full:
            print("صف پشتیبانی پر است؛ پیام جدید نادیده گرفته شد.")

    def _worker_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                item = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.process(item)
            except Exception as exc:
                print(f"خطای پشتیبانی: {exc}")
            finally:
                self.queue.task_done()

    def _send_group(self, text: str, reply_to: str = "") -> None:
        try:
            if reply_to:
                self.client.reply(SUPPORT_GROUP_TARGET, reply_to, text)
            else:
                self.client.send_message(SUPPORT_GROUP_TARGET, text)
        except Exception as exc:
            print(f"ارسال به گروه اپراتورها ناموفق بود: {exc}")

    def _send_user(self, target: str, text: str, reply_to: str = "") -> None:
        try:
            if reply_to:
                self.client.reply(target, reply_to, text)
            else:
                self.client.send_message(target, text)
        except Exception as exc:
            print(f"ارسال به کاربر {target} ناموفق بود: {exc}")

    def _is_operator_group(self, item: SupportEvent) -> bool:
        if not item.is_group or item.is_outgoing:
            return False
        return item.chat_name == SUPPORT_GROUP or item.chat_id == SUPPORT_GROUP

    def _handle_operator_command(self, item: SupportEvent) -> bool:
        text = item.text.strip()
        if not text.startswith("/"):
            return False
        parts = text.split()
        command = parts[0].casefold()

        if command == "/tickets":
            open_tickets = self.store.list_open()
            if not open_tickets:
                self._send_group("هیچ ticket بازی وجود ندارد.", item.message_id)
                return True
            lines = [
                f"• {t.get('user_id')}: {t.get('user_name') or '?'} "
                f"[{t.get('assignee') or 'بدون مسئول'}] — {t.get('message_count', 0)} پیام"
                for t in open_tickets
            ]
            self._send_group("📋 Ticketهای باز:\n" + "\n".join(lines), item.message_id)
            return True

        if command == "/ticket" and len(parts) >= 2:
            user_id = parts[1]
            ticket = self.store.get(user_id)
            if not ticket:
                self._send_group(f"Ticket برای {user_id} یافت نشد.", item.message_id)
            else:
                self._send_group(ticket_summary(ticket), item.message_id)
            return True

        if command == "/assign" and len(parts) >= 3:
            user_id = parts[1]
            operator = " ".join(parts[2:])
            ticket = self.store.assign(user_id, operator)
            if not ticket:
                self._send_group(f"Ticket برای {user_id} یافت نشد.", item.message_id)
            else:
                self._send_group(
                    f"✅ Ticket {user_id} به {operator} اختصاص یافت.",
                    item.message_id,
                )
            return True

        if command == "/close" and len(parts) >= 2:
            user_id = parts[1]
            ticket = self.store.close(user_id)
            if not ticket:
                self._send_group(f"Ticket برای {user_id} یافت نشد.", item.message_id)
            else:
                self._send_group(f"🔒 Ticket {user_id} بسته شد.", item.message_id)
            return True

        if command == "/stats":
            stats = self.store.stats()
            self._send_group(
                "📊 آمار پشتیبانی\n"
                f"کل: {stats['total']}\n"
                f"باز: {stats['open']}\n"
                f"بسته: {stats['closed']}\n"
                f"اختصاص‌یافته: {stats['assigned']}\n"
                f"پیام‌ها: {stats['messages']}",
                item.message_id,
            )
            return True

        return False

    def process(self, item: SupportEvent) -> None:
        if self._is_operator_group(item):
            self._handle_operator_command(item)
            return

        if item.is_outgoing or not item.is_private or not item.text.strip():
            return

        user_id = item.sender_id or item.chat_id
        if not user_id:
            return

        ticket = self.store.upsert_message(
            user_id=user_id,
            user_name=item.sender_name or item.chat_name or user_id,
            text=item.text.strip(),
            chat_id=item.chat_id,
            chat_name=item.chat_name,
        )

        target = item.chat_name or item.chat_id or user_id
        if user_id not in self._welcomed and WELCOME:
            self._send_user(target, WELCOME, item.message_id)
            self._welcomed.add(user_id)

        self._send_group(
            "🆕 پیام پشتیبانی جدید\n" + ticket_summary(ticket),
        )


def main() -> None:
    from soropy import SoroushClient

    client = SoroushClient(
        PHONE,
        backend="websocket",
        session_dir=SESSION_DIR,
        auto_reply_private_only=True,
    )
    bot = SupportDeskBot(client)

    def _shutdown(_signum: int, _frame: Any) -> None:
        bot.stop_event.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        client.on("new_message", bot.on_event)
        client.login(code_callback=lambda: input("کد پیامک‌شده: ").strip())
        bot.start()
        print("میز پشتیبانی فعال شد. برای خروج Ctrl+C بزنید.")
        while not bot.stop_event.is_set():
            time.sleep(0.5)
    finally:
        bot.stop()
        client.close()


if __name__ == "__main__":
    main()
