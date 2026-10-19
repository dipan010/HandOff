import pytest

from app.config import Settings
from app.steps import run as run_module
from app.steps.run import Timing, run_task
from tests.fakes import FakeBrowser, FakeCaller, FakeUI, action_reply

NO_WAIT = Timing(after_action=0, after_page_load=0, preview=0, speak_wait=0, no_frame_wait=0)


@pytest.fixture(autouse=True)
def quiet_side_effects(monkeypatch):
    async def nothing(*a, **k):
        return None

    monkeypatch.setattr(run_module, "upload_screenshot", nothing)
    monkeypatch.setattr(run_module, "log_action", nothing)
    monkeypatch.setattr(run_module, "update_session_state", nothing)
    monkeypatch.setattr("app.steps.finish.update_session_state", nothing)


def cfg(**overrides):
    return Settings(GOOGLE_API_KEY="test", **overrides)


async def start(caller, browser=None, **settings):
    ui = FakeUI()
    browser = browser or FakeBrowser()
    await run_task("s1", "play lofi on youtube", "", browser,
                   caller=caller, ui=ui, cfg=cfg(**settings), timing=NO_WAIT)
    return ui, browser


def sent(ui, name):
    return [args for n, args, _ in ui.sent if n == name]


async def test_chat_is_answered_without_browser():
    caller = FakeCaller(sort=[{"kind": "chat", "effort": "quick", "reply": "Hello there!"}])
    ui, browser = await start(caller)
    assert sent(ui, "send_quick_reply") == [("Hello there!",)]
    assert sent(ui, "send_task_complete") == [("Hello there!",)]
    assert browser.actions == [] and caller.count("action") == 0


async def test_two_step_task_runs_to_the_end():
    caller = FakeCaller(
        plan=[{"steps": [
            {"title": "Search for lofi", "done_when": "Results are shown"},
            {"title": "Play the first video", "done_when": "A video is playing"},
        ]}],
        actions=[
            action_reply(call=("type_text_at", {"x": 1, "y": 2, "text": "lofi"})),
            action_reply("STEP DONE: results shown"),
            action_reply(call=("click_at", {"x": 5, "y": 5})),
            action_reply("TASK COMPLETE: The lofi stream is playing."),
        ],
    )
    ui, browser = await start(caller)

    assert [a[0] for a in browser.actions] == ["type_text_at", "click_at"]
    assert sent(ui, "send_ack")
    assert len(sent(ui, "send_plan")[0][0]) == 2
    states = [(n, s) for n, s, *_ in sent(ui, "send_step_update")]
    assert (1, "done") in states and (2, "done") in states
    assert sent(ui, "send_task_complete") == [("The lofi stream is playing.",)]
    assert caller.count("check") == 2


async def test_hard_tasks_are_planned_with_strong_model():
    caller = FakeCaller(sort=[{"kind": "task", "effort": "hard", "reply": None}])
    await start(caller, STRONG_MODEL="strong", FAST_MODEL="fast")
    assert ("plan", "strong") in caller.calls


async def test_step_not_really_done_keeps_working():
    caller = FakeCaller(
        actions=[
            action_reply("TASK COMPLETE: playing"),
            action_reply(call=("click_at", {"x": 1, "y": 1})),
            action_reply("TASK COMPLETE: playing now"),
        ],
        check=[{"done": False, "reason": "Video is paused"}, {"done": True, "reason": "Playing"}],
    )
    ui, browser = await start(caller)
    assert len(browser.actions) == 1
    assert any(s == "retrying" for _, s, *_ in sent(ui, "send_step_update"))
    assert sent(ui, "send_task_complete") == [("playing now",)]


async def test_frozen_screen_leads_to_replan_then_gives_up():
    caller = FakeCaller(actions=[
        action_reply(call=("click_at", {"x": 1, "y": 1})),
        action_reply(call=("click_at", {"x": 2, "y": 2})),
        action_reply(call=("click_at", {"x": 3, "y": 3})),
    ])
    ui, browser = await start(caller, browser=FakeBrowser(frozen=True), MAX_PLAN_REVISIONS=1)
    assert caller.count("revise") == 1
    summary = sent(ui, "send_task_complete")[0][0]
    assert summary.startswith("I couldn't finish this.")
    assert "Nothing on the screen changed" in summary


async def test_replan_continues_with_new_steps():
    caller = FakeCaller(
        actions=[
            action_reply(call=("click_at", {"x": 1, "y": 1})),
            action_reply(call=("click_at", {"x": 2, "y": 2})),
            action_reply(call=("click_at", {"x": 3, "y": 3})),
            action_reply("TASK COMPLETE: found it another way"),
        ],
        revise=[{"steps": [{"title": "Use the menu", "done_when": "Menu item open"}]}],
    )
    browser = FakeBrowser(fail_actions=True)
    ui, _ = await start(caller, browser=browser)
    plans = sent(ui, "send_plan")
    assert len(plans) == 2
    assert sent(ui, "send_task_complete") == [("found it another way",)]


async def test_action_budget_is_shared_across_the_task():
    caller = FakeCaller(actions=[action_reply(call=("scroll_document", {"direction": "down"}))])
    ui, browser = await start(caller, MAX_AGENT_TURNS=2, MAX_STEP_ACTIONS=50, MAX_STEP_RETRIES=50)
    assert len(browser.actions) == 2
    assert "limit of 2 actions" in sent(ui, "send_task_complete")[0][0]


async def test_gemini_error_is_shown_plainly():
    caller = FakeCaller(actions=[RuntimeError("503 UNAVAILABLE")])
    ui, _ = await start(caller)
    assert "busy" in sent(ui, "send_error")[0][0]
    assert sent(ui, "send_task_complete") == []
