"""H2: when one action in a turn lands on a sign-in or payment page, the actions
after it in the same turn don't run unchecked."""

from tests.fakes import FakeCaller, FakePageBrowser, calls_reply, page
from tests.test_page_step import start, sent

SHOP = page("https://shop.example.com/item/42", ("button", "Continue"), ("text box", "Coupon"))
SIGN_IN = page("https://shop.example.com/login", ("text box", "Email"), ("button", "Next"))


async def test_actions_after_landing_on_a_sign_in_page_wait_for_the_user(monkeypatch):
    asked = []

    async def say_no(session_id, reason, prompt, ui, needs_input=False):
        asked.append(reason)
        return False, None

    monkeypatch.setattr("app.steps.safety.pause_and_wait", say_no)
    browser = FakePageBrowser([SHOP, SIGN_IN])
    caller = FakeCaller(actions=[calls_reply(
        ("click", {"element_id": 1}),
        ("type_text", {"element_id": 1, "text": "me@example.com"}),
    )])
    ui = await start(caller, browser, task="buy item 42")
    assert asked == ["login_wall"]
    assert browser.actions == [("click_element", {"element_id": 1})]   # nothing typed on the sign-in page
    assert sent(ui, "send_task_complete") == []
