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
