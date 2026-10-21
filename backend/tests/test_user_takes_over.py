"""H8: when the user clicks or types in HandOff's tab during a task, HandOff
pauses instead of acting on top of them."""

import pytest

from tests.fakes import FakeCaller, FakePageBrowser, action_reply, calls_reply, page
from tests.test_page_step import start, sent

FORM = page("https://example.com/form", ("button", "Next"), ("button", "Back"), ("link", "Help"))


class UserClicksDuring(FakePageBrowser):
    """The user clicks in the tab right after HandOff's first action."""

    user_input_seen = False

    async def execute_action(self, name, args):
        reply = await super().execute_action(name, args)
        if name == "click_element" and len(self.actions) == 1:
            self.user_input_seen = True
        return reply


@pytest.fixture
def answers(monkeypatch):
    asked, replies = [], []

    async def fake_pause(session_id, reason, prompt, ui, needs_input=False):
        asked.append(reason)
        return (replies.pop(0) if replies else False), None

    monkeypatch.setattr("app.steps.page_step.pause_and_wait", fake_pause)
    return asked, replies


async def test_handoff_stops_acting_and_asks_when_the_user_uses_the_page(answers):
    asked, _ = answers
    browser = UserClicksDuring([FORM, FORM, FORM])
    caller = FakeCaller(actions=[calls_reply(("click", {"element_id": 1}), ("click", {"element_id": 2}))])
    ui = await start(caller, browser, task="fill in the form")
    assert asked == ["user_input"]
    assert browser.actions == [("click_element", {"element_id": 1})]   # the second click never ran
    assert sent(ui, "send_task_complete") == []


async def test_continue_carries_on(answers):
    asked, replies = answers
    replies.append(True)
    browser = UserClicksDuring([FORM, FORM, page("https://example.com/done", ("link", "Home"))])
    caller = FakeCaller(actions=[
        calls_reply(("click", {"element_id": 1}), ("click", {"element_id": 2})),
        action_reply(call=("click", {"element_id": 1})),
        action_reply(call=("task_complete", {"summary": "The form is done."})),
    ])
    ui = await start(caller, browser, task="fill in the form")
    assert asked == ["user_input"]
    assert sent(ui, "send_task_complete") == [("The form is done.",)]
