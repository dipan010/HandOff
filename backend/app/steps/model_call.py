"""Calling Gemini: retries on busy errors, a backup model, and JSON answers.

Everything in steps/ talks to Gemini through a `Caller`, so tests can hand in
a fake one with canned replies.
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Protocol
from zoneinfo import ZoneInfo

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


# Gemini's daily limits reset at midnight Pacific time.
RESET_ZONE = ZoneInfo("America/Los_Angeles")


def next_daily_reset(now: datetime | None = None) -> datetime:
    local = (now or datetime.now(timezone.utc)).astimezone(RESET_ZONE)
    return (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


class UsedUpModels:
    """Models that have hit their daily limit, until the limit resets.

    Shared by every task in the running service, so a used-up model isn't
    asked again on every turn.
    """

    def __init__(self):
        self._until: dict[str, datetime] = {}

    def mark(self, model: str, now: datetime | None = None) -> None:
        self._until[model] = next_daily_reset(now)
        logger.warning(f"{model} has used up today's requests; skipping it until {self._until[model]:%H:%M %Z}")

    def is_used_up(self, model: str, now: datetime | None = None) -> bool:
        until = self._until.get(model)
        if until is None:
            return False
        if (now or datetime.now(timezone.utc)) >= until:
            del self._until[model]
            return False
        return True

    def all_used_up(self, models, now: datetime | None = None) -> bool:
        names = [m for m in models if m]
        return bool(names) and all(self.is_used_up(m, now) for m in names)

    def clear(self) -> None:
        self._until.clear()


used_up = UsedUpModels()


def reset_time_text(now: datetime | None = None) -> str:
    """When the daily limit resets, in the computer's own time, e.g. '12:30 PM'."""
    return next_daily_reset(now).astimezone().strftime("%I:%M %p").lstrip("0")


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


def used_up_message() -> str:
    return (f"I've used today's free Gemini requests. Try again after {reset_time_text()}, "
            "or add credit to the Gemini project (ai.studio/projects).")


def plain_error(err: Exception) -> str:
    """Turn a Gemini error into a sentence a user can understand."""
    if isinstance(err, DailyLimitReached) or is_daily_limit(err):
        return used_up_message()
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

    def __init__(self, api_key: str, retry_delays: tuple[float, ...] = RETRY_DELAYS,
                 on_wait: Callable[[float], Awaitable[None]] | None = None):
        self._client = genai.Client(api_key=api_key)
        self._retry_delays = retry_delays
        self.on_wait = on_wait   # told before each wait, so the user sees "Waiting a moment"

    async def ask(self, model: str, contents: Any, config: Any = None) -> Any:
        if used_up.is_used_up(model):
            raise DailyLimitReached(f"{model} has used up today's requests.")
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
                    used_up.mark(model)
                    raise DailyLimitReached(str(err)) from err
                if is_busy_error(err) and attempt < len(self._retry_delays):
                    asked = retry_delay_seconds(err)
                    delay = min(asked + 1, MAX_WAIT_FOR_LIMIT) if asked else self._retry_delays[attempt]
                    logger.warning(f"Gemini busy on {model}; retrying in {delay:.0f}s")
                    if self.on_wait is not None:
                        try:
                            await self.on_wait(delay)
                        except Exception:
                            pass
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
