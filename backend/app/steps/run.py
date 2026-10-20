"""Plan, do, check: how HandOff carries out a task.

1. Sort the request. Chat gets an answer straight away; tasks go on.
2. Say a short "on it" so the user knows they were heard.
3. Plan a few steps, each with a "done when" description.
4. For each step, let the Computer Use model act one action at a time.
   After every action, check that something actually happened.
   When the model says a step is finished, check that against the screen.
5. If a step keeps failing, rewrite the remaining steps (a limited number of times).
6. Finish with a spoken summary.

The whole task shares one action budget (MAX_AGENT_TURNS).
"""

import asyncio
import base64
import hashlib
import logging
import re
import time
from dataclasses import dataclass, field

from google.genai import types

from app.action_log import log_action
from app.browser.base import BrowserAdapter
from app.config import get_settings
from app.firestore_client import update_session_state
from app.steps.check import ScreenState, changed, is_step_done
from app.steps.describe import action_in_plain_words
from app.steps.finish import finish_task
from app.steps.model_call import Caller, GeminiCaller, plain_error, used_up, used_up_message
from app.steps.page_step import do_step_by_page
from app.steps.plan import Step, make_plan, revise_plan
from app.steps.safety import SignInGuard, pause_and_wait
from app.steps.sort import sort_request
from app.storage import upload_screenshot
from app.voice.narration import narrate_action
from app.websocket import manager as default_ui

logger = logging.getLogger(__name__)

ACK_LINES = [
    "Sure, I'm on it.",
    "Okay, let me do that for you.",
    "Got it, starting now.",
    "Right away.",
]
ACK_LINES_WARM = [
    "Of course, I'll take care of that for you.",
    "No problem at all, let me do that now.",
    "Happy to help, give me just a moment.",
]

ACTION_RULES = (
    "You operate a web browser for a person who finds computers hard to use. "
    "You work on ONE step of a larger plan at a time. Issue ONE action per response.\n\n"
    "WHEN TO STOP:\n"
    "- When the current step is finished, reply 'STEP DONE: <what you see that shows it>'.\n"
    "- When the user's whole task is finished, reply 'TASK COMPLETE: <summary for the user>'. "
    "If the user asked a question, put the answer in the summary.\n"
    "- If the site clearly shows 'no results', 'not available' or similar, reply "
    "'TASK COMPLETE: <what you found>' instead of searching forever.\n"
    "- Search results alone don't finish a task; open the actual site and do it there.\n\n"
    "ACTION RULES:\n"
    "1. One action per response.\n"
    "2. The list of earlier actions is shown to you. Do not repeat an action that did nothing.\n"
    "3. Use 'navigate' to go to a URL directly; never type URLs into search boxes.\n"
    "4. For sensitive actions (passwords, payments) use 'require_confirmation'.\n"
    "5. Keep the user's exact names, stations, cities and dates.\n"
    "6. If the page is still loading, wait and let the next screenshot show the result.\n"
    "7. To scroll, use 'scroll' with a 'coordinate' on the element to scroll, a 'direction' and an "
    "'amount' in clicks (1 click = 120 pixels).\n"
    "8. For dropdowns, city pickers and suggestion lists, use 'select_option' with the exact visible text. "
    "Use 'click_at' inside them only if 'select_option' is not available."
)

LAST_STEP_NOTE = (
    "This is the LAST step. When it is finished, reply 'TASK COMPLETE: <summary for the user>' "
    "(not STEP DONE). If the user asked a question, the summary must contain the answer.\n\n"
)

ASK_FOR_SUMMARY = (
    "Every step is finished. Reply with 'TASK COMPLETE: <summary for the user>'. "
    "If the user asked a question, give the answer from what is on screen. Do not take any more actions."
)

_MARKER = re.compile(r"(TASK COMPLETE|STEP DONE)\s*:?\s*(.*)", re.IGNORECASE | re.DOTALL)


def find_marker(text: str) -> tuple[str, str] | None:
    """Return ("task" | "step", summary) if the model said it finished something."""
    match = _MARKER.search(text or "")
    if not match:
        return None
    kind = "task" if match.group(1).upper().startswith("TASK") else "step"
    return kind, match.group(2).strip()


def trim_screenshots(contents: list, keep: int) -> list:
    """Keep only the newest `keep` screenshots in the history; older ones become a note."""
    seen = 0
    trimmed = []
    for content in reversed(contents):
        parts = getattr(content, "parts", None) or []
        if any(getattr(p, "inline_data", None) for p in parts):
            seen += 1
            if seen > keep:
                content = types.Content(role=content.role, parts=[types.Part(text="[older screenshot removed]")])
        trimmed.append(content)
    return list(reversed(trimmed))


@dataclass
class Timing:
    after_action: float
    after_page_load: float
    preview: float = 0.8
    speak_wait: float = 4.0
    no_frame_wait: float = 1.0

    @classmethod
    def for_mode(cls, patience_mode: bool) -> "Timing":
        return cls(after_action=2.0, after_page_load=4.0) if patience_mode else cls(after_action=0.5, after_page_load=1.0)


@dataclass
class StepOutcome:
    kind: str           # "done", "task_done", "stuck", "out_of_actions", "stopped", "error"
    summary: str = ""


@dataclass
class TaskRun:
    session_id: str
    task: str
    start_url: str
    browser: BrowserAdapter
    caller: Caller
    ui: object
    cfg: object
    timing: Timing
    grandparents_mode: bool = False
    last_action_time_ref: list | None = None
    completion_text_ref: list | None = None
    live_session_ref: list | None = None
    actions_used: int = 0
    frames_saved: int = 0
    history: list[str] = field(default_factory=list)
    last_action_finish: float = 0.0
    next_screenshot: bytes | None = None
    sign_in_guard: SignInGuard | None = None
    action_model: str = ""   # model used to choose page actions (quick: FAST, hard: STRONG)

    def __post_init__(self):
        if self.sign_in_guard is None:
            self.sign_in_guard = SignInGuard(self.session_id, self.ui)

    # ── small helpers ────────────────────────────────────────────────────

    async def finish(self, summary: str, note: str) -> None:
        await finish_task(
            self.session_id, summary, note,
            grandparents_mode=self.grandparents_mode,
            live_session_ref=self.live_session_ref,
            completion_text_ref=self.completion_text_ref,
            ui=self.ui,
            speak_wait=self.timing.speak_wait,
        )

    async def status(self, state: str, detail: str) -> None:
        await self.ui.send_status(self.session_id, state, detail, self.grandparents_mode)

    async def say_on_it(self) -> None:
        lines = ACK_LINES_WARM if self.grandparents_mode else ACK_LINES
        line = lines[len(self.task) % len(lines)]
        await self.ui.send_ack(self.session_id, line)
        session = self.live_session_ref[0] if self.live_session_ref else None
        if session is not None:
            try:
                await session.send_client_content(turns=types.Content(parts=[types.Part(text=line)]))
            except Exception:
                pass

    async def screenshot(self) -> bytes | None:
        if self.next_screenshot:
            shot, self.next_screenshot = self.next_screenshot, None
            return shot
        return await self.browser.capture_screenshot(min_timestamp=self.last_action_finish)

    async def show_and_save(self, shot: bytes) -> None:
        self.frames_saved += 1
        await self.ui.send_screenshot(self.session_id, base64.b64encode(shot).decode("utf-8"), self.frames_saved)
        asyncio.create_task(upload_screenshot(self.session_id, self.frames_saved, shot))

    async def url(self) -> str:
        try:
            return await self.browser.get_current_url()
        except Exception:
            return ""

    def opening_message(self, step: Step, plan: list[Step]) -> types.Content:
        is_last = step is plan[-1]
        plan_text = "\n".join(f"{s.number}. {s.title}" for s in plan)
        recent = "\n".join(self.history[-15:]) or "(nothing yet)"
        start = f"The browser started on: {self.start_url}\n" if self.start_url else ""
        text = (
            f"The user's task: {self.task}\n{start}\n"
            f"Plan:\n{plan_text}\n\n"
            f"Actions so far:\n{recent}\n\n"
            f"Work on step {step.number} now: {step.title}\n"
            f"This step is finished when: {step.done_when}\n\n"
            + (LAST_STEP_NOTE if is_last else "")
            + "The browser is already open. Do NOT call open_web_browser."
        )
        return types.Content(role="user", parts=[types.Part(text=text)])

    # ── one step ─────────────────────────────────────────────────────────

    async def do_step(self, step: Step, plan: list[Step]) -> StepOutcome:
        cfg = self.cfg
        action_config = types.GenerateContentConfig(
            tools=[types.Tool(computer_use=types.ComputerUse(environment=types.Environment.ENVIRONMENT_BROWSER))],
            system_instruction=ACTION_RULES,
        )
        contents: list = [self.opening_message(step, plan)]
        failures, step_actions, nudges, empty_frames = 0, 0, 0, 0
        last_failure = ""
        last_signature, last_hash = None, None

        while True:
            if self.actions_used >= cfg.MAX_AGENT_TURNS:
                return StepOutcome("out_of_actions")
            if failures >= cfg.MAX_STEP_RETRIES:
                return StepOutcome("stuck", last_failure or "This step kept failing.")
            if step_actions >= cfg.MAX_STEP_ACTIONS:
                return StepOutcome("stuck", f"Used {step_actions} actions on this step without finishing it.")

            await self.status("thinking", f"Step {step.number}: {step.title}")

            shot = await self.screenshot()
            if not shot:
                empty_frames += 1
                if empty_frames > 10:
                    return StepOutcome("error", "No picture is coming from the browser. Is the HandOff extension installed and on?")
                await asyncio.sleep(self.timing.no_frame_wait)
                continue
            empty_frames = 0
            await self.show_and_save(shot)

            contents.append(types.Content(role="user", parts=[
                types.Part(inline_data=types.Blob(mime_type="image/png", data=shot)),
            ]))
            contents = trim_screenshots(contents, cfg.KEEP_SCREENSHOTS)

            try:
                response = await self.caller.ask(cfg.COMPUTER_USE_MODEL, contents, action_config)
            except Exception as err:
                logger.error(f"Action model error: {err}")
                return StepOutcome("error", plain_error(err))

            candidate = response.candidates[0] if response and getattr(response, "candidates", None) else None
            content = candidate.content if candidate else None
            if content is None or not getattr(content, "parts", None):
                return StepOutcome("error", "Gemini gave no usable answer. Try rewording the task.")
            contents.append(content)

            text = " ".join(p.text for p in content.parts if getattr(p, "text", None))
            calls = [p.function_call for p in content.parts if getattr(p, "function_call", None)]
            marker = find_marker(text)
            if text and not marker:
                await self.ui.send_narration(self.session_id, text)

            # The model says it's finished, or has stopped acting: check the screen.
            if marker or (not calls and nudges >= 1):
                check = await is_step_done(
                    self.task, step, shot, await self.url(),
                    self.caller, cfg.CHECK_MODEL, cfg.BACKUP_MODEL,
                )
                if check.ok:
                    kind = "task_done" if marker and marker[0] == "task" else "done"
                    summary = (marker[1] if marker else "") or check.reason
                    if kind == "done" and step is plan[-1]:
                        # Make sure the user hears the result, not just "step finished".
                        summary = await self.final_summary(contents, action_config) or summary
                        kind = "task_done"
                    return StepOutcome(kind, summary)
                failures += 1
                last_failure = check.reason
                nudges = 0
                await self.ui.send_step_update(self.session_id, step.number, "retrying", check.reason)
                contents.append(types.Content(role="user", parts=[types.Part(
                    text=f"Not finished yet: {check.reason} Keep working on step {step.number}."
                )]))
                continue

            if not calls:
                nudges += 1
                contents.append(types.Content(role="user", parts=[types.Part(text=(
                    "What is the ONE next action? If this step is finished say 'STEP DONE: ...'. "
                    "If the whole task is finished say 'TASK COMPLETE: ...'."
                ))]))
                continue
            nudges = 0

            signature = str([(c.name, dict(c.args) if c.args else {}) for c in calls])
            screen_hash = hashlib.md5(shot).hexdigest()
            if signature == last_signature and screen_hash == last_hash:
                failures += 1
                last_failure = "Repeated the same action on a screen that didn't change."
                last_signature = None
                await self.ui.send_step_update(self.session_id, step.number, "retrying", last_failure)
                contents.append(types.Content(role="user", parts=[types.Part(
                    text="You repeated the same action and nothing changed. Try a different way."
                )]))
                continue
            last_signature, last_hash = signature, screen_hash

            before = ScreenState.of(await self.url(), shot)
            outcome, results, names = await self.act(calls)
            if outcome is not None:
                return outcome
            if not names:
                # Nothing was carried out (e.g. the user just signed in): look again.
                last_signature = None
                continue
            step_actions += len(names)

            await asyncio.sleep(self.timing.after_page_load)
            self.last_action_finish = time.time()

            after_shot = await self.browser.capture_screenshot(min_timestamp=self.last_action_finish)
            self.next_screenshot = after_shot or None
            effect = changed(before, ScreenState.of(await self.url(), after_shot), results, names)
            if not effect.ok:
                failures += 1
                last_failure = effect.reason
                await self.ui.send_step_update(self.session_id, step.number, "retrying", effect.reason)

            done_list = "\n".join(f"  - {line}" for line in self.history[-len(names):]) if names else "  (none)"
            contents.append(types.Content(role="user", parts=[types.Part(text=(
                f"Actions just taken:\n{done_list}\nResult: {effect.reason}"
                + ("" if effect.ok else " Try a different way.")
                + "\n\nA new screenshot follows. If this step is finished say 'STEP DONE: ...'. "
                "If the whole task is finished say 'TASK COMPLETE: ...'. Otherwise give the ONE next action."
            ))]))

    async def final_summary(self, contents: list, action_config) -> str:
        """Ask the action model for the closing summary (with the answer, if any)."""
        contents = contents + [types.Content(role="user", parts=[types.Part(text=ASK_FOR_SUMMARY)])]
        try:
            response = await self.caller.ask(self.cfg.COMPUTER_USE_MODEL, contents, action_config)
            parts = response.candidates[0].content.parts
        except Exception as err:
            logger.warning(f"Could not get a closing summary: {err}")
            return ""
        text = " ".join(p.text for p in parts if getattr(p, "text", None))
        marker = find_marker(text)
        return (marker[1] if marker else text).strip()

    async def act(self, calls) -> tuple[StepOutcome | None, list[dict], list[str]]:
        """Carry out the model's actions. Returns (early outcome or None, results, action names)."""
        results, names = [], []
        for call in calls:
            name = call.name
            args = dict(call.args) if call.args else {}

            if name == "require_confirmation":
                prompt = args.get("message", "HandOff wants to do something sensitive.")
                approved, _ = await pause_and_wait(self.session_id, "confirmation", prompt, self.ui)
                if not approved:
                    await self.status("cancelled", "You said no, so I stopped.")
                    return StepOutcome("stopped"), results, names
                continue

            sign_in = await self.sign_in_guard.check(await self.url())
            if sign_in == "stopped":
                await self.status("cancelled", "Stopped at the sign-in page.")
                return StepOutcome("stopped"), results, names
            if sign_in == "resumed":
                break  # the page changed while the user signed in; look again first

            if self.actions_used >= self.cfg.MAX_AGENT_TURNS:
                return StepOutcome("out_of_actions"), results, names

            plain = action_in_plain_words(name, args)
            self.actions_used += 1
            await self.ui.send_action_preview(self.session_id, plain)
            await asyncio.sleep(self.timing.preview)
            await self.status("executing", plain if self.grandparents_mode else f"Executing: {name}")
            await log_action(self.session_id, self.actions_used, name, args)

            result = await self.browser.execute_action(name, args)
            results.append(result if isinstance(result, dict) else {})
            names.append(name)
            self.history.append(f"{name}({', '.join(f'{k}={v}' for k, v in args.items())})")

            await narrate_action(name, args, self.last_action_time_ref, self.live_session_ref,
                                 grandparents_mode=self.grandparents_mode)
            await self.ui.send_action(self.session_id, result, self.actions_used)
            await update_session_state(self.session_id, "executing", f"Action {self.actions_used}: {name}")
            await asyncio.sleep(self.timing.after_action)
        return None, results, names


async def run_task(
    session_id: str,
    task: str,
    start_url: str,
    browser: BrowserAdapter,
    patience_mode: bool = False,
    grandparents_mode: bool = False,
    last_action_time_ref: list | None = None,
    completion_text_ref: list | None = None,
    live_session_ref: list | None = None,
    *,
    caller: Caller | None = None,
    ui=default_ui,
    cfg=None,
    timing: Timing | None = None,
    open_browser=None,
) -> None:
    """Same arguments as the classic loop, so main.py can call either.

    `open_browser` is awaited once the request turns out to be a real task;
    it opens the tab and starts narration. Chat never opens anything.
    """
    cfg = cfg or get_settings()
    run = TaskRun(
        session_id=session_id, task=task, start_url=start_url, browser=browser,
        caller=caller or GeminiCaller(cfg.GOOGLE_API_KEY), ui=ui, cfg=cfg,
        timing=timing or Timing.for_mode(patience_mode),
        grandparents_mode=grandparents_mode,
        last_action_time_ref=last_action_time_ref,
        completion_text_ref=completion_text_ref,
        live_session_ref=live_session_ref,
    )

    if isinstance(run.caller, GeminiCaller) and run.caller.on_wait is None:
        async def waiting(seconds: float) -> None:
            await run.status("waiting", "Just a moment, Gemini asked me to wait..." if run.grandparents_mode
                             else f"Waiting a moment for Gemini ({seconds:.0f}s)...")
        run.caller.on_wait = waiting

    sorted_request = await sort_request(task, start_url, run.caller, cfg.SORT_MODEL, cfg.BACKUP_MODEL)
    if sorted_request.kind == "chat":
        await ui.send_quick_reply(session_id, sorted_request.reply)
        await run.finish(sorted_request.reply, "Quick reply")
        return

    # Every model that could do the task has used up today's requests:
    # say so now instead of opening a tab and failing step after step.
    if used_up.all_used_up([cfg.FAST_MODEL, cfg.STRONG_MODEL, cfg.BACKUP_MODEL]):
        message = used_up_message()
        await ui.send_error(session_id, message)
        await update_session_state(session_id, "error", "Daily limit used up")
        return

    if open_browser is not None:
        await open_browser()
    await run.say_on_it()
    plan_model = cfg.STRONG_MODEL if sorted_request.effort == "hard" else cfg.FAST_MODEL
    run.action_model = plan_model
    await run.status("thinking", "Planning the steps...")
    remaining = await make_plan(task, start_url, run.caller, plan_model, cfg.BACKUP_MODEL)
    finished: list[Step] = []
    revisions = 0
    await ui.send_plan(session_id, [s.as_dict() for s in remaining], revision=0)

    last_summary = ""
    while remaining:
        step = remaining[0]
        await ui.send_step_update(session_id, step.number, "working")
        if cfg.ACTION_MODE == "screenshot":
            outcome = await run.do_step(step, finished + remaining)
        else:
            outcome = await do_step_by_page(run, step, finished + remaining)

        if outcome.kind == "done":
            finished.append(remaining.pop(0))
            last_summary = outcome.summary
            await ui.send_step_update(session_id, step.number, "done", outcome.summary)
            continue

        if outcome.kind == "task_done":
            await ui.send_step_update(session_id, step.number, "done", outcome.summary)
            await run.finish(outcome.summary or "All done.", outcome.summary or "Task complete")
            return

        if outcome.kind == "stopped":
            await update_session_state(session_id, "cancelled", "User said no")
            return

        if outcome.kind == "out_of_actions":
            summary = f"I reached the limit of {cfg.MAX_AGENT_TURNS} actions. The task may be only partly done."
            await run.finish(summary, "Max turns reached")
            return

        if outcome.kind == "error":
            await ui.send_error(session_id, outcome.summary)
            await update_session_state(session_id, "error", outcome.summary)
            return

        # Stuck: rewrite the remaining steps, a limited number of times.
        await ui.send_step_update(session_id, step.number, "failed", outcome.summary)
        new_steps: list[Step] = []
        if revisions < cfg.MAX_PLAN_REVISIONS:
            revisions += 1
            await run.status("thinking", "That didn't work. Trying another way...")
            try:
                new_steps = await revise_plan(
                    task, finished, step, outcome.summary, await run.url(),
                    run.caller, plan_model, cfg.BACKUP_MODEL,
                )
            except Exception as err:
                logger.warning(f"Re-planning failed: {err}")
        if not new_steps:
            await run.finish(f"I couldn't finish this. {outcome.summary}", "Stuck")
            return
        remaining = new_steps
        await ui.send_plan(session_id, [s.as_dict() for s in finished + remaining], revision=revisions)

    await run.finish(last_summary or "All the steps are finished.", "All steps done")
