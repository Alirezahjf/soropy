import asyncio
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from soropy.auto_reply import AutoReplyEngine
from soropy.backends.base import BackendEvent
from soropy.backends.websocket.backend import WebSocketBackend
from soropy.backends.websocket.events import EventBus
from soropy.backends.websocket.loop_runner import LoopRunner
from soropy.backends.websocket.mtproto_engine import (
    MtprotoEngine,
    _ascii_upload_name,
    _entity_kind,
    _is_auth_key_error,
)
from soropy.client import SoroushClient
from soropy.message_tracker import MessageTracker
from soropy.types import ChatCollection, SendResult
from soropy.utils import is_valid_iranian_mobile, validate_phone


class InlineRunner:
    """Run short test coroutines without creating a background loop."""

    is_running = True

    def run(self, coroutine, timeout=None):
        return asyncio.run(coroutine)


class FakeClient:
    def __init__(self):
        self.code_requested = False
        self.signed_code = None
        self.upload = None
        self.sent_file = None
        self.permission_kwargs = None
        self.admin_kwargs = None
        # Allow _sender swap for upload connection tests
        self._sender = SimpleNamespace(is_connected=lambda: True)

    def is_connected(self):
        return True

    async def send_code_request(self, phone):
        self.code_requested = True

    async def sign_in(self, **kwargs):
        self.signed_code = kwargs

    async def is_user_authorized(self):
        return True

    async def upload_file(self, stream, **kwargs):
        self.upload = (stream.read(), stream.name, kwargs)
        return "uploaded"

    async def send_file(self, target, uploaded, **kwargs):
        self.sent_file = (target, uploaded, kwargs)
        return SimpleNamespace(id=12, chat_id=34)

    async def edit_permissions(self, chat, user=None, **kwargs):
        self.permission_kwargs = kwargs

    async def edit_admin(self, chat, user, **kwargs):
        self.admin_kwargs = kwargs


def make_engine(tmp_path: Path, client=None) -> MtprotoEngine:
    engine = MtprotoEngine("09121111111", session_dir=str(tmp_path))
    engine._client = client or FakeClient()
    engine._runner = InlineRunner()
    engine._connected = True
    engine._authorized = True
    engine._entity_cache.update({"chat": "chat-peer", "user": "user-peer"})
    return engine


def test_chat_collection_total_does_not_double_count_categories():
    chats = ChatCollection(
        all=["a", "b", "c"], personal=["a"], groups=["b"], channels=["c"]
    )
    assert chats.total_count == 3
    assert ChatCollection(personal=["a"], groups=["b"]).total_count == 2


@pytest.mark.parametrize(
    "raw",
    [
        "09123456789",
        "9123456789",
        "+989123456789",
        "00989123456789",
        "989123456789",
        "۰۹۱۲۳۴۵۶۷۸۹",
    ],
)
def test_phone_formats(raw):
    assert is_valid_iranian_mobile(raw)
    assert validate_phone(raw) == "+989123456789"


@pytest.mark.parametrize("raw", ["0912xxxxxxx", "091038502235", "123", "", None])
def test_invalid_phone_rejected(raw):
    assert not is_valid_iranian_mobile(raw)
    with pytest.raises(ValueError):
        validate_phone(raw)


def test_entity_classification_never_treats_broadcast_as_personal():
    User = type("User", (), {})
    Channel = type("Channel", (), {})
    Chat = type("Chat", (), {})
    broadcast = Channel()
    broadcast.broadcast = True
    megagroup = Channel()
    megagroup.megagroup = True
    assert _entity_kind(User()) == "personal"
    assert _entity_kind(Channel()) == "group"
    assert _entity_kind(broadcast) == "channel"
    assert _entity_kind(megagroup) == "group"
    assert _entity_kind(Chat()) == "group"


def test_auth_key_error_detection_matches_real_windows_message():
    assert _is_auth_key_error(
        RuntimeError("The key is not registered in the system (GetStateRequest)")
    )
    assert not _is_auth_key_error(RuntimeError("temporary network timeout"))


def test_entity_cache_handles_marked_ids_and_rejects_duplicate_names(tmp_path):
    engine = make_engine(tmp_path)
    engine._entity_cache.clear()
    first = SimpleNamespace(id=100, username=None)
    second = SimpleNamespace(id=200, username=None)
    engine._remember_entity("علی", first, kind="personal", entity_id="-100100")
    # The marked dialog ID and intrinsic entity ID refer to the same peer.
    engine._remember_entity("علی", first, kind="personal", entity_id="100")
    assert "علی" in engine._entity_cache
    engine._remember_entity("علی", second, kind="personal", entity_id="200")
    assert "علی" in engine._ambiguous_names
    assert "علی" not in engine._entity_cache


def test_login_callbacks_run_outside_an_event_loop(tmp_path):
    fake = FakeClient()
    engine = make_engine(tmp_path, fake)
    engine._authorized = False
    callback_thread = threading.get_ident()

    def code_callback():
        assert threading.get_ident() == callback_thread
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        return "12345"

    assert engine.login(code_callback=code_callback) == "success"
    assert fake.code_requested
    assert fake.signed_code == {"phone": "+989121111111", "code": "12345"}


def test_disconnect_closes_nested_http_and_sqlite_sessions(tmp_path):
    class HttpSession:
        def __init__(self):
            self.closed = False

        async def ws_connect(self):
            return None

        async def close(self):
            self.closed = True

    class SqliteSession:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    http = HttpSession()
    sqlite = SqliteSession()

    class Client:
        session = sqlite
        _sender = SimpleNamespace(
            _connection=SimpleNamespace(_cached_session=http)
        )

        async def disconnect(self):
            return None

    engine = make_engine(tmp_path)
    asyncio.run(engine._safe_disconnect(Client()))
    assert http.closed
    assert sqlite.closed


def test_unicode_document_upload_uses_ascii_bytesio_and_512kb_parts(tmp_path):
    fake = FakeClient()
    engine = make_engine(tmp_path, fake)
    path = tmp_path / "نحو مقدماتی- حمید محمدی.docx"
    path.write_bytes(b"document-data")

    result = engine.send_file("chat", str(path))

    assert result["id"] == 12
    data, safe_name, upload_kwargs = fake.upload
    assert data == b"document-data"
    safe_name.encode("ascii")
    assert safe_name.endswith(".docx")
    assert upload_kwargs["part_size_kb"] == 512
    assert fake.sent_file[2]["force_document"] is True


def test_upload_422_reconnects_and_retries_once(tmp_path):
    class RetryClient(FakeClient):
        def __init__(self):
            super().__init__()
            self.attempts = 0

        async def upload_file(self, stream, **kwargs):
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("RPCError 422: FILE_REQUEST_RECEIVED_ON_CONNECTION_SERVER")
            self.upload = (stream.read(), stream.name, kwargs)
            return "uploaded"

        async def send_file(self, target, uploaded, **kwargs):
            self.sent_file = (target, uploaded, kwargs)
            return SimpleNamespace(id=13, chat_id=35)

    fake = RetryClient()
    engine = make_engine(tmp_path, fake)
    path = tmp_path / "report.pdf"
    path.write_bytes(b"pdf")

    result = engine.send_file("chat", str(path))
    assert result["id"] == 13
    # First upload_file call raises 422, second succeeds via retry
    assert fake.attempts == 2


def test_ban_uses_false_and_promote_only_passes_supported_kwargs(tmp_path):
    fake = FakeClient()
    engine = make_engine(tmp_path, fake)

    assert engine.ban("chat", "user") is True
    assert fake.permission_kwargs["view_messages"] is False

    assert engine.promote("chat", "user", rank="مدیر", delete_messages=True) is True
    assert fake.admin_kwargs["title"] == "مدیر"
    assert "rank" not in fake.admin_kwargs
    assert "other" not in fake.admin_kwargs


def test_server_refresh_discards_stale_unread_counter():
    backend = WebSocketBackend("+989121111111")
    backend._logged_in = True
    backend._unread = {"old": 1}
    backend._engine = SimpleNamespace(
        get_dialogs=lambda limit: [
            {"name": "old", "type": "personal", "unread": 0}
        ]
    )
    assert backend.get_unread_personal_chats() == []
    assert backend._unread == {}
    backend.close()


def test_realtime_reply_is_reserved_before_worker_send(tmp_path):
    tracker = AutoReplyEngine(
        tracker=MessageTracker(str(tmp_path / "tracker.json"))
    )
    tracker.add_rule("سلام", "علیک")
    delivered = threading.Event()

    class Backend:
        name = "websocket"

        def reply_to_message(self, chat_name, message_id, reply):
            assert tracker.tracker.is_replied(
                chat_name, "سلام", message_id=message_id
            )
            delivered.set()
            return SendResult(True, chat_name, reply)

        def chat_kind(self, name):
            return "personal"

    client = SoroushClient.__new__(SoroushClient)
    client.auto_reply_enabled = True
    client.auto_reply_private_only = True
    client._auto_reply = tracker
    client._backend = Backend()
    client._on_backend_new_message(
        BackendEvent(
            "new_message",
            {
                "message_id": "1",
                "chat_name": "علی",
                "text": "سلام",
                "is_private": True,
                "is_group": False,
                "is_channel": False,
                "is_outgoing": False,
            },
        )
    )
    assert delivered.wait(2)


def test_duplicate_tracking_uses_message_id_when_available(tmp_path):
    engine = AutoReplyEngine(
        tracker=MessageTracker(str(tmp_path / "ids.json"))
    )
    engine.add_rule("سلام", "علیک")
    assert engine.get_reply("سلام", "علی", message_id="101") == "علیک"
    engine.mark_replied("علی", "سلام", message_id="101")
    assert engine.get_reply("سلام", "علی", message_id="101") is None
    # The same text in a genuinely new message must still receive a reply.
    assert engine.get_reply("سلام", "علی", message_id="102") == "علیک"


def test_event_bus_async_does_not_block_emitter():
    bus = EventBus()
    completed = threading.Event()

    def slow(_event):
        time.sleep(0.1)
        completed.set()

    bus.on("x", slow)
    started = time.monotonic()
    bus.emit_async("x")
    assert time.monotonic() - started < 0.05
    assert completed.wait(1)
    bus.close()


def test_loop_runner_deadlock_guard():
    runner = LoopRunner("test-loop")
    runner.start()
    assert runner.run(asyncio.sleep(0, result=42), timeout=2) == 42

    async def nested():
        return runner.run(asyncio.sleep(0), timeout=1)

    with pytest.raises(RuntimeError, match="deadlock"):
        runner.run(nested(), timeout=2)
    runner.stop()


def test_ascii_upload_name_preserves_extension():
    name = _ascii_upload_name(r"C:\\Users\\me\\Downloads\\فایل فارسی.PDF")
    name.encode("ascii")
    assert name.endswith(".pdf")
