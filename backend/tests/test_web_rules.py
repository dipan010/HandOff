from app.tools.web_rules import as_address, route, search_url


def test_web_addresses_are_opened_as_they_are():
    assert route("wikipedia.org") == "https://wikipedia.org"
    assert route("https://www.irctc.co.in/nget/train-search") == "https://www.irctc.co.in/nget/train-search"
    assert as_address("alan turing") is None


def test_known_sites_use_their_own_search_page():
    assert route("play lofi on youtube") == "https://www.youtube.com/results?search_query=lofi"
    assert route("Alan Turing wikipedia") == "https://en.wikipedia.org/w/index.php?search=Alan+Turing"
    assert route("bluetooth speaker", site="Amazon") == "https://www.amazon.in/s?k=bluetooth+speaker"


def test_known_site_without_a_search_page_opens_its_home():
    assert route("flights from Delhi to Mumbai on makemytrip") == "https://www.makemytrip.com/"


def test_site_name_alone_opens_its_home():
    assert route("youtube") == "https://www.youtube.com/"


def test_everything_else_is_a_web_search():
    assert route("weather in Kolkata tomorrow") is None
    assert search_url("weather in Kolkata") == "https://www.google.com/search?q=weather+in+Kolkata"
    assert search_url("x", engine="bing") == "https://www.bing.com/search?q=x"


def test_site_names_inside_other_words_do_not_count():
    assert route("wikiHow guide to knots") is None
