"""Fixed rules for when to search the web and when to go straight to a site.

- A web address ("wikipedia.org", "https://...") is opened as it is.
- A request that names a site we know ("lofi on youtube", "Alan Turing
  wikipedia") opens that site's own search page.
- Anything else goes to a web search, and the best result is opened.
"""

import re
from dataclasses import dataclass
from urllib.parse import quote_plus


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
