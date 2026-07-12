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
from typing import Any, Callable, Dict, List, Optional, Tuple

from soropy.backends.websocket.events import IncomingMessage
from soropy.backends.websocket.loop_runner import LoopRunner
from soropy.exceptions import LoginError, SoroPyError, TransportError
from soropy.utils import get_logger, normalize_phone

logger = get_logger("soropy.ws.mtproto")

# Optional heavy dependency
try:
    from splusthon import SoroushClient as _SPClient  # type: ignore
    from splusthon import events as _sp_events  # type: ignore
    from splusthon.sessions import StringSession, SQLiteSession  # type: ignore
    from splusthon import functions as _sp_functions  # type: ignore
    from splusthon import types as _sp_types  # type: ignore
    from splusthon import utils as _sp_utils  # type: ignore

    _HAS_SPLUSTHON = True
except ImportError:  # pragma: no cover
    _SPClient = None  # type: ignore
    _sp_events = None  # type: ignore
    StringSession = None  # type: ignore
    SQLiteSession = None  # type: ignore
    _sp_functions = None  # type: ignore
    _sp_types = None  # type: ignore
    _sp_utils = None  # type: ignore
    _HAS_SPLUSTHON = False


# Soroush Plus public API credentials (same as official web client / SPlusthon)
SPLUS_API_ID = 1030400
SPLUS_API_HASH = "6edb16cf88714a4e9a805e928c39c937"
SPLUS_APP_VERSION = "3.9.2 A"
SPLUS_LANG = "fa"


def require_splusthon() -> None:
    if not _HAS_SPLUSTHON:
        raise TransportError(
            "MTProto WebSocket backend requires 'splusthon'. "
            "Install with:  pip install soropy[ws]   or   pip install splusthon"
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
        self._phone = normalize_phone(phone)
        self._session_dir = os.path.abspath(session_dir)
        os.makedirs(self._session_dir, exist_ok=True)
        self._on_message = on_message
        self._on_raw = on_raw
        self._api_id = api_id
        self._api_hash = api_hash

        self._runner = LoopRunner(name=f"mtproto-{self._phone[-4:]}")
        self._client: Any = None
        self._connected = False
        self._authorized = False
        # name → entity cache
        self._entity_cache: Dict[str, Any] = {}

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
        if not self._connected:
            self.connect()

        if self._authorized:
            return "session_restored"

        if code_callback is None:
            code_callback = lambda: input("🔑 Enter verification code: ")

        phone = self._phone

        async def _do_login():
            await self._client.send_code_request(phone)
            code = code_callback()
            if not code:
                raise LoginError("Empty verification code")
            try:
                await self._client.sign_in(phone=phone, code=str(code).strip())
            except Exception as exc:
                # 2FA password?
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
            raise LoginError(str(exc)) from exc

        self._authorized = True
        return "success"

    def disconnect(self) -> None:
        if self._client is not None and self._runner.is_running:
            try:
                self._runner.run(self._client.disconnect(), timeout=15)
            except Exception as exc:
                logger.debug("disconnect error: %s", exc)
        self._connected = False
        self._authorized = False
        self._client = None
        self._runner.stop()

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
        try:
            chat = await event.get_chat()
            if chat is not None:
                chat_name = (
                    getattr(chat, "title", None)
                    or " ".join(
                        p
                        for p in (
                            getattr(chat, "first_name", None),
                            getattr(chat, "last_name", None),
                        )
                        if p
                    )
                    or getattr(chat, "username", None)
                    or chat_id
                )
                if chat_name:
                    self._entity_cache[chat_name] = chat
        except Exception:
            chat_name = chat_id

        sender_id = ""
        sender_name = ""
        try:
            sender = await event.get_sender()
            if sender is not None:
                sender_id = str(getattr(sender, "id", "") or "")
                sender_name = (
                    " ".join(
                        p
                        for p in (
                            getattr(sender, "first_name", None),
                            getattr(sender, "last_name", None),
                        )
                        if p
                    )
                    or getattr(sender, "username", None)
                    or sender_id
                )
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
            kwargs = {}
            if reply_to:
                kwargs["reply_to"] = int(reply_to)
            result = await self._client.send_message(target, text, **kwargs)
            return {
                "id": getattr(result, "id", None),
                "chat_id": str(getattr(result, "chat_id", "") or entity),
            }

        return self._runner.run(_send(), timeout=30)

    def get_dialogs(self, limit: int = 100) -> List[Dict[str, Any]]:
        self._ensure()

        async def _dialogs():
            dialogs = await self._client.get_dialogs(limit=limit)
            out = []
            for d in dialogs:
                entity = d.entity
                name = (
                    getattr(entity, "title", None)
                    or " ".join(
                        p
                        for p in (
                            getattr(entity, "first_name", None),
                            getattr(entity, "last_name", None),
                        )
                        if p
                    )
                    or getattr(entity, "username", None)
                    or str(d.id)
                )
                kind = "personal"
                if getattr(entity, "broadcast", False):
                    kind = "channel"
                elif getattr(entity, "megagroup", False) or getattr(entity, "gigagroup", False):
                    kind = "group"
                elif hasattr(entity, "title") and not getattr(entity, "broadcast", False):
                    # Chat / group
                    if type(entity).__name__ in ("Chat", "Channel") and not getattr(
                        entity, "broadcast", False
                    ):
                        if getattr(entity, "megagroup", False) or type(entity).__name__ == "Chat":
                            kind = "group"
                        elif getattr(entity, "broadcast", False):
                            kind = "channel"
                self._entity_cache[name] = entity
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

    def get_contacts(self) -> List[Dict[str, Any]]:
        self._ensure()

        async def _contacts():
            result = await self._client(_sp_functions.contacts.GetContactsRequest(0))
            users = getattr(result, "users", []) or []
            out = []
            for u in users:
                name = " ".join(
                    p
                    for p in (
                        getattr(u, "first_name", None),
                        getattr(u, "last_name", None),
                    )
                    if p
                ) or getattr(u, "username", None) or str(u.id)
                phone = getattr(u, "phone", "") or ""
                self._entity_cache[name] = u
                out.append({"name": name, "phone": phone, "id": str(u.id)})
            return out

        return self._runner.run(_contacts(), timeout=30)

    def add_contact(self, phone: str, first_name: str, last_name: str = "") -> bool:
        self._ensure()
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

    # ── resolve helpers ────────────────────────────────

    async def _resolve(self, entity: str):
        if entity in self._entity_cache:
            return self._entity_cache[entity]
        # username
        if entity.startswith("@"):
            resolved = await self._client.get_entity(entity)
            self._entity_cache[entity] = resolved
            return resolved
        # numeric id
        if entity.lstrip("-").isdigit():
            resolved = await self._client.get_entity(int(entity))
            self._entity_cache[entity] = resolved
            return resolved
        # try as-is (phone / username without @)
        try:
            resolved = await self._client.get_entity(entity)
            self._entity_cache[entity] = resolved
            return resolved
        except Exception:
            pass
        # search dialogs by name
        dialogs = await self._client.get_dialogs(limit=200)
        for d in dialogs:
            ent = d.entity
            name = (
                getattr(ent, "title", None)
                or " ".join(
                    p
                    for p in (
                        getattr(ent, "first_name", None),
                        getattr(ent, "last_name", None),
                    )
                    if p
                )
                or ""
            )
            if name and (entity == name or entity in name):
                self._entity_cache[entity] = ent
                self._entity_cache[name] = ent
                return ent
        raise SoroPyError(f"Entity not found: {entity}")

    def _ensure(self) -> None:
        if not self._connected or self._client is None:
            raise SoroPyError("Not connected. Call login() first.")
        if not self._authorized:
            raise SoroPyError("Not authorized. Complete login first.")
