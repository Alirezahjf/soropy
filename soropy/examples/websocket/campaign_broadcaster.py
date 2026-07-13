"""کمپین پیام‌رسانی امن برای SoroPy WebSocket.

پیش‌فرض dry-run است و هیچ پیامی ارسال نمی‌شود مگر اینکه
SOROPY_CAMPAIGN_CONFIRM=YES تنظیم شده باشد.

envها:
  SOROPY_PHONE
  SOROPY_SESSION_DIR
  SOROPY_CAMPAIGN_TARGETS
  SOROPY_CAMPAIGN_TEXT
  SOROPY_CAMPAIGN_FILE
  SOROPY_CAMPAIGN_DELAY
  SOROPY_CAMPAIGN_MAX
  SOROPY_CAMPAIGN_CONFIRM
"""

from __future__ import annotations

import csv
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

PHONE = os.getenv("SOROPY_PHONE", "09123456789")
SESSION_DIR = os.getenv("SOROPY_SESSION_DIR", "soropy_ws_sessions")
TARGETS_CSV = os.getenv("SOROPY_CAMPAIGN_TARGETS", "")
CAMPAIGN_TEXT = os.getenv(
    "SOROPY_CAMPAIGN_TEXT",
    "سلام {name}! این یک پیام کمپین است. ({kind}) {note}",
)
CAMPAIGN_FILE = os.getenv("SOROPY_CAMPAIGN_FILE", "")
CAMPAIGN_DELAY = float(os.getenv("SOROPY_CAMPAIGN_DELAY", "2.0"))
CAMPAIGN_MAX = int(os.getenv("SOROPY_CAMPAIGN_MAX", "0"))
CAMPAIGN_CONFIRM = os.getenv("SOROPY_CAMPAIGN_CONFIRM", "").strip()


@dataclass(frozen=True)
class CampaignTarget:
    name: str
    kind: str = "personal"
    note: str = ""

    def as_dict(self) -> Dict[str, str]:
        return {"name": self.name, "kind": self.kind, "note": self.note}


def load_targets(path: str | os.PathLike[str] | None = None) -> List[CampaignTarget]:
    """Load campaign targets from a CSV with columns name, kind, note."""
    csv_path = Path(path or TARGETS_CSV) if (path or TARGETS_CSV) else None
    if csv_path is None or not csv_path.exists():
        return []
    targets: List[CampaignTarget] = []
    with csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            targets.append(
                CampaignTarget(
                    name=name,
                    kind=str(row.get("kind") or "personal").strip() or "personal",
                    note=str(row.get("note") or "").strip(),
                )
            )
    return targets


def targets_from_chats(chats: Any) -> List[CampaignTarget]:
    """Build targets from get_chats().personal when CSV is missing."""
    personal = getattr(chats, "personal", None) or []
    targets: List[CampaignTarget] = []
    for item in personal:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("chat_name") or item.get("id") or "")
            kind = str(item.get("kind") or "personal")
            note = str(item.get("note") or "")
        else:
            name = str(
                getattr(item, "name", None)
                or getattr(item, "chat_name", None)
                or getattr(item, "id", None)
                or item
            )
            kind = str(getattr(item, "kind", None) or "personal")
            note = str(getattr(item, "note", None) or "")
        if name:
            targets.append(CampaignTarget(name=name, kind=kind, note=note))
    return targets


def render_message(
    template: str,
    target: CampaignTarget | Dict[str, str],
) -> str:
    """Render campaign template with {name}, {kind}, {note}."""
    if isinstance(target, CampaignTarget):
        data = target.as_dict()
    else:
        data = {
            "name": str(target.get("name") or ""),
            "kind": str(target.get("kind") or "personal"),
            "note": str(target.get("note") or ""),
        }
    try:
        return template.format(**data)
    except (KeyError, ValueError, IndexError):
        return (
            template.replace("{name}", data["name"])
            .replace("{kind}", data["kind"])
            .replace("{note}", data["note"])
        )


def chunked(items: Sequence[Any], size: int) -> List[List[Any]]:
    """Split a sequence into fixed-size chunks (size<=0 returns one chunk)."""
    if size <= 0:
        return [list(items)]
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


def is_confirmed(value: Optional[str] = None) -> bool:
    return (value if value is not None else CAMPAIGN_CONFIRM).strip() == "YES"


def run_campaign(
    client: Any,
    targets: Iterable[CampaignTarget],
    text_template: str = CAMPAIGN_TEXT,
    file_path: str = CAMPAIGN_FILE,
    delay: float = CAMPAIGN_DELAY,
    max_count: int = CAMPAIGN_MAX,
    confirm: Optional[str] = None,
) -> Dict[str, Any]:
    """Send campaign messages. Dry-run unless confirm is exactly YES."""
    target_list = list(targets)
    if max_count > 0:
        target_list = target_list[:max_count]

    confirmed = is_confirmed(confirm)
    results: List[Dict[str, Any]] = []
    sent = 0
    skipped = 0

    print(
        f"کمپین: {len(target_list)} هدف | "
        f"حالت: {'ارسال واقعی' if confirmed else 'dry-run'} | "
        f"delay={delay}s"
    )

    for index, target in enumerate(target_list):
        message = render_message(text_template, target)
        entry: Dict[str, Any] = {
            "name": target.name,
            "kind": target.kind,
            "note": target.note,
            "message": message,
            "status": "dry-run",
        }
        if not confirmed:
            print(f"[dry-run] {index + 1}/{len(target_list)} → {target.name}: {message[:80]}")
            skipped += 1
            results.append(entry)
            continue

        try:
            if file_path and Path(file_path).is_file():
                client.send_file(target.name, file_path, caption=message)
            else:
                client.send_message(target.name, message)
            entry["status"] = "sent"
            sent += 1
            print(f"[sent] {index + 1}/{len(target_list)} → {target.name}")
        except Exception as exc:
            entry["status"] = "failed"
            entry["error"] = str(exc)
            print(f"[failed] {target.name}: {exc}")
        results.append(entry)
        if delay > 0 and index + 1 < len(target_list):
            time.sleep(delay)

    summary = {
        "total": len(target_list),
        "sent": sent,
        "skipped": skipped,
        "failed": sum(1 for item in results if item.get("status") == "failed"),
        "confirmed": confirmed,
        "results": results,
    }
    print(
        f"پایان کمپین: total={summary['total']} sent={summary['sent']} "
        f"skipped={summary['skipped']} failed={summary['failed']}"
    )
    return summary


def main() -> None:
    from soropy import SoroushClient

    client = SoroushClient(
        PHONE,
        backend="websocket",
        session_dir=SESSION_DIR,
        auto_reply_private_only=True,
    )
    try:
        client.login(code_callback=lambda: input("کد پیامک‌شده: ").strip())
        targets = load_targets()
        if not targets:
            print("CSV هدف یافت نشد؛ از get_chats().personal استفاده می‌شود.")
            targets = targets_from_chats(client.get_chats())
        if not targets:
            print("هیچ هدفی برای کمپین یافت نشد.")
            return
        if not is_confirmed():
            print(
                "حالت dry-run فعال است. برای ارسال واقعی "
                "SOROPY_CAMPAIGN_CONFIRM=YES را تنظیم کنید."
            )
        run_campaign(client, targets)
    finally:
        client.close()


if __name__ == "__main__":
    main()
