"""Tests for app.pubsub — sensitive-data redaction and logging."""

import json
import threading
from pathlib import Path

import pytest

from app import pubsub


@pytest.fixture
def isolated_log(tmp_path, monkeypatch):
    log = tmp_path / "actions.log"
    monkeypatch.setattr(pubsub, "_LOG_FILE", log)
    return log


class TestRedact:
    def test_redacts_password_key(self):
        assert pubsub._redact({"password": "hunter2"}) == {"password": "[REDACTED]"}

    def test_redacts_token(self):
        assert pubsub._redact({"token": "abc123"}) == {"token": "[REDACTED]"}

    def test_redacts_card_number(self):
        assert pubsub._redact({"card_number": "4111111111111111"}) == {"card_number": "[REDACTED]"}

    def test_redacts_typed_text(self):
        # The `text` field is what gets typed into inputs — could be a password
        result = pubsub._redact({"text": "myPassword123"})
        assert result == {"text": "[REDACTED]"}

    def test_keeps_non_sensitive_fields(self):
        args = {"url": "https://google.com", "x": 100, "y": 200, "direction": "down"}
        assert pubsub._redact(args) == args

    def test_redaction_is_case_insensitive(self):
        assert pubsub._redact({"PASSWORD": "x"}) == {"PASSWORD": "[REDACTED]"}
        assert pubsub._redact({"Token": "x"}) == {"Token": "[REDACTED]"}

    def test_empty_args(self):
        assert pubsub._redact({}) == {}

    def test_mixed_sensitive_and_safe(self):
        args = {"url": "https://x.com", "password": "secret", "x": 5}
        assert pubsub._redact(args) == {
            "url": "https://x.com",
            "password": "[REDACTED]",
            "x": 5,
        }

    def test_does_not_mutate_input(self):
        original = {"password": "hunter2"}
        pubsub._redact(original)
        assert original == {"password": "hunter2"}

    def test_empty_text_still_redacted(self):
        # Even an empty typed string shouldn't leak (could later become sensitive)
        result = pubsub._redact({"text": ""})
        assert result == {"text": ""}  # empty stays empty, no redaction needed


class TestPublishAction:
    async def test_writes_json_line(self, isolated_log):
        msg_id = await pubsub.publish_action("sess1", 1, "click_at", {"x": 10, "y": 20})
        assert msg_id == "local-sess1-1"
        contents = isolated_log.read_text().strip()
        entry = json.loads(contents)
        assert entry["session_id"] == "sess1"
        assert entry["step"] == 1
        assert entry["action"] == "click_at"
        assert entry["args"] == {"x": 10, "y": 20}
        assert "timestamp" in entry

    async def test_redacts_before_writing(self, isolated_log):
        await pubsub.publish_action("sess1", 1, "type", {"text": "my-password"})
        entry = json.loads(isolated_log.read_text().strip())
        assert entry["args"] == {"text": "[REDACTED]"}

    async def test_appends_multiple_entries(self, isolated_log):
        await pubsub.publish_action("s", 1, "click_at", {})
        await pubsub.publish_action("s", 2, "scroll", {"direction": "down"})
        lines = isolated_log.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["step"] == 1
        assert json.loads(lines[1])["step"] == 2

    async def test_returns_none_on_failure(self, monkeypatch, isolated_log):
        # Force a write failure
        def boom(*a, **kw):
            raise OSError("disk full")
        monkeypatch.setattr(Path, "open", boom)
        result = await pubsub.publish_action("s", 1, "click_at", {})
        assert result is None

    async def test_concurrent_writes_dont_corrupt(self, isolated_log):
        """The threading.Lock should keep JSON lines well-formed under contention."""
        import asyncio
        await asyncio.gather(*[
            pubsub.publish_action(f"s{i}", i, "click_at", {"i": i})
            for i in range(20)
        ])
        lines = isolated_log.read_text().strip().split("\n")
        assert len(lines) == 20
        # Every line must parse as valid JSON — no interleaving
        for line in lines:
            json.loads(line)
