# SoroPy 🚀

**حرفه‌ای‌ترین کتابخانه پایتون برای سروش پلاس** — نسخه **1.3.0**

[![PyPI](https://img.shields.io/pypi/v/soropy)](https://pypi.org/project/soropy/)
[![Python](https://img.shields.io/pypi/pyversions/soropy)](https://pypi.org/project/soropy/)
[![License](https://img.shields.io/pypi/l/soropy)](https://opensource.org/licenses/MIT)

---

## ✨ امکانات

| قابلیت | توضیح |
|--------|-------|
| 🔐 **لاگین خودکار** | ورود با شماره + کد تأیید، ذخیره سشن |
| 💬 **استخراج چت‌ها** | لیست همه / شخصی / گروه / کانال |
| 📨 **ارسال پیام** | تکی، ریپلای، دسته‌ای، گروه، کانال |
| 📎 **ارسال فایل / مدیا** | `send_file` / `download_media` (WS) |
| 🛠️ **ابزار پیام** | حذف، ادیت، پین / آن‌پین (WS) |
| 📇 **مخاطبین** | مشاهده، اضافه، جستجو، بلاک / آن‌بلاک |
| 🛡️ **مودریشن** | kick / ban / unban / promote / permissions (WS) |
| 🤖 **پاسخ خودکار** | قوانین + default_reply + ضدتکرار — **فقط PV** |
| 👁️ **مانیتور** | poll ایمنی + push لحظه‌ای روی WS |
| 👥 **چند اکانت** | `MultiAccountManager` |
| 🔌 **دو Backend** | Selenium (UI) و WebSocket/MTProto |
| 🖥️ **منوی تعاملی** | `python interactive_manager.py` |

### جدول مقایسه Backend

| قابلیت | Selenium | WebSocket / MTProto |
|--------|:--------:|:-------------------:|
| `login` + سشن | ✅ Chrome profile | ✅ SQLite session |
| `send_message` / bulk | ✅ | ✅ |
| `get_chats` (personal/group/channel) | ✅ | ✅ |
| `on("new_message")` realtime | ❌ | ✅ |
| auto-reply فقط PV | ✅ poll | ✅ push + poll |
| `send_file` / `download_media` | ❌ | ✅ |
| `reply` / `edit` / `delete` / `pin` | محدود UI | ✅ |
| `kick` / `ban` / `promote` / … | ❌ | ✅ |
| `block_user` / `report` | ❌ | ✅ |
| بدون Chrome | ❌ | ✅ |
| headless | ✅ | ✅ (همیشه) |

---

## 📦 نصب

### از PyPI

```bash
pip install soropy
pip install "soropy[ws]"   # برای backend وب‌سوکت (SPlusthon)
```

### از GitHub (برنچ توسعه)

> ⚠️ آدرس باید **بدون** `/tree/` باشد. از `#subdirectory=soropy` استفاده کنید.

```bash
pip uninstall soropy -y

# آخرین برنچ این سشن Arena:
pip install "soropy[ws] @ git+https://github.com/Alirezahjf/soropy.git@arena/019f5686-soropy#subdirectory=soropy"

# یا برنچ قبلی:
# pip install "soropy[ws] @ git+https://github.com/Alirezahjf/soropy.git@arena/019f5612-soropy#subdirectory=soropy"
```

### پیش‌نیازها

- Python 3.8+
- **Selenium:** Google Chrome / Chromium + ChromeDriver
- **WebSocket:** فقط `pip install soropy[ws]` (بدون Chrome)

### extras `ws`

```
splusthon>=1.1.0
aiohttp>=3.8.0
pyaes>=1.6.1
rsa>=4.0
```

---

## 🚀 شروع سریع

### Selenium (پیش‌فرض)

```python
from soropy import SoroushClient

client = SoroushClient("09123456789")   # backend="selenium"
client.login()
client.send_message("علی", "سلام!")
chats = client.get_chats()
print(chats.total_count)
client.close()
```

### WebSocket / MTProto (realtime)

```python
from soropy import SoroushClient

client = SoroushClient("09123456789", backend="websocket")

def on_msg(event):
    d = event.data
    # message_id, chat_id, chat_name, text, sender_id, sender_name,
    # is_outgoing, is_private, is_group, is_channel, timestamp, reply_to_id
    print(d["chat_name"], d["text"], "PV" if d.get("is_private") else "other")

client.on("new_message", on_msg)
client.login()                       # SMS بار اول؛ بعد سشن SQLite
client.send_message("علی", "سلام از MTProto!")
client.close()
```

پروتکل واقعی: **MTProto** روی `wss://im-server.splus.ir:443/apiws`  
جزئیات: [`docs/WEBSOCKET_ARCHITECTURE.md`](docs/WEBSOCKET_ARCHITECTURE.md)

---

## 📎 فایل، گروه، کانال، ریپلای

```python
client = SoroushClient("09123456789", backend="websocket")
client.login()

client.send_message("علی", "سلام")
client.reply("علی", message_id=12345, text="در پاسخ...")
client.send_to_group("گروه خانواده", "سلام گروه")
client.send_to_channel("@my_channel", "پست کانال")  # نیاز ادمین

client.send_file("علی", "photo.jpg", caption="عکس", force_document=False)
path = client.download_media("علی", message_id=12345, file_path="out.bin")

client.edit_message("علی", 12345, "متن ویرایش‌شده")
client.delete_messages("علی", [12345, 12346], revoke=True)
client.pin_message("علی", 12345, notify=False)
client.unpin_message("علی")  # همه
```

---

## 🛡️ مودریشن / بلاک / ریپورت

```python
client.kick("گروه من", "user_or_id")
client.ban("گروه من", "user_or_id")
client.unban("گروه من", "user_or_id")
client.promote("گروه من", "user_or_id", delete_messages=True, ban_users=True)
client.set_permissions("گروه من", "user_or_id", send_messages=False)
client.get_participants("گروه من", limit=100)
client.get_permissions("گروه من")

client.block_user("اسپمر")
client.unblock_user("اسپمر")
client.report("اسپمر", reason="spam", message="")  # spam|violence|porn|copyright|other
```

> همهٔ این متدها روی `backend="websocket"` پیاده شده‌اند. روی Selenium خطای واضح می‌گیرید.

---

## 🤖 پاسخ خودکار — فقط PV

از نسخه **1.3.0** auto-reply (realtime و poll) **فقط چت شخصی** را هدف می‌گیرد  
تا سیل خطای `CHAT_ADMIN_REQUIRED` روی کانال/گروه رخ ندهد.

```python
client = SoroushClient("09123456789", backend="websocket")
client.login()

client.add_reply_rule("سلام", "علیک سلام! 👋")
client.set_default_reply("پیامت دریافت شد ✅")  # همان متن کاربر؛ نه «جواب N»
# client.set_default_reply(None)  # خاموش کردن default

client.set_auto_reply_enabled(True)
client.set_private_only(True)   # پیش‌فرض True

# realtime push جواب می‌دهد؛ monitor فقط safety-net (حداقل ~120s روی WS)
client.start_monitor(interval=120)  # فقط PV، حداکثر ~۵ چت در هر cycle
```

- پیام‌های تکراری با `MessageTracker` ذخیره می‌شوند.
- خطای admin به‌صورت soft-skip (لاگ debug) رد می‌شود، نه flood.
- ارسال realtime **async** است تا WebSocket قطع نشود.

---

## 👥 چند اکانت

```python
from soropy import MultiAccountManager

with MultiAccountManager(backend="websocket") as mgr:
    mgr.add_account("09123456789")
    mgr.add_account("09187654321")
    mgr.login_all()
    mgr.get_client("09123456789").send_message("علی", "سلام از اکانت ۱")
    mgr.start_all_monitors(interval=120)
```

---

## ⚡ رویدادها

| Event | توضیح |
|-------|--------|
| `connecting` / `connected` / `disconnected` | چرخه اتصال |
| `auth_success` / `auth_failed` | لاگین |
| `new_message` | پیام ورودی (با فلگ‌های is_private/group/channel) |
| `message_sent` | تأیید ارسال |
| `chat_updated` / `unread_changed` | لیست و badge |
| `error` | خطاهای transport |

### سشن‌ها

| Backend | مسیر | فرمت |
|---------|------|------|
| Selenium | `soropy_sessions/plus_98…/` | Chrome profile |
| WebSocket | `soropy_ws_sessions/plus_98….session` | SQLite (auth key + DC) |

حذف: `client.delete_session()`

---

## 🖥️ منوی تعاملی

```bash
git clone -b arena/019f5686-soropy https://github.com/Alirezahjf/soropy.git
cd soropy
pip install -e "./soropy[ws]"
python interactive_manager.py
```

منوی فارسی با ذخیره تنظیمات در `manager_config.json`:

1. لاگین / اتصال (websocket پیش‌فرض)
2. وضعیت + لیست قابلیت‌ها
3. لیست چت‌ها (+ JSON)
4. ارسال: متن / ریپلای / چندتایی / فایل
5. قوانین auto-reply + toggleها
6. سرویس‌ها: Listener / Monitor جدا
7. حالت زنده (Live feed)
8. مخاطبین
9. مودریشن
10. ابزار پیام
11. تست سریع
12. حذف سشن
13. خروج از اکانت  
0. خروج

پیشنهاد تست واقعی: لاگین → قانون «سلام» → Listener روشن → Monitor خاموش → Live → جواب فقط PV بدون سیل `CHAT_ADMIN`.

---

## 🏗️ معماری

```
SoroushClient (client.py)          ← API عمومی ثابت
└── BaseBackend
    ├── SeleniumBackend            ← پیش‌فرض (Chrome + DOM)
    └── WebSocketBackend           ← MTProto روی WSS
        ├── MtprotoEngine (SPlusthon)
        ├── LoopRunner (create_task / بدون deadlock)
        └── EventBus (new_message, …)

AutoReplyEngine + MessageTracker   ← مشترک، فقط PV
MultiAccountManager(backend=...)
interactive_manager.py             ← CLI فارسی
```

---

## 🔧 عیب‌یابی

| علامت | راه‌حل |
|--------|--------|
| `شماره نامعتبر` / `bytes or str expected, not NoneType` | شماره **واقعی** ۱۱ رقمی بدهید (`09123456789`). placeholder مثل `0912xxxxxxx` رد می‌شود. |
| `CHAT_ADMIN_REQUIRED` سیل | auto-reply فقط PV است؛ Monitor را خاموش کنید یا interval را بالا ببرید. قوانین را روی کانال نزنید. |
| `WebSocket closed` + Ping pending | نسخه 1.3.0 ارسال auto-reply را async کرده؛ `pip install` دوباره از برنچ. |
| `Unclosed client session` | `client.close()` را صدا بزنید؛ disconnect تمیز aiohttp را می‌بندد. |
| `requires 'splusthon'` | `pip install "soropy[ws]"` |
| `MTProto connect failed` | دسترسی به `im-server.splus.ir:443` (DNS/VPN/فایروال) |
| سشن خراب | `client.delete_session()` سپس لاگین مجدد |

---

## 📄 لایسنس

- **هسته SoroPy (Selenium و API عمومی):** [MIT](soropy/LICENSE)
- **اختیاری `soropy[ws]` + SPlusthon:** SPlusthon تحت **GPL-3.0** است؛ توزیع باینری ترکیبی مشمول تعهدات GPL می‌شود.  
  اگر فقط Selenium می‌خواهید: `pip install soropy` بدون extra.

---

## 📬 ارتباط

[Telegram @mr_hjf](https://t.me/mr_hjf) · [GitHub Issues](https://github.com/Alirezahjf/soropy/issues)

ساخته شده با ❤️ — نسخه 1.3.0
