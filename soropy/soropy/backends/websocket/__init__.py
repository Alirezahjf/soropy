"""
WebSocket / MTProto backend for Soroush Plus.

Real transport
--------------
Soroush Plus speaks **MTProto** over WebSocket:

* URL: ``wss://im-server.splus.ir:443/apiws``
* Origin: ``https://web.splus.ir``
* Codec: obfuscated abridged MTProto

The heavy crypto / TL schema is provided by the optional
``splusthon`` dependency (Telethon fork for Soroush).

Install::

    pip install soropy[ws]
"""

from soropy.backends.websocket.backend import WebSocketBackend
from soropy.backends.websocket.events import EventBus, SplusEvent
from soropy.backends.websocket.mtproto_engine import MtprotoEngine

__all__ = [
    "WebSocketBackend",
    "EventBus",
    "SplusEvent",
    "MtprotoEngine",
]
