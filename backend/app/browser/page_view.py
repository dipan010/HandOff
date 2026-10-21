"""Turning the extension's page map into short text, and comparing pages.

The page map (extension/page_map.js) lists what a person can see and use,
each item with a number. The model reads it as lines like:

    [4] text box "From station" = "Delhi"
    [7] checkbox "Student fare" (checked)
    [9] button "Search trains"
"""

import hashlib
import json
import re
from difflib import SequenceMatcher

PAGE_VIEW_HEADER = "PAGE VIEW"


def element_line(el: dict) -> str:
    line = f'[{el.get("id")}] {el.get("role", "item")} "{el.get("label", "")}"'
    if el.get("value"):
        line += f' = "{el["value"]}"'
    state = el.get("state") or []
    if state:
        line += f' ({", ".join(state)})'
    href = el.get("href")
    if href and el.get("role") == "link" and not href.startswith("javascript"):
        line += f" -> {href}"
    if el.get("frame"):
        line += f" (in a frame from {el['frame']})"
    return line


def page_view_text(page: dict | None, note: str = "") -> str:
    """The text the model sees each turn."""
    if not page:
        return f"{PAGE_VIEW_HEADER}\nThe page could not be read (it may still be loading).{(' ' + note) if note else ''}"
    lines = [
        PAGE_VIEW_HEADER,
        f"Address: {page.get('url', '')}",
        f"Title: {page.get('title', '')}",
    ]
    scroll = page.get("scroll") or {}
    if scroll.get("max"):
        lines.append(f"Scrolled {scroll.get('y', 0)} of {scroll.get('max')} pixels.")
    if page.get("dialog_open"):
        lines.append("A pop-up or dialog is open.")
    elements = page.get("elements") or []
    if elements:
        lines.append("What is on screen (use the numbers):")
        lines.extend(element_line(e) for e in elements)
    else:
        lines.append("No buttons, links or boxes are visible.")
    if page.get("hidden_below"):
        lines.append(f"(+{page['hidden_below']} more items further down: scroll to see them)")
    for host in page.get("payment_frames") or []:
        lines.append(f"A payment form from {host} is on this page. HandOff never fills it in: use ask_before so the user can.")
    for host in page.get("unreadable_frames") or []:
        lines.append(f"Part of this page (from {host}) can't be read. Use look_at_screen if you need it.")
    if note:
        lines.append(note)
    return "\n".join(lines)


def structure_hash(page: dict | None, scroll: bool = True) -> str:
    """Changes when the address, the items, their values or states change.

    Unlike a screenshot hash it ignores videos playing, animations and ads,
    so an action that did nothing really does look like nothing changed.
    With scroll=False, scrolling alone doesn't change it.
    """
    if not page:
        return ""
    shape = {
        "url": page.get("url"),
        "dialog": page.get("dialog_open"),
        "items": [(e.get("role"), e.get("label"), e.get("value"), tuple(e.get("state") or [])) for e in page.get("elements") or []],
        "scroll": (page.get("scroll") or {}).get("y") if scroll else None,
    }
    return hashlib.md5(json.dumps(shape, sort_keys=True, default=str).encode()).hexdigest()


def element_by_id(page: dict | None, element_id) -> dict | None:
    for el in (page or {}).get("elements") or []:
        if str(el.get("id")) == str(element_id):
            return el
    return None


_WORD = re.compile(r"[a-z0-9]+")


def _similarity(a: str, b: str) -> float:
    a, b = a.lower().strip(), b.lower().strip()
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.85
    words_a, words_b = set(_WORD.findall(a)), set(_WORD.findall(b))
    overlap = len(words_a & words_b) / max(1, len(words_a | words_b))
    return max(overlap, SequenceMatcher(None, a, b).ratio() * 0.8)


FIELD_ROLES = {"text box", "search box", "dropdown", "checkbox", "radio", "date box", "time box",
               "datetime-local box", "month box", "week box", "slider", "switch", "spinbutton"}


def find_field(page: dict | None, label: str, used: set | None = None) -> dict | None:
    """The form field whose label best matches `label` (for filling forms)."""
    used = used or set()
    best, best_score = None, 0.0
    for el in (page or {}).get("elements") or []:
        if el.get("role") not in FIELD_ROLES or el.get("id") in used or "disabled" in (el.get("state") or []):
            continue
        score = _similarity(label, el.get("label", ""))
        if score > best_score:
            best, best_score = el, score
    return best if best_score >= 0.5 else None


# What the extension saw change after a click or typing action, in plain words.
CHANGE_WORDS = [
    ("added", "{n} item{s} added"),
    ("removed", "{n} item{s} removed"),
    ("opened", "something opened"),
    ("closed", "something closed"),
    ("ticked", "{n} box{es} ticked"),
    ("unticked", "{n} box{es} unticked"),
    ("typed", "text typed"),
    ("chosen", "a choice made"),
    ("disabled", "{n} item{s} greyed out"),
    ("enabled", "{n} item{s} made usable"),
    ("text", "some text changed"),
]


def change_words(change: dict | None) -> str:
    if not change:
        return ""
    if change.get("left_page"):
        return "a new page started loading"
    words = []
    for key, phrase in CHANGE_WORDS:
        n = change.get(key) or 0
        if n:
            words.append(phrase.format(n=n, s="" if n == 1 else "s", es="" if n == 1 else "es"))
    return ", ".join(words)


# Cookie notices: HandOff closes them itself, saying no to cookies that aren't
# needed. If a notice offers no way to say no, it's left for the model. Only
# whole labels that are answers to a cookie question count, so "Reject request"
# or "Decline" elsewhere on a page is never clicked.
_COOKIE_WORDS = re.compile(r"\b(cookies?|consent)\b", re.I)
_REJECT_ALL = re.compile(r"(reject|decline|refuse) all( cookies)?", re.I)
_SAY_NO = re.compile(
    r"(reject|decline|refuse) all( cookies)?"
    r"|(i )?(do not|don.?t) accept( all)?( cookies)?"
    r"|(reject|decline|refuse)( non.?essential| optional| additional)? cookies"
    r"|only (necessary|essential)( cookies)?"
    r"|(use )?(necessary|essential)( cookies)? only"
    r"|continue without accepting", re.I)
_SAY_YES = re.compile(
    r"(i )?(accept|allow|agree)( to)?( all)?( cookies)?|accept (and|&) (continue|close)|allow all cookies", re.I)


def _answer(el: dict) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s']", " ", str(el.get("label") or ""))).strip()


def cookie_notice_button(page: dict | None) -> dict | None:
    """The button that says no on a cookie notice, or None if there isn't one."""
    buttons = [e for e in (page or {}).get("elements") or [] if e.get("role") in ("button", "link")]
    says_yes = any(_SAY_YES.fullmatch(_answer(e)) for e in buttons)
    found = [e for e in buttons if _SAY_NO.fullmatch(_answer(e))
             and (_COOKIE_WORDS.search(_answer(e)) or says_yes)]
    found.sort(key=lambda e: 0 if _REJECT_ALL.fullmatch(_answer(e)) else 1)
    return found[0] if found else None
