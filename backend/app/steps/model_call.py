"""Calling Gemini: retries on busy errors, a backup model, and JSON answers.

Everything in steps/ talks to Gemini through a `Caller`, so tests can hand in
a fake one with canned replies.
"""

import asyncio
import json
import logging
import re
from typing import Any, Protocol

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

BUSY_MARKERS = ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED")
RETRY_DELAYS = (2, 4)  # seconds; two retries after the first try
MAX_WAIT_FOR_LIMIT = 60  # seconds: wait out a per-minute limit, but not a daily one

_RETRY_DELAY = re.compile(r"retryDelay['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)s")


def retry_delay_seconds(err: Exception) -> float | None:
    """The wait Gemini asks for in a 429 error, if it gives one."""
    match = _RETRY_DELAY.search(str(err))
    return float(match.group(1)) if match else None


def is_daily_limit(err: Exception) -> bool:
    text = str(err)
    if "PerDay" in text:
        return True
    delay = retry_delay_seconds(err)
    return delay is not None and delay > MAX_WAIT_FOR_LIMIT


class DailyLimitReached(RuntimeError):
    """Raised instead of waiting hours for a daily free-tier limit to reset."""


class Caller(Protocol):
    async def ask(self, model: str, contents: Any, config: Any = None) -> Any:
        """Return the raw Gemini response for `contents`."""


def is_account_problem(err: Exception) -> bool:
    """No credit, bad key or API switched off: retrying or another model won't help."""
    text = str(err).upper()
    return ("402" in text or "PREPAYMENT" in text or "PERMISSION_DENIED" in text
            or "API_KEY_INVALID" in text or "SERVICE_DISABLED" in text)


def is_busy_error(err: Exception) -> bool:
    if is_account_problem(err):
        return False
    text = str(err).upper()
    return any(m in text for m in BUSY_MARKERS)


def plain_error(err: Exception) -> str:
    """Turn a Gemini error into a sentence a user can understand."""
    if isinstance(err, DailyLimitReached) or is_daily_limit(err):
        return "Today's free Gemini limit is used up. Try again tomorrow, or add credit to the Google Cloud project."
    text = str(err).upper()
    if "402" in text or "PREPAYMENT" in text:
        return "The Gemini account has no credit left. Add prepaid credit in AI Studio (ai.studio/projects)."
    if "503" in text or "UNAVAILABLE" in text:
        return "The Gemini service is busy. Please try again in a minute."
    if "429" in text or "RESOURCE_EXHAUSTED" in text:
        return "Too many requests. Please wait a moment and try again."
    if "PERMISSION_DENIED" in text or "403" in text:
        return "Gemini refused the request. Check that the API key is valid and the Gemini API is enabled for its project."
    return f"Gemini error: {err}"


class GeminiCaller:
    """The real thing: google-genai with retries on temporary overload."""

    def __init__(self, api_key: str, retry_delays: tuple[float, ...] = RETRY_DELAYS):
        self._client = genai.Client(api_key=api_key)
        self._retry_delays = retry_delays

    async def ask(self, model: str, contents: Any, config: Any = None) -> Any:
        for attempt in range(len(self._retry_delays) + 1):
            try:
                return await asyncio.to_thread(
                    self._client.models.generate_content,
                    model=model,
                    contents=contents,
                    config=config,
                )
            except Exception as err:
                if is_busy_error(err) and is_daily_limit(err):
                    raise DailyLimitReached(str(err)) from err
                if is_busy_error(err) and attempt < len(self._retry_delays):
                    asked = retry_delay_seconds(err)
                    delay = min(asked + 1, MAX_WAIT_FOR_LIMIT) if asked else self._retry_delays[attempt]
                    logger.warning(f"Gemini busy on {model}; retrying in {delay:.0f}s")
                    await asyncio.sleep(delay)
                    continue
                raise


async def ask_with_backup(caller: Caller, model: str, backup: str | None, contents: Any, config: Any = None) -> Any:
    """Try `model`; if it fails for any reason, try `backup` once."""
    try:
        return await caller.ask(model, contents, config)
    except Exception as err:
        if not backup or backup == model or is_account_problem(err):
            raise
        logger.warning(f"{model} failed ({err}); using backup model {backup}")
        return await caller.ask(backup, contents, config)


def response_text(response: Any) -> str:
    """All text parts of the first candidate, joined."""
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text
    try:
        parts = response.candidates[0].content.parts
    except (AttributeError, IndexError, TypeError):
        return ""
    return " ".join(p.text for p in parts if getattr(p, "text", None))


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_json(text: str) -> Any:
    """Parse JSON from a model answer, tolerating ```json fences and stray prose."""
    cleaned = _FENCE.sub("", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Fall back to the first {...} or [...] block in the text.
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start, end = cleaned.find(open_ch), cleaned.rfind(close_ch)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError(f"No JSON found in: {text[:200]}")


async def ask_json(caller: Caller, model: str, backup: str | None, contents: Any) -> Any:
    """Ask for a JSON answer and return it parsed."""
    config = types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2)
    response = await ask_with_backup(caller, model, backup, contents, config)
    return parse_json(response_text(response))
