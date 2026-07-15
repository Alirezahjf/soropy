"""ارسال تعاملی عکس/فایل با SoroPy WebSocket.

ویژگی‌ها:
  - اولویت با @username یا chat_id است (نه اسم نمایشی چت).
    این باعث می‌شود خطای Entity not found برای گروه‌ها کمتر شود.
  - لیست چت‌ها همراه با id و username از get_dialogs نمایش داده می‌شود.
  - fallback هوشمند: اگر target اصلی fail شد، target‌های دیگر امتحان می‌شوند.
  - کپشن، force_document و فاصله بین ارسال‌ها قابل تنظیم است.
  - قبل از اجرا مطمئن می‌شود SoroPy 1.3.6+ با extra وب‌سوکت نصب است
    و در صورت نیاز با چند روش (local source، PyPI، GitHub) آپدیت می‌کند.

نصب پیشنهادی:

    python -m pip install --upgrade "soropy[ws]>=1.3.6"

اجرا:

    python send_file_interactive.py

envها:
  SOROPY_PHONE          شماره پیش‌فرض (09123456789)
  SOROPY_SESSION_DIR    مسیر session (soropy_ws_sessions)
  SOROPY_SEND_DELAY     فاصله ارسال به ثانیه (3)
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any, List, Optional, Tuple

REQUIRED_SOROPY_VERSION = "1.3.6"
GITHUB_INSTALL_SPEC = (
    "soropy[ws] @ "
    "git+https://github.com/Alirezahjf/soropy.git@main#subdirectory=soropy"
)


def _version_tuple(value: str) -> Tuple[int, ...]:
    parts = []
    for chunk in str(value or "").replace("-", ".").split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        if digits:
            parts.append(int(digits))
        else:
            break
    return tuple(parts or [0])


def _installed_soropy_version() -> Optional[str]:
    try:
        return metadata.version("soropy")
    except metadata.PackageNotFoundError:
        return None


def _has_ws_dependencies() -> bool:
    return importlib.util.find_spec("splusthon") is not None


def _run_pip(args: List[str], cwd: Optional[Path] = None) -> bool:
    cmd = [sys.executable, "-m", "pip", *args]
    print("🔧 اجرای نصب/آپدیت:", " ".join(cmd))
    try:
        subprocess.check_call(cmd, cwd=str(cwd) if cwd else None)
        importlib.invalidate_caches()
        return True
    except Exception as exc:
        print("⚠️ این روش نصب ناموفق بود:", exc)
        return False


def ensure_latest_soropy() -> None:
    """Ensure this example runs with SoroPy >= 1.3.6 and ws extras.

    The local source checkout is tried first so running this example from a
    downloaded repository uses the code next to it.  PyPI and GitHub are used as
    additional fallbacks.  Set ``SOROPY_SKIP_AUTO_INSTALL=1`` to disable.
    """
    if os.getenv("SOROPY_SKIP_AUTO_INSTALL", "").strip().lower() in {"1", "true", "yes"}:
        return

    installed = _installed_soropy_version()
    if (
        installed
        and _version_tuple(installed) >= _version_tuple(REQUIRED_SOROPY_VERSION)
        and _has_ws_dependencies()
    ):
        return

    print("\n📦 بررسی نسخه SoroPy/WebSocket...")
    print("نسخه نصب‌شده:", installed or "نصب نیست")
    print("نسخه لازم برای این مثال:", REQUIRED_SOROPY_VERSION)

    install_attempts: List[Tuple[List[str], Optional[Path]]] = []
    local_project = Path(__file__).resolve().parents[2]
    if (local_project / "pyproject.toml").exists():
        install_attempts.append((["install", "--upgrade", ".[ws]"], local_project))

    install_attempts.extend(
        [
            (["install", "--upgrade", f"soropy[ws]>={REQUIRED_SOROPY_VERSION}"], None),
            (["install", "--upgrade", GITHUB_INSTALL_SPEC], None),
            (
                [
                    "install",
                    "--upgrade",
                    "soropy",
                    "splusthon>=1.1.2,<1.1.3",
                    "aiohttp>=3.8.0",
                    "pyaes>=1.6.1",
                    "rsa>=4.0",
                ],
                None,
            ),
        ]
    )

    for args, cwd in install_attempts:
        if _run_pip(args, cwd=cwd):
            installed = _installed_soropy_version()
            if (
                installed
                and _version_tuple(installed) >= _version_tuple(REQUIRED_SOROPY_VERSION)
                and _has_ws_dependencies()
            ):
                print("✅ SoroPy به‌روز است:", installed)
                return

    raise RuntimeError(
        "SoroPy/WebSocket به نسخه لازم آپدیت نشد. دستی اجرا کنید:\n"
        f"  {sys.executable} -m pip install --upgrade 'soropy[ws]>={REQUIRED_SOROPY_VERSION}'\n"
        "یا از داخل سورس پروژه:\n"
        f"  {sys.executable} -m pip install --upgrade '.[ws]'"
    )


ensure_latest_soropy()

from soropy import SoroushClient

PHONE = os.getenv("SOROPY_PHONE", "09123456789")
SESSION_DIR = os.getenv("SOROPY_SESSION_DIR", "soropy_ws_sessions")
DEFAULT_DELAY = float(os.getenv("SOROPY_SEND_DELAY", "3"))


# ── data structures ──────────────────────────────────


@dataclass
class ChatItem:
    index: int
    name: str
    kind: str
    chat_id: str = ""
    username: str = ""

    @property
    def primary_target(self) -> str:
        """بهترین target برای ارسال: ۱) @username  ۲) chat_id  ۳) name"""
        if self.username:
            return "@" + self.username.lstrip("@")
        if self.chat_id:
            return self.chat_id
        return self.name

    @property
    def fallback_targets(self) -> List[str]:
        """اگر target اصلی fail شد، این‌ها را هم امتحان می‌کنیم."""
        values: List[str] = []
        if self.username:
            values.append("@" + self.username.lstrip("@"))
        if self.chat_id:
            values.append(self.chat_id)
        if self.name:
            values.append(self.name)
        # حذف تکراری‌ها
        out: List[str] = []
        for value in values:
            if value and value not in out:
                out.append(value)
        return out


# ── helper functions ──────────────────────────────────


def clean_path(value: str) -> str:
    return str(value or "").strip().strip('"').strip("'")


def ask_non_empty(prompt: str) -> str:
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print("❌ مقدار نمی‌تواند خالی باشد.")


def ask_yes_no(prompt: str, default: bool = False) -> bool:
    suffix = "Y/n" if default else "y/N"
    value = input(f"{prompt} ({suffix}): ").strip().lower()
    if not value:
        return default
    return value in {"y", "yes", "بله", "آره", "اره"}


def ask_float(prompt: str, default: float) -> float:
    value = input(f"{prompt} [{default}]: ").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        print("❌ عدد نامعتبر بود؛ مقدار پیش‌فرض استفاده شد.")
        return default


def parse_indices(raw: str, max_index: int) -> List[int]:
    """پars کردن شماره‌ها: 1,2,3 یا 1-5 یا all"""
    raw = str(raw or "").strip().lower()
    if raw in {"all", "همه"}:
        return list(range(1, max_index + 1))

    result: set[int] = set()
    parts = raw.replace("،", ",").replace(" ", ",").split(",")

    for part in parts:
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            try:
                start_text, end_text = part.split("-", 1)
                start = int(start_text)
                end = int(end_text)
            except ValueError:
                print(f"⚠️ بازه نامعتبر نادیده گرفته شد: {part}")
                continue
            if start > end:
                start, end = end, start
            for number in range(start, end + 1):
                if 1 <= number <= max_index:
                    result.add(number)
            continue

        try:
            number = int(part)
        except ValueError:
            print(f"⚠️ شماره نامعتبر نادیده گرفته شد: {part}")
            continue
        if 1 <= number <= max_index:
            result.add(number)
        else:
            print(f"⚠️ شماره خارج از محدوده نادیده گرفته شد: {number}")

    return sorted(result)


def get_username_from_entity(entity: Any) -> str:
    if entity is None:
        return ""
    username = getattr(entity, "username", "") or ""
    return str(username).strip()


# ── chat list builders ───────────────────────────────


def build_chat_items_from_dialogs(client: SoroushClient) -> List[ChatItem]:
    """روش بهتر برای WebSocket: از engine.get_dialogs استفاده می‌کنیم
    تا id و username هم داشته باشیم."""
    backend = client.backend
    engine = getattr(backend, "_engine", None)
    if engine is None or not hasattr(engine, "get_dialogs"):
        return []

    try:
        dialogs = engine.get_dialogs(limit=300)
    except Exception as exc:
        print("⚠️ گرفتن dialogs با id ناموفق بود:", repr(exc))
        return []

    items: List[ChatItem] = []
    seen: set[str] = set()

    for dialog in dialogs:
        name = str(dialog.get("name") or "").strip()
        chat_id = str(dialog.get("id") or "").strip()
        kind = str(dialog.get("type") or "chat").upper()
        entity = dialog.get("entity")
        username = get_username_from_entity(entity)

        key = chat_id or username or name
        if not key or key in seen:
            continue
        seen.add(key)

        if kind == "PERSONAL":
            kind_label = "PV"
        elif kind == "GROUP":
            kind_label = "GROUP"
        elif kind == "CHANNEL":
            kind_label = "CHANNEL"
        else:
            kind_label = kind

        items.append(
            ChatItem(
                index=len(items) + 1,
                name=name or chat_id or username,
                kind=kind_label,
                chat_id=chat_id,
                username=username,
            )
        )

    return items


def build_chat_items_fallback(client: SoroushClient) -> List[ChatItem]:
    """fallback قدیمی، اگر dialogs با id در دسترس نبود."""
    chats = client.get_chats()
    items: List[ChatItem] = []
    seen: set[str] = set()

    def add_many(names: List[str], kind: str) -> None:
        for name in names:
            if not name or name in seen:
                continue
            seen.add(name)
            items.append(ChatItem(index=len(items) + 1, name=name, kind=kind))

    add_many(chats.personal, "PV")
    add_many(chats.groups, "GROUP")
    add_many(chats.channels, "CHANNEL")

    if not items and chats.all:
        add_many(chats.all, "CHAT")

    return items


def build_chat_items(client: SoroushClient) -> List[ChatItem]:
    items = build_chat_items_from_dialogs(client)
    if items:
        return items
    return build_chat_items_fallback(client)


# ── display and selection ─────────────────────────────


def print_chats(items: List[ChatItem]) -> None:
    print("\n" + "=" * 100)
    print("📋 لیست چت‌ها")
    print("=" * 100)
    for item in items:
        target = item.primary_target
        print(
            f"{item.index:>4}. "
            f"[{item.kind:<7}] "
            f"{item.name} "
            f"| target={target}"
        )
    print("=" * 100)
    print("مثال انتخاب:")
    print("  1,2,3")
    print("  1-5")
    print("  all")
    print("=" * 100)


def choose_targets(items: List[ChatItem]) -> List[ChatItem]:
    while True:
        raw = ask_non_empty("\nشماره چت‌ها را وارد کن: ")
        indices = parse_indices(raw, max_index=len(items))
        if not indices:
            print("❌ هیچ شماره معتبری انتخاب نشد.")
            continue

        selected = [items[i - 1] for i in indices]

        print("\n✅ چت‌های انتخاب‌شده:")
        for item in selected:
            print(
                f"  {item.index}. [{item.kind}] "
                f"{item.name} | target={item.primary_target}"
            )

        if ask_yes_no("تأیید انتخاب؟", default=True):
            return selected


# ── file path input ───────────────────────────────────


def ask_file_path() -> str:
    while True:
        raw = ask_non_empty("\nمسیر فایل/عکس را وارد کن: ")
        path = clean_path(raw)
        file_path = Path(path)
        if not file_path.exists():
            print("❌ فایل پیدا نشد:", file_path)
            continue
        if not file_path.is_file():
            print("❌ مسیر واردشده فایل نیست:", file_path)
            continue
        return str(file_path)


# ── send logic ────────────────────────────────────────


def send_file_with_fallback(
    client: SoroushClient,
    target: ChatItem,
    file_path: str,
    caption: str,
    force_document: bool,
) -> Any:
    """اول با @username یا chat_id ارسال می‌کند.
    اگر fail شد، target بعدی را امتحان می‌کند."""
    last_result = None
    last_error: str | None = None

    for send_target in target.fallback_targets:
        print(f"  تلاش با target: {send_target}")
        try:
            result = client.send_file(
                send_target,
                file_path,
                caption=caption,
                force_document=force_document,
            )
            last_result = result
            if getattr(result, "success", False):
                return result

            last_error = getattr(result, "error", "") or str(result)
            print("  ناموفق:", last_error)

            # اگر خطای Entity بود، target بعدی را امتحان کن
            if "Entity not found" in last_error:
                continue

            # خطای upload دیگر با عوض کردن target حل نمی‌شود
            return result

        except Exception as exc:
            last_error = str(exc)
            print("  خطا:", repr(exc))
            if "Entity not found" in last_error:
                continue
            raise

    if last_result is not None:
        return last_result
    raise RuntimeError(last_error or "ارسال ناموفق بود.")


def send_file_to_targets(
    client: SoroushClient,
    targets: List[ChatItem],
    file_path: str,
    caption: str = "",
    delay: float = DEFAULT_DELAY,
    force_document: bool = False,
) -> None:
    print("\n" + "=" * 70)
    print("🚀 شروع ارسال")
    print("=" * 70)

    success_count = 0
    failed_count = 0

    for i, target in enumerate(targets, start=1):
        print(
            f"\n[{i}/{len(targets)}] ارسال به "
            f"[{target.kind}] {target.name}"
        )
        print("target اصلی:", target.primary_target)

        try:
            result = send_file_with_fallback(
                client=client,
                target=target,
                file_path=file_path,
                caption=caption,
                force_document=force_document,
            )
            print("نتیجه:", result)
            if getattr(result, "success", False):
                success_count += 1
            else:
                failed_count += 1
        except Exception as exc:
            failed_count += 1
            print("❌ خطا در ارسال:", repr(exc))

        if i < len(targets) and delay > 0:
            print(f"⏳ انتظار {delay} ثانیه...")
            time.sleep(delay)

    print("\n" + "=" * 70)
    print("📊 گزارش نهایی")
    print("=" * 70)
    print("موفق:", success_count)
    print("ناموفق:", failed_count)
    print("=" * 70)


# ── main ──────────────────────────────────────────────


def main() -> None:
    print("=" * 70)
    print("📤 ارسال تعاملی فایل/عکس با SoroPy WebSocket")
    print("=" * 70)

    phone = input(f"شماره تلفن [{PHONE}]: ").strip() or PHONE

    client = SoroushClient(
        phone,
        backend="websocket",
        session_dir=SESSION_DIR,
        auto_reply_private_only=True,
    )

    try:
        print("\n🔐 در حال ورود...")
        client.login(code_callback=lambda: input("کد پیامک‌شده: ").strip())
        print("✅ ورود موفق")

        # ── دریافت چت‌ها ──
        print("\n📥 در حال دریافت چت‌ها با id/username...")
        items = build_chat_items(client)

        if not items:
            print("❌ هیچ چتی پیدا نشد.")
            return

        print_chats(items)

        # ── انتخاب مقاصد ──
        targets = choose_targets(items)

        # ── اطلاعات فایل ──
        file_path = ask_file_path()
        caption = input("\nکپشن فایل، اگر نمی‌خواهی خالی بگذار: ").strip()
        force_document = ask_yes_no(
            "فایل حتماً به صورت document ارسال شود؟",
            default=False,
        )
        delay = ask_float(
            "فاصله بین ارسال‌ها به ثانیه",
            default=DEFAULT_DELAY,
        )

        # ── تأیید نهایی ──
        print("\n" + "=" * 70)
        print("خلاصه ارسال")
        print("=" * 70)
        print("فایل:", file_path)
        print("کپشن:", caption or "-")
        print("تعداد مقصد:", len(targets))
        print("فاصله:", delay)
        print("ارسال document:", force_document)
        print("=" * 70)
        print("\nمقصدها:")
        for item in targets:
            print(f"- {item.name} => {item.primary_target}")

        if not ask_yes_no("ارسال شروع شود؟", default=False):
            print("لغو شد.")
            return

        # ── ارسال ──
        send_file_to_targets(
            client=client,
            targets=targets,
            file_path=file_path,
            caption=caption,
            delay=delay,
            force_document=force_document,
        )

    finally:
        print("\nدر حال بستن اتصال...")
        client.close()
        print("تمام شد.")


if __name__ == "__main__":
    main()
