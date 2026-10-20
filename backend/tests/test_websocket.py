"""The dashboard connection must survive a failed message and overlapping sends."""

import asyncio

from starlette.websockets import WebSocketState

from app.websocket import ConnectionManager


class FakeSocket:
    def __init__(self, fail_once=False):
        self.client_state = WebSocketState.CONNECTED
        self.application_state = WebSocketState.CONNECTED
        self.sent = []
        self.fail_once = fail_once
        self.sending = False

    async def send_text(self, text):
        assert not self.sending, "two sends overlapped"
        self.sending = True
        try:
            await asyncio.sleep(0)
            if self.fail_once:
                self.fail_once = False
                raise RuntimeError("send failed")
            self.sent.append(text)
        finally:
            self.sending = False


def manager_with(ws):
    manager = ConnectionManager()
    manager.active_connections["s1"] = ws
    return manager


async def test_one_failed_message_does_not_cut_the_dashboard_off():
    ws = FakeSocket(fail_once=True)
    manager = manager_with(ws)
    await manager.send_narration("s1", "first")
    await manager.send_narration("s1", "second")
    assert manager.active_connections["s1"] is ws
    assert len(ws.sent) == 1 and "second" in ws.sent[0]


async def test_a_closed_socket_is_forgotten():
    ws = FakeSocket(fail_once=True)
    ws.client_state = WebSocketState.DISCONNECTED
    manager = manager_with(ws)
    await manager.send_narration("s1", "hello")
    assert "s1" not in manager.active_connections


async def test_sends_from_different_tasks_take_turns():
    ws = FakeSocket()
    manager = manager_with(ws)
    await asyncio.gather(*(manager.send_narration("s1", f"n{i}") for i in range(20)))
    assert len(ws.sent) == 20


def test_an_old_socket_does_not_remove_a_newer_one():
    old, new = FakeSocket(), FakeSocket()
    manager = manager_with(new)
    manager.disconnect("s1", old)
    assert manager.active_connections["s1"] is new


async def test_a_reconnecting_dashboard_gets_the_plan_steps_and_status_again():
    import json
    manager = ConnectionManager()
    first = FakeSocket()
    manager.active_connections["s1"] = first
    await manager.send_plan("s1", [{"number": 1, "title": "Open YouTube"}, {"number": 2, "title": "Play"}])
    await manager.send_step_update("s1", 1, "done", "YouTube is open")
    await manager.send_step_update("s1", 2, "working")
    await manager.send_status("s1", "thinking", "Step 2: Play")
    await manager.send_narration("s1", "not replayed")
    manager.disconnect("s1", first)

    again = FakeSocket()
    again.accept = lambda: _done()
    await manager.connect("s1", again)
    types = [json.loads(m)["type"] for m in again.sent]
    assert types == ["plan", "step_update", "step_update", "status_update"]


async def test_nothing_is_replayed_after_the_task_ends():
    manager = ConnectionManager()
    first = FakeSocket()
    manager.active_connections["s1"] = first
    await manager.send_plan("s1", [{"number": 1, "title": "Open YouTube"}])
    await manager.send_task_complete("s1", "Done.")
    manager.disconnect("s1", first)
    again = FakeSocket()
    again.accept = lambda: _done()
    await manager.connect("s1", again)
    assert again.sent == []


async def _done():
    return None
