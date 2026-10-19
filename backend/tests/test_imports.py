"""The backend should import cleanly after the folder reshuffle."""

import importlib

import pytest

MODULES = [
    "app.main",
    "app.computer_use",
    "app.live_stream",
    "app.action_log",
    "app.browser.base",
    "app.browser.live_tab",
    "app.steps",
    "app.tools",
    "app.computer",
    "app.memory",
    "app.voice",
    "app.voice.narration",
    "app.steps.finish",
]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name):
    importlib.import_module(name)


def test_live_tab_is_a_browser_adapter():
    from app.browser.base import BrowserAdapter
    from app.browser.live_tab import LiveBrowserAdapter

    assert issubclass(LiveBrowserAdapter, BrowserAdapter)
