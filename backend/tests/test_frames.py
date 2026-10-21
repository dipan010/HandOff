"""H5: forms and buttons inside frames. The merging code runs in the extension;
it is tested here with Node, and the page reader in real headless Chrome."""

import shutil
import subprocess
from pathlib import Path

import pytest

from app.browser.page_view import page_view_text

REPO = Path(__file__).resolve().parents[2]
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="Node not installed")
def test_frame_maps_are_merged_and_numbered():
    out = subprocess.run([NODE, str(REPO / "extension" / "tests" / "frames_test.js")],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert "frames ok" in out.stdout


def test_page_view_says_what_it_cannot_read():
    text = page_view_text({"url": "https://shop.example.com/pay", "title": "Pay", "elements": [],
                           "unreadable_frames": ["ads.example.net"], "payment_frames": ["js.stripe.com"]})
    assert "A payment form from js.stripe.com is on this page" in text
    assert "Part of this page (from ads.example.net) can't be read" in text


def test_frame_elements_show_where_they_are():
    text = page_view_text({"url": "https://shop.example.com/", "title": "Shop", "elements": [
        {"id": 100004, "role": "text box", "label": "Email", "frame": "forms.example.com"}]})
    assert '[100004] text box "Email" (in a frame from forms.example.com)' in text


CHROME = next((p for p in ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                           shutil.which("google-chrome") or "", shutil.which("chromium") or ""]
               if p and Path(p).exists()), None)


@pytest.mark.skipif(CHROME is None, reason="Chrome not installed")
def test_frames_are_listed_and_read_in_real_chrome(tmp_path):
    import functools
    import html
    import http.server
    import json
    import re
    import threading

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(REPO / "extension"))
    handler.log_message = lambda *a: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        # Parent on 127.0.0.1, frame on localhost: a different origin, like a real embedded form.
        frame_url = f"http://localhost:{port}/tests/frame_child_fixture.html"
        parent = (REPO / "extension" / "tests" / "frame_parent_fixture.html").read_text().replace("FRAME_URL", frame_url)
        (REPO / "extension" / "tests" / "_frame_parent.html").write_text(parent)
        dom = subprocess.run(
            # One process for both origins: --virtual-time-budget doesn't wait for work in a
            # separate frame process, so the page could be saved before the frame answered.
            # The origin rules between page and frame still apply.
            [CHROME, "--headless=new", "--disable-gpu", "--window-size=1200,800", "--virtual-time-budget=5000",
             "--disable-site-isolation-trials", "--disable-features=IsolateOrigins,site-per-process",
             "--dump-dom", f"http://127.0.0.1:{port}/tests/_frame_parent.html"],
            capture_output=True, text=True, timeout=60).stdout
    finally:
        server.shutdown()
        (REPO / "extension" / "tests" / "_frame_parent.html").unlink(missing_ok=True)
    match = re.search(r'<pre id="out">(.*?)</pre>', dom, re.S)
    assert match and match.group(1), "frame test did not run"
    found = json.loads(html.unescape(match.group(1)))
    assert [f["src"] for f in found["top"]["frames"]] == [frame_url]      # the 1x1 frame is left out
    assert {e["label"] for e in found["frame"]["elements"]} == {"Guest name", "Book now"}
    assert "frames" not in found["frame"] and not found["frame"].get("payment_frame")
