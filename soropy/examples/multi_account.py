"""
Multi-account management example.
"""

from soropy import MultiAccountManager

manager = MultiAccountManager(
    headless=True,
    session_dir="multi_sessions",
)

try:
    # Register accounts
    c1 = manager.add_account("09123456789")
    c2 = manager.add_account("09187654321")

    # Configure rules per-account
    c1.add_reply_rule("سلام", "سلام از اکانت ۱")
    c2.add_reply_rule("سلام", "سلام از اکانت ۲")

    # Login all (sequential, will prompt for codes)
    statuses = manager.login_all()
    for phone, status in statuses.items():
        print(f"{phone}: {status.value}")

    # Extract chats for account 1
    chats = manager.get_client("09123456789").get_chats()
    print(f"Account 1 chats: {chats.total_count}")

    # Send message from account 2
    result = manager.get_client("09187654321").send_message("علی", "سلام!")
    print(result)

    # Start monitors for all accounts
    def on_any_reply(phone, chat, orig, reply):
        print(f"[{phone}] {chat} → {reply}")

    threads = manager.start_all_monitors(interval=30, on_reply=on_any_reply)
    print(f"Monitors running: {len(threads)}")

    # Keep running
    import time
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass

    manager.stop_all_monitors()

finally:
    manager.close_all()