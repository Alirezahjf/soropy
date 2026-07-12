"""
Soroush Plus wire protocol encoder / decoder.

This module defines the *shape* of protocol messages used inside SoroPy.
The actual binary/JSON mapping must be completed after reverse-engineering
``wss://…`` traffic from ``web.splus.ir``.

Design goals
------------
* Keep all frame knowledge in one place.
* Decode unknown frames into a safe ``RawFrame`` so the rest of the stack
  never crashes on unexpected server messages.
* Encode high-level intents (send text, mark read, …) into wire payloads.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from soropy.backends.websocket.events import IncomingMessage, SplusEvent
from soropy.utils import get_logger

logger = get_logger("soropy.ws.protocol")


class FrameType(str, Enum):
    """Logical frame categories (independent of wire encoding)."""

    # client → server
    AUTH = "auth"
    PING = "ping"
    SEND_MESSAGE = "send_message"
    REPLY_MESSAGE = "reply_message"
    MARK_READ = "mark_read"
    GET_CHATS = "get_chats"
    GET_HISTORY = "get_history"
    GET_CONTACTS = "get_contacts"
    ADD_CONTACT = "add_contact"
    TYPING = "typing"
    ACK = "ack"

    # server → client
    AUTH_RESULT = "auth_result"
    PONG = "pong"
    NEW_MESSAGE = "new_message"
    MESSAGE_ACK = "message_ack"
    CHAT_LIST = "chat_list"
    HISTORY = "history"
    CONTACTS = "contacts"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass
class ProtocolFrame:
    """
    Internal representation of one protocol message.

    Attributes
    ----------
    type : FrameType
        Logical type.
    request_id : str
        Correlation id for request/response pairs.
    payload : dict
        Decoded body.
    raw : str | bytes | None
        Original wire data (for debugging / RAW_FRAME events).
    """

    type: FrameType
    payload: Dict[str, Any] = field(default_factory=dict)
    request_id: str = ""
    raw: Optional[Union[str, bytes]] = None
    timestamp: float = field(default_factory=time.time)

    def to_event_name(self) -> Optional[str]:
        """Map frame type → :class:`SplusEvent` name when applicable."""
        mapping = {
            FrameType.NEW_MESSAGE: SplusEvent.NEW_MESSAGE.value,
            FrameType.MESSAGE_ACK: SplusEvent.MESSAGE_ACK.value,
            FrameType.AUTH_RESULT: SplusEvent.AUTH_SUCCESS.value,
            FrameType.ERROR: SplusEvent.ERROR.value,
            FrameType.PONG: None,  # handled internally
        }
        return mapping.get(self.type)


@dataclass
class EncodedFrame:
    """Ready-to-send wire data."""

    data: Union[str, bytes]
    request_id: str = ""
    is_binary: bool = False


class SplusProtocol:
    """
    Encode high-level actions and decode inbound frames.

    Wire format strategy
    --------------------
    Until reverse-engineering is complete we use a **documented provisional
    JSON schema**.  When the real protocol is known, only methods in this
    class need to change — transport and backend stay intact.

    Provisional JSON (client → server)::

        {
          "id": "<uuid>",
          "method": "messages.send",
          "params": { ... }
        }

    Provisional JSON (server → client)::

        {
          "id": "<uuid>",          # optional, echoes request
          "event": "messages.new", # or "result" / "error"
          "data": { ... }
        }
    """

    # ── method / event name constants (provisional) ────
    # TODO(protocol): replace with real method names from splus
    METHOD_AUTH = "auth.login"
    METHOD_AUTH_RESUME = "auth.resume"
    METHOD_PING = "sys.ping"
    METHOD_SEND = "messages.send"
    METHOD_REPLY = "messages.reply"
    METHOD_MARK_READ = "messages.read"
    METHOD_GET_CHATS = "chats.list"
    METHOD_GET_HISTORY = "messages.history"
    METHOD_GET_CONTACTS = "contacts.list"
    METHOD_ADD_CONTACT = "contacts.add"
    METHOD_TYPING = "chats.typing"

    EVENT_NEW_MESSAGE = "messages.new"
    EVENT_MESSAGE_ACK = "messages.ack"
    EVENT_AUTH_OK = "auth.ok"
    EVENT_AUTH_FAIL = "auth.fail"
    EVENT_PONG = "sys.pong"
    EVENT_CHAT_LIST = "chats.list"
    EVENT_HISTORY = "messages.history"
    EVENT_CONTACTS = "contacts.list"
    EVENT_ERROR = "error"

    def __init__(self) -> None:
        self._pending: Dict[str, FrameType] = {}

    # ═══════════════════════════════════════════════════
    #  Encode (client → server)
    # ═══════════════════════════════════════════════════

    def _new_id(self) -> str:
        return uuid.uuid4().hex[:16]

    def _encode_json(self, method: str, params: Dict[str, Any], frame_type: FrameType) -> EncodedFrame:
        req_id = self._new_id()
        body = {"id": req_id, "method": method, "params": params}
        self._pending[req_id] = frame_type
        data = json.dumps(body, ensure_ascii=False)
        return EncodedFrame(data=data, request_id=req_id, is_binary=False)

    def encode_auth(self, phone: str, code: str = "", token: str = "") -> EncodedFrame:
        """Build auth / resume frame."""
        if token:
            return self._encode_json(
                self.METHOD_AUTH_RESUME,
                {"token": token, "phone": phone},
                FrameType.AUTH,
            )
        return self._encode_json(
            self.METHOD_AUTH,
            {"phone": phone, "code": code},
            FrameType.AUTH,
        )

    def encode_ping(self) -> EncodedFrame:
        return self._encode_json(self.METHOD_PING, {"ts": time.time()}, FrameType.PING)

    def encode_send_message(
        self,
        chat_id: str,
        text: str,
        reply_to_id: str = "",
    ) -> EncodedFrame:
        params: Dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_to_id:
            params["reply_to"] = reply_to_id
            return self._encode_json(self.METHOD_REPLY, params, FrameType.REPLY_MESSAGE)
        return self._encode_json(self.METHOD_SEND, params, FrameType.SEND_MESSAGE)

    def encode_mark_read(self, chat_id: str, message_ids: Optional[List[str]] = None) -> EncodedFrame:
        return self._encode_json(
            self.METHOD_MARK_READ,
            {"chat_id": chat_id, "message_ids": message_ids or []},
            FrameType.MARK_READ,
        )

    def encode_get_chats(self) -> EncodedFrame:
        return self._encode_json(self.METHOD_GET_CHATS, {}, FrameType.GET_CHATS)

    def encode_get_history(self, chat_id: str, limit: int = 50, offset: int = 0) -> EncodedFrame:
        return self._encode_json(
            self.METHOD_GET_HISTORY,
            {"chat_id": chat_id, "limit": limit, "offset": offset},
            FrameType.GET_HISTORY,
        )

    def encode_get_contacts(self) -> EncodedFrame:
        return self._encode_json(self.METHOD_GET_CONTACTS, {}, FrameType.GET_CONTACTS)

    def encode_add_contact(
        self,
        phone: str,
        first_name: str,
        last_name: str = "",
    ) -> EncodedFrame:
        return self._encode_json(
            self.METHOD_ADD_CONTACT,
            {"phone": phone, "first_name": first_name, "last_name": last_name},
            FrameType.ADD_CONTACT,
        )

    def encode_typing(self, chat_id: str, is_typing: bool = True) -> EncodedFrame:
        return self._encode_json(
            self.METHOD_TYPING,
            {"chat_id": chat_id, "typing": is_typing},
            FrameType.TYPING,
        )

    def encode_raw(self, data: Union[str, bytes, Dict[str, Any]]) -> EncodedFrame:
        """Escape hatch for experiments during reverse-engineering."""
        if isinstance(data, dict):
            raw = json.dumps(data, ensure_ascii=False)
            return EncodedFrame(data=raw, is_binary=False)
        if isinstance(data, bytes):
            return EncodedFrame(data=data, is_binary=True)
        return EncodedFrame(data=str(data), is_binary=False)

    # ═══════════════════════════════════════════════════
    #  Decode (server → client)
    # ═══════════════════════════════════════════════════

    def decode(self, raw: Union[str, bytes]) -> ProtocolFrame:
        """
        Parse one inbound frame.

        TODO(protocol): if the real protocol is binary / MessagePack /
        custom MTProto-like, replace the body of this method only.
        """
        text: str
        if isinstance(raw, bytes):
            # TODO(protocol): binary decode path
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                return ProtocolFrame(
                    type=FrameType.UNKNOWN,
                    payload={"hex": raw[:64].hex(), "length": len(raw)},
                    raw=raw,
                )
        else:
            text = raw

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.debug("Non-JSON frame: %s", text[:120])
            return ProtocolFrame(
                type=FrameType.UNKNOWN,
                payload={"text": text[:500]},
                raw=raw,
            )

        if not isinstance(data, dict):
            return ProtocolFrame(type=FrameType.UNKNOWN, payload={"value": data}, raw=raw)

        return self._classify(data, raw)

    def _classify(self, data: Dict[str, Any], raw: Union[str, bytes]) -> ProtocolFrame:
        req_id = str(data.get("id") or data.get("request_id") or "")
        event = (
            data.get("event")
            or data.get("method")
            or data.get("type")
            or data.get("action")
            or ""
        )
        event = str(event).lower()
        body = data.get("data") or data.get("params") or data.get("result") or data
        if not isinstance(body, dict):
            body = {"value": body}

        # Correlate response to pending request
        if req_id and req_id in self._pending:
            pending = self._pending.pop(req_id)
            # map request type → response type
            response_map = {
                FrameType.AUTH: FrameType.AUTH_RESULT,
                FrameType.PING: FrameType.PONG,
                FrameType.GET_CHATS: FrameType.CHAT_LIST,
                FrameType.GET_HISTORY: FrameType.HISTORY,
                FrameType.GET_CONTACTS: FrameType.CONTACTS,
                FrameType.SEND_MESSAGE: FrameType.MESSAGE_ACK,
                FrameType.REPLY_MESSAGE: FrameType.MESSAGE_ACK,
            }
            ftype = response_map.get(pending, FrameType.UNKNOWN)
            if data.get("error") or event in ("error", self.EVENT_ERROR, self.EVENT_AUTH_FAIL):
                ftype = FrameType.ERROR
            return ProtocolFrame(type=ftype, payload=body if isinstance(body, dict) else data, request_id=req_id, raw=raw)

        event_map = {
            self.EVENT_NEW_MESSAGE: FrameType.NEW_MESSAGE,
            "message": FrameType.NEW_MESSAGE,
            "new_message": FrameType.NEW_MESSAGE,
            self.EVENT_MESSAGE_ACK: FrameType.MESSAGE_ACK,
            self.EVENT_AUTH_OK: FrameType.AUTH_RESULT,
            self.EVENT_AUTH_FAIL: FrameType.ERROR,
            self.EVENT_PONG: FrameType.PONG,
            "pong": FrameType.PONG,
            self.EVENT_CHAT_LIST: FrameType.CHAT_LIST,
            self.EVENT_HISTORY: FrameType.HISTORY,
            self.EVENT_CONTACTS: FrameType.CONTACTS,
            self.EVENT_ERROR: FrameType.ERROR,
            "error": FrameType.ERROR,
        }
        ftype = event_map.get(event, FrameType.UNKNOWN)
        if data.get("error"):
            ftype = FrameType.ERROR

        return ProtocolFrame(type=ftype, payload=body if isinstance(body, dict) else data, request_id=req_id, raw=raw)

    # ═══════════════════════════════════════════════════
    #  Domain mappers
    # ═══════════════════════════════════════════════════

    def frame_to_incoming_message(self, frame: ProtocolFrame) -> Optional[IncomingMessage]:
        """Convert a NEW_MESSAGE frame into :class:`IncomingMessage`."""
        if frame.type != FrameType.NEW_MESSAGE:
            return None
        p = frame.payload
        # TODO(protocol): adjust field names to real splus schema
        text = (
            p.get("text")
            or p.get("message")
            or p.get("body")
            or p.get("content")
            or ""
        )
        if isinstance(text, dict):
            text = text.get("text") or text.get("body") or ""
        return IncomingMessage(
            message_id=str(p.get("id") or p.get("message_id") or frame.request_id or ""),
            chat_id=str(p.get("chat_id") or p.get("peer_id") or p.get("dialog_id") or ""),
            chat_name=str(p.get("chat_name") or p.get("title") or p.get("peer_name") or ""),
            text=str(text),
            sender_id=str(p.get("sender_id") or p.get("from_id") or ""),
            sender_name=str(p.get("sender_name") or p.get("from_name") or ""),
            is_outgoing=bool(p.get("is_outgoing") or p.get("out") or False),
            timestamp=float(p.get("timestamp") or p.get("date") or time.time()),
            reply_to_id=str(p.get("reply_to") or p.get("reply_to_id") or ""),
            raw=p,
        )

    def chats_from_frame(self, frame: ProtocolFrame) -> Dict[str, List[str]]:
        """
        Extract categorised chat names from a CHAT_LIST frame.

        Returns dict with keys: all, personal, groups, channels.
        """
        p = frame.payload
        items = p.get("chats") or p.get("dialogs") or p.get("items") or p
        result = {"all": [], "personal": [], "groups": [], "channels": []}
        if not isinstance(items, list):
            return result

        for item in items:
            if isinstance(item, str):
                result["all"].append(item)
                continue
            if not isinstance(item, dict):
                continue
            name = (
                item.get("name")
                or item.get("title")
                or item.get("fullName")
                or ""
            )
            if not name:
                continue
            result["all"].append(str(name))
            kind = str(item.get("type") or item.get("category") or "").lower()
            if kind in ("private", "personal", "user", "pv", "شخصی"):
                result["personal"].append(str(name))
            elif kind in ("group", "groups", "گروه", "گروه‌ها"):
                result["groups"].append(str(name))
            elif kind in ("channel", "channels", "کانال", "کانال‌ها"):
                result["channels"].append(str(name))
            else:
                result["personal"].append(str(name))
        return result
