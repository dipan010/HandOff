import pytest

from app.config import Settings
from app.steps import run as run_module
from app.steps.page_step import trim_page_views
from app.steps.run import Timing, run_task
from tests.fakes import FakeCaller, FakePageBrowser, FakeUI, action_reply, calls_reply, page

NO_WAIT = Timing(after_action=0, after_page_load=0, preview=0, speak_wait=0, no_frame_wait=0)

SEARCH_PAGE = page("https://www.youtube.com/", ("search box", "Search"), ("button", "Search"), ("link", "Home"))
RESULTS_PAGE = page("https://www.youtube.com/results?search_query=lofi",
                    ("link", "lofi hip hop radio - beats to relax/study to"), ("link", "Shorts"), ("button", "Filters"))
PLAYING_PAGE = page("https://www.youtube.com/watch?v=jfKfPfyJRdk",
                    ("button", "Pause (k)"), ("link", "Lofi Girl"), ("button", "Subscribe"))


@pytest.fixture(autouse=True)
def quiet_side_effects(monkeypatch):
    async def nothing(*a, **k):
        return None

    monkeypatch.setattr(run_module, "upload_screenshot", nothing)
    monkeypatch.setattr("app.steps.page_step.log_action", nothing)
    monkeypatch.setattr("app.steps.page_step.update_session_state", nothing)
    monkeypatch.setattr("app.steps.finish.update_session_state", nothing)


def cfg(**overrides):
    return Settings(GOOGLE_API_KEY="test", ACTION_MODE="page",
                    FAST_MODEL="fast", STRONG_MODEL="strong", BACKUP_MODEL="backup",
                    COMPUTER_USE_MODEL="computer-use", **overrides)


async def start(caller, browser, task="play lofi on youtube", **settings):
    ui = FakeUI()
    await run_task("s1", task, "", browser, caller=caller, ui=ui, cfg=cfg(**settings), timing=NO_WAIT)
    return ui


def sent(ui, name):
    return [args for n, args, _ in ui.sent if n == name]


async def test_acts_on_numbered_items_without_the_computer_use_model():
    browser = FakePageBrowser([SEARCH_PAGE, RESULTS_PAGE, PLAYING_PAGE])
    caller = FakeCaller(actions=[
        action_reply(call=("type_text", {"element_id": 1, "text": "lofi hip hop radio", "submit": True})),
        action_reply(call=("click", {"element_id": 1})),
        action_reply(call=("task_complete", {"summary": "The lofi stream is playing."})),
    ])
    ui = await start(caller, browser)

    assert browser.actions == [
        ("type_text", {"element_id": 1, "text": "lofi hip hop radio", "submit": True}),
        ("click_element", {"element_id": 1}),
    ]
    assert sent(ui, "send_task_complete") == [("The lofi stream is playing.",)]
    assert ("action", "computer-use") not in caller.calls
    assert ("action", "fast") in caller.calls


async def test_page_view_lists_numbers_and_no_screenshot_when_page_is_readable():
    seen = []
    caller = FakeCaller(actions=[action_reply(call=("task_complete", {"summary": "done"}))])
    original = caller.ask

    async def spy(model, contents, config=None):
        if config is not None and getattr(config, "tools", None):
            seen.append(contents[-1])
        return await original(model, contents, config)

    caller.ask = spy
    await start(caller, FakePageBrowser([SEARCH_PAGE]))
    last = seen[0]
    text = " ".join(p.text for p in last.parts if p.text)
    assert '[1] search box "Search"' in text and '[2] button "Search"' in text
    assert not any(p.inline_data for p in last.parts)


async def test_screenshot_added_when_page_view_is_nearly_empty():
    seen = []
    canvas = page("https://maps.example.com/", ("button", "Zoom in"))
    caller = FakeCaller(actions=[action_reply(call=("task_complete", {"summary": "done"}))])
    original = caller.ask

    async def spy(model, contents, config=None):
        if config is not None and getattr(config, "tools", None):
            seen.append(contents[-1])
        return await original(model, contents, config)

    caller.ask = spy
    await start(caller, FakePageBrowser([canvas]))
    assert any(p.inline_data for p in seen[0].parts)


async def test_vanished_element_is_reported_and_retried():
    browser = FakePageBrowser(
        [SEARCH_PAGE, RESULTS_PAGE],
        replies={"click_element": {"success": False, "stale": True, "detail": "Element 9 is no longer on the page."}},
    )
    caller = FakeCaller(actions=[
        action_reply(call=("click", {"element_id": 9})),
        action_reply(call=("type_text", {"element_id": 1, "text": "lofi", "submit": True})),
        action_reply(call=("task_complete", {"summary": "Results shown."})),
    ])
    ui = await start(caller, browser)
    assert browser.actions[0] == ("click_element", {"element_id": 9})
    assert len(browser.actions) == 2
    assert sent(ui, "send_task_complete") == [("Results shown.",)]


async def test_frozen_page_gives_up_with_plain_reason():
    browser = FakePageBrowser([SEARCH_PAGE], frozen=True)
    caller = FakeCaller(actions=[action_reply(call=("click", {"element_id": 2}))])
    ui = await start(caller, browser, MAX_PLAN_REVISIONS=0)
    summary = sent(ui, "send_task_complete")[0][0]
    assert summary.startswith("I couldn't finish this.")
    assert "Nothing on the screen changed" in summary


async def test_a_failed_action_skips_the_rest_of_the_turn():
    browser = FakePageBrowser([SEARCH_PAGE, RESULTS_PAGE],
                              replies={"type_text": {"success": False, "detail": "That element can't be typed into."}})
    caller = FakeCaller(actions=[
        calls_reply(("type_text", {"element_id": 3, "text": "lofi"}), ("click", {"element_id": 2})),
        action_reply(call=("task_complete", {"summary": "ok"})),
    ])
    await start(caller, browser)
    assert [a[0] for a in browser.actions] == ["type_text"]


async def test_last_step_done_is_followed_by_a_spoken_answer():
    wiki = page("https://en.wikipedia.org/wiki/Google_DeepMind", ("link", "Founders"), ("search box", "Search Wikipedia"), ("link", "History"))
    browser = FakePageBrowser([wiki], text="DeepMind was founded by Demis Hassabis, Shane Legg and Mustafa Suleyman.")
    caller = FakeCaller(actions=[
        action_reply(call=("step_done", {"evidence": "The article is open"})),
        action_reply(call=("task_complete", {"summary": "DeepMind was founded by Demis Hassabis, Shane Legg and Mustafa Suleyman."})),
    ])
    ui = await start(caller, browser, task="who founded DeepMind? check wikipedia")
    assert "Demis Hassabis" in sent(ui, "send_task_complete")[0][0]
    assert caller.count("check") == 1


async def test_user_saying_no_stops_the_task(monkeypatch):
    async def say_no(*a, **k):
        return False, None

    monkeypatch.setattr("app.steps.page_step.pause_and_wait", say_no)
    caller = FakeCaller(actions=[action_reply(call=("ask_before", {"question": "Pay ₹450 for this ticket?"}))])
    browser = FakePageBrowser([SEARCH_PAGE])
    ui = await start(caller, browser)
    assert browser.actions == []
    assert sent(ui, "send_task_complete") == []


async def test_every_tool_call_gets_an_answer():
    """Gemini rejects a turn if any tool call in the previous turn has no answer."""
    browser = FakePageBrowser([SEARCH_PAGE, RESULTS_PAGE, PLAYING_PAGE])
    turns = []
    caller = FakeCaller(actions=[
        calls_reply(("read_page", {}), ("type_text", {"element_id": 1, "text": "lofi", "submit": True})),
        action_reply(call=("task_complete", {"summary": "ok"})),
    ])
    original = caller.ask

    async def spy(model, contents, config=None):
        if config is not None and getattr(config, "tools", None):
            turns.append(contents[-1])
        return await original(model, contents, config)

    caller.ask = spy
    await start(caller, browser)
    answers = [p.function_response.name for p in turns[1].parts if p.function_response]
    assert answers == ["read_page", "type_text"]


def test_old_page_views_are_trimmed():
    from google.genai import types
    view = lambda n: types.Content(role="user", parts=[types.Part(text=f"PAGE VIEW\n{n}")])
    trimmed = trim_page_views([view(1), view(2), view(3)], keep=2)
    assert trimmed[0].parts[0].text == "[older page view removed]"
    assert trimmed[2].parts[0].text.endswith("3")
