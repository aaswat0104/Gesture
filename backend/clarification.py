"""Rule-based "understand -> ask -> execute" layer for ambiguous actions.

No LLM call: a fixed decision tree, as chosen for v1. The one case v1 needs
this for is "open hand with nothing selected" -- everything else in the
gesture flow (acquire/transfer/release) is unambiguous and handled directly
by SessionManager.
"""
from __future__ import annotations

NOTHING_SELECTED = {
    "question": "Your hand is open but nothing is selected on this device. What do you want to do?",
    "options": [
        {"key": "A", "label": "Select", "hint": "Type text or pick a file first"},
        {"key": "B", "label": "Transfer", "hint": "Select something, then close your hand to grab it"},
        {"key": "C", "label": "Status", "hint": "Check what's currently held"},
        {"key": "D", "label": "Help", "hint": "How does gesture transfer work?"},
    ],
}


def resolve(choice: str, other_text: str, selection: dict | None) -> dict:
    """Turns a clarification answer into a small result payload for the client.

    Deliberately simple: these are honest stubs, not fake functionality.
    """
    if choice == "other":
        return {"result": f"Noted: \"{other_text}\". Custom actions aren't wired up yet."}

    if choice == "A":
        return {"result": "Select text or pick an image/file, then close your hand to grab it."}

    if choice == "B":
        return {"result": "1. Select file here\n2. Close hand (fist) to grab\n3. Walk to another device\n4. Open hand (palm) to release"}

    if choice == "C":
        if not selection:
            return {"result": "Nothing selected yet."}
        if selection["content_type"] == "text":
            text = selection["content"]
            return {"result": f"Text: {len(text)} chars, {len(text.split())} words"}
        return {"result": f"File selected: {selection.get('filename', 'unnamed')}"}

    if choice == "D":
        return {"result": "Gesture Transfer: Close (grab) → Walk → Open (release). Multi-device, multi-person."}

    return {"result": "Unrecognized choice."}


# -- very small voice-command vocabulary, layered on the same gestures ----
# NEW SEMANTICS: Close = Grab/Acquire, Open = Release/Deliver (Huawei AirShare style)
VOICE_COMMANDS = {
    "grab": "close_hand",
    "grab it": "close_hand",
    "take it": "close_hand",
    "pick up": "close_hand",
    "hold": "close_hand",
    "release": "open_hand",
    "let go": "open_hand",
    "drop": "open_hand",
    "give": "open_hand",
}


def match_voice_command(text: str) -> str | None:
    text = text.lower().strip()
    for phrase, action in VOICE_COMMANDS.items():
        if phrase in text:
            return action
    return None
