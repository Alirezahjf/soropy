<div align="center">

# SoroPy 1.3.4 🚀

**کتابخانهٔ حرفه‌ای Python برای سروش‌پلاس با دو backend مستقل: Selenium و WebSocket/MTProto**

[![PyPI](https://img.shields.io/pypi/v/soropy?style=for-the-badge)](https://pypi.org/project/soropy/)
[![Python](https://img.shields.io/pypi/pyversions/soropy?style=for-the-badge)](https://pypi.org/project/soropy/)
[![Backend](https://img.shields.io/badge/Selenium%20%7C%20WebSocket-ready-success?style=for-the-badge)](#جدول-مقایسه-selenium-و-websocket)
[![License](https://img.shields.io/badge/License-MIT-blue?style=for-the-badge)](soropy/LICENSE)

<a href="https://t.me/soropy"><img src="https://img.shields.io/badge/Telegram-soropy-229ED9?style=for-the-badge" /></a>
<a href="https://ble.ir/soropy"><img src="https://img.shields.io/badge/Bale-soropy-00A693?style=for-the-badge" /></a>
<a href="https://splus.ir/soropy"><img src="https://img.shields.io/badge/Soroush%20Plus-soropy-f97316?style=for-the-badge" /></a>
<a href="https://rubika.ir/soropy"><img src="https://img.shields.io/badge/Rubika-soropy-8b5cf6?style=for-the-badge" /></a>

</div>

> [!IMPORTANT]
> backend وب‌سوکت از API رسمی عمومی استفاده نمی‌کند؛ SPlusthon یک کلاینت شخص ثالث MTProto است. قوانین و محدودیت‌های سروش‌پلاس را رعایت کنید، روی حساب/گروه آزمایشی تست بگیرید و شماره، کد SMS، API key یا فایل session را منتشر نکنید.

## دسترسی سریع

- [چرا SoroPy؟](#چرا-soropy)
- [نصب](#نصب-pypi)
- [شروع سریع Selenium](#مثال-selenium)
- [شروع سریع WebSocket](#مثال-websocket-realtime)
- [پروژه‌های آماده WebSocket](#پروژههای-آماده-websocket)
- [فهرست کامل API](#فهرست-کامل-api)
- [Troubleshooting](#troubleshooting)
- [جامعه و سازنده](#جامعه-و-سازنده)

---

## چرا SoroPy؟

SoroPy یک API واحد و sync به شما می‌دهد تا بدون درگیر شدن با جزئیات Chrome، WebSocket، event loop و session، روی automation تمرکز کنید:

- Selenium برای کاربرانی که رفتار وب‌کلاینت را می‌خواهند.
- WebSocket / MTProto برای اجرای سبک، realtime، بدون Chrome و مناسب server.
- auto-reply امن با پیش‌فرض فقط PV.
- مدیریت چند اکانت، session پایدار، contact، media و moderation.
- مثال‌های آمادهٔ 1.3.4 برای مدیر گروه، AI و cookbook کامل.

## جدول مقایسه Selenium و WebSocket

| قابلیت | Selenium | WebSocket / MTProto |
|---|:---:|:---:|
| `login` با شماره و کد | ✅ رابط وب | ✅ SMS / session |
| ذخیرهٔ session | Chrome profile | SQLite auth key |
| ارسال پیام و bulk | ✅ | ✅ |
| reply با message ID | محدود | ✅ |
| realtime `new_message` | ❌ | ✅ |
| auto-reply | poll | push + poll ایمنی |
| فقط PV به‌صورت پیش‌فرض | ✅ | ✅ |
| ارسال/دانلود فایل | ❌ | ✅ |
| حذف، ویرایش، pin و unpin | ❌ | ✅ |
| مخاطبین | ✅ | ✅ |
| block / unblock / report | ❌ | ✅ |
| kick / ban / promote / permissions | ❌ | ✅؛ نیازمند ادمین |
| چند اکانت | ✅ | ✅ |
| اجرای بدون Chrome | ❌ | ✅ |

Selenium همچنان backend پیش‌فرض است؛ کدهای قدیمی بدون تعیین `backend` رفتار قبلی را حفظ می‌کنند.

## نصب PyPI

```bash
# هسته و Selenium
pip install soropy

# WebSocket / MTProto
pip install "soropy[ws]"
```

extra وب‌سوکت شامل `splusthon>=1.1.2,<1.1.3`، `aiohttp`، `pyaes` و `rsa` است. dependencyهای AI عمداً dependency اصلی نیستند و فقط در مثال AI به‌صورت lazy import می‌شوند.

## نصب GitHub از main

```bash
pip uninstall soropy -y
pip install "soropy[ws] @ git+https://github.com/Alirezahjf/soropy.git@main#subdirectory=soropy"
python -c "import soropy; print(soropy.__version__)"
```

## مثال Selenium

```python
from soropy import SoroushClient

with SoroushClient("09123456789", backend="selenium", headless=True) as client:
    status = client.login()
    chats = client.get_chats()
    print(status, chats.personal[:10])
    print(client.send_message("علی", "سلام از Selenium"))
```

## مثال WebSocket realtime

```python
from soropy import SoroushClient

client = SoroushClient("09123456789", backend="websocket")

def on_message(event):
    data = event.data
    print(data["chat_name"], data["text"])

client.on("new_message", on_message)
client.login(code_callback=lambda: input("کد پیامک‌شده: ").strip())
client.send_message("علی", "سلام از MTProto")
client.close()
```

## payload رویداد

```text
message_id, chat_id, chat_name, text,
sender_id, sender_name,
is_outgoing, is_private, is_group, is_channel,
timestamp, reply_to_id
```

handlerهای کاربر خارج از thread دریافت MTProto اجرا می‌شوند تا callback کند، ping/recv وب‌سوکت را مسدود نکند.

## پروژه‌های آماده WebSocket

| پروژه | فایل | توضیح |
|---|---|---|
| مدیر تمام‌عیار گروه | [`group_moderator.py`](soropy/examples/websocket/group_moderator.py) | ضدلینک، ضدواژه، ضد flood، ضد تکرار، state پایدار و سه اخطار |
| دستیار هوش مصنوعی | [`ai_assistant.py`](soropy/examples/websocket/ai_assistant.py) | OpenAI، compatible، Gemini، Claude و Ollama محلی |
| Cookbook کامل API | [`capability_cookbook.py`](soropy/examples/websocket/capability_cookbook.py) | نمونهٔ همهٔ متدهای WebSocket بدون اجرای خودکار عملیات خطرناک |
| راهنمای مثال‌ها | [`examples/websocket/README.md`](soropy/examples/websocket/README.md) | نصب، env، امنیت، AI، moderation و MultiAccount |

راهنمای مستندات: [`docs/WEBSOCKET_EXAMPLES.md`](docs/WEBSOCKET_EXAMPLES.md)

### snippet کوتاه مدیر گروه

```bash
export SOROPY_PHONE="09123456789"
export SOROPY_GROUP="نام دقیق گروه"
export SOROPY_GROUP_TARGET="@group_or_id"
export SOROPY_BAD_WORDS="کلمه۱,کلمه۲"
export SOROPY_ALLOWED_DOMAINS="example.com,splus.ir"
python -m examples.websocket.group_moderator
```

### snippet اتصال AI

```bash
# محلی و بدون API key
ollama serve
export AI_PROVIDER=ollama
export AI_MODEL=llama3.2
python -m examples.websocket.ai_assistant

# OpenAI-compatible
pip install openai
export AI_PROVIDER=openai-compatible
export OPENAI_API_KEY="..."
export OPENAI_BASE_URL="https://api.example.com/v1"
```

## پیام، فایل، گروه و کانال

```python
client.send_message("علی", "پیام معمولی")
client.reply("علی", message_id=12345, text="پاسخ به پیام")
client.send_bulk_messages(["علی", "رضا"], "پیام گروهی", delay=3)
client.send_to_group("گروه خانواده", "سلام گروه")
client.send_to_channel("@my_channel", "پست کانال")
client.send_file("علی", "file.pdf", caption="فایل")
client.download_media("علی", message_id=12345, file_path="downloads/file.bin")
client.edit_message("علی", 12345, "متن ویرایش‌شده")
client.delete_messages("علی", [12345, 12346], revoke=True)
client.pin_message("علی", 12345, notify=False)
client.unpin_message("علی", 12345)
client.unpin_message("علی")  # همه
```

## مخاطبین

```python
contacts = client.get_contacts()
results = client.search_contacts("baba")
ok = client.add_contact("09123456789", "علی", "احمدی")
client.block_user("@spam_user")
client.unblock_user("@spam_user")
client.report("@spam_user", reason="spam", message="پیام مزاحم")
```

## moderation

```python
client.kick("گروه من", "@user")
client.ban("گروه من", "@user")
client.unban("گروه من", "@user")
client.set_permissions("گروه من", "@user", send_messages=False)
client.promote("گروه من", "@user", title="پشتیبان", delete_messages=True)
participants = client.get_participants("گروه من", limit=100)
permissions = client.get_permissions("گروه من", "@user")
```

برای نام‌های تکراری از `@username` یا ID عددی استفاده کنید. resolver نام مبهم را انتخاب نمی‌کند تا عملیات روی فرد اشتباه اجرا نشود.

## auto-reply

```python
client.add_reply_rule("سلام", "علیک سلام 👋")
client.add_reply_rule("قیمت", "لطفاً با پشتیبانی تماس بگیرید")
client.set_default_reply("پیامت دریافت شد ✅")
client.set_auto_reply_enabled(True)
client.set_private_only(True)
client.start_monitor(interval=120, blocking=True)
```

در WebSocket مسیر اصلی realtime است و monitor فقط safety-net با حداقل 120 ثانیه فاصله است.

## چند اکانت

```python
from soropy import MultiAccountManager

with MultiAccountManager(backend="websocket") as manager:
    manager.add_account("09123456789")
    manager.add_account("09187654321")
    manager.login_all(parallel=False)
    manager.get_client("09123456789").send_message("علی", "سلام")
    manager.start_all_monitors(interval=120)
    manager.stop_all_monitors()
```

## رویدادها

```python
client.on("connected", handler)
client.on("auth_success", handler)
client.on("new_message", handler)
client.on("message_sent", handler)
client.on("chat_updated", handler)
client.on("unread_changed", handler)
client.on("error", handler)
client.on("disconnected", handler)
client.off("new_message", handler)
```

## session

| backend | مسیر session | محتوا |
|---|---|---|
| Selenium | `soropy_sessions/plus_98…/` | Chrome profile |
| WebSocket | `soropy_ws_sessions/plus_98….session` | SQLite auth key + DC |

```python
print(client.has_session)
client.close()
client.delete_session()  # فقط برای auth key خراب یا خروج کامل
```

session، tracker، `manager_config.json`، `.venv`، `__pycache__` و شمارهٔ واقعی را commit نکنید.

## منوی تعاملی

```bash
git clone https://github.com/Alirezahjf/soropy.git
cd soropy
pip install -e "./soropy[ws]"
python interactive_manager.py
```

منو login، وضعیت، چت‌ها، ارسال متن/فایل، قوانین auto-reply، listener، live feed، contacts، moderation، حذف/ویرایش/pin/download و smoke test را پوشش می‌دهد.

## Troubleshooting

| علامت | علت / راه‌حل |
|---|---|
| شماره مثل `0912xxxxxxx` | شماره واقعی 11 رقمی مثل `09123456789` بدهید. |
| `The key is not registered` | `delete_session()` یا گزینهٔ حذف session در منو. |
| `requires 'splusthon'` | `pip install "soropy[ws]"` |
| `Unclosed client session` | همیشه `client.close()` یا context manager. |
| `CHAT_ADMIN_REQUIRED` | دسترسی ادمین ندارید یا target گروه/کانال اشتباه است. |
| auto-reply جواب نمی‌دهد | rule/default، listener و PV-only را بررسی کنید. |
| endpoint وصل نمی‌شود | DNS، firewall، VPN/proxy و ساعت سیستم را بررسی کنید. |
| AI خطا می‌دهد | package و API key همان provider را نصب/تنظیم کنید؛ dependencyهای AI اختیاری‌اند. |

## فهرست کامل API

| دسته | متدها |
|---|---|
| Lifecycle | `SoroushClient(..., backend="websocket")`, `login`, `close`, `is_logged_in`, `get_me`, `has_session`, `delete_session` |
| Events | `on`, `off`, `connected`, `auth_success`, `new_message`, `message_sent`, `chat_updated`, `unread_changed`, `error`, `disconnected` |
| Chat/message | `get_chats`, `get_chats(save_to="chats.json")`, `send_message`, `reply`, `send_bulk_messages`, `send_to_personal`, `send_to_group`, `send_to_channel` |
| Media/tools | `send_file`, `download_media`, `edit_message`, `delete_messages`, `pin_message`, `unpin_message` |
| Contacts/user | `get_contacts`, `search_contacts`, `add_contact`, `block_user`, `unblock_user`, `report` |
| Moderation | `get_participants`, `get_permissions`, `set_permissions`, `promote`, `kick`, `ban`, `unban` |
| Auto-reply | `add_reply_rule`, `remove_reply_rule`, `set_default_reply`, `load_reply_rules`, `set_auto_reply_enabled`, `set_private_only`, `check_and_reply`, `start_monitor`, `stop_monitor` |
| Multi-account | `MultiAccountManager`, `add_account`, `login_all`, `start_all_monitors`, `stop_all_monitors`, `get_client`, `close_all` |

## معماری

```text
SoroushClient (API عمومی sync)
└── BaseBackend
    ├── SeleniumBackend
    │   └── Chrome + DOM managers
    └── WebSocketBackend
        ├── EventBus (dispatch خارج loop دریافت)
        └── MtprotoEngine
            ├── LoopRunner (asyncio thread)
            └── SPlusthon
                └── MTProto obfuscated abridged over WSS
```

endpoint واقعی: `wss://im-server.splus.ir:443/apiws`

Origin: `https://web.splus.ir`

API عمومی web client: `1030400 / 6edb16cf88714a4e9a805e928c39c937`

جزئیات بیشتر: [`docs/WEBSOCKET_ARCHITECTURE.md`](docs/WEBSOCKET_ARCHITECTURE.md)

## Smoke tests توسعه‌دهنده

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -e "./soropy[ws]" pytest ruff build
python -m compileall -q soropy/soropy soropy/examples soropy/tests interactive_manager.py
pytest -q soropy/tests
ruff check soropy/examples/websocket soropy/tests/test_websocket_examples.py
python -m build soropy
cmp -s README.md soropy/README.md
```

تست endpoint واقعی login/send/receive/upload نیازمند حساب آزمایشی است.

## لایسنس

- هستهٔ SoroPy و backend Selenium: **MIT**
- dependency اختیاری SPlusthon: **GPL-3.0**

توزیع محصولی که dependency GPL را ترکیب می‌کند می‌تواند تعهدات GPL داشته باشد؛ پیش از توزیع تجاری بررسی حقوقی انجام دهید.

## Repository و Issues

- Repository: https://github.com/Alirezahjf/soropy
- Issues: https://github.com/Alirezahjf/soropy/issues

## جامعه و سازنده

<div align="center">

<a href="https://t.me/soropy"><img src="https://img.shields.io/badge/Telegram%20Group-soropy-229ED9?style=for-the-badge" /></a>
<a href="https://ble.ir/soropy"><img src="https://img.shields.io/badge/Bale%20Group-soropy-00A693?style=for-the-badge" /></a>
<a href="https://splus.ir/soropy"><img src="https://img.shields.io/badge/Soroush%20Plus%20Group-soropy-f97316?style=for-the-badge" /></a>
<a href="https://rubika.ir/soropy"><img src="https://img.shields.io/badge/Rubika%20Group-soropy-8b5cf6?style=for-the-badge" /></a>

<br />

<a href="https://t.me/mr_hjf"><img src="https://img.shields.io/badge/Creator%20Telegram-mr__hjf-229ED9?style=for-the-badge" /></a>
<a href="https://ble.ir/mrhjf"><img src="https://img.shields.io/badge/Creator%20Bale-mrhjf-00A693?style=for-the-badge" /></a>
<a href="https://splus.ir/mr_hjf"><img src="https://img.shields.io/badge/Creator%20Soroush%20Plus-mr__hjf-f97316?style=for-the-badge" /></a>
<a href="https://rubika.ir/mr__hjf"><img src="https://img.shields.io/badge/Creator%20Rubika-mr____hjf-8b5cf6?style=for-the-badge" /></a>

</div>

<div align="center">

**ساخته‌شده با ❤️ برای جامعهٔ Python فارسی — نسخهٔ 1.3.4**

</div>
