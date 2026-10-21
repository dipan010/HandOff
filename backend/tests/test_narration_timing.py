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
    # The acknowledgement and where it's going, as one line, so speech for it starts at once.
    assert said_before and said_before[-1].endswith("Opening turing.ac.uk.")
    assert len(said_before[-1]) > len("Opening turing.ac.uk.")


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


# ── Live round part 2b: "HandOff has started by opening the website" came after
# the site was already open. Speech takes a second or two to start. ──────────

class SpeakingLive(FakeLiveSession):
    """Starts speaking (sends audio) a moment after it is told something."""

    def __init__(self, events, delay=0.2, speaks=True):
        super().__init__()
        self.events, self.delay, self.speaks = events, delay, speaks
        self.last_audio = 0.0

    async def send_client_content(self, turns):
        import asyncio
        import time
        self.spoken.append(turns.parts[0].text)
        if self.speaks:
            async def speak():
                await asyncio.sleep(self.delay)
                self.last_audio = time.time()
                self.events.append(("speaking", turns.parts[0].text))
            asyncio.create_task(speak())


async def test_the_tab_opens_once_the_narrator_has_started_speaking():
    events = []
    live = SpeakingLive(events)

    async def open_browser(url=""):
        events.append(("opened", url))

    caller = FakeCaller(actions=[action_reply(call=("task_complete", {"summary": "Open."}))])
    await run_task("s1", "open turing.ac.uk", "", FakePageBrowser([RESULTS_PAGE]), caller=caller, ui=FakeUI(),
                   cfg=cfg(), timing=NO_WAIT, live_session_ref=[live], last_action_time_ref=[0.0],
                   open_browser=open_browser)
    opened = events.index(("opened", "https://turing.ac.uk"))
    assert any(kind == "speaking" and text.endswith("Opening turing.ac.uk.") for kind, text in events[:opened])


async def test_a_narrator_that_never_speaks_holds_the_tab_back_only_briefly(monkeypatch):
    import time
    from app.steps import run as run_module
    monkeypatch.setattr(run_module, "NARRATOR_SPEECH_WAIT", 0.3)
    events = []
    live = SpeakingLive(events, speaks=False)

    async def open_browser(url=""):
        events.append(("opened", url))

    started = time.time()
    caller = FakeCaller(actions=[action_reply(call=("task_complete", {"summary": "Open."}))])
    await run_task("s1", "open turing.ac.uk", "", FakePageBrowser([RESULTS_PAGE]), caller=caller, ui=FakeUI(),
                   cfg=cfg(), timing=NO_WAIT, live_session_ref=[live], last_action_time_ref=[0.0],
                   open_browser=open_browser)
    assert ("opened", "https://turing.ac.uk") in events
    assert time.time() - started < 2.5


def test_about_to_lines_are_said_as_happening_now():
    for prompt in (NARRATION_PROMPT_DEFAULT, NARRATION_PROMPT_GRANDPARENTS):
        assert "say it as happening now" in prompt
