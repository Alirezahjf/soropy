"""
Headless (no visible window) operation.
"""

from soropy import SoroushClient

# The browser runs invisibly
client = SoroushClient(
    phone="09123456789",
    headless=True,
    session_dir="headless_sessions",
)

try:
    # If session exists, no code needed
    if client.has_session:
        print("Session found – auto-login")
        status = client.login()
    else:
        # First time: need code
        def get_code():
            return input("Enter SMS code: ")
        status = client.login(code_callback=get_code)

    print(f"Status: {status}")

    # Do work...
    chats = client.get_chats()
    print(f"Chats: {chats.total_count}")

    # Single auto-reply pass
    results = client.check_and_reply()
    total_ok = sum(
        1 for sends in results.values()
        for s in sends if s.success
    )
    print(f"Replied to {total_ok} messages")

finally:
    client.close()