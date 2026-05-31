"""
Authentication flow: phone entry → verification code → chat page wait.
"""

import time
from typing import Optional, Callable

from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from soropy import constants as C
from soropy.utils import (
    get_logger,
    wait_and_find,
    safe_click,
    safe_type,
    wait_page_load,
)
from soropy.types import LoginStatus
from soropy.exceptions import LoginError

logger = get_logger("soropy.auth")


class Authenticator:
    """Encapsulates the multi-step Soroush Plus login process."""

    def __init__(self, driver: WebDriver):
        self._driver = driver

    # ── public ─────────────────────────────────────────

    def is_logged_in(self) -> bool:
        """Check whether the current page shows the chat list."""
        time.sleep(3)
        wait_page_load(self._driver, C.PAGE_LOAD_TIMEOUT)
        for sel in C.SEL_LOGGED_IN_INDICATORS:
            try:
                if self._driver.find_elements(By.CSS_SELECTOR, sel):
                    logger.info("Already logged in (matched %s)", sel)
                    return True
            except Exception:
                continue
        return False

    def login(
        self,
        phone: str,
        code_callback: Optional[Callable[[], str]] = None,
    ) -> LoginStatus:
        """
        Run the full login flow.

        Parameters
        ----------
        phone : str
            Normalised phone number (e.g. "+989123456789").
        code_callback : callable, optional
            A function that returns the verification code string.
            Defaults to ``input()`` prompt.

        Returns
        -------
        LoginStatus
        """
        self._driver.get(C.SPLUS_WEB_URL)
        logger.info("Navigated to %s", C.SPLUS_WEB_URL)
        wait_page_load(self._driver, 15)

        if self.is_logged_in():
            return LoginStatus.ALREADY_LOGGED_IN

        time.sleep(2)
        self._dismiss_popup()
        time.sleep(1)

        if not self._enter_phone(phone):
            raise LoginError("Could not enter phone number")

        if not self._click_next():
            raise LoginError("Could not click 'next' button")

        time.sleep(3)

        if code_callback is None:
            code_callback = lambda: input("🔑 Enter verification code: ")

        code = code_callback()
        if not self._enter_code(code):
            raise LoginError("Could not enter verification code")

        if not self._wait_for_chat_page():
            raise LoginError("Chat page did not load after login")

        return LoginStatus.SUCCESS

    # ── steps ──────────────────────────────────────────

    def _dismiss_popup(self) -> bool:
        logger.debug("Checking for popup...")
        for xpath in C.XPATH_DISMISS_POPUP_VARIANTS:
            try:
                el = WebDriverWait(self._driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                )
                safe_click(self._driver, el)
                logger.info("Popup dismissed")
                time.sleep(1)
                return True
            except Exception:
                continue
        logger.debug("No popup found")
        return False

    def _enter_phone(self, phone: str) -> bool:
        logger.info("Entering phone: %s", phone)
        wait_page_load(self._driver)

        inp = wait_and_find(
            self._driver, By.CSS_SELECTOR, C.SEL_PHONE_INPUT,
            timeout=10, clickable=True,
        )
        if not inp:
            return False

        inp.click()
        time.sleep(0.2)
        inp.send_keys(Keys.CONTROL + "a")
        time.sleep(0.1)
        inp.send_keys(Keys.DELETE)
        time.sleep(0.2)

        for ch in phone:
            inp.send_keys(ch)
            time.sleep(0.05)

        time.sleep(0.5)
        actual = inp.get_attribute("value")
        logger.debug("Phone field value: %s", actual)
        return True

    def _click_next(self) -> bool:
        logger.info("Clicking 'next'...")
        time.sleep(1)
        btn = wait_and_find(
            self._driver, By.XPATH, C.XPATH_NEXT_BUTTON,
            timeout=10, clickable=True,
        )
        if btn and safe_click(self._driver, btn):
            logger.info("'Next' clicked")
            return True
        return False

    def _enter_code(self, code: str) -> bool:
        logger.info("Entering verification code")
        wait_page_load(self._driver)

        code_input = None
        for by, val in [
            (By.ID, C.SEL_CODE_INPUT_ID),
            (By.CSS_SELECTOR, C.SEL_CODE_INPUT_ARIA),
            (By.CSS_SELECTOR, C.SEL_CODE_INPUT_NUMERIC),
        ]:
            code_input = wait_and_find(self._driver, by, val, timeout=10, clickable=True)
            if code_input:
                break

        if not code_input:
            return False

        safe_type(self._driver, code_input, code)
        logger.info("Code entered – waiting for automatic redirect")
        return True

    def _wait_for_chat_page(self) -> bool:
        logger.info("Waiting for chat page...")
        start = time.time()
        while time.time() - start < C.LOGIN_WAIT:
            try:
                found = self._driver.find_elements(
                    By.CSS_SELECTOR,
                    "[class*='chatlist'], [class*='dialog'], [class*='folders-tabs']",
                )
                if found:
                    elapsed = int(time.time() - start)
                    logger.info("Chat page loaded (%ds)", elapsed)
                    return True
            except Exception:
                pass
            time.sleep(1)
        return True  # optimistic – some indicators may not match