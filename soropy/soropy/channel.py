"""
Channel message posting via Saved Messages link trick.
"""

import time
from typing import Optional

from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from soropy import constants as C
from soropy.utils import get_logger, safe_click
from soropy.exceptions import ChannelError

logger = get_logger("soropy.channel")


class ChannelManager:
    """Post messages to channels using the Saved Messages workaround."""

    def __init__(self, driver: WebDriver, chat_manager):
        self._driver = driver
        self._chat = chat_manager

    def send_to_channel(self, channel_url: str, message: str) -> bool:
        """
        Send *message* to a channel.

        The flow:
        1. Open Saved Messages.
        2. Send the channel URL as a message.
        3. Click the resulting link to navigate to the channel.
        4. If admin → type and send *message*.
        5. Delete the link message from Saved Messages.

        Returns True if the message was sent (admin), False otherwise.
        """
        # Step 1: Go to Saved Messages
        if not self._chat.go_to_saved_messages():
            raise ChannelError("Cannot open Saved Messages")
        time.sleep(2)

        # Step 2: Send channel URL
        if not self._chat.type_and_send(channel_url):
            raise ChannelError("Failed to send channel URL in Saved Messages")
        time.sleep(3)

        # Step 3: Click the link
        if not self._click_channel_link(channel_url):
            raise ChannelError("Channel link not found in messages")
        time.sleep(4)

        from soropy.utils import wait_page_load
        wait_page_load(self._driver)

        # Step 4: Check admin status and send
        sent = False
        if self._chat.has_message_box():
            logger.info("Admin access confirmed – sending message")
            sent = self._chat.type_and_send(message)
            if sent:
                logger.info("Channel message sent: %s", message[:50])
        else:
            logger.warning("Not admin in this channel – no message box")

        # Step 5: Clean up Saved Messages
        self._cleanup_saved_link(channel_url)

        return sent

    # ────────────────────────────────────────────────────

    def _click_channel_link(self, channel_url: str) -> bool:
        """Find and click the channel link in the last messages."""
        # Strategy 1: find <a> elements
        try:
            links = self._driver.find_elements(
                By.CSS_SELECTOR, "a.text-entity-link, a[href], .text-entity-link"
            )
            clean = channel_url.replace("@", "")
            for link in reversed(links):
                try:
                    href = link.get_attribute("href") or ""
                    text = link.text.strip()
                    if clean in href or clean in text or channel_url in text:
                        safe_click(self._driver, link)
                        return True
                except Exception:
                    continue
        except Exception:
            pass

        # Strategy 2: JS
        try:
            clicked = self._driver.execute_script(
                """
                var url = arguments[0].replace('@', '');
                var links = document.querySelectorAll('a');
                for (var i = links.length - 1; i >= 0; i--) {
                    var href = links[i].href || '';
                    var text = links[i].textContent || '';
                    if (href.indexOf(url) !== -1 || text.indexOf(url) !== -1
                        || text.indexOf(arguments[0]) !== -1) {
                        links[i].click(); return true;
                    }
                }
                var msgs = document.querySelectorAll(
                    '.message-content, .Message, [class*="message"]'
                );
                for (var i = msgs.length - 1; i >= 0; i--) {
                    if (msgs[i].textContent.indexOf(arguments[0]) !== -1) {
                        var a = msgs[i].querySelector('a');
                        if (a) { a.click(); return true; }
                    }
                }
                return false;
                """,
                channel_url,
            )
            return bool(clicked)
        except Exception:
            return False

    def _cleanup_saved_link(self, channel_url: str):
        """Go back to Saved Messages and delete the link message."""
        logger.debug("Cleaning up link from Saved Messages")
        self._chat.go_back()
        time.sleep(1)
        self._chat.go_to_saved_messages()
        time.sleep(2)
        self._delete_message_containing(channel_url)
        self._chat.go_back()
        time.sleep(1)
        self._chat.click_bottom_tab(C.TAB_CHAT)

    def _delete_message_containing(self, text: str) -> bool:
        """Delete the last message containing *text*."""
        time.sleep(1)

        target = None
        try:
            msgs = self._driver.find_elements(
                By.CSS_SELECTOR, ".Message, .message, [class*='message']"
            )
            clean = text.replace("@", "")
            for msg in reversed(msgs):
                try:
                    if text in msg.text or clean in msg.text:
                        target = msg
                        break
                except Exception:
                    continue
            if not target and msgs:
                target = msgs[-1]
        except Exception:
            pass

        if not target:
            logger.debug("No message to delete")
            return False

        # Right-click
        try:
            ActionChains(self._driver).context_click(target).perform()
            time.sleep(1)
        except Exception:
            return False

        # Click delete
        delete_clicked = False
        try:
            btn = self._driver.find_element(By.CSS_SELECTOR, C.SEL_MENU_ITEM_DESTRUCTIVE)
            safe_click(self._driver, btn)
            delete_clicked = True
        except Exception:
            pass

        if not delete_clicked:
            try:
                delete_clicked = self._driver.execute_script(
                    """
                    var items = document.querySelectorAll('.MenuItem');
                    for (var i = 0; i < items.length; i++) {
                        if (items[i].textContent.indexOf('حذف') !== -1) {
                            items[i].click(); return true;
                        }
                    }
                    return false;
                    """
                )
            except Exception:
                pass

        if not delete_clicked:
            try:
                self._driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            except Exception:
                pass
            return False

        # Confirm
        time.sleep(1)
        try:
            confirm = WebDriverWait(self._driver, 3).until(
                EC.element_to_be_clickable(
                    (By.XPATH, C.XPATH_DELETE_CONFIRM)
                )
            )
            safe_click(self._driver, confirm)
        except Exception:
            pass

        time.sleep(1)
        logger.debug("Message deleted")
        return True