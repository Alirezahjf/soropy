
# SoroPy 🚀

**حرفه‌ای‌ترین کتابخانه پایتون برای سروش پلاس**

[![PyPI](https://img.shields.io/pypi/v/soropy)](https://pypi.org/project/soropy/)
[![Downloads](https://img.shields.io/pypi/dm/soropy)](https://pypi.org/project/soropy/)
[![Python](https://img.shields.io/pypi/pyversions/soropy)](https://pypi.org/project/soropy/)
[![License](https://img.shields.io/pypi/l/soropy)](https://opensource.org/licenses/MIT)

---

## ✨ امکانات

| قابلیت | توضیح |
|--------|-------|
| 🔐 **لاگین خودکار** | ورود با شماره + کد تأیید، ذخیره سشن |
| 💬 **استخراج چت‌ها** | لیست همه / شخصی / گروه / کانال |
| 📨 **ارسال پیام** | تکی و دسته‌ای به چت‌های شخصی |
| 📢 **ارسال در کانال** | پست گذاشتن (نیاز به ادمین بودن) |
| 📇 **مدیریت مخاطبین** | مشاهده، اضافه کردن، جستجو |
| 🤖 **پاسخ خودکار** | موتور قوانین + جلوگیری از پاسخ تکراری |
| 👁️ **مانیتور مداوم** | بررسی و پاسخ خودکار هر X ثانیه |
| 👥 **چند اکانت** | مدیریت همزمان چندین حساب |
| 🖥️ **بدون پنجره** | حالت headless - بدون نمایش مرورگر |
| 🧵 **Thread-safe** | طراحی ایمن برای چند نخی |
| 💾 **ذخیره سشن** | بدون نیاز به لاگین مجدد |
| 🔌 **دو Backend** | Selenium (UI) و WebSocket (پروتکل) |
| ⚡ **رویداد لحظه‌ای** | `on("new_message")` روی backend وب‌سوکت |

---

## 📦 نصب

```bash
pip install soropy
pip install soropy[ws]   # اختیاری – برای backend وب‌سوکت
```

### پیش‌نیازها
- Python 3.8+
- Google Chrome / Chromium (فقط backend=selenium)
- ChromeDriver (مطابق نسخه Chrome)

---

## 🚀 شروع سریع

### استفاده ساده

```python
from soropy import SoroushClient

client = SoroushClient("09123456789")
client.login()

# ارسال پیام
client.send_message("علی", "سلام!")

# استخراج لیست چت
chats = client.get_chats()
print(f"تعداد چت: {chats.total_count}")

client.close()
```

### Context Manager

```python
from soropy import SoroushClient

with SoroushClient("09123456789", headless=True) as client:
    client.login()
    client.send_message("علی", "سلام!")
```

---

## 🤖 پاسخ خودکار

```python
from soropy import SoroushClient

client = SoroushClient("09123456789")
client.login()

# تعریف قوانین
client.add_reply_rule("سلام", "علیک سلام! 👋")
client.add_reply_rule("قیمت", "لطفاً به سایت مراجعه کنید")
client.set_default_reply("پیامت دریافت شد ✅")

# شروع مانیتور (Ctrl+C برای توقف)
client.start_monitor(interval=30)

client.close()
```

### جلوگیری از پاسخ تکراری
SoroPy به‌صورت خودکار هش پیام‌های پاسخ‌داده‌شده را ذخیره می‌کند.
حتی بعد از ریستارت برنامه، پیام‌های قبلی دوباره پاسخ نمی‌گیرند.

---

## 👥 چند اکانت همزمان

```python
from soropy import MultiAccountManager

with MultiAccountManager(headless=True) as mgr:
    mgr.add_account("09123456789")
    mgr.add_account("09187654321")

    mgr.login_all()

    # ارسال از هر اکانت
    mgr.get_client("09123456789").send_message("علی", "سلام از اکانت ۱")
    mgr.get_client("09187654321").send_message("علی", "سلام از اکانت ۲")

    # مانیتور همه
    mgr.start_all_monitors(interval=30)
```

---

## 📇 مخاطبین

```python
# لیست مخاطبین
contacts = client.get_contacts()

# اضافه کردن
client.add_contact("09187654321", "محمد", "احمدی")

# جستجو
results = client.search_contacts("محمد")
```

---

## 📢 کانال

```python
# ارسال پست (نیاز به ادمین بودن)
client.send_to_channel("@my_channel", "پیام تست")
```

---

## ⚙️ تنظیمات پیشرفته

```python
client = SoroushClient(
    phone="09123456789",
    headless=True,                     # بدون پنجره
    session_dir="my_sessions",         # مسیر ذخیره سشن
    tracker_path="my_tracker.json",    # فایل ردیاب پیام
    log_file="soropy.log",             # فایل لاگ
    chrome_binary="/usr/bin/chromium", # مسیر Chrome
    chromedriver_path="/usr/bin/chromedriver",
    extra_chrome_args=["--proxy-server=..."],
)
```

---

## 🔌 Backend وب‌سوکت / MTProto

```bash
pip install soropy[ws]
```

```python
from soropy import SoroushClient

client = SoroushClient("09123456789", backend="websocket")
client.on("new_message", lambda e: print(e.data))
client.login()
client.send_message("علی", "سلام!")
```

جزئیات: `docs/WEBSOCKET_ARCHITECTURE.md`

---

## 🏗️ معماری

```
SoroushClient (client.py)          ← API عمومی ثابت
└── BaseBackend
    ├── SeleniumBackend            ← پیش‌فرض (Chrome + DOM)
    └── WebSocketBackend           ← رویدادمحور (experimental)

AutoReplyEngine + MessageTracker   ← مشترک
MultiAccountManager(backend=...)
```

---

## 📄 License

MIT License - آزاد برای استفاده شخصی و تجاری

---

## 📬 ارتباط با توسعه‌دهنده

<p align="center">

[![Telegram](https://img.shields.io/badge/Telegram-@mr__hjf-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white)](https://t.me/mr_hjf)
[![Rubika](https://img.shields.io/badge/Rubika-@mr____hjf-8E24AA?style=for-the-badge&logo=data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAA4AAAAOCAYAAAAfSC3RAAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAAJcEhZcwAADsMAAA7DAcdvqGQAAAA0SURBVDhPY/hPIWBgGHaaiYECMKoRN0A1Bv9HF8QLRjUiA1Q7R0fDBCgNRjXiBgz/AQDmXwb/vnToiQAAAABJRU5ErkJggg==)](https://rubika.ir/mr__hjf)
[![Bale](https://img.shields.io/badge/Bale-@mrhjf-4CAF50?style=for-the-badge&logo=data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAA4AAAAOCAYAAAAfSC3RAAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAAJcEhZcwAADsMAAA7DAcdvqGQAAAA0SURBVDhPY/hPIWBgGHaaiYECMKoRN0A1Bv9HF8QLRjUiA1Q7R0fDBCgNRjXiBgz/AQDmXwb/vnToiQAAAABJRU5ErkJggg==)](https://ble.ir/mrhjf)

</p>

---

## 🤝 مشارکت

نظرات، پیشنهادات و مشارکت‌های شما استقبال می‌شود!

- 💬 پیام مستقیم از طریق شبکه‌های بالا
- 🐛 گزارش باگ از طریق [Issues](https://github.com/Mrhjf/soropy/issues)
- 🔀 ارسال Pull Request از طریق [GitHub](https://github.com/Mrhjf/soropy)

---

<p align="center">
  ساخته شده با ❤️ توسط <a href="https://t.me/mr_hjf">MrHjf</a>
  <br/>
  <a href="https://pypi.org/project/soropy/">PyPI</a> •
  <a href="https://github.com/Mrhjf/soropy">GitHub</a> •
  <a href="https://t.me/mr_hjf">تلگرام</a>
</p>
