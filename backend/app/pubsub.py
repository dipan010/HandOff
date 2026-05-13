"""Local file logging for action audit trail (replaces Pub/Sub)."""

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_LOG_FILE = Path("actions.log")
_log_lock = threading.Lock()

# Fields whose values must never appear in logs (passwords, card numbers, etc.)
_SENSITIVE_KEYS = frozenset({
    "password", "passwd", "secret", "token", "credit_card", "card_number",
    "cvv", "pin", "ssn", "api_key", "private_key", "otp",
})


def _redact(args: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of args with sensitive values replaced by '[REDACTED]'."""
    redacted: dict[str, Any] = {}
    for k, v in args.items():
        if k.lower() in _SENSITIVE_KEYS:
            redacted[k] = "[REDACTED]"
        elif isinstance(v, str) and k.lower() == "text" and len(v) > 0:
            # Redact typed text that may contain passwords or card numbers
            redacted[k] = "[REDACTED]"
        else:
            redacted[k] = v
    return redacted


async def publish_action(
    session_id: str, step: int, action_name: str, action_args: dict[str, Any]
) -> str | None:
    """Append an action to the local actions log file.

    Returns a pseudo message-id or None on failure.
    """
    try:
        entry = {
            "session_id": session_id,
            "step": step,
            "action": action_name,
            "args": _redact(action_args),
            "timestamp": datetime.utcnow().isoformat(),
        }

        with _log_lock:
            with _LOG_FILE.open("a") as f:
                f.write(json.dumps(entry) + "\n")

        msg_id = f"local-{session_id}-{step}"
        logger.info(f"Action logged locally: {msg_id}")
        return msg_id
    except Exception as e:
        logger.error(f"Action log error: {e}")
        return None
