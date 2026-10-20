"""Item 3: wait for the extension before the first action, and for the page to
settle after actions instead of a fixed delay."""

import asyncio

from app.browser.live_tab import LiveBrowserAdapter
from app.steps.run import Timing
from app.websocket import manager as ws_manager
from tests.fakes import FakeCaller, FakePageBrowser, FakeUI, action_reply, page
from tests.test_page_step import NO_WAIT, cfg, sent

FORM = page("https://example.com/form", ("button", "Search"))
LOADING = page("https://example.com/results", ("link", "Loading..."))
RESULTS = page("https://example.com/results", ("link", "First result"), ("link", "Second result"))


async def test_waits_for_the_extension_to_connect():
    adapter = LiveBrowserAdapter("ext1")

    async def connect_soon():
        await asyncio.sleep(0.05)
        ws_manager.extension_connections["ext1"] = object()

    try:
        asyncio.create_task(connect_soon())
        assert await adapter.wait_for_extension(timeout=1.0)
    finally:
        ws_manager.extension_connections.pop("ext1", None)


async def test_gives_up_when_the_extension_never_connects():
    assert not await LiveBrowserAdapter("ext2").wait_for_extension(timeout=0.1)


async def test_actions_fail_at_once_without_the_extension():
    adapter = LiveBrowserAdapter("ext3")
    adapter.reconnect_wait = 0.1
    reply = await asyncio.wait_for(adapter.execute_action("page_map", {}), timeout=2)
    assert reply["success"] is False and "extension" in reply["detail"].lower()


class NoExtension(FakePageBrowser):
    async def wait_for_extension(self, timeout):
        return False


async def test_task_stops_with_a_plain_message_when_the_extension_is_missing():
    from app.steps.run import run_task
    browser = NoExtension([FORM])
    caller = FakeCaller()
    ui = FakeUI()

    async def open_browser():
        return None

    await run_task("s1", "search for shoes", "", browser, caller=caller, ui=ui, cfg=cfg(),
                   timing=NO_WAIT, open_browser=open_browser)
    errors = [args[0] for args in sent(ui, "send_error")]
    assert errors and "extension isn't connected" in errors[0] and "chrome://extensions" in errors[0]
    assert caller.count("plan") == 0 and browser.actions == []


class SlowResults(FakePageBrowser):
    """After the click, the results page shows "Loading..." for two reads."""

    def __init__(self):
        super().__init__([FORM, RESULTS])
        self.loading_reads = 0

    async def execute_action(self, name, args):
        if name == "page_map" and self.index == 1 and self.loading_reads < 2:
            self.loading_reads += 1
            return {"success": True, "page": LOADING}
        return await super().execute_action(name, args)


async def test_the_next_page_view_is_the_settled_page():
    from tests.test_page_step import start
    seen = []
    browser = SlowResults()
    caller = FakeCaller(actions=[
        action_reply(call=("click", {"element_id": 1})),
        action_reply(call=("task_complete", {"summary": "Results are open."})),
    ])
    original = caller.ask

    async def spy(model, contents, config=None):
        if config is not None and getattr(config, "tools", None):
            seen.append(" ".join(p.text for p in contents[-1].parts if getattr(p, "text", None)))
        return await original(model, contents, config)

    caller.ask = spy
    timing = Timing(after_action=0, after_page_load=0, preview=0, speak_wait=0, no_frame_wait=0,
                    settle_min=0, settle_interval=0, settle_max=2)
    ui = FakeUI()
    from app.steps.run import run_task
    await run_task("s1", "search", "", browser, caller=caller, ui=ui, cfg=cfg(), timing=timing)
    assert "First result" in seen[1] and "Loading" not in seen[1]
