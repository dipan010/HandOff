"""Tests for app.browser_adapters.live_browser_adapter."""

import asyncio
import base64
from unittest.mock import AsyncMock, patch

import pytest

from app.browser_adapters.live_browser_adapter import LiveBrowserAdapter


@pytest.fixture
def adapter():
    return LiveBrowserAdapter("test-session")


class TestUpdateScreenshot:
    def test_decodes_and_stores_frame(self, adapter):
        raw = b"\x89PNG\r\n\x1a\nFAKE"
        b64 = base64.b64encode(raw).decode()
        adapter.update_screenshot(b64)
        assert adapter._latest_screenshot_bytes == raw
        assert adapter._latest_screenshot_time > 0

    def test_invalid_base64_does_not_crash(self, adapter):
        adapter.update_screenshot("not!valid!base64!!!")
        # Logs an error but doesn't raise — adapter must stay usable
        assert adapter._latest_screenshot_bytes is None


class TestCaptureScreenshot:
    async def test_returns_existing_frame_when_fresh(self, adapter):
        raw = b"fakeimage"
        adapter._latest_screenshot_bytes = raw
        adapter._latest_screenshot_time = 100.0
        result = await adapter.capture_screenshot(min_timestamp=50.0)
        assert result == raw

    async def test_returns_none_when_no_frame_ever(self, adapter):
        # No screenshot has ever arrived, short-circuit the spin loop
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await adapter.capture_screenshot(min_timestamp=0)
        assert result is None

    async def test_returns_latest_on_stale_timeout(self, adapter):
        """When min_timestamp can't be satisfied but we have ANY frame, return it."""
        raw = b"stale-frame"
        adapter._latest_screenshot_bytes = raw
        adapter._latest_screenshot_time = 10.0  # older than min_timestamp
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await adapter.capture_screenshot(min_timestamp=100.0)
        assert result == raw  # falls back to latest, not None


class TestCompleteAction:
    async def test_resolves_pending_future(self, adapter):
        adapter._action_result_future = asyncio.Future()
        adapter.complete_action({"success": True, "action": "click_at"})
        result = await adapter._action_result_future
        assert result == {"success": True, "action": "click_at"}

    def test_no_pending_future_is_noop(self, adapter):
        adapter._action_result_future = None
        adapter.complete_action({"x": 1})  # must not raise

    async def test_already_done_future_is_noop(self, adapter):
        fut = asyncio.Future()
        fut.set_result({"already": "done"})
        adapter._action_result_future = fut
        adapter.complete_action({"new": "result"})
        # Future result is unchanged
        assert await fut == {"already": "done"}


class TestExecuteAction:
    async def test_sends_action_to_extension(self, adapter):
        with patch("app.websocket.manager.send_to_extension", new_callable=AsyncMock) as mock_send:
            # Pre-resolve the future so wait_for returns immediately
            async def resolve():
                await asyncio.sleep(0.01)
                adapter.complete_action({"success": True})

            asyncio.create_task(resolve())
            result = await adapter.execute_action("click_at", {"x": 5, "y": 10})

            assert mock_send.called
            sent_msg = mock_send.call_args.args[1]
            assert sent_msg["type"] == "execute_action"
            assert sent_msg["action"] == "click_at"
            assert sent_msg["x"] == 5
            assert sent_msg["y"] == 10
            assert result == {"success": True}

    async def test_returns_timeout_dict_on_no_response(self, adapter):
        with patch("app.websocket.manager.send_to_extension", new_callable=AsyncMock):
            # Patch the timeout to fire fast
            with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()):
                result = await adapter.execute_action("click_at", {"x": 1, "y": 2})
        assert result["success"] is False
        assert result["action"] == "click_at"
        assert "timeout" in result["detail"].lower()

    async def test_get_current_url_extracts_url_field(self, adapter):
        with patch.object(
            adapter, "execute_action", new=AsyncMock(return_value={"url": "https://x.com"})
        ):
            assert await adapter.get_current_url() == "https://x.com"

    async def test_get_current_url_returns_empty_when_missing(self, adapter):
        with patch.object(
            adapter, "execute_action", new=AsyncMock(return_value={"success": False})
        ):
            assert await adapter.get_current_url() == ""


class TestClose:
    async def test_sends_stop_stream_to_extension(self, adapter):
        with patch("app.websocket.manager.send_to_extension", new_callable=AsyncMock) as mock_send:
            await adapter.close()
            mock_send.assert_called()
            args = mock_send.call_args.args
            assert args[1] == {"type": "stop_stream"}

    async def test_clears_screenshot_state(self, adapter):
        adapter._latest_screenshot_bytes = b"frame"
        with patch("app.websocket.manager.send_to_extension", new_callable=AsyncMock):
            await adapter.close()
        assert adapter._latest_screenshot_bytes is None

    async def test_swallows_send_errors(self, adapter):
        # close() must succeed even if the extension WS is already dead
        with patch(
            "app.websocket.manager.send_to_extension",
            new=AsyncMock(side_effect=Exception("dead socket")),
        ):
            await adapter.close()  # no exception bubbles
