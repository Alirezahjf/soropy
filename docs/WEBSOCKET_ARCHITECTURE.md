# SoroPy WebSocket / MTProto Architecture

> **Status:** Production-ready transport via SPlusthon (MTProto over WSS)  
> **Endpoint:** `wss://im-server.splus.ir:443/apiws`

---

## 1. What the real protocol is

Soroush Plus is **not** a custom JSON chat protocol.  
The official web client (`web.splus.ir`) uses a **Telegram-compatible MTProto** stack:

| Layer | Detail |
|--|--|
| Transport | WebSocket binary frames |
| URL | `wss://im-server.splus.ir:443/apiws` |
| Origin header | `https://web.splus.ir` |
| Packet codec | Obfuscated + abridged MTProto |
| Schema | TL layer ~182 (Soroush-specific RSA keys / DCs) |
| API id / hash | `1030400` / `6edb16cf88714a4e9a805e928c39c937` (public web client) |

Re-implementing MTProto from scratch is unnecessary. SoroPy adapts
**[SPlusthon](https://github.com/shayanheidari01/SPlusthon)** (GPL-3.0 Telethon fork)
behind the existing `BaseBackend` interface.

---

## 2. Architecture

```
SoroushClient (sync public API)
    └── WebSocketBackend
            ├── EventBus                  (new_message, connected, …)
            ├── MtprotoEngine             (sync façade)
            │       ├── LoopRunner        (background asyncio thread)
            │       └── splusthon.SoroushClient
            │               └── ConnectionWebSocket
            │                       └── wss://im-server.splus.ir/apiws
            └── SQLite session files      (soropy_ws_sessions/)
```

Selenium backend is unchanged and remains the default.

---

## 3. Install

```bash
pip install soropy[ws]
# pulls: splusthon, aiohttp, pyaes, rsa
```

---

## 4. Usage

```python
from soropy import SoroushClient

client = SoroushClient("09123456789", backend="websocket")

def on_msg(event):
    d = event.data
    print(f"← {d['chat_name']}: {d['text']}")

client.on("new_message", on_msg)

status = client.login()          # SMS code on first run; session next time
print(status)

chats = client.get_chats()
print(chats.personal[:5])

client.send_message("علی", "سلام از MTProto!")

client.add_reply_rule("سلام", "علیک سلام 👋")
client.start_monitor(interval=60)   # safety poll; realtime already active
```

### Multi-account

```python
from soropy import MultiAccountManager

with MultiAccountManager(backend="websocket") as mgr:
    mgr.add_account("0912...")
    mgr.add_account("0918...")
    mgr.login_all()
    mgr.start_all_monitors(interval=60)
```

---

## 5. Session files

| Backend | Location | Format |
|--|--|--|
| Selenium | `soropy_sessions/plus_98…/` | Chrome profile |
| WebSocket | `soropy_ws_sessions/plus_98….session` | SQLite (auth key + DC) |

Delete with `client.delete_session()`.

---

## 6. Events

| Event | Payload highlights |
|--|--|
| `connecting` / `connected` / `disconnected` | lifecycle |
| `auth_success` / `auth_failed` | login |
| `new_message` | `message_id`, `chat_id`, `chat_name`, `text`, `sender_*` |
| `message_sent` | outbound confirm |
| `chat_updated` | lists after `get_chats` |
| `unread_changed` | badge counters |
| `error` | transport / protocol errors |

Realtime auto-reply: if rules are configured, `SoroushClient` replies on
`new_message` without waiting for the poll loop.

---

## 7. Capability matrix

| Method | Selenium | WebSocket/MTProto |
|--|:--:|:--:|
| `login` | ✅ UI | ✅ SMS / session |
| `send_message` | ✅ | ✅ |
| `get_chats` | ✅ | ✅ dialogs |
| `get_contacts` / `add_contact` | ✅ | ✅ |
| `send_to_channel` | ✅ | ✅ |
| `check_and_reply` / `start_monitor` | ✅ poll | ✅ poll + **push** |
| `on("new_message")` | ❌ | ✅ |
| no Chrome required | ❌ | ✅ |

---

## 8. Module map

| File | Role |
|--|--|
| `backends/base.py` | abstract contract |
| `backends/selenium_backend.py` | DOM automation |
| `backends/websocket/backend.py` | BaseBackend impl |
| `backends/websocket/mtproto_engine.py` | SPlusthon adapter |
| `backends/websocket/loop_runner.py` | background asyncio loop |
| `backends/websocket/events.py` | EventBus + IncomingMessage |
| `backends/websocket/protocol.py` | legacy provisional JSON (kept for experiments) |
| `backends/websocket/transport.py` | legacy raw WS (kept for experiments) |
| `backends/websocket/auth.py` / `session.py` | legacy token store (superseded by SQLite) |

---

## 9. Licensing note

SPlusthon is **GPL-3.0**. When you install `soropy[ws]`, the combined
work that ships the MTProto engine is subject to GPL-3.0 obligations
for distribution. The core SoroPy package (Selenium-only, MIT) remains
usable without the optional extra.

---

## 10. Troubleshooting

| Symptom | Fix |
|--|--|
| `TransportError: … requires 'splusthon'` | `pip install soropy[ws]` |
| `MTProto connect failed` | check access to `im-server.splus.ir:443` (VPN/DNS) |
| SMS not arriving | wait / retry; Soroush rate-limits code requests |
| Session invalid | `client.delete_session()` then login again |
| 2FA password | engine prompts on `SessionPasswordNeeded` |

---

## 11. Why not pure reverse-engineering?

A clean-room MTProto client is months of work (RSA fingerprints, AES-IGE,
msg_id, salt, TL codegen, updates state machine…). SPlusthon already
contains the Soroush-specific patches. SoroPy focuses on a **stable,
simple public API** and dual backends instead of re-doing crypto.
