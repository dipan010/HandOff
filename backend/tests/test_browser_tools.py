"""The bigger browser tools: each does several small actions and returns one answer."""

from app.tools.browser import BrowserTools
from tests.fakes import FakePageBrowser, page

BLANK = page("about:blank")
RESULTS = [
    {"title": "Alan Turing - Wikipedia", "url": "https://en.wikipedia.org/wiki/Alan_Turing", "snippet": ""},
    {"title": "Alan Turing | Britannica", "url": "https://www.britannica.com/biography/Alan-Turing", "snippet": ""},
]


def navigations(browser):
    return [args["url"] for name, args in browser.actions if name == "navigate"]


async def test_search_goes_straight_to_a_named_site():
    browser = FakePageBrowser([BLANK, page("https://www.youtube.com/results?search_query=lofi")])
    result = await BrowserTools(browser).run("search_web", {"query": "lofi", "site": "youtube"})
    assert result.ok
    assert navigations(browser) == ["https://www.youtube.com/results?search_query=lofi"]


async def test_search_opens_the_best_result_and_lists_the_others():
    browser = FakePageBrowser([BLANK, page("https://www.google.com/search?q=alan+turing"), page(RESULTS[0]["url"])],
                              results=RESULTS)
    result = await BrowserTools(browser).run("search_web", {"query": "alan turing"})
    assert result.ok
    assert navigations(browser) == ["https://www.google.com/search?q=alan+turing", RESULTS[0]["url"]]
    assert "Alan Turing - Wikipedia" in result.message and "2. Alan Turing | Britannica" in result.message


async def test_search_can_just_list_results():
    browser = FakePageBrowser([BLANK, page("https://www.bing.com/search?q=alan+turing")], results=RESULTS)
    result = await BrowserTools(browser, search_engine="bing").run(
        "search_web", {"query": "alan turing", "open_result": False})
    assert navigations(browser) == ["https://www.bing.com/search?q=alan+turing"]
    assert "1. Alan Turing - Wikipedia" in result.message


async def test_search_with_no_readable_results_leaves_the_page_open():
    browser = FakePageBrowser([BLANK, page("https://www.google.com/search?q=x")])
    result = await BrowserTools(browser).run("search_web", {"query": "x"})
    assert result.ok and "pick one from the page view" in result.message
    assert len(navigations(browser)) == 1


async def test_password_boxes_are_never_typed_into():
    login = page("https://example.com/login", ("text box", "Email"), ("text box", "Password"))
    login["elements"][1]["secret"] = True
    browser = FakePageBrowser([login])
    tools = BrowserTools(browser)
    tools.last_page = login
    result = await tools.run("type_text", {"element_id": 2, "text": "hunter2"})
    assert not result.ok and "never types" in result.message
    assert browser.actions == []


async def test_pull_list_turns_tables_and_lists_into_short_text():
    found = {"success": True, "tables": [{"caption": "Trains", "header": ["Train", "Fare"],
                                          "rows": [["Rajdhani", "₹3,200"], ["Poorva", "₹1,450"]], "more": 0}],
             "lists": [{"items": [{"text": "JBL Go 3 · ₹2,999", "link": "https://shop.example.com/p/2"}], "more": 5}]}
    browser = FakePageBrowser([BLANK], replies={"pull_items": found})
    result = await BrowserTools(browser).run("pull_list", {"about": "fares"})
    assert result.ok and not result.is_action
    assert result.message.splitlines()[:4] == ["Table 1: Trains", "Train | Fare", "Rajdhani | ₹3,200", "Poorva | ₹1,450"]
    assert "1. JBL Go 3 · ₹2,999 -> https://shop.example.com/p/2" in result.message
    assert "(+5 more items further down)" in result.message


async def test_pull_list_on_a_page_without_lists():
    browser = FakePageBrowser([BLANK], replies={"pull_items": {"success": True, "tables": [], "lists": []}})
    result = await BrowserTools(browser).run("pull_list", {})
    assert not result.ok and "read_page" in result.message


FORM = page("https://www.irctc.co.in/nget/train-search",
            ("text box", "From station"), ("text box", "To station"), ("dropdown", "Class"),
            ("checkbox", "Student fare"), ("radio", "Female"), ("text box", "Password"), ("button", "Search"))
FORM["elements"][5]["secret"] = True


async def test_fill_form_uses_the_right_action_for_each_box_and_never_submits():
    browser = FakePageBrowser([FORM], frozen=True, replies={"choose_option": {"success": True, "chosen": "AC 3 Tier (3A)"}})
    result = await BrowserTools(browser).run("fill_form", {"fields": [
        {"label": "From", "value": "Howrah"},
        {"label": "To station", "value": "New Delhi"},
        {"label": "class", "value": "AC 3 Tier"},
        {"label": "Student fare", "value": "yes"},
        {"label": "Gender", "value": "Female"},
        {"label": "Password", "value": "hunter2"},
        {"label": "Coach number", "value": "B2"},
    ]})
    assert browser.actions == [
        ("type_text", {"element_id": 1, "text": "Howrah", "submit": False}),
        ("type_text", {"element_id": 2, "text": "New Delhi", "submit": False}),
        ("choose_option", {"element_id": 3, "text": "AC 3 Tier"}),
        ("set_checked", {"element_id": 4, "checked": True}),
        ("set_checked", {"element_id": 5, "checked": True}),
    ]
    assert result.ok
    assert "Class = AC 3 Tier (3A)" in result.message
    assert "No box found for: Coach number" in result.message
    assert "Password" in result.message and "user must do these" in result.message
    assert "has not been sent" in result.message


async def test_fill_form_with_nothing_matching_fails():
    browser = FakePageBrowser([FORM], frozen=True)
    result = await BrowserTools(browser).run("fill_form", {"fields": [{"label": "Coach number", "value": "B2"}]})
    assert not result.ok and browser.actions == []


def test_each_step_is_offered_the_tools_that_fit_it():
    from app.tools.browser import ALL_TOOLS, tools_for_step
    reading = tools_for_step("Read the Founders section of the article. The founders' names are visible")
    assert {"search_web", "pull_list", "fill_form"}.isdisjoint(reading)
    assert {"click", "type_text", "read_page", "click_at", "ask_before", "task_complete"} <= set(reading)
    assert "search_web" in tools_for_step("Search YouTube for lofi hip hop")
    assert "pull_list" in tools_for_step("Find the cheapest flight in the results")
    assert "fill_form" in tools_for_step("Enter the travel dates and passenger details")
    assert len(reading) < len(ALL_TOOLS)


async def test_fill_form_types_into_pickers_that_only_list_matches_after_typing():
    picker = page("https://www.makemytrip.com/", ("dropdown", "From"))
    calls = []

    class Picker(FakePageBrowser):
        async def execute_action(self, name, args):
            if name == "choose_option":
                calls.append(args)
                typed = any(n == "type_text" for n, _ in self.actions)
                self.actions.append((name, args))
                return {"success": True, "chosen": "Kolkata, India"} if typed else {"success": False, "detail": "No option"}
            return await super().execute_action(name, args)

    browser = Picker([picker], frozen=True)
    result = await BrowserTools(browser, settle_seconds=0).run("fill_form", {"fields": [{"label": "From", "value": "Kolkata"}]})
    assert [n for n, _ in browser.actions] == ["choose_option", "type_text", "choose_option"]
    assert calls[1] == {"text": "Kolkata"}
    assert result.ok and "From = Kolkata, India" in result.message
