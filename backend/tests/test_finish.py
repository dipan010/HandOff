from app.steps import finish
from tests.fakes import FakeLiveSession, FakeUI


async def test_finish_speaks_and_notifies(monkeypatch):
    saved = []

    async def fake_update(session_id, status, detail=""):
        saved.append((session_id, status, detail))

    monkeypatch.setattr(finish, "update_session_state", fake_update)
    ui, live = FakeUI(), FakeLiveSession()
    done_ref = [None]

    await finish.finish_task(
        "s1", "Found 3 trains", "Dedup stop",
        live_session_ref=[live], completion_text_ref=done_ref, ui=ui, speak_wait=0,
    )

    assert live.spoken == ["Task complete. Found 3 trains"]
    assert done_ref == ["Found 3 trains"]
    assert ui.names() == ["send_task_complete", "broadcast_to_extension"]
    assert saved == [("s1", "completed", "Dedup stop")]


async def test_finish_uses_warm_words_in_grandparents_mode(monkeypatch):
    async def fake_update(*a, **k):
        pass

    monkeypatch.setattr(finish, "update_session_state", fake_update)
    live = FakeLiveSession()
    await finish.finish_task(
        "s1", "Your recipe is open", "x", grandparents_mode=True,
        live_session_ref=[live], ui=FakeUI(), speak_wait=0,
    )
    assert live.spoken == ["All done! Your recipe is open"]


async def test_finish_without_narration_session(monkeypatch):
    async def fake_update(*a, **k):
        pass

    monkeypatch.setattr(finish, "update_session_state", fake_update)
    ui = FakeUI()
    await finish.finish_task("s1", "ok", "ok", live_session_ref=[None], ui=ui, speak_wait=0)
    assert "send_task_complete" in ui.names()
