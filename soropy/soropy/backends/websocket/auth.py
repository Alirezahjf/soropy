"""
Authentication service for the WebSocket backend.

Flow (target)
-------------
1. If stored credentials exist → resume session over WS / HTTP.
2. Else → request SMS code (HTTP or WS) → user supplies code → exchange for tokens.
3. Persist credentials via :class:`WsSessionStore`.

The concrete endpoints are marked ``TODO(protocol)`` until reverse-engineered.
"""

from __future__ import annotations

import time
import uuid
from typing import Callable, Optional

from soropy.backends.websocket.protocol import FrameType, SplusProtocol
from soropy.backends.websocket.session import WsCredentials, WsSessionStore
from soropy.backends.websocket.transport import WsTransport
from soropy.exceptions import LoginError, ProtocolNotReadyError
from soropy.types import LoginStatus
from soropy.utils import get_logger

logger = get_logger("soropy.ws.auth")


class SplusAuthService:
    """
    Handles login / session resume for the WS backend.

    Parameters
    ----------
    store : WsSessionStore
        Credential persistence.
    protocol : SplusProtocol
        Frame encoder.
    auth_mode : str
        ``"token"`` – resume with saved token (default path after first login).
        ``"sms"``   – full phone + code flow.
        ``"hybrid"``– try token first, fall back to SMS.
    """

    def __init__(
        self,
        store: WsSessionStore,
        protocol: Optional[SplusProtocol] = None,
        auth_mode: str = "hybrid",
        # TODO(protocol): set real HTTP bootstrap URL once known
        bootstrap_url: str = "",
    ):
        self._store = store
        self._protocol = protocol or SplusProtocol()
        self._auth_mode = auth_mode
        self._bootstrap_url = bootstrap_url
        self._credentials: Optional[WsCredentials] = None

    @property
    def credentials(self) -> Optional[WsCredentials]:
        return self._credentials

    def load_saved(self, phone: str) -> Optional[WsCredentials]:
        creds = self._store.load(phone)
        if creds and creds.is_valid():
            self._credentials = creds
            return creds
        return None

    def ensure_device_id(self, phone: str) -> str:
        """Stable device id per phone (created once, then reused)."""
        creds = self._store.load(phone) or WsCredentials(phone=phone)
        if not creds.device_id:
            creds.device_id = uuid.uuid4().hex
            self._store.save(creds)
        self._credentials = creds
        return creds.device_id

    def login(
        self,
        phone: str,
        transport: Optional[WsTransport],
        code_callback: Optional[Callable[[], str]] = None,
        wait_auth_result: Optional[Callable[[float], Optional[dict]]] = None,
        timeout: float = 30.0,
    ) -> LoginStatus:
        """
        Run auth against an already-connected *transport*.

        Parameters
        ----------
        wait_auth_result :
            Callable provided by the backend that blocks until an
            AUTH_RESULT / ERROR frame arrives, returning its payload.
        """
        if transport is None or not transport.is_connected:
            raise LoginError("Transport not connected")

        # 1) try resume
        if self._auth_mode in ("token", "hybrid"):
            saved = self.load_saved(phone)
            if saved and saved.is_valid():
                logger.info("Resuming WS session for %s", phone)
                frame = self._protocol.encode_auth(phone, token=saved.access_token or saved.session_id)
                transport.send(frame.data)
                if wait_auth_result:
                    result = wait_auth_result(timeout)
                    if result is not None and not result.get("error"):
                        self._update_from_auth_payload(phone, result)
                        return LoginStatus.SESSION_RESTORED
                    logger.warning("Token resume failed, falling back to SMS")
                else:
                    # optimistic – backend will surface errors via events
                    return LoginStatus.SESSION_RESTORED

        if self._auth_mode == "token":
            raise LoginError("No valid token and auth_mode='token'")

        # 2) SMS flow
        return self._login_with_sms(phone, transport, code_callback, wait_auth_result, timeout)

    def _login_with_sms(
        self,
        phone: str,
        transport: WsTransport,
        code_callback: Optional[Callable[[], str]],
        wait_auth_result: Optional[Callable[[float], Optional[dict]]],
        timeout: float,
    ) -> LoginStatus:
        """
        Full phone + code authentication.

        TODO(protocol): The real splus flow may be:
          a) pure WS (auth.login → code challenge → auth.verify)
          b) HTTP POST /api/auth → then WS with cookie/token
        Both are supported by filling in the methods below.
        """
        logger.info("Starting SMS auth for %s", phone)

        # Step A: request code
        # Prefer HTTP bootstrap if URL configured; else send WS auth without code
        if self._bootstrap_url:
            self._http_request_code(phone)
        else:
            # Send provisional "start auth" frame (empty code)
            frame = self._protocol.encode_auth(phone, code="")
            transport.send(frame.data)

        # Step B: collect code from user
        if code_callback is None:
            code_callback = lambda: input("🔑 Enter verification code: ")
        code = (code_callback() or "").strip()
        if not code:
            raise LoginError("Empty verification code")

        # Step C: submit code
        frame = self._protocol.encode_auth(phone, code=code)
        transport.send(frame.data)

        if wait_auth_result:
            result = wait_auth_result(timeout)
            if result is None:
                raise LoginError("Auth timed out waiting for server response")
            if result.get("error"):
                raise LoginError(f"Auth failed: {result.get('error')}")
            self._update_from_auth_payload(phone, result)
            return LoginStatus.SUCCESS

        # Without a waiter we cannot confirm — mark provisional success
        # and let the caller verify via is_logged_in / events.
        logger.warning(
            "No auth-result waiter configured; assuming success. "
            "Wire wait_auth_result for production use."
        )
        device_id = self.ensure_device_id(phone)
        creds = self._credentials or WsCredentials(phone=phone, device_id=device_id)
        # Keep a marker so exists() returns True after first interactive login
        if not creds.session_id:
            creds.session_id = f"pending-{uuid.uuid4().hex[:12]}"
        self._store.save(creds)
        self._credentials = creds
        return LoginStatus.SUCCESS

    def _http_request_code(self, phone: str) -> None:
        """
        TODO(protocol): HTTP endpoint that triggers SMS.

        Example sketch (not active until URL is known)::

            import urllib.request, json
            req = urllib.request.Request(
                self._bootstrap_url,
                data=json.dumps({\"phone\": phone}).encode(),
                headers={\"Content-Type\": \"application/json\"},
                method=\"POST\",
            )
            urllib.request.urlopen(req, timeout=15)
        """
        raise ProtocolNotReadyError(
            "HTTP bootstrap URL is set but _http_request_code is not implemented. "
            "Fill in the real splus auth endpoint after reverse-engineering."
        )

    def _update_from_auth_payload(self, phone: str, payload: dict) -> None:
        """Merge server auth response into stored credentials."""
        # TODO(protocol): map real field names
        creds = self._store.load(phone) or WsCredentials(phone=phone)
        creds.access_token = str(
            payload.get("access_token")
            or payload.get("token")
            or payload.get("auth_token")
            or creds.access_token
        )
        creds.refresh_token = str(
            payload.get("refresh_token") or creds.refresh_token
        )
        creds.user_id = str(
            payload.get("user_id") or payload.get("uid") or creds.user_id
        )
        creds.session_id = str(
            payload.get("session_id") or payload.get("sid") or creds.session_id
        )
        if not creds.device_id:
            creds.device_id = uuid.uuid4().hex
        # Keep any unknown keys
        for k, v in payload.items():
            if k not in (
                "access_token", "token", "auth_token", "refresh_token",
                "user_id", "uid", "session_id", "sid", "error",
            ):
                creds.extra[k] = v
        self._store.save(creds)
        self._credentials = creds
        logger.info("Credentials updated for %s", phone)

    def logout(self, phone: str) -> None:
        self._store.delete(phone)
        self._credentials = None
