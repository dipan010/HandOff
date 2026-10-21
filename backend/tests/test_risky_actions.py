"""H1: buttons that send, pay, book, post or delete always pause for a yes, in code,
even when the model doesn't call ask_before."""

import pytest

from tests.fakes import FakeCaller, FakePageBrowser, action_reply, calls_reply, page
from tests.test_page_step import start, sent

CART = page("https://shop.example.com/cart", ("button", "Place your order"), ("link", "Continue shopping"))
CHAT = page("https://web.whatsapp.com/", ("text box", "Type a message", "", ["focused"]), ("button", "Send"))
HOME = page("https://www.irctc.co.in/", ("link", "Book Ticket"), ("button", "Search"))
HOME["elements"][0]["href"] = "/nget/train-search"


@pytest.fixture
def answers(monkeypatch):
    """Records each pause and answers with the queued replies (default: no)."""
    asked, replies = [], []

    async def fake_pause(session_id, reason, prompt, ui, needs_input=False):
        asked.append(prompt)
        return (replies.pop(0) if replies else False), None

    monkeypatch.setattr("app.steps.page_step.pause_and_wait", fake_pause)
    return asked, replies


async def test_clicking_place_order_pauses_even_without_ask_before(answers):
    asked, _ = answers
    browser = FakePageBrowser([CART])
    caller = FakeCaller(actions=[action_reply(call=("click", {"element_id": 1}))])
    ui = await start(caller, browser, task="buy the speaker in my cart")
    assert len(asked) == 1 and "Place your order" in asked[0]
    assert browser.actions == []                       # the user said no, nothing clicked
    assert sent(ui, "send_task_complete") == []


async def test_a_yes_lets_the_click_happen(answers):
    asked, replies = answers
    replies.append(True)
    browser = FakePageBrowser([CART, page("https://shop.example.com/thanks", ("link", "Your orders"))])
    caller = FakeCaller(actions=[
        action_reply(call=("click", {"element_id": 1})),
        action_reply(call=("task_complete", {"summary": "Order placed."})),
    ])
    await start(caller, browser, task="buy the speaker in my cart")
    assert len(asked) == 1
    assert browser.actions == [("click_element", {"element_id": 1})]


async def test_ask_before_counts_as_the_yes(answers):
    asked, replies = answers
    replies.append(True)
    browser = FakePageBrowser([CART, page("https://shop.example.com/thanks", ("link", "Your orders"))])
    caller = FakeCaller(actions=[
        calls_reply(("ask_before", {"question": "Place the order for ₹1,299?"}), ("click", {"element_id": 1})),
        action_reply(call=("task_complete", {"summary": "Order placed."})),
    ])
    await start(caller, browser, task="buy the speaker in my cart")
    assert asked == ["Place the order for ₹1,299?"]    # asked once, not twice
    assert browser.actions == [("click_element", {"element_id": 1})]


async def test_enter_in_a_message_box_pauses(answers):
    asked, _ = answers
    browser = FakePageBrowser([CHAT])
    caller = FakeCaller(actions=[action_reply(call=("type_text", {"element_id": 1, "text": "On my way", "submit": True}))])
    await start(caller, browser, task="tell mum I'm on my way on whatsapp")
    assert len(asked) == 1 and "send" in asked[0].lower()
    assert browser.actions == []


async def test_pressing_enter_in_a_focused_message_box_pauses(answers):
    asked, _ = answers
    browser = FakePageBrowser([CHAT])
    caller = FakeCaller(actions=[action_reply(call=("press_key", {"key": "Enter"}))])
    await start(caller, browser, task="tell mum I'm on my way on whatsapp")
    assert len(asked) == 1
    assert browser.actions == []


async def test_navigation_links_and_ordinary_buttons_do_not_pause(answers):
    asked, _ = answers
    browser = FakePageBrowser([HOME, page("https://www.irctc.co.in/nget/train-search", ("text box", "From"))])
    caller = FakeCaller(actions=[
        action_reply(call=("click", {"element_id": 1})),
        action_reply(call=("task_complete", {"summary": "The train search is open."})),
    ])
    await start(caller, browser, task="open irctc train booking")
    assert asked == []
    assert browser.actions == [("click_element", {"element_id": 1})]


async def test_a_yes_covers_only_the_next_action(answers):
    asked, replies = answers
    replies.extend([True, False])
    menu = page("https://shop.example.com/cart", ("button", "Apply coupon"), ("button", "Place your order"))
    browser = FakePageBrowser([menu, menu])
    caller = FakeCaller(actions=[
        calls_reply(("ask_before", {"question": "Apply the coupon?"}), ("click", {"element_id": 1})),
        action_reply(call=("click", {"element_id": 2})),
    ])
    await start(caller, browser, task="buy the speaker in my cart")
    assert len(asked) == 2 and "Place your order" in asked[1]
    assert browser.actions == [("click_element", {"element_id": 1})]


@pytest.mark.parametrize("label,risky", [
    ("Send", True), ("Pay ₹450", True), ("Place order", True), ("Book now", True), ("Post", True),
    ("Delete", True), ("Confirm booking", True), ("Buy now", True),
    ("Search", False), ("Postcode", False), ("Add to cart", False), ("Next", False), ("Booking.com deals", False),
])
def test_risky_button_words(label, risky):
    from app.steps.safety import risky_target
    shop = page("https://example.com/", ("button", label))
    assert bool(risky_target("click", {"element_id": 1}, shop)) is risky
