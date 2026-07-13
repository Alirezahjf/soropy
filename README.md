# SoroPy 1.3.3 🚀

کتابخانهٔ پایتون برای کار با **سروش‌پلاس** با یک API عمومی و دو backend مستقل:

- **Selenium**: کنترل رابط وب با Chrome؛ backend پیش‌فرض و مناسب اتوماسیون UI.
- **WebSocket / MTProto**: ارتباط realtime و بدون Chrome از طریق SPlusthon.

[![PyPI](https://img.shields.io/pypi/v/soropy)](https://pypi.org/project/soropy/)
[![Python](https://img.shields.io/pypi/pyversions/soropy)](https://pypi.org/project/soropy/)
[![License](https://img.shields.io/badge/core-MIT-blue.svg)](https://github.com/Alirezahjf/soropy/blob/main/soropy/LICENSE)

> [!IMPORTANT]
> backend وب‌سوکت از API رسمی عمومی استفاده نمی‌کند؛ SPlusthon یک کلاینت شخص ثالث MTProto است. قوانین و محدودیت‌های سروش‌پلاس را رعایت کنید و قبل از استفادهٔ عملی، حساب آزمایشی و نرخ ارسال محافظه‌کارانه داشته باشید.

---

## مقایسهٔ backendها

| قابلیت | Selenium | WebSocket / MTProto |
|---|:---:|:---:|
| `login` با شماره و کد | ✅ رابط وب | ✅ SMS / session |
| ذخیرهٔ session | Chrome profile | SQLite auth key |
| `send_message` و bulk | ✅ | ✅ |
| `reply` | محدود به DOM | ✅ با message ID |
| گروه و کانال | ✅ | ✅ |
| دریافت realtime با `new_message` | ❌ | ✅ |
| auto-reply | poll | push + poll ایمنی |
| auto-reply فقط PV به‌صورت پیش‌فرض | ✅ | ✅ |
| `send_file` / `download_media` | ❌ | ✅ |
| حذف، ویرایش، pin و unpin | ❌ | ✅ |
| مخاطبین | ✅ | ✅ |
| block / unblock / report | ❌ | ✅ |
| kick / ban / promote / permissions | ❌ | ✅؛ نیازمند دسترسی ادمین |
| چند اکانت | ✅؛ یک Chrome برای هر حساب | ✅؛ یک loop/session برای هر حساب |
| اجرای بدون Chrome | ❌ | ✅ |
| `headless` | ✅ | ذاتاً بدون UI |

Selenium همچنان backend پیش‌فرض است؛ کدهای قبلی بدون تعیین `backend` تغییر رفتار نمی‌دهند.

---

## نصب

### از PyPI

```bash
# هسته و Selenium
pip install soropy

# قابلیت‌های WebSocket / MTProto
pip install "soropy[ws]"
```

extra وب‌سوکت شامل `SPlusthon`, `aiohttp`, `pyaes` و `rsa` است. در نسخهٔ 1.3.3 بازهٔ شناخته‌شدهٔ پایدار SPlusthon یعنی `>=1.1.2,<1.1.3` استفاده می‌شود؛ 1.1.2 مشکل session مشترک چند اکانت را رفع کرده و 1.1.3 به‌دلیل regression در reconnect دوره‌ای فعلاً کنار گذاشته شده است.

### نصب مستقیم از branch این PR

آدرس Git باید **بدون `/tree/`** و همراه `#subdirectory=soropy` باشد:

```bash
pip uninstall soropy -y
pip install "soropy[ws] @ git+https://github.com/Alirezahjf/soropy.git@arena/019f56cc-soropy#subdirectory=soropy"
python -c "import soropy; print(soropy.__version__)"
# 1.3.3
```

### پیش‌نیازها

- Python 3.8+
- Selenium: Chrome/Chromium و ChromeDriver سازگار
- WebSocket: دسترسی شبکه به `im-server.splus.ir:443`؛ Chrome لازم نیست

---

## شروع سریع Selenium

```python
from soropy import SoroushClient

with SoroushClient("09123456789", backend="selenium", headless=True) as client:
    status = client.login()
    chats = client.get_chats()
    print(chats.personal[:10])
    result = client.send_message("علی", "سلام از Selenium")
    print(result)
```

### مسیر Chrome در ویندوز

```python
client = SoroushClient(
    "09123456789",
    backend="selenium",
    headless=False,
    chrome_binary=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    chromedriver_path=r"C:\tools\chromedriver.exe",
    extra_chrome_args=["--window-size=1280,900"],
)
client.login()
```

---

## WebSocket / MTProto realtime

```python
from soropy import SoroushClient

client = SoroushClient(
    "09123456789",
    backend="websocket",
    auto_reply_private_only=True,  # پیش‌فرض امن
)

def on_message(event):
    data = event.data
    print(
        data["chat_name"],
        data["text"],
        "PV" if data["is_private"] else "group/channel",
    )

client.on("new_message", on_message)
status = client.login()  # کد فقط بار اول؛ سپس SQLite session
print(status)

client.send_message("علی", "سلام از MTProto")
client.close()  # همیشه منابع aiohttp و loop را ببندید
```

payload نرمال‌شدهٔ `new_message`:

```text
message_id, chat_id, chat_name, text,
sender_id, sender_name,
is_outgoing, is_private, is_group, is_channel,
timestamp, reply_to_id
```

handlerهای کاربر خارج از thread دریافت MTProto اجرا می‌شوند تا callback کند، ping/recv وب‌سوکت را مسدود نکند.

---

## پیام، فایل، گروه و کانال

```python
client.send_message("علی", "پیام معمولی")
client.reply("علی", message_id=12345, text="پاسخ به پیام")
client.send_bulk_messages(["علی", "رضا"], "پیام گروهی", delay=3)
client.send_to_group("گروه خانواده", "سلام گروه")
client.send_to_channel("@my_channel", "پست کانال")  # دسترسی ارسال لازم است

# مسیر فارسی، فاصله و کوتیشن ویندوز پشتیبانی می‌شود.
client.send_file(
    "علی",
    r"C:\Users\me\Downloads\نحو مقدماتی- حمید محمدی.docx",
    caption="فایل آموزشی",
)
client.send_file("علی", "photo.jpg", caption="عکس", force_document=False)

path = client.download_media("علی", message_id=12345, file_path="downloads/file.bin")
client.edit_message("علی", 12345, "متن ویرایش‌شده")
client.delete_messages("علی", [12345, 12346], revoke=True)
client.pin_message("علی", 12345, notify=False)
client.unpin_message("علی", 12345)
client.unpin_message("علی")  # همه
```

در آپلود فایل:

- فایل ابتدا در `BytesIO` با نام ASCII-safe قرار می‌گیرد؛ extension حفظ می‌شود.
- فایل غیرتصویری به‌صورت document ارسال می‌شود.
- اندازهٔ part برابر 512 KiB و timeout برابر 300 ثانیه است.
- خطای `FILE_REQUEST_RECEIVED_ON_CONNECTION_SERVER` / RPC 422 یک‌بار reconnect و retry می‌شود.

---

## مخاطبین و عملیات کاربر

```python
contacts = client.get_contacts()
results = client.search_contacts("baba")  # local + contacts.SearchRequest

ok = client.add_contact("09123456789", "علی", "احمدی")
if not ok:
    print("شماره معتبر نیست، عضو سروش نیست یا import توسط سرور رد شده است")

client.block_user("@spam_user")
client.unblock_user("@spam_user")
client.report("@spam_user", reason="spam", message="پیام مزاحم")
```

`add_contact` شماره را سخت‌گیرانه اعتبارسنجی و variantهای `989…`، `+989…` و `09…` را برای import ارسال می‌کند. شماره‌هایی با رقم کم/زیاد یا placeholder رد می‌شوند.

reasonهای report: `spam`, `violence`, `porn`, `copyright`, `other`, `fake`, `child`, `geo`.

---

## مودریشن

تمام متدهای زیر مخصوص backend وب‌سوکت و نیازمند permission مناسب هستند:

```python
client.kick("گروه من", "@user")
client.ban("گروه من", "@user")
client.unban("گروه من", "@user")
client.set_permissions("گروه من", "@user", send_messages=False)
client.promote(
    "گروه من",
    "@user",
    title="پشتیبان",
    delete_messages=True,
    ban_users=True,
    invite_users=True,
)
participants = client.get_participants("گروه من", limit=100)
permissions = client.get_permissions("گروه من", "@user")
```

در 1.3.3 semantics مربوط به `ban` اصلاح شده است: API سطح بالای SPlusthon برای اعمال ban باید `view_messages=False` دریافت کند. همچنین `promote` فقط آرگومان‌های پشتیبانی‌شدهٔ `edit_admin` را ارسال می‌کند.

> برای نام‌های تکراری از `@username` یا ID عددی استفاده کنید. resolver دیگر substring مبهم را انتخاب نمی‌کند تا پیام یا عملیات مدیریتی روی فرد اشتباه اجرا نشود.

---

## پاسخ خودکار امن و realtime

```python
client = SoroushClient("09123456789", backend="websocket")
client.login()

client.add_reply_rule("سلام", "علیک سلام 👋")
client.add_reply_rule("قیمت", "لطفاً با پشتیبانی تماس بگیرید")
client.set_default_reply("پیامت دریافت شد ✅")
client.set_auto_reply_enabled(True)
client.set_private_only(True)  # پیش‌فرض؛ گروه/کانال پاسخ نمی‌گیرند

# realtime مسیر اصلی است؛ monitor فقط safety-net است.
client.start_monitor(interval=120, blocking=True)
```

رفتار مسیر realtime:

1. فقط پیام ورودی با `is_private=True` یا kind قطعی `personal` پذیرفته می‌شود.
2. `MessageTracker` قبل از queue شدن، ترجیحاً با `message_id`، رزرو می‌شود تا poll پاسخ تکراری ندهد؛ متن یکسان با ID جدید دوباره قابل پاسخ است.
3. ارسال sync در daemon worker خارج از event loop انجام می‌شود.
4. لاگ‌های `queued`، `delivered` و `failed` قابل مشاهده‌اند.
5. در شکست واقعی رزرو آزاد می‌شود؛ خطاهای permission کانال/گروه soft-skip هستند.

`default_reply` دقیقاً همان متن تنظیم‌شدهٔ کاربر است؛ fallback قدیمی «جواب N» به‌صورت پیش‌فرض خاموش است. poll وب‌سوکت حداقل فاصلهٔ 120 ثانیه و سقف 5 چت شخصی در هر cycle دارد.

---

## چند اکانت

```python
from soropy import MultiAccountManager

with MultiAccountManager(backend="websocket") as manager:
    manager.add_account("09123456789")
    manager.add_account("09187654321")
    manager.login_all(parallel=False)  # ورود تعاملی بهتر است ترتیبی باشد
    manager.get_client("09123456789").send_message("علی", "سلام")
    manager.start_all_monitors(interval=120)
```

برای Selenium فقط backend را عوض کنید:

```python
manager = MultiAccountManager(backend="selenium", headless=True)
```

مسیر session پیش‌فرض مدیر نیز با backend هماهنگ می‌شود.

---

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

| backend | مسیر session | محتوا |
|---|---|---|
| Selenium | `soropy_sessions/plus_98…/` | Chrome profile |
| WebSocket | `soropy_ws_sessions/plus_98….session` | SQLite auth key + DC |

```python
client.close()
client.delete_session()  # برای auth key خراب؛ در صورت اتصال ابتدا transport بسته می‌شود
```

session، فایل tracker، تنظیمات manager و شمارهٔ واقعی را commit نکنید.

---

## منوی تعاملی فارسی

```bash
git clone -b arena/019f56cc-soropy https://github.com/Alirezahjf/soropy.git
cd soropy
pip install -e "./soropy[ws]"
python interactive_manager.py
```

`manager_config.json` شماره، backend، قوانین و toggleها را محلی ذخیره می‌کند و در Git نادیده گرفته می‌شود.

منو شامل این بخش‌ها است:

1. لاگین/اتصال با WebSocket پیش‌فرض یا Selenium
2. وضعیت و capabilityها
3. چت‌ها و export JSON
4. متن، reply، bulk، فایل، گروه و کانال
5. قوانین، default، import/export و toggleها
6. Listener، Monitor، Auto-reply، PV-only و log مستقل
7. Live feed
8. مخاطبین
9. مودریشن، block و report
10. حذف/ویرایش/pin/download
11. smoke test
12. حذف session
13. خروج از حساب

callback کد SMS صریحاً روی thread منو اجرا می‌شود. مسیر فایل ویندوز از کوتیشن پاک، وجود فایل و اندازهٔ آن قبل از ارسال بررسی می‌شود.

---

## عیب‌یابی

| علامت | علت / راه‌حل |
|---|---|
| `0912xxxxxxx` یا شمارهٔ کوتاه/بلند | شمارهٔ واقعی 11 رقمی مثل `09123456789` بدهید. |
| `The key is not registered` / `AuthKeyNotFound` | 1.3.3 یک‌بار session را خودکار reset می‌کند؛ در صورت تکرار `delete_session()` یا گزینهٔ 12 منو. |
| `WebSocket closed`، pending SignIn/Ping زیاد | از 1.3.1 دریافت SMS/2FA خارج event loop است. نسخه را بررسی و session خراب را حذف کنید. |
| `FILE_REQUEST_RECEIVED_ON_CONNECTION_SERVER` / 422 | از 1.3.2+ نام ASCII، document upload و یک reconnect/retry انجام می‌شود. |
| auto-reply دیر یا بدون پاسخ | Rule/default، Auto-reply، Listener و PV-only را روشن کنید؛ لاگ `queued/delivered/failed` را ببینید. Monitor مسیر اصلی نیست. |
| سیل `CHAT_ADMIN_REQUIRED` | PV-only را روشن نگه دارید؛ گروه و broadcast channel نباید auto-reply بگیرند. |
| نام مشابه به فرد اشتباه resolve نمی‌شود | رفتار عمدی است؛ `@username` یا peer ID بدهید. |
| `Unclosed client session` | حتماً `client.close()` یا context manager؛ 1.3.3 nested aiohttp sessionها را هم می‌بندد. |
| `requires 'splusthon'` | `pip install "soropy[ws]"` |
| خطای اتصال به `im-server.splus.ir:443` | DNS، firewall، VPN/proxy و ساعت سیستم را بررسی کنید. |
| متد WS روی Selenium | backend را `websocket` کنید؛ متد unsupported باید `SoroPyError` واضح بدهد. |

---

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

فایل‌های legacy مربوط به JSON/raw WebSocket در tree باقی مانده‌اند اما مسیر production از آن‌ها استفاده نمی‌کند. جزئیات بیشتر در [WebSocket Architecture](https://github.com/Alirezahjf/soropy/blob/main/docs/WEBSOCKET_ARCHITECTURE.md).

---

## smoke test توسعه‌دهنده

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -e "./soropy[ws]" pytest
python -m compileall -q soropy/soropy interactive_manager.py
pytest -q soropy/tests
python -c "import soropy; print(soropy.__version__)"
```

تست‌ها login callback خارج loop، مسیر Unicode، semantics مربوط به ban/promote، unread stale، EventBus، auto-reply reservation و deadlock guard را بدون نیاز به حساب واقعی پوشش می‌دهند. تست نهایی login/send/receive/upload باید با حساب آزمایشی واقعی انجام شود.

---

## لایسنس

- هستهٔ SoroPy و backend Selenium: **MIT**
- dependency اختیاری SPlusthon: **GPL-3.0**

توزیع محصولی که dependency GPL را ترکیب می‌کند می‌تواند تعهدات GPL داشته باشد؛ پیش از توزیع تجاری بررسی حقوقی انجام دهید.

---

## ارتباط

- Issues: https://github.com/Alirezahjf/soropy/issues
- Repository: https://github.com/Alirezahjf/soropy

ساخته‌شده با ❤️ — نسخهٔ **1.3.3**
