"""Wrapping up a task: speak the result, tell the UI and the extension, save state."""

import asyncio
import logging

from google.genai import types

from app.firestore_client import update_session_state
from app.websocket import manager as default_ui

logger = logging.getLogger(__name__)

# Time for the narration voice to finish speaking before the session closes.
SPEAK_WAIT_SECONDS = 4.0


async def finish_task(
    session_id: str,
    summary: str,
    state_note: str,
    *,
    grandparents_mode: bool = False,
    live_session_ref: list | None = None,
    completion_text_ref: list | None = None,
    ui=default_ui,
    speak_wait: float = SPEAK_WAIT_SECONDS,
) -> None:
    """End a task the same way every time, whatever the reason it ended."""
    if live_session_ref is not None and live_session_ref[0] is not None:
        spoken = f"All done! {summary}" if grandparents_mode else f"Task complete. {summary}"
        try:
            await live_session_ref[0].send_client_content(
                turns=types.Content(parts=[types.Part(text=spoken)])
            )
        except Exception:
            pass

    # Lets the narration loop in live_stream.py stop cleanly.
    if completion_text_ref is not None:
        completion_text_ref[0] = summary

    await asyncio.sleep(speak_wait)

    await ui.send_task_complete(session_id, summary)
    await update_session_state(session_id, "completed", state_note)
    await ui.broadcast_to_extension(session_id, {
        "type": "UDAA_STATUS",
        "payload": {"status": "completed", "message": "Task done."},
    })
    logger.info(f"Task finished ({state_note[:60]}): {summary[:100]}")
