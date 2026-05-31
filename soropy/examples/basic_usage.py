"""
Basic SoroPy usage example.
"""

from soropy import SoroushClient

# ── Single account ────────────────────────────────────

client = SoroushClient(
    phone="09123456789",
    headless=False,       # Set True for invisible browser
    session_dir="my_sessions",
)

try:
    # Login (will prompt for SMS code if needed)
    status = client.login()
    print(f"Login status: {status}")

    # Extract chat list
    chats = client.get_chats(save_to="chats.json")
    print(f"Total chats: {chats.total_count}")
    print(f"Personal: {len(chats.personal)}")
    print(f"Groups: {len(chats.groups)}")
    print(f"Channels: {len(chats.channels)}")

    # Send a message to a specific chat
    result = client.send_message("علی", "سلام! حالت خوبه؟")
    print(result)

    # Send bulk messages to first 5 personal chats
    results = client.send_to_personal(message="سلام!", max_count=5)
    for r in results:
        print(r)

    # Get contacts
    contacts = client.get_contacts()
    print(f"Contacts: {len(contacts)}")

    # Add a contact
    client.add_contact("09187654321", "محمد", "احمدی")

    # Search contacts
    found = client.search_contacts("محمد")
    print(f"Found: {found}")

    # Send to channel (admin required)
    client.send_to_channel("@my_channel", "سلام از SoroPy!")

finally:
    client.close()