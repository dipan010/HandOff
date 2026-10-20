"""Runs extension/page_map.js in real headless Chrome (skipped if Chrome isn't installed)."""

import html
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "extension" / "tests" / "page_map_fixture.html"
CHROME_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    shutil.which("google-chrome") or "",
    shutil.which("chromium") or "",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
]
CHROME = next((p for p in CHROME_PATHS if p and Path(p).exists()), None)

pytestmark = pytest.mark.skipif(CHROME is None, reason="Chrome not installed")


@pytest.fixture(scope="module")
def result():
    dom = subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--allow-file-access-from-files",
         "--window-size=1200,800", "--dump-dom", FIXTURE.as_uri()],
        capture_output=True, text=True, timeout=60,
    ).stdout
    match = re.search(r'<pre id="out">(.*?)</pre>', dom, re.S)
    assert match, "page map did not run"
    return json.loads(html.unescape(match.group(1)))


def labels(result):
    return {e["label"]: e for e in result["map"]["elements"]}


def test_lists_visible_controls_with_labels(result):
    found = labels(result)
    assert found["From station"]["value"] == "Delhi"
    assert found["To station"]["role"] == "text box"
    assert found["Class"]["role"] == "dropdown" and found["Class"]["value"] == "AC 3 Tier"
    assert "checked" in found["Student fare"]["state"]
    assert "closed" in found["Menu"]["state"]
    assert found["Help"]["role"] == "link"


def test_link_text_is_not_listed_twice(result):
    assert sum(1 for e in result["map"]["elements"] if e["label"] == "Help") == 1


def test_secrets_never_leave_the_page(result):
    found = labels(result)
    assert found["Password"]["value"] == "(filled, hidden)"
    assert found["Card"]["value"] == "(filled, hidden)"
    assert "hunter2" not in json.dumps(result)
    assert "4111111111111111" not in json.dumps(result)


def test_hidden_covered_and_offscreen_are_left_out(result):
    found = labels(result)
    assert "Invisible" not in found
    assert "Covered button" not in found       # under the cookie banner
    assert "Accept cookies" in found
    assert "Far below" not in found
    assert result["map"]["hidden_below"] >= 1


def test_ids_are_unique_numbers(result):
    ids = [e["id"] for e in result["map"]["elements"]]
    assert len(ids) == len(set(ids)) and all(isinstance(i, int) for i in ids)


def test_read_text_gives_main_content(result):
    text = result["text"]["text"]
    assert text.startswith("Book a train")
    assert "Trains run daily." in text


ACTIONS_FIXTURE = REPO / "extension" / "tests" / "actions_fixture.html"


@pytest.fixture(scope="module")
def actions():
    dom = subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--allow-file-access-from-files",
         "--window-size=1200,800", "--virtual-time-budget=5000", "--dump-dom", ACTIONS_FIXTURE.as_uri()],
        capture_output=True, text=True, timeout=60,
    ).stdout
    match = re.search(r'<pre id="out">(.*?)</pre>', dom, re.S)
    assert match and match.group(1), "actions did not run"
    return json.loads(html.unescape(match.group(1)))


def test_actions_by_element_number_change_the_page(actions):
    state = actions["state"]
    assert state["to"] == "Mumbai"
    assert state["cls"] == "Sleeper"
    assert state["student"] is False
    assert state["clicked"] == "yes"
    assert state["city"] == "Pune"
    assert state["from"] == "Kolkata, India"     # typed, then picked the suggestion
    assert state["userInputReports"] == 0         # HandOff's own clicks never count as the user


def test_action_replies(actions):
    results = actions["results"]
    assert results["type"] is True
    assert results["select"] == {"success": True, "chosen": "Sleeper"}
    assert results["custom"]["success"] is True
    assert results["stale"]["success"] is False and results["stale"]["stale"] is True
    assert results["map"]["success"] is True and results["map"]["page"]["elements"]


def run_fixture(name: str) -> dict:
    dom = subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--allow-file-access-from-files",
         "--window-size=1200,800", "--dump-dom", (REPO / "extension" / "tests" / name).as_uri()],
        capture_output=True, text=True, timeout=60,
    ).stdout
    match = re.search(r'<pre id="out">(.*?)</pre>', dom, re.S)
    assert match and match.group(1), f"{name} did not run"
    return json.loads(html.unescape(match.group(1)))


def test_search_results_skip_ads_and_unwrap_redirects():
    results = run_fixture("search_fixture.html")["results"]
    assert [r["url"] for r in results] == [
        "https://en.m.wikipedia.org/wiki/Alan_Turing",
        "https://www.britannica.com/biography/Alan-Turing",
        "https://www.turing.ac.uk/",
        "https://www.google.com/goto?url=CAESZAHrOzAV574Okl2f",
    ]
    assert results[0]["title"] == "Alan Turing - Wikipedia"
    assert "English mathematician" in results[0]["snippet"]


def test_secret_fields_are_marked(result):
    found = labels(result)
    assert found["Password"]["secret"] is True and found["Card"]["secret"] is True
    assert "secret" not in found["From station"]


def test_tables_and_repeated_blocks_are_pulled_out():
    found = run_fixture("list_fixture.html")
    assert len(found["tables"]) == 1                     # the hidden one is skipped
    table = found["tables"][0]
    assert table["caption"] == "Trains from Howrah to Delhi"
    assert table["header"] == ["Train", "Leaves", "Fare"]
    assert table["rows"][1] == ["Poorva Express", "08:05", "₹1,450"]
    items = found["lists"][0]["items"]
    assert len(items) == 4
    assert items[1]["text"] == "JBL Go 3 speaker · ₹2,999 · 4.4 stars"
    assert items[1]["link"] == "https://shop.example.com/p/2"
    assert not any("Home page link" in i["text"] for lst in found["lists"] for i in lst["items"])   # menus left out
