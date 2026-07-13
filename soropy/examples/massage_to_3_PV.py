"""
نمونه کاربردی ساده - لاگین و ارسال به ۳ نفر
اجرا:
    pip install soropy
    python send_three.py
"""

from soropy import SoroushClient

# ─── مرحله ۱: شماره و لاگین ───────────────────────────
raw_phone = input("📱 phone number ( 09123456789): ").strip()

client = SoroushClient(phone=raw_phone, headless=True)

try:
    # لاگین - اگه اولین باره کد SMS میخواد
    status = client.login()
    print(f"✅ وضعیت: {status.value}")

    # ─── مرحله ۲: گرفتن نام ۳ نفر ─────────────────────
    targets = []
    for i in range(1, 4):
        name = input(f"👤 name personal {i}: ").strip()
        targets.append(name)

    # ─── مرحله ۳: ارسال پیام ──────────────────────────
    msg = "سلام خوبی؟ 😊"
    print(f"\n📨 ارسال: '{msg}' به {len(targets)} نفر\n")

    results = client.send_bulk_messages(
        chat_names=targets,
        message=msg,
        delay=3.0,
    )

    # ─── نتیجه ─────────────────────────────────────────
    ok = sum(1 for r in results if r.success)
    fail = len(results) - ok

    print("\n" + "=" * 40)
    print(f"📊 نتیجه: ✅ {ok} | ❌ {fail}")
    for r in results:
        print(f"   {r}")
    print("=" * 40)

finally:
    input("\n⏎ Enter بزن تا بسته بشه...")
    client.close()
