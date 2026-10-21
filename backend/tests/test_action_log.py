import json

from app import action_log


async def test_log_action_appends_json_line(tmp_path, monkeypatch):
    log_file = tmp_path / "actions.log"
    monkeypatch.setattr(action_log, "_LOG_FILE", log_file)

    entry_id = await action_log.log_action("abc", 3, "click_at", {"x": 10, "y": 20})

    assert entry_id == "local-abc-3"
    entry = json.loads(log_file.read_text().strip())
    assert entry["session_id"] == "abc"
    assert entry["step"] == 3
    assert entry["action"] == "click_at"
    assert entry["args"] == {"x": 10, "y": 20}
