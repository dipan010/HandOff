"""Decide what kind of request this is before doing any work.

- "chat": greetings, thanks and questions HandOff can answer without touching
  the screen. These get an answer straight away.
- "task": anything that needs the browser. Tasks are "quick" (one or two
  obvious actions) or "hard" (several parts, forms, comparisons, unclear wording).
"""

import logging
import re
from dataclasses import dataclass

from app.steps.model_call import Caller, ask_json

logger = logging.getLogger(__name__)


@dataclass
class Sorted:
    kind: str            # "chat" or "task"
    effort: str          # "quick" or "hard"
    reply: str | None = None


_GREETING = re.compile(
    r"^\s*(hi|hello|hey|hiya|good (morning|afternoon|evening)|thanks|thank you|thank u|cheers|ok(ay)?|cool|great)"
    r"( there)?( handoff)?[\s!.,?]*$",
    re.IGNORECASE,
)

_GREETING_REPLIES = {
    "thanks": "You're welcome! Anything else I can do?",
    "default": "Hello! Tell me what you'd like to do and I'll take care of it.",
}

SORT_PROMPT = """You sort requests for HandOff, a helper that operates a web browser for people who find computers hard to use.

Request: "{task}"
Start page given by the user: "{start_url}"

Answer with JSON only:
{{"kind": "chat" | "task", "effort": "quick" | "hard", "reply": string | null}}

Rules:
- "chat" only if the request can be fully answered in words with no website: greetings, small talk, general knowledge, arithmetic. Put a short, friendly answer (max 2 sentences) in "reply".
- Anything that mentions a website, searching, booking, buying, playing, opening, reading a page, or uses the start page is a "task" with "reply": null.
- "quick": one or two obvious actions (open a site, play a video, one search).
- "hard": several parts, forms, dates, comparisons, logins or unclear wording.
- If unsure, choose "task" and "hard"."""


def quick_rule(task: str) -> Sorted | None:
    """Handle obvious greetings and thanks without calling a model."""
    match = _GREETING.match(task or "")
    if not match:
        return None
    word = match.group(1).lower()
    key = "thanks" if word.startswith("thank") or word == "cheers" else "default"
    return Sorted(kind="chat", effort="quick", reply=_GREETING_REPLIES[key])


async def sort_request(task: str, start_url: str, caller: Caller, model: str, backup: str | None) -> Sorted:
    rule = quick_rule(task)
    if rule:
        return rule

    try:
        answer = await ask_json(caller, model, backup, SORT_PROMPT.format(task=task, start_url=start_url or "none"))
    except Exception as err:
        logger.warning(f"Sorting failed, treating as a hard task: {err}")
        return Sorted(kind="task", effort="hard")

    kind = answer.get("kind") if isinstance(answer, dict) else None
    effort = answer.get("effort") if isinstance(answer, dict) else None
    reply = answer.get("reply") if isinstance(answer, dict) else None

    # A start page always means the user wants the browser used.
    if kind == "chat" and reply and not start_url:
        return Sorted(kind="chat", effort="quick", reply=str(reply).strip())
    return Sorted(kind="task", effort=effort if effort in ("quick", "hard") else "hard")
