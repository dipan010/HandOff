"""Tests for app.config — settings loading."""

from app.config import Settings, get_settings


class TestSettings:
    def test_default_values(self):
        s = Settings(GOOGLE_API_KEY="x")
        assert s.MAX_AGENT_TURNS == 25
        assert s.SCREEN_WIDTH == 1440
        assert s.SCREEN_HEIGHT == 900
        assert s.LIVE_MODEL == "gemini-2.0-flash-exp"
        assert s.COMPUTER_USE_MODEL.startswith("gemini-2.5-computer-use")
        assert s.USE_FIRESTORE is False  # default off, opt-in
        assert s.AGENT_TIMEOUT_SECONDS == 300

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("MAX_AGENT_TURNS", "5")
        monkeypatch.setenv("GOOGLE_API_KEY", "test")
        s = Settings()
        assert s.MAX_AGENT_TURNS == 5

    def test_cors_origins_default(self):
        s = Settings(GOOGLE_API_KEY="x")
        assert "http://localhost:3000" in s.CORS_ORIGINS

    def test_get_settings_is_cached(self):
        a = get_settings()
        b = get_settings()
        assert a is b  # @lru_cache
