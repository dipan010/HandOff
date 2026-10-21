import pytest

from app.config import Settings
from app.steps import run as run_module
from app.steps.run import Timing, run_task
from tests.fakes import FakeBrowser, FakeCaller, FakeUI, action_reply

NO_WAIT = Timing(after_action=0, after_page_load=0, preview=0, speak_wait=0, no_frame_wait=0,
                 settle_min=0, settle_interval=0, settle_max=0)


@pytest.fixture(autouse=True)
def quiet_side_effects(monkeypatch):
    async def nothing(*a, **k):
        return None

    monkeypatch.setattr(run_module, "upload_screenshot", nothing)
    monkeypatch.setattr(run_module, "log_action", nothing)
    monkeypatch.setattr(run_module, "update_session_state", nothing)
    monkeypatch.setattr("app.steps.finish.update_session_state", nothing)


def cfg(**overrides):
    # These tests drive the screenshot mode; page mode has its own tests.
    overrides.setdefault("ACTION_MODE", "screenshot")
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


async def test_chat_never_opens_the_browser():
    opened = []

    async def open_browser(url=""):
        opened.append(True)

    caller = FakeCaller(sort=[{"kind": "chat", "effort": "quick", "reply": "Hi!"}])
    await run_task("s1", "how are you?", "", FakeBrowser(), caller=caller, ui=FakeUI(),
                   cfg=cfg(), timing=NO_WAIT, open_browser=open_browser)
    assert opened == []


async def test_tasks_open_the_browser_once_before_acting():
    order = []
    browser = FakeBrowser()

    async def open_browser(url=""):
        order.append("open")

    original = browser.execute_action

    async def act(name, args):
        order.append(name)
        return await original(name, args)

    browser.execute_action = act
    caller = FakeCaller(actions=[
        action_reply(call=("click_at", {"x": 1, "y": 1})),
        action_reply("TASK COMPLETE: done"),
    ])
    await run_task("s1", "play lofi", "", browser, caller=caller, ui=FakeUI(),
                   cfg=cfg(), timing=NO_WAIT, open_browser=open_browser)
    assert order[0] == "open" and order.count("open") == 1


async def test_last_step_ending_with_step_done_still_gives_the_answer():
    caller = FakeCaller(
        plan=[{"steps": [{"title": "Open the DeepMind article", "done_when": "Article is open"}]}],
        actions=[
            action_reply("STEP DONE: the article is open"),
            action_reply("TASK COMPLETE: DeepMind was founded by Demis Hassabis, Shane Legg and Mustafa Suleyman."),
        ],
    )
    ui, _ = await start(caller)
    summary = sent(ui, "send_task_complete")[0][0]
    assert "Demis Hassabis" in summary


async def test_last_step_is_told_to_answer():
    caller = FakeCaller(plan=[{"steps": [
        {"title": "Search", "done_when": "Results"},
        {"title": "Read the answer", "done_when": "Answer visible"},
    ]}], actions=[action_reply("STEP DONE: results"), action_reply("TASK COMPLETE: 42")])
    seen = []
    original = caller.ask

    async def spy(model, contents, config=None):
        if config is not None and getattr(config, "tools", None):
            seen.append(contents[0].parts[0].text)
        return await original(model, contents, config)

    caller.ask = spy
    await start(caller)
    first_step_prompts = [t for t in seen if "Work on step 1" in t]
    last_step_prompts = [t for t in seen if "Work on step 2" in t]
    assert first_step_prompts and "LAST step" not in first_step_prompts[0]
    assert last_step_prompts and "LAST step" in last_step_prompts[0]


async def test_sign_in_page_asks_once_then_carries_on(monkeypatch):
    asked = []

    async def fake_pause(session_id, reason, prompt, ui, needs_input=False):
        asked.append(reason)
        return True, None

    monkeypatch.setattr("app.steps.safety.pause_and_wait", fake_pause)
    caller = FakeCaller(actions=[
        action_reply(call=("click_at", {"x": 1, "y": 1})),
        action_reply(call=("click_at", {"x": 1, "y": 1})),
        action_reply("TASK COMPLETE: signed in and done"),
    ])
    browser = FakeBrowser(url="https://www.netflix.com/login")
    ui, _ = await start(caller, browser=browser)
    assert asked == ["login_wall"]
    assert len(browser.actions) == 1          # first click skipped while the user signed in
    assert sent(ui, "send_task_complete") == [("signed in and done",)]


async def test_a_task_naming_a_site_opens_the_tab_there_and_the_plan_knows_it():
    # F5 (live round, 2026-10-21): the tab opened on google.com, then went to MakeMyTrip.
    from tests.fakes import _prompt_text
    opened, prompts = [], []

    async def open_browser(url=""):
        opened.append(url)

    caller = FakeCaller(actions=[action_reply("TASK COMPLETE: done")])
    original = caller.ask

    async def spy(model, contents, config=None):
        prompts.append(_prompt_text(contents))
        return await original(model, contents, config)

    caller.ask = spy
    await run_task("s1", "on makemytrip, fill in a flight from Delhi to Mumbai", "", FakeBrowser(), caller=caller,
                   ui=FakeUI(), cfg=cfg(), timing=NO_WAIT, open_browser=open_browser)
    assert opened == ["https://www.makemytrip.com/"]
    assert any('already on: "https://www.makemytrip.com/"' in p for p in prompts if "You plan browser tasks" in p)


async def test_an_address_given_by_the_dashboard_still_wins():
    opened = []

    async def open_browser(url=""):
        opened.append(url)

    await run_task("s1", "play lofi on youtube", "https://music.example.com/", FakeBrowser(),
                   caller=FakeCaller(actions=[action_reply("TASK COMPLETE: done")]), ui=FakeUI(),
                   cfg=cfg(), timing=NO_WAIT, open_browser=open_browser)
    assert opened == ["https://music.example.com/"]
