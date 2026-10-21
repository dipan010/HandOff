"""Fixed rules for when to search the web and when to go straight to a site.

- A web address ("wikipedia.org", "https://...") is opened as it is.
- A request that names a site we know ("lofi on youtube", "Alan Turing
  wikipedia") opens that site's own search page.
- Anything else goes to a web search, and the best result is opened.
- "Best" is decided by fixed rules (`rank_results`): results that match more
  of the words, and official, docs or help pages, go up; social sites, ads
  and links back to the search engine go down.
"""

import re
from dataclasses import dataclass
from urllib.parse import quote_plus, urlparse


@dataclass(frozen=True)
class Site:
    names: tuple[str, ...]   # words that mean this site in a request
    home: str
    search: str = ""         # address of its search page; {q} is the query


KNOWN_SITES = [
    Site(("youtube", "you tube"), "https://www.youtube.com/", "https://www.youtube.com/results?search_query={q}"),
    Site(("wikipedia", "wiki"), "https://en.wikipedia.org/", "https://en.wikipedia.org/w/index.php?search={q}"),
    Site(("google maps", "maps"), "https://www.google.com/maps", "https://www.google.com/maps/search/{q}"),
    Site(("gmail", "my email", "my inbox"), "https://mail.google.com/", "https://mail.google.com/mail/u/0/#search/{q}"),
    Site(("makemytrip", "make my trip"), "https://www.makemytrip.com/"),
    Site(("amazon",), "https://www.amazon.in/", "https://www.amazon.in/s?k={q}"),
    Site(("flipkart",), "https://www.flipkart.com/", "https://www.flipkart.com/search?q={q}"),
    Site(("irctc",), "https://www.irctc.co.in/nget/train-search"),
    Site(("google news",), "https://news.google.com/", "https://news.google.com/search?q={q}"),
]

SEARCH_ENGINES = {
    "google": "https://www.google.com/search?q={q}",
    "bing": "https://www.bing.com/search?q={q}",
    "duckduckgo": "https://duckduckgo.com/?q={q}",
}

# "example.com", "www.example.co.in/page", "https://..."
_ADDRESS = re.compile(r"^(https?://)?([a-z0-9-]+\.)+[a-z]{2,}(/\S*)?$", re.I)
# Little words left over once the site's name is taken out of a request.
_FILLER = re.compile(r"\b(on|in|at|from|search|find|look up|open|play|show me|go to)\b", re.I)


def as_address(text: str) -> str | None:
    """The text as a web address, if it is one."""
    text = text.strip()
    if " " in text or not _ADDRESS.match(text):
        return None
    return text if "://" in text else "https://" + text


def _mentions(text: str, name: str) -> bool:
    return re.search(rf"\b{re.escape(name)}\b", text, re.I) is not None


def find_site(text: str, site: str = "") -> Site | None:
    """The known site named in `site`, or else in the request itself."""
    for where in (site, text):
        if not where:
            continue
        for known in KNOWN_SITES:
            if any(_mentions(where, name) for name in known.names):
                return known
    return None


def _without_site(text: str, known: Site) -> str:
    for name in known.names:
        text = re.sub(rf"\b{re.escape(name)}\b", " ", text, flags=re.I)
    text = _FILLER.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip(" ,.-")


def route(query: str, site: str = "") -> str | None:
    """Where to go directly for this request, or None to search the web."""
    address = as_address(query) or as_address(site)
    if address:
        return address
    known = find_site(query, site)
    if not known:
        return None
    words = _without_site(query, known)
    if words and known.search:
        return known.search.format(q=quote_plus(words))
    return known.home


def search_url(query: str, engine: str = "google") -> str:
    template = SEARCH_ENGINES.get(engine.lower(), SEARCH_ENGINES["google"])
    return template.format(q=quote_plus(query.strip()))


# ── Picking the best result ────────────────────────────────────────────────

_SMALL_WORDS = {"a", "an", "the", "of", "for", "in", "on", "to", "and", "or", "how", "what", "is", "are",
                "find", "website", "site", "page", "web", "online", "me", "my", "with"}
SOCIAL_SITES = ("facebook.com", "instagram.com", "twitter.com", "x.com", "tiktok.com", "pinterest.com",
                "linkedin.com", "threads.net", "snapchat.com")
AD_LINK = re.compile(r"(googleadservices\.|doubleclick\.|/pagead/|/aclk\b|[?&]ad_?id=)", re.I)
# The search engine's own address, not its company's other sites (support.google.com is a help page).
SEARCH_SITES = re.compile(r"^(google\.[a-z.]+|bing\.com|duckduckgo\.com|search\.yahoo\.com|yandex\.[a-z]+)$", re.I)
HELP_HOST = re.compile(r"^(docs|help|support|developers?|learn)\.", re.I)
HELP_PATH = re.compile(r"/(docs?|documentation|help|support|faq|manual|guides?)(/|$)", re.I)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 1 and w not in _SMALL_WORDS}


def _on(host: str, sites: tuple[str, ...]) -> bool:
    return any(host == s or host.endswith("." + s) for s in sites)


def result_score(query: str, result: dict) -> int:
    url = str(result.get("url") or "")
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    wanted = _words(query)
    title = _words(result.get("title", ""))
    elsewhere = _words(f"{url} {result.get('snippet', '')}")
    score = sum(2 if w in title else 1 if w in elsewhere else 0 for w in wanted)
    # Official: says so, or the site's own name is one of the words ("turing.ac.uk").
    labels = host.split(".")[:-1]
    if "official" in title or any(len(w) >= 4 and w in label for w in wanted for label in labels):
        score += 2
    if HELP_HOST.match(host) or HELP_PATH.search(parsed.path):
        score += 2
    if _on(host, SOCIAL_SITES):
        score -= 4
    if AD_LINK.search(url):
        score -= 10
    elif SEARCH_SITES.search(host):
        score -= 3
    return score


def rank_results(query: str, results: list[dict]) -> list[dict]:
    """Search results best first. Equal results keep the search engine's order."""
    return sorted(results, key=lambda r: -result_score(query, r))
