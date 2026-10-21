"""Tests for the pure helpers in app.computer_use."""

from app import computer_use
from app.guardrails import is_login_wall


class TestIsLoginWall:
    def test_detects_google_accounts(self):
        assert is_login_wall("https://accounts.google.com/signin")

    def test_detects_paypal(self):
        assert is_login_wall("https://www.paypal.com/login")

    def test_detects_login_subdomain(self):
        assert is_login_wall("https://login.example.com/")

    def test_detects_payment_subdomain(self):
        assert is_login_wall("https://payment.shop.com/checkout")

    def test_does_not_match_random_url(self):
        assert not is_login_wall("https://wikipedia.org/wiki/Login")

    def test_does_not_match_search_results(self):
        assert not is_login_wall("https://google.com/search?q=cats")

    def test_empty_url_safe(self):
        assert not is_login_wall("")

    def test_none_url_safe(self):
        # guardrails.is_login_wall guards against falsy input
        assert not is_login_wall(None)


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
        # "scroll" is now the page tool ("Scroll down"); the screenshot flow's scroll keeps the distance.
        result = computer_use._action_to_plain_english("scroll_document", {"direction": "down", "amount": 3})
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
