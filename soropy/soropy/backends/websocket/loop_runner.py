"""
Background asyncio event-loop runner.

SoroPy's public API is synchronous; SPlusthon (MTProto) is async.
This helper owns a dedicated thread + loop so we can bridge safely.

Critical design rules
---------------------
* ``run()`` must NEVER be called from the loop thread itself
  (would deadlock). Use ``create_task`` / ``submit`` instead.
* Fire-and-forget work (auto-reply, reconnect side-effects) goes
  through ``create_task`` so event handlers stay non-blocking.
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
        result = runner.run(coro(), timeout=30)   # sync callers
        runner.create_task(coro())                 # fire-and-forget
        runner.stop()
    """

    def __init__(self, name: str = "soropy-ws-loop"):
        self._name = name
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._stopped = False
        self._thread_id: Optional[int] = None
        self._state_lock = threading.RLock()
        self._atexit_registered = False

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

    def in_loop_thread(self) -> bool:
        """True when called from the asyncio loop's own thread."""
        return (
            self._thread_id is not None
            and threading.get_ident() == self._thread_id
        )

    def start(self) -> None:
        with self._state_lock:
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
        if not self._atexit_registered:
            atexit.register(self.stop)
            self._atexit_registered = True

    def _run_forever(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._thread_id = threading.get_ident()
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
                loop.run_until_complete(loop.shutdown_asyncgens())
                # Close default aiohttp-style executors cleanly
                try:
                    loop.run_until_complete(loop.shutdown_default_executor())
                except Exception:
                    pass
            except Exception:
                pass
            loop.close()
            self._loop = None
            self._thread_id = None

    def submit(self, coro: Coroutine[Any, Any, T]) -> Future:
        """Schedule *coro* and return a concurrent.futures.Future."""
        if not self.is_running:
            # Close the coroutine to avoid "never awaited" warnings
            try:
                coro.close()
            except Exception:
                pass
            raise RuntimeError("LoopRunner is not running")
        assert self._loop is not None
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def create_task(self, coro: Coroutine[Any, Any, T]) -> Optional[asyncio.Task]:
        """
        Fire-and-forget schedule of *coro* on the loop.

        Safe to call from any thread, including the loop thread.
        Returns the Task when called from the loop thread, else None
        (the concurrent.futures.Future is kept alive until done).
        """
        if not self.is_running or self._loop is None:
            try:
                coro.close()
            except Exception:
                pass
            return None

        if self.in_loop_thread():
            task = self._loop.create_task(coro)

            def _done(t: asyncio.Task) -> None:
                try:
                    exc = t.exception()
                    if exc is not None:
                        logger.debug("Background task error: %s", exc)
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass

            task.add_done_callback(_done)
            return task

        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)

        def _done_cb(f: Future) -> None:
            try:
                f.result()
            except Exception as exc:
                logger.debug("Background task error: %s", exc)

        fut.add_done_callback(_done_cb)
        return None

    def run(self, coro: Coroutine[Any, Any, T], timeout: Optional[float] = 60.0) -> T:
        """
        Block until *coro* finishes; re-raise exceptions from the coro.

        Must NOT be called from the loop thread (deadlock). Use
        ``await coro`` or ``create_task`` there instead.
        """
        if self.in_loop_thread():
            try:
                coro.close()
            except Exception:
                pass
            raise RuntimeError(
                "LoopRunner.run() called from the loop thread – "
                "this would deadlock. Use create_task() or await instead."
            )
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

    def stop(self, timeout: float = 8.0) -> None:
        with self._state_lock:
            if self._stopped:
                return
            self._stopped = True
            loop = self._loop
            thread = self._thread

        if loop is not None and thread is not None and thread.is_alive():
            def _cancel_and_stop() -> None:
                current = asyncio.current_task(loop=loop)
                try:
                    for task in asyncio.all_tasks(loop):
                        if task is not current and not task.done():
                            task.cancel()
                except Exception:
                    pass
                loop.stop()

            if self.in_loop_thread():
                # Never join the current thread. The loop exits after the
                # currently executing callback/coroutine yields control.
                _cancel_and_stop()
                return

            try:
                loop.call_soon_threadsafe(_cancel_and_stop)
            except RuntimeError:
                pass  # loop already closed
            thread.join(timeout=timeout)
            if thread.is_alive():
                logger.warning("LoopRunner thread did not stop within %.1fs", timeout)
                return

        with self._state_lock:
            self._thread = None
            self._loop = None
            self._thread_id = None
        logger.debug("LoopRunner stopped")
