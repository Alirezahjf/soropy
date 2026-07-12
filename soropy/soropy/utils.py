"""
Utility helpers: logging, phone normalisation, safe Selenium wrappers.
"""

import os
import time
import logging
import hashlib
from typing import Optional

from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    StaleElementReferenceException,
    TimeoutException,
    ElementClickInterceptedException,
)

from soropy.constants import ELEMENT_RETRY_COUNT, SHORT_WAIT

# ─── Logger ────────────────────────────────────────────

_loggers = {}


def get_logger(name: str = "soropy", log_file: Optional[str] = None) -> logging.Logger:
    """Return (and cache) a logger with console + optional file output."""
    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if not logger.handlers:
        fmt = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(fmt)
        logger.addHandler(ch)

        if log_file:
            fh = logging.FileHandler(log_file, encoding="utf-8")
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(fmt)
            logger.addHandler(fh)

    _loggers[name] = logger
    return logger


# ─── Phone normalisation ──────────────────────────────

def _digits_only(value: str) -> str:
    """Keep only ASCII digits from *value*."""
    return "".join(ch for ch in value if ch.isdigit())


def is_valid_iranian_mobile(phone: str) -> bool:
    """
    Return True if *phone* looks like a real Iranian mobile number.

    Accepts: 0912…, 912…, +98912…, 0098912…, 98912…
    Rejects: placeholders like 0912xxxxxxx, too short/long, non-digits.
    """
    if phone is None:
        return False
    raw = (
        str(phone)
        .strip()
        .replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
    )
    if not raw:
        return False
    # Reject obvious placeholders (x, *, #, etc. mixed with digits)
    lower = raw.lower()
    if any(c in lower for c in ("x", "*", "#", "n", "y", "z")):
        # allow only if those chars are not standing in for digits
        # e.g. "0912xxxxxxx" → invalid
        stripped = lower
        for prefix in ("+98", "0098", "98", "0"):
            if stripped.startswith(prefix):
                stripped = stripped[len(prefix):]
                break
        body = "".join(ch for ch in stripped if ch.isalnum())
        if any(c.isalpha() or c in "*#" for c in body):
            return False

    digits = _digits_only(raw)
    if not digits:
        return False

    # Normalise to 10-digit national (9xxxxxxxxx)
    if digits.startswith("98") and len(digits) >= 12:
        digits = digits[2:]
    if digits.startswith("0") and len(digits) >= 11:
        digits = digits[1:]

    if len(digits) != 10:
        return False
    if not digits.startswith("9"):
        return False
    # All digits, real mobile prefix 9xx
    return digits.isdigit()


def validate_phone(phone: str) -> str:
    """
    Validate and normalise an Iranian mobile to ``+98XXXXXXXXXX``.

    Raises
    ------
    ValueError
        If the number is empty, placeholder, or not a valid mobile.
    """
    if phone is None or not str(phone).strip():
        raise ValueError(
            "شماره تلفن خالی است. یک شماره واقعی وارد کنید "
            "(مثال: 09123456789)."
        )
    raw = str(phone).strip()
    if not is_valid_iranian_mobile(raw):
        raise ValueError(
            f"شماره نامعتبر: '{raw}'. "
            "فقط رقم واقعی ایرانی بدهید "
            "(مثال: 09123456789 یا +989123456789). "
            "شماره‌هایی مثل 0912xxxxxxx قابل قبول نیستند."
        )
    return normalize_phone(raw)


def normalize_phone(phone: str) -> str:
    """
    Normalise any Iranian phone format to +98XXXXXXXXXX.

    Does **not** fully validate – use :func:`validate_phone` before login.

    Examples:
        >>> normalize_phone("09123456789")
        '+989123456789'
        >>> normalize_phone("+989123456789")
        '+989123456789'
        >>> normalize_phone("00989123456789")
        '+989123456789'
    """
    if phone is None:
        raise ValueError("شماره تلفن None است.")
    phone = (
        str(phone)
        .strip()
        .replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
    )
    # Drop non-digit noise except leading +
    if phone.startswith("+"):
        phone = "+" + _digits_only(phone)
    else:
        phone = _digits_only(phone)

    if phone.startswith("+98"):
        phone = phone[3:]
    elif phone.startswith("0098"):
        phone = phone[4:]
    elif phone.startswith("98") and len(phone) >= 12:
        phone = phone[2:]
    if phone.startswith("0"):
        phone = phone[1:]
    return "+98" + phone


# ─── Message hashing ─────────────────────────────────

def hash_message(chat_name: str, text: str) -> str:
    """Create a deterministic hash for a message to detect duplicates."""
    content = f"{chat_name}::{text.strip()}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


# ─── Safe Selenium helpers ────────────────────────────

def wait_and_find(
    driver: WebDriver,
    by: str,
    value: str,
    timeout: int = 15,
    clickable: bool = False,
) -> Optional[WebElement]:
    """
    Wait for an element with retry on stale references.
    Returns None instead of raising on timeout.
    """
    for attempt in range(ELEMENT_RETRY_COUNT):
        try:
            condition = (
                EC.element_to_be_clickable((by, value))
                if clickable
                else EC.presence_of_element_located((by, value))
            )
            el = WebDriverWait(driver, timeout).until(condition)
            # Touch the element to detect staleness immediately
            el.is_displayed()
            return el
        except StaleElementReferenceException:
            time.sleep(0.5)
        except TimeoutException:
            if attempt == ELEMENT_RETRY_COUNT - 1:
                return None
            time.sleep(0.5)
    return None


def safe_click(driver: WebDriver, element: WebElement) -> bool:
    """Scroll into view and click, falling back to JS click."""
    try:
        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center'});", element
        )
        time.sleep(SHORT_WAIT)
        try:
            element.click()
        except ElementClickInterceptedException:
            driver.execute_script("arguments[0].click();", element)
        return True
    except Exception:
        return False


def safe_type(driver: WebDriver, element: WebElement, text: str) -> bool:
    """Focus, clear, and type into an element."""
    try:
        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center'});", element
        )
        time.sleep(SHORT_WAIT)
        element.click()
        time.sleep(0.2)
        element.clear()
        time.sleep(0.2)
        element.send_keys(text)
        return True
    except Exception:
        return False


def wait_page_load(driver: WebDriver, timeout: int = 10) -> None:
    """Block until document.readyState == 'complete'."""
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
    except Exception:
        pass
    time.sleep(0.5)


def fire_input_events(driver: WebDriver, element: WebElement) -> None:
    """Dispatch input + change events so React/Vue picks up value changes."""
    driver.execute_script(
        """
        var el = arguments[0];
        el.dispatchEvent(new Event('input', {bubbles: true}));
        el.dispatchEvent(new Event('change', {bubbles: true}));
        """,
        element,
    )