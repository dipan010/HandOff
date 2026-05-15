"""Input-validation and navigation-safety guardrails."""

import re
from urllib.parse import urlparse

# RFC-1918 / loopback — the agent must never navigate to these
_PRIVATE_HOST_RE = re.compile(
    r'^('
    r'localhost'
    r'|127(?:\.\d{1,3}){3}'
    r'|::1'
    r'|10(?:\.\d{1,3}){3}'
    r'|192\.168(?:\.\d{1,3}){2}'
    r'|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}'
    r')$',
    re.IGNORECASE,
)

# Subdomain prefixes that identify login / auth / payment subdomains
# e.g. login.example.com, pay.shop.com
_SENSITIVE_SUBDOMAIN_PREFIXES = (
    "login.", "signin.", "sign-in.", "auth.", "sso.",
    "pay.", "checkout.", "payment.", "billing.",
)

# Full hostnames that signal a login / payment page (subdomain-aware)
_SENSITIVE_HOSTS = frozenset({
    "accounts.google.com",
    "paypal.com",
    "facebook.com",
    "twitter.com",
    "x.com",
    "netflix.com",
    "amazon.com",
    "apple.com",
    "icloud.com",
    "microsoft.com",
    "live.com",
    "outlook.com",
})

# URL path prefixes that indicate login / auth / payment pages
_SENSITIVE_PATHS = (
    "/login", "/signin", "/sign-in",
    "/auth", "/oauth",
    "/pay", "/checkout", "/payment", "/billing",
)

# Hard limits
MAX_TASK_LENGTH = 4000      # chars — constrains prompt-injection surface
PAUSE_GATE_TIMEOUT = 300.0  # seconds — prevents resource leaks on abandoned sessions


def validate_url(url: str) -> str | None:
    """Return an error string if *url* is unsafe; ``None`` if it is acceptable."""
    if not url:
        return None
    try:
        parsed = urlparse(url)
    except Exception:
        return "Could not parse URL"
    if parsed.scheme not in ("http", "https"):
        return f"Unsafe URL scheme '{parsed.scheme}': only http and https are permitted"
    host = (parsed.hostname or "").lower()
    if _PRIVATE_HOST_RE.match(host):
        return f"Navigation to private/internal addresses is not allowed: {host}"
    return None


def is_navigation_allowed(
    url: str,
    blocked: list[str],
    allowed: list[str],
) -> tuple[bool, str]:
    """Check domain-policy rules (blocklist + optional allowlist).

    Returns ``(True, "")`` when navigation is permitted, or
    ``(False, reason)`` when it must be blocked.
    """
    if not url:
        return True, ""
    scheme_err = validate_url(url)
    if scheme_err:
        return False, scheme_err
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False, "Invalid URL"

    if any(host == d or host.endswith("." + d) for d in blocked):
        return False, f"Domain '{host}' is blocked by policy"

    if allowed and not any(host == d or host.endswith("." + d) for d in allowed):
        return False, f"Domain '{host}' is not in the permitted-domain list"

    return True, ""


def is_login_wall(url: str) -> bool:
    """Return ``True`` when *url* looks like a login or payment page.

    Uses exact hostname matching (including subdomains) rather than a plain
    substring search — ``notapaypal.com`` does *not* match ``paypal.com``.
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    if any(host == d or host.endswith("." + d) for d in _SENSITIVE_HOSTS):
        return True
    if any(host.startswith(p) for p in _SENSITIVE_SUBDOMAIN_PREFIXES):
        return True
    path = parsed.path.lower()
    return any(path.startswith(p) for p in _SENSITIVE_PATHS)


def validate_task(task: str) -> str | None:
    """Return an error string if *task* is invalid; ``None`` if acceptable."""
    if not task or not task.strip():
        return "Task text cannot be empty"
    if len(task) > MAX_TASK_LENGTH:
        return f"Task too long ({len(task)} chars). Maximum is {MAX_TASK_LENGTH}."
    return None
