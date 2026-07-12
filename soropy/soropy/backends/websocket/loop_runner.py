"""
Background asyncio event-loop runner.

SoroPy's public API is synchronous; SPlusthon (MTProto) is async.
This helper owns a dedicated thread + loop so we can bridge safely.
"""

from __future__ import annotations

import asyncio
import atexit
import threading
from concurrent.futures import Future
from typing import Any, Coroutine, Optional, TypeVar

from soropy.utils import get_logger

logger = get_logger("soropy.ws.loop")

T = TypeVar("T")


class LoopRunner:
    """
    One dedicated asyncio loop running on a daemon thread.

    Usage::

        runner = LoopRunner()
        runner.start()
        result = runner.run(coro(), timeout=30)
        runner.stop()
    """

    def __init__(self, name: str = "soropy-ws-loop"):
        self._name = name
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._stopped = False

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            raise RuntimeError("LoopRunner not started")
        return self._loop

    @property
    def is_running(self) -> bool:
        return (
            self._loop is not None
            and self._thread is not None
            and self._thread.is_alive()
            and not self._stopped
        )

    def start(self) -> None:
        if self.is_running:
            return
        self._stopped = False
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._run_forever,
            name=self._name,
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(timeout=10):
            raise RuntimeError("Failed to start asyncio loop thread")
        atexit.register(self.stop)

    def _run_forever(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            try:
                # Cancel remaining tasks
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            loop.close()
            self._loop = None

    def submit(self, coro: Coroutine[Any, Any, T]) -> Future:
        """Schedule *coro* and return a concurrent.futures.Future."""
        if not self.is_running:
            raise RuntimeError("LoopRunner is not running")
        assert self._loop is not None
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def run(self, coro: Coroutine[Any, Any, T], timeout: Optional[float] = 60.0) -> T:
        """Block until *coro* finishes; re-raise exceptions from the coro."""
        fut = self.submit(coro)
        try:
            return fut.result(timeout=timeout)
        except Exception:
            fut.cancel()
            raise

    def call_soon(self, callback, *args) -> None:
        if not self.is_running:
            return
        assert self._loop is not None
        self._loop.call_soon_threadsafe(callback, *args)

    def stop(self, timeout: float = 5.0) -> None:
        if self._stopped:
            return
        self._stopped = True
        loop = self._loop
        thread = self._thread
        if loop is not None and thread is not None and thread.is_alive():
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=timeout)
        self._thread = None
        self._loop = None
        logger.debug("LoopRunner stopped")
