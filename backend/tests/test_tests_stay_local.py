"""Tests must not write to HandOff's real files (actions.log, screenshots, session state)."""

from pathlib import Path

from app.steps.run import run_task
from tests.fakes import FakeCaller, FakePageBrowser, FakeUI, action_reply
from tests.test_page_step import NO_WAIT, SEARCH_PAGE, cfg

ACTIONS_LOG = Path(__file__).resolve().parents[1] / "actions.log"


async def test_a_task_run_in_a_test_leaves_the_real_action_log_alone():
    before = ACTIONS_LOG.read_bytes() if ACTIONS_LOG.exists() else b""
    caller = FakeCaller(actions=[action_reply(call=("click", {"element_id": 2})),
                                 action_reply(call=("task_complete", {"summary": "Done."}))])
    await run_task("s1", "search youtube", "", FakePageBrowser([SEARCH_PAGE, SEARCH_PAGE]), caller=caller,
                   ui=FakeUI(), cfg=cfg(), timing=NO_WAIT)
    after = ACTIONS_LOG.read_bytes() if ACTIONS_LOG.exists() else b""
    assert after == before
