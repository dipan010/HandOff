"""Stopping to ask the user before sign-ins, payments and other sensitive steps."""

from app.pause_gate import get_or_create as get_gate

from urllib.parse import urlparse

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
