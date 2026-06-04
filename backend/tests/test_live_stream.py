"""Tests for app.live_stream — heartbeat receiver, completion signalling.

The full run_live_stream is hard to test directly because it opens a Gemini
Live API connection.  We test the constants and prompts here; the run-loop
behaviour is exercised by integration tests against a real Live API.
"""

import pytest

from app import live_stream


class TestConstants:
    def test_screenshot_interval_positive(self):
        assert live_stream.NARRATION_SCREENSHOT_INTERVAL > 0

    def test_narration_gap_positive(self):
        assert live_stream.MIN_NARRATION_GAP > 0

    def test_action_cooldown_positive(self):
        assert live_stream.ACTION_NARRATION_COOLDOWN > 0


class TestPrompts:
    def test_default_prompt_is_real(self):
        assert isinstance(live_stream.NARRATION_PROMPT_DEFAULT, str)
        assert len(live_stream.NARRATION_PROMPT_DEFAULT) > 50

    def test_grandparents_prompt_is_real(self):
        assert isinstance(live_stream.NARRATION_PROMPT_GRANDPARENTS, str)
        assert len(live_stream.NARRATION_PROMPT_GRANDPARENTS) > 50

    def test_grandparents_avoids_technical_jargon(self):
        text = live_stream.NARRATION_PROMPT_GRANDPARENTS.lower()
        # The prompt should explicitly forbid jargon
        assert "jargon" in text or "technical" in text

    def test_default_prompt_mentions_screen(self):
        assert "screen" in live_stream.NARRATION_PROMPT_DEFAULT.lower()
