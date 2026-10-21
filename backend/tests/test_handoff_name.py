"""Item 5b: the extension is called HandOff in Chrome's list, its toolbar
button and its banner (spec §7, §15)."""

import html
import json
import re
import subprocess

import pytest

from tests.test_page_map_in_chrome import CHROME, REPO

EXTENSION = REPO / "extension"


def test_chrome_lists_the_extension_as_handoff():
    manifest = json.loads((EXTENSION / "manifest.json").read_text())
    assert manifest["name"] == "HandOff"
    assert manifest["action"]["default_title"] == "HandOff"
    assert "UDAA" not in manifest["description"] and " AI" not in manifest["description"]


@pytest.fixture(scope="module")
def banner():
    if CHROME is None:
        pytest.skip("Chrome not installed")
    # "login" in the address makes the secure-page badge appear.
    url = (EXTENSION / "tests" / "banner_fixture.html").as_uri() + "?page=login"
    dom = subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--allow-file-access-from-files",
         "--window-size=1200,800", "--virtual-time-budget=5000", "--dump-dom", url],
        capture_output=True, text=True, timeout=60,
    ).stdout
    match = re.search(r'<pre id="out">(.*?)</pre>', dom, re.S)
    assert match and match.group(1), "banner test did not run"
    return json.loads(html.unescape(match.group(1)))


def test_the_banner_shows_the_handoff_name_and_the_message(banner):
    assert banner["normal"] == {"name": "HandOff", "text": "Clicking 'Search'"}


def test_grandparents_mode_keeps_the_handoff_name(banner):
    assert banner["grandparents"]["name"] == "HandOff"


def test_the_secure_page_badge_names_handoff(banner):
    assert "HandOff" in banner["badge"] and "UDAA" not in banner["badge"]


def test_a_status_without_a_message_is_still_plain_words(banner):
    assert banner["noMessage"]["text"] == "Thinking about what to do next..."
