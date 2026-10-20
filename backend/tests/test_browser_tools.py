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
