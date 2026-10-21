"""H7: a dashboard reload or a short network drop doesn't stop the running task."""

import asyncio

from app import main


async def test_task_keeps_running_if_the_dashboard_comes_back(monkeypatch):
    stopped = []

    async def fake_stop(session_id):
        stopped.append(session_id)

    monkeypatch.setattr(main, "stop_session", fake_stop)
    monkeypatch.setattr(main, "DASHBOARD_GRACE_SECONDS", 0.05)
    main.active_sessions["s1"] = {"task": "x"}
    try:
        main.dashboard_gone("s1")
        await asyncio.sleep(0.01)
        main.dashboard_back("s1")
        await asyncio.sleep(0.1)
        assert stopped == []
    finally:
        main.active_sessions.pop("s1", None)


async def test_task_stops_if_the_dashboard_stays_away(monkeypatch):
    stopped = []

    async def fake_stop(session_id):
        stopped.append(session_id)

    monkeypatch.setattr(main, "stop_session", fake_stop)
    monkeypatch.setattr(main, "DASHBOARD_GRACE_SECONDS", 0.05)
    main.active_sessions["s1"] = {"task": "x"}
    try:
        main.dashboard_gone("s1")
        await asyncio.sleep(0.15)
        assert stopped == ["s1"]
    finally:
        main.active_sessions.pop("s1", None)
