"""
Contact management: list, add, search.
"""

import time
from typing import List, Optional

from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from soropy import constants as C
from soropy.types import ContactInfo
from soropy.utils import (
    get_logger,
    normalize_phone,
    safe_click,
    fire_input_events,
)
from soropy.exceptions import ContactError

logger = get_logger("soropy.contacts")


class ContactManager:
    """Manage contacts inside Soroush Plus web."""

    def __init__(self, driver: WebDriver, chat_manager):
        self._driver = driver
        self._chat = chat_manager  # for tab navigation

    def open_contacts_section(self) -> bool:
        """Navigate to the contacts section in the account tab."""
        return self._chat.click_account_item(C.ICON_CONTACTS, "مخاطبین")

    # ────────────────────────────────────────────────────
    #  List contacts
    # ────────────────────────────────────────────────────

    def _get_visible_names(self) -> List[str]:
        try:
            return (
                self._driver.execute_script(
                    """
                    var names = [];
                    var items = document.querySelectorAll(
                        'a.ListItem-button, .ListItem-button'
                    );
                    for (var i = 0; i < items.length; i++) {
                        var h3 = items[i].querySelector('h3, .fullName');
                        if (h3) {
                            var n = h3.textContent.trim();
                            if (n && n.length < 100 && names.indexOf(n) === -1) {
                                names.push(n);
                            }
                        }
                    }
                    return names;
                    """
                )
                or []
            )
        except Exception:
            return []

    def list_contacts(self) -> List[str]:
        """Return all contact names (scrolling to collect them all)."""
        time.sleep(1)

        # Find scrollable container
        scroll = None
        for sel in [".os-viewport", "[class*='scroll']", ".custom-scroll"]:
            try:
                for c in self._driver.find_elements(By.CSS_SELECTOR, sel):
                    if c.size["height"] > 100 and c.is_displayed():
                        scroll = c
                        break
                if scroll:
                    break
            except Exception:
                continue

        all_names = self._get_visible_names()
        no_new = 0

        if scroll:
            for _ in range(30):
                try:
                    self._driver.execute_script(
                        "arguments[0].scrollTop += arguments[0].clientHeight;", scroll
                    )
                except Exception:
                    break
                time.sleep(0.8)
                new = self._get_visible_names()
                added = 0
                for n in new:
                    if n not in all_names:
                        all_names.append(n)
                        added += 1
                if added == 0:
                    no_new += 1
                    if no_new >= 3:
                        break
                else:
                    no_new = 0

        logger.info("Found %d contacts", len(all_names))
        return all_names

    # ────────────────────────────────────────────────────
    #  Add a new contact
    # ────────────────────────────────────────────────────

    def add_contact(
        self,
        phone: str,
        first_name: str,
        last_name: str = "",
    ) -> bool:
        """
        Add a new contact via the UI form.

        Parameters
        ----------
        phone : str
            Raw phone number (will be normalised).
        first_name : str
            Required.
        last_name : str
            Optional family name.

        Returns
        -------
        bool  – True on success.
        """
        norm_phone = normalize_phone(phone)
        if not first_name:
            raise ContactError("first_name is required")

        # Click the "+" button
        if not self._open_new_contact_form():
            raise ContactError("Could not open new-contact form")

        # Wait for the form
        time.sleep(1)
        try:
            WebDriverWait(self._driver, 8).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, C.SEL_CONTACT_FORM)
                )
            )
        except Exception:
            logger.warning("Contact form may not have appeared")

        time.sleep(0.5)

        # Fill fields
        try:
            inputs = self._driver.find_elements(By.CSS_SELECTOR, C.SEL_CONTACT_FORM_INPUTS)
            if len(inputs) < 2:
                self._cancel_dialog()
                raise ContactError(f"Expected ≥2 form fields, found {len(inputs)}")

            # Phone
            self._fill_field(inputs[0], norm_phone)
            logger.info("Phone filled: %s", norm_phone)
            time.sleep(0.5)

            # Name
            self._fill_field(inputs[1], first_name)
            logger.info("Name filled: %s", first_name)
            time.sleep(0.5)

            # Family
            if last_name and len(inputs) >= 3:
                self._fill_field(inputs[2], last_name)
                logger.info("Family filled: %s", last_name)
                time.sleep(0.3)

        except ContactError:
            raise
        except Exception as e:
            self._cancel_dialog()
            raise ContactError(f"Error filling form: {e}")

        time.sleep(1)

        # Confirm
        if not self._click_confirm():
            self._cancel_dialog()
            raise ContactError("Confirm button not found or click failed")

        logger.info("Contact added: %s %s (%s)", first_name, last_name, norm_phone)
        time.sleep(2)
        return True

    def _fill_field(self, element, value: str):
        """Focus a form field, clear it, type value, fire events."""
        self._driver.execute_script("arguments[0].focus();", element)
        time.sleep(0.2)
        element.send_keys(Keys.CONTROL + "a")
        element.send_keys(Keys.DELETE)
        time.sleep(0.2)
        for ch in value:
            element.send_keys(ch)
            time.sleep(0.05)
        fire_input_events(self._driver, element)

    def _open_new_contact_form(self) -> bool:
        """Click + → "ایجاد مخاطب جدید"."""
        # Try CSS
        for strategy in range(3):
            try:
                if strategy == 0:
                    self._driver.execute_script(
                        """
                        var c = document.querySelector('.NewContactButton');
                        if (c) { var b = c.querySelector('button.round'); if (b) b.click(); }
                        """
                    )
                elif strategy == 1:
                    btn = self._driver.find_element(
                        By.CSS_SELECTOR, C.SEL_NEW_CONTACT_BUTTON
                    )
                    self._driver.execute_script("arguments[0].click();", btn)
                else:
                    btn = self._driver.find_element(
                        By.CSS_SELECTOR, "button[title='مخاطب جدید']"
                    )
                    self._driver.execute_script("arguments[0].click();", btn)

                time.sleep(1)

                # Click "ایجاد مخاطب جدید" in the dropdown
                clicked = self._driver.execute_script(
                    """
                    var items = document.querySelectorAll('.MenuItem');
                    for (var i = 0; i < items.length; i++) {
                        if (items[i].textContent.indexOf('ایجاد مخاطب') !== -1) {
                            items[i].click(); return true;
                        }
                    }
                    return false;
                    """
                )
                if clicked:
                    return True
            except Exception:
                continue

        return False

    def _click_confirm(self) -> bool:
        """Click the confirm button in the dialog."""
        try:
            btns = self._driver.find_elements(By.CSS_SELECTOR, C.SEL_CONFIRM_BUTTON)
            target = None
            for btn in btns:
                try:
                    text = btn.text.strip()
                    if "تأیید" in text or "تایید" in text:
                        target = btn
                        break
                except Exception:
                    pass
            if not target and btns:
                target = btns[-1]

            if target:
                self._driver.execute_script(
                    """
                    var btn = arguments[0];
                    btn.removeAttribute('disabled');
                    btn.classList.remove('disabled');
                    btn.click();
                    """,
                    target,
                )
                return True
        except Exception:
            pass

        # Fallback JS
        try:
            result = self._driver.execute_script(
                """
                var btns = document.querySelectorAll('.dialog-buttons button');
                for (var i = btns.length - 1; i >= 0; i--) {
                    var t = btns[i].textContent.trim();
                    if (t.indexOf('تأیید') !== -1 || t.indexOf('تایید') !== -1 || t.indexOf('OK') !== -1) {
                        btns[i].removeAttribute('disabled');
                        btns[i].classList.remove('disabled');
                        btns[i].click();
                        return true;
                    }
                }
                if (btns.length > 0) { btns[btns.length-1].click(); return true; }
                return false;
                """
            )
            return bool(result)
        except Exception:
            return False

    def _cancel_dialog(self):
        try:
            self._driver.execute_script(
                """
                var btns = document.querySelectorAll('.dialog-buttons button');
                for (var i = 0; i < btns.length; i++) {
                    if (btns[i].textContent.indexOf('لغو') !== -1) {
                        btns[i].click(); return;
                    }
                }
                """
            )
        except Exception:
            try:
                self._driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            except Exception:
                pass
        time.sleep(1)

    # ────────────────────────────────────────────────────
    #  Search
    # ────────────────────────────────────────────────────

    def search(self, query: str) -> List[str]:
        """Search contacts and return matching names."""
        if not query:
            return []

        # Remove any modal backdrop
        try:
            self._driver.execute_script(
                """
                var b = document.querySelectorAll('.modal-backdrop');
                for (var i = 0; i < b.length; i++) b[i].style.display = 'none';
                """
            )
            time.sleep(0.3)
        except Exception:
            pass

        search_input = self._find_search_input()
        if not search_input:
            logger.error("Search input not found")
            return []

        # Type query using native setter for React compatibility
        try:
            self._driver.execute_script(
                """
                var el = arguments[0];
                var q = arguments[1];
                el.focus();
                el.value = '';
                el.dispatchEvent(new Event('input', {bubbles:true}));
                var setter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value'
                ).set;
                setter.call(el, q);
                el.dispatchEvent(new Event('input', {bubbles:true}));
                el.dispatchEvent(new Event('change', {bubbles:true}));
                """,
                search_input,
                query,
            )
            time.sleep(2)
        except Exception as e:
            logger.error("Search typing failed: %s", e)
            return []

        results = self._get_visible_names()

        # Clear search
        try:
            self._driver.execute_script(
                """
                var el = arguments[0];
                el.value = '';
                el.dispatchEvent(new Event('input', {bubbles:true}));
                el.dispatchEvent(new Event('change', {bubbles:true}));
                """,
                search_input,
            )
            time.sleep(1)
        except Exception:
            pass

        logger.info("Search '%s': %d results", query, len(results))
        return results

    def _find_search_input(self):
        for by, val in [
            (By.ID, C.SEL_SEARCH_INPUT_ID),
            (By.CSS_SELECTOR, "input[placeholder*='جستجوی مخاطب']"),
        ]:
            try:
                el = self._driver.find_element(by, val)
                if el.is_displayed():
                    return el
            except Exception:
                pass
        try:
            return self._driver.execute_script(
                """
                var inputs = document.querySelectorAll('input');
                for (var i = 0; i < inputs.length; i++) {
                    var ph = inputs[i].placeholder || '';
                    var id = inputs[i].id || '';
                    if (ph.indexOf('جستجو') !== -1 || id === 'search-input') return inputs[i];
                }
                return null;
                """
            )
        except Exception:
            return None