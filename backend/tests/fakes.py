"""Small stand-ins for the dashboard connection and the narration session."""


class FakeUI:
    """Records every message the backend would send to the dashboard or extension."""

    def __init__(self):
        self.sent = []

    def __getattr__(self, name):
        if not name.startswith("send") and not name.startswith("broadcast"):
            raise AttributeError(name)

        async def record(session_id, *args, **kwargs):
            self.sent.append((name, args, kwargs))

        return record

    def names(self):
        return [n for n, _, _ in self.sent]


class FakeLiveSession:
    def __init__(self):
        self.spoken = []

    async def send_client_content(self, turns):
        self.spoken.append(turns.parts[0].text)


# ── Gemini and browser stand-ins for the step tests ─────────────────────────

import json as _json
from types import SimpleNamespace

from google.genai import types as _types


def _prompt_text(contents) -> str:
    if isinstance(contents, str):
        return contents
    texts = []
    for c in contents if isinstance(contents, list) else [contents]:
        for p in getattr(c, "parts", None) or []:
            if getattr(p, "text", None):
                texts.append(p.text)
    return "\n".join(texts)


def action_reply(text: str | None = None, call: tuple[str, dict] | None = None):
    """What the Computer Use model would send back."""
    parts = []
    if text:
        parts.append(_types.Part(text=text))
    if call:
        parts.append(_types.Part(function_call=_types.FunctionCall(name=call[0], args=call[1])))
    return SimpleNamespace(candidates=[SimpleNamespace(content=_types.Content(role="model", parts=parts))])


class FakeCaller:
    """Answers each kind of Gemini call from its own queue of canned replies.

    sort / plan / revise / check replies are dicts (sent back as JSON text);
    action replies come from `action_reply()`. When a queue has one item left
    it is reused, so "always answer X" is a one-item list.
    """

    def __init__(self, sort=None, plan=None, revise=None, check=None, actions=None, fail_models=()):
        self.queues = {
            "sort": list(sort or [{"kind": "task", "effort": "quick", "reply": None}]),
            "plan": list(plan or [{"steps": [{"title": "Do it", "done_when": "It is done"}]}]),
            "revise": list(revise or [{"steps": []}]),
            "check": list(check or [{"done": True, "reason": "Looks done"}]),
            "action": list(actions or [action_reply("TASK COMPLETE: done")]),
        }
        self.fail_models = set(fail_models)
        self.calls = []

    def _next(self, kind):
        queue = self.queues[kind]
        return queue.pop(0) if len(queue) > 1 else queue[0]

    async def ask(self, model, contents, config=None):
        if model in self.fail_models:
            raise RuntimeError(f"{model} is down")
        if config is not None and getattr(config, "tools", None):
            self.calls.append(("action", model))
            reply = self._next("action")
            if isinstance(reply, Exception):
                raise reply
            return reply
        text = _prompt_text(contents)
        if "You sort requests" in text:
            kind = "sort"
        elif "could not be finished" in text:
            kind = "revise"
        elif "You plan browser tasks" in text:
            kind = "plan"
        elif "You check the work" in text:
            kind = "check"
        else:
            raise AssertionError(f"Unexpected prompt: {text[:80]}")
        self.calls.append((kind, model))
        return SimpleNamespace(text=_json.dumps(self._next(kind)))

    def count(self, kind):
        return sum(1 for k, _ in self.calls if k == kind)


class FakeBrowser:
    """A tab whose screen changes after every action unless `frozen` is set."""

    def __init__(self, url="https://example.com", frozen=False, fail_actions=False):
        self.current_url = url
        self.frozen = frozen
        self.fail_actions = fail_actions
        self.actions = []
        self._frame = 0

    @property
    def page(self):
        return None

    async def get_current_url(self):
        return self.current_url

    async def capture_screenshot(self, min_timestamp: float = 0) -> bytes:
        return f"frame-{self._frame}".encode()

    async def execute_action(self, name, args):
        self.actions.append((name, args))
        if not self.frozen:
            self._frame += 1
        if self.fail_actions:
            return {"action": name, "success": False, "detail": "element not found"}
        return {"action": name, "success": True}

    async def close(self):
        pass


def page(url: str, *items, below: int = 0) -> dict:
    """A page map like extension/page_map.js returns. Items are (role, label[, value[, state]])."""
    elements = []
    for i, item in enumerate(items, start=1):
        role, label = item[0], item[1]
        value = item[2] if len(item) > 2 else ""
        state = item[3] if len(item) > 3 else []
        elements.append({"id": i, "role": role, "label": label, "value": value, "state": state, "box": [0, 0, 10, 10]})
    return {"url": url, "title": url, "elements": elements, "hidden_below": below,
            "scroll": {"y": 0, "max": 0}, "dialog_open": False}


def calls_reply(*calls):
    """A model answer with several tool calls in one turn."""
    parts = [_types.Part(function_call=_types.FunctionCall(name=n, args=a)) for n, a in calls]
    return SimpleNamespace(candidates=[SimpleNamespace(content=_types.Content(role="model", parts=parts))])


class FakePageBrowser(FakeBrowser):
    """Serves page maps from a list; each real action moves to the next page.

    `replies` lets a test make specific actions fail, e.g. {"click_element": {...}}.
    """

    LOOK_ONLY = {"page_map", "read_text", "get_current_url", "search_results"}

    def __init__(self, pages, text="Some page text.", frozen=False, replies=None, results=None):
        super().__init__(url=pages[0]["url"], frozen=frozen)
        self.pages = pages
        self.text = text
        self.results = results or []   # what search_results finds on a results page
        self.replies = replies or {}
        self.index = 0

    @property
    def current(self):
        return self.pages[min(self.index, len(self.pages) - 1)]

    async def get_current_url(self):
        return self.current["url"]

    async def execute_action(self, name, args):
        if name == "page_map":
            return {"success": True, "page": self.current}
        if name == "read_text":
            return {"success": True, "text": self.text, "url": self.current["url"]}
        if name == "get_current_url":
            return {"success": True, "url": self.current["url"]}
        if name == "search_results":
            return {"success": True, "url": self.current["url"], "results": self.results}
        self.actions.append((name, args))
        if name in self.replies:
            return self.replies[name]
        if not self.frozen:
            self.index += 1
            self._frame += 1
        return {"success": True, "action": name}
