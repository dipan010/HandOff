"""H9: time and date questions are answered from the computer's clock:
no model call and no browser tab."""

from datetime import datetime

import pytest

from app.steps.sort import quick_rule, sort_request
from tests.fakes import FakeCaller

NOW = datetime(2026, 10, 21, 15, 45)


@pytest.mark.parametrize("question", ["what time is it?", "What's the time", "time now", "tell me the time please"])
def test_time_questions(question):
    answer = quick_rule(question, now=NOW)
    assert answer is not None and answer.kind == "chat"
    assert answer.reply == "It's 3:45 PM."


@pytest.mark.parametrize("question", ["what's the date today?", "what is today's date", "what day is it", "date today"])
def test_date_questions(question):
    answer = quick_rule(question, now=NOW)
    assert answer is not None and answer.reply == "Today is Wednesday, 21 October 2026."


@pytest.mark.parametrize("question", [
    "what time is the next train to Delhi", "what time is it in London", "book a table for today at 8",
    "what's the date of the next India match",
])
def test_other_questions_about_time_are_not_answered_from_the_clock(question):
    assert quick_rule(question, now=NOW) is None


async def test_no_model_call_for_the_clock():
    caller = FakeCaller()
    answer = await sort_request("what time is it", "", caller, "sort", "backup")
    assert answer.kind == "chat" and answer.reply.startswith("It's ")
    assert caller.calls == []
