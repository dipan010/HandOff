"""Describing browser actions in plain words for the user."""


def action_in_plain_words(action_name: str, args: dict) -> str:
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
