"""F1 (live round, 2026-10-21): narration ran behind the actions, and said the
MakeMyTrip homepage was open while HandOff was still on Google."""

from app.live_stream import NARRATION_PROMPT_DEFAULT, NARRATION_PROMPT_GRANDPARENTS, opening_line
from app.steps.run import run_task
from app.voice import narration
from tests.fakes import FakeCaller, FakeLiveSession, FakePageBrowser, FakeUI, action_reply
from tests.test_page_step import NO_WAIT, PLAYING_PAGE, RESULTS_PAGE, SEARCH_PAGE, cfg


async def test_each_action_is_narrated_as_it_starts_not_after_it_finishes(monkeypatch):
    monkeypatch.setattr(narration, "_last_narration_inject_time", 0.0)
    events = []

    class Live(FakeLiveSession):
        async def send_client_content(self, turns):
            events.append(("said", turns.parts[0].text))

    class Browser(FakePageBrowser):
        async def execute_action(self, name, args):
            if name == "click_element":
                events.append(("clicked", name))
            return await super().execute_action(name, args)

    caller = FakeCaller(actions=[
        action_reply(call=("click", {"element_id": 1})),
        action_reply(call=("task_complete", {"summary": "Playing."})),
    ])
    await run_task("s1", "play lofi on youtube", "", Browser([RESULTS_PAGE, PLAYING_PAGE]), caller=caller,
                   ui=FakeUI(), cfg=cfg(), timing=NO_WAIT, live_session_ref=[Live()], last_action_time_ref=[0.0])
    said = next(i for i, e in enumerate(events) if e[0] == "said" and "click" in e[1].lower())
    clicked = events.index(("clicked", "click_element"))
    assert said < clicked


def test_the_narrator_only_says_what_has_happened():
    for prompt in (NARRATION_PROMPT_DEFAULT, NARRATION_PROMPT_GRANDPARENTS):
        assert "what will happen next" not in prompt
        assert "Never say a page is open or something is done until" in prompt


def test_the_narrator_is_told_nothing_has_happened_yet():
    line = opening_line("on makemytrip, fill in a flight from Delhi to Mumbai")
    assert "on makemytrip, fill in a flight from Delhi to Mumbai" in line
    assert "Nothing has been done yet" in line


# ── Live round part 2: the tab opened and a cookie notice closed before the
# narrator said anything. ─────────────────────────────────────────────────────

async def test_the_narrator_speaks_before_the_tab_opens():
    events, ref = [], [None]

    class Live(FakeLiveSession):
        async def send_client_content(self, turns):
            events.append(("said", turns.parts[0].text))

    def start_narration():
        ref[0] = Live()

    async def open_browser(url=""):
        events.append(("opened", url))

    caller = FakeCaller(actions=[action_reply(call=("task_complete", {"summary": "Open."}))])
    await run_task("s1", "open turing.ac.uk", "", FakePageBrowser([RESULTS_PAGE]), caller=caller, ui=FakeUI(),
                   cfg=cfg(), timing=NO_WAIT, live_session_ref=ref, last_action_time_ref=[0.0],
                   open_browser=open_browser, start_narration=start_narration)
    opened = events.index(("opened", "https://turing.ac.uk"))
    said_before = [text for kind, text in events[:opened] if kind == "said"]
    assert len(said_before) >= 2                                  # the acknowledgement, then where it's going
    assert "turing.ac.uk" in said_before[-1] and said_before[-1].startswith("Opening")


async def test_closing_a_cookie_notice_is_narrated_first():
    from tests.test_cookie_notices import TURING, TURING_CLEAR, Consent
    events = []

    class Live(FakeLiveSession):
        async def send_client_content(self, turns):
            events.append(("said", turns.parts[0].text))

    class Watched(Consent):
        async def execute_action(self, name, args):
            if name == "click_element":
                events.append(("clicked", args.get("element_id")))
            return await super().execute_action(name, args)

    caller = FakeCaller(actions=[action_reply(call=("task_complete", {"summary": "Open."}))])
    await run_task("s1", "open turing.ac.uk", "", Watched([TURING, TURING_CLEAR]), caller=caller, ui=FakeUI(),
                   cfg=cfg(), timing=NO_WAIT, live_session_ref=[Live()], last_action_time_ref=[0.0])
    clicked = events.index(("clicked", 3))
    assert any(kind == "said" and "cookie" in text.lower() for kind, text in events[:clicked])
