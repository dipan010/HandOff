"""Browser actions the model can call, and how each one is carried out.

Every tool works on the element numbers from the page map, except `click_at`,
which is the screenshot fallback for things the page map can't see.
"""

import asyncio
import re
from dataclasses import dataclass
from typing import Any

from google.genai import types

from app.browser.base import BrowserAdapter
from app.browser.page_view import element_by_id, find_field
from app.tools.web_rules import route, search_url


@dataclass
class ToolResult:
    ok: bool
    message: str                 # sent back to the model as the tool's answer
    ends: str | None = None      # "step" or "task" when the model says it's finished
    summary: str = ""
    is_action: bool = True       # False for tools that only look (read_page, look_at_screen)
    wants_screenshot: bool = False
    stale: bool = False          # the element number no longer exists
    data: Any = None


def _int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _schema(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties, "required": required or []}


ELEMENT = {"type": "integer", "description": "The element's number from the page view, e.g. 12 for [12]."}

DECLARATIONS = {
    "click": ("Click a button, link, tab or other item by its number.",
              _schema({"element_id": ELEMENT}, ["element_id"])),
    "type_text": ("Type into a text box by its number. Replaces what is there. Set submit to true to press Enter afterwards (e.g. to search).",
                  _schema({"element_id": ELEMENT, "text": {"type": "string"},
                           "submit": {"type": "boolean"}}, ["element_id", "text"])),
    "choose_option": ("Pick an item from a dropdown, city picker, date list or suggestion list by its visible text. Give the dropdown's number if it isn't open yet.",
                      _schema({"text": {"type": "string"}, "element_id": ELEMENT}, ["text"])),
    "fill_form": ("Fill several boxes of a form at once, matched by their labels. Text boxes are typed into, dropdowns "
                  "are chosen from, checkboxes are ticked for yes. It never presses the form's submit button: click that yourself.",
                  _schema({"fields": {"type": "array", "items": _schema(
                      {"label": {"type": "string", "description": "The box's label as shown, e.g. 'From station'."},
                       "value": {"type": "string", "description": "What to put in it; 'yes' or 'no' for a checkbox."}},
                      ["label", "value"])}}, ["fields"])),
    "set_checked": ("Tick or untick a checkbox or switch by its number.",
                    _schema({"element_id": ELEMENT, "checked": {"type": "boolean"}}, ["element_id", "checked"])),
    "press_key": ("Press a key: Enter, Escape, Tab, ArrowDown, ArrowUp, PageDown, PageUp, Backspace.",
                  _schema({"key": {"type": "string"}}, ["key"])),
    "scroll": ("Scroll the page (or the list with the given number) to see more.",
               _schema({"direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
                        "amount": {"type": "integer", "description": "1 to 10, default 3 (about one screen)"},
                        "element_id": ELEMENT}, ["direction"])),
    "search_web": ("Find something on the web. Goes straight to a site's own search when the query names one "
                   "(YouTube, Wikipedia, Amazon...), otherwise searches the web and opens the best result. "
                   "Use this instead of typing into a search engine yourself. Set open_result to false to just list the results.",
                   _schema({"query": {"type": "string", "description": "What to look for, in the user's words."},
                            "site": {"type": "string", "description": "Optional site to search on, e.g. youtube."},
                            "open_result": {"type": "boolean"}}, ["query"])),
    "open_page": ("Go straight to a web address.",
                  _schema({"url": {"type": "string"}}, ["url"])),
    "go_back": ("Go back to the previous page.", _schema({})),
    "read_page": ("Read the text of the page (articles, results, prices, answers). Use this to find information.",
                  _schema({})),
    "pull_list": ("Pull the lists and tables out of the page in one go: prices, products, listings, search hits, timetables. "
                  "Better than read_page when you need to compare several items.",
                  _schema({"about": {"type": "string", "description": "Optional: what the list is about, e.g. 'speaker prices'."}})),
    "look_at_screen": ("Get a screenshot of the page next turn. Use only when the page view is missing what you need (pictures, maps, canvas).",
                       _schema({})),
    "click_at": ("Click a point on the screenshot. x and y go from 0 to 1000 across and down the screen. Only for things that have no number in the page view.",
                 _schema({"x": {"type": "integer"}, "y": {"type": "integer"}}, ["x", "y"])),
    "wait": ("Wait for the page to finish loading or updating.",
             _schema({"seconds": {"type": "integer", "description": "1 to 5"}})),
    "ask_before": ("Stop and ask the user before something sensitive: paying, sending a message, booking, deleting, posting, sharing personal details.",
                   _schema({"question": {"type": "string"}}, ["question"])),
    "step_done": ("Say the current step is finished, with what on the page shows it.",
                  _schema({"evidence": {"type": "string"}}, ["evidence"])),
    "task_complete": ("Say the user's whole task is finished. The summary is spoken to the user; if they asked a question, include the answer.",
                      _schema({"summary": {"type": "string"}}, ["summary"])),
}

ALL_TOOLS = list(DECLARATIONS)
# The bigger tools are offered only on steps that sound like they need them,
# so the model has fewer tools to choose from. Every other tool is always offered.
EXTRA_TOOLS = {
    "search_web": re.compile(r"\b(search|find|look (up|for)|go to|open|visit|watch|play|listen|news|weather|"
                             r"youtube|wikipedia|amazon|flipkart|website|site)\b", re.I),
    "pull_list": re.compile(r"\b(prices?|cheap(er|est)?|compare|list|options|results|times?|timetable|table|ratings?|"
                            r"reviews?|best|top|fares?|flights?|trains?|hotels?|products?|items)\b", re.I),
    "fill_form": re.compile(r"\b(fill|enter|form|details|dates?|book|booking|sign up|register|address|passengers?|"
                            r"travell?ers?|checkout|apply)\b", re.I),
}


def tools_for_step(text: str) -> list[str]:
    """The tools to offer for a step, picked from its wording."""
    return [name for name in ALL_TOOLS if name not in EXTRA_TOOLS or EXTRA_TOOLS[name].search(text or "")]


# Tools that only look at the page: they don't use up actions or need to change anything.
LOOK_ONLY = {"read_page", "pull_list", "look_at_screen", "wait"}


def declarations(names: list[str] | None = None) -> list[types.FunctionDeclaration]:
    chosen = names or ALL_TOOLS
    return [
        types.FunctionDeclaration(name=n, description=DECLARATIONS[n][0], parameters_json_schema=DECLARATIONS[n][1])
        for n in chosen if n in DECLARATIONS
    ]


def _reply_ok(reply) -> bool:
    return isinstance(reply, dict) and reply.get("success") is True


def _reply_detail(reply, fallback: str) -> str:
    if isinstance(reply, dict):
        return reply.get("detail") or fallback
    return fallback


def _results_text(results: list[dict], start: int = 1) -> str:
    lines = []
    for i, r in enumerate(results, start=start):
        snippet = (r.get("snippet") or "")[:120]
        lines.append(f"{i}. {r.get('title', '')}" + (f" — {snippet}" if snippet else "") + f" ({r.get('url', '')})")
    return "\n".join(lines)


YES = {"yes", "true", "on", "1", "tick", "ticked", "checked", "y"}
TICK_ROLES = {"checkbox", "switch", "radio"}


def items_text(found: dict, max_chars: int = 6000) -> str:
    """Tables and lists from the extension's pull_items, as short text for the model."""
    blocks = []
    for n, table in enumerate(found.get("tables") or [], start=1):
        lines = [f"Table {n}" + (f": {table['caption']}" if table.get("caption") else "")]
        if table.get("header"):
            lines.append(" | ".join(table["header"]))
        lines.extend(" | ".join(row) for row in table.get("rows") or [])
        if table.get("more"):
            lines.append(f"(+{table['more']} more rows)")
        blocks.append("\n".join(lines))
    for n, group in enumerate(found.get("lists") or [], start=1):
        items = group.get("items") or []
        lines = [f"List {n} ({len(items) + (group.get('more') or 0)} items)"]
        for i, item in enumerate(items, start=1):
            lines.append(f"{i}. {item.get('text', '')}" + (f" -> {item['link']}" if item.get("link") else ""))
        if group.get("more"):
            lines.append(f"(+{group['more']} more items further down)")
        blocks.append("\n".join(lines))
    text = "\n\n".join(blocks)
    return text if len(text) <= max_chars else text[:max_chars] + "\n…(cut short)"


class BrowserTools:
    """Carries out the model's tool calls through the extension."""

    def __init__(self, browser: BrowserAdapter, search_engine: str = "google", settle_seconds: float = 0.6):
        self.browser = browser
        self.search_engine = search_engine
        self.settle_seconds = settle_seconds   # time for suggestions to appear after typing
        self.last_page: dict | None = None   # the page map the model is looking at

    def _is_secret(self, element_id) -> bool:
        el = element_by_id(self.last_page, element_id)
        return bool(el and el.get("secret"))

    async def open(self, url: str) -> ToolResult:
        reply = await self.browser.execute_action("navigate", {"url": url})
        ok = reply is True or (isinstance(reply, dict) and reply.get("success") is not False)
        return ToolResult(ok, f"Opening {url}." if ok else _reply_detail(reply, f"Could not open {url}."), data=reply)

    async def choose_or_type(self, el_id, value: str):
        """Pick from a dropdown. Many city and station pickers only list matches
        after you type, so if the option isn't there, type and pick again."""
        reply = await self.browser.execute_action("choose_option", {"element_id": el_id, "text": value})
        if _reply_ok(reply):
            return reply
        typed = await self.browser.execute_action("type_text", {"element_id": el_id, "text": value, "submit": False})
        if not (_reply_ok(typed) or typed is True):
            return reply
        await asyncio.sleep(self.settle_seconds)
        picked = await self.browser.execute_action("choose_option", {"text": value})
        # Typing alone is enough for a box that just takes text.
        return picked if _reply_ok(picked) else {"success": True}

    async def fill_form(self, fields: list) -> ToolResult:
        page = await self.page_map() or self.last_page
        filled, missing, refused, failed = [], [], [], []
        used: set = set()
        for field in fields or []:
            if not isinstance(field, dict):
                continue
            label, value = str(field.get("label", "")).strip(), str(field.get("value", ""))
            if not label:
                continue
            el = find_field(page, label, used)
            if el is None:
                # "Gender: Female" -> the radio button labelled "Female".
                el = find_field(page, value, used)
                if el is None or el.get("role") not in TICK_ROLES:
                    missing.append(label)
                    continue
                value = "yes"
            used.add(el.get("id"))
            if el.get("secret"):
                refused.append(label)
                continue
            role, el_id = el.get("role"), el.get("id")
            if role in TICK_ROLES:
                ticked = value.strip().lower() in YES
                if role == "radio" and not ticked:
                    continue
                reply = await self.browser.execute_action("set_checked", {"element_id": el_id, "checked": ticked})
            elif role == "dropdown":
                reply = await self.choose_or_type(el_id, value)
            else:
                reply = await self.browser.execute_action("type_text", {"element_id": el_id, "text": value, "submit": False})
            if _reply_ok(reply) or reply is True:
                chosen = reply.get("chosen") if isinstance(reply, dict) else None
                filled.append(f"{el.get('label') or label} = {chosen or value}")
            else:
                failed.append(f"{label} ({_reply_detail(reply, 'did not work')})")

        parts = []
        if filled:
            parts.append("Filled: " + "; ".join(filled) + ".")
        if missing:
            parts.append("No box found for: " + ", ".join(missing) + ". Scroll or check the labels in the page view.")
        if refused:
            parts.append("Not filled (password or card boxes, the user must do these): " + ", ".join(refused) + ".")
        if failed:
            parts.append("Could not fill: " + "; ".join(failed) + ".")
        if not parts:
            parts.append("No fields were given.")
        if filled:
            parts.append("The form has not been sent.")
        return ToolResult(bool(filled), " ".join(parts), data={"filled": filled, "missing": missing})

    async def search_web(self, query: str, site: str = "", open_result: bool = True) -> ToolResult:
        query = query.strip()
        if not query:
            return ToolResult(False, "No search words given.")
        direct = route(query, site)
        if direct:
            opened = await self.open(direct)
            if opened.ok:
                opened.message = f"Went straight to {direct}."
            return opened

        address = search_url(query, self.search_engine)
        opened = await self.open(address)
        if not opened.ok:
            return opened
        reply = await self.browser.execute_action("search_results", {})
        results = (reply.get("results") or []) if _reply_ok(reply) else []
        if not results:
            return ToolResult(True, f"Searched for \"{query}\". The results are open; pick one from the page view.",
                              data=opened.data)
        if not open_result:
            return ToolResult(True, f"Results for \"{query}\":\n{_results_text(results)}\n"
                                    "Use open_page with the address of the one you want.", data={"results": results})
        best = results[0]
        opened = await self.open(best["url"])
        if not opened.ok:
            return ToolResult(False, f"Found results but could not open the first one. Results:\n{_results_text(results)}",
                              data={"results": results})
        others = f"\nOther results:\n{_results_text(results[1:5], start=2)}" if len(results) > 1 else ""
        return ToolResult(True, f"Searched for \"{query}\" and opened the first result: {best['title']} ({best['url']}).{others}",
                          data={"results": results, "opened": best["url"]})

    async def page_map(self) -> dict | None:
        reply = await self.browser.execute_action("page_map", {})
        return reply.get("page") if _reply_ok(reply) else None

    async def page_text(self, max_chars: int = 12000) -> str:
        reply = await self.browser.execute_action("read_text", {"max_chars": max_chars})
        return reply.get("text", "") if _reply_ok(reply) else ""

    async def _do(self, action: str, args: dict, done: str, failed: str) -> ToolResult:
        reply = await self.browser.execute_action(action, args)
        if _reply_ok(reply):
            extra = f" ({reply['chosen']})" if isinstance(reply, dict) and reply.get("chosen") else ""
            return ToolResult(True, done + extra, data=reply)
        stale = isinstance(reply, dict) and bool(reply.get("stale"))
        detail = _reply_detail(reply, failed)
        if isinstance(reply, dict) and reply.get("options"):
            detail += " Options are: " + ", ".join(reply["options"][:15])
        return ToolResult(False, detail, stale=stale, data=reply)

    async def run(self, name: str, args: dict) -> ToolResult:
        args = dict(args or {})
        el = _int(args.get("element_id"))

        if name == "click":
            return await self._do("click_element", {"element_id": el}, f"Clicked {el}.", f"Could not click {el}.")
        if name == "type_text":
            if self._is_secret(el):
                return ToolResult(False, "That box is for a password or card number. HandOff never types those; "
                                         "use ask_before so the user can fill it in.")
            return await self._do(
                "type_text",
                {"element_id": el, "text": str(args.get("text", "")), "submit": bool(args.get("submit"))},
                f"Typed into {el}" + (" and pressed Enter." if args.get("submit") else "."),
                f"Could not type into {el}.",
            )
        if name == "choose_option":
            payload = {"text": str(args.get("text", ""))}
            if el is not None:
                payload["element_id"] = el
            return await self._do("choose_option", payload, f"Chose \"{payload['text']}\".", f"Could not choose \"{payload['text']}\".")
        if name == "fill_form":
            return await self.fill_form(args.get("fields") or [])
        if name == "set_checked":
            checked = bool(args.get("checked"))
            return await self._do("set_checked", {"element_id": el, "checked": checked},
                                  f"{'Ticked' if checked else 'Unticked'} {el}.", f"Could not change {el}.")
        if name == "press_key":
            key = str(args.get("key", "Enter"))
            return await self._do("press_key", {"key": key}, f"Pressed {key}.", f"Could not press {key}.")
        if name == "scroll":
            payload = {"direction": args.get("direction", "down"), "amount": _int(args.get("amount"), 3)}
            if el is not None:
                payload["element_id"] = el
            return await self._do("scroll_page", payload, f"Scrolled {payload['direction']}.", "Could not scroll.")
        if name == "open_page":
            url = str(args.get("url", "")).strip()
            if url and "://" not in url:
                url = "https://" + url
            if not url:
                return ToolResult(False, "No address given.")
            return await self.open(url)
        if name == "search_web":
            return await self.search_web(str(args.get("query", "")), str(args.get("site") or ""),
                                         args.get("open_result") is not False)
        if name == "go_back":
            return await self._do("go_back", {}, "Went back.", "Could not go back.")
        if name == "click_at":
            x, y = _int(args.get("x"), 500), _int(args.get("y"), 500)
            return await self._do("click_at", {"x": x, "y": y}, f"Clicked the screen at ({x}, {y}).", "Nothing to click there.")
        if name == "read_page":
            text = await self.page_text()
            return ToolResult(bool(text), text or "The page has no readable text.", is_action=False)
        if name == "pull_list":
            reply = await self.browser.execute_action("pull_items", {"about": str(args.get("about") or "")})
            text = items_text(reply) if _reply_ok(reply) else ""
            if not text:
                return ToolResult(False, "No lists or tables found on this page. Try read_page or scroll.", is_action=False)
            return ToolResult(True, text, is_action=False, data=reply)
        if name == "look_at_screen":
            return ToolResult(True, "A screenshot follows.", is_action=False, wants_screenshot=True)
        if name == "wait":
            return ToolResult(True, "Waited.", is_action=False, data={"seconds": max(1, min(5, _int(args.get("seconds"), 2)))})
        if name == "step_done":
            return ToolResult(True, "Checking...", ends="step", summary=str(args.get("evidence", "")), is_action=False)
        if name == "task_complete":
            return ToolResult(True, "Checking...", ends="task", summary=str(args.get("summary", "")), is_action=False)
        return ToolResult(False, f"There is no tool called {name}.", is_action=False)
