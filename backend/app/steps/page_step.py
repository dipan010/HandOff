"""Doing one step by reading the page, not by looking at pixels.

Each turn the model gets a PAGE VIEW: the page address and a numbered list of
what is on screen (from the extension's page map). It answers with tool calls
that use those numbers ("click 12", "type 'Delhi' into 4"). A screenshot is
added only when the page view isn't enough: very few items, the model asked
for one, or the last two tries failed.

Any model that supports tool calls works here; the Computer Use model is not
needed.
"""

import asyncio
import logging
import time

from google.genai import types

from app.action_log import log_action
from app.browser.page_view import PAGE_VIEW_HEADER, page_view_text, structure_hash
from app.firestore_client import update_session_state
from app.steps.check import ScreenState, changed, is_step_done
from app.steps.describe import action_in_plain_words
from app.steps.model_call import ask_with_backup, plain_error
from app.steps.plan import Step
from app.steps.safety import pause_and_wait, risky_target
from app.tools.browser import ALL_TOOLS, LOOK_ONLY, BrowserTools, ToolResult, declarations, tools_for_step
from app.voice.narration import narrate_action

logger = logging.getLogger(__name__)

PAGE_RULES = (
    "You operate a web browser for a person who finds computers hard to use. "
    "You work on ONE step of a larger plan at a time.\n\n"
    "Every turn you get a PAGE VIEW: the address and a numbered list of what is on screen, e.g. "
    "[12] button \"Search\". Act with the tools, using those numbers.\n\n"
    "RULES:\n"
    "1. Only use numbers that are in the latest page view. Numbers can change after the page changes.\n"
    "2. If what you need isn't listed, scroll, or use read_page to read the page's text. "
    "To compare prices, products, listings or times, use pull_list if it is offered.\n"
    "3. Use look_at_screen only when the page view can't show it (pictures, maps, charts). "
    "click_at is only for things that have no number.\n"
    "4. Before paying, booking, sending a message, posting, deleting or sharing personal details, use ask_before.\n"
    "5. Keep the user's exact names, places and dates. To fill two or more boxes of a form, use fill_form if it is offered.\n"
    "6. To find something, use search_web if it is offered: it goes to the right site or searches the web and opens the best result. "
    "Use open_page only for an address you already know. Don't type addresses or searches into a search engine yourself.\n"
    "7. When the current step is finished, call step_done with what shows it.\n"
    "8. When the user's whole task is finished, call task_complete. If they asked a question, the summary must contain the answer.\n"
    "9. If the site clearly shows 'no results', 'sold out' or 'not available', call task_complete and say so.\n"
    "10. Never type passwords or card numbers (HandOff refuses boxes marked for them). If a page needs them, use ask_before so the user can do it.\n"
    "11. Search results alone don't finish a task: open the right result and do it there."
)

LAST_STEP = (
    "This is the LAST step. When it is finished, call task_complete (not step_done) with a summary for the user; "
    "if they asked a question, include the answer."
)

KEEP_PAGE_VIEWS = 2
MAX_READ_RESULT = 6000


def trim_page_views(contents: list, keep: int = KEEP_PAGE_VIEWS) -> list:
    """Keep only the newest page views in the history; older ones become a note."""
    seen = 0
    out = []
    for content in reversed(contents):
        parts = list(getattr(content, "parts", None) or [])
        changed_any = False
        for i, part in enumerate(parts):
            text = getattr(part, "text", None)
            if text and text.startswith(PAGE_VIEW_HEADER):
                seen += 1
                if seen > keep:
                    parts[i] = types.Part(text="[older page view removed]")
                    changed_any = True
        if changed_any:
            content = types.Content(role=content.role, parts=parts)
        out.append(content)
    return list(reversed(out))


def trim_images(contents: list, keep: int) -> list:
    seen = 0
    out = []
    for content in reversed(contents):
        parts = list(getattr(content, "parts", None) or [])
        changed_any = False
        for i, part in enumerate(parts):
            if getattr(part, "inline_data", None):
                seen += 1
                if seen > keep:
                    parts[i] = types.Part(text="[older screenshot removed]")
                    changed_any = True
        if changed_any:
            content = types.Content(role=content.role, parts=parts)
        out.append(content)
    return list(reversed(out))


def _response(name: str, ok: bool, message: str) -> types.Part:
    return types.Part.from_function_response(name=name, response={"ok": ok, "result": message})


def opening_text(run, step: Step, plan: list[Step]) -> str:
    plan_text = "\n".join(f"{s.number}. {s.title}" for s in plan)
    recent = "\n".join(run.history[-15:]) or "(nothing yet)"
    start = f"The browser started on: {run.start_url}\n" if run.start_url else ""
    last = (LAST_STEP + "\n\n") if step is plan[-1] else ""
    return (
        f"The user's task: {run.task}\n{start}\n"
        f"Plan:\n{plan_text}\n\n"
        f"Actions so far:\n{recent}\n\n"
        f"Work on step {step.number} now: {step.title}\n"
        f"This step is finished when: {step.done_when}\n\n"
        f"{last}"
        "The browser is already open."
    )


async def do_step_by_page(run, step: Step, plan: list[Step]):
    """Same contract as TaskRun.do_step: returns a StepOutcome."""
    from app.steps.run import StepOutcome  # avoid a circular import

    cfg = run.cfg
    tools = BrowserTools(run.browser, cfg.SEARCH_ENGINE)
    def config_with(names: list[str]) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            system_instruction=PAGE_RULES,
            tools=[types.Tool(function_declarations=declarations(names))],
            tool_config=types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode="ANY")),
            temperature=0.2,
        )

    # Start with the tools that fit this step; once a try fails, offer them all.
    config = config_with(tools_for_step(f"{step.title} {step.done_when}"))
    all_offered = False
    contents: list = [types.Content(role="user", parts=[types.Part(text=opening_text(run, step, plan))])]
    pending: list[types.Part] = []           # tool answers to send with the next page view
    failures, step_actions, unreadable = 0, 0, 0
    last_failure = ""
    want_screenshot = False
    waiting_for_summary = False
    before: ScreenState | None = None         # page state before the last batch of actions
    last_names: list[str] = []
    last_results: list[dict] = []
    is_last = step is plan[-1]
    approved_next = False                    # the user just said yes to an ask_before

    while True:
        if run.actions_used >= cfg.MAX_AGENT_TURNS:
            return StepOutcome("out_of_actions")
        if failures >= cfg.MAX_STEP_RETRIES:
            return StepOutcome("stuck", last_failure or "This step kept failing.")
        if step_actions >= cfg.MAX_STEP_ACTIONS:
            return StepOutcome("stuck", f"Used {step_actions} actions on this step without finishing it.")

        await run.status("thinking", f"Step {step.number}: {step.title}")

        page = await tools.page_map()
        tools.last_page = page
        shot = await run.screenshot()
        if shot:
            await run.show_and_save(shot)
        url = (page or {}).get("url") or await run.url()
        notes = []

        # Did the last batch of actions change anything?
        if before is not None:
            effect = changed(before, ScreenState.of(url, shot, structure_hash(page)), last_results, last_names)
            before = None
            if not effect.ok:
                failures += 1
                last_failure = effect.reason
                await run.ui.send_step_update(run.session_id, step.number, "retrying", effect.reason)
                notes.append(f"Result of your last actions: {effect.reason} Try a different way.")

        if page is None:
            unreadable += 1
            if unreadable > 5:
                return StepOutcome("error", "HandOff can't read this page. Is the HandOff extension installed and on?")
            want_screenshot = True
        else:
            unreadable = 0

        few_items = page is not None and len(page.get("elements") or []) < 3
        add_shot = bool(shot) and (want_screenshot or page is None or few_items or failures >= 2)
        want_screenshot = False

        parts = pending + [types.Part(text=page_view_text(page, " ".join(notes)))]
        if add_shot:
            parts.append(types.Part(inline_data=types.Blob(mime_type="image/png", data=shot)))
        pending = []
        contents.append(types.Content(role="user", parts=parts))
        contents = trim_images(trim_page_views(contents), cfg.KEEP_SCREENSHOTS)

        if failures and not all_offered:
            config, all_offered = config_with(ALL_TOOLS), True

        try:
            response = await ask_with_backup(run.caller, run.action_model, cfg.BACKUP_MODEL, contents, config)
        except Exception as err:
            logger.error(f"Action model error: {err}")
            return StepOutcome("error", plain_error(err))

        candidate = response.candidates[0] if response and getattr(response, "candidates", None) else None
        content = candidate.content if candidate else None
        if content is None or not getattr(content, "parts", None):
            failures += 1
            last_failure = "Gemini gave no answer."
            continue
        contents.append(content)

        calls = [p.function_call for p in content.parts if getattr(p, "function_call", None)]
        text = " ".join(p.text for p in content.parts if getattr(p, "text", None) and not getattr(p, "thought", False))
        if text:
            await run.ui.send_narration(run.session_id, text)
        if not calls:
            failures += 1
            last_failure = "Gemini answered without choosing an action."
            pending.append(types.Part(text="Please answer with a tool call."))
            continue

        page_before = ScreenState.of(url, shot, structure_hash(page))
        names, results = [], []
        outcome = None

        for index, call in enumerate(calls):
            name = call.name
            args = dict(call.args) if call.args else {}

            if outcome is not None or (results and results[-1].get("success") is False):
                pending.append(_response(name, False, "Skipped because an earlier action in this turn didn't work."))
                continue

            if name == "ask_before":
                question = str(args.get("question") or "HandOff wants to do something sensitive. Go ahead?")
                approved, _ = await pause_and_wait(run.session_id, "confirmation", question, run.ui)
                if not approved:
                    pending.append(_response(name, False, "The user said no."))
                    await run.status("cancelled", "You said no, so I stopped.")
                    outcome = StepOutcome("stopped")
                    continue
                pending.append(_response(name, True, "The user said yes. Go ahead."))
                approved_next = True
                continue

            if name in ("step_done", "task_complete"):
                summary = str(args.get("summary") or args.get("evidence") or "").strip()
                if name == "task_complete" and waiting_for_summary:
                    outcome = StepOutcome("task_done", summary)
                    pending.append(_response(name, True, "Thanks."))
                    continue
                page_text = page_view_text(page)
                read = await tools.page_text(4000)
                if read:
                    page_text += "\nPage text:\n" + read
                check = await is_step_done(
                    run.task, step, shot if add_shot or page is None else None, url,
                    run.caller, cfg.CHECK_MODEL, cfg.BACKUP_MODEL, page_text=page_text,
                )
                if not check.ok:
                    failures += 1
                    last_failure = check.reason
                    await run.ui.send_step_update(run.session_id, step.number, "retrying", check.reason)
                    pending.append(_response(name, False, f"Not finished yet: {check.reason} Keep working on this step."))
                    continue
                if name == "task_complete":
                    outcome = StepOutcome("task_done", summary or check.reason)
                    pending.append(_response(name, True, "Confirmed."))
                elif is_last:
                    # Make sure the user hears the result, not just "step finished".
                    waiting_for_summary = True
                    pending.append(_response(name, True,
                        "Confirmed. That was the last step: now call task_complete with the summary for the user "
                        "(include the answer if they asked a question)."))
                else:
                    outcome = StepOutcome("done", summary or check.reason)
                    pending.append(_response(name, True, "Confirmed."))
                continue

            result: ToolResult
            if name in LOOK_ONLY:
                result = await tools.run(name, args)
                if name == "wait":
                    await asyncio.sleep(result.data["seconds"])
                if result.wants_screenshot:
                    want_screenshot = True
                message = result.message[:MAX_READ_RESULT]
                pending.append(_response(name, result.ok, message))
                continue

            # A real action: check sign-in pages and budgets first.
            sign_in = await run.sign_in_guard.check(url)
            if sign_in == "stopped":
                await run.status("cancelled", "Stopped at the sign-in page.")
                pending.append(_response(name, False, "The user stopped at the sign-in page."))
                outcome = StepOutcome("stopped")
                continue
            if sign_in == "resumed":
                pending.append(_response(name, False, "The user just signed in themselves. Look at the new page first."))
                for later in calls[index + 1:]:
                    pending.append(_response(later.name, False, "Skipped: look at the new page first."))
                break
            if run.actions_used >= cfg.MAX_AGENT_TURNS:
                pending.append(_response(name, False, "Out of actions for this task."))
                outcome = StepOutcome("out_of_actions")
                continue

            # Sending, paying, booking, posting or deleting always needs a yes,
            # whether or not the model asked first.
            risky = risky_target(name, args, page)
            said_yes, approved_next = approved_next, False   # a yes covers only the next action
            if risky and not said_yes:
                question = f"HandOff is about to {risky}. Go ahead?"
                approved, _ = await pause_and_wait(run.session_id, "confirmation", question, run.ui)
                if not approved:
                    pending.append(_response(name, False, "The user said no."))
                    await run.status("cancelled", "You said no, so I stopped.")
                    outcome = StepOutcome("stopped")
                    continue

            plain = action_in_plain_words(name, args)
            run.actions_used += 1
            step_actions += 1
            await run.ui.send_action_preview(run.session_id, plain)
            await asyncio.sleep(run.timing.preview)
            await run.status("executing", plain if run.grandparents_mode else f"Executing: {name}")
            await log_action(run.session_id, run.actions_used, name, args)

            result = await tools.run(name, args)
            names.append(name)
            results.append({"action": name, "success": result.ok, "detail": result.message})
            run.history.append(f"{name}({', '.join(f'{k}={v}' for k, v in args.items())}) -> {'ok' if result.ok else result.message}")
            message = result.message
            if result.stale:
                message += " The page has changed; use the numbers in the new page view."
            pending.append(_response(name, result.ok, message))

            await narrate_action(name, args, run.last_action_time_ref, run.live_session_ref,
                                 grandparents_mode=run.grandparents_mode)
            await run.ui.send_action(run.session_id, result.data if isinstance(result.data, dict) else {"action": name, "success": result.ok}, run.actions_used)
            await update_session_state(run.session_id, "executing", f"Action {run.actions_used}: {name}")
            await asyncio.sleep(run.timing.after_action)

            if not result.ok:
                failures += 1
                last_failure = result.message

        if outcome is not None:
            return outcome

        if names:
            await asyncio.sleep(run.timing.after_page_load)
            run.last_action_finish = time.time()
            before, last_names, last_results = page_before, names, results
