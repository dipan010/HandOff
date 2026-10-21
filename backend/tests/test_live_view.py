"""Item 5a: the dashboard's live view is a small picture sent only while a task
runs; HandOff takes a full-size screenshot only when it needs to look (spec §2a)."""

import asyncio
import base64
import shutil
import subprocess
from pathlib import Path

import pytest

from app.browser.live_tab import LiveBrowserAdapter
from app.websocket import manager as ws_manager
from tests.fakes import FakeCaller, FakePageBrowser, FakeUI, action_reply, page
from tests.test_page_step import NO_WAIT, cfg

REPO = Path(__file__).resolve().parents[2]
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="Node not installed")
def test_extension_sends_small_frames_only_while_a_task_runs():
    out = subprocess.run([NODE, str(REPO / "extension" / "tests" / "live_view_test.js")],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert "live view ok" in out.stdout


@pytest.fixture
def extension(monkeypatch):
    """A connected extension that answers each command from `replies`."""
    sent = []
    replies = {}

    async def send(session_id, message):
        sent.append(message)
        adapter = adapters.get(session_id)
        if message.get("type") == "execute_action" and adapter is not None:
            adapter.complete_action(replies.get(message["action"], {"success": True}))

    adapters: dict = {}
    monkeypatch.setattr(ws_manager, "send_to_extension", send)
    monkeypatch.setitem(ws_manager.extension_connections, "live1", object())
    return sent, replies, adapters


async def test_handoff_asks_for_a_full_screenshot_when_it_needs_to_look(extension):
    sent, replies, adapters = extension
    adapter = adapters["live1"] = LiveBrowserAdapter("live1")
    full = b"\x89PNG full size"
    replies["screenshot"] = {"success": True, "image": base64.b64encode(full).decode(), "url": "https://a.example/"}
    adapter.note_live_frame("https://a.example/")      # live frames are for the dashboard only
    assert await asyncio.wait_for(adapter.capture_screenshot(), timeout=2) == full
    assert [m["action"] for m in sent if m.get("type") == "execute_action"] == ["screenshot"]


async def test_a_failed_screenshot_falls_back_to_the_last_one(extension):
    sent, replies, adapters = extension
    adapter = adapters["live1"] = LiveBrowserAdapter("live1")
    replies["screenshot"] = {"success": True, "image": base64.b64encode(b"first").decode()}
    assert await adapter.capture_screenshot() == b"first"
    replies["screenshot"] = {"success": False, "detail": "HandOff's tab isn't in front."}
    assert await adapter.capture_screenshot() == b"first"


async def test_live_view_starts_and_stops_with_the_task(extension):
    sent, _, adapters = extension
    adapter = adapters["live1"] = LiveBrowserAdapter("live1")
    assert not adapter.live_view
    await adapter.start_live_view()
    assert adapter.live_view and sent[-1] == {"type": "start_stream"}
    await adapter.close()
    assert not adapter.live_view and sent[-1] == {"type": "stop_stream"}


class Recording(FakePageBrowser):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.live_started_after_extension = None
        self.extension_ready = False

    async def wait_for_extension(self, timeout):
        self.extension_ready = True
        return True

    async def start_live_view(self):
        self.live_started_after_extension = self.extension_ready


async def test_the_task_turns_the_live_view_on_once_the_extension_is_there():
    from app.steps.run import run_task
    browser = Recording([page("https://example.com/", ("button", "Go"))])
    caller = FakeCaller(actions=[action_reply(call=("task_complete", {"summary": "done"}))])

    async def open_browser():
        return None

    await run_task("s1", "open example.com", "", browser, caller=caller, ui=FakeUI(), cfg=cfg(),
                   timing=NO_WAIT, open_browser=open_browser)
    assert browser.live_started_after_extension is True


def test_an_extension_that_reconnects_mid_task_resumes_the_live_view(monkeypatch):
    from starlette.testclient import TestClient

    from app import main

    adapter = LiveBrowserAdapter("live2")
    adapter.live_view = True
    monkeypatch.setitem(main.active_sessions, "live2", {"browser": adapter})
    to_dashboard = []

    async def send_screenshot(session_id, image, step):
        to_dashboard.append(image)

    monkeypatch.setattr(ws_manager, "send_screenshot", send_screenshot)
    with TestClient(main.app).websocket_connect("/ws/live_ext/live2") as ws:
        assert ws.receive_json() == {"type": "start_stream"}
        ws.send_json({"type": "screen_frame", "image": "c21hbGw=", "url": "https://b.example/"})
        ws.send_json({"type": "user_input", "kind": "click"})   # round trip, so the frame was handled
        ws.close()
    assert to_dashboard == ["c21hbGw="]
    assert adapter._latest_url == "https://b.example/"
    assert adapter._latest_screenshot_bytes is None          # a live frame is not HandOff's screenshot
