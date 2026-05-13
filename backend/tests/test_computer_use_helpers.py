"""Tests for the pure helpers in app.computer_use."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import computer_use


class TestIsLoginWall:
    def test_detects_google_accounts(self):
        assert computer_use._is_login_wall("https://accounts.google.com/signin")

    def test_detects_paypal(self):
        assert computer_use._is_login_wall("https://www.paypal.com/login")

    def test_detects_login_subdomain(self):
        assert computer_use._is_login_wall("https://login.example.com/")

    def test_detects_payment_subdomain(self):
        assert computer_use._is_login_wall("https://payment.shop.com/checkout")

    def test_does_not_match_random_url(self):
        assert not computer_use._is_login_wall("https://wikipedia.org/wiki/Login")

    def test_does_not_match_search_results(self):
        assert not computer_use._is_login_wall("https://google.com/search?q=cats")

    def test_empty_url_safe(self):
        assert not computer_use._is_login_wall("")

    def test_none_url_safe(self):
        assert not computer_use._is_login_wall(None)


class TestActionToPlainEnglish:
    def test_click_variants(self):
        for name in ["click_at", "click", "left_click"]:
            assert computer_use._action_to_plain_english(name, {}) == "Click a button or link"

    def test_type_short_text(self):
        result = computer_use._action_to_plain_english("type", {"text": "hi"})
        assert result == "Type 'hi'"

    def test_type_long_text_redacts(self):
        # Long text gets a generic phrase — important so passwords aren't read aloud
        result = computer_use._action_to_plain_english("type", {"text": "a" * 20})
        assert result == "Type a message"

    def test_navigate(self):
        result = computer_use._action_to_plain_english("navigate", {"url": "https://x.com"})
        assert "https://x.com" in result

    def test_scroll_with_amount(self):
        result = computer_use._action_to_plain_english("scroll", {"direction": "down", "amount": 3})
        assert "down" in result
        assert "360" in result  # 3 * 120

    def test_scroll_to(self):
        result = computer_use._action_to_plain_english("scroll_to", {"pixel_y": 500})
        assert "500" in result

    def test_key_combination_list(self):
        result = computer_use._action_to_plain_english("key_combination", {"keys": ["ctrl", "a"]})
        assert "ctrl+a" in result.lower() or "ctrl+a" in result

    def test_key_combination_string(self):
        result = computer_use._action_to_plain_english("key_combination", {"keys": "enter"})
        assert "enter" in result

    def test_hover(self):
        assert computer_use._action_to_plain_english("hover_at", {}) == "Point at an element"

    def test_unknown_action_fallback(self):
        result = computer_use._action_to_plain_english("totally_made_up", {})
        assert result == "Prepare to take action"


class TestNarrateAction:
    async def test_no_live_session_is_noop(self, clean_narration_times):
        """If live_session_ref is None or [None], _narrate_action should silently return."""
        last_action = [0.0]
        await computer_use._narrate_action(
            "s1", "click_at", {}, last_action, None, grandparents_mode=False
        )
        await computer_use._narrate_action(
            "s1", "click_at", {}, last_action, [None], grandparents_mode=False
        )
        # last_action_time still gets updated regardless
        assert last_action[0] > 0

    async def test_updates_last_action_time(self, clean_narration_times):
        last_action = [0.0]
        before = time.time()
        await computer_use._narrate_action("s1", "click_at", {}, last_action, None)
        assert last_action[0] >= before

    async def test_rate_limited_per_session(self, clean_narration_times):
        """Two calls within 3s for the same session — second is suppressed."""
        live_session = AsyncMock()
        live_ref = [live_session]
        last_action = [0.0]

        await computer_use._narrate_action("s1", "click_at", {}, last_action, live_ref)
        await computer_use._narrate_action("s1", "click_at", {}, last_action, live_ref)
        # Only first call should have invoked send_client_content
        assert live_session.send_client_content.call_count == 1

    async def test_different_sessions_independent(self, clean_narration_times):
        """The 3-second cooldown is per-session, not global."""
        live_session = AsyncMock()
        live_ref = [live_session]
        last_action = [0.0]

        await computer_use._narrate_action("s1", "click_at", {}, last_action, live_ref)
        await computer_use._narrate_action("s2", "click_at", {}, last_action, live_ref)
        # Both sessions should narrate — no cross-session interference
        assert live_session.send_client_content.call_count == 2

    async def test_grandparents_mode_phrasing(self, clean_narration_times):
        live_session = AsyncMock()
        await computer_use._narrate_action(
            "s1", "navigate", {"url": "google.com"}, [0.0], [live_session],
            grandparents_mode=True,
        )
        call = live_session.send_client_content.call_args
        text = call.kwargs["turns"].parts[0].text
        assert text.startswith("I'm now")  # warm first-person phrasing

    async def test_normal_mode_phrasing(self, clean_narration_times):
        live_session = AsyncMock()
        await computer_use._narrate_action(
            "s1", "navigate", {"url": "google.com"}, [0.0], [live_session],
            grandparents_mode=False,
        )
        text = live_session.send_client_content.call_args.kwargs["turns"].parts[0].text
        assert text.startswith("Action:")  # factual log-style


class TestHeartbeat:
    async def test_first_message_after_interval(self):
        """Heartbeat shouldn't fire immediately — only after the interval."""
        with patch.object(computer_use.ws_manager, "send_narration", new_callable=AsyncMock) as mock_send:
            task = asyncio.create_task(
                computer_use._heartbeat("s1", grandparents_mode=False, interval=0.05)
            )
            await asyncio.sleep(0.02)  # less than interval
            # No call yet
            assert mock_send.call_count == 0
            await asyncio.sleep(0.08)  # cross the interval
            assert mock_send.call_count >= 1
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def test_uses_grandparents_messages(self):
        with patch.object(computer_use.ws_manager, "send_narration", new_callable=AsyncMock) as mock_send:
            task = asyncio.create_task(
                computer_use._heartbeat("s1", grandparents_mode=True, interval=0.01)
            )
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            # At least one call made, and the message must be from the GP pool
            assert mock_send.call_count >= 1
            spoken = mock_send.call_args.args[1]
            assert spoken in computer_use._HEARTBEAT_MESSAGES_GP

    async def test_uses_normal_messages(self):
        with patch.object(computer_use.ws_manager, "send_narration", new_callable=AsyncMock) as mock_send:
            task = asyncio.create_task(
                computer_use._heartbeat("s1", grandparents_mode=False, interval=0.01)
            )
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            assert mock_send.call_count >= 1
            spoken = mock_send.call_args.args[1]
            assert spoken in computer_use._HEARTBEAT_MESSAGES

    async def test_cancellable(self):
        task = asyncio.create_task(
            computer_use._heartbeat("s1", grandparents_mode=False, interval=10.0)
        )
        await asyncio.sleep(0.01)
        task.cancel()
        # Should not raise — _heartbeat swallows CancelledError
        await task
        assert task.done()


class TestWithHeartbeatContextManager:
    async def test_starts_and_cancels_heartbeat(self):
        with patch.object(computer_use.ws_manager, "send_narration", new_callable=AsyncMock) as mock_send:
            async with computer_use._with_heartbeat("s1", False, interval=0.02):
                await asyncio.sleep(0.05)
            # After the context exits, no more calls should happen
            calls_at_exit = mock_send.call_count
            await asyncio.sleep(0.05)
            assert mock_send.call_count == calls_at_exit  # no further calls

    async def test_short_op_doesnt_fire_heartbeat(self):
        """If the work finishes before the first interval, no heartbeat is sent."""
        with patch.object(computer_use.ws_manager, "send_narration", new_callable=AsyncMock) as mock_send:
            async with computer_use._with_heartbeat("s1", False, interval=1.0):
                await asyncio.sleep(0.01)  # finishes fast
            assert mock_send.call_count == 0


class TestHeartbeatMessagePools:
    def test_normal_pool_nonempty(self):
        assert len(computer_use._HEARTBEAT_MESSAGES) > 0

    def test_grandparents_pool_nonempty(self):
        assert len(computer_use._HEARTBEAT_MESSAGES_GP) > 0

    def test_grandparents_pool_avoids_jargon(self):
        """Grandparents messages should not use technical terms."""
        jargon = ["URL", "agent", "DOM", "API", "click"]
        for msg in computer_use._HEARTBEAT_MESSAGES_GP:
            lower = msg.lower()
            # "agent" appears nowhere in our GP pool — sanity check
            for term in ["url", "dom", "api"]:
                assert term not in lower.split(), f"Jargon '{term}' in GP message: {msg}"
