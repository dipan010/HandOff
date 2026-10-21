import pytest

from app.steps import safety
from app.steps.safety import SignInGuard, is_login_wall
from tests.fakes import FakeUI


@pytest.mark.parametrize("url", [
    "https://accounts.google.com/v3/signin",
    "https://www.netflix.com/login",
    "https://www.amazon.in/ap/signin?openid=x",
    "https://login.microsoftonline.com/common",
    "https://pay.google.com/",
    "https://shop.example.com/checkout/step-1",
    "https://www.paypal.com/in/home",
])
def test_sign_in_and_payment_pages(url):
    assert is_login_wall(url)


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=jfKfPfyJRdk",
    "https://en.wikipedia.org/wiki/Google_DeepMind",
    "https://www.display.com/",
    "https://www.makemytrip.com/flights/",
    "https://www.google.com/search?q=login+help",
    "https://example.com/blog/how-to-login-faster",
    "",
])
def test_ordinary_pages(url):
    assert not is_login_wall(url)


async def test_guard_asks_once_per_page(monkeypatch):
    asked = []

    async def fake_pause(session_id, reason, prompt, ui, needs_input=False):
        asked.append(reason)
        return True, None

    monkeypatch.setattr(safety, "pause_and_wait", fake_pause)
    guard = SignInGuard("s1", FakeUI())
    assert await guard.check("https://www.netflix.com/login") == "resumed"
    assert await guard.check("https://www.netflix.com/login?next=/browse") == "clear"
    assert await guard.check("https://www.youtube.com/") == "clear"
    assert asked == ["login_wall"]


async def test_guard_stops_when_user_says_no(monkeypatch):
    async def fake_pause(*a, **k):
        return False, None

    monkeypatch.setattr(safety, "pause_and_wait", fake_pause)
    assert await SignInGuard("s1", FakeUI()).check("https://accounts.google.com/") == "stopped"
