"""Item 5c: the banner says what HandOff is doing in plain words ("Clicking
'Search'"), never a tool name like "Executing: click" (spec §7)."""

from app.steps.describe import action_now
from tests.fakes import FakeCaller, FakePageBrowser, action_reply, page
from tests.test_page_step import SEARCH_PAGE, RESULTS_PAGE, PLAYING_PAGE, sent, start

FORM = page("https://example.com/form", ("search box", "Search"), ("checkbox", "Student fare"), ("dropdown", "Class"))


def test_actions_are_described_by_what_they_touch():
    assert action_now("click", {"element_id": 1}, SEARCH_PAGE) == "Clicking 'Search'"
    assert action_now("type_text", {"element_id": 1, "text": "lofi", "submit": True}, FORM) == \
        "Typing 'lofi' into 'Search' and searching"
    assert action_now("set_checked", {"element_id": 2, "checked": True}, FORM) == "Ticking 'Student fare'"
    assert action_now("choose_option", {"element_id": 3, "text": "Sleeper"}, FORM) == "Choosing 'Sleeper' in 'Class'"
    assert action_now("open_page", {"url": "https://www.youtube.com/results?q=x"}, None) == "Opening youtube.com"
    assert action_now("search_web", {"query": "alan turing"}, None) == "Searching for 'alan turing'"
    assert action_now("press_key", {"key": "Enter"}, None) == "Pressing Enter"


def test_actions_without_a_known_target_still_read_plainly():
    assert action_now("click", {"element_id": 99}, FORM) == "Clicking a button or link"
    assert action_now("click_at", {"x": 10, "y": 20}, None) == "Clicking on the page"
    assert action_now("something_new", {}, None) == "Working on the page"


async def test_the_banner_never_shows_a_tool_name():
    browser = FakePageBrowser([SEARCH_PAGE, RESULTS_PAGE, PLAYING_PAGE])
    caller = FakeCaller(actions=[
        action_reply(call=("type_text", {"element_id": 1, "text": "lofi hip hop radio", "submit": True})),
        action_reply(call=("click", {"element_id": 1})),
        action_reply(call=("task_complete", {"summary": "The lofi stream is playing."})),
    ])
    ui = await start(caller, browser)
    doing = [args[1] for args in sent(ui, "send_status") if args[0] == "executing"]
    assert doing == ["Typing a message into 'Search' and searching",
                     "Clicking 'lofi hip hop radio - beats to relax/study to'"]
