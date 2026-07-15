# SoroPy WebSocket / MTProto Architecture — 1.3.6

> Endpoint: `wss://im-server.splus.ir:443/apiws`
> Origin: `https://web.splus.ir`
> Status: adapter کامل با تست‌های رگرسیون آفلاین؛ تست پذیرش نهایی نیازمند حساب واقعی است.

## 1. پروتکل واقعی

وب‌کلاینت سروش‌پلاس JSON ساده روی WebSocket نیست. stack مشاهده‌شده با MTProto سازگار است:

| لایه | مقدار |
|---|---|
| Socket | WebSocket binary frames |
| Codec | obfuscated + abridged MTProto |
| Schema | TL layer نزدیک 182 با DC/RSA سروش |
| API ID | `1030400` |
| API hash | `6edb16cf88714a4e9a805e928c39c937` |
| App version | `3.9.2 A` |

SoroPy پروتکل و crypto را از صفر پیاده نمی‌کند. `MtprotoEngine` یک adapter روی SPlusthon است.

## 2. ساختار

```text
SoroushClient (public synchronous API)
└── BaseBackend
    ├── SeleniumBackend
    │   ├── BrowserManager
    │   └── DOM chat/contact/channel managers
    └── WebSocketBackend
        ├── EventBus
        │   └── ThreadPoolExecutor (user callbacks off recv loop)
        └── MtprotoEngine
            ├── LoopRunner
            │   └── dedicated asyncio daemon thread
            ├── entity/kind cache
            └── splusthon.SoroushClient
                ├── MTProto sender/update loop
                ├── ConnectionWebSocket
                └── aiohttp ClientSession
```

API عمومی sync است. هر عملیات شبکهٔ SPlusthon به‌کمک `LoopRunner.run()` روی loop اختصاصی اجرا می‌شود. `LoopRunner.run()` از thread خود loop ممنوع است و guard صریح دارد.

## 3. ماژول‌ها

| فایل | نقش |
|---|---|
| `backends/base.py` | قرارداد مشترک backendها |
| `backends/websocket/backend.py` | تبدیل مدل‌های MTProto به API عمومی |
| `backends/websocket/mtproto_engine.py` | login، messaging، media، contacts و moderation |
| `backends/websocket/loop_runner.py` | bridge امن sync/async |
| `backends/websocket/events.py` | payload استاندارد و dispatch خارج loop |
| `client.py` | façade، auto-reply و monitor |
| `message_tracker.py` | رزرو/ضدتکرار persistent و atomic |

این فایل‌ها legacy و خارج از مسیر اجرایی فعلی هستند:

- `backends/websocket/protocol.py`
- `backends/websocket/transport.py`
- `backends/websocket/auth.py`
- `backends/websocket/session.py`

آن‌ها scaffold آزمایشی JSON/raw WebSocket هستند و نباید با backend MTProto اشتباه شوند.

## 4. lifecycle و session

```text
construct
  → login
      → connect
      → is_user_authorized
      ├── authorized: SESSION_RESTORED
      └── unauthorized:
          1. send_code_request on asyncio loop
          2. code_callback on caller/UI thread
          3. reconnect if transport dropped while waiting
          4. sign_in on asyncio loop
          5. optional 2FA callback on caller thread
  → operations/events
  → close
      → client.disconnect
      → nested aiohttp ClientSession close
      → SQLite session close
      → LoopRunner.stop
```

مسیر فایل session:

```text
soropy_ws_sessions/plus_98912….session
```

برای `AuthKeyNotFound`، `AUTH_KEY_UNREGISTERED` یا «key is not registered»، engine یک بار transport را می‌بندد، session و sidecarهای journal/WAL/SHM را حذف می‌کند و اتصال تازه می‌سازد.

### اصل حیاتی login

`input()` و callback کد/رمز هرگز داخل coroutine شبکه اجرا نمی‌شوند. در نسخه‌های قدیمی، توقف event loop هنگام انتظار SMS باعث watchdog 90 ثانیه‌ای، pending RPC، reconnect storm و session باز aiohttp می‌شد.

## 5. event flow

```text
SPlusthon NewMessage coroutine
  → normalize IncomingMessage
  → WebSocketBackend._on_incoming
  → EventBus.emit_async
  → worker thread
      ├── internal realtime auto-reply hook
      └── user handlers
```

payload:

```text
message_id, chat_id, chat_name, text,
sender_id, sender_name,
is_outgoing, is_private, is_group, is_channel,
timestamp, reply_to_id
```

EventBus registration thread-safe است. handler کند کاربر ping/receive loop را متوقف نمی‌کند.

## 6. auto-reply

مسیر realtime:

1. پیام outgoing حذف می‌شود.
2. در حالت پیش‌فرض فقط `is_private=True` یا kind قطعی `personal` پذیرفته می‌شود.
3. rule/default با `AutoReplyEngine` انتخاب می‌شود.
4. tracker **قبل از queue** با `message_id` علامت می‌خورد تا poll همان پیام را دوباره پاسخ ندهد؛ در نبود ID از متن استفاده می‌شود.
5. daemon worker، متد sync reply را خارج loop صدا می‌زند.
6. لاگ `queued` سپس `delivered` یا `failed` ثبت می‌شود.
7. در failure واقعی tracker آزاد می‌شود؛ permission errorهای گروه/کانال soft-skip هستند.

مسیر poll فقط safety-net است:

- حداقل interval وب‌سوکت: 120 ثانیه
- حداکثر personal chat در cycle: 5
- refresh موفق dialogها authoritative است و counter قدیمی پاک می‌شود
- channel broadcast هرگز personal نیست

دسته‌بندی entity:

| Entity | kind |
|---|---|
| `User` / `UserEmpty` | personal |
| `Channel(broadcast=True)` | channel |
| `Channel(megagroup/gigagroup=True)` | group |
| `Channel` بدون broadcast | group |
| `Chat` | group |

## 7. upload فایل

`send_file` برای pathهای Windows/Unicode این مراحل را دارد:

1. حذف کوتیشن اطراف path و بررسی `isfile`
2. خواندن bytes
3. ساخت `BytesIO` با نام ASCII-safe و extension اصلی
4. ساخت sender اختصاصی upload بدون دست‌زدن به sender اصلی WebSocket
5. ارسال اولین `SaveFilePartRequest` واقعی داخل `InvokeWithLayer(InitConnection(..., params=upload))` تا سرور اتصال را upload-only تشخیص دهد
6. ارسال partهای بعدی روی همان sender اختصاصی و ساخت `InputFile` / `InputFileBig`
7. ارسال پیام نهایی با file handle روی اتصال اصلی (regular RPC)
8. non-image با `force_document=True` و timeout کل 300 ثانیه
9. روی `FILE_REQUEST_RECEIVED_ON_CONNECTION*` یا RPC 422، sender آپلود invalidate می‌شود و با profile بعدی metadata یک retry کنترل‌شده انجام می‌شود

این retry محدود است تا loop نامحدود یا ارسال تکراری رخ ندهد؛ اتصال اصلی پیام‌ها، listener و login دست‌نخورده باقی می‌مانند.

## 8. entity resolution

کلید قابل‌اعتماد peer ID یا `@username` است. display name فقط وقتی cache می‌شود که یکتا باشد. جستجوی substring حذف شده است؛ نام دقیق تکراری با `SoroPyError` رد می‌شود تا پیام، ban یا promote روی peer اشتباه اجرا نشود.

## 9. dependency policy

نسخهٔ 1.3.6 از این بازه استفاده می‌کند:

```text
splusthon>=1.1.2,<1.1.3
```

دلیل:

- 1.1.0/1.1.1 cache کلاس‌سطحی aiohttp بین چند ConnectionWebSocket داشتند.
- 1.1.2 cache را per-instance کرد.
- 1.1.3 یک reconnect loop دوره‌ای 30 ثانیه‌ای اضافه کرد که task جدید می‌سازد و task قبلی/جدید را در disconnect با هم cancel می‌کند؛ تا رفع upstream برای soak و multi-account مناسب نیست.

قبل از تغییر این pin باید سناریوی دو اکانت و soak حداقل چند دقیقه‌ای اجرا شود.

## 10. capability matrix

| Method | Selenium | WebSocket / MTProto |
|---|:---:|:---:|
| `login` / session | ✅ | ✅ |
| `get_chats` | ✅ | ✅ |
| `send_message` / bulk | ✅ | ✅ |
| `reply` | DOM محدود | ✅ |
| group/channel send | ✅ | ✅ |
| realtime `new_message` | ❌ | ✅ |
| private-only auto-reply | poll | push + poll |
| `send_file` / `download_media` | ❌ | ✅ |
| edit/delete/pin/unpin | ❌ | ✅ |
| contacts/add/search | ✅ | ✅ |
| block/unblock/report | ❌ | ✅ |
| kick/ban/unban/promote | ❌ | ✅ |
| participants/permissions | ❌ | ✅ |
| no Chrome | ❌ | ✅ |
| multi-account | ✅ | ✅ |

متد unsupported روی Selenium باید `SoroPyError` واضح بدهد، نه traceback خام.

## 11. تست

تست‌های `soropy/tests/test_websocket_safety.py` بدون حساب واقعی این موارد را پوشش می‌دهند:

- phone normalization و placeholder rejection
- entity classification
- callback login بیرون event loop
- Unicode document upload و part size
- semantics صحیح ban و پارامترهای promote
- حذف stale unread
- رزرو auto-reply قبل از worker
- EventBus غیرمسدودکننده
- LoopRunner deadlock guard

ماتریس پیشنهادی تست پروژه Python 3.8، 3.11 و 3.12 است.

سناریوی پذیرش دستی با حساب آزمایشی:

1. session قدیمی را حذف کنید.
2. login و ورود SMS را بدون pending flood انجام دهید.
3. Listener و Auto-reply و PV-only روشن، Monitor خاموش باشد.
4. پیام PV بفرستید و `queued/delivered` را ببینید.
5. پیام گروه/کانال نباید جواب بگیرد.
6. فایل docx با path فارسی ویندوز ارسال شود.
7. add/search contact و عملیات moderation روی گروه آزمایشی بررسی شود.
8. `close()` بدون `Unclosed client session` پایان یابد.

## 12. امنیت و لایسنس

- فایل `.session` auth key حساس دارد؛ آن را منتشر نکنید.
- tracker و `manager_config.json` می‌توانند اطلاعات مخاطب/شماره داشته باشند و در `.gitignore` هستند.
- API id/hash وب عمومی‌اند، اما session هر کاربر محرمانه است.
- هستهٔ SoroPy MIT است.
- SPlusthon اختیاری و GPL-3.0 است؛ توزیع ترکیبی می‌تواند مشمول GPL باشد.

## 13. مثال‌های کاربردی

در نسخهٔ 1.3.6 یک مجموعهٔ مستقل از مثال‌های production-oriented برای WebSocket اضافه شده است:

| فایل | کاربرد |
|---|---|
| [`soropy/examples/websocket/group_moderator.py`](../soropy/examples/websocket/group_moderator.py) | مدیر گروه thread-safe با queue، ضدلینک، ضدواژه، ضد flood، ضد تکرار، state اتمیک و سه اخطار |
| [`soropy/examples/websocket/ai_assistant.py`](../soropy/examples/websocket/ai_assistant.py) | دستیار چندارائه‌دهنده‌ای AI با lazy import برای OpenAI، Gemini، Claude و Ollama |
| [`soropy/examples/websocket/capability_cookbook.py`](../soropy/examples/websocket/capability_cookbook.py) | cookbook کامل APIهای WebSocket، با جداسازی عملیات destructive از main |
| [`soropy/examples/websocket/support_desk_bot.py`](../soropy/examples/websocket/support_desk_bot.py) | میز پشتیبانی ticket-based؛ PV → ticket، اعلان به گروه اپراتورها، queue/worker و state اتمیک |
| [`soropy/examples/websocket/campaign_broadcaster.py`](../soropy/examples/websocket/campaign_broadcaster.py) | کمپین پیام‌رسانی امن؛ dry-run پیش‌فرض، CSV هدف، template و confirm=`YES` برای ارسال واقعی |
| [`soropy/examples/websocket/event_audit_logger.py`](../soropy/examples/websocket/event_audit_logger.py) | Audit logger JSONL برای eventهای realtime با sanitize فیلدهای حساس |
| [`soropy/examples/websocket/README.md`](../soropy/examples/websocket/README.md) | راهنمای فارسی نصب، env، امنیت، moderation، AI، پشتیبانی، کمپین و MultiAccount |

الگوی مشترک مثال‌های long-running:

1. `backend="websocket"`
2. handler فقط enqueue می‌کند تا EventBus block نشود
3. worker daemon پردازش می‌کند
4. state با tmp + `os.replace` و `RLock` نوشته می‌شود
5. `finally: bot.stop(); client.close()`

خلاصهٔ سریع این مجموعه در [`WEBSOCKET_EXAMPLES.md`](WEBSOCKET_EXAMPLES.md) آمده است.
اسکریپت انتشار امن‌تر: [`scripts/publish_pypi.py`](../scripts/publish_pypi.py) — نام پکیج همچنان `soropy` و extra نصب `soropy[ws]` است.
