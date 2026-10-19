"""Writes every action the assistant takes to a local log file."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_LOG_FILE = Path("actions.log")


async def log_action(
    session_id: str, step: int, action_name: str, action_args: dict[str, Any]
) -> str | None:
    """Append an action to the local actions log file.

    Returns a log entry id or None on failure.
    """
    try:
        entry = {
            "session_id": session_id,
            "step": step,
            "action": action_name,
            "args": action_args,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        with _LOG_FILE.open("a") as f:
            f.write(json.dumps(entry) + "\n")

        msg_id = f"local-{session_id}-{step}"
        logger.info(f"Action logged locally: {msg_id}")
        return msg_id
    except Exception as e:
        logger.error(f"Action log error: {e}")
        return None
