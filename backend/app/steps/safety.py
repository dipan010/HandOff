"""Stopping to ask the user before sign-ins, payments and other sensitive steps."""

from app.pause_gate import get_or_create as get_gate

SENSITIVE_DOMAINS = [
    "accounts.google.com", "login.", "signin.", "auth.",
    "paypal.com", "pay.", "checkout.", "payment.",
    "facebook.com/login", "twitter.com/login", "netflix.com/login",
]

def is_login_wall(url: str) -> bool:
    if not url: return False
    return any(d in url for d in SENSITIVE_DOMAINS)

async def pause_and_wait(
    session_id: str,
    reason: str,
    prompt_text: str,
    ws_manager,
    needs_input: bool = False,
) -> tuple[bool, str | None]:
    """Pause, show the user a prompt, and wait for their answer."""
    gate = get_gate(session_id)
    gate.event.clear()
    gate.reason = reason

    # Tell frontend to show the pause prompt
    await ws_manager.send_pause_prompt(session_id, {
        "reason": reason,
        "prompt": prompt_text,
        "needs_input": needs_input,
    })

    # No timeout: wait as long as the person needs.
    await gate.event.wait()
    return gate.approved, gate.user_input
