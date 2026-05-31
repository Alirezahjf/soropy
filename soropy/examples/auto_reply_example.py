"""
Auto-reply with custom rules.
"""

from soropy import SoroushClient

client = SoroushClient("09123456789", headless=True)

try:
    client.login()

    # ── Configure rules ────────────────────────────────
    client.add_reply_rule("سلام", "علیک سلام! 👋")
    client.add_reply_rule("چطوری", "خوبم ممنون، تو چطوری؟")
    client.add_reply_rule("خوبی", "ممنون خوبم! 😊")
    client.add_reply_rule("خداحافظ", "بای بای! 🙏", priority=10)

    # Or bulk-load from dict:
    client.load_reply_rules({
        "قیمت": "لطفاً به سایت مراجعه کنید",
        "آدرس": "تهران، خیابان ولیعصر",
    })

    # Set the fallback reply
    client.set_default_reply("پیامت دریافت شد، به زودی پاسخ میدم ✅")

    # ── Single pass ────────────────────────────────────
    results = client.check_and_reply()
    for chat, sends in results.items():
        for s in sends:
            print(s)

    # ── Or continuous monitor ──────────────────────────
    def on_reply(chat_name, original, reply):
        print(f"📨 {chat_name}: replied '{reply}'")

    # Blocking (Ctrl+C to stop):
    client.start_monitor(interval=30, blocking=True, on_reply=on_reply)

finally:
    client.close()