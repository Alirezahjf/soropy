"""
All CSS selectors, XPaths, and configuration constants.

Centralising selectors makes maintenance trivial when the
Soroush Plus web app changes its markup.
"""

# ─── URLs ───────────────────────────────────────────────
SPLUS_WEB_URL = "https://web.splus.ir/"

# ─── Timeouts (seconds) ────────────────────────────────
DEFAULT_TIMEOUT = 15
PAGE_LOAD_TIMEOUT = 10
SHORT_WAIT = 0.3
MEDIUM_WAIT = 1
LONG_WAIT = 3
LOGIN_WAIT = 30
ELEMENT_RETRY_COUNT = 3

# ─── Sessions ──────────────────────────────────────────
DEFAULT_SESSIONS_DIR = "soropy_sessions"
TRACKER_DB_NAME = "message_tracker.json"

# ─── CSS Selectors ─────────────────────────────────────

# Login page
SEL_PHONE_INPUT = "input[type='tel']"
SEL_CODE_INPUT_ID = "sign-in-code"
SEL_CODE_INPUT_ARIA = "input[aria-label='کد را وارد کنید']"
SEL_CODE_INPUT_NUMERIC = "input[inputmode='numeric']"

# Chat list indicators (proves user is logged in)
SEL_LOGGED_IN_INDICATORS = [
    "[class*='chatlist']",
    "[class*='chat-list']",
    "[class*='sidebar-header']",
    "[class*='folders-tabs']",
    ".os-viewport",
]

# Chat list items
SEL_CHAT_CONTAINERS = [
    "[class*='chatlist'] li, [class*='chat-list'] li",
    "[class*='dialog'], [class*='Dialog']",
    "[class*='row'], [class*='Row']",
    "a[class*='chat'], a[class*='dialog']",
]

SEL_CHAT_NAME_SELECTORS = [
    "[class*='name'], [class*='title'], .peer-title",
    "[class*='name'], [class*='title'], span",
]

SEL_CHAT_LINK = "a.ListItem-button"
SEL_CHAT_FULLNAME = "h3.fullName"

# Scroll containers
SEL_SCROLL_CONTAINERS = [
    ".os-viewport",
    "[class*='chatlist']",
    "[class*='scroll']",
    "[class*='sidebar']",
]

# Message input
SEL_MSG_INPUT_ID = "editable-message-text"
SEL_MSG_INPUT_ARIA = "div[contenteditable='true'][aria-label='پیام']"
SEL_MSG_INPUT_WRAPPER = ".message-input-wrapper"
SEL_MSG_INPUT_TEXT_ID = "message-input-text"
SEL_CONTENTEDITABLE = "div[contenteditable='true']"

# Messages in chat
SEL_MESSAGE = ".Message"
SEL_MESSAGE_INCOMING = ".Message.is-in"
SEL_MESSAGE_OUTGOING = ".Message.is-out"
SEL_MESSAGE_TEXT = ".text-content, .message-text, [class*='text']"

# Unread badges
SEL_PRIVATE_CHAT = ".ListItem.Chat.private"
SEL_UNREAD_BADGE = ".ChatBadge.unread"

# Back button
SEL_BACK_BUTTONS = [
    "button.back-button",
    "[class*='back-button']",
    "button[class*='back']",
]

# Context menu
SEL_MENU_ITEM = ".MenuItem"
SEL_MENU_ITEM_DESTRUCTIVE = ".MenuItem.destructive"

# Contact form
SEL_CONTACT_FORM = ".NewContactModal__new-contact"
SEL_CONTACT_FORM_INPUTS = (
    ".NewContactModal__new-contact input.form-control, "
    ".modal-content input.form-control"
)
SEL_NEW_CONTACT_BUTTON = ".NewContactButton button.round"
SEL_DIALOG_BUTTONS = ".dialog-buttons"
SEL_CONFIRM_BUTTON = ".dialog-buttons .Button.confirm-dialog-button"

# Search
SEL_SEARCH_INPUT_ID = "search-input"

# Bottom tabs
SEL_BOTTOM_TABS = ".bottomTabs .tab"

# Account section
SEL_SETTINGS_CONTENT = ".settings-content, .settings-main-menu"
SEL_LISTITEM_BUTTON = ".ListItem-button"

# ─── XPaths ────────────────────────────────────────────
XPATH_DISMISS_POPUP_VARIANTS = [
    "//*[contains(text(), 'متوجه شدم')]",
    "//button[contains(text(), 'متوجه شدم')]",
    "//a[contains(text(), 'متوجه شدم')]",
]

XPATH_NEXT_BUTTON = "//*[contains(text(), 'بعدی')]"
XPATH_DELETE_CONFIRM = "//button[contains(text(), 'حذف')]"

# ─── Tab names ─────────────────────────────────────────
TAB_CHAT = "گفتگو"
TAB_ACCOUNT = "حساب من"
TAB_ALL = "همه"
TAB_PERSONAL = "شخصی"
TAB_GROUPS = "گروه‌ها"
TAB_CHANNELS = "کانال‌ها"

CHAT_TABS = [TAB_ALL, TAB_PERSONAL, TAB_GROUPS, TAB_CHANNELS]

# ─── Account menu icons ───────────────────────────────
ICON_SAVED_MESSAGES = "icon-saved-messages"
ICON_CONTACTS = "icon-user"