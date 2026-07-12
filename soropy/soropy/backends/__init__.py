"""
Transport backends for SoroPy.

Two backends share the same high-level contract:

* ``selenium``  – DOM automation via Chrome (current default)
* ``websocket`` – direct protocol client (event-driven, lightweight)

Example
-------
>>> from soropy import SoroushClient
>>> client = SoroushClient("0912...", backend="websocket")
>>> client.login()
>>> client.send_message("علی", "سلام")
"""

from soropy.backends.base import BaseBackend, BackendCapability

__all__ = [
    "BaseBackend",
    "BackendCapability",
    "create_backend",
]


def create_backend(name: str, **kwargs) -> "BaseBackend":
    """
    Factory: build a backend by name.

    Parameters
    ----------
    name : str
        ``"selenium"`` or ``"websocket"`` (aliases: ``"ws"``, ``"splus"``).
    **kwargs
        Forwarded to the backend constructor.
    """
    key = (name or "selenium").strip().lower()
    if key in ("selenium", "browser", "chrome", "ui"):
        from soropy.backends.selenium_backend import SeleniumBackend
        return SeleniumBackend(**kwargs)
    if key in ("websocket", "ws", "splus", "protocol"):
        from soropy.backends.websocket.backend import WebSocketBackend
        return WebSocketBackend(**kwargs)
    raise ValueError(
        f"Unknown backend '{name}'. Use 'selenium' or 'websocket'."
    )
