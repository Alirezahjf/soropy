"""
Multi-account manager – run multiple SoroushClient instances
in parallel, each with its own browser and session.
"""

import threading
from typing import Dict, Optional, Callable, List

from soropy.client import SoroushClient
from soropy.types import LoginStatus, ChatCollection, SendResult
from soropy.utils import get_logger, normalize_phone
from soropy.exceptions import SoroPyError

logger = get_logger("soropy.multi")


class MultiAccountManager:
    """
    Manage multiple Soroush Plus accounts simultaneously.

    Example
    -------
    >>> mgr = MultiAccountManager(headless=True)
    >>> mgr.add_account("+989123456789")
    >>> mgr.add_account("+989187654321")
    >>> mgr.login_all()
    >>> mgr.get_client("+989123456789").send_message("علی", "سلام!")
    >>> mgr.close_all()
    """

    def __init__(
        self,
        headless: bool = False,
        session_dir: str = "soropy_sessions",
        **client_kwargs,
    ):
        self._headless = headless
        self._session_dir = session_dir
        self._client_kwargs = client_kwargs
        self._clients: Dict[str, SoroushClient] = {}
        self._lock = threading.Lock()

    # ── Account management ─────────────────────────────

    def add_account(self, phone: str, **kwargs) -> SoroushClient:
        """
        Register a phone number.  Does NOT start the browser yet.
        Returns the created SoroushClient.
        """
        norm = normalize_phone(phone)
        merged = {**self._client_kwargs, **kwargs}
        client = SoroushClient(
            norm,
            headless=self._headless,
            session_dir=self._session_dir,
            **merged,
        )
        with self._lock:
            self._clients[norm] = client
        logger.info("Account added: %s", norm)
        return client

    def remove_account(self, phone: str) -> None:
        """Close and remove an account."""
        norm = normalize_phone(phone)
        with self._lock:
            client = self._clients.pop(norm, None)
        if client:
            client.close()
            logger.info("Account removed: %s", norm)

    def get_client(self, phone: str) -> SoroushClient:
        """Get the SoroushClient for *phone*."""
        norm = normalize_phone(phone)
        with self._lock:
            client = self._clients.get(norm)
        if client is None:
            raise SoroPyError(f"Account {norm} not registered")
        return client

    @property
    def phones(self) -> List[str]:
        with self._lock:
            return list(self._clients.keys())

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._clients)

    # ── Bulk operations ────────────────────────────────

    def login_all(
        self,
        code_callback_factory: Optional[Callable[[str], Callable[[], str]]] = None,
        parallel: bool = False,
    ) -> Dict[str, LoginStatus]:
        """
        Log in all registered accounts.

        Parameters
        ----------
        code_callback_factory : callable(phone) -> callable() -> str
            Factory that returns a code-input callback for each phone.
            Default: ``input()`` prompt mentioning the phone number.
        parallel : bool
            If True, log in accounts in parallel threads.
            **Note**: If codes are needed interactively, set False.

        Returns
        -------
        dict  phone → LoginStatus
        """
        results: Dict[str, LoginStatus] = {}
        results_lock = threading.Lock()

        def _login_one(phone: str, client: SoroushClient):
            if code_callback_factory:
                cb = code_callback_factory(phone)
            else:
                cb = lambda: input(f"🔑 Code for {phone}: ")
            try:
                status = client.login(code_callback=cb)
            except Exception as e:
                logger.error("Login failed for %s: %s", phone, e)
                status = LoginStatus.FAILED
            with results_lock:
                results[phone] = status
            logger.info("Login %s: %s", phone, status.value)

        with self._lock:
            items = list(self._clients.items())

        if parallel:
            threads = []
            for phone, client in items:
                t = threading.Thread(
                    target=_login_one,
                    args=(phone, client),
                    daemon=True,
                    name=f"login-{phone}",
                )
                threads.append(t)
                t.start()
            for t in threads:
                t.join(timeout=120)
        else:
            for phone, client in items:
                _login_one(phone, client)

        return results

    def close_all(self) -> None:
        """Close all accounts."""
        with self._lock:
            items = list(self._clients.items())
        for phone, client in items:
            try:
                client.close()
            except Exception:
                pass
        with self._lock:
            self._clients.clear()
        logger.info("All accounts closed")

    def start_all_monitors(
        self,
        interval: int = 30,
        on_reply: Optional[Callable[[str, str, str, str], None]] = None,
    ) -> Dict[str, threading.Thread]:
        """
        Start auto-reply monitors for all accounts (non-blocking).

        Parameters
        ----------
        on_reply : callable(phone, chat_name, original_msg, reply_msg)
            Optional callback.

        Returns
        -------
        dict  phone → Thread
        """
        threads: Dict[str, threading.Thread] = {}
        with self._lock:
            items = list(self._clients.items())

        for phone, client in items:
            def make_callback(p):
                def cb(chat, orig, reply):
                    if on_reply:
                        on_reply(p, chat, orig, reply)
                return cb

            t = client.start_monitor(
                interval=interval,
                blocking=False,
                on_reply=make_callback(phone),
            )
            if t:
                threads[phone] = t

        logger.info("Monitors started for %d accounts", len(threads))
        return threads

    def stop_all_monitors(self) -> None:
        """Stop all running monitors."""
        with self._lock:
            items = list(self._clients.items())
        for _, client in items:
            client.stop_monitor()
        logger.info("All monitors stopped")

    # ── Context manager ────────────────────────────────

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close_all()