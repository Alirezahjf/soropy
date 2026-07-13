<div align="center">

# 🚀 مثال‌های WebSocket / MTProto در SoroPy

[![SoroPy](https://img.shields.io/badge/SoroPy-1.3.4-blue)](https://pypi.org/project/soropy/)
[![Backend](https://img.shields.io/badge/WebSocket-MTProto-success)](../../README.md)
[![Python](https://img.shields.io/badge/Python-3.8%2B-yellow)](https://www.python.org/)

**مدیر گروه، دستیار هوش مصنوعی و cookbook کامل API برای سروش‌پلاس**

</div>

> ⚠️ قبل از استفادهٔ عملی، همه چیز را روی گروه آزمایشی و حساب تست بررسی کنید. شماره، کد SMS، API key و فایل session را برای هیچ‌کس ارسال نکنید.

## انتخاب مثال مناسب

| فایل | کاربرد | اجرا |
|---|---|---|
| [`group_moderator.py`](group_moderator.py) | مدیر گروه ضدلینک/واژه/flood با سه اخطار | `python -m examples.websocket.group_moderator` |
| [`ai_assistant.py`](ai_assistant.py) | دستیار AI با OpenAI/Gemini/Claude/Ollama | `python -m examples.websocket.ai_assistant` |
| [`capability_cookbook.py`](capability_cookbook.py) | نمونهٔ همهٔ APIهای WebSocket | `python -m examples.websocket.capability_cookbook` |
| [`README.md`](README.md) | همین راهنما | — |

## نصب پایه

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install "soropy[ws]"
```

## مدیر گروه

### PowerShell ویندوز

```powershell
$env:SOROPY_PHONE="09123456789"
$env:SOROPY_GROUP="نام دقیق گروه"
$env:SOROPY_GROUP_TARGET="@group_username_or_id"
$env:SOROPY_BAD_WORDS="کلمه۱,کلمه۲"
$env:SOROPY_ALLOWED_DOMAINS="example.com,splus.ir"
python -m examples.websocket.group_moderator
```

### Linux/macOS

```bash
export SOROPY_PHONE="09123456789"
export SOROPY_GROUP="نام دقیق گروه"
export SOROPY_GROUP_TARGET="@group_username_or_id"
export SOROPY_BAD_WORDS="کلمه۱,کلمه۲"
export SOROPY_ALLOWED_DOMAINS="example.com,splus.ir"
python -m examples.websocket.group_moderator
```

### متغیرهای moderation

| متغیر | پیش‌فرض | توضیح |
|---|---:|---|
| `SOROPY_PHONE` | `09123456789` | شمارهٔ حساب |
| `SOROPY_GROUP` | متن نمونه | نام دقیق گروه برای فیلتر event |
| `SOROPY_GROUP_TARGET` | مقدار `SOROPY_GROUP` | @username یا ID دقیق برای عملیات |
| `SOROPY_SESSION_DIR` | `soropy_ws_sessions` | محل session و state |
| `SOROPY_MAX_WARNINGS` | `3` | تعداد اخطار قبل از kick |
| `SOROPY_BAD_WORDS` | placeholder | واژه‌ها با کاما؛ فحش واقعی در سورس نیست |
| `SOROPY_ALLOWED_DOMAINS` | خالی | اگر خالی باشد همهٔ لینک‌ها ممنوع‌اند |
| `SOROPY_FLOOD_MAX` / `SOROPY_FLOOD_WINDOW` | `6` / `8` | ضد flood |
| `SOROPY_REPEAT_MAX` / `SOROPY_REPEAT_WINDOW` | `3` / `30` | ضد تکرار متن |
| `SOROPY_EXEMPT_USER_IDS` | خالی | ID کاربران معاف با کاما |

### افزودن قانون سفارشی

در فایل `group_moderator.py` می‌توانید قبل از `process` یک rule جدید اضافه کنید یا با env واژه‌ها و دامنه‌های مجاز را تغییر دهید. state اخطارها در `soropy_ws_sessions/moderator_warnings.json` ذخیره و به‌صورت atomic نوشته می‌شود.

### فرمان‌های مدیر

```text
/rules
/warnings
/forgive USER_ID
/kick USER_ID
/ban USER_ID
```

فرمان‌ها فقط برای admin/creator اجرا می‌شوند. برای گروه‌های هم‌نام، حتماً `SOROPY_GROUP_TARGET` را با @username یا ID دقیق تنظیم کنید.

## دستیار AI

### OpenAI

```bash
pip install openai
export AI_PROVIDER=openai
export OPENAI_API_KEY="sk-..."
export AI_MODEL="gpt-4o-mini"
python -m examples.websocket.ai_assistant
```

### OpenAI-compatible

```bash
pip install openai
export AI_PROVIDER=openai-compatible
export OPENAI_API_KEY="..."
export OPENAI_BASE_URL="https://api.example.com/v1"
export AI_MODEL="model-name"
```

### Gemini

```bash
pip install google-genai
export AI_PROVIDER=gemini
export GEMINI_API_KEY="..."
export AI_MODEL="gemini-1.5-flash"
```

### Claude

```bash
pip install anthropic
export AI_PROVIDER=claude
export ANTHROPIC_API_KEY="..."
export AI_MODEL="claude-3-5-haiku-latest"
```

### Ollama محلی

```bash
ollama serve
ollama pull llama3.2
export AI_PROVIDER=ollama
export AI_MODEL=llama3.2
python -m examples.websocket.ai_assistant
```

### AI در گروه

پیش‌فرض فقط PV پاسخ می‌گیرد. برای گروه:

```bash
export AI_PRIVATE_ONLY=false
export SOROPY_AI_GROUP="نام دقیق گروه"
```

در گروه فقط این triggerها پاسخ می‌گیرند:

```text
/ai سؤال شما
هوش: سؤال شما
```

### تنظیم رفتار

| متغیر | توضیح |
|---|---|
| `AI_SYSTEM_PROMPT` | شخصیت و دستورالعمل سیستم |
| `AI_RATE_LIMIT` | سقف پیام هر کاربر در دقیقه |
| `AI_HISTORY_MESSAGES` | تعداد پیام‌های history برای هر chat |
| `AI_MAX_REPLY_CHARS` | اندازهٔ chunk پاسخ؛ chunk اول reply و بقیه send می‌شود |

### حریم خصوصی

متن پیام‌ها برای provider انتخابی شما ارسال می‌شود. برای دادهٔ حساس از Ollama محلی استفاده کنید یا provider ابری را خاموش نگه دارید.

## جدول API WebSocket

| قابلیت | یک خط کد |
|---|---|
| login | `client.login(code_callback=lambda: input("کد: ").strip())` |
| get_me | `client.get_me()` |
| get_chats | `client.get_chats(save_to="chats.json")` |
| send | `client.send_message("@user", "سلام")` |
| reply | `client.reply("@user", 123, "پاسخ")` |
| bulk | `client.send_bulk_messages(["@a", "@b"], "سلام")` |
| file | `client.send_file("@user", "file.pdf")` |
| download | `client.download_media("@user", 123)` |
| edit/delete | `client.edit_message("@user", 123, "جدید"); client.delete_messages("@user", [123])` |
| pin/unpin | `client.pin_message("@user", 123); client.unpin_message("@user")` |
| contacts | `client.get_contacts(); client.search_contacts("علی")` |
| add contact | `client.add_contact("09123456789", "علی")` |
| block/report | `client.block_user("@spam"); client.report("@spam")` |
| permissions | `client.get_permissions("@group", "@user")` |
| promote | `client.promote("@group", "@user", delete_messages=True)` |
| kick/ban | `client.kick("@group", "@user"); client.ban("@group", "@user")` |
| auto-reply | `client.add_reply_rule("سلام", "علیک"); client.start_monitor(120)` |
| events | `client.on("new_message", handler)` |

## MultiAccountManager

```python
from soropy import MultiAccountManager

with MultiAccountManager(backend="websocket") as manager:
    manager.add_account("09123456789")
    manager.login_all(parallel=False)
    client = manager.get_client("09123456789")
    client.send_message("@user", "سلام")
    manager.start_all_monitors(interval=120)
    manager.stop_all_monitors()
```

## جامعه و سازنده

<div align="center">

<a href="https://t.me/soropy">Telegram گروه</a> ·
<a href="https://ble.ir/soropy">Bale گروه</a> ·
<a href="https://splus.ir/soropy">Soroush Plus گروه</a> ·
<a href="https://rubika.ir/soropy">Rubika گروه</a>

<a href="https://t.me/mr_hjf">Telegram سازنده</a> ·
<a href="https://ble.ir/mrhjf">Bale سازنده</a> ·
<a href="https://splus.ir/mr_hjf">Soroush Plus سازنده</a> ·
<a href="https://rubika.ir/mr__hjf">Rubika سازنده</a>

</div>
