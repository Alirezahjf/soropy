"""
Utility helpers: logging, phone normalisation, safe Selenium wrappers.
"""

import time
import logging
import hashlib
from typing import Optional

from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
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

_PERSIAN_ARABIC_DIGITS = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)


def _ascii_phone_text(value: str) -> str:
    return str(value or "").translate(_PERSIAN_ARABIC_DIGITS)


def _digits_only(value: str) -> str:
    """Keep only ASCII digits from *value*."""
    return "".join(ch for ch in _ascii_phone_text(value) if "0" <= ch <= "9")


def _national_mobile_digits(phone: str) -> Optional[str]:
    """Return the ten national digits (9xxxxxxxxx), or None when malformed."""
    if phone is None:
        return None
    raw = _ascii_phone_text(phone).strip()
    if not raw:
        return None
    # Only conventional visual separators are accepted. Never silently strip
    # placeholders or arbitrary letters from an authentication identifier.
    allowed = set("0123456789+ -()")
    if any(ch not in allowed for ch in raw):
        return None
    if "+" in raw and (not raw.startswith("+") or raw.count("+") != 1):
        return None
    digits = _digits_only(raw)
    if digits.startswith("0098"):
        digits = digits[4:]
    elif digits.startswith("98"):
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = digits[1:]
    if len(digits) != 10 or not digits.startswith("9"):
        return None
    return digits if digits.isascii() and digits.isdigit() else None


def is_valid_iranian_mobile(phone: str) -> bool:
    """Validate 0912…, 912…, +98912…, 0098912… or 98912… formats."""
    return _national_mobile_digits(phone) is not None


def validate_phone(phone: str) -> str:
    """Validate and normalize an Iranian mobile to ``+98XXXXXXXXXX``."""
    if phone is None or not str(phone).strip():
        raise ValueError(
            "شماره تلفن خالی است. یک شماره واقعی وارد کنید "
            "(مثال: 09123456789)."
        )
    raw = str(phone).strip()
    national = _national_mobile_digits(raw)
    if national is None:
        raise ValueError(
            f"شماره نامعتبر: '{raw}'. "
            "شماره موبایل واقعی ۱۱ رقمی وارد کنید "
            "(مثال: 09123456789 یا +989123456789). "
            "placeholder مانند 0912xxxxxxx پذیرفته نیست."
        )
    return "+98" + national


def normalize_phone(phone: str) -> str:
    """Normalize common Iranian formats; use :func:`validate_phone` for auth."""
    if phone is None:
        raise ValueError("شماره تلفن None است.")
    national = _national_mobile_digits(str(phone))
    if national is not None:
        return "+98" + national

    # Backward-compatible best effort for non-auth callers. Validation remains
    # mandatory before login/contact import.
    digits = _digits_only(str(phone))
    if digits.startswith("0098"):
        digits = digits[4:]
    elif digits.startswith("98"):
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = digits[1:]
    return "+98" + digits


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