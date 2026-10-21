"""Shared pytest fixtures for backend tests."""

import asyncio
import os
import sys
from pathlib import Path

import pytest

# Make `app.*` imports work without installing the package
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Provide a dummy API key so config.Settings() validates during import
os.environ.setdefault("GOOGLE_API_KEY", "test-key")


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


@pytest.fixture
def event_loop():
    """Provide a fresh event loop per test so module-level state stays clean."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def clean_pause_gates():
    """Reset pause-gate registry between tests."""
    from app import pause_gate
    with pause_gate._gates_lock:
        pause_gate._gates.clear()
    yield
    with pause_gate._gates_lock:
        pause_gate._gates.clear()
