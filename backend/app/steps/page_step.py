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
import re
import time

from google.genai import types

from app.action_log import log_action
from app.browser.page_view import PAGE_VIEW_HEADER, cookie_notice_button, page_view_text, structure_hash
from app.firestore_client import update_session_state
from app.steps.check import ScreenState, changed, is_step_done, quick_check
from app.steps.describe import action_in_plain_words, action_now
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


STILL_LOADING = re.compile(r"^\s*(loading|please wait|fetching|searching)\b", re.I)


def still_loading(page: dict | None) -> bool:
    return any(STILL_LOADING.match(e.get("label") or "") for e in (page or {}).get("elements") or [])


async def settled_page(tools: BrowserTools, timing) -> dict | None:
    """The page view once the page has stopped changing after an action.

    Waits at least `settle_min`, then reads the page until two reads in a row
    match, for at most `settle_max`. A fast page is read again almost at once;
    a slow one gets the time it needs, instead of one fixed delay for both.
    """
    loop = asyncio.get_running_loop()
    await asyncio.sleep(timing.settle_min)
    deadline = loop.time() + timing.settle_max
    page = await tools.page_map()
    while True:
        if loop.time() >= deadline:
            return page
        await asyncio.sleep(timing.settle_interval)
        again = await tools.page_map()
        if (again is not None and page is not None and not still_loading(again)
                and structure_hash(again) == structure_hash(page)):
            return again
        page = again


def _forget_user_input(run) -> None:
    """After HandOff's own pauses the user was meant to use the page; that isn't a takeover."""
    if getattr(run.browser, "user_input_seen", False):
        run.browser.user_input_seen = False


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

    # Start with the tools that fit this step and the task (a plan can split a
    # form into steps that don't sound like one); once a try fails, offer them all.
    config = config_with(tools_for_step(f"{step.title} {step.done_when} {run.task}"))
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
    settled: dict | None = None              # page view read while waiting for the page to settle

    while True:
        if run.actions_used >= cfg.MAX_AGENT_TURNS:
            return StepOutcome("out_of_actions")
        if failures >= cfg.MAX_STEP_RETRIES:
            return StepOutcome("stuck", last_failure or "This step kept failing.")
        if step_actions >= cfg.MAX_STEP_ACTIONS:
            return StepOutcome("stuck", f"Used {step_actions} actions on this step without finishing it.")

        # The user clicked or typed in HandOff's tab: don't act on top of them.
        if getattr(run.browser, "user_input_seen", False):
            run.browser.user_input_seen = False
            approved, _ = await pause_and_wait(
                run.session_id, "user_input",
                "You're using the page, so HandOff has paused. Continue when you're done?", run.ui)
            if not approved:
                await run.status("cancelled", "Stopped, so you can carry on yourself.")
                return StepOutcome("stopped")
            before = None                        # the user changed the page, not HandOff
            pending.append(types.Part(text="The user used the page while HandOff was paused. Look at it again."))

        await run.status("thinking", f"Step {step.number}: {step.title}")

        page = settled if settled is not None else await tools.page_map()
        settled = None
        notes = []

        # A cookie notice covering the page: say no to it here, once per page,
        # without asking the model.
        notice = cookie_notice_button(page)
        notice_key = ((page or {}).get("url"), (notice or {}).get("label"))
        if notice is not None and notice_key not in run.closed_notices:
            run.closed_notices.add(notice_key)
            closed = await tools.run("click", {"element_id": notice.get("id")})
            if closed.ok:
                logger.info(f"Closed a cookie notice: {notice.get('label')}")
                notes.append(f"HandOff closed a cookie notice by choosing \"{notice.get('label')}\".")
                page = await settled_page(tools, run.timing) or page
        tools.last_page = page
        # A full screenshot only when the model will look at it: the page view
        # usually says enough, and the dashboard has its own live view.
        few_items = page is not None and len(page.get("elements") or []) < 3
        add_shot = want_screenshot or page is None or few_items or failures >= 2
        want_screenshot = False
        shot = await run.screenshot() if add_shot else None
        if shot:
            await run.show_and_save(shot)
        add_shot = bool(shot)
        url = (page or {}).get("url") or await run.url()

        # Did the last batch of actions change anything?
        if before is not None:
            effect = changed(before, ScreenState.of(url, shot, page=page), last_results, last_names)
            before = None
            if not effect.ok:
                failures += 1
                last_failure = effect.reason
                await run.ui.send_step_update(run.session_id, step.number, "retrying", effect.reason)
                notes.append(f"Result of your last actions: {effect.reason} Try a different way.")
                if shot is None and failures >= 2:
                    shot = await run.screenshot()
                    if shot:
                        await run.show_and_save(shot)
                    add_shot = bool(shot)

        if page is None:
            unreadable += 1
            if unreadable > 5:
                return StepOutcome("error", "HandOff can't read this page. Is the HandOff extension installed and on?")
            want_screenshot = True
        else:
            unreadable = 0

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
            await run.ui.send_narration(run.session_id, text, speak=not run.narrator_on())
        if not calls:
            failures += 1
            last_failure = "Gemini answered without choosing an action."
            pending.append(types.Part(text="Please answer with a tool call."))
            continue

        page_before = ScreenState.of(url, shot, page=page)
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
                _forget_user_input(run)
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
                # Check against the page as it is now: actions earlier in this
                # turn may have changed it since the page view was taken.
                check_page, check_shot, check_url = page, (shot if add_shot or page is None else None), url
                if names:
                    check_page = await settled_page(tools, run.timing) or page
                    check_url = (check_page or {}).get("url") or await run.url() or url
                    if check_shot is not None or check_page is None:
                        check_shot = await run.screenshot()
                read = await tools.page_text(4000)
                check = quick_check(step, check_url, check_page, read, summary, ends_task=(name == "task_complete"))
                if check is None:
                    page_text = page_view_text(check_page)
                    if read:
                        page_text += "\nPage text:\n" + read
                    check = await is_step_done(
                        run.task, step, check_shot, check_url,
                        run.caller, cfg.CHECK_MODEL, cfg.BACKUP_MODEL, page_text=page_text,
                    )
                else:
                    logger.info(f"Step {step.number} checked in code: {check.reason}")
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

            # The user started using the page during this turn: stop here and
            # ask at the top of the next turn.
            if getattr(run.browser, "user_input_seen", False):
                pending.append(_response(name, False, "Not done: the user is using the page."))
                for later in calls[index + 1:]:
                    pending.append(_response(later.name, False, "Not done: the user is using the page."))
                break

            # A real action: check sign-in pages and budgets first.
            sign_in = await run.sign_in_guard.check(url)
            if sign_in != "clear":
                _forget_user_input(run)
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
                _forget_user_input(run)
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
            await run.status("executing", action_now(name, args, page))
            await log_action(run.session_id, run.actions_used, name, args)

            # Tell the narrator as the action starts, so speech keeps up with it.
            await narrate_action(name, args, run.last_action_time_ref, run.live_session_ref,
                                 grandparents_mode=run.grandparents_mode)
            result = await tools.run(name, args)
            names.append(name)
            reply = result.data if isinstance(result.data, dict) else {}
            results.append({"action": name, "success": result.ok, "detail": result.message,
                            **{k: reply[k] for k in ("page_change", "already", "no_answer") if k in reply}})
            run.history.append(f"{name}({', '.join(f'{k}={v}' for k, v in args.items())}) -> {'ok' if result.ok else result.message}")
            message = result.message
            if result.stale:
                message += " The page has changed; use the numbers in the new page view."
            pending.append(_response(name, result.ok, message))

            await run.ui.send_action(run.session_id, result.data if isinstance(result.data, dict) else {"action": name, "success": result.ok}, run.actions_used)
            await update_session_state(run.session_id, "executing", f"Action {run.actions_used}: {name}")
            await asyncio.sleep(run.timing.after_action)

            if not result.ok:
                failures += 1
                last_failure = result.message

            # The action may have opened a sign-in or payment page: re-read the
            # address so the next action in this turn is checked against it.
            if index < len(calls) - 1:
                url = await run.url() or url

        if outcome is not None:
            return outcome

        if names:
            settled = await settled_page(tools, run.timing)
            run.last_action_finish = time.time()
            before, last_names, last_results = page_before, names, results
