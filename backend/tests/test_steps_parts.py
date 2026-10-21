import pytest
from google.genai import types

from app.steps import model_call
from app.steps.check import ScreenState, changed, is_step_done
from app.steps.plan import Step, make_plan, revise_plan
from app.steps.run import find_marker, trim_screenshots
from app.steps.sort import quick_rule, sort_request
from tests.fakes import FakeCaller


# ── sorting ──────────────────────────────────────────────────────────────

def test_greetings_need_no_model():
    assert quick_rule("hi").kind == "chat"
    assert quick_rule("Thank you!").reply.startswith("You're welcome")
    assert quick_rule("hi, open youtube") is None


async def test_chat_request_gets_reply():
    caller = FakeCaller(sort=[{"kind": "chat", "effort": "quick", "reply": "Paris."}])
    result = await sort_request("capital of France?", "", caller, "sorter", "backup")
    assert (result.kind, result.reply) == ("chat", "Paris.")


async def test_start_page_always_means_task():
    caller = FakeCaller(sort=[{"kind": "chat", "effort": "quick", "reply": "Hi"}])
    result = await sort_request("what is this page about", "https://x.com", caller, "sorter", "backup")
    assert result.kind == "task"


async def test_sorting_failure_falls_back_to_hard_task():
    caller = FakeCaller(fail_models={"sorter", "backup"})
    result = await sort_request("book a train", "", caller, "sorter", "backup")
    assert (result.kind, result.effort) == ("task", "hard")


async def test_backup_model_used_when_first_fails():
    caller = FakeCaller(sort=[{"kind": "task", "effort": "quick", "reply": None}], fail_models={"sorter"})
    result = await sort_request("open youtube", "", caller, "sorter", "backup")
    assert result.effort == "quick"
    assert caller.calls == [("sort", "backup")]


# ── planning ─────────────────────────────────────────────────────────────

async def test_plan_is_numbered():
    caller = FakeCaller(plan=[{"steps": [
        {"title": "Open YouTube", "done_when": "YouTube home is shown"},
        {"title": "Search lofi", "done_when": "Results for lofi"},
    ]}])
    steps = await make_plan("play lofi", "", caller, "fast", "backup")
    assert [s.number for s in steps] == [1, 2]
    assert steps[1].done_when == "Results for lofi"


async def test_plan_failure_gives_single_step():
    steps = await make_plan("play lofi", "", FakeCaller(fail_models={"fast", "backup"}), "fast", "backup")
    assert len(steps) == 1 and steps[0].title == "play lofi"


async def test_revised_steps_continue_numbering():
    caller = FakeCaller(revise=[{"steps": [{"title": "Try the menu", "done_when": "Menu open"}]}])
    finished = [Step(1, "a", "a"), Step(2, "b", "b")]
    new = await revise_plan("t", finished, Step(3, "c", "c"), "button missing", "u", caller, "fast", "backup")
    assert [s.number for s in new] == [3]


# ── checking ─────────────────────────────────────────────────────────────

def test_changed_detects_page_and_screen_changes():
    a = ScreenState.of("https://a", b"1")
    assert changed(a, ScreenState.of("https://b", b"1"), [{}], ["click_at"]).ok
    assert changed(a, ScreenState.of("https://a", b"2"), [{}], ["click_at"]).ok
    assert not changed(a, ScreenState.of("https://a", b"1"), [{}], ["click_at"]).ok
    assert changed(a, a, [{}], ["wait_5_seconds"]).ok


def test_changed_reports_extension_failure():
    a = ScreenState.of("https://a", b"1")
    result = changed(a, ScreenState.of("https://b", b"2"),
                     [{"action": "click_at", "success": False, "detail": "no element"}], ["click_at"])
    assert not result.ok and "no element" in result.reason


async def test_step_check_reads_answer():
    caller = FakeCaller(check=[{"done": False, "reason": "Still on search page"}])
    result = await is_step_done("t", Step(1, "a", "b"), b"png", "u", caller, "fast", "backup")
    assert (result.ok, result.reason) == (False, "Still on search page")


async def test_step_check_failure_accepts_step():
    caller = FakeCaller(fail_models={"fast", "backup"})
    result = await is_step_done("t", Step(1, "a", "b"), b"png", "u", caller, "fast", "backup")
    assert result.ok


# ── small helpers ────────────────────────────────────────────────────────

def test_parse_json_handles_fences_and_prose():
    assert model_call.parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert model_call.parse_json('Sure! {"a": 2} hope that helps') == {"a": 2}


def test_plain_error_messages():
    assert "busy" in model_call.plain_error(Exception("503 UNAVAILABLE"))
    assert "API key" in model_call.plain_error(Exception("403 PERMISSION_DENIED"))


def test_find_marker():
    assert find_marker("STEP DONE: results shown") == ("step", "results shown")
    assert find_marker("ok. Task complete: booked") == ("task", "booked")
    assert find_marker("clicking the button") is None


def test_trim_screenshots_keeps_newest():
    def img():
        return types.Content(role="user", parts=[types.Part(inline_data=types.Blob(mime_type="image/png", data=b"x"))])
    contents = [types.Content(role="user", parts=[types.Part(text="start")]), img(), img(), img(), img()]
    trimmed = trim_screenshots(contents, keep=2)
    images = [c for c in trimmed if any(p.inline_data for p in c.parts)]
    assert len(images) == 2
    assert trimmed[1].parts[0].text == "[older screenshot removed]"
    assert trimmed[0].parts[0].text == "start"


async def test_live_facts_are_never_answered_from_memory():
    caller = FakeCaller(sort=[{"kind": "chat", "effort": "quick", "reply": "It's sunny and 28°C."}])
    for question in ["What's the weather in Bangalore today?", "when is the next train to Mumbai",
                     "price of an iPhone 16", "any new emails in my inbox?"]:
        result = await sort_request(question, "", caller, "sorter", "backup")
        assert result.kind == "task", question


async def test_general_knowledge_can_still_be_chat():
    caller = FakeCaller(sort=[{"kind": "chat", "effort": "quick", "reply": "Paris."}])
    result = await sort_request("What is the capital of France?", "", caller, "sorter", "backup")
    assert result.kind == "chat"


async def test_no_credit_is_not_retried_or_sent_to_backup():
    from app.steps.model_call import ask_with_backup, is_busy_error

    class Broke:
        def __init__(self):
            self.models = []

        async def ask(self, model, contents, config=None):
            self.models.append(model)
            raise RuntimeError("402 RESOURCE_EXHAUSTED. Your prepayment credits are depleted.")

    caller = Broke()
    with pytest.raises(RuntimeError):
        await ask_with_backup(caller, "fast", "backup", "hi")
    assert caller.models == ["fast"]
    assert not is_busy_error(RuntimeError("402 RESOURCE_EXHAUSTED prepayment"))
    assert is_busy_error(RuntimeError("429 RESOURCE_EXHAUSTED"))


async def test_plans_fill_a_form_in_one_step_not_one_step_per_click():
    # Live round, 2026-10-21: "fill in a flight from Delhi to Mumbai" was split
    # into a step per click and suggestion, and never finished.
    from tests.fakes import _prompt_text
    prompts = []
    caller = FakeCaller(plan=[{"steps": [{"title": "Fill in the flight", "done_when": "From and To are filled"}]}])
    original = caller.ask

    async def spy(model, contents, config=None):
        prompts.append(_prompt_text(contents))
        return await original(model, contents, config)

    caller.ask = spy
    await make_plan("on makemytrip, fill in a flight from Delhi to Mumbai", "", caller, "fast", "backup")
    await revise_plan("fill in a flight", [], Step(1, "a", "b"), "stuck", "https://x", caller, "fast", "backup")
    for prompt in prompts:
        assert "Fill a whole form in one step" in prompt
        assert "never one step per click" in prompt
