"""Checking that actions worked and that steps are really finished.

Two kinds of check:
- `changed()` is free: after an action, did the page address or the screen change,
  and did the extension report success?
- `is_step_done()` asks a model to compare the screen with the step's
  "done when" description. `page_text` will carry the page map once the
  extension can send one; until then only the screenshot and address are used.
"""

import hashlib
import logging
import re
from dataclasses import dataclass
from urllib.parse import unquote_plus, urlparse

from google.genai import types

from app.steps.model_call import Caller, ask_json
from app.steps.plan import Step
from app.tools.web_rules import KNOWN_SITES

logger = logging.getLogger(__name__)


@dataclass
class ScreenState:
    url: str
    screen_hash: str
    page_hash: str = ""   # from the page map; ignores videos and animations

    @classmethod
    def of(cls, url: str, screenshot: bytes | None, page_hash: str = "") -> "ScreenState":
        return cls(url=url or "", screen_hash=hashlib.md5(screenshot or b"").hexdigest(), page_hash=page_hash)


@dataclass
class CheckResult:
    ok: bool
    reason: str


# Actions that don't need to change the screen to count as working.
NO_VISIBLE_CHANGE_OK = {"wait_5_seconds", "hover_at", "get_current_url"}


def changed(before: ScreenState, after: ScreenState, action_results: list[dict], action_names: list[str]) -> CheckResult:
    """Did the last batch of actions do anything?"""
    failed = [r for r in action_results if isinstance(r, dict) and r.get("success") is False]
    if failed:
        detail = failed[0].get("detail") or failed[0].get("error") or "no detail"
        return CheckResult(False, f"The browser reported that '{failed[0].get('action', 'the action')}' failed: {detail}.")
    if before.url != after.url:
        return CheckResult(True, f"The page changed to {after.url}.")
    if before.page_hash and after.page_hash:
        # Compare what's on the page, not pixels: a playing video changes every frame.
        if before.page_hash != after.page_hash:
            return CheckResult(True, "The page changed.")
    elif before.screen_hash != after.screen_hash:
        return CheckResult(True, "The screen changed.")
    if action_names and all(n in NO_VISIBLE_CHANGE_OK for n in action_names):
        return CheckResult(True, "Nothing needed to change.")
    return CheckResult(False, "Nothing on the screen changed after that action.")


# ── Plain-code checks ───────────────────────────────────────────────────────
# Tried before the check model. Each rule answers only when the page proves it
# one way or the other; anything unclear returns None and the model decides.

NOT_FOUND = re.compile(r"\b(404|page not found|not found|can.t be reached|access denied)\b", re.I)
# Steps whose result is information: the address alone never proves them.
NEEDS_ANSWER = re.compile(r"\b(read|find|found|compare|price|prices|cost|how (many|much)|who|what|when|where|which|"
                          r"answer|list|names?|details?|report|summar\w*|check|tell)\b", re.I)
PLAYING = re.compile(r"\b(play|plays|playing)\b", re.I)
OPEN_ONLY = re.compile(r"\b(home ?page|homepage|main page|site is open|website is open)\b", re.I)
RESULTS = re.compile(r"\b(search|results?)\b", re.I)
QUOTED = re.compile(r"[\"'‘“]([^\"'’”]{2,80})[\"'’”]")
# Facts in an answer: amounts and numbers, times, and names of two or more capitalised words.
NUMBER = re.compile(r"[₹$€£]?\d[\d,.:]*")
NAME = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b")


def _root(host: str) -> str:
    return ".".join(host.lower().removeprefix("www.").split(".")[-2:])


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower().replace(",", ""))


def answer_facts(summary: str) -> list[str]:
    facts = [n.strip(".,:") for n in NUMBER.findall(summary or "") if any(c.isdigit() for c in n)]
    facts += NAME.findall(summary or "")
    return [f for f in facts if f]


def quick_check(step: Step, url: str, page: dict | None, page_text: str, summary: str,
                ends_task: bool = False) -> CheckResult | None:
    """A confident answer from the page itself, or None to ask the model."""
    wording = f"{step.title} {step.done_when}"
    title = (page or {}).get("title") or ""
    if NOT_FOUND.search(title):
        return CheckResult(False, f'The page says "{title}".')

    # Only judge the site when the step names exactly one known site.
    named = [k for k in KNOWN_SITES if any(re.search(rf"\b{re.escape(n)}\b", wording, re.I) for n in k.names)]
    site = named[0] if len(named) == 1 else None
    host = urlparse(url or "").hostname or ""
    if site and host and _root(host) != _root(urlparse(site.home).hostname or ""):
        return CheckResult(False, f"The browser is on {host}, not {site.names[0].title()}.")

    if PLAYING.search(step.done_when) and any(
            (e.get("role") == "button" and (e.get("label") or "").lower().startswith("pause"))
            for e in (page or {}).get("elements") or []):
        return CheckResult(True, "A video is playing (there is a Pause button).")

    if ends_task or NEEDS_ANSWER.search(wording):
        facts = answer_facts(summary)
        found_in = _norm(page_text) + " " + _norm(unquote_plus(url or ""))
        if facts and all(_norm(f) in found_in for f in facts):
            return CheckResult(True, "Everything in the answer is on the page.")
        return None

    if site and host:
        terms = [t.strip() for t in QUOTED.findall(wording) if t.strip()]
        where = _norm(unquote_plus(url)) + " " + _norm(page_text)
        if terms and all(_norm(t) in where for t in terms):
            return CheckResult(True, f"The page is on {host} and shows {', '.join(terms)}.")
        if not terms and OPEN_ONLY.search(step.done_when) and not RESULTS.search(step.done_when):
            return CheckResult(True, f"{host} is open.")
    return None


CHECK_PROMPT = """You check the work of HandOff, a helper that operates a web browser.

The user's task: "{task}"
Current step: "{title}"
The step is finished when: "{done_when}"
Current page address: {url}
{page_text}
Look at the page (and the screenshot, if there is one). Is the step finished?

Answer with JSON only:
{{"done": true | false, "reason": "one short sentence about what you see"}}

Say true only if the screen clearly shows the "finished when" condition.
If the page shows that the thing cannot be done (no results, sold out, not available), say true and explain that in the reason."""


async def is_step_done(
    task: str,
    step: Step,
    screenshot: bytes | None,
    url: str,
    caller: Caller,
    model: str,
    backup: str | None,
    page_text: str | None = None,
) -> CheckResult:
    prompt = CHECK_PROMPT.format(
        task=task, title=step.title, done_when=step.done_when, url=url or "unknown",
        page_text=f"Text on the page:\n{page_text[:4000]}\n" if page_text else "",
    )
    parts = [types.Part(text=prompt)]
    if screenshot:
        parts.append(types.Part(inline_data=types.Blob(mime_type="image/png", data=screenshot)))
    contents = [types.Content(role="user", parts=parts)]
    try:
        answer = await ask_json(caller, model, backup, contents)
    except Exception as err:
        # If the check itself fails, trust the action model rather than looping forever.
        logger.warning(f"Step check failed, accepting the step: {err}")
        return CheckResult(True, "Could not double-check this step.")
    done = bool(answer.get("done")) if isinstance(answer, dict) else False
    reason = str(answer.get("reason", "")).strip() if isinstance(answer, dict) else ""
    return CheckResult(done, reason or ("Looks finished." if done else "Not finished yet."))
