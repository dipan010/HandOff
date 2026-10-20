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
from dataclasses import dataclass

from google.genai import types

from app.steps.model_call import Caller, ask_json
from app.steps.plan import Step

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
