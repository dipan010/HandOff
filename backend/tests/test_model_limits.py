"""Gemini limits: a used-up model is skipped until the daily reset, waits are shown, and
a task stops at once with a plain message when no model has requests left."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.steps import model_call
from app.steps.model_call import (DailyLimitReached, GeminiCaller, ask_with_backup, busy, next_daily_reset,
                                  plain_error, used_up)

DAILY = RuntimeError("429 RESOURCE_EXHAUSTED. {'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'}")
PER_MINUTE = RuntimeError("429 RESOURCE_EXHAUSTED. Too many requests per minute")
OVERLOADED = RuntimeError("503 UNAVAILABLE. This model is currently experiencing high demand.")


@pytest.fixture(autouse=True)
def fresh_limits(monkeypatch):
    used_up.clear()
    busy.clear()
    monkeypatch.setattr(model_call, "BUSY_RETRY_WAIT", 0)
    yield
    used_up.clear()
    busy.clear()


class FakeModels:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def generate_content(self, model, contents, config=None):
        self.calls.append(model)
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def caller_with(models: FakeModels, **kwargs) -> GeminiCaller:
    caller = GeminiCaller("test-key", **kwargs)
    caller._client = SimpleNamespace(models=models)
    return caller


def test_daily_limits_reset_at_midnight_pacific():
    # 02:00 UTC on 21 Oct is 19:00 on 20 Oct in California; the reset is 07:00 UTC on 21 Oct.
    reset = next_daily_reset(datetime(2026, 10, 21, 2, 0, tzinfo=timezone.utc))
    assert reset.astimezone(timezone.utc) == datetime(2026, 10, 21, 7, 0, tzinfo=timezone.utc)


def test_a_used_up_model_comes_back_after_the_reset():
    before = datetime(2026, 10, 21, 2, 0, tzinfo=timezone.utc)
    used_up.mark("fast", now=before)
    assert used_up.is_used_up("fast", now=before)
    assert not used_up.is_used_up("fast", now=datetime(2026, 10, 21, 7, 1, tzinfo=timezone.utc))


async def test_a_used_up_model_is_not_asked_again():
    models = FakeModels(DAILY)
    caller = caller_with(models)
    with pytest.raises(DailyLimitReached):
        await caller.ask("fast", "hi")
    with pytest.raises(DailyLimitReached):
        await caller.ask("fast", "hi again")
    assert models.calls == ["fast"]          # the second ask never reached Gemini


async def test_backup_answers_straight_away_when_the_main_model_is_used_up():
    used_up.mark("fast")
    models = FakeModels("backup answer")
    caller = caller_with(models)
    assert await ask_with_backup(caller, "fast", "backup", "hi") == "backup answer"
    assert models.calls == ["backup"]


async def test_waits_are_announced():
    waits = []

    async def on_wait(seconds):
        waits.append(seconds)

    models = FakeModels(PER_MINUTE, "ok")
    caller = caller_with(models, retry_delays=(0,), on_wait=on_wait)
    assert await caller.ask("fast", "hi") == "ok"
    assert waits == [0]


def test_used_up_message_says_when_to_try_again():
    message = plain_error(DailyLimitReached("fast"))
    assert message.startswith("I've used today's free Gemini requests. Try again after ")
    assert "ai.studio/projects" in message


async def test_task_stops_at_once_when_every_model_is_used_up(monkeypatch):
    from tests.fakes import FakeCaller, FakePageBrowser, page
    from tests.test_page_step import NO_WAIT, cfg, sent
    from app.steps import run as run_module
    from tests.fakes import FakeUI

    async def nothing(*a, **k):
        return None

    monkeypatch.setattr(run_module, "update_session_state", nothing)
    for name in ("fast", "strong", "backup"):
        used_up.mark(name)
    opened = []

    async def open_browser(url=""):
        opened.append(True)

    browser = FakePageBrowser([page("about:blank")])
    caller = FakeCaller()
    ui = FakeUI()
    await run_module.run_task("s1", "find train times to Delhi", "", browser, caller=caller, ui=ui,
                              cfg=cfg(), timing=NO_WAIT, open_browser=open_browser)
    assert [args[0] for args in sent(ui, "send_error")][0].startswith("I've used today's free Gemini requests")
    assert opened == [] and browser.actions == []
    assert caller.count("plan") == 0 and caller.count("action") == 0


class SlowModels(FakeModels):
    """Hangs on the models named in `slow` (in a worker thread, like the real client)."""

    def __init__(self, slow, answer="ok"):
        super().__init__(answer)
        self.slow = set(slow)

    def generate_content(self, model, contents, config=None):
        import time
        self.calls.append(model)
        if model in self.slow:
            time.sleep(0.3)
        return "late" if model in self.slow else self.outcomes[0]


async def test_a_hanging_call_times_out_instead_of_waiting_forever():
    from app.steps.model_call import ModelTimeout
    models = SlowModels(slow={"fast"})
    caller = caller_with(models, retry_delays=(0,), timeout=0.05)
    with pytest.raises(ModelTimeout):
        await caller.ask("fast", "hi")
    assert models.calls == ["fast", "fast"]       # tried again once, then gave up


async def test_the_backup_answers_when_the_main_model_hangs():
    models = SlowModels(slow={"fast"}, answer="backup answer")
    caller = caller_with(models, retry_delays=(), timeout=0.05)
    assert await ask_with_backup(caller, "fast", "backup", "hi") == "backup answer"


def test_timeouts_have_a_plain_message():
    from app.steps.model_call import ModelTimeout
    assert plain_error(ModelTimeout("fast")) == "Gemini took too long to answer. Please try again in a moment."



# ── F2 (live round, 2026-10-21): "busy" answers seem to count towards the daily
# limit, so a busy model isn't asked again and again. ─────────────────────────

async def test_a_busy_model_is_not_retried_the_backup_answers_at_once():
    models = FakeModels(OVERLOADED, "backup answer")
    assert await ask_with_backup(caller_with(models), "fast", "backup", "hi") == "backup answer"
    assert models.calls == ["fast", "backup"]


async def test_a_model_that_was_just_busy_is_skipped_for_a_minute():
    models = FakeModels(OVERLOADED, "backup answer")
    caller = caller_with(models)
    await ask_with_backup(caller, "fast", "backup", "hi")
    await ask_with_backup(caller, "fast", "backup", "hi again")
    assert models.calls == ["fast", "backup", "backup"]


def test_a_busy_model_is_tried_again_after_the_minute():
    now = datetime(2026, 10, 21, 9, 0, tzinfo=timezone.utc)
    busy.mark("fast", now=now)
    assert busy.is_busy("fast", now=now)
    assert not busy.is_busy("fast", now=datetime(2026, 10, 21, 9, 1, 1, tzinfo=timezone.utc))


async def test_when_both_models_are_busy_wait_once_then_try_the_main_one_again():
    waits = []

    async def on_wait(seconds):
        waits.append(seconds)

    models = FakeModels(OVERLOADED, OVERLOADED, "ok")
    assert await ask_with_backup(caller_with(models, on_wait=on_wait), "fast", "backup", "hi") == "ok"
    assert models.calls == ["fast", "backup", "fast"]
    assert len(waits) == 1


async def test_a_busy_model_with_no_backup_is_tried_once_more_after_a_wait():
    models = FakeModels(OVERLOADED, "ok")
    assert await ask_with_backup(caller_with(models), "fast", None, "hi") == "ok"
    assert models.calls == ["fast", "fast"]


# ── F3 (live round, 2026-10-21): a minute's wait with one unchanging message
# looked like HandOff was stuck. ─────────────────────────────────────────────

async def test_a_long_wait_counts_down_so_it_doesnt_look_stuck(monkeypatch):
    waits, slept = [], []

    async def on_wait(seconds):
        waits.append(seconds)

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(model_call.asyncio, "sleep", fake_sleep)
    models = FakeModels(PER_MINUTE, "ok")
    caller = caller_with(models, retry_delays=(25,), on_wait=on_wait)
    assert await caller.ask("fast", "hi") == "ok"
    assert waits == [25, 15, 5]
    assert sum(slept) == 25


async def test_the_banner_says_how_long_is_left(monkeypatch):
    from app.steps.run import run_task
    from tests.fakes import FakeUI
    from tests.test_page_step import NO_WAIT, cfg

    caller = GeminiCaller("test-key")
    caller._client = SimpleNamespace(models=FakeModels(RuntimeError("boom")))
    ui = FakeUI()

    async def fake_sort(*a, **k):
        await caller.on_wait(40)
        raise RuntimeError("stop here")

    monkeypatch.setattr("app.steps.run.sort_request", fake_sort)
    with pytest.raises(RuntimeError):
        await run_task("s1", "hello", "", None, caller=caller, ui=ui, cfg=cfg(), timing=NO_WAIT)
    statuses = [args for name, args, _ in ui.sent if name == "send_status"]
    assert ("waiting", "Waiting for Gemini: 40 s left...") in [(s[0], s[1]) for s in statuses]


async def test_a_busy_main_model_is_tried_again_when_the_backup_is_used_up():
    used_up.mark("backup")
    models = FakeModels(OVERLOADED, "ok")
    assert await ask_with_backup(caller_with(models), "fast", "backup", "hi") == "ok"
    assert models.calls == ["fast", "fast"]


async def test_a_backup_that_runs_out_while_the_main_model_is_busy_doesnt_end_the_task():
    models = FakeModels(OVERLOADED, DAILY, "ok")
    assert await ask_with_backup(caller_with(models), "fast", "backup", "hi") == "ok"
    assert models.calls == ["fast", "backup", "fast"]
