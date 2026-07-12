#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SoroPy Interactive Manager – منوی تعاملی فارسی
==============================================

اجرا از ریشهٔ ریپو::

    python interactive_manager.py

یا بعد از نصب پکیج از examples::

    python -m examples.interactive_manager   # اگر path درست باشد
    python soropy/examples/interactive_manager.py
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from typing import Any, Dict, List, Optional

# Allow running without install (repo root or examples/)
_HERE = os.path.dirname(os.path.abspath(__file__))
# examples/ → package parent (…/soropy/) that contains the soropy package dir
_CANDIDATES = [
    os.path.join(_HERE, "soropy"),                 # repo root layout
    os.path.dirname(_HERE),                        # …/soropy/ (has soropy/ package)
    os.path.join(os.path.dirname(_HERE), "soropy"),
    os.path.abspath(os.path.join(_HERE, "..")),
    os.path.abspath(os.path.join(_HERE, "..", "..")),
]
for _p in _CANDIDATES:
    if os.path.isdir(os.path.join(_p, "soropy")) and _p not in sys.path:
        sys.path.insert(0, _p)
        break

try:
    import soropy
    from soropy import SoroushClient
    from soropy.exceptions import LoginError, SoroPyError
except ImportError as exc:
    print("❌ نصب soropy لازم است:")
    print('   pip install -e "./soropy[ws]"')
    print("   یا: pip install \"soropy[ws] @ git+https://github.com/Alirezahjf/soropy.git@arena/019f5686-soropy#subdirectory=soropy\"")
    print(f"   جزئیات: {exc}")
    sys.exit(1)


CONFIG_PATH = os.path.join(_HERE, "manager_config.json")

DEFAULT_CONFIG: Dict[str, Any] = {
    "phone": "",
    "backend": "websocket",
    "headless": True,
    "auto_reply_enabled": True,
    "private_only": True,
    "listener_enabled": False,
    "monitor_enabled": False,
    "log_messages": True,
    "rules": {},
    "default_reply": "",
    "monitor_interval": 120,
}


def clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def pause(msg: str = "Enter برای ادامه...") -> None:
    try:
        input(f"\n  {msg}")
    except EOFError:
        pass


def banner() -> None:
    ver = getattr(soropy, "__version__", "?")
    print(
        f"""
╔══════════════════════════════════════════════════╗
║     SoroPy Interactive Manager  v{ver:<8}       ║
║     مدیریت سروش‌پلاس – منوی فارسی              ║
╚══════════════════════════════════════════════════╝
"""
    )


def load_config() -> Dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                cfg.update(data)
        except Exception as exc:
            print(f"⚠ خواندن config ناموفق: {exc}")
    return cfg


def save_config(cfg: Dict[str, Any]) -> None:
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        print(f"⚠ ذخیره config ناموفق: {exc}")


class ManagerApp:
    def __init__(self) -> None:
        self.cfg = load_config()
        self.client: Optional[SoroushClient] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._listener_handler = None
        self._live_stop = threading.Event()
        self._live_messages: List[str] = []

    # ── helpers ────────────────────────────────────────

    def _safe_call(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except SoroPyError as exc:
            print(f"  ⚠ {exc}")
            return None
        except Exception as exc:
            print(f"  ❌ خطا: {exc}")
            traceback.print_exc()
            return None

    def _need_client(self) -> bool:
        if self.client is None or not self.client.is_logged_in:
            print("  ⚠ ابتدا لاگین کنید (گزینه ۱).")
            return False
        return True

    def _apply_rules_to_client(self) -> None:
        if not self.client:
            return
        self.client.auto_reply_engine.clear_rules()
        rules = self.cfg.get("rules") or {}
        if rules:
            self.client.load_reply_rules(rules)
        dr = self.cfg.get("default_reply") or ""
        self.client.set_default_reply(dr if dr else None)
        self.client.set_auto_reply_enabled(bool(self.cfg.get("auto_reply_enabled", True)))
        self.client.set_private_only(bool(self.cfg.get("private_only", True)))

    def _on_new_message(self, event) -> None:
        data = event.data or {}
        if not self.cfg.get("log_messages", True) and not self.cfg.get("listener_enabled"):
            return
        kind = (
            "PV"
            if data.get("is_private")
            else "گروه"
            if data.get("is_group")
            else "کانال"
            if data.get("is_channel")
            else "?"
        )
        line = (
            f"[{kind}] {data.get('chat_name', '?')}: "
            f"{(data.get('text') or '')[:80]}"
        )
        self._live_messages.append(line)
        if self.cfg.get("log_messages", True):
            print(f"\n  ← {line}")

    # ── 1. login ───────────────────────────────────────

    def menu_login(self) -> None:
        print("\n── لاگین / اتصال ──")
        phone = input(f"  شماره [{self.cfg.get('phone') or 'خالی'}]: ").strip()
        if not phone:
            phone = self.cfg.get("phone") or ""
        if not phone:
            print("  شماره لازم است.")
            return

        backend = input(
            f"  backend [websocket/selenium] "
            f"({self.cfg.get('backend', 'websocket')}): "
        ).strip().lower()
        if not backend:
            backend = self.cfg.get("backend") or "websocket"
        if backend in ("ws", "w", "1"):
            backend = "websocket"
        if backend in ("s", "sel", "2"):
            backend = "selenium"

        self.cfg["phone"] = phone
        self.cfg["backend"] = backend
        save_config(self.cfg)

        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None

        print(f"  در حال اتصال با backend={backend} ...")
        try:
            self.client = SoroushClient(
                phone,
                backend=backend,
                headless=bool(self.cfg.get("headless", True)),
                auto_reply_private_only=bool(self.cfg.get("private_only", True)),
            )
        except Exception as exc:
            print(f"  ❌ ساخت کلاینت: {exc}")
            self.client = None
            return

        self._apply_rules_to_client()

        # Always wire listener (toggle controls printing)
        try:
            self.client.on("new_message", self._on_new_message)
        except Exception:
            pass

        try:
            status = self.client.login()
            print(f"  ✅ لاگین: {status.value if hasattr(status, 'value') else status}")
        except LoginError as exc:
            print(f"  ❌ لاگین ناموفق: {exc}")
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None
            return
        except Exception as exc:
            print(f"  ❌ {exc}")
            traceback.print_exc()
            try:
                if self.client:
                    self.client.close()
            except Exception:
                pass
            self.client = None
            return

        if self.cfg.get("monitor_enabled"):
            self._start_monitor_bg()

    # ── 2. status ──────────────────────────────────────

    def menu_status(self) -> None:
        print("\n── وضعیت ──")
        print(f"  نسخه soropy     : {getattr(soropy, '__version__', '?')}")
        print(f"  شماره           : {self.cfg.get('phone') or '—'}")
        print(f"  backend         : {self.cfg.get('backend')}")
        print(f"  لاگین           : {'✅' if self.client and self.client.is_logged_in else '❌'}")
        print(f"  Auto-reply      : {'ON' if self.cfg.get('auto_reply_enabled') else 'OFF'}")
        print(f"  فقط PV          : {'ON' if self.cfg.get('private_only') else 'OFF'}")
        print(f"  Listener        : {'ON' if self.cfg.get('listener_enabled') else 'OFF'}")
        print(f"  Monitor poll    : {'ON' if self.cfg.get('monitor_enabled') else 'OFF'}")
        print(f"  لاگ پیام‌ها     : {'ON' if self.cfg.get('log_messages') else 'OFF'}")
        print(f"  تعداد قوانین    : {len(self.cfg.get('rules') or {})}")
        print(f"  default_reply   : {self.cfg.get('default_reply') or '—'}")
        print("\n  قابلیت‌های API (websocket):")
        for name in (
            "send_file", "download_media", "delete_messages", "edit_message",
            "pin_message", "kick", "ban", "unban", "promote", "block_user",
            "report", "get_participants", "reply", "send_to_group",
        ):
            ok = self.client is not None and hasattr(self.client, name)
            print(f"    {'✅' if ok else '❌'} {name}")

        if self.client and self.client.is_logged_in:
            me = self._safe_call(self.client.get_me)
            if me:
                print(f"\n  اکانت: {me}")

    # ── 3. chats ───────────────────────────────────────

    def menu_chats(self) -> None:
        if not self._need_client():
            return
        print("\n── لیست چت‌ها ──")
        chats = self._safe_call(self.client.get_chats)
        if chats is None:
            return
        print(f"  شخصی ({len(chats.personal)}):")
        for n in chats.personal[:30]:
            print(f"    • {n}")
        print(f"  گروه ({len(chats.groups)}):")
        for n in chats.groups[:20]:
            print(f"    • {n}")
        print(f"  کانال ({len(chats.channels)}):")
        for n in chats.channels[:20]:
            print(f"    • {n}")
        save = input("  ذخیره JSON؟ [مسیر/خالی=نه]: ").strip()
        if save:
            self._safe_call(self.client.get_chats, save_to=save)
            print(f"  ذخیره شد: {save}")

    # ── 4. send ────────────────────────────────────────

    def menu_send(self) -> None:
        if not self._need_client():
            return
        print(
            """
── ارسال ──
  1) متن
  2) ریپلای
  3) چندتایی
  4) فایل
  5) گروه
  6) کانال
  0) برگشت
"""
        )
        choice = input("  انتخاب: ").strip()
        if choice == "1":
            chat = input("  چت: ").strip()
            text = input("  متن: ").strip()
            r = self._safe_call(self.client.send_message, chat, text)
            print(f"  → {r}")
        elif choice == "2":
            chat = input("  چت: ").strip()
            mid = input("  message_id: ").strip()
            text = input("  متن: ").strip()
            r = self._safe_call(self.client.reply, chat, mid, text)
            print(f"  → {r}")
        elif choice == "3":
            raw = input("  چت‌ها (با کاما): ").strip()
            text = input("  متن: ").strip()
            names = [x.strip() for x in raw.split(",") if x.strip()]
            r = self._safe_call(self.client.send_bulk_messages, names, text)
            print(f"  → {r}")
        elif choice == "4":
            chat = input("  چت: ").strip()
            path = input("  مسیر فایل: ").strip()
            cap = input("  کپشن: ").strip()
            r = self._safe_call(
                self.client.send_file, chat, path, caption=cap
            )
            print(f"  → {r}")
        elif choice == "5":
            g = input("  گروه: ").strip()
            text = input("  متن: ").strip()
            r = self._safe_call(self.client.send_to_group, g, text)
            print(f"  → {r}")
        elif choice == "6":
            ch = input("  کانال (@ یا نام): ").strip()
            text = input("  متن: ").strip()
            r = self._safe_call(self.client.send_to_channel, ch, text)
            print(f"  → {r}")

    # ── 5. rules ───────────────────────────────────────

    def menu_rules(self) -> None:
        print(
            """
── قوانین پاسخ خودکار ──
  1) افزودن قانون
  2) حذف قانون
  3) تنظیم default_reply
  4) نمایش قوانین
  5) import JSON
  6) export JSON
  7) Auto-reply ON/OFF
  8) فقط PV ON/OFF
  0) برگشت
"""
        )
        choice = input("  انتخاب: ").strip()
        rules = dict(self.cfg.get("rules") or {})

        if choice == "1":
            kw = input("  کلمه کلیدی: ").strip()
            resp = input("  پاسخ: ").strip()
            if kw and resp:
                rules[kw] = resp
                self.cfg["rules"] = rules
                save_config(self.cfg)
                if self.client:
                    self.client.add_reply_rule(kw, resp)
                print("  ✅ اضافه شد")
        elif choice == "2":
            kw = input("  کلمه کلیدی: ").strip()
            if kw in rules:
                del rules[kw]
                self.cfg["rules"] = rules
                save_config(self.cfg)
                if self.client:
                    self.client.remove_reply_rule(kw)
                print("  ✅ حذف شد")
            else:
                print("  پیدا نشد")
        elif choice == "3":
            dr = input("  default_reply (خالی=خاموش): ").strip()
            self.cfg["default_reply"] = dr
            save_config(self.cfg)
            if self.client:
                self.client.set_default_reply(dr if dr else None)
            print("  ✅")
        elif choice == "4":
            print(f"  default: {self.cfg.get('default_reply') or '—'}")
            for k, v in rules.items():
                print(f"    «{k}» → «{v}»")
        elif choice == "5":
            path = input("  مسیر JSON: ").strip()
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    rules.update({str(k): str(v) for k, v in data.items()})
                    self.cfg["rules"] = rules
                    save_config(self.cfg)
                    self._apply_rules_to_client()
                    print(f"  ✅ {len(data)} قانون")
            except Exception as exc:
                print(f"  ❌ {exc}")
        elif choice == "6":
            path = input("  مسیر خروجی: ").strip() or "rules_export.json"
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(rules, f, ensure_ascii=False, indent=2)
                print(f"  ✅ {path}")
            except Exception as exc:
                print(f"  ❌ {exc}")
        elif choice == "7":
            self.cfg["auto_reply_enabled"] = not bool(
                self.cfg.get("auto_reply_enabled", True)
            )
            save_config(self.cfg)
            if self.client:
                self.client.set_auto_reply_enabled(self.cfg["auto_reply_enabled"])
            print(
                f"  Auto-reply → "
                f"{'ON' if self.cfg['auto_reply_enabled'] else 'OFF'}"
            )
        elif choice == "8":
            self.cfg["private_only"] = not bool(self.cfg.get("private_only", True))
            save_config(self.cfg)
            if self.client:
                self.client.set_private_only(self.cfg["private_only"])
            print(
                f"  فقط PV → {'ON' if self.cfg['private_only'] else 'OFF'}"
            )

    # ── 6. services ────────────────────────────────────

    def _start_monitor_bg(self) -> None:
        if not self.client or not self.client.is_logged_in:
            return
        try:
            self.client.stop_monitor()
        except Exception:
            pass
        interval = int(self.cfg.get("monitor_interval") or 120)
        self._monitor_thread = self.client.start_monitor(
            interval=interval, blocking=False
        )
        print(f"  Monitor poll روشن (interval≈{interval}s، فقط PV)")

    def menu_services(self) -> None:
        print(
            f"""
── سرویس‌ها ──
  Listener realtime : {'ON' if self.cfg.get('listener_enabled') else 'OFF'}
  Monitor poll      : {'ON' if self.cfg.get('monitor_enabled') else 'OFF'}
  Auto-reply        : {'ON' if self.cfg.get('auto_reply_enabled') else 'OFF'}
  فقط PV            : {'ON' if self.cfg.get('private_only') else 'OFF'}
  لاگ پیام‌ها       : {'ON' if self.cfg.get('log_messages') else 'OFF'}

  1) Listener ON/OFF
  2) Monitor ON/OFF
  3) Auto-reply ON/OFF
  4) فقط PV ON/OFF
  5) لاگ پیام‌ها ON/OFF
  6) تنظیم interval مانیتور
  0) برگشت
"""
        )
        choice = input("  انتخاب: ").strip()
        if choice == "1":
            self.cfg["listener_enabled"] = not bool(
                self.cfg.get("listener_enabled")
            )
            save_config(self.cfg)
            print(
                f"  Listener → "
                f"{'ON' if self.cfg['listener_enabled'] else 'OFF'}"
            )
            print("  (رویداد new_message همیشه وصل است؛ این فلگ فقط نمایش/لاگ)")
        elif choice == "2":
            self.cfg["monitor_enabled"] = not bool(self.cfg.get("monitor_enabled"))
            save_config(self.cfg)
            if self.cfg["monitor_enabled"]:
                if self._need_client():
                    self._start_monitor_bg()
            else:
                if self.client:
                    self.client.stop_monitor()
                    print("  Monitor خاموش")
        elif choice == "3":
            self.cfg["auto_reply_enabled"] = not bool(
                self.cfg.get("auto_reply_enabled", True)
            )
            save_config(self.cfg)
            if self.client:
                self.client.set_auto_reply_enabled(self.cfg["auto_reply_enabled"])
            print(
                f"  Auto-reply → "
                f"{'ON' if self.cfg['auto_reply_enabled'] else 'OFF'}"
            )
        elif choice == "4":
            self.cfg["private_only"] = not bool(self.cfg.get("private_only", True))
            save_config(self.cfg)
            if self.client:
                self.client.set_private_only(self.cfg["private_only"])
            print(f"  فقط PV → {'ON' if self.cfg['private_only'] else 'OFF'}")
        elif choice == "5":
            self.cfg["log_messages"] = not bool(self.cfg.get("log_messages", True))
            save_config(self.cfg)
            print(f"  لاگ → {'ON' if self.cfg['log_messages'] else 'OFF'}")
        elif choice == "6":
            raw = input("  interval ثانیه (حداقل ۱۲۰ برای WS): ").strip()
            try:
                self.cfg["monitor_interval"] = max(10, int(raw))
                save_config(self.cfg)
                print(f"  interval = {self.cfg['monitor_interval']}")
            except ValueError:
                print("  عدد نامعتبر")

    # ── 7. live ────────────────────────────────────────

    def menu_live(self) -> None:
        if not self._need_client():
            return
        print("\n── حالت زنده (Ctrl+C برای توقف) ──")
        print("  پیام‌های realtime اینجا نمایش داده می‌شوند.")
        print("  Auto-reply فقط روی PV (اگر قوانین ست شده باشند).")
        self.cfg["listener_enabled"] = True
        self.cfg["log_messages"] = True
        save_config(self.cfg)
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\n  توقف live.")

    # ── 8. contacts ────────────────────────────────────

    def menu_contacts(self) -> None:
        if not self._need_client():
            return
        print(
            """
── مخاطبین ──
  1) لیست
  2) افزودن
  3) جستجو
  0) برگشت
"""
        )
        choice = input("  انتخاب: ").strip()
        if choice == "1":
            names = self._safe_call(self.client.get_contacts) or []
            for n in names[:50]:
                print(f"    • {n}")
            print(f"  تعداد: {len(names)}")
        elif choice == "2":
            phone = input("  شماره: ").strip()
            first = input("  نام: ").strip()
            last = input("  نام‌خانوادگی: ").strip()
            ok = self._safe_call(self.client.add_contact, phone, first, last)
            print(f"  → {ok}")
        elif choice == "3":
            q = input("  جستجو: ").strip()
            r = self._safe_call(self.client.search_contacts, q) or []
            for n in r:
                print(f"    • {n}")

    # ── 9. moderation ──────────────────────────────────

    def menu_moderation(self) -> None:
        if not self._need_client():
            return
        print(
            """
── مودریشن (نیاز ادمین / websocket) ──
  1) kick
  2) ban
  3) unban
  4) promote
  5) set_permissions (send_messages=False)
  6) get_participants
  7) get_permissions
  8) block_user
  9) unblock_user
 10) report
  0) برگشت
"""
        )
        choice = input("  انتخاب: ").strip()
        if choice in ("1", "2", "3", "4", "5"):
            chat = input("  چت/گروه: ").strip()
            user = input("  کاربر: ").strip()
            if choice == "1":
                print("  →", self._safe_call(self.client.kick, chat, user))
            elif choice == "2":
                print("  →", self._safe_call(self.client.ban, chat, user))
            elif choice == "3":
                print("  →", self._safe_call(self.client.unban, chat, user))
            elif choice == "4":
                print("  →", self._safe_call(self.client.promote, chat, user))
            elif choice == "5":
                print(
                    "  →",
                    self._safe_call(
                        self.client.set_permissions,
                        chat,
                        user,
                        send_messages=False,
                    ),
                )
        elif choice == "6":
            chat = input("  چت: ").strip()
            parts = self._safe_call(self.client.get_participants, chat) or []
            for p in parts[:40]:
                print(f"    • {p}")
        elif choice == "7":
            chat = input("  چت: ").strip()
            user = input("  کاربر (خالی=خودت): ").strip() or None
            print("  →", self._safe_call(self.client.get_permissions, chat, user))
        elif choice == "8":
            user = input("  کاربر: ").strip()
            print("  →", self._safe_call(self.client.block_user, user))
        elif choice == "9":
            user = input("  کاربر: ").strip()
            print("  →", self._safe_call(self.client.unblock_user, user))
        elif choice == "10":
            ent = input("  entity: ").strip()
            reason = input("  reason [spam]: ").strip() or "spam"
            print("  →", self._safe_call(self.client.report, ent, reason))

    # ── 10. message tools ──────────────────────────────

    def menu_message_tools(self) -> None:
        if not self._need_client():
            return
        print(
            """
── ابزار پیام ──
  1) حذف
  2) ادیت
  3) پین
  4) آن‌پین
  5) دانلود مدیا
  0) برگشت
"""
        )
        choice = input("  انتخاب: ").strip()
        chat = input("  چت: ").strip() if choice in "12345" else ""
        if choice == "1":
            mids = input("  message_id(ها) با کاما: ").strip()
            ids = [x.strip() for x in mids.split(",") if x.strip()]
            print("  →", self._safe_call(self.client.delete_messages, chat, ids))
        elif choice == "2":
            mid = input("  message_id: ").strip()
            text = input("  متن جدید: ").strip()
            print("  →", self._safe_call(self.client.edit_message, chat, mid, text))
        elif choice == "3":
            mid = input("  message_id: ").strip()
            print("  →", self._safe_call(self.client.pin_message, chat, mid))
        elif choice == "4":
            mid = input("  message_id (خالی=همه): ").strip() or None
            print("  →", self._safe_call(self.client.unpin_message, chat, mid))
        elif choice == "5":
            mid = input("  message_id: ").strip()
            path = input("  مسیر ذخیره (اختیاری): ").strip() or None
            print(
                "  →",
                self._safe_call(self.client.download_media, chat, mid, path),
            )

    # ── 11. quick test ─────────────────────────────────

    def menu_test(self) -> None:
        print("\n── تست سریع API ──")
        print(f"  version = {soropy.__version__}")
        phone = self.cfg.get("phone") or "09121111111"
        try:
            c = SoroushClient(phone, backend="websocket")
            for name in (
                "send_file", "kick", "ban", "promote", "block_user",
                "reply", "download_media", "delete_messages", "edit_message",
                "pin_message", "unban", "report", "get_participants",
            ):
                print(f"  {'✅' if hasattr(c, name) else '❌'} {name}")
            c.close()
            print("  API OK")
        except Exception as exc:
            print(f"  ❌ {exc}")

        # phone validation
        from soropy.utils import is_valid_iranian_mobile, validate_phone
        for sample, expect in (
            ("09123456789", True),
            ("0912xxxxxxx", False),
            ("123", False),
            ("+989123456789", True),
        ):
            ok = is_valid_iranian_mobile(sample)
            mark = "✅" if ok == expect else "❌"
            print(f"  {mark} is_valid({sample!r}) = {ok}")

    # ── 12. delete session ─────────────────────────────

    def menu_delete_session(self) -> None:
        if self.client is None:
            phone = self.cfg.get("phone") or input("  شماره: ").strip()
            backend = self.cfg.get("backend") or "websocket"
            try:
                tmp = SoroushClient(phone, backend=backend)
                ok = tmp.delete_session()
                tmp.close()
                print(f"  حذف سشن: {ok}")
            except Exception as exc:
                print(f"  ❌ {exc}")
            return
        ok = self._safe_call(self.client.delete_session)
        print(f"  حذف سشن: {ok}")

    # ── 13. logout ─────────────────────────────────────

    def menu_logout(self) -> None:
        if self.client:
            try:
                self.client.stop_monitor()
            except Exception:
                pass
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None
            print("  ✅ خارج شدید (سشن فایل حذف نشد؛ برای حذف گزینه ۱۲).")
        else:
            print("  کلاینتی باز نیست.")

    # ── main loop ──────────────────────────────────────

    def run(self) -> None:
        while True:
            clear_screen()
            banner()
            st = "✅ متصل" if self.client and self.client.is_logged_in else "❌ قطع"
            print(
                f"  وضعیت: {st} | backend={self.cfg.get('backend')} | "
                f"phone={self.cfg.get('phone') or '—'} | "
                f"AR={'ON' if self.cfg.get('auto_reply_enabled') else 'OFF'} "
                f"PV-only={'ON' if self.cfg.get('private_only') else 'OFF'} "
                f"L={'ON' if self.cfg.get('listener_enabled') else 'OFF'} "
                f"M={'ON' if self.cfg.get('monitor_enabled') else 'OFF'}"
            )
            print(
                """
  1) لاگین / اتصال
  2) وضعیت اکانت + قابلیت‌ها
  3) لیست چت‌ها
  4) ارسال (متن / ریپلای / چندتایی / فایل)
  5) قوانین پاسخ خودکار
  6) سرویس‌ها (Listener / Monitor / toggles)
  7) حالت زنده (Live feed)
  8) مخاطبین
  9) مودریشن
 10) ابزار پیام (حذف/ادیت/پین/دانلود)
 11) تست سریع
 12) حذف سشن
 13) خروج از اکانت
  0) خروج از برنامه
"""
            )
            choice = input("  انتخاب شما: ").strip()
            actions = {
                "1": self.menu_login,
                "2": self.menu_status,
                "3": self.menu_chats,
                "4": self.menu_send,
                "5": self.menu_rules,
                "6": self.menu_services,
                "7": self.menu_live,
                "8": self.menu_contacts,
                "9": self.menu_moderation,
                "10": self.menu_message_tools,
                "11": self.menu_test,
                "12": self.menu_delete_session,
                "13": self.menu_logout,
            }
            if choice == "0":
                self.menu_logout()
                print("  خداحافظ 👋")
                break
            fn = actions.get(choice)
            if fn:
                try:
                    fn()
                except KeyboardInterrupt:
                    print("\n  (لغو)")
                except Exception as exc:
                    print(f"  ❌ {exc}")
                    traceback.print_exc()
                pause()
            else:
                print("  گزینه نامعتبر")
                time.sleep(0.8)


def main() -> None:
    app = ManagerApp()
    try:
        app.run()
    except KeyboardInterrupt:
        print("\n  خروج.")
        app.menu_logout()


if __name__ == "__main__":
    main()
