"""
Chat list extraction, navigation, and message sending.
"""

import time
from typing import List, Optional, Dict

from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from soropy import constants as C
from soropy.types import ChatCollection, SendResult, UnreadChat, MessageInfo
from soropy.utils import (
    get_logger,
    wait_and_find,
    safe_click,
    wait_page_load,
)
from soropy.exceptions import ChatError, MessageError

logger = get_logger("soropy.chat")


class ChatManager:
    """All operations related to the chat list and individual chats."""

    def __init__(self, driver: WebDriver):
        self._driver = driver

    # ════════════════════════════════════════════════════
    #  Bottom / sidebar tab navigation
    # ════════════════════════════════════════════════════

    def click_bottom_tab(self, tab_name: str) -> bool:
        """Click one of the bottom navigation tabs (گفتگو, حساب من, …)."""
        logger.debug("Clicking bottom tab: %s", tab_name)

        # Strategy 1: CSS query
        try:
            tabs = self._driver.find_elements(By.CSS_SELECTOR, C.SEL_BOTTOM_TABS)
            for tab in tabs:
                try:
                    if tab_name in tab.text.strip() or tab.text.strip() in tab_name:
                        self._driver.execute_script("arguments[0].click();", tab)
                        time.sleep(2)
                        return True
                except Exception:
                    continue
        except Exception:
            pass

        # Strategy 2: JS full scan
        try:
            clicked = self._driver.execute_script(
                """
                var tabs = document.querySelectorAll('.bottomTabs .tab');
                for (var i = 0; i < tabs.length; i++) {
                    if (tabs[i].textContent.indexOf(arguments[0]) !== -1) {
                        tabs[i].click(); return true;
                    }
                }
                return false;
                """,
                tab_name,
            )
            if clicked:
                time.sleep(2)
                return True
        except Exception:
            pass

        # Strategy 3: variants (half-space)
        for variant in [tab_name, tab_name.replace("\u200c", " "), tab_name.replace("\u200c", "")]:
            try:
                el = self._driver.find_element(
                    By.XPATH,
                    f"//div[contains(@class, 'bottomTabs')]//div[contains(text(), '{variant}')]",
                )
                self._driver.execute_script("arguments[0].click();", el)
                time.sleep(2)
                return True
            except Exception:
                continue

        logger.warning("Bottom tab '%s' not found", tab_name)
        return False

    def click_chat_tab(self, tab_name: str) -> bool:
        """Click a tab above the chat list (همه, شخصی, گروه‌ها, کانال‌ها)."""
        variants = [tab_name]
        if "\u200c" in tab_name:
            variants.append(tab_name.replace("\u200c", " "))
            variants.append(tab_name.replace("\u200c", ""))
        else:
            variants.append(tab_name.replace(" ", "\u200c"))

        for variant in variants:
            for by, val in [
                (By.XPATH, f"//*[contains(text(), '{variant}')]"),
                (By.XPATH, f"//span[contains(text(), '{variant}')]"),
                (By.XPATH, f"//div[contains(text(), '{variant}')]"),
            ]:
                try:
                    tab = WebDriverWait(self._driver, 3).until(
                        EC.element_to_be_clickable((by, val))
                    )
                    safe_click(self._driver, tab)
                    time.sleep(2)
                    return True
                except Exception:
                    continue
        return False

    # ════════════════════════════════════════════════════
    #  Chat list extraction
    # ════════════════════════════════════════════════════

    def extract_visible_chats(self) -> List[str]:
        """Return chat names currently visible on screen."""
        names: List[str] = []
        strategies = list(zip(C.SEL_CHAT_CONTAINERS, C.SEL_CHAT_NAME_SELECTORS))
        # Pad shorter list
        while len(strategies) < len(C.SEL_CHAT_CONTAINERS):
            strategies.append(
                (C.SEL_CHAT_CONTAINERS[len(strategies)], C.SEL_CHAT_NAME_SELECTORS[-1])
            )

        for container_sel, name_sel in strategies:
            try:
                containers = self._driver.find_elements(By.CSS_SELECTOR, container_sel)
                if not containers:
                    continue
                for container in containers:
                    try:
                        name_el = container.find_element(By.CSS_SELECTOR, name_sel)
                        name = name_el.text.strip()
                        if name and name not in names and len(name) < 100:
                            names.append(name)
                    except Exception:
                        try:
                            name = container.text.strip().split("\n")[0]
                            if name and name not in names and len(name) < 100:
                                names.append(name)
                        except Exception:
                            continue
                if names:
                    break
            except Exception:
                continue
        return names

    def _find_scroll_container(self):
        for sel in C.SEL_SCROLL_CONTAINERS:
            try:
                for c in self._driver.find_elements(By.CSS_SELECTOR, sel):
                    if c.size["height"] > 100:
                        return c
            except Exception:
                continue
        return None

    def scroll_and_collect(self, existing: List[str]) -> List[str]:
        """Scroll through the chat list and accumulate names."""
        sc = self._find_scroll_container()
        if not sc:
            return list(existing)

        all_names = list(existing)
        no_new = 0
        for _ in range(20):
            try:
                self._driver.execute_script(
                    "arguments[0].scrollTop += arguments[0].clientHeight;", sc
                )
            except Exception:
                break
            time.sleep(1)
            added = 0
            for name in self.extract_visible_chats():
                if name not in all_names:
                    all_names.append(name)
                    added += 1
            if added == 0:
                no_new += 1
                if no_new >= 3:
                    break
            else:
                no_new = 0
                logger.debug("+%d chats (total %d)", added, len(all_names))
        return all_names

    def get_all_chats(self) -> ChatCollection:
        """
        Switch to the Chat bottom tab, iterate all sub-tabs,
        and return a ChatCollection.
        """
        self.click_bottom_tab(C.TAB_CHAT)
        time.sleep(2)

        result = ChatCollection()
        tab_map = {
            C.TAB_ALL: "all",
            C.TAB_PERSONAL: "personal",
            C.TAB_GROUPS: "groups",
            C.TAB_CHANNELS: "channels",
        }

        for tab_name, attr in tab_map.items():
            logger.info("Extracting tab: %s", tab_name)
            if not self.click_chat_tab(tab_name):
                logger.warning("Tab '%s' not found", tab_name)
                continue
            time.sleep(2)
            names = self.extract_visible_chats()
            names = self.scroll_and_collect(names)
            setattr(result, attr, names)
            logger.info("Tab '%s': %d chats", tab_name, len(names))

        logger.info("Total chats extracted: %d", result.total_count)
        return result

    # ════════════════════════════════════════════════════
    #  Navigate into a specific chat
    # ════════════════════════════════════════════════════

    def click_on_chat(self, chat_name: str) -> bool:
        """Open a chat by its display name."""
        # Scroll to top first
        try:
            for sc in self._driver.find_elements(
                By.CSS_SELECTOR, ".os-viewport, [class*='scroll']"
            ):
                self._driver.execute_script("arguments[0].scrollTop = 0;", sc)
        except Exception:
            pass
        time.sleep(1)

        for attempt in range(5):
            # Python-side search
            try:
                for link in self._driver.find_elements(By.CSS_SELECTOR, C.SEL_CHAT_LINK):
                    try:
                        name_el = link.find_element(By.CSS_SELECTOR, C.SEL_CHAT_FULLNAME)
                        if chat_name in name_el.text.strip():
                            self._driver.execute_script(
                                "arguments[0].scrollIntoView({block:'center'});", link
                            )
                            time.sleep(0.5)
                            safe_click(self._driver, link)
                            time.sleep(2)
                            return True
                    except Exception:
                        continue
            except Exception:
                pass

            # JS fallback
            try:
                clicked = self._driver.execute_script(
                    """
                    var links = document.querySelectorAll('a.ListItem-button');
                    for (var i = 0; i < links.length; i++) {
                        var h3 = links[i].querySelector('h3.fullName, h3, .fullName');
                        if (h3 && h3.textContent.indexOf(arguments[0]) !== -1) {
                            links[i].scrollIntoView({block: 'center'});
                            links[i].click();
                            return true;
                        }
                    }
                    return false;
                    """,
                    chat_name,
                )
                if clicked:
                    time.sleep(2)
                    return True
            except Exception:
                pass

            # Scroll down a bit and retry
            try:
                for sc in self._driver.find_elements(By.CSS_SELECTOR, ".os-viewport"):
                    self._driver.execute_script(
                        "arguments[0].scrollTop += 300;", sc
                    )
            except Exception:
                pass
            time.sleep(1)

        logger.warning("Chat '%s' not found after 5 attempts", chat_name)
        return False

    # ════════════════════════════════════════════════════
    #  Message box detection
    # ════════════════════════════════════════════════════

    def has_message_box(self) -> bool:
        """Return True if there is a visible message input box."""
        time.sleep(2)

        # Quick checks
        for by, val in [
            (By.ID, C.SEL_MSG_INPUT_ID),
            (By.CSS_SELECTOR, C.SEL_MSG_INPUT_ARIA),
        ]:
            try:
                el = self._driver.find_element(by, val)
                if el.is_displayed():
                    return True
            except Exception:
                pass

        try:
            wrapper = self._driver.find_element(By.CSS_SELECTOR, C.SEL_MSG_INPUT_WRAPPER)
            if wrapper.is_displayed():
                try:
                    ed = wrapper.find_element(By.CSS_SELECTOR, C.SEL_CONTENTEDITABLE)
                    if ed.is_displayed():
                        return True
                except Exception:
                    time.sleep(2)
                    try:
                        ed = wrapper.find_element(By.CSS_SELECTOR, C.SEL_CONTENTEDITABLE)
                        if ed.is_displayed():
                            return True
                    except Exception:
                        pass
        except Exception:
            pass

        try:
            container = self._driver.find_element(By.ID, C.SEL_MSG_INPUT_TEXT_ID)
            if container.is_displayed():
                return True
        except Exception:
            pass

        # JS comprehensive check
        try:
            found = self._driver.execute_script(
                """
                var el = document.getElementById('editable-message-text');
                if (el && el.offsetParent !== null) return 'id';
                el = document.querySelector('div[contenteditable="true"][aria-label="پیام"]');
                if (el && el.offsetParent !== null) return 'aria';
                el = document.querySelector('.message-input-wrapper');
                if (el && el.offsetParent !== null) {
                    var ed = el.querySelector('div[contenteditable="true"]');
                    if (ed && ed.offsetParent !== null) return 'wrapper';
                }
                el = document.getElementById('message-input-text');
                if (el && el.offsetParent !== null) return 'input-text';
                var all = document.querySelectorAll('div[contenteditable="true"]');
                for (var i = 0; i < all.length; i++) {
                    if (all[i].offsetParent !== null) return 'any';
                }
                return null;
                """
            )
            if found:
                return True
        except Exception:
            pass

        return False

    # ════════════════════════════════════════════════════
    #  Find the message input element
    # ════════════════════════════════════════════════════

    def _find_message_box(self):
        """Locate the contenteditable message input."""
        # Method 1: by ID
        try:
            el = self._driver.find_element(By.ID, C.SEL_MSG_INPUT_ID)
            if el.is_displayed():
                return el
        except Exception:
            pass

        # Method 2: aria-label
        try:
            el = self._driver.find_element(By.CSS_SELECTOR, C.SEL_MSG_INPUT_ARIA)
            if el.is_displayed():
                return el
        except Exception:
            pass

        # Method 3: wrapper
        try:
            wrapper = self._driver.find_element(By.CSS_SELECTOR, C.SEL_MSG_INPUT_WRAPPER)
            el = wrapper.find_element(By.CSS_SELECTOR, C.SEL_CONTENTEDITABLE)
            if el.is_displayed():
                return el
        except Exception:
            pass

        # Method 4: message-input-text container
        try:
            container = self._driver.find_element(By.ID, C.SEL_MSG_INPUT_TEXT_ID)
            el = container.find_element(By.CSS_SELECTOR, C.SEL_CONTENTEDITABLE)
            if el.is_displayed():
                return el
        except Exception:
            pass

        # Method 5: JS comprehensive
        try:
            return self._driver.execute_script(
                """
                var el = document.getElementById('editable-message-text');
                if (el && el.offsetParent !== null) return el;
                el = document.querySelector('div[contenteditable="true"][aria-label="پیام"]');
                if (el && el.offsetParent !== null) return el;
                el = document.querySelector('.message-input-wrapper div[contenteditable="true"]');
                if (el && el.offsetParent !== null) return el;
                el = document.querySelector('#message-input-text div[contenteditable="true"]');
                if (el && el.offsetParent !== null) return el;
                var all = document.querySelectorAll('div[contenteditable="true"]');
                for (var i = 0; i < all.length; i++) {
                    if (all[i].offsetParent !== null) return all[i];
                }
                return null;
                """
            )
        except Exception:
            pass

        return None

    # ════════════════════════════════════════════════════
    #  Type and send a message
    # ════════════════════════════════════════════════════

    def type_and_send(self, message: str) -> bool:
        """Type *message* into the active chat and press Enter."""
        time.sleep(1)
        msg_box = self._find_message_box()
        if not msg_box:
            logger.error("Message box not found")
            return False

        # Focus
        try:
            self._driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", msg_box
            )
            time.sleep(C.SHORT_WAIT)
            self._driver.execute_script("arguments[0].focus();", msg_box)
            time.sleep(0.2)
            msg_box.click()
            time.sleep(C.SHORT_WAIT)
        except Exception:
            pass

        # Clear
        try:
            self._driver.execute_script("arguments[0].innerHTML = '';", msg_box)
        except Exception:
            pass
        time.sleep(C.SHORT_WAIT)

        # Type
        typed = False
        try:
            msg_box.send_keys(message)
            typed = True
        except Exception:
            pass

        if not typed:
            try:
                self._driver.execute_script(
                    """
                    var el = arguments[0]; el.focus();
                    el.innerHTML = arguments[1];
                    el.dispatchEvent(new Event('input', {bubbles:true}));
                    """,
                    msg_box,
                    message,
                )
                typed = True
            except Exception:
                logger.error("Failed to type message")
                return False

        time.sleep(0.5)

        # Verify something was typed
        try:
            content = (
                self._driver.execute_script(
                    "return arguments[0].textContent;", msg_box
                )
                or ""
            )
            if not content.strip():
                msg_box.click()
                time.sleep(C.SHORT_WAIT)
                msg_box.send_keys(message)
                time.sleep(0.5)
        except Exception:
            pass

        # Send (Enter key)
        time.sleep(C.SHORT_WAIT)
        try:
            msg_box.send_keys(Keys.ENTER)
        except Exception:
            try:
                self._driver.execute_script(
                    """
                    arguments[0].dispatchEvent(new KeyboardEvent('keydown',
                        {key:'Enter',code:'Enter',keyCode:13,which:13,bubbles:true}));
                    """,
                    msg_box,
                )
            except Exception:
                pass

        time.sleep(1)
        logger.info("Message sent: %s", message[:50])
        return True

    # ════════════════════════════════════════════════════
    #  Go back to chat list
    # ════════════════════════════════════════════════════

    def go_back(self) -> bool:
        """Navigate back to the chat list."""
        for by, val in [
            (By.CSS_SELECTOR, "button.back-button"),
            (By.CSS_SELECTOR, "[class*='back-button']"),
            (By.CSS_SELECTOR, "button[class*='back']"),
            (By.XPATH, "//button[contains(@class, 'back')]"),
        ]:
            try:
                btn = self._driver.find_element(by, val)
                if btn.is_displayed():
                    safe_click(self._driver, btn)
                    time.sleep(1)
                    return True
            except Exception:
                continue
        # Fallback: Escape key
        try:
            self._driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            time.sleep(1)
            return True
        except Exception:
            pass
        return False

    # ════════════════════════════════════════════════════
    #  Unread messages
    # ════════════════════════════════════════════════════

    def get_unread_personal_chats(self) -> List[UnreadChat]:
        """Return list of private chats that have unread messages."""
        unread: List[UnreadChat] = []
        try:
            result = self._driver.execute_script(
                """
                var unread = [];
                var chats = document.querySelectorAll('.ListItem.Chat.private');
                for (var i = 0; i < chats.length; i++) {
                    var badge = chats[i].querySelector('.ChatBadge.unread');
                    if (badge) {
                        var countEl = badge.querySelector('span span, span');
                        var count = countEl ? parseInt(countEl.textContent.trim()) : 1;
                        var nameEl = chats[i].querySelector('h3.fullName, h3');
                        var name = nameEl ? nameEl.textContent.trim() : '';
                        if (name && count > 0) {
                            unread.push({name: name, count: count});
                        }
                    }
                }
                return unread;
                """
            )
            if result:
                for item in result:
                    unread.append(
                        UnreadChat(
                            name=item.get("name", ""),
                            count=item.get("count", 1),
                        )
                    )
        except Exception as e:
            logger.error("Failed to get unread chats: %s", e)
        return unread

    def get_unread_messages_in_chat(self, count: int) -> List[MessageInfo]:
        """Read the last *count* incoming messages in the open chat."""
        messages: List[MessageInfo] = []
        try:
            # Scroll to bottom
            self._driver.execute_script(
                """
                var containers = document.querySelectorAll(
                    '.messages-container, [class*="messages"]'
                );
                for (var i = 0; i < containers.length; i++) {
                    containers[i].scrollTop = containers[i].scrollHeight;
                }
                """
            )
            time.sleep(1)

            result = self._driver.execute_script(
                """
                var msgs = [];
                var allMsgs = document.querySelectorAll('.Message.is-in, [class*="message"][class*="in"]');
                if (allMsgs.length === 0) {
                    allMsgs = document.querySelectorAll('.Message');
                }
                var inMsgs = [];
                for (var i = 0; i < allMsgs.length; i++) {
                    var el = allMsgs[i];
                    var isOutgoing = el.classList.contains('is-out') ||
                                     el.querySelector('[class*="outgoing"]') !== null;
                    if (!isOutgoing) {
                        var textEl = el.querySelector('.text-content, .message-text, [class*="text"]');
                        var text = textEl ? textEl.textContent.trim() : el.textContent.trim();
                        if (text && text.length < 500) {
                            inMsgs.push({text: text, element_index: i});
                        }
                    }
                }
                var start = Math.max(0, inMsgs.length - arguments[0]);
                for (var i = start; i < inMsgs.length; i++) {
                    msgs.push(inMsgs[i]);
                }
                return msgs;
                """,
                count,
            )
            if result:
                for item in result:
                    messages.append(
                        MessageInfo(
                            text=item.get("text", ""),
                            element_index=item.get("element_index", 0),
                        )
                    )
        except Exception as e:
            logger.error("Failed to read unread messages: %s", e)
        return messages

    # ════════════════════════════════════════════════════
    #  Reply to a specific message
    # ════════════════════════════════════════════════════

    def reply_to_message(self, element_index: int, reply_text: str) -> bool:
        """
        Right-click on message at *element_index*, choose Reply,
        then type and send *reply_text*.
        """
        from selenium.webdriver.common.action_chains import ActionChains

        try:
            all_msgs = self._driver.find_elements(By.CSS_SELECTOR, C.SEL_MESSAGE)
            if element_index >= len(all_msgs):
                return self.type_and_send(reply_text)

            target = all_msgs[element_index]

            # Right-click
            ActionChains(self._driver).context_click(target).perform()
            time.sleep(1)

            # Click "پاسخ" (Reply)
            reply_clicked = False

            # icon-reply
            try:
                icon = self._driver.find_element(
                    By.CSS_SELECTOR, ".MenuItem .icon-reply"
                )
                parent = icon.find_element(
                    By.XPATH, "./ancestor::div[contains(@class, 'MenuItem')]"
                )
                safe_click(self._driver, parent)
                reply_clicked = True
            except Exception:
                pass

            if not reply_clicked:
                try:
                    reply_clicked = self._driver.execute_script(
                        """
                        var items = document.querySelectorAll('.MenuItem');
                        for (var i = 0; i < items.length; i++) {
                            var icon = items[i].querySelector('.icon-reply');
                            var text = items[i].textContent;
                            if (icon || text.indexOf('پاسخ') !== -1) {
                                items[i].click(); return true;
                            }
                        }
                        return false;
                        """
                    )
                except Exception:
                    pass

            if not reply_clicked:
                try:
                    item = self._driver.find_element(
                        By.XPATH,
                        "//div[contains(@class,'MenuItem') and contains(text(),'پاسخ')]",
                    )
                    safe_click(self._driver, item)
                    reply_clicked = True
                except Exception:
                    pass

            if not reply_clicked:
                # Close context menu and send as normal message
                try:
                    self._driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                except Exception:
                    pass
                time.sleep(0.5)

            time.sleep(1)
            return self.type_and_send(reply_text)

        except Exception as e:
            logger.error("Reply failed: %s", e)
            return self.type_and_send(reply_text)

    # ════════════════════════════════════════════════════
    #  Batch send personal messages
    # ════════════════════════════════════════════════════

    def send_to_personal_chats(
        self,
        chat_names: List[str],
        message: str,
        delay: float = 3.0,
    ) -> List[SendResult]:
        """Send *message* to each chat in *chat_names*."""
        results: List[SendResult] = []

        self.click_bottom_tab(C.TAB_CHAT)
        time.sleep(1)
        self.click_chat_tab(C.TAB_PERSONAL)
        time.sleep(2)

        for i, name in enumerate(chat_names, 1):
            logger.info("[%d/%d] %s", i, len(chat_names), name)
            try:
                if not self.click_on_chat(name):
                    results.append(SendResult(False, name, message, "Chat not found"))
                    continue
                time.sleep(2)
                if not self.type_and_send(message):
                    results.append(SendResult(False, name, message, "Send failed"))
                    continue
                results.append(SendResult(True, name, message))
                time.sleep(delay)
                self.go_back()
                time.sleep(1)
            except Exception as e:
                results.append(SendResult(False, name, message, str(e)))
                self.go_back()

        return results

    # ════════════════════════════════════════════════════
    #  Account tab helpers
    # ════════════════════════════════════════════════════

    def ensure_account_tab(self) -> bool:
        """Make sure we are on the 'حساب من' tab."""
        try:
            content = self._driver.find_elements(By.CSS_SELECTOR, C.SEL_SETTINGS_CONTENT)
            if content:
                return True
        except Exception:
            pass
        self.click_bottom_tab(C.TAB_ACCOUNT)
        time.sleep(2)
        wait_page_load(self._driver)
        return True

    def click_account_item(self, icon_class: str, item_name: str) -> bool:
        """Click an item in the account/settings sidebar by icon class."""
        self.ensure_account_tab()
        time.sleep(1)

        # icon approach
        try:
            icon = self._driver.find_element(By.CSS_SELECTOR, f"i.icon.{icon_class}")
            parent = icon.find_element(
                By.XPATH, "./ancestor::div[contains(@class, 'ListItem-button')]"
            )
            self._driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", parent
            )
            time.sleep(C.SHORT_WAIT)
            safe_click(self._driver, parent)
            time.sleep(2)
            return True
        except Exception:
            pass

        # JS icon
        try:
            clicked = self._driver.execute_script(
                "var icon = document.querySelector('i.icon."
                + icon_class
                + "');"
                + """
                if (icon) {
                    var btn = icon.closest('.ListItem-button');
                    if (btn) { btn.click(); return true; }
                    var parent = icon.parentElement;
                    if (parent) { parent.click(); return true; }
                }
                return false;
                """
            )
            if clicked:
                time.sleep(2)
                return True
        except Exception:
            pass

        # JS text search
        try:
            clicked = self._driver.execute_script(
                """
                var items = document.querySelectorAll('.ListItem-button');
                for (var i = 0; i < items.length; i++) {
                    if (items[i].textContent.indexOf(arguments[0]) !== -1) {
                        items[i].scrollIntoView({block:'center'});
                        items[i].click();
                        return true;
                    }
                }
                return false;
                """,
                item_name,
            )
            if clicked:
                time.sleep(2)
                return True
        except Exception:
            pass

        logger.warning("Account item '%s' not found", item_name)
        return False

    def go_to_saved_messages(self) -> bool:
        """Navigate to Saved Messages."""
        return self.click_account_item(C.ICON_SAVED_MESSAGES, "پیام‌های ذخیره شده")