"""Unit tests for the guardrails module."""

import pytest
from app.guardrails import (
    validate_url,
    is_navigation_allowed,
    is_login_wall,
    validate_task,
    MAX_TASK_LENGTH,
    PAUSE_GATE_TIMEOUT,
)


class TestValidateUrl:
    def test_valid_https(self):
        assert validate_url("https://example.com") is None

    def test_valid_http(self):
        assert validate_url("http://example.com/path?q=1") is None

    def test_empty_string_allowed(self):
        assert validate_url("") is None

    def test_file_scheme_rejected(self):
        assert validate_url("file:///etc/passwd") is not None

    def test_javascript_scheme_rejected(self):
        assert validate_url("javascript:alert(1)") is not None

    def test_data_scheme_rejected(self):
        assert validate_url("data:text/html,<h1>hi</h1>") is not None

    def test_ftp_scheme_rejected(self):
        assert validate_url("ftp://files.example.com") is not None

    def test_localhost_rejected(self):
        assert validate_url("http://localhost:8080") is not None

    def test_127_loopback_rejected(self):
        assert validate_url("http://127.0.0.1") is not None

    def test_private_10_rejected(self):
        assert validate_url("http://10.0.0.1/admin") is not None

    def test_private_192_168_rejected(self):
        assert validate_url("http://192.168.1.100") is not None

    def test_private_172_16_rejected(self):
        assert validate_url("http://172.16.0.1") is not None

    def test_private_172_31_rejected(self):
        assert validate_url("http://172.31.255.255") is not None

    def test_private_172_15_allowed(self):
        # 172.15.x.x is NOT in the private range
        assert validate_url("http://172.15.0.1") is None

    def test_ipv6_loopback_rejected(self):
        assert validate_url("http://[::1]/") is not None

    def test_public_ip_allowed(self):
        assert validate_url("http://8.8.8.8") is None


class TestIsNavigationAllowed:
    def test_no_blocklist_or_allowlist(self):
        ok, reason = is_navigation_allowed("https://example.com", [], [])
        assert ok
        assert reason == ""

    def test_blocked_domain_exact(self):
        ok, reason = is_navigation_allowed("https://evil.com", ["evil.com"], [])
        assert not ok
        assert "evil.com" in reason

    def test_blocked_subdomain(self):
        ok, _ = is_navigation_allowed("https://sub.evil.com", ["evil.com"], [])
        assert not ok

    def test_non_blocked_domain_not_affected(self):
        ok, _ = is_navigation_allowed("https://good.com", ["evil.com"], [])
        assert ok

    def test_allowlist_pass(self):
        ok, _ = is_navigation_allowed("https://trusted.com/page", [], ["trusted.com"])
        assert ok

    def test_allowlist_subdomain_pass(self):
        ok, _ = is_navigation_allowed("https://sub.trusted.com", [], ["trusted.com"])
        assert ok

    def test_allowlist_blocks_others(self):
        ok, reason = is_navigation_allowed("https://other.com", [], ["trusted.com"])
        assert not ok
        assert "permitted" in reason

    def test_private_always_blocked_regardless_of_lists(self):
        ok, _ = is_navigation_allowed("http://192.168.1.1", [], [])
        assert not ok

    def test_localhost_blocked_regardless_of_allowlist(self):
        ok, _ = is_navigation_allowed("http://localhost", [], ["localhost"])
        assert not ok

    def test_file_scheme_blocked(self):
        ok, _ = is_navigation_allowed("file:///etc/passwd", [], [])
        assert not ok

    def test_empty_url_allowed(self):
        ok, _ = is_navigation_allowed("", ["evil.com"], [])
        assert ok


class TestIsLoginWall:
    def test_google_accounts(self):
        assert is_login_wall("https://accounts.google.com/signin") is True

    def test_paypal_exact(self):
        assert is_login_wall("https://paypal.com/signin") is True

    def test_paypal_subdomain(self):
        assert is_login_wall("https://www.paypal.com/login") is True

    def test_facebook(self):
        assert is_login_wall("https://facebook.com/login") is True

    def test_login_path(self):
        assert is_login_wall("https://mybank.com/login") is True

    def test_signin_path(self):
        assert is_login_wall("https://example.com/signin?redirect=/home") is True

    def test_checkout_path(self):
        assert is_login_wall("https://shop.example.com/checkout/review") is True

    def test_payment_path(self):
        assert is_login_wall("https://service.com/payment") is True

    def test_normal_url(self):
        assert is_login_wall("https://example.com/about") is False

    def test_empty_string(self):
        assert is_login_wall("") is False

    def test_login_subdomain(self):
        # login.example.com is a login wall by subdomain prefix
        assert is_login_wall("https://login.example.com/") is True

    def test_pay_subdomain(self):
        assert is_login_wall("https://pay.shop.com/order") is True

    def test_no_substring_evasion_paypal(self):
        # "notapaypal.com" must NOT match paypal.com
        assert is_login_wall("https://notapaypal.com") is False

    def test_no_substring_evasion_login_in_query(self):
        # /products?ref=login should not be caught as a login wall
        assert is_login_wall("https://store.com/products?ref=login") is False


class TestValidateTask:
    def test_valid_task(self):
        assert validate_task("Book a flight to Paris") is None

    def test_empty_string_rejected(self):
        assert validate_task("") is not None

    def test_whitespace_only_rejected(self):
        assert validate_task("   \t\n  ") is not None

    def test_exactly_max_length_accepted(self):
        assert validate_task("x" * MAX_TASK_LENGTH) is None

    def test_one_over_max_rejected(self):
        err = validate_task("x" * (MAX_TASK_LENGTH + 1))
        assert err is not None
        assert str(MAX_TASK_LENGTH) in err

    def test_error_message_mentions_length(self):
        big = "y" * (MAX_TASK_LENGTH + 100)
        err = validate_task(big)
        assert err is not None
        assert str(MAX_TASK_LENGTH + 100) in err


class TestConstants:
    def test_max_task_length_is_reasonable(self):
        assert 1000 <= MAX_TASK_LENGTH <= 10000

    def test_pause_gate_timeout_is_positive(self):
        assert PAUSE_GATE_TIMEOUT > 0
