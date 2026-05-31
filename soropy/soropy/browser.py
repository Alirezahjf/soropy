"""
Browser (Chrome/Chromium) lifecycle management.

Handles driver creation with anti-detection, headless mode,
custom profiles, and teardown.
"""

import os
from typing import Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

from soropy.session import SessionManager
from soropy.utils import get_logger
from soropy.exceptions import BrowserError

logger = get_logger("soropy.browser")


class BrowserManager:
    """Creates and manages a Selenium Chrome WebDriver."""

    def __init__(
        self,
        phone: Optional[str] = None,
        headless: bool = False,
        session_manager: Optional[SessionManager] = None,
        window_size: str = "1300,900",
        extra_args: Optional[list] = None,
        chrome_binary: Optional[str] = None,
        chromedriver_path: Optional[str] = None,
    ):
        self._phone = phone
        self._headless = headless
        self._session_mgr = session_manager or SessionManager()
        self._window_size = window_size
        self._extra_args = extra_args or []
        self._chrome_binary = chrome_binary
        self._chromedriver_path = chromedriver_path
        self._driver: Optional[webdriver.Chrome] = None

    @property
    def driver(self) -> webdriver.Chrome:
        if self._driver is None:
            raise BrowserError("Browser not started. Call start() first.")
        return self._driver

    @property
    def is_running(self) -> bool:
        if self._driver is None:
            return False
        try:
            # If the browser window is closed this will throw
            _ = self._driver.title
            return True
        except Exception:
            return False

    def start(self) -> webdriver.Chrome:
        """Launch Chrome and return the WebDriver."""
        options = Options()

        # ── Anti-detection ────────────────────────────
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument(f"--window-size={self._window_size}")

        # ── Headless ──────────────────────────────────
        if self._headless:
            options.add_argument("--headless=new")
            options.add_argument("--disable-gpu")
            options.add_argument("--no-first-run")
            options.add_argument("--no-default-browser-check")
            logger.info("Headless mode enabled")

        # ── Session profile ───────────────────────────
        if self._phone:
            profile_path = self._session_mgr.get_path(self._phone)
            options.add_argument(f"--user-data-dir={profile_path}")
            logger.info("Session profile: %s", profile_path)

        # ── Custom binary ─────────────────────────────
        if self._chrome_binary:
            options.binary_location = self._chrome_binary

        # ── Extra args ────────────────────────────────
        for arg in self._extra_args:
            options.add_argument(arg)

        # ── Service ───────────────────────────────────
        service_kwargs = {}
        if self._chromedriver_path:
            service_kwargs["executable_path"] = self._chromedriver_path
        service = Service(**service_kwargs)

        try:
            self._driver = webdriver.Chrome(service=service, options=options)
            if not self._headless:
                self._driver.maximize_window()

            # Remove webdriver flag
            self._driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            logger.info("Browser started successfully")
            return self._driver
        except Exception as e:
            raise BrowserError(f"Failed to start Chrome: {e}")

    def stop(self) -> None:
        """Quit the browser."""
        if self._driver:
            try:
                self._driver.quit()
                logger.info("Browser stopped")
            except Exception:
                pass
            finally:
                self._driver = None

    def restart(self) -> webdriver.Chrome:
        """Stop and re-start."""
        self.stop()
        return self.start()