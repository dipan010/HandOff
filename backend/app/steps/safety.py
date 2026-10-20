"""Stopping to ask the user before sign-ins, payments and other sensitive steps."""

import re
from urllib.parse import urlparse

from app.pause_gate import get_or_create as get_gate

# Whole sites where every page is about signing in or paying.
SENSITIVE_HOSTS = {"accounts.google.com", "login.microsoftonline.com", "appleid.apple.com", "paypal.com", "www.paypal.com"}

# Hosts that start with one of these words (login.example.com, pay.example.com ...).
SENSITIVE_HOST_STARTS = ("login.", "signin.", "auth.", "pay.", "checkout.", "payment.", "secure.")

# Address paths that mean a sign-in or payment page on any site.
SENSITIVE_PATH_PARTS = ("/login", "/signin", "/sign-in", "/sign_in", "/checkout", "/payment", "/ap/signin")


def is_login_wall(url: str) -> bool:
    """True for sign-in and payment pages, where the user should take over."""
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower()
    if host in SENSITIVE_HOSTS:
        return True
    if host.startswith(SENSITIVE_HOST_STARTS):
        return True
    return any(path == part or path.startswith(part + "/") or path.startswith(part + "?") or path.startswith(part + ".")
               for part in SENSITIVE_PATH_PARTS)


# Buttons whose click can't be taken back: sending, paying, booking, posting, deleting.
RISKY_LABEL = re.compile(
    r"\b(send|pay|payment|place (your )?order|buy( it)? now|purchase|checkout and pay|book( now)?|"
    r"confirm (and pay|booking|order|payment|purchase)|reserve|post|publish|tweet|delete|"
    r"remove permanently|transfer|donate)\b",
    re.I,
)
# Boxes where Enter sends what was typed.
MESSAGE_BOX = re.compile(r"\b(message|comment|reply|tweet|post|chat|write something|what's on your mind)\b", re.I)
CLICK_ROLES = {"button", "clickable", "menuitem", "link", "tab", "option"}


def _element(page: dict | None, element_id) -> dict | None:
    for el in (page or {}).get("elements") or []:
        if str(el.get("id")) == str(element_id):
            return el
    return None


def _is_navigation_link(el: dict) -> bool:
    href = (el.get("href") or "").strip().lower()
    return el.get("role") == "link" and bool(href) and not href.startswith(("#", "javascript"))


def risky_target(name: str, args: dict, page: dict | None) -> str | None:
    """What a click or Enter would send, pay, book, post or delete, if anything.

    Returns words for the question to the user, or None when the action is
    ordinary. Plain code, so it holds even if the model forgets to ask.
    """
    if name == "click":
        el = _element(page, args.get("element_id"))
        if not el or el.get("role") not in CLICK_ROLES or _is_navigation_link(el):
            return None
        label = el.get("label") or ""
        return f'click "{label}"' if RISKY_LABEL.search(label) else None
    if name in ("type_text", "press_key"):
        if name == "type_text":
            if not args.get("submit"):
                return None
            el = _element(page, args.get("element_id"))
        else:
            if str(args.get("key", "")).strip().lower() != "enter":
                return None
            el = next((e for e in (page or {}).get("elements") or [] if "focused" in (e.get("state") or [])), None)
        label = (el or {}).get("label") or ""
        return f'send what is typed in "{label}"' if MESSAGE_BOX.search(label) else None
    return None


def page_key(url: str) -> str:
    """Host and path, without query or fragment, so one page is asked about once."""
    try:
        parsed = urlparse(url)
        return f"{(parsed.hostname or '').lower()}{parsed.path or '/'}"
    except ValueError:
        return url


class SignInGuard:
    """Ask the user to take over on a sign-in or payment page, once per page.

    `check()` returns:
      "clear"   - not a sign-in page (or already approved): go ahead.
      "resumed" - the user just finished and clicked Continue: look at the
                  page again before acting, because it has probably changed.
      "stopped" - the user said no.
    """

    def __init__(self, session_id: str, ui):
        self.session_id = session_id
        self.ui = ui
        self.approved_pages: set[str] = set()

    async def check(self, url: str) -> str:
        if not is_login_wall(url):
            return "clear"
        key = page_key(url)
        if key in self.approved_pages:
            return "clear"
        approved, _ = await pause_and_wait(
            self.session_id, "login_wall",
            "This page is asking you to sign in or pay. Please do that yourself, then click Continue.",
            self.ui,
        )
        if not approved:
            return "stopped"
        self.approved_pages.add(key)
        return "resumed"


async def pause_and_wait(
    session_id: str,
    reason: str,
    prompt_text: str,
    ws_manager,
    needs_input: bool = False,
) -> tuple[bool, str | None]:
    """Pause, show the user a prompt, and wait for their answer."""
    gate = get_gate(session_id)
    gate.event.clear()
    gate.reason = reason

    # Tell frontend to show the pause prompt
    await ws_manager.send_pause_prompt(session_id, {
        "reason": reason,
        "prompt": prompt_text,
        "needs_input": needs_input,
    })

    # No timeout: wait as long as the person needs.
    await gate.event.wait()
    return gate.approved, gate.user_input
