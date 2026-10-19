"""Gemini Computer Use agent loop — the core of the project."""

import asyncio
import base64
import logging
import hashlib
import time

from google import genai
from google.genai import types

from app.config import get_settings
from app.browser.base import BrowserAdapter
from app.websocket import manager as ws_manager
from app.storage import upload_screenshot
from app.firestore_client import update_session_state
from app.action_log import log_action
from app.steps.finish import finish_task
from app.voice.narration import narrate_action

logger = logging.getLogger(__name__)
settings = get_settings()

from app.steps.safety import is_login_wall as _is_login_wall, pause_and_wait as _pause_and_wait
from app.steps.describe import action_in_plain_words as _action_to_plain_english

async def run_agent_loop(
    session_id: str,
    task: str,
    start_url: str,
    browser: BrowserAdapter,
    patience_mode: bool = False,
    grandparents_mode: bool = False,
    last_action_time_ref: list | None = None,
    completion_text_ref: list | None = None,
    live_session_ref: list | None = None,  # holds the live session so agent loop can push into it
):
    """Execute the Computer Use agent loop.

    1. Capture screenshot
    2. Send screenshot + task → Gemini Computer Use model
    3. Parse function_call actions
    4. Handle safety_decision (require_confirmation → ask user)
    5. Execute actions via Playwright or Live Extension
    6. Capture new screenshot
    7. Repeat until task complete or max turns reached
    """
    client = genai.Client(api_key=settings.GOOGLE_API_KEY)
    
    post_action_sleep = 2.0 if patience_mode else 0.5
    post_nav_sleep = 4.0 if patience_mode else 1.0

    # Configure Computer Use tool
    config = types.GenerateContentConfig(
        tools=[
            types.Tool(
                computer_use=types.ComputerUse(
                    environment=types.Environment.ENVIRONMENT_BROWSER
                )
            )
        ],
        system_instruction=(
            "You are a browser automation agent completing tasks step by step. "
            "Issue ONE action per response. Check action history before acting.\n\n"
            "COMPLETION RULES — output 'TASK COMPLETE: <summary>' when:\n"
            "- The user's actual goal has been accomplished (e.g., booking confirmed, form submitted, information found ON the destination website).\n"
            "- A destination site explicitly shows 'no results', 'not available', or 'no trains/flights found' — report that outcome.\n"
            "- A confirmation or success message is visible after a form submission.\n"
            "- DO NOT declare complete just because Google search results loaded. You must click through to the actual website and complete the task there.\n\n"
            "ACTION RULES:\n"
            "1. One action per response — never queue multiple actions.\n"
            "2. Action history is shown before each screenshot. Do NOT repeat any action already listed there.\n"
            "3. Use 'navigate' to go to a URL directly — never type URLs into search bars.\n"
            "4. For sensitive actions (passwords, payments) use 'require_confirmation'.\n"
            "5. Follow the user's exact wording for names, stations, cities, and dates. Never substitute with a different station or city.\n"
            "6. If a page is still loading or shows a spinner, wait (do nothing) and let the next screenshot confirm the state before acting.\n"
            "7. If a site shows no availability or 'no results', report TASK COMPLETE with what you found — do not keep searching endlessly.\n"
            "8. For scrolling: use 'scroll' with a 'coordinate' pointing at the element to scroll, 'direction' (up/down/left/right), and 'amount' in scroll clicks (1 click = 120 pixels). Always provide 'coordinate' so the correct scrollable element is targeted — not just the window. Example: scroll({coordinate: [500, 400], direction: 'down', amount: 3}) scrolls 360px downward at the element under coordinate (500, 400).\n"
            "9. For dropdown menus, city pickers, autocomplete lists: use 'select_option' with the exact visible text to select an item. Only scroll inside a dropdown if the desired option is not visible in the current viewport.\n"
            "10. Only use 'click_at' inside dropdowns if 'select_option' is not available or the items have no readable text labels."
        ),
    )

    # Navigate to start URL
    if start_url:
        await ws_manager.send_status(session_id, "navigating", f"Opening {start_url}", grandparents_mode)
        # The tab was already opened at start_url when the session launched.

    # Building optimization: tell the agent the browser is already open
    contents: list[types.Content] = [
        types.Content(
            role="user",
            parts=[types.Part(text=(
                f"Task: {task}\n\n"
                f"The browser is already open and ready. "
                f"{'You are on: ' + start_url if start_url else 'Begin immediately.'} "
                f"Do NOT call open_web_browser. Start the task directly."
            ))],
        )
    ]

    nudge_count = 0
    last_action_signature: str | None = None
    last_screenshot_hash_at_action: str | None = None
    last_action_finish_time: float = 0.0

    for turn in range(settings.MAX_AGENT_TURNS):
        logger.info(f"Agent turn {turn + 1}/{settings.MAX_AGENT_TURNS}")
        await ws_manager.send_status(
            session_id, "thinking", f"Step {turn + 1}: Analyzing screen...", grandparents_mode
        )

        # Capture screenshot — wait for a fresh one if we just performed an action
        screenshot_bytes = await browser.capture_screenshot(min_timestamp=last_action_finish_time)
        
        # If no screenshot is available yet (e.g. extension connecting), wait and retry
        if not screenshot_bytes:
            logger.warning("No screenshot available yet, waiting 1s...")
            await asyncio.sleep(1)
            continue
            
        screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")

        # Send screenshot to frontend
        await ws_manager.send_screenshot(session_id, screenshot_b64, turn + 1)

        # Upload to Cloud Storage (async, non-blocking)
        asyncio.create_task(
            upload_screenshot(session_id, turn + 1, screenshot_bytes)
        )

        # Add screenshot to conversation
        contents.append(
            types.Content(
                role="user",
                parts=[
                    types.Part(
                        inline_data=types.Blob(
                            mime_type="image/png",
                            data=screenshot_bytes,
                        )
                    )
                ],
            )
        )

        # Call Gemini Computer Use model (retry on 503/429 — temporary overload)
        response = None
        last_error = None
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=settings.COMPUTER_USE_MODEL,
                    contents=contents,
                    config=config,
                )
                last_error = None
                break
            except Exception as e:
                last_error = e
                err_str = str(e).upper()
                is_retryable = "503" in err_str or "UNAVAILABLE" in err_str or "429" in err_str or "RESOURCE_EXHAUSTED" in err_str
                if is_retryable and attempt < max_retries - 1:
                    delay = 2 ** (attempt + 1)  # 2, 4, 8 seconds
                    logger.warning(f"Gemini API overload ({e}). Retrying in {delay}s (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(delay)
                else:
                    break
        if last_error is not None:
            err_str = str(last_error).upper()
            if "503" in err_str or "UNAVAILABLE" in err_str:
                msg = "The AI service is busy. Please try again in a minute."
            elif "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                msg = "Too many requests. Please wait a moment and try again."
            else:
                msg = f"AI model error: {last_error}"
            logger.error(f"Gemini API error: {last_error}")
            await ws_manager.send_error(session_id, msg)
            break
        if response is None:
            break

        if not response or not response.candidates:
            logger.warning("Empty response from model")
            await ws_manager.send_error(session_id, "No response from AI model")
            break

        candidate = response.candidates[0]
        content = candidate.content
        if content is None or not getattr(content, "parts", None):
            logger.warning("Model returned candidate with no content or no parts (e.g. safety filter)")
            await ws_manager.send_error(session_id, "Model returned no actionable response (safety or empty). Try rephrasing.")
            break

        # Add model response to conversation history
        contents.append(content)

        # Check for text response (task complete or reasoning)
        text_parts = [p.text for p in content.parts if p.text]
        if text_parts:
            combined_text = " ".join(text_parts)
            logger.info(f"Model text: {combined_text[:200]}")

            if "TASK COMPLETE:" in combined_text.upper():
                summary = combined_text.split("TASK COMPLETE:")[-1].strip() if "TASK COMPLETE:" in combined_text else combined_text
                
                await finish_task(
                    session_id, summary, summary,
                    grandparents_mode=grandparents_mode,
                    live_session_ref=live_session_ref,
                    completion_text_ref=completion_text_ref,
                )
                return

            # Send reasoning/narration to frontend
            await ws_manager.send_narration(session_id, combined_text)

        # Check for function calls (actions)
        function_calls = [p.function_call for p in content.parts if p.function_call]

        if not function_calls:
            if text_parts:
                combined_lower = " ".join(text_parts).lower()
                completion_words = ["complete", "finished", "done", "successfully", "found", "loaded"]
                if any(w in combined_lower for w in completion_words):
                    summary = " ".join(text_parts)
                    await finish_task(
                        session_id, summary, summary,
                        grandparents_mode=grandparents_mode,
                        live_session_ref=live_session_ref,
                        completion_text_ref=completion_text_ref,
                    )
                    return
            
            nudge_count += 1
            if nudge_count >= 2:
                summary = "Task appears complete."
                await finish_task(
                    session_id, summary, "No-action stop",
                    grandparents_mode=grandparents_mode,
                    live_session_ref=live_session_ref,
                    completion_text_ref=completion_text_ref,
                )
                return
            
            contents.append(
                types.Content(
                    role="user",
                    parts=[types.Part(text="Next single action? If done, say 'TASK COMPLETE: <summary>'.")],
                )
            )
            continue

        nudge_count = 0

        current_sig = str([
            (fc.name, dict(fc.args) if fc.args else {})
            for fc in function_calls
        ])

        current_screenshot_hash = hashlib.md5(screenshot_bytes).hexdigest()

        if (current_sig == last_action_signature
                and current_screenshot_hash == last_screenshot_hash_at_action):
            logger.warning(f"Identical actions on turn {turn+1} with unchanged screen — stopping")
            summary = "Task complete — repeated action guard triggered."
            await finish_task(
                session_id, summary, "Dedup stop",
                grandparents_mode=grandparents_mode,
                live_session_ref=live_session_ref,
                completion_text_ref=completion_text_ref,
            )
            return
         
        last_action_signature = current_sig
        last_screenshot_hash_at_action = current_screenshot_hash

        # Execute each action
        for fc in function_calls:
            action_name = fc.name
            action_args = dict(fc.args) if fc.args else {}

            if action_name == 'require_confirmation':
                prompt = action_args.get('message', 'The agent wants to perform a sensitive action.')
                approved, _ = await _pause_and_wait(
                    session_id,
                    reason='confirmation',
                    prompt_text=prompt,
                    ws_manager=ws_manager,
                    needs_input=False,
                )
                if not approved:
                    await ws_manager.send_status(session_id, 'cancelled', 'User declined.', grandparents_mode)
                    return
                continue  # re-enter loop, Gemini will proceed
            
            # Auto-detect login walls from current URL
            current_url = await browser.get_current_url()
            if _is_login_wall(current_url):
                approved, typed_text = await _pause_and_wait(
                    session_id,
                    reason='login_wall',
                    prompt_text='The page is asking you to log in. Please sign in, then click Continue.',
                    ws_manager=ws_manager,
                    needs_input=False,
                )
                if not approved:
                    await ws_manager.send_status(session_id, 'cancelled', 'User cancelled at login wall.', grandparents_mode)
                    return
                # After user signals ready, take a fresh screenshot and continue
                await asyncio.sleep(1)
                continue

            plain_action = _action_to_plain_english(action_name, action_args)
            logger.info(f"Action: {action_name}({action_args}) -> {plain_action}")
            
            # Use Plain English if Grandparents Mode is on
            status_msg = plain_action if grandparents_mode else f"Executing: {action_name}"

            # 1. PREVIEW: show what we are ABOUT to do (Section 6.2)
            await ws_manager.send_action_preview(session_id, plain_action)
            await asyncio.sleep(0.8) # 800ms preview delay

            # 2. STATUS: show we are doing it now
            await ws_manager.send_status(
                session_id, "executing", status_msg, grandparents_mode
            )

            # Write to the local action log
            await log_action(session_id, turn + 1, action_name, action_args)

            # Execute the action
            result = await browser.execute_action(action_name, action_args)
            
            await narrate_action(
                action_name,
                action_args,
                last_action_time_ref,
                live_session_ref,
                grandparents_mode=grandparents_mode
            )

            # Send action result to frontend
            await ws_manager.send_action(session_id, result, turn + 1)

            # Update Firestore
            await update_session_state(
                session_id, "executing",
                f"Step {turn + 1}: {action_name}"
            )

            # Small delay between actions
            await asyncio.sleep(post_action_sleep)

        # Add action results as user message for next turn
        action_summary_lines = []
        for fc in function_calls:
            args = dict(fc.args) if fc.args else {}
            args_str = ", ".join(f"{k}={v}" for k, v in args.items())
            action_summary_lines.append(f"  - {fc.name}({args_str})")
         
        contents.append(types.Content(
            role="user",
            parts=[types.Part(text=(
                f"Turn {turn + 1} completed actions:\n"
                + "\n".join(action_summary_lines)
                + "\n\nUpdated screenshot attached. "
                + "If the task goal is now visibly achieved on screen, respond "
                + "'TASK COMPLETE: <summary>'. Otherwise, what is the ONE next action?"
            ))],
        ))

        # Brief wait for page to settle after actions
        await asyncio.sleep(post_nav_sleep)
        last_action_finish_time = time.time()

    # Max turns reached
    summary = f"Agent reached the maximum of {settings.MAX_AGENT_TURNS} steps. The task may be partially complete."
    await finish_task(
        session_id, summary, "Max turns reached",
        grandparents_mode=grandparents_mode,
        live_session_ref=live_session_ref,
        completion_text_ref=completion_text_ref,
    )
