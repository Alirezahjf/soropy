"""Cookbook کامل قابلیت‌های WebSocket در SoroPy 1.3.4.

قبل از اجرای هر تابع، نام چت‌ها، @usernameها و IDهای نمونه را تغییر دهید.
برای موجودیت‌های هم‌نام، استفاده از @username یا ID عددی امن‌تر از display name است.
main فقط login، get_me و get_chats را اجرا می‌کند؛ عملیات destructive خودکار نیستند.
"""

from __future__ import annotations

import os
import time
from typing import Any

from soropy import MultiAccountManager, SoroushClient

PHONE = os.getenv("SOROPY_PHONE", "09123456789")
CHAT = os.getenv("SOROPY_CHAT", "نام مخاطب")
GROUP = os.getenv("SOROPY_GROUP", "نام گروه")
CHANNEL = os.getenv("SOROPY_CHANNEL", "@channel")
USER = os.getenv("SOROPY_USER", "@username")
MESSAGE_ID = int(os.getenv("SOROPY_MESSAGE_ID", "1"))
FILE_PATH = os.getenv("SOROPY_FILE", "example.pdf")


def make_client() -> SoroushClient:
    return SoroushClient(PHONE, backend="websocket", auto_reply_private_only=True)


def lifecycle() -> None:
    client = make_client()
    try:
        client.login(code_callback=lambda: input("کد پیامک‌شده: ").strip())
        print(client.is_logged_in)
        print(client.get_me())
        print(client.has_session)
        # client.delete_session()  # فقط وقتی session خراب است.
    finally:
        client.close()


def events(client: SoroushClient) -> None:
    def handler(event: Any) -> None:
        print(event.name, event.data)

    for name in [
        "connected",
        "auth_success",
        "new_message",
        "message_sent",
        "chat_updated",
        "unread_changed",
        "error",
        "disconnected",
    ]:
        client.on(name, handler)
    client.off("new_message", handler)


def chat_and_message(client: SoroushClient) -> None:
    chats = client.get_chats()
    print(chats.total_count)
    client.get_chats(save_to="chats.json")
    client.send_message(CHAT, "سلام")
    client.reply(CHAT, MESSAGE_ID, "پاسخ")
    client.send_bulk_messages([CHAT], "پیام گروهی", delay=3)
    client.send_to_personal("سلام", max_count=3)
    client.send_to_group(GROUP, "سلام گروه")
    client.send_to_channel(CHANNEL, "پست کانال")


def media_tools(client: SoroushClient) -> None:
    client.send_file(CHAT, FILE_PATH, caption="فایل")
    client.download_media(CHAT, MESSAGE_ID, file_path="downloaded.bin")
    client.edit_message(CHAT, MESSAGE_ID, "متن ویرایش‌شده")
    client.delete_messages(CHAT, [MESSAGE_ID], revoke=True)
    client.pin_message(CHAT, MESSAGE_ID, notify=False)
    client.unpin_message(CHAT, MESSAGE_ID)
    client.unpin_message(CHAT)  # unpin all


def contacts_and_user(client: SoroushClient) -> None:
    print(client.get_contacts())
    print(client.search_contacts("علی"))
    client.add_contact("09123456789", "علی", "احمدی")
    client.block_user(USER)
    client.unblock_user(USER)
    client.report(USER, reason="spam", message="مزاحمت")


def moderation(client: SoroushClient) -> None:
    print(client.get_participants(GROUP, limit=50))
    print(client.get_permissions(GROUP, USER))
    client.set_permissions(GROUP, USER, send_messages=False)
    client.promote(GROUP, USER, title="مدیر", delete_messages=True)
    client.kick(GROUP, USER)
    client.ban(GROUP, USER)
    client.unban(GROUP, USER)


def auto_reply(client: SoroushClient) -> None:
    client.add_reply_rule("سلام", "علیک سلام")
    client.remove_reply_rule("سلام")
    client.set_default_reply("پیامت دریافت شد.")
    client.load_reply_rules({"قیمت": "با پشتیبانی تماس بگیرید."})
    client.set_auto_reply_enabled(True)
    client.set_private_only(True)
    client.check_and_reply()
    thread = client.start_monitor(interval=120, blocking=False)
    time.sleep(1)
    client.stop_monitor()
    if thread:
        thread.join(timeout=2)


def multi_account() -> None:
    with MultiAccountManager(backend="websocket") as manager:
        manager.add_account(PHONE)
        manager.login_all(parallel=False)
        manager.start_all_monitors(interval=120)
        client = manager.get_client(PHONE)
        print(client.get_me() if client else None)
        manager.stop_all_monitors()
        manager.close_all()


def main() -> None:
    client = make_client()
    try:
        client.login(code_callback=lambda: input("کد پیامک‌شده: ").strip())
        print("Logged in:", client.is_logged_in)
        print("Me:", client.get_me())
        print("Chats:", client.get_chats().total_count)
    finally:
        client.close()


if __name__ == "__main__":
    main()
