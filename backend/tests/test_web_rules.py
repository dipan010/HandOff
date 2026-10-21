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


# ── Picking the best result (item 6, spec §7) ───────────────────────────────

from app.tools.web_rules import rank_results  # noqa: E402


def result(title, url, snippet=""):
    return {"title": title, "url": url, "snippet": snippet}


def urls(results):
    return [r["url"] for r in results]


def test_results_matching_more_of_the_words_come_first():
    ranked = rank_results("alan turing institute", [
        result("Alan Turing - Wikipedia", "https://en.wikipedia.org/wiki/Alan_Turing"),
        result("Alan Turing | Britannica", "https://www.britannica.com/biography/Alan-Turing"),
        result("The Alan Turing Institute", "https://www.turing.ac.uk/"),
    ])
    assert ranked[0]["url"] == "https://www.turing.ac.uk/"


def test_official_docs_and_help_pages_go_up_and_social_sites_go_down():
    ranked = rank_results("requests timeout", [
        result("Requests timeout tips", "https://www.facebook.com/groups/python/posts/1"),
        result("Requests timeout - a blog post", "https://someblog.example.com/requests-timeout"),
        result("Advanced Usage: Requests timeout", "https://docs.python-requests.org/en/latest/user/advanced/"),
    ])
    assert urls(ranked)[0] == "https://docs.python-requests.org/en/latest/user/advanced/"
    assert urls(ranked)[-1] == "https://www.facebook.com/groups/python/posts/1"
    ranked = rank_results("acme router setup", [
        result("Acme router setup guide", "https://forum.example.net/t/acme-router"),
        result("Acme router setup | Official Acme Support", "https://support.acme.com/router/setup"),
    ])
    assert urls(ranked)[0] == "https://support.acme.com/router/setup"


def test_ads_and_links_back_to_the_search_engine_go_last():
    ranked = rank_results("alan turing", [
        result("Alan Turing biography", "https://www.google.com/goto?url=CAESZAHrOzAV574Okl2f"),
        result("Alan Turing books - buy now", "https://www.googleadservices.com/pagead/aclk?sa=L&ai=x"),
        result("Alan Turing biography", "https://www.biography.com/scientists/alan-turing"),
    ])
    assert urls(ranked) == [
        "https://www.biography.com/scientists/alan-turing",
        "https://www.google.com/goto?url=CAESZAHrOzAV574Okl2f",
        "https://www.googleadservices.com/pagead/aclk?sa=L&ai=x",
    ]


def test_equal_results_keep_the_search_engines_order():
    results = [result("Lofi beats", "https://a.example.com/"), result("Lofi beats", "https://b.example.com/")]
    assert urls(rank_results("lofi beats", results)) == ["https://a.example.com/", "https://b.example.com/"]
    assert rank_results("x", []) == []


def test_a_site_named_after_the_words_counts_as_official():
    from app.tools.web_rules import result_score
    plain = result_score("acme router", result("Router", "https://shop.example.com/acme/router"))
    assert result_score("acme router", result("Router", "https://store.acme.com/router")) == plain + 2
    assert result_score("acme router", result("Router", "https://acme.co.uk/router")) == plain + 2


def test_a_search_companys_own_help_site_is_not_a_link_back_to_the_search():
    ranked = rank_results("change gmail password", [
        result("Change gmail password - a blog post", "https://someblog.example.com/change-gmail-password"),
        result("Change gmail password - Gmail Help", "https://support.google.com/mail/answer/41078"),
    ])
    assert urls(ranked)[0] == "https://support.google.com/mail/answer/41078"
