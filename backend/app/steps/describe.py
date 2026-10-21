"""Describing browser actions in plain words for the user."""


def action_in_plain_words(action_name: str, args: dict) -> str:
    page_action = _page_action_in_plain_words(action_name, args)
    if page_action:
        return page_action
    if action_name in ["click_at", "click", "left_click"]:
        return "Click a button or link"
    elif action_name in ["type_text_at", "type"]:
        text = args.get("text", "...")
        if len(text) > 15:
            return "Type a message"
        return f"Type '{text}'"
    elif action_name == "navigate":
        return f"Open website: {args.get('url', '...')}"
    elif action_name in ["scroll", "scroll_document", "scroll_at"]:
        direction = args.get("direction", "down")
        amount = args.get("amount", 3)
        pixels = amount * 120
        return f"Scroll {direction} {pixels}px"
    elif action_name == "scroll_to":
        target_y = args.get("pixel_y", args.get("target_y", 0))
        return f"Jump to position {target_y}px"
    elif action_name == "key_combination":
        keys = args.get("keys", [])
        return f"Press shortcut: {'+'.join(keys) if isinstance(keys, list) else keys}"
    elif action_name == "hover_at":
        return "Point at an element"
    return "Prepare to take action"


def _page_action_in_plain_words(action_name: str, args: dict) -> str | None:
    """Wording for the page-map tools (tools/browser.py)."""
    if action_name == "type_text":
        text = str(args.get("text", ""))
        typed = "Type a message" if len(text) > 15 else f"Type '{text}'"
        return typed + (" and search" if args.get("submit") else "")
    if action_name == "choose_option":
        return f"Choose '{args.get('text', '')}'"
    if action_name == "set_checked":
        return "Tick a box" if args.get("checked") else "Untick a box"
    if action_name == "press_key":
        return f"Press {args.get('key', 'a key')}"
    if action_name == "fill_form":
        count = len(args.get("fields") or [])
        return f"Fill in {count} box{'es' if count != 1 else ''} on the form"
    if action_name == "search_web":
        where = f" on {args['site']}" if args.get("site") else ""
        return f"Search for '{args.get('query', '')}'{where}"
    if action_name == "open_page":
        return f"Open website: {args.get('url', '...')}"
    if action_name == "go_back":
        return "Go back a page"
    if action_name == "scroll":
        return f"Scroll {args.get('direction', 'down')}"
    return None


def _label(page: dict | None, element_id) -> str:
    from app.browser.page_view import element_by_id
    el = element_by_id(page, element_id) if element_id is not None else None
    label = str((el or {}).get("label") or "").strip()
    return label if len(label) <= 60 else label[:57] + "..."


def _typed(text) -> str:
    text = str(text or "")
    return "a message" if len(text) > 15 else f"'{text}'"


def action_now(action_name: str, args: dict, page: dict | None) -> str:
    """What the banner says while an action runs: "Clicking 'Search'"."""
    from urllib.parse import urlparse
    label = _label(page, args.get("element_id"))
    named = f"'{label}'" if label else ""
    if action_name in ("click", "click_element"):
        return f"Clicking {named}" if named else "Clicking a button or link"
    if action_name == "type_text":
        into = f" into {named}" if named else ""
        return f"Typing {_typed(args.get('text'))}{into}" + (" and searching" if args.get("submit") else "")
    if action_name == "choose_option":
        return f"Choosing '{args.get('text', '')}'" + (f" in {named}" if named else "")
    if action_name == "set_checked":
        word = "Ticking" if args.get("checked") else "Unticking"
        return f"{word} {named}" if named else f"{word} a box"
    if action_name == "press_key":
        return f"Pressing {args.get('key', 'a key')}"
    if action_name == "fill_form":
        count = len(args.get("fields") or [])
        return f"Filling in {count} box{'es' if count != 1 else ''} on the form"
    if action_name == "search_web":
        where = f" on {args['site']}" if args.get("site") else ""
        return f"Searching for '{args.get('query', '')}'{where}"
    if action_name in ("open_page", "navigate", "open_web_browser"):
        host = (urlparse(str(args.get("url") or "")).hostname or "").removeprefix("www.")
        return f"Opening {host}" if host else "Opening a page"
    if action_name == "go_back":
        return "Going back a page"
    if action_name in ("scroll", "scroll_page", "scroll_document", "scroll_at", "scroll_to"):
        return f"Scrolling {args.get('direction', 'down')}"
    if action_name in ("click_at", "left_click"):
        return "Clicking on the page"
    if action_name in ("type_text_at", "type"):
        return f"Typing {_typed(args.get('text'))}"
    if action_name == "key_combination":
        keys = args.get("keys", [])
        return f"Pressing {'+'.join(keys) if isinstance(keys, list) else keys}"
    if action_name == "hover_at":
        return "Pointing at something on the page"
    return "Working on the page"
