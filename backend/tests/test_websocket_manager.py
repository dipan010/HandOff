"""Tests for app.websocket.ConnectionManager — message routing and shape."""

from unittest.mock import AsyncMock

import pytest

from app.websocket import ConnectionManager


@pytest.fixture
def manager():
    return ConnectionManager()


@pytest.fixture
def mock_ws():
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    ws.send_text = AsyncMock()
    return ws


class TestConnectionLifecycle:
    async def test_connect_accepts_and_stores(self, manager, mock_ws):
        await manager.connect("sess1", mock_ws)
        mock_ws.accept.assert_awaited_once()
        assert manager.active_connections["sess1"] is mock_ws

    async def test_disconnect_removes(self, manager, mock_ws):
        await manager.connect("sess1", mock_ws)
        manager.disconnect("sess1")
        assert "sess1" not in manager.active_connections

    def test_disconnect_unknown_is_noop(self, manager):
        manager.disconnect("never-was")  # no exception

    async def test_get_connection(self, manager, mock_ws):
        await manager.connect("sess1", mock_ws)
        assert manager.get_connection("sess1") is mock_ws
        assert manager.get_connection("other") is None


class TestExtensionConnection:
    async def test_connect_extension(self, manager, mock_ws):
        await manager.connect_extension("sess1", mock_ws)
        mock_ws.accept.assert_awaited_once()
        assert manager.extension_connections["sess1"] is mock_ws

    async def test_disconnect_extension(self, manager, mock_ws):
        await manager.connect_extension("sess1", mock_ws)
        manager.disconnect_extension("sess1")
        assert "sess1" not in manager.extension_connections


class TestMessageShapes:
    async def test_send_screenshot_shape(self, manager, mock_ws):
        await manager.connect("s", mock_ws)
        await manager.send_screenshot("s", "BASE64DATA", 3)
        sent = mock_ws.send_json.call_args.args[0]
        assert sent["type"] == "screenshot_update"
        assert sent["data"]["screenshot"] == "BASE64DATA"
        assert sent["data"]["step"] == 3

    async def test_send_action_shape(self, manager, mock_ws):
        await manager.connect("s", mock_ws)
        await manager.send_action("s", {"action": "click_at", "success": True}, 2)
        sent = mock_ws.send_json.call_args.args[0]
        assert sent["type"] == "action_executed"
        assert sent["data"]["action"]["action"] == "click_at"
        assert sent["data"]["step"] == 2

    async def test_send_narration_shape(self, manager, mock_ws):
        await manager.connect("s", mock_ws)
        await manager.send_narration("s", "Hello there.")
        sent = mock_ws.send_json.call_args.args[0]
        assert sent == {"type": "narration", "data": {"text": "Hello there."}}

    async def test_send_audio_narration_shape(self, manager, mock_ws):
        await manager.connect("s", mock_ws)
        await manager.send_audio_narration("s", "AUDIO_B64")
        sent = mock_ws.send_json.call_args.args[0]
        assert sent["type"] == "audio_narration"
        assert sent["data"]["audio"] == "AUDIO_B64"
        assert sent["data"]["sample_rate"] == 24000
        assert sent["data"]["encoding"] == "pcm"

    async def test_send_action_preview_shape(self, manager, mock_ws):
        await manager.connect("s", mock_ws)
        # No extension connected — should not raise
        await manager.send_action_preview("s", "click the search box")
        sent = mock_ws.send_json.call_args.args[0]
        assert sent["type"] == "action_preview"
        assert sent["data"]["text"] == "click the search box"

    async def test_send_action_preview_also_notifies_extension(self, manager, mock_ws):
        ext_ws = AsyncMock()
        ext_ws.send_json = AsyncMock()
        await manager.connect("s", mock_ws)
        await manager.connect_extension("s", ext_ws)
        await manager.send_action_preview("s", "click")
        ext_ws.send_json.assert_awaited()
        sent_to_ext = ext_ws.send_json.call_args.args[0]
        assert sent_to_ext["type"] == "action_preview"
        assert sent_to_ext["text"] == "click"

    async def test_send_status_shape(self, manager, mock_ws):
        await manager.connect("s", mock_ws)
        await manager.send_status("s", "thinking", "Step 1: Analyzing screen", False)
        sent = mock_ws.send_json.call_args.args[0]
        assert sent["type"] == "status_update"
        assert sent["data"]["status"] == "thinking"
        assert sent["data"]["detail"] == "Step 1: Analyzing screen"

    async def test_send_safety_confirm_includes_request_id(self, manager, mock_ws):
        await manager.connect("s", mock_ws)
        await manager.send_safety_confirm("s", {"action": "pay"}, "req-123")
        sent = mock_ws.send_json.call_args.args[0]
        assert sent["type"] == "safety_confirm"
        assert sent["data"]["request_id"] == "req-123"

    async def test_send_task_complete_shape(self, manager, mock_ws):
        await manager.connect("s", mock_ws)
        await manager.send_task_complete("s", "All done summary")
        sent = mock_ws.send_json.call_args.args[0]
        assert sent["type"] == "task_complete"
        assert sent["data"]["summary"] == "All done summary"

    async def test_send_error_shape(self, manager, mock_ws):
        await manager.connect("s", mock_ws)
        await manager.send_error("s", "Something broke")
        sent = mock_ws.send_json.call_args.args[0]
        assert sent["type"] == "error"
        assert sent["data"]["message"] == "Something broke"

    async def test_send_pause_prompt_shape(self, manager, mock_ws):
        await manager.connect("s", mock_ws)
        data = {"reason": "login", "prompt": "Sign in please", "needs_input": False}
        await manager.send_pause_prompt("s", data)
        sent = mock_ws.send_json.call_args.args[0]
        assert sent["type"] == "pause_prompt"
        assert sent["data"] == data


class TestSendFailureHandling:
    async def test_send_to_unknown_session_is_noop(self, manager):
        # No connection registered — calling send should silently no-op
        await manager.send_narration("ghost", "hi")  # no exception

    async def test_send_failure_disconnects(self, manager):
        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock(side_effect=Exception("connection reset"))
        await manager.connect("s", ws)
        await manager.send_narration("s", "test")
        # Failure should evict the connection
        assert "s" not in manager.active_connections


class TestExtensionSendFailure:
    async def test_extension_send_failure_disconnects(self, manager):
        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock(side_effect=Exception("dead"))
        await manager.connect_extension("s", ws)
        await manager.send_to_extension("s", {"type": "ping"})
        assert "s" not in manager.extension_connections

    async def test_broadcast_to_unknown_extension_is_noop(self, manager):
        await manager.broadcast_to_extension("ghost", {"type": "x"})  # no exception
