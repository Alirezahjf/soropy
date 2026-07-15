"""
MTProto engine for Soroush Plus, powered by SPlusthon.

Soroush Plus uses a Telegram-compatible MTProto stack over
``wss://im-server.splus.ir:443/apiws`` (obfuscated abridged frames).

Rather than re-implementing RSA handshake, AES-IGE, TL schema, etc.
(thousands of lines), we adapt the battle-tested SPlusthon client and
expose a sync façade for :class:`WebSocketBackend`.
"""

from __future__ import annotations

import io
import inspect
import os
import re
import time
import unicodedata
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


def _is_auth_key_error(exc: BaseException) -> bool:
    """True for stale/unknown MTProto authorization-key failures."""
    text = f"{type(exc).__name__}: {exc}".upper()
    return any(
        token in text
        for token in (
            "AUTHKEYNOTFOUND",
            "AUTH_KEY_UNREGISTERED",
            "AUTH KEY UNREGISTERED",
            "KEY IS NOT REGISTERED",
            "AUTH_KEY_INVALID",
        )
    )


def _is_password_needed(exc: BaseException) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return "sessionpasswordneeded" in text or "password is needed" in text


def _is_upload_connection_error(exc: BaseException) -> bool:
    text = f"{type(exc).__name__}: {exc}".upper()
    return "FILE_REQUEST_RECEIVED_ON_CONNECTION" in text or "RPCERROR 422" in text


def _ascii_upload_name(path: str) -> str:
    """Return an ASCII-safe filename while preserving the original extension."""
    original = os.path.basename(path) or "upload.bin"
    stem, extension = os.path.splitext(original)
    normalized = unicodedata.normalize("NFKD", stem)
    stem_ascii = normalized.encode("ascii", "ignore").decode("ascii")
    stem_ascii = re.sub(r"[^A-Za-z0-9._-]+", "_", stem_ascii).strip("._-")
    extension_ascii = re.sub(r"[^A-Za-z0-9.]", "", extension).lower()
    if not stem_ascii:
        stem_ascii = "upload"
    if not extension_ascii or extension_ascii == ".":
        extension_ascii = ".bin"
    return f"{stem_ascii}{extension_ascii}"


_IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff",
}


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
        # entity aliases → entity. Display names are removed when ambiguous.
        self._entity_cache: Dict[str, Any] = {}
        self._ambiguous_names = set()
        # chat id/name → personal|group|channel
        self._kind_cache: Dict[str, str] = {}
        # Dedicated MTProto sender for file uploads (init with upload params
        # so the server treats this connection as an upload connection and
        # accepts SaveFilePartRequest instead of rejecting it with
        # FILE_REQUEST_RECEIVED_ON_CONNECTION_SERVER / RPCError 422).
        self._upload_sender: Any = None

    def _remember_entity(
        self,
        name: str,
        entity: Any,
        kind: Optional[str] = None,
        entity_id: Optional[str] = None,
    ) -> None:
        """Cache safe aliases without silently overwriting duplicate names."""
        kind = kind or _entity_kind(entity)
        intrinsic_id = str(getattr(entity, "id", "") or "")
        raw_id = str(entity_id or intrinsic_id)
        if raw_id:
            self._entity_cache[raw_id] = entity
            self._kind_cache[raw_id] = kind
        if intrinsic_id and intrinsic_id != raw_id:
            self._entity_cache[intrinsic_id] = entity
            self._kind_cache[intrinsic_id] = kind
        username = str(getattr(entity, "username", "") or "")
        if username:
            self._entity_cache["@" + username.lstrip("@")] = entity
            self._kind_cache["@" + username.lstrip("@")] = kind
        if not name:
            return
        previous = self._entity_cache.get(name)
        previous_id = str(getattr(previous, "id", "") or "") if previous else ""
        if (
            previous is not None
            and intrinsic_id
            and previous_id
            and previous_id != intrinsic_id
        ):
            self._entity_cache.pop(name, None)
            self._kind_cache.pop(name, None)
            self._ambiguous_names.add(name)
            return
        if name not in self._ambiguous_names:
            self._entity_cache[name] = entity
            self._kind_cache[name] = kind

    # ── paths ──────────────────────────────────────────

    def _session_path(self) -> str:
        safe = self._phone.replace("+", "plus_")
        return os.path.join(self._session_dir, safe)

    def session_exists(self) -> bool:
        base = self._session_path()
        return os.path.isfile(base + ".session") or os.path.isfile(base)

    def delete_session(self) -> bool:
        """Delete the SQLite session and all common sidecar files."""
        removed = False
        base = self._session_path()
        paths = (
            base,
            base + ".session",
            base + ".session-journal",
            base + ".session-wal",
            base + ".session-shm",
            base + "-journal",
            base + "-wal",
            base + "-shm",
        )
        for path in paths:
            if os.path.isfile(path):
                try:
                    os.remove(path)
                    removed = True
                except OSError as exc:
                    logger.warning("Cannot delete session file %s: %s", path, exc)
        return removed

    # ── lifecycle ──────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        if not self._connected or self._client is None:
            return False
        checker = getattr(self._client, "is_connected", None)
        if callable(checker):
            try:
                return bool(checker())
            except Exception:
                return False
        return True

    @property
    def is_authorized(self) -> bool:
        return self._authorized

    @property
    def runner(self) -> LoopRunner:
        return self._runner

    def _make_client(self) -> Any:
        session = SQLiteSession(self._session_path())
        return _SPClient(
            session,
            self._api_id,
            self._api_hash,
            app_version=SPLUS_APP_VERSION,
            lang_code=SPLUS_LANG,
            system_lang_code=SPLUS_LANG,
            base_logger=logger,
            auto_reconnect=True,
        )

    def connect(self) -> None:
        """Open MTProto and repair one stale auth-key session automatically."""
        require_splusthon()
        if self.is_connected:
            return

        last_error: Optional[BaseException] = None
        for attempt in range(2):
            try:
                self._runner.start()
                self._client = self._make_client()
                self._runner.run(self._client.connect(), timeout=45)
                self._connected = True
                self._client.add_event_handler(
                    self._handle_new_message,
                    _sp_events.NewMessage(incoming=True),
                )
                try:
                    authorized = self._runner.run(
                        self._client.is_user_authorized(), timeout=20
                    )
                except Exception as exc:
                    if _is_auth_key_error(exc):
                        raise
                    logger.warning("is_user_authorized check failed: %s", exc)
                    authorized = False
                self._authorized = bool(authorized)
                for session_file in (
                    self._session_path(), self._session_path() + ".session"
                ):
                    if os.path.isfile(session_file):
                        try:
                            os.chmod(session_file, 0o600)
                        except OSError:
                            pass  # Windows ACLs/unsupported filesystems
                logger.info(
                    "MTProto connected (authorized=%s) for %s",
                    self._authorized,
                    self._phone,
                )
                return
            except Exception as exc:
                last_error = exc
                stale_key = _is_auth_key_error(exc)
                logger.warning("MTProto connect attempt %d failed: %s", attempt + 1, exc)
                self.disconnect()
                if stale_key and attempt == 0:
                    removed = self.delete_session()
                    logger.warning(
                        "Invalid MTProto auth key; session reset (removed=%s), retrying",
                        removed,
                    )
                    continue
                break

        raise TransportError(f"MTProto connect failed: {last_error}") from last_error

    def _reset_invalid_session(self) -> None:
        """Close the old transport, remove its key, then create a fresh client."""
        self.disconnect()
        self.delete_session()
        self.connect()

    def _ensure_transport_connected(self) -> None:
        if self.is_connected:
            return
        if self._client is None or not self._runner.is_running:
            self.connect()
            return

        logger.warning("MTProto dropped while waiting for credentials; reconnecting")
        self._runner.run(self._client.connect(), timeout=45)
        self._connected = True

    def login(
        self,
        code_callback: Optional[Callable[[], str]] = None,
        password_callback: Optional[Callable[[], str]] = None,
    ) -> str:
        """Authorize without ever blocking the asyncio/WebSocket loop.

        Network operations run on :class:`LoopRunner`; code and 2FA callbacks
        deliberately run on the caller thread between those short async phases.
        """
        try:
            self._phone = validate_phone(self._phone)
        except ValueError as exc:
            raise LoginError(str(exc)) from exc

        if not self.is_connected:
            self.connect()
        if self._authorized:
            return "session_restored"

        if code_callback is None:
            def code_callback() -> str:
                return input("🔑 Enter verification code: ")
        if password_callback is None:
            def password_callback() -> str:
                return input("🔐 2FA password: ")

        phone = self._phone
        if not phone:
            raise LoginError("شماره تلفن خالی/نامعتبر است. مثال: 09123456789")

        last_error: Optional[BaseException] = None
        for auth_attempt in range(2):
            try:
                # Phase 1: a short network operation on the asyncio thread.
                async def _request_code():
                    return await self._client.send_code_request(phone)

                self._runner.run(_request_code(), timeout=45)

                # Phase 2: caller/UI thread. Never move this into a coroutine.
                code = code_callback()
                code = str(code or "").strip()
                if not code:
                    raise LoginError("Empty verification code")

                # Phase 3: the user may have taken a while; repair a dropped WS.
                self._ensure_transport_connected()

                # Phase 4: another short network operation on the asyncio thread.
                async def _sign_in_code():
                    return await self._client.sign_in(phone=phone, code=code)

                try:
                    self._runner.run(_sign_in_code(), timeout=60)
                except Exception as exc:
                    if not _is_password_needed(exc):
                        raise
                    # 2FA input also belongs to the caller thread.
                    password = str(password_callback() or "")
                    if not password:
                        raise LoginError("Empty 2FA password")
                    self._ensure_transport_connected()

                    async def _sign_in_password():
                        return await self._client.sign_in(password=password)

                    self._runner.run(_sign_in_password(), timeout=60)

                async def _authorized_check():
                    return await self._client.is_user_authorized()

                if not self._runner.run(_authorized_check(), timeout=20):
                    raise LoginError("Server did not authorize this session")
                self._authorized = True
                return "success"
            except LoginError:
                raise
            except Exception as exc:
                last_error = exc
                if _is_auth_key_error(exc) and auth_attempt == 0:
                    logger.warning("Auth key is not registered; rebuilding session once")
                    self._reset_invalid_session()
                    if self._authorized:
                        return "session_restored"
                    continue
                msg = str(exc)
                if "NoneType" in msg or "bytes or str expected" in msg:
                    raise LoginError(
                        f"شماره نامعتبر یا پاسخ سرور خالی: {exc}. "
                        "شماره واقعی 11 رقمی ایرانی بدهید (0912…)."
                    ) from exc
                raise LoginError(f"sign_in failed: {exc}") from exc

        raise LoginError(str(last_error or "Login failed")) from last_error

    def disconnect(self) -> None:
        """Idempotently close MTProto, nested aiohttp sessions and the loop."""
        # Close the dedicated upload sender first
        upload_sender = self._upload_sender
        self._upload_sender = None

        client = self._client
        runner = self._runner
        self._connected = False
        self._authorized = False
        self._client = None

        if upload_sender is not None and runner.is_running:
            try:
                # Also close any aiohttp sessions owned by the upload sender's
                # WebSocket connection to prevent "Unclosed client session" leaks.
                async def _close_upload_sender():
                    try:
                        await upload_sender.disconnect()
                    except Exception as exc:
                        logger.debug("upload sender disconnect: %s", exc)
                    # Close the WebSocket connection's cached aiohttp session
                    conn = getattr(upload_sender, "_connection", None)
                    if conn is not None:
                        cached = getattr(conn, "_cached_session", None)
                        if cached is not None and not bool(getattr(cached, "closed", False)):
                            try:
                                await cached.close()
                            except Exception:
                                pass
                        session = getattr(conn, "_session", None)
                        if session is not None and session is not cached and not bool(getattr(session, "closed", False)):
                            try:
                                await session.close()
                            except Exception:
                                pass

                runner.run(_close_upload_sender(), timeout=10)
            except Exception as exc:
                logger.debug("upload sender cleanup error: %s", exc)

        if client is not None and runner.is_running:
            if runner.in_loop_thread():
                async def _shutdown_from_loop():
                    try:
                        await self._safe_disconnect(client)
                    finally:
                        runner.stop(timeout=0)

                runner.create_task(_shutdown_from_loop())
                return
            try:
                runner.run(self._safe_disconnect(client), timeout=25)
            except Exception as exc:
                logger.debug("disconnect error: %s", exc)
        try:
            runner.stop(timeout=8.0)
        except Exception as exc:
            logger.debug("runner stop error: %s", exc)

    async def _safe_disconnect(self, client: Any) -> None:
        try:
            result = client.disconnect()
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            logger.debug("client.disconnect: %s", exc)

        # SPlusthon versions have stored aiohttp sessions at different depths.
        # Close only session-like objects here; do not disconnect the sender twice.
        seen = set()
        queue = [client]
        for _ in range(5):
            next_queue = []
            for parent in queue:
                if parent is None or id(parent) in seen:
                    continue
                seen.add(id(parent))
                for attr in (
                    "_sender", "_connection", "connection", "_session",
                    "_cached_session", "session", "_borrowed_senders",
                ):
                    child = getattr(parent, attr, None)
                    if child is not None and id(child) not in seen:
                        if isinstance(child, dict):
                            for v in child.values():
                                v_child = v[-1] if isinstance(v, tuple) else v
                                if v_child is not None and id(v_child) not in seen:
                                    next_queue.append(v_child)
                        elif isinstance(child, (list, tuple, set)):
                            for v in child:
                                if v is not None and id(v) not in seen:
                                    next_queue.append(v)
                        else:
                            next_queue.append(child)
                module = type(parent).__module__.lower()
                is_http_session = "aiohttp" in module or hasattr(parent, "ws_connect")
                if is_http_session and not bool(getattr(parent, "closed", False)):
                    close = getattr(parent, "close", None)
                    if close:
                        try:
                            result = close()
                            if inspect.isawaitable(result):
                                await result
                        except Exception as exc:
                            logger.debug("nested session close: %s", exc)
            queue = next_queue

        # Finally flush/close the SQLite session when supported.
        session = getattr(client, "session", None)
        close = getattr(session, "close", None)
        if close:
            try:
                result = close()
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                logger.debug("SQLite session close: %s", exc)

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
                self._remember_entity(chat_name, chat, kind=kind, entity_id=chat_id)
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

    # ── upload connection ──────────────────────────────

    async def _ensure_upload_sender(self) -> Any:
        """Create (or return) a dedicated MTProto sender for file uploads.

        The Soroush Plus server requires ``upload.SaveFilePartRequest`` to be
        sent on a connection that was initialized with
        ``params={"connection": "upload"}`` in the ``InitConnectionRequest``.
        Without this flag the server returns
        ``FILE_REQUEST_RECEIVED_ON_CONNECTION_SERVER`` (RPCError 422).

        This method lazily creates a second WebSocket/MTProto connection to
        the same DC, re-uses the existing auth key (no re-login needed), and
        keeps the sender alive for reuse across multiple uploads.
        """
        if self._upload_sender is not None and self._upload_sender.is_connected():
            return self._upload_sender

        await self._invalidate_upload_sender()

        from splusthon.network import MTProtoSender, ConnectionWebSocket  # type: ignore
        from splusthon.tl.alltlobjects import LAYER  # type: ignore

        client = self._client
        if client is None:
            raise TransportError("Cannot create upload sender: no main client")

        # Build the upload-specific InitConnectionRequest.
        # The ``params`` field tells the server this connection is for file
        # uploads, so it accepts SaveFilePartRequest / SaveBigFilePartRequest.
        upload_params = _sp_types.JsonObject(value=[
            _sp_types.JsonObjectValue(
                key="connection",
                value=_sp_types.JsonString(value="upload"),
            ),
        ])

        # Read init-request parameters from the main client.  Guard against
        # test fakes that may not have the full SPlusthon attribute set.
        init_req = getattr(client, "_init_request", None)
        if init_req is None:
            raise TransportError(
                "Cannot create upload sender: client has no _init_request"
            )

        init_request = _sp_functions.InitConnectionRequest(
            api_id=getattr(client, "api_id", SPLUS_API_ID),
            device_model=getattr(init_req, "device_model", "SoroPy"),
            system_version=getattr(init_req, "system_version", "1.0"),
            app_version=getattr(init_req, "app_version", SPLUS_APP_VERSION),
            lang_code=getattr(init_req, "lang_code", SPLUS_LANG),
            system_lang_code=getattr(init_req, "system_lang_code", SPLUS_LANG),
            lang_pack=getattr(init_req, "lang_pack", ""),
            query=_sp_functions.help.GetConfigRequest(),
            proxy=getattr(init_req, "proxy", None),
            params=upload_params,
        )

        # Create a new MTProtoSender with the *same* auth key — no re-login.
        sender = MTProtoSender(
            client.session.auth_key,
            loggers=client._log,
            retries=5,
            delay=1,
            auto_reconnect=False,
            connect_timeout=client._timeout,
        )

        # Open a second WebSocket connection to the same server.
        connection = client._connection(
            client.session.server_address,
            client.session.port,
            client.session.dc_id,
            loggers=client._log,
            proxy=client._proxy,
            local_addr=client._local_addr,
        )

        await sender.connect(connection)

        # Initialize the connection with the upload-flagged InitConnection.
        # The response may fail to parse (Soroush custom config types) but
        # that is harmless — the server already registered this as an upload
        # connection.
        try:
            layer_req = _sp_functions.InvokeWithLayerRequest(LAYER, init_request)
            future = sender.send(layer_req)
            import asyncio
            await asyncio.wait_for(future, timeout=30)
        except Exception as exc:
            # TypeNotFoundError / BufferError are expected because Soroush
            # sends custom config types that SPlusthon can't parse.
            # The connection is still valid as an upload connection.
            exc_upper = f"{type(exc).__name__}: {exc}".upper()
            if any(t in exc_upper for t in (
                "TYPENOTFOUND", "BUFFER", "INTERNAL_SERVER",
            )):
                logger.debug(
                    "Upload connection init response parse error (expected): %s", exc
                )
            else:
                logger.warning("Upload connection init failed: %s", exc)
                try:
                    await sender.disconnect()
                except Exception:
                    pass
                raise

        logger.info("Upload MTProto sender connected for %s", self._phone)
        self._upload_sender = sender
        return sender

    async def _invalidate_upload_sender(self) -> None:
        """Disconnect and discard the cached upload sender."""
        sender = self._upload_sender
        self._upload_sender = None
        if sender is not None:
            try:
                await sender.disconnect()
            except Exception as exc:
                logger.debug("upload sender disconnect: %s", exc)

    async def _upload_file_on_upload_connection(
        self,
        stream: io.BytesIO,
        safe_name: str,
        file_size: int,
        part_size_kb: float = 512,
    ) -> Any:
        """Upload file bytes through a dedicated upload connection.

        Temporarily swaps ``self._client._sender`` with the upload sender so
        that ``self._client.upload_file()`` routes all SaveFilePartRequest
        calls through the upload connection.  The original sender is always
        restored in a ``finally`` block.

        If the upload sender cannot be created (e.g. during unit tests with
        mock clients that lack the full SPlusthon interface), falls back to
        calling ``upload_file`` on the main client directly.
        """
        try:
            upload_sender = await self._ensure_upload_sender()
        except Exception as exc:
            # If we can't create the upload sender (e.g. test fakes, missing
            # attributes), fall back to the main client's upload_file.
            logger.debug(
                "Could not create upload sender, using main client: %s", exc
            )
            return await self._client.upload_file(
                stream,
                part_size_kb=part_size_kb,
                file_size=file_size,
                file_name=safe_name,
            )

        original_sender = self._client._sender
        self._client._sender = upload_sender
        try:
            uploaded = await self._client.upload_file(
                stream,
                part_size_kb=part_size_kb,
                file_size=file_size,
                file_name=safe_name,
            )
        except Exception:
            # Upload sender may be broken; discard it so next attempt rebuilds.
            await self._invalidate_upload_sender()
            raise
        finally:
            self._client._sender = original_sender

        return uploaded

    def send_file(
        self,
        entity: str,
        path: str,
        caption: str = "",
        force_document: bool = False,
        reply_to: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Upload a file safely over a dedicated upload connection.

        The Soroush Plus server rejects ``SaveFilePartRequest`` on regular
        data connections with ``FILE_REQUEST_RECEIVED_ON_CONNECTION_SERVER``
        (RPCError 422).  This method opens a second MTProto connection
        initialised with ``params={"connection": "upload"}`` so the server
        accepts the upload, then sends the resulting file via the main
        connection.
        """
        self._ensure()
        clean_path = os.path.expanduser(str(path or "").strip().strip('"').strip("'"))
        if not clean_path or not os.path.isfile(clean_path):
            raise SoroPyError(f"File not found: {clean_path or path}")

        try:
            with open(clean_path, "rb") as source:
                payload = source.read()
        except OSError as exc:
            raise SoroPyError(f"Cannot read file '{clean_path}': {exc}") from exc

        safe_name = _ascii_upload_name(clean_path)
        extension = os.path.splitext(clean_path)[1].lower()
        as_document = bool(force_document or extension not in _IMAGE_EXTENSIONS)

        async def _send_via_upload_connection():
            """Upload on a dedicated upload connection, then send via main."""
            target = await self._resolve(entity)

            # Step 1: upload file bytes on the upload connection
            stream = io.BytesIO(payload)
            stream.name = safe_name  # type: ignore[attr-defined]
            uploaded = await self._upload_file_on_upload_connection(
                stream,
                safe_name=safe_name,
                file_size=len(payload),
                part_size_kb=512,
            )

            # Step 2: send the message with the uploaded handle on the main
            # connection (this is a regular API call, not an upload).
            kwargs: Dict[str, Any] = {
                "caption": caption or "",
                "force_document": as_document,
            }
            if reply_to:
                kwargs["reply_to"] = int(reply_to)
            result = await self._client.send_file(target, uploaded, **kwargs)
            msg = result[0] if isinstance(result, list) and result else result
            return {
                "id": getattr(msg, "id", None),
                "chat_id": str(getattr(msg, "chat_id", "") or entity),
                "file_name": safe_name,
            }

        async def _send_with_retry():
            try:
                return await _send_via_upload_connection()
            except Exception as exc:
                if not _is_upload_connection_error(exc):
                    raise
                # The upload sender is invalidated inside
                # _upload_file_on_upload_connection on error.  Discard it and
                # retry once with a fresh upload connection.
                logger.warning(
                    "Upload 422 on first attempt; retrying with fresh upload connection for %s",
                    safe_name,
                )
                await self._invalidate_upload_sender()
                return await _send_via_upload_connection()

        return self._runner.run(_send_with_retry(), timeout=300)

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
            mid = int(message_id) if message_id is not None else None
            if hasattr(self._client, "unpin_message"):
                await self._client.unpin_message(target, mid)
            else:
                # Older Telethon-compatible versions accept None for unpin-all.
                await self._client.pin_message(target, None)
            return True

        try:
            return bool(self._runner.run(_unpin(), timeout=30))
        except Exception as exc:
            logger.error("unpin_message failed: %s", exc)
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
                self._remember_entity(name, entity, kind=kind, entity_id=str(d.id))
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
                self._remember_entity(name, u, kind="personal")
                out.append({"name": name, "phone": phone, "id": str(u.id)})
            return out

        return self._runner.run(_contacts(), timeout=30)

    def add_contact(self, phone: str, first_name: str, last_name: str = "") -> bool:
        self._ensure()
        try:
            normalized = validate_phone(phone)
        except ValueError as exc:
            logger.warning("add_contact rejected invalid phone: %s", exc)
            return False
        if not str(first_name or "").strip():
            logger.warning("add_contact requires a non-empty first name")
            return False

        national = "0" + normalized[3:]
        variants = [normalized.lstrip("+"), normalized, national]

        async def _add():
            errors = []
            for index, value in enumerate(variants):
                contact = _sp_types.InputPhoneContact(
                    client_id=index + 1,
                    phone=value,
                    first_name=str(first_name).strip(),
                    last_name=str(last_name or "").strip(),
                )
                try:
                    result = await self._client(
                        _sp_functions.contacts.ImportContactsRequest([contact])
                    )
                except Exception as exc:
                    errors.append(f"{value}: {exc}")
                    continue
                imported = getattr(result, "imported", None) or []
                users = getattr(result, "users", None) or []
                if imported or users:
                    for found_user in users:
                        name = _entity_display_name(
                            found_user, str(getattr(found_user, "id", ""))
                        )
                        self._remember_entity(name, found_user, kind="personal")
                    return True
            logger.warning(
                "Contact was not imported. Verify the 11-digit number is registered "
                "in Soroush Plus. Server details: %s",
                "; ".join(errors) if errors else "no imported users",
            )
            return False

        try:
            return bool(self._runner.run(_add(), timeout=30))
        except Exception as exc:
            logger.error("add_contact failed: %s", exc)
            return False

    def search_contacts(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Search local contacts first, then use contacts.SearchRequest."""
        self._ensure()
        needle = str(query or "").strip().casefold()
        if not needle:
            return []

        async def _search():
            local_result = await self._client(
                _sp_functions.contacts.GetContactsRequest(0)
            )
            users = list(getattr(local_result, "users", None) or [])
            matched: Dict[str, Any] = {}
            for user in users:
                name = _entity_display_name(user, str(getattr(user, "id", "")))
                phone = str(getattr(user, "phone", "") or "")
                username = str(getattr(user, "username", "") or "")
                if any(needle in value.casefold() for value in (name, phone, username)):
                    matched[str(getattr(user, "id", name))] = user

            search_cls = getattr(_sp_functions.contacts, "SearchRequest", None)
            if search_cls is not None:
                try:
                    remote = await self._client(search_cls(q=str(query).strip(), limit=limit))
                    for user in getattr(remote, "users", None) or []:
                        matched[str(getattr(user, "id", id(user)))] = user
                except Exception as exc:
                    logger.debug("remote contact search unavailable: %s", exc)

            out = []
            for user in list(matched.values())[:limit]:
                name = _entity_display_name(user, str(getattr(user, "id", "")))
                self._remember_entity(name, user, kind="personal")
                out.append(
                    {
                        "name": name,
                        "phone": str(getattr(user, "phone", "") or ""),
                        "username": str(getattr(user, "username", "") or ""),
                        "id": str(getattr(user, "id", "")),
                    }
                )
            return out

        try:
            return self._runner.run(_search(), timeout=30)
        except Exception as exc:
            logger.error("search_contacts failed: %s", exc)
            return []

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
                # High-level edit_permissions uses False to apply a restriction.
                await self._client.edit_permissions(
                    chat_ent, user_ent, view_messages=False
                )
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
            # SPlusthon's high-level API applies restrictions for False values.
            # Therefore view_messages=False is a full ban; True would unban.
            kwargs = dict(rights_kwargs) if rights_kwargs else {"view_messages": False}
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
            allowed = {
                "change_info", "post_messages", "edit_messages", "delete_messages",
                "ban_users", "invite_users", "pin_messages", "add_admins",
                "anonymous", "manage_call",
            }
            defaults = {
                "change_info": False,
                "post_messages": False,
                "edit_messages": False,
                "delete_messages": True,
                "ban_users": True,
                "invite_users": True,
                "pin_messages": True,
                "add_admins": False,
                "anonymous": False,
                "manage_call": False,
            }
            defaults.update({k: v for k, v in admin_rights.items() if k in allowed})
            rank = str(admin_rights.get("rank") or admin_rights.get("title") or "admin")

            if hasattr(self._client, "edit_admin"):
                # edit_admin does not accept TL-only fields such as `other` or `rank`.
                await self._client.edit_admin(
                    chat_ent, user_ent, title=rank, **defaults
                )
            else:
                tl_allowed = set(inspect.signature(ChatAdminRights).parameters)
                rights = ChatAdminRights(
                    **{k: v for k, v in defaults.items() if k in tl_allowed}
                )
                await self._client(
                    _sp_functions.channels.EditAdminRequest(
                        channel=chat_ent,
                        user_id=user_ent,
                        admin_rights=rights,
                        rank=rank,
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
                self._remember_entity(name, u, kind="personal")
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
        key = str(entity or "").strip()
        if not key:
            raise SoroPyError("Entity cannot be empty")
        if key in self._ambiguous_names:
            raise SoroPyError(
                f"Ambiguous entity name: {key!r}. Use @username or numeric chat/user id."
            )
        if key in self._entity_cache:
            return self._entity_cache[key]

        if key.startswith("@") or key.lstrip("-").isdigit():
            value: Union[str, int] = int(key) if key.lstrip("-").isdigit() else key
            resolved = await self._client.get_entity(value)
            self._remember_entity(key, resolved)
            return resolved

        # Display-name lookup is exact and must be unique. Check dialogs before
        # treating a bare word as a username, otherwise a chat named "ali"
        # could be confused with the unrelated @ali account.
        dialogs = await self._client.get_dialogs(limit=200)
        exact = []
        for dialog in dialogs:
            candidate = dialog.entity
            name = _entity_display_name(candidate, "")
            kind = _entity_kind(candidate)
            self._remember_entity(
                name, candidate, kind=kind, entity_id=str(getattr(dialog, "id", "") or "")
            )
            if name and name.casefold() == key.casefold():
                exact.append(candidate)
        unique = {
            str(getattr(candidate, "id", id(candidate))): candidate
            for candidate in exact
        }
        if len(unique) == 1:
            resolved = next(iter(unique.values()))
            self._remember_entity(key, resolved)
            return resolved
        if len(unique) > 1:
            self._ambiguous_names.add(key)
            raise SoroPyError(
                f"Ambiguous entity name: {key!r}. Use @username or numeric chat/user id."
            )

        # Backward-compatible bare username/phone resolution, only after no
        # dialog has that exact display name.
        try:
            resolved = await self._client.get_entity(key)
            self._remember_entity(key, resolved)
            return resolved
        except Exception:
            raise SoroPyError(f"Entity not found: {key}") from None

    def _ensure(self) -> None:
        if not self.is_connected:
            raise TransportError("MTProto transport is disconnected; reconnect/login again.")
        if not self._authorized:
            raise SoroPyError("Not authorized. Complete login first.")

    def _ensure_connected(self) -> None:
        if not self.is_connected:
            raise TransportError("MTProto transport is disconnected; reconnect/login again.")
