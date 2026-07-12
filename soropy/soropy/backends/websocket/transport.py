"""
Low-level WebSocket transport with reconnect and heartbeat.

Uses the stdlib where possible; prefers the ``websocket-client`` package
when installed (declared as an optional extra: ``pip install soropy[ws]``).
"""

from __future__ import annotations

import queue
import threading
import time
from enum import Enum
from typing import Callable, Optional, Union

from soropy.exceptions import TransportError, ProtocolError
from soropy.utils import get_logger

logger = get_logger("soropy.ws.transport")

# Optional dependency
try:
    import websocket as _ws_lib  # websocket-client
    _HAS_WS = True
except ImportError:  # pragma: no cover
    _ws_lib = None  # type: ignore
    _HAS_WS = False


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    CLOSING = "closing"


OnMessage = Callable[[Union[str, bytes]], None]
OnState = Callable[[ConnectionState, str], None]


class WsTransport:
    """
    Threaded WebSocket client.

    * Incoming frames are delivered on a background thread via *on_message*.
    * Outgoing frames are queued and flushed by a writer loop so callers
      never block on the socket from the main thread longer than needed.
    * Automatic reconnect with exponential backoff.
    """

    def __init__(
        self,
        url: str,
        headers: Optional[dict] = None,
        on_message: Optional[OnMessage] = None,
        on_state: Optional[OnState] = None,
        ping_interval: float = 25.0,
        reconnect: bool = True,
        max_reconnect_delay: float = 60.0,
        connect_timeout: float = 15.0,
    ):
        self._url = url
        self._headers = headers or {}
        self._on_message = on_message
        self._on_state = on_state
        self._ping_interval = ping_interval
        self._reconnect_enabled = reconnect
        self._max_reconnect_delay = max_reconnect_delay
        self._connect_timeout = connect_timeout

        self._state = ConnectionState.DISCONNECTED
        self._ws = None
        self._lock = threading.RLock()
        self._send_q: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._threads: list = []
        self._reconnect_attempt = 0
        self._last_pong = 0.0

    # ── properties ─────────────────────────────────────

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def is_connected(self) -> bool:
        return self._state == ConnectionState.CONNECTED

    @property
    def url(self) -> str:
        return self._url

    def set_url(self, url: str) -> None:
        self._url = url

    def set_headers(self, headers: dict) -> None:
        self._headers = dict(headers)

    # ── lifecycle ──────────────────────────────────────

    def connect(self) -> None:
        """Open the socket (blocking until connected or error)."""
        if not _HAS_WS:
            raise TransportError(
                "websocket-client is required for the WebSocket backend. "
                "Install with: pip install soropy[ws]   or   pip install websocket-client"
            )
        self._stop.clear()
        self._set_state(ConnectionState.CONNECTING)
        self._open_socket()
        self._start_workers()

    def close(self) -> None:
        self._stop.set()
        self._set_state(ConnectionState.CLOSING)
        with self._lock:
            if self._ws is not None:
                try:
                    self._ws.close()
                except Exception:
                    pass
                self._ws = None
        # Unblock send queue
        try:
            self._send_q.put_nowait(None)
        except Exception:
            pass
        for t in self._threads:
            t.join(timeout=3)
        self._threads.clear()
        self._set_state(ConnectionState.DISCONNECTED)
        logger.info("Transport closed")

    def send(self, data: Union[str, bytes], block: bool = True, timeout: float = 10.0) -> None:
        """Queue a frame for sending."""
        if self._stop.is_set():
            raise TransportError("Transport is closed")
        self._send_q.put(data, block=block, timeout=timeout)

    def send_now(self, data: Union[str, bytes]) -> None:
        """Send immediately on the calling thread (use sparingly)."""
        with self._lock:
            if self._ws is None or not self.is_connected:
                raise TransportError("Not connected")
            try:
                if isinstance(data, bytes):
                    self._ws.send(data, opcode=_ws_lib.ABNF.OPCODE_BINARY)
                else:
                    self._ws.send(data)
            except Exception as exc:
                raise TransportError(f"Send failed: {exc}") from exc

    # ── internals ──────────────────────────────────────

    def _set_state(self, state: ConnectionState, detail: str = "") -> None:
        self._state = state
        logger.debug("Transport state → %s %s", state.value, detail)
        if self._on_state:
            try:
                self._on_state(state, detail)
            except Exception as exc:
                logger.error("on_state handler error: %s", exc)

    def _open_socket(self) -> None:
        assert _ws_lib is not None
        logger.info("Connecting to %s", self._url)
        header_list = [f"{k}: {v}" for k, v in self._headers.items()]
        try:
            sock = _ws_lib.create_connection(
                self._url,
                header=header_list,
                timeout=self._connect_timeout,
                enable_multithread=True,
            )
        except Exception as exc:
            self._set_state(ConnectionState.DISCONNECTED, str(exc))
            raise TransportError(f"WebSocket connect failed: {exc}") from exc

        with self._lock:
            self._ws = sock
        self._reconnect_attempt = 0
        self._last_pong = time.time()
        self._set_state(ConnectionState.CONNECTED)
        logger.info("WebSocket connected")

    def _start_workers(self) -> None:
        self._threads = [
            threading.Thread(target=self._reader_loop, name="ws-reader", daemon=True),
            threading.Thread(target=self._writer_loop, name="ws-writer", daemon=True),
            threading.Thread(target=self._heartbeat_loop, name="ws-heartbeat", daemon=True),
        ]
        for t in self._threads:
            t.start()

    def _reader_loop(self) -> None:
        while not self._stop.is_set():
            ws = self._ws
            if ws is None:
                if not self._maybe_reconnect():
                    break
                continue
            try:
                opcode, data = ws.recv_data()
                if data is None or data == b"":
                    raise TransportError("Empty frame / closed")
                # TEXT = 1, BINARY = 2
                if opcode == 1:
                    payload: Union[str, bytes] = data.decode("utf-8", errors="replace")
                else:
                    payload = data
                if self._on_message:
                    self._on_message(payload)
            except Exception as exc:
                if self._stop.is_set():
                    break
                logger.warning("Reader error: %s", exc)
                self._invalidate_socket()
                if not self._maybe_reconnect():
                    break

    def _writer_loop(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._send_q.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                continue
            try:
                self.send_now(item)
            except Exception as exc:
                if self._stop.is_set():
                    break
                logger.warning("Writer error: %s", exc)
                # re-queue once
                try:
                    self._send_q.put_nowait(item)
                except Exception:
                    pass
                self._invalidate_socket()
                time.sleep(0.5)

    def _heartbeat_loop(self) -> None:
        """
        Application-level heartbeat placeholder.

        The backend injects real ping frames via *on_message* / protocol.
        Here we only detect stalled sockets (no data for 3× interval).
        """
        while not self._stop.is_set():
            self._stop.wait(timeout=self._ping_interval)
            if self._stop.is_set():
                break
            if not self.is_connected:
                continue
            # Stall detection is optional; rely on OS TCP + WS ping if available
            try:
                with self._lock:
                    if self._ws is not None and hasattr(self._ws, "ping"):
                        self._ws.ping()
            except Exception as exc:
                logger.debug("Socket ping failed: %s", exc)
                self._invalidate_socket()

    def _invalidate_socket(self) -> None:
        with self._lock:
            if self._ws is not None:
                try:
                    self._ws.close()
                except Exception:
                    pass
                self._ws = None
        if not self._stop.is_set():
            self._set_state(ConnectionState.DISCONNECTED, "socket invalidated")

    def _maybe_reconnect(self) -> bool:
        if self._stop.is_set() or not self._reconnect_enabled:
            return False
        self._reconnect_attempt += 1
        delay = min(
            self._max_reconnect_delay,
            (2 ** min(self._reconnect_attempt, 6)) * 0.5,
        )
        self._set_state(
            ConnectionState.RECONNECTING,
            f"attempt={self._reconnect_attempt} delay={delay:.1f}s",
        )
        logger.info(
            "Reconnecting in %.1fs (attempt %d)",
            delay,
            self._reconnect_attempt,
        )
        if self._stop.wait(timeout=delay):
            return False
        try:
            self._open_socket()
            return True
        except Exception as exc:
            logger.warning("Reconnect failed: %s", exc)
            return True  # keep trying
