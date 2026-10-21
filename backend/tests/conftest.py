import pytest


@pytest.fixture(autouse=True)
def quiet_side_effects(monkeypatch):
    """Keep every test away from HandOff's real files: actions.log, saved
    screenshots and session state."""
    async def nothing(*a, **k):
        return None

    monkeypatch.setattr("app.steps.run.upload_screenshot", nothing)
    monkeypatch.setattr("app.steps.run.log_action", nothing)
    monkeypatch.setattr("app.steps.run.update_session_state", nothing)
    monkeypatch.setattr("app.steps.page_step.log_action", nothing)
    monkeypatch.setattr("app.steps.page_step.update_session_state", nothing)
    monkeypatch.setattr("app.steps.finish.update_session_state", nothing)
