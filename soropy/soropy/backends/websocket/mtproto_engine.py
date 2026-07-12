"""
MTProto engine for Soroush Plus, powered by SPlusthon.

Soroush Plus uses a Telegram-compatible MTProto stack over
``wss://im-server.splus.ir:443/apiws`` (obfuscated abridged frames).

Rather than re-implementing RSA handshake, AES-IGE, TL schema, etc.
(thousands of lines), we adapt the battle-tested SPlusthon client and
expose a sync façade for :class:`WebSocketBackend`.
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from soropy.backends.websocket.events import IncomingMessage
from soropy.backends.websocket.loop_runner import LoopRunner
from soropy.exceptions import LoginError, SoroPyError, TransportError
from soropy.utils import get_logger, normalize_phone, validate_phone

logger = get_logger("soropy.ws.mtproto")

# Optional heavy dependency
try:
    from splusthon import SoroushClient as _SPClient  # type: ignore
    from splusthon import events as _sp_events  # type: ignore
    from splusthon.sessions import StringSession, SQLiteSession  # type: ignore
    from splusthon import functions as _sp_functions  # type: ignore
    from splusthon import types as _sp_types  # type: ignore
    from splusthon import utils as _sp_utils  # type: ignore
    from splusthon.tl.types import (  # type: ignore
        ChatBannedRights,
        ChatAdminRights,
        InputPeerUser,
        InputPeerChannel,
        InputPeerChat,
    )

    _HAS_SPLUSTHON = True
except ImportError:  # pragma: no cover
    _SPClient = None  # type: ignore
    _sp_events = None  # type: ignore
    StringSession = None  # type: ignore
    SQLiteSession = None  # type: ignore
    _sp_functions = None  # type: ignore
    _sp_types = None  # type: ignore
    _sp_utils = None  # type: ignore
    ChatBannedRights = None  # type: ignore
    ChatAdminRights = None  # type: ignore
    InputPeerUser = None  # type: ignore
    InputPeerChannel = None  # type: ignore
    InputPeerChat = None  # type: ignore
    _HAS_SPLUSTHON = False


# Soroush Plus public API credentials (same as official web client / SPlusthon)
SPLUS_API_ID = 1030400
SPLUS_API_HASH = "6edb16cf88714a4e9a805e928c39c937"
SPLUS_APP_VERSION = "3.9.2 A"
SPLUS_LANG = "fa"

# Report reason map (Soroush/Telegram style)
_REPORT_REASONS = {
    "spam": "InputReportReasonSpam",
    "violence": "InputReportReasonViolence",
    "porn": "InputReportReasonPornography",
    "copyright": "InputReportReasonCopyright",
    "other": "InputReportReasonOther",
    "geo": "InputReportReasonGeoIrrelevant",
    "fake": "InputReportReasonFake",
    "child": "InputReportReasonChildAbuse",
}


def require_splusthon() -> None:
    if not _HAS_SPLUSTHON:
        raise TransportError(
            "MTProto WebSocket backend requires 'splusthon'. "
            "Install with:  pip install soropy[ws]   or   pip install splusthon"
        )


def _entity_kind(entity: Any) -> str:
    """
    Classify a TL entity.

    Returns
    -------
    str
        ``\"personal\"`` | ``\"group\"`` | ``\"channel\"``
    """
    if entity is None:
        return "personal"

    name = type(entity).__name__

    # User / UserEmpty → personal
    if name in ("User", "UserEmpty") or (
        hasattr(entity, "first_name") and not hasattr(entity, "title")
    ):
        return "personal"

    # Channel with broadcast flag → channel
    if getattr(entity, "broadcast", False):
        return "channel"

    # megagroup / gigagroup / Chat → group
    if getattr(entity, "megagroup", False) or getattr(entity, "gigagroup", False):
        return "group"

    if name == "Chat":
        return "group"

    if name == "Channel":
        # Channel without broadcast is usually a supergroup
        return "group"

    if hasattr(entity, "title"):
        return "group"

    return "personal"


def _entity_display_name(entity: Any, fallback: str = "") -> str:
    if entity is None:
        return fallback
    title = getattr(entity, "title", None)
    if title:
        return title
    parts = [
        p
        for p in (
            getattr(entity, "first_name", None),
            getattr(entity, "last_name", None),
        )
        if p
    ]
    if parts:
        return " ".join(parts)
    username = getattr(entity, "username", None)
    if username:
        return username
    eid = getattr(entity, "id", None)
    return str(eid) if eid is not None else fallback


def _is_admin_error(exc: BaseException) -> bool:
    text = f"{type(exc).__name__}: {exc}".upper()
    return any(
        token in text
        for token in (
            "CHAT_ADMIN_REQUIRED",
            "CHAT_WRITE_FORBIDDEN",
            "CHAT_SEND",
            "USER_BANNED_IN_CHANNEL",
            "CHANNEL_PRIVATE",
            "CHAT_RESTRICTED",
            "RIGHT_FORBIDDEN",
            "ADMIN PRIVILEGES",
        )
    )


class MtprotoEngine:
    """
    Sync wrapper around SPlusthon's async :class:`SoroushClient`.

    Parameters
    ----------
    phone : str
        ``+98…`` phone number.
    session_dir : str
        Directory for SQLite session files.
    on_message : callable, optional
        ``on_message(IncomingMessage)`` invoked for every inbound message.
    on_raw : callable, optional
        ``on_raw(update)`` for advanced users.
    """

    def __init__(
        self,
        phone: str,
        session_dir: str = "soropy_ws_sessions",
        on_message: Optional[Callable[[IncomingMessage], None]] = None,
        on_raw: Optional[Callable[[Any], None]] = None,
        api_id: int = SPLUS_API_ID,
        api_hash: str = SPLUS_API_HASH,
    ):
        require_splusthon()
        # Soft-normalise here; hard validation happens at login()
        try:
            self._phone = validate_phone(phone)
        except ValueError:
            # Allow constructing with a session-path phone; login will re-validate
            self._phone = normalize_phone(phone) if phone else ""
        self._session_dir = os.path.abspath(session_dir)
        os.makedirs(self._session_dir, exist_ok=True)
        self._on_message = on_message
        self._on_raw = on_raw
        self._api_id = api_id
        self._api_hash = api_hash

        self._runner = LoopRunner(name=f"mtproto-{(self._phone or 'xx')[-4:]}")
        self._client: Any = None
        self._connected = False
        self._authorized = False
        # name → entity cache
        self._entity_cache: Dict[str, Any] = {}
        # chat_id → kind cache
        self._kind_cache: Dict[str, str] = {}

    # ── paths ──────────────────────────────────────────

    def _session_path(self) -> str:
        safe = self._phone.replace("+", "plus_")
        return os.path.join(self._session_dir, safe)

    def session_exists(self) -> bool:
        base = self._session_path()
        return os.path.isfile(base + ".session") or os.path.isfile(base)

    def delete_session(self) -> bool:
        removed = False
        base = self._session_path()
        for path in (base, base + ".session", base + ".session-journal"):
            if os.path.isfile(path):
                try:
                    os.remove(path)
                    removed = True
                except OSError:
                    pass
        return removed

    # ── lifecycle ──────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        return self._connected and self._client is not None

    @property
    def is_authorized(self) -> bool:
        return self._authorized

    @property
    def runner(self) -> LoopRunner:
        return self._runner

    def connect(self) -> None:
        require_splusthon()
        self._runner.start()
        session = SQLiteSession(self._session_path())
        self._client = _SPClient(
            session,
            self._api_id,
            self._api_hash,
            app_version=SPLUS_APP_VERSION,
            lang_code=SPLUS_LANG,
            system_lang_code=SPLUS_LANG,
        )
        self._runner.run(self._client.connect(), timeout=45)
        self._connected = True
        # Register event handler
        self._client.add_event_handler(
            self._handle_new_message,
            _sp_events.NewMessage(incoming=True),
        )
        try:
            authorized = self._runner.run(
                self._client.is_user_authorized(), timeout=20
            )
        except Exception as exc:
            logger.warning("is_user_authorized check failed: %s", exc)
            authorized = False
        self._authorized = bool(authorized)
        logger.info(
            "MTProto connected (authorized=%s) for %s",
            self._authorized,
            self._phone,
        )

    def login(self, code_callback: Optional[Callable[[], str]] = None) -> str:
        """
        Ensure the client is authorized.

        Returns
        -------
        str
            ``\"session_restored\"`` | ``\"success\"`` | ``\"already\"``
        """
        # Hard phone validation before any network call
        try:
            self._phone = validate_phone(self._phone)
        except ValueError as exc:
            raise LoginError(str(exc)) from exc

        if not self._connected:
            self.connect()

        if self._authorized:
            return "session_restored"

        if code_callback is None:
            code_callback = lambda: input("🔑 Enter verification code: ")

        phone = self._phone
        if not phone:
            raise LoginError(
                "شماره تلفن خالی/نامعتبر است. مثال: 09123456789"
            )

        async def _do_login():
            # send_code_request needs a non-empty phone string
            await self._client.send_code_request(phone)
            code = code_callback()
            if not code:
                raise LoginError("Empty verification code")
            try:
                await self._client.sign_in(phone=phone, code=str(code).strip())
            except Exception as exc:
                name = type(exc).__name__
                if "SessionPasswordNeeded" in name or "password" in str(exc).lower():
                    pwd = input("🔐 2FA password: ")
                    await self._client.sign_in(password=pwd)
                else:
                    raise LoginError(f"sign_in failed: {exc}") from exc
            return True

        try:
            self._runner.run(_do_login(), timeout=120)
        except LoginError:
            raise
        except Exception as exc:
            # Surface NoneType from bad phone clearly
            msg = str(exc)
            if "NoneType" in msg or "bytes or str expected" in msg:
                raise LoginError(
                    f"شماره نامعتبر یا پاسخ سرور خالی: {exc}. "
                    "شماره واقعی 11 رقمی ایرانی بدهید (0912…)."
                ) from exc
            raise LoginError(str(exc)) from exc

        self._authorized = True
        return "success"

    def disconnect(self) -> None:
        """Clean disconnect – close MTProto + aiohttp session, stop loop."""
        client = self._client
        runner = self._runner
        if client is not None and runner.is_running:
            try:
                # Prefer async disconnect on the loop
                runner.run(self._safe_disconnect(client), timeout=20)
            except Exception as exc:
                logger.debug("disconnect error: %s", exc)
                # Best-effort sync close if available
                try:
                    if hasattr(client, "session") and hasattr(client.session, "close"):
                        client.session.close()
                except Exception:
                    pass
        self._connected = False
        self._authorized = False
        self._client = None
        try:
            runner.stop(timeout=8.0)
        except Exception as exc:
            logger.debug("runner stop error: %s", exc)

    async def _safe_disconnect(self, client: Any) -> None:
        try:
            await client.disconnect()
        except Exception as exc:
            logger.debug("client.disconnect: %s", exc)
        # Extra cleanup for aiohttp ClientSession leftovers
        for attr in ("_sender", "session", "_connection"):
            obj = getattr(client, attr, None)
            if obj is None:
                continue
            close = getattr(obj, "close", None) or getattr(obj, "disconnect", None)
            if close is None:
                continue
            try:
                result = close()
                if hasattr(result, "__await__"):
                    await result
            except Exception:
                pass

    # ── events ─────────────────────────────────────────

    async def _handle_new_message(self, event) -> None:
        try:
            msg = await self._event_to_incoming(event)
            if msg and self._on_message:
                self._on_message(msg)
            if self._on_raw:
                self._on_raw(event)
        except Exception as exc:
            logger.error("new_message handler error: %s", exc)

    async def _event_to_incoming(self, event) -> Optional[IncomingMessage]:
        message = event.message
        if message is None:
            return None
        text = message.message or message.raw_text or ""
        chat_id = str(event.chat_id or getattr(message, "peer_id", "") or "")
        chat_name = ""
        is_private = False
        is_group = False
        is_channel = False
        try:
            chat = await event.get_chat()
            if chat is not None:
                chat_name = _entity_display_name(chat, chat_id)
                kind = _entity_kind(chat)
                is_private = kind == "personal"
                is_group = kind == "group"
                is_channel = kind == "channel"
                if chat_name:
                    self._entity_cache[chat_name] = chat
                if chat_id:
                    self._kind_cache[chat_id] = kind
                    self._kind_cache[chat_name] = kind
        except Exception:
            chat_name = chat_id
            # Heuristic from event flags when available
            try:
                if getattr(event, "is_private", False):
                    is_private = True
                elif getattr(event, "is_group", False) or getattr(event, "is_channel", False):
                    # Telethon: is_channel True for both channels & megagroups
                    if getattr(event, "is_group", False):
                        is_group = True
                    else:
                        is_channel = True
            except Exception:
                pass

        sender_id = ""
        sender_name = ""
        try:
            sender = await event.get_sender()
            if sender is not None:
                sender_id = str(getattr(sender, "id", "") or "")
                sender_name = _entity_display_name(sender, sender_id)
        except Exception:
            pass

        ts = time.time()
        date = getattr(message, "date", None)
        if date is not None and hasattr(date, "timestamp"):
            try:
                ts = float(date.timestamp())
            except Exception:
                pass

        return IncomingMessage(
            message_id=str(getattr(message, "id", "") or ""),
            chat_id=chat_id,
            chat_name=chat_name or chat_id,
            text=text,
            sender_id=sender_id,
            sender_name=sender_name,
            is_outgoing=bool(getattr(message, "out", False)),
            is_private=is_private,
            is_group=is_group,
            is_channel=is_channel,
            timestamp=ts,
            reply_to_id=str(
                getattr(getattr(message, "reply_to", None), "reply_to_msg_id", "")
                or ""
            ),
            raw={"id": getattr(message, "id", None), "chat_id": chat_id},
        )

    # ── messaging ──────────────────────────────────────

    def send_message(
        self,
        entity: str,
        text: str,
        reply_to: Optional[int] = None,
    ) -> Dict[str, Any]:
        self._ensure()

        async def _send():
            target = await self._resolve(entity)
            kwargs: Dict[str, Any] = {}
            if reply_to:
                kwargs["reply_to"] = int(reply_to)
            result = await self._client.send_message(target, text, **kwargs)
            return {
                "id": getattr(result, "id", None),
                "chat_id": str(getattr(result, "chat_id", "") or entity),
            }

        return self._runner.run(_send(), timeout=30)

    async def send_message_async(
        self,
        entity: str,
        text: str,
        reply_to: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Async send – safe to schedule from the loop thread via create_task."""
        self._ensure_connected()
        target = await self._resolve(entity)
        kwargs: Dict[str, Any] = {}
        if reply_to:
            kwargs["reply_to"] = int(reply_to)
        result = await self._client.send_message(target, text, **kwargs)
        return {
            "id": getattr(result, "id", None),
            "chat_id": str(getattr(result, "chat_id", "") or entity),
        }

    def schedule_send(
        self,
        entity: str,
        text: str,
        reply_to: Optional[int] = None,
        on_done: Optional[Callable[[bool, str], None]] = None,
    ) -> None:
        """
        Fire-and-forget send on the loop thread.

        Used by realtime auto-reply so the event handler never blocks
        on ``run_until_complete`` / ``run()``.
        """
        async def _task():
            try:
                await self.send_message_async(entity, text, reply_to=reply_to)
                if on_done:
                    on_done(True, "")
            except Exception as exc:
                if _is_admin_error(exc):
                    logger.debug(
                        "auto-reply soft-skip (no privilege) %s: %s", entity, exc
                    )
                else:
                    logger.warning("async send failed → %s: %s", entity, exc)
                if on_done:
                    on_done(False, str(exc))

        self._runner.create_task(_task())

    def send_file(
        self,
        entity: str,
        path: str,
        caption: str = "",
        force_document: bool = False,
        reply_to: Optional[int] = None,
    ) -> Dict[str, Any]:
        self._ensure()
        if not path or not os.path.isfile(path):
            raise SoroPyError(f"File not found: {path}")

        async def _send():
            target = await self._resolve(entity)
            kwargs: Dict[str, Any] = {
                "caption": caption or "",
                "force_document": force_document,
            }
            if reply_to:
                kwargs["reply_to"] = int(reply_to)
            result = await self._client.send_file(target, path, **kwargs)
            # send_file may return a list
            msg = result[0] if isinstance(result, list) and result else result
            return {
                "id": getattr(msg, "id", None),
                "chat_id": str(getattr(msg, "chat_id", "") or entity),
            }

        return self._runner.run(_send(), timeout=120)

    def download_media(
        self,
        entity: str,
        message_id: Union[int, str],
        file_path: Optional[str] = None,
    ) -> Optional[str]:
        self._ensure()

        async def _dl():
            target = await self._resolve(entity)
            mid = int(message_id)
            messages = await self._client.get_messages(target, ids=mid)
            msg = messages if not isinstance(messages, list) else (
                messages[0] if messages else None
            )
            if msg is None:
                raise SoroPyError(f"Message {message_id} not found in {entity}")
            path = await self._client.download_media(msg, file=file_path)
            return path

        return self._runner.run(_dl(), timeout=120)

    def delete_messages(
        self,
        entity: str,
        message_ids: Sequence[Union[int, str]],
        revoke: bool = True,
    ) -> bool:
        self._ensure()
        ids = [int(m) for m in message_ids]

        async def _del():
            target = await self._resolve(entity)
            await self._client.delete_messages(target, ids, revoke=revoke)
            return True

        try:
            return bool(self._runner.run(_del(), timeout=30))
        except Exception as exc:
            if _is_admin_error(exc):
                logger.debug("delete_messages privilege error: %s", exc)
            else:
                logger.error("delete_messages failed: %s", exc)
            return False

    def edit_message(
        self,
        entity: str,
        message_id: Union[int, str],
        text: str,
    ) -> bool:
        self._ensure()

        async def _edit():
            target = await self._resolve(entity)
            await self._client.edit_message(target, int(message_id), text)
            return True

        try:
            return bool(self._runner.run(_edit(), timeout=30))
        except Exception as exc:
            logger.error("edit_message failed: %s", exc)
            return False

    def pin_message(
        self,
        entity: str,
        message_id: Union[int, str],
        notify: bool = False,
    ) -> bool:
        self._ensure()

        async def _pin():
            target = await self._resolve(entity)
            await self._client.pin_message(
                target, int(message_id), notify=notify
            )
            return True

        try:
            return bool(self._runner.run(_pin(), timeout=30))
        except Exception as exc:
            logger.error("pin_message failed: %s", exc)
            return False

    def unpin_message(
        self,
        entity: str,
        message_id: Optional[Union[int, str]] = None,
    ) -> bool:
        self._ensure()

        async def _unpin():
            target = await self._resolve(entity)
            if message_id is None:
                # unpin all
                await self._client.pin_message(target, None)
            else:
                await self._client.pin_message(target, int(message_id), unpin=True)
            return True

        try:
            return bool(self._runner.run(_unpin(), timeout=30))
        except Exception as exc:
            # Fallback: EditPinnedMessagesRequest style
            try:
                async def _unpin2():
                    target = await self._resolve(entity)
                    if hasattr(self._client, "unpin_message"):
                        await self._client.unpin_message(target, message_id)
                    else:
                        await self._client.pin_message(target, None)
                    return True

                return bool(self._runner.run(_unpin2(), timeout=30))
            except Exception as exc2:
                logger.error("unpin_message failed: %s / %s", exc, exc2)
                return False

    # ── dialogs / history ──────────────────────────────

    def get_dialogs(self, limit: int = 100) -> List[Dict[str, Any]]:
        self._ensure()

        async def _dialogs():
            dialogs = await self._client.get_dialogs(limit=limit)
            out = []
            for d in dialogs:
                entity = d.entity
                name = _entity_display_name(entity, str(d.id))
                kind = _entity_kind(entity)
                self._entity_cache[name] = entity
                self._kind_cache[name] = kind
                self._kind_cache[str(d.id)] = kind
                out.append(
                    {
                        "name": name,
                        "id": str(d.id),
                        "type": kind,
                        "unread": int(getattr(d, "unread_count", 0) or 0),
                        "entity": entity,
                    }
                )
            return out

        return self._runner.run(_dialogs(), timeout=45)

    def get_messages(
        self,
        entity: str,
        limit: int = 20,
        incoming_only: bool = True,
    ) -> List[Dict[str, Any]]:
        self._ensure()

        async def _hist():
            target = await self._resolve(entity)
            messages = await self._client.get_messages(target, limit=limit)
            out = []
            for m in messages:
                if m is None:
                    continue
                is_out = bool(getattr(m, "out", False))
                if incoming_only and is_out:
                    continue
                text = m.message or m.raw_text or ""
                out.append(
                    {
                        "id": str(getattr(m, "id", "") or ""),
                        "text": text,
                        "is_outgoing": is_out,
                        "date": getattr(m, "date", None),
                    }
                )
            return list(reversed(out))  # oldest first

        return self._runner.run(_hist(), timeout=30)

    # ── contacts / user ops ────────────────────────────

    def get_contacts(self) -> List[Dict[str, Any]]:
        self._ensure()

        async def _contacts():
            result = await self._client(_sp_functions.contacts.GetContactsRequest(0))
            users = getattr(result, "users", []) or []
            out = []
            for u in users:
                name = _entity_display_name(u, str(u.id))
                phone = getattr(u, "phone", "") or ""
                self._entity_cache[name] = u
                self._kind_cache[name] = "personal"
                out.append({"name": name, "phone": phone, "id": str(u.id)})
            return out

        return self._runner.run(_contacts(), timeout=30)

    def add_contact(self, phone: str, first_name: str, last_name: str = "") -> bool:
        self._ensure()
        try:
            phone_n = validate_phone(phone).lstrip("+")
        except ValueError:
            phone_n = normalize_phone(phone).lstrip("+")

        async def _add():
            contact = _sp_types.InputPhoneContact(
                client_id=0,
                phone=phone_n,
                first_name=first_name,
                last_name=last_name or "",
            )
            result = await self._client(
                _sp_functions.contacts.ImportContactsRequest([contact])
            )
            imported = getattr(result, "imported", None) or []
            return len(imported) > 0

        try:
            return bool(self._runner.run(_add(), timeout=30))
        except Exception as exc:
            logger.error("add_contact failed: %s", exc)
            return False

    def block_user(self, user: str) -> bool:
        self._ensure()

        async def _block():
            target = await self._resolve(user)
            await self._client(_sp_functions.contacts.BlockRequest(target))
            return True

        try:
            return bool(self._runner.run(_block(), timeout=30))
        except Exception as exc:
            logger.error("block_user failed: %s", exc)
            return False

    def unblock_user(self, user: str) -> bool:
        self._ensure()

        async def _unblock():
            target = await self._resolve(user)
            await self._client(_sp_functions.contacts.UnblockRequest(target))
            return True

        try:
            return bool(self._runner.run(_unblock(), timeout=30))
        except Exception as exc:
            logger.error("unblock_user failed: %s", exc)
            return False

    def report(
        self,
        entity: str,
        reason: str = "spam",
        message: str = "",
    ) -> bool:
        self._ensure()
        reason_key = (reason or "spam").strip().lower()
        reason_cls_name = _REPORT_REASONS.get(reason_key, _REPORT_REASONS["spam"])

        async def _report():
            target = await self._resolve(entity)
            reason_cls = getattr(_sp_types, reason_cls_name, None)
            if reason_cls is None:
                # Fallback for older TL
                reason_obj = _sp_types.InputReportReasonSpam()
            else:
                reason_obj = reason_cls()
            await self._client(
                _sp_functions.account.ReportPeerRequest(
                    peer=target,
                    reason=reason_obj,
                    message=message or "",
                )
            )
            return True

        try:
            return bool(self._runner.run(_report(), timeout=30))
        except Exception as exc:
            logger.error("report failed: %s", exc)
            return False

    # ── moderation ─────────────────────────────────────

    def kick(self, chat: str, user: str) -> bool:
        """Kick (ban then unban) a user from a group/channel."""
        self._ensure()

        async def _kick():
            chat_ent = await self._resolve(chat)
            user_ent = await self._resolve(user)
            if hasattr(self._client, "kick_participant"):
                await self._client.kick_participant(chat_ent, user_ent)
            else:
                # ban then unban
                rights = ChatBannedRights(
                    until_date=None,
                    view_messages=True,
                )
                await self._client.edit_permissions(chat_ent, user_ent, rights)
                await self._client.edit_permissions(chat_ent, user_ent, view_messages=True)
                # actually unban
                await self._client.edit_permissions(chat_ent, user_ent)
            return True

        try:
            return bool(self._runner.run(_kick(), timeout=30))
        except Exception as exc:
            if _is_admin_error(exc):
                logger.warning("kick requires admin: %s", exc)
            else:
                logger.error("kick failed: %s", exc)
            return False

    def ban(
        self,
        chat: str,
        user: str,
        until_date: Optional[int] = None,
        **rights_kwargs,
    ) -> bool:
        self._ensure()

        async def _ban():
            chat_ent = await self._resolve(chat)
            user_ent = await self._resolve(user)
            # Default: fully ban (view_messages=True means banned in TL)
            kwargs = dict(rights_kwargs) if rights_kwargs else {"view_messages": True}
            if until_date is not None:
                kwargs["until_date"] = until_date
            await self._client.edit_permissions(chat_ent, user_ent, **kwargs)
            return True

        try:
            return bool(self._runner.run(_ban(), timeout=30))
        except Exception as exc:
            if _is_admin_error(exc):
                logger.warning("ban requires admin: %s", exc)
            else:
                logger.error("ban failed: %s", exc)
            return False

    def unban(self, chat: str, user: str) -> bool:
        self._ensure()

        async def _unban():
            chat_ent = await self._resolve(chat)
            user_ent = await self._resolve(user)
            # Empty rights = unrestricted
            await self._client.edit_permissions(chat_ent, user_ent)
            return True

        try:
            return bool(self._runner.run(_unban(), timeout=30))
        except Exception as exc:
            if _is_admin_error(exc):
                logger.warning("unban requires admin: %s", exc)
            else:
                logger.error("unban failed: %s", exc)
            return False

    def set_permissions(
        self,
        chat: str,
        user: Optional[str] = None,
        **rights,
    ) -> bool:
        """
        Set banned/restricted rights on a user (or default chat rights).

        ``**rights`` are keyword args accepted by Telethon/SPlusthon
        ``edit_permissions`` (e.g. ``send_messages=False``).
        """
        self._ensure()

        async def _perm():
            chat_ent = await self._resolve(chat)
            user_ent = await self._resolve(user) if user else None
            if user_ent is not None:
                await self._client.edit_permissions(chat_ent, user_ent, **rights)
            else:
                await self._client.edit_permissions(chat_ent, **rights)
            return True

        try:
            return bool(self._runner.run(_perm(), timeout=30))
        except Exception as exc:
            if _is_admin_error(exc):
                logger.warning("set_permissions requires admin: %s", exc)
            else:
                logger.error("set_permissions failed: %s", exc)
            return False

    def promote(self, chat: str, user: str, **admin_rights) -> bool:
        """
        Promote a user to admin.

        ``**admin_rights`` map to ChatAdminRights fields
        (e.g. ``delete_messages=True, ban_users=True``).
        """
        self._ensure()

        async def _promote():
            chat_ent = await self._resolve(chat)
            user_ent = await self._resolve(user)
            # Defaults: common moderate rights
            defaults = {
                "change_info": admin_rights.get("change_info", False),
                "post_messages": admin_rights.get("post_messages", False),
                "edit_messages": admin_rights.get("edit_messages", False),
                "delete_messages": admin_rights.get("delete_messages", True),
                "ban_users": admin_rights.get("ban_users", True),
                "invite_users": admin_rights.get("invite_users", True),
                "pin_messages": admin_rights.get("pin_messages", True),
                "add_admins": admin_rights.get("add_admins", False),
                "anonymous": admin_rights.get("anonymous", False),
                "manage_call": admin_rights.get("manage_call", False),
                "other": admin_rights.get("other", True),
            }
            # Merge any extra keys
            for k, v in admin_rights.items():
                if k not in defaults:
                    defaults[k] = v
            if hasattr(self._client, "edit_admin"):
                await self._client.edit_admin(chat_ent, user_ent, **defaults)
            else:
                rights = ChatAdminRights(**{
                    k: v for k, v in defaults.items()
                    if k in ChatAdminRights.__annotations__
                    or True  # best effort
                })
                await self._client(
                    _sp_functions.channels.EditAdminRequest(
                        channel=chat_ent,
                        user_id=user_ent,
                        admin_rights=rights,
                        rank=admin_rights.get("rank", "admin"),
                    )
                )
            return True

        try:
            return bool(self._runner.run(_promote(), timeout=30))
        except Exception as exc:
            if _is_admin_error(exc):
                logger.warning("promote requires admin: %s", exc)
            else:
                logger.error("promote failed: %s", exc)
            return False

    def get_participants(self, chat: str, limit: int = 100) -> List[Dict[str, Any]]:
        self._ensure()

        async def _parts():
            target = await self._resolve(chat)
            participants = await self._client.get_participants(target, limit=limit)
            out = []
            for u in participants:
                name = _entity_display_name(u, str(getattr(u, "id", "")))
                out.append(
                    {
                        "id": str(getattr(u, "id", "")),
                        "name": name,
                        "username": getattr(u, "username", None) or "",
                        "phone": getattr(u, "phone", None) or "",
                    }
                )
                self._entity_cache[name] = u
            return out

        try:
            return self._runner.run(_parts(), timeout=60)
        except Exception as exc:
            logger.error("get_participants failed: %s", exc)
            return []

    def get_permissions(
        self,
        chat: str,
        user: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        self._ensure()

        async def _perms():
            chat_ent = await self._resolve(chat)
            if user:
                user_ent = await self._resolve(user)
                perms = await self._client.get_permissions(chat_ent, user_ent)
            else:
                perms = await self._client.get_permissions(chat_ent)
            if perms is None:
                return None
            # Convert common attributes to a plain dict
            data: Dict[str, Any] = {}
            for attr in (
                "is_admin",
                "is_banned",
                "is_creator",
                "can_post_messages",
                "can_edit_messages",
                "can_delete_messages",
                "can_ban_users",
                "can_invite_users",
                "can_pin_messages",
                "can_add_admins",
                "can_send_messages",
                "can_send_media",
                "can_send_stickers",
                "can_send_gifs",
                "can_send_games",
                "can_send_inline",
                "can_view_messages",
                "can_change_info",
            ):
                if hasattr(perms, attr):
                    data[attr] = getattr(perms, attr)
            return data

        try:
            return self._runner.run(_perms(), timeout=30)
        except Exception as exc:
            logger.error("get_permissions failed: %s", exc)
            return None

    def get_me(self) -> Optional[Dict[str, Any]]:
        self._ensure()

        async def _me():
            me = await self._client.get_me()
            if me is None:
                return None
            return {
                "id": str(me.id),
                "phone": getattr(me, "phone", ""),
                "first_name": getattr(me, "first_name", ""),
                "last_name": getattr(me, "last_name", ""),
                "username": getattr(me, "username", ""),
            }

        try:
            return self._runner.run(_me(), timeout=20)
        except Exception as exc:
            logger.warning("get_me failed: %s", exc)
            return None

    def mark_read(self, entity: str) -> bool:
        self._ensure()

        async def _read():
            target = await self._resolve(entity)
            await self._client.send_read_acknowledge(target)
            return True

        try:
            return bool(self._runner.run(_read(), timeout=20))
        except Exception as exc:
            logger.debug("mark_read failed: %s", exc)
            return False

    def chat_kind(self, name_or_id: str) -> Optional[str]:
        """Return cached kind for a chat name/id if known."""
        return self._kind_cache.get(name_or_id)

    # ── resolve helpers ────────────────────────────────

    async def _resolve(self, entity: str):
        if entity in self._entity_cache:
            return self._entity_cache[entity]
        # username
        if entity.startswith("@"):
            resolved = await self._client.get_entity(entity)
            self._entity_cache[entity] = resolved
            self._kind_cache[entity] = _entity_kind(resolved)
            return resolved
        # numeric id
        if entity.lstrip("-").isdigit():
            resolved = await self._client.get_entity(int(entity))
            self._entity_cache[entity] = resolved
            self._kind_cache[entity] = _entity_kind(resolved)
            return resolved
        # try as-is (phone / username without @)
        try:
            resolved = await self._client.get_entity(entity)
            self._entity_cache[entity] = resolved
            self._kind_cache[entity] = _entity_kind(resolved)
            return resolved
        except Exception:
            pass
        # search dialogs by name
        dialogs = await self._client.get_dialogs(limit=200)
        for d in dialogs:
            ent = d.entity
            name = _entity_display_name(ent, "")
            kind = _entity_kind(ent)
            if name:
                self._entity_cache[name] = ent
                self._kind_cache[name] = kind
            if name and (entity == name or entity in name):
                self._entity_cache[entity] = ent
                self._kind_cache[entity] = kind
                return ent
        raise SoroPyError(f"Entity not found: {entity}")

    def _ensure(self) -> None:
        if not self._connected or self._client is None:
            raise SoroPyError("Not connected. Call login() first.")
        if not self._authorized:
            raise SoroPyError("Not authorized. Complete login first.")

    def _ensure_connected(self) -> None:
        if not self._connected or self._client is None:
            raise SoroPyError("Not connected. Call login() first.")
