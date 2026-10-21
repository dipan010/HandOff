"""Item 2: plain-code step checks. They answer only when the page proves it;
otherwise they return None and the check model decides."""

from app.steps.check import quick_check
from app.steps.plan import Step
from tests.fakes import page


def step(title, done_when):
    return Step(number=1, title=title, done_when=done_when)


YT_HOME = page("https://www.youtube.com/", ("search box", "Search"))
YT_RESULTS = page("https://www.youtube.com/results?search_query=lofi+hip+hop", ("link", "lofi hip hop radio"))
YT_PLAYING = page("https://www.youtube.com/watch?v=jfKfPfyJRdk", ("button", "Pause (k)"), ("link", "Lofi Girl"))
WIKI = page("https://en.wikipedia.org/wiki/Google_DeepMind", ("link", "History"))
WIKI_TEXT = "DeepMind Technologies was founded in September 2010 by Demis Hassabis, Shane Legg and Mustafa Suleyman."


def test_opening_a_named_site_is_proved_by_the_address():
    result = quick_check(step("Go to YouTube", "The YouTube homepage is open"), YT_HOME["url"], YT_HOME, "", "")
    assert result is not None and result.ok


def test_search_results_need_the_search_words_in_the_address_or_page():
    s = step("Search YouTube for 'lofi hip hop'", "YouTube search results for 'lofi hip hop' are shown")
    assert quick_check(s, YT_RESULTS["url"], YT_RESULTS, "", "").ok
    assert quick_check(s, YT_HOME["url"], YT_HOME, "", "") is None      # can't tell: ask the model


def test_wrong_site_is_not_done():
    s = step("Search YouTube for 'lofi hip hop'", "YouTube search results for 'lofi hip hop' are shown")
    result = quick_check(s, "https://www.google.com/search?q=lofi", page("https://www.google.com/search?q=lofi"), "", "")
    assert result is not None and not result.ok and "youtube" in result.reason.lower()


def test_a_playing_video_shows_a_pause_button():
    s = step("Click a 'lofi hip hop' video to play it", "A lofi hip hop video is playing")
    assert quick_check(s, YT_PLAYING["url"], YT_PLAYING, "", "").ok


def test_an_answer_is_proved_when_its_facts_are_on_the_page():
    s = step("Find who founded DeepMind on Wikipedia", "The founders' names are visible")
    summary = "DeepMind was founded in 2010 by Demis Hassabis, Shane Legg and Mustafa Suleyman."
    assert quick_check(s, WIKI["url"], WIKI, WIKI_TEXT, summary, ends_task=True).ok


def test_an_answer_with_facts_not_on_the_page_goes_to_the_model():
    s = step("Find who founded DeepMind on Wikipedia", "The founders' names are visible")
    assert quick_check(s, WIKI["url"], WIKI, WIKI_TEXT, "It was founded by Larry Page in 2014.", ends_task=True) is None


def test_finding_steps_are_never_passed_on_the_address_alone():
    s = step("Find who founded DeepMind on Wikipedia", "The founders' names are visible")
    assert quick_check(s, WIKI["url"], WIKI, WIKI_TEXT, "The article is open.") is None


def test_a_not_found_page_is_not_done():
    missing = page("https://en.wikipedia.org/wiki/Deepmindd")
    missing["title"] = "Page not found - Wikipedia"
    s = step("Open the DeepMind article on Wikipedia", "The DeepMind article is open")
    result = quick_check(s, missing["url"], missing, "", "")
    assert result is not None and not result.ok


def test_ordinary_steps_go_to_the_model():
    assert quick_check(step("Do it", "It is done"), "https://example.com/", page("https://example.com/"), "", "") is None


def test_steps_naming_two_sites_are_left_to_the_model():
    s = step("Open the YouTube link from the email in Gmail", "The YouTube video from the email is open")
    gmail = page("https://mail.google.com/mail/u/0/#inbox")
    assert quick_check(s, gmail["url"], gmail, "", "") is None
