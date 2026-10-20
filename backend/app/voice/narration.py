"""Short spoken updates sent to the Gemini Live narration session."""

import logging
import time

from google.genai import types

from app.steps.describe import action_in_plain_words

logger = logging.getLogger(__name__)

_last_narration_inject_time = 0.0

async def narrate_action(
    action_name: str,
    action_args: dict,
    last_action_time_ref: list | None,
    live_session_ref: list | None,
    grandparents_mode: bool = False,
):
    global _last_narration_inject_time

    # Always update action timestamp for cooldown tracking
    if last_action_time_ref is not None:
        last_action_time_ref[0] = time.time()

    # Don't narrate if Live session isn't open
    if live_session_ref is None or live_session_ref[0] is None:
        return

    # Rate limit — never inject narration faster than every 3 seconds
    # This prevents audio blur when the agent fires multiple actions quickly
    now = time.time()
    if now - _last_narration_inject_time < 3.0:
        return
    _last_narration_inject_time = now

    # Build plain English description — different phrasing per mode
    if action_name in ("type_text_at", "type"):
        text_typed = action_args.get("text", "")
        plain = f"typing: {text_typed}"
    elif action_name in ("navigate", "open_web_browser"):
        url = action_args.get("url", "a new page")
        plain = f"opening {url}"
    elif action_name in ("scroll_document", "scroll"):
        direction = action_args.get("direction", "down")
        plain = f"scrolling {direction}"
    elif action_name == "key_combination":
        keys = action_args.get("keys", "")
        plain = f"pressing {keys}"
    elif action_name in ("click_at", "left_click", "click"):
        plain = "clicking on something on the screen"
    else:
        plain = None

    # Normal mode: factual log-style. Grandparents mode: warm first-person.
    # The Live session system prompt shapes Gemini's spoken RESPONSE to this.
    if plain is None:
        # Page tools (tools/browser.py) have their own plain wording.
        described = action_in_plain_words(action_name, action_args)
        described = described[0].lower() + described[1:]
        msg = f"Next, I'll {described}." if grandparents_mode else f"Action: {described}"
    elif grandparents_mode:
        msg = f"I'm now {plain}."
    else:
        msg = f"Action: {plain}"

    try:
        await live_session_ref[0].send_client_content(
            turns=types.Content(parts=[types.Part(text=msg)])
        )
    except Exception as e:
        logger.debug(f"Live action narration skipped: {e}")
