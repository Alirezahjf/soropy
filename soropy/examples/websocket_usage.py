"""
WebSocket / MTProto backend – full example.

Requires::

    pip install soropy[ws]
    # or: pip install splusthon aiohttp pyaes rsa
"""

from soropy import SoroushClient


def main():
    client = SoroushClient(
        phone="09123456789",          # ← your number
        backend="websocket",
        # session_dir="my_ws_sessions",
    )

    def on_message(event):
        d = event.data
        print(f"← [{d.get('chat_name')}] {d.get('text')}")

    def on_status(event):
        print(f"🔌 {event.name}: {event.data}")

    client.on("new_message", on_message)
    client.on("connected", on_status)
    client.on("disconnected", on_status)
    client.on("auth_success", on_status)
    client.on("error", on_status)

    try:
        status = client.login()
        print(f"Login: {status}")

        me = client.backend.get_me() if hasattr(client.backend, "get_me") else None
        if me:
            print(f"Me: {me}")

        chats = client.get_chats()
        print(
            f"Chats — personal:{len(chats.personal)} "
            f"groups:{len(chats.groups)} channels:{len(chats.channels)}"
        )
        if chats.personal:
            print("  first personal:", chats.personal[:5])

        # Send a test message (uncomment & set a real name)
        # result = client.send_message("علی", "سلام از SoroPy MTProto!")
        # print(result)

        # Realtime auto-reply
        client.add_reply_rule("سلام", "علیک سلام 👋")
        client.add_reply_rule("قیمت", "لطفاً به پشتیبانی پیام بدید")
        client.set_default_reply("پیامت دریافت شد ✅")

        print("Listening for messages (Ctrl+C to stop)…")
        # Realtime handler already replies; monitor is a light safety net
        client.start_monitor(interval=120, blocking=True)

    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        client.close()


if __name__ == "__main__":
    main()
