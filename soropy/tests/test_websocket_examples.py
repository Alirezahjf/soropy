import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples" / "websocket"
MODULE_FILES = {
    "group_moderator": EXAMPLES_DIR / "group_moderator.py",
    "ai_assistant": EXAMPLES_DIR / "ai_assistant.py",
    "capability_cookbook": EXAMPLES_DIR / "capability_cookbook.py",
    "support_desk_bot": EXAMPLES_DIR / "support_desk_bot.py",
    "campaign_broadcaster": EXAMPLES_DIR / "campaign_broadcaster.py",
    "event_audit_logger": EXAMPLES_DIR / "event_audit_logger.py",
}
_CACHE = {}


def load_example(name):
    if name in _CACHE:
        return _CACHE[name]
    spec = importlib.util.spec_from_file_location(f"test_{name}", MODULE_FILES[name])
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _CACHE[name] = module
    return module


@pytest.mark.parametrize("module_name", sorted(MODULE_FILES))
def test_import_websocket_example_modules(module_name):
    assert load_example(module_name)


def test_warning_store_increment_persistence_summary_clear(tmp_path):
    gm = load_example("group_moderator")
    path = tmp_path / "warnings.json"
    store = gm.WarningStore(path)
    assert store.increment("chat", "user", "bad") == 1
    assert store.increment("chat", "user", "link") == 2
    assert "user: 2 اخطار" in store.summary("chat")

    reloaded = gm.WarningStore(path)
    assert reloaded.get("chat", "user") == 2
    assert reloaded.clear("chat", "user") is True
    assert reloaded.get("chat", "user") == 0
    assert "هیچ" in reloaded.summary("chat")


def test_bad_word_detection():
    gm = load_example("group_moderator")
    assert gm.contains_bad_word("این متن کلمه_ممنوع_۱ دارد", {"کلمه_ممنوع_۱"})
    assert not gm.contains_bad_word("متن سالم", {"کلمه_ممنوع_۱"})


def test_disallowed_link_detection():
    gm = load_example("group_moderator")
    assert gm.contains_disallowed_link("لینک https://bad.example/path", [])


def test_allowed_example_domain():
    gm = load_example("group_moderator")
    assert not gm.contains_disallowed_link("see https://example.com/page", ["example.com"])


def test_subdomain_allowed_by_allowlist():
    gm = load_example("group_moderator")
    assert not gm.contains_disallowed_link("https://docs.example.com", ["example.com"])


def test_flood_after_limit():
    gm = load_example("group_moderator")
    detector = gm.SlidingWindowCounter(max_count=2, window_seconds=8)
    assert detector.hit("u", now=1) is False
    assert detector.hit("u", now=2) is False
    assert detector.hit("u", now=3) is True


def test_flood_window_expires():
    gm = load_example("group_moderator")
    detector = gm.SlidingWindowCounter(max_count=1, window_seconds=2)
    assert detector.hit("u", now=1) is False
    assert detector.hit("u", now=4) is False


def test_repeat_after_limit():
    gm = load_example("group_moderator")
    detector = gm.RepeatDetector(max_count=3, window_seconds=30)
    assert detector.hit("u", "سلام", now=1) is False
    assert detector.hit("u", "سلام", now=2) is False
    assert detector.hit("u", "سلام", now=3) is True


def test_repeat_ignores_empty_text():
    gm = load_example("group_moderator")
    detector = gm.RepeatDetector(max_count=1, window_seconds=30)
    assert detector.hit("u", "   ", now=1) is False


def test_ai_provider_prompt():
    ai = load_example("ai_assistant")
    provider = ai.AIProvider(provider="ollama", model="x")
    prompt = provider._prompt([{"role": "user", "content": "قبلی"}], "جدید")
    assert prompt[0]["role"] == "system"
    assert prompt[-1] == {"role": "user", "content": "جدید"}


def test_ai_group_slash_trigger(monkeypatch):
    ai = load_example("ai_assistant")
    monkeypatch.setattr(ai, "AI_PRIVATE_ONLY", False)
    monkeypatch.setattr(ai, "SOROPY_AI_GROUP", "گروه")
    item = ai.IncomingAIMessage("1", "c", "گروه", "u", "/ai سلام", False, True, False)
    assert ai.should_answer(item) == (True, "سلام")


def test_ai_group_persian_trigger(monkeypatch):
    ai = load_example("ai_assistant")
    monkeypatch.setattr(ai, "AI_PRIVATE_ONLY", False)
    monkeypatch.setattr(ai, "SOROPY_AI_GROUP", "گروه")
    item = ai.IncomingAIMessage("1", "c", "گروه", "u", "هوش: سلام", False, True, False)
    assert ai.should_answer(item) == (True, "سلام")


def test_ai_rejects_regular_group_message(monkeypatch):
    ai = load_example("ai_assistant")
    monkeypatch.setattr(ai, "AI_PRIVATE_ONLY", False)
    monkeypatch.setattr(ai, "SOROPY_AI_GROUP", "گروه")
    item = ai.IncomingAIMessage("1", "c", "گروه", "u", "سلام", False, True, False)
    assert ai.should_answer(item) == (False, "")


def test_ai_accepts_private_question():
    ai = load_example("ai_assistant")
    item = ai.IncomingAIMessage("1", "c", "", "u", "سؤال من", True, False, False)
    assert ai.should_answer(item) == (True, "سؤال من")


def test_ai_rejects_outgoing_private_question():
    ai = load_example("ai_assistant")
    item = ai.IncomingAIMessage("1", "c", "", "u", "سؤال", True, False, True)
    assert ai.should_answer(item) == (False, "")


def test_group_trigger_text_empty_slash_ai():
    ai = load_example("ai_assistant")
    assert ai.group_trigger_text("/ai") == ""


def test_split_text_chunks():
    ai = load_example("ai_assistant")
    assert ai.split_text("abcdef", max_chars=2) == ["ab", "cd", "ef"]


def test_rate_limiter():
    ai = load_example("ai_assistant")
    limiter = ai.RateLimiter(limit=1, window_seconds=60)
    assert limiter.allow("u") is True
    assert limiter.allow("u") is False


def test_capability_cookbook_import_has_no_network_side_effects():
    cookbook = load_example("capability_cookbook")
    assert callable(cookbook.make_client)
    assert callable(cookbook.main)


def test_moderation_event_from_payload():
    gm = load_example("group_moderator")
    item = gm.ModerationEvent.from_payload(
        {"message_id": 1, "chat_id": 2, "chat_name": "g", "sender_id": 3, "text": "x"}
    )
    assert item.message_id == "1"
    assert item.chat_id == "2"
    assert item.sender_id == "3"


class FakeClient:
    def __init__(self):
        self.sent = []

    def get_permissions(self, group, user):
        return {"is_admin": False, "is_creator": False}

    def reply(self, target, message_id, text):
        self.sent.append(("reply", target, message_id, text))

    def send_message(self, target, text):
        self.sent.append(("send", target, text))

    def delete_messages(self, target, ids, revoke=True):
        self.sent.append(("delete", target, tuple(ids), revoke))

    def kick(self, target, user):
        self.sent.append(("kick", target, user))
        return True

    def ban(self, target, user):
        self.sent.append(("ban", target, user))
        return True

    def send_file(self, target, path, caption=""):
        self.sent.append(("file", target, path, caption))


def test_group_moderator_rules_command_from_admin(monkeypatch, tmp_path):
    gm = load_example("group_moderator")
    monkeypatch.setattr(gm, "SESSION_DIR", str(tmp_path))
    moderator = gm.GroupModerator(FakeClient())
    monkeypatch.setattr(moderator, "_is_admin_or_creator", lambda _sender: True)
    item = gm.ModerationEvent("1", "chat", gm.GROUP_NAME, "admin", "admin", "/rules", False, True, False, False)
    assert moderator._handle_command(item) is True
    assert moderator.client.sent[0][0] == "reply"


def test_group_moderator_forwards_matching_group(monkeypatch, tmp_path):
    gm = load_example("group_moderator")
    monkeypatch.setattr(gm, "SESSION_DIR", str(tmp_path))
    moderator = gm.GroupModerator(FakeClient())
    event = SimpleNamespace(data={"chat_name": gm.GROUP_NAME, "is_group": True, "text": "x"})
    moderator.on_event(event)
    assert moderator.queue.qsize() == 1


# ---------------------------------------------------------------------------
# support_desk_bot
# ---------------------------------------------------------------------------


def test_ticket_store_lifecycle(tmp_path):
    support = load_example("support_desk_bot")
    store = support.TicketStore(tmp_path / "support_tickets.json")
    t1 = store.upsert_message("u1", "علی", "سلام، مشکل دارم")
    assert t1["status"] == "open"
    assert t1["message_count"] == 1
    t2 = store.upsert_message("u1", "علی", "هنوز جواب ندادید")
    assert t2["message_count"] == 2
    assigned = store.assign("u1", "اپراتور-۱")
    assert assigned["assignee"] == "اپراتور-۱"
    closed = store.close("u1")
    assert closed["status"] == "closed"
    stats = store.stats()
    assert stats["total"] == 1
    assert stats["closed"] == 1
    assert stats["open"] == 0
    assert stats["assigned"] == 1
    assert stats["messages"] == 2

    reloaded = support.TicketStore(tmp_path / "support_tickets.json")
    assert reloaded.get("u1")["status"] == "closed"
    assert reloaded.get("u1")["assignee"] == "اپراتور-۱"


def test_ticket_summary_contains_core_fields():
    support = load_example("support_desk_bot")
    text = support.ticket_summary(
        {
            "user_id": "42",
            "user_name": "رضا",
            "status": "open",
            "assignee": "سارا",
            "message_count": 3,
            "last_message": "کمک",
            "created_at": 1,
            "updated_at": 2,
        }
    )
    assert "42" in text
    assert "رضا" in text
    assert "open" in text
    assert "سارا" in text
    assert "3" in text
    assert "کمک" in text


def test_support_desk_operator_stats_command(monkeypatch, tmp_path):
    support = load_example("support_desk_bot")
    monkeypatch.setattr(support, "SESSION_DIR", str(tmp_path))
    bot = support.SupportDeskBot(FakeClient())
    bot.store.upsert_message("10", "کاربر", "سلام")
    item = support.SupportEvent(
        "1",
        "g",
        support.SUPPORT_GROUP,
        "op",
        "op",
        "/stats",
        False,
        False,
        True,
    )
    assert bot._handle_operator_command(item) is True
    assert bot.client.sent
    assert "آمار" in bot.client.sent[0][-1]


# ---------------------------------------------------------------------------
# campaign_broadcaster
# ---------------------------------------------------------------------------


def test_campaign_load_targets(tmp_path):
    campaign = load_example("campaign_broadcaster")
    csv_path = tmp_path / "targets.csv"
    csv_path.write_text(
        "name,kind,note\nعلی,personal,VIP\n@group,group,تست\n",
        encoding="utf-8",
    )
    targets = campaign.load_targets(csv_path)
    assert len(targets) == 2
    assert targets[0].name == "علی"
    assert targets[0].kind == "personal"
    assert targets[0].note == "VIP"
    assert targets[1].name == "@group"


def test_campaign_render_message():
    campaign = load_example("campaign_broadcaster")
    target = campaign.CampaignTarget(name="علی", kind="personal", note="ویژه")
    text = campaign.render_message("سلام {name} ({kind}) {note}", target)
    assert text == "سلام علی (personal) ویژه"


def test_campaign_chunked():
    campaign = load_example("campaign_broadcaster")
    assert campaign.chunked([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
    assert campaign.chunked([1, 2, 3], 0) == [[1, 2, 3]]
    assert campaign.chunked([], 3) == []


def test_campaign_dry_run_does_not_send():
    campaign = load_example("campaign_broadcaster")
    client = FakeClient()
    targets = [
        campaign.CampaignTarget("علی", "personal", "a"),
        campaign.CampaignTarget("رضا", "personal", "b"),
    ]
    summary = campaign.run_campaign(
        client,
        targets,
        text_template="hi {name}",
        delay=0,
        confirm="NO",
    )
    assert summary["confirmed"] is False
    assert summary["sent"] == 0
    assert summary["skipped"] == 2
    assert client.sent == []


def test_campaign_confirm_sends_message():
    campaign = load_example("campaign_broadcaster")
    client = FakeClient()
    targets = [campaign.CampaignTarget("علی", "personal", "x")]
    summary = campaign.run_campaign(
        client,
        targets,
        text_template="سلام {name}",
        delay=0,
        confirm="YES",
    )
    assert summary["sent"] == 1
    assert client.sent[0][0] == "send"
    assert client.sent[0][1] == "علی"
    assert client.sent[0][2] == "سلام علی"


# ---------------------------------------------------------------------------
# event_audit_logger
# ---------------------------------------------------------------------------


def test_sanitize_payload_masks_sensitive_keys():
    audit = load_example("event_audit_logger")
    cleaned = audit.sanitize_payload(
        {
            "phone": "09123456789",
            "token": "abc",
            "access_token": "a",
            "refresh_token": "b",
            "auth_key": "c",
            "code": "12345",
            "text": "سلام",
            "nested": {"phone": "x", "ok": 1},
        }
    )
    assert cleaned["phone"] == "***"
    assert cleaned["token"] == "***"
    assert cleaned["access_token"] == "***"
    assert cleaned["refresh_token"] == "***"
    assert cleaned["auth_key"] == "***"
    assert cleaned["code"] == "***"
    assert cleaned["text"] == "سلام"
    assert cleaned["nested"]["phone"] == "***"
    assert cleaned["nested"]["ok"] == 1


def test_jsonl_audit_logger_write_and_summary(tmp_path):
    audit = load_example("event_audit_logger")
    path = tmp_path / "events_audit.jsonl"
    logger = audit.JsonlAuditLogger(path)
    logger.write("connected", {"status": "ok"})
    logger.write("new_message", {"phone": "0912", "text": "hi"})
    logger.write("error", {"code": "secret"})
    assert logger.total == 3
    assert logger.counts["connected"] == 1
    assert logger.counts["new_message"] == 1
    assert logger.counts["error"] == 1
    summary = logger.summary()
    assert "total=3" in summary
    assert "connected=1" in summary
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    import json

    second = json.loads(lines[1])
    assert second["data"]["phone"] == "***"
    assert second["data"]["text"] == "hi"
    third = json.loads(lines[2])
    assert third["data"]["code"] == "***"
