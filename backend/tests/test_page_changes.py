"""The extension reports what a click or typing action changed on the page (spec §7)."""

from app.steps.check import ScreenState, change_words, changed
from app.tools.browser import BrowserTools
from tests.fakes import FakePageBrowser, action_reply, page

FORM = page("https://shop.example.com/cart", ("button", "Add rows"), ("button", "Send once"))
SCROLLED = {**FORM, "scroll": {"y": 300, "max": 900}}
MORE = page("https://shop.example.com/cart", ("button", "Add rows"), ("button", "Send once"), ("link", "Row 1"))

NOTHING = {"changed": False, "added": 0, "removed": 0, "opened": 0, "closed": 0, "ticked": 0, "unticked": 0,
           "typed": 0, "chosen": 0, "disabled": 0, "enabled": 0, "text": 0}


def report(**counts) -> dict:
    return {**NOTHING, "changed": True, **counts}


def click(change: dict) -> list[dict]:
    return [{"action": "click_element", "success": True, "page_change": change}]


def test_change_words_are_plain():
    assert change_words(report(added=3, opened=1)) == "3 items added, something opened"
    assert change_words(report(ticked=1, typed=1)) == "1 box ticked, text typed"
    assert change_words(report(text=2)) == "some text changed"


def test_a_reported_change_counts_even_when_the_visible_items_look_the_same():
    # e.g. rows added below the fold, which the page view doesn't list
    state = ScreenState.of(FORM["url"], b"1", page=FORM)
    result = changed(state, state, click(report(added=3)), ["click_element"])
    assert result.ok and "3 items added" in result.reason


def test_nothing_reported_and_only_the_scroll_moved_is_no_effect():
    # Bringing the button into view scrolls the page; that alone isn't the click working.
    result = changed(ScreenState.of(FORM["url"], b"1", page=FORM), ScreenState.of(FORM["url"], b"2", page=SCROLLED),
                     click(NOTHING), ["click_element"])
    assert not result.ok and "nothing on the page changed" in result.reason.lower()


def test_a_late_change_the_report_missed_still_counts():
    result = changed(ScreenState.of(FORM["url"], b"1", page=FORM), ScreenState.of(MORE["url"], b"2", page=MORE),
                     click(NOTHING), ["click_element"])
    assert result.ok


def test_scrolling_on_purpose_still_counts_as_a_change():
    results = click(NOTHING) + [{"action": "scroll_page", "success": True}]
    result = changed(ScreenState.of(FORM["url"], b"1", page=FORM), ScreenState.of(FORM["url"], b"2", page=SCROLLED),
                     results, ["click_element", "scroll_page"])
    assert result.ok


def test_a_box_that_was_already_ticked_needed_no_change():
    state = ScreenState.of(FORM["url"], b"1", page=FORM)
    results = [{"action": "set_checked", "success": True, "already": True, "page_change": NOTHING}]
    assert changed(state, state, results, ["set_checked"]).ok


def test_a_click_that_left_the_page_before_answering_is_not_a_failure():
    before = ScreenState.of(FORM["url"], b"1", page=FORM)
    after = ScreenState.of("https://shop.example.com/checkout", b"2")
    results = [{"action": "click_element", "success": False, "no_answer": True,
                "detail": "The page did not answer (it may still be loading)."}]
    assert changed(before, after, results, ["click_element"]).ok
    # ...but no answer and still on the same page is.
    assert not changed(before, ScreenState.of(FORM["url"], b"1", page=FORM), results, ["click_element"]).ok


async def test_the_model_is_told_what_the_click_changed():
    browser = FakePageBrowser([FORM], frozen=True,
                              replies={"click_element": {"success": True, "page_change": report(added=3)}})
    result = await BrowserTools(browser).run("click", {"element_id": 1})
    assert result.ok and result.message == "Clicked 1. The page changed: 3 items added."


async def test_the_model_is_told_when_a_click_changed_nothing():
    browser = FakePageBrowser([FORM], frozen=True,
                              replies={"click_element": {"success": True, "page_change": NOTHING}})
    result = await BrowserTools(browser).run("click", {"element_id": 1})
    assert result.ok and result.message == "Clicked 1. Nothing on the page changed."


class ScrollsOnly(FakePageBrowser):
    """Every click scrolls the page (to bring the button into view) and does nothing else."""

    async def execute_action(self, name, args):
        reply = await super().execute_action(name, args)
        if name == "click_element":
            return {"success": True, "page_change": NOTHING}
        return reply


async def test_a_click_that_only_scrolled_is_retried_another_way():
    from tests.test_page_step import start
    from tests.fakes import FakeCaller

    browser = ScrollsOnly([FORM, SCROLLED])
    seen = []
    caller = FakeCaller(actions=[
        action_reply(call=("click", {"element_id": 1})),
        action_reply(call=("task_complete", {"summary": "Rows added."})),
    ])
    original = caller.ask

    async def spy(model, contents, config=None):
        if config is not None and getattr(config, "tools", None):
            seen.append(" ".join(p.text for p in contents[-1].parts if p.text))
        return await original(model, contents, config)

    caller.ask = spy
    await start(caller, browser, task="add rows to the cart")
    assert "Nothing on the page changed" in seen[1] and "Try a different way" in seen[1]
