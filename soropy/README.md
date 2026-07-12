# SoroPy 🚀

**کتابخانه حرفه‌ای پایتون برای سروش پلاس** — v**1.3.0**

[![PyPI](https://img.shields.io/pypi/v/soropy)](https://pypi.org/project/soropy/)
[![License](https://img.shields.io/pypi/l/soropy)](https://opensource.org/licenses/MIT)

---

## امکانات

| قابلیت | Selenium | WebSocket |
|--------|:--------:|:---------:|
| لاگین + سشن | ✅ | ✅ |
| ارسال پیام / گروه / کانال | ✅ | ✅ |
| `on("new_message")` | ❌ | ✅ |
| auto-reply **فقط PV** | poll | push + poll |
| `send_file` / دانلود مدیا | ❌ | ✅ |
| حذف / ادیت / پین | محدود | ✅ |
| kick / ban / promote | ❌ | ✅ |
| block / report | ❌ | ✅ |
| بدون Chrome | ❌ | ✅ |

---

## نصب

```bash
pip install soropy
pip install "soropy[ws]"   # splusthon + aiohttp + pyaes + rsa
```

از GitHub (بدون `/tree/`):

```bash
pip install "soropy[ws] @ git+https://github.com/Alirezahjf/soropy.git@arena/019f5686-soropy#subdirectory=soropy"
```

---

## شروع سریع

### Selenium

```python
from soropy import SoroushClient

with SoroushClient("09123456789", headless=True) as client:
    client.login()
    client.send_message("علی", "سلام!")
```

### WebSocket realtime

```python
from soropy import SoroushClient

client = SoroushClient("09123456789", backend="websocket")
client.on("new_message", lambda e: print(e.data))
client.login()
client.add_reply_rule("سلام", "علیک سلام 👋")
client.set_default_reply("دریافت شد ✅")   # نه «جواب N»
client.set_private_only(True)              # پیش‌فرض
client.start_monitor(interval=120)         # safety-net؛ فقط PV
```

### فایل / مودریشن

```python
client.send_file("علی", "a.jpg", caption="عکس")
client.reply("علی", 123, "پاسخ")
client.send_to_group("گروه", "سلام")
client.send_to_channel("@ch", "پست")
client.kick("گروه", "user")
client.ban("گروه", "user")
client.promote("گروه", "user", delete_messages=True)
client.block_user("spam")
client.report("spam", reason="spam")
```

### Multi-account

```python
from soropy import MultiAccountManager

with MultiAccountManager(backend="websocket") as mgr:
    mgr.add_account("0912...")
    mgr.login_all()
    mgr.start_all_monitors(interval=120)
```

---

## منوی تعاملی

از ریشهٔ ریپو:

```bash
python interactive_manager.py
```

تنظیمات در `manager_config.json` ذخیره می‌شود (شماره، backend، قوانین، Listener/Monitor).

---

## سشن و رویداد

- Selenium: `soropy_sessions/`
- WebSocket: `soropy_ws_sessions/*.session` (SQLite)
- رویدادها: `new_message`, `connected`, `auth_success`, `error`, …

Payload `new_message`:  
`message_id, chat_id, chat_name, text, sender_id, sender_name, is_outgoing, is_private, is_group, is_channel, timestamp, reply_to_id`

---

## عیب‌یابی

| مشکل | کار |
|------|-----|
| شماره `0912xxxxxxx` | فقط رقم واقعی؛ validate قبل از login |
| سیل `CHAT_ADMIN_REQUIRED` | auto-reply فقط PV؛ monitor را خاموش/کند کنید |
| WebSocket قطع هنگام reply | 1.3.0 از `create_task` استفاده می‌کند |
| Unclosed aiohttp | `client.close()` |
| splusthon | `pip install soropy[ws]` |

---

## معماری

```
SoroushClient
└── BaseBackend
    ├── SeleniumBackend
    └── WebSocketBackend → MtprotoEngine (SPlusthon) + LoopRunner + EventBus
```

## لایسنس

- هسته: **MIT**
- `soropy[ws]` / SPlusthon: **GPL-3.0** (اختیاری)

مستندات کامل‌تر در README ریشهٔ ریپو و `docs/WEBSOCKET_ARCHITECTURE.md`.
