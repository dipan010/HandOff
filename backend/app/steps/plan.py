"""Turn a task into a short list of steps, and rewrite the rest when a step fails."""

import logging
from dataclasses import asdict, dataclass

from app.steps.model_call import Caller, ask_json

logger = logging.getLogger(__name__)

MAX_STEPS = 6


@dataclass
class Step:
    number: int
    title: str        # what to do, e.g. "Open the YouTube search results for 'lofi'"
    done_when: str    # what the screen shows when it's done

    def as_dict(self) -> dict:
        return asdict(self)


PLAN_PROMPT = """You plan browser tasks for HandOff, a helper for people who find computers hard to use.

Task: "{task}"
{where}

Split the task into 1 to {max_steps} steps. Simple tasks need only 1 or 2 steps.
Each step is something you can see is finished by looking at the browser.
Keep the user's exact names, places and dates.
The browser is already open; never include a step to open the browser.

Answer with JSON only:
{{"steps": [{{"title": "...", "done_when": "..."}}]}}

"title": the action in plain words.
"done_when": what is visible on screen once the step is finished."""


REVISE_PROMPT = """You plan browser tasks for HandOff, a helper for people who find computers hard to use.

Task: "{task}"

Steps already finished:
{finished}

This step could not be finished: "{failed}"
What went wrong: {reason}
Current page: {url}

Write the remaining steps (1 to {max_steps}) to still complete the task, trying a different way than the failed step.
If the task cannot be done (for example the item does not exist or the site refuses), answer with an empty list.

Answer with JSON only:
{{"steps": [{{"title": "...", "done_when": "..."}}]}}"""


def single_step_plan(task: str) -> list[Step]:
    """Used when planning fails: the whole task is one step."""
    return [Step(number=1, title=task, done_when="The user's request is visibly finished on screen.")]


def _to_steps(answer, first_number: int = 1) -> list[Step]:
    raw = answer.get("steps") if isinstance(answer, dict) else answer
    if not isinstance(raw, list):
        raise ValueError("No step list in answer")
    steps = []
    for item in raw[:MAX_STEPS]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        done_when = str(item.get("done_when", "")).strip()
        if title:
            steps.append(Step(
                number=first_number + len(steps),
                title=title,
                done_when=done_when or f"{title} is visibly finished on screen.",
            ))
    return steps


async def make_plan(task: str, start_url: str, caller: Caller, model: str, backup: str | None) -> list[Step]:
    where = f'The browser is already on: "{start_url}"' if start_url else "The browser is open on a blank or search page."
    prompt = PLAN_PROMPT.format(task=task, where=where, max_steps=MAX_STEPS)
    try:
        steps = _to_steps(await ask_json(caller, model, backup, prompt))
    except Exception as err:
        logger.warning(f"Planning failed, using one step: {err}")
        return single_step_plan(task)
    return steps or single_step_plan(task)


async def revise_plan(
    task: str,
    finished: list[Step],
    failed: Step,
    reason: str,
    url: str,
    caller: Caller,
    model: str,
    backup: str | None,
) -> list[Step]:
    """Return new remaining steps, numbered after the finished ones. Empty list = give up."""
    finished_text = "\n".join(f"{s.number}. {s.title}" for s in finished) or "(none)"
    prompt = REVISE_PROMPT.format(
        task=task, finished=finished_text, failed=failed.title,
        reason=reason, url=url or "unknown", max_steps=MAX_STEPS,
    )
    answer = await ask_json(caller, model, backup, prompt)
    return _to_steps(answer, first_number=len(finished) + 1)
