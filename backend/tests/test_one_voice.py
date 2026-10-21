"""Live round part 2 (2026-10-21): two voices. The dashboard read messages aloud
with the browser's voice while the narrator spoke in its own. While the narrator
runs it is the only voice; the dashboard shows the text without speaking it."""

import json

from app.steps.run import run_task
from app.websocket import ConnectionManager
from tests.fakes import FakeCaller, FakeLiveSession, FakePageBrowser, FakeUI, action_reply
from tests.test_page_step import NO_WAIT, SEARCH_PAGE, cfg
from tests.test_websocket import FakeSocket


def spoken_here(ui, name):
    return [kwargs.get("speak", True) for n, _, kwargs in ui.sent if n == name]


async def run_with(live, caller):
    ui = FakeUI()
    await run_task("s1", "play lofi on youtube", "", FakePageBrowser([SEARCH_PAGE]), caller=caller, ui=ui,
                   cfg=cfg(), timing=NO_WAIT, live_session_ref=None if live is None else [live],
                   last_action_time_ref=[0.0])
    return ui


async def test_with_the_narrator_running_the_dashboard_doesnt_speak_too():
    live = FakeLiveSession()
    caller = FakeCaller(actions=[action_reply(text="Looking at the page.",
                                              call=("task_complete", {"summary": "Done."}))])
    ui = await run_with(live, caller)
    assert spoken_here(ui, "send_ack") == [False]
    assert spoken_here(ui, "send_narration") == [False]
    assert any(line for line in live.spoken)                 # the narrator said the acknowledgement


async def test_with_narration_off_the_dashboard_speaks():
    caller = FakeCaller(actions=[action_reply(text="Looking at the page.",
                                              call=("task_complete", {"summary": "Done."}))])
    ui = await run_with(None, caller)
    assert spoken_here(ui, "send_ack") == [True]
    assert spoken_here(ui, "send_narration") == [True]


async def test_the_dashboard_is_told_whether_to_speak():
    ws = FakeSocket()
    manager = ConnectionManager()
    manager.active_connections["s1"] = ws
    await manager.send_ack("s1", "On it.", speak=False)
    await manager.send_narration("s1", "Clicking 'Search'.")
    sent = [json.loads(t)["data"] for t in ws.sent]
    assert sent == [{"text": "On it.", "speak": False}, {"text": "Clicking 'Search'.", "speak": True}]


async def test_the_acknowledgement_waits_for_a_narrator_that_is_still_connecting():
    import asyncio
    live, ref = FakeLiveSession(), [None]

    async def connect_soon():
        await asyncio.sleep(0.2)
        ref[0] = live

    asyncio.create_task(connect_soon())
    ui = FakeUI()
    caller = FakeCaller(actions=[action_reply(call=("task_complete", {"summary": "Done."}))])
    await run_task("s1", "play lofi on youtube", "", FakePageBrowser([SEARCH_PAGE]), caller=caller, ui=ui,
                   cfg=cfg(), timing=NO_WAIT, live_session_ref=ref, last_action_time_ref=[0.0])
    assert spoken_here(ui, "send_ack") == [False]
