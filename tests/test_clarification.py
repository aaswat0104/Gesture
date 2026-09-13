import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import clarification


def test_analyze_text_selection_counts_words():
    selection = {"content_type": "text", "content": "hello brave new world"}
    result = clarification.resolve("C", "", selection)
    assert "4 words" in result["result"]


def test_analyze_with_no_selection():
    result = clarification.resolve("C", "", None)
    assert "Nothing selected" in result["result"]


def test_other_choice_echoes_custom_text():
    result = clarification.resolve("other", "do a barrel roll", None)
    assert "do a barrel roll" in result["result"]


def test_voice_command_matching():
    # NEW SEMANTICS: "hold" = close hand (grab), "release" = open hand (drop)
    assert clarification.match_voice_command("please hold this for me") == "close_hand"
    assert clarification.match_voice_command("ok release it now") == "open_hand"
    assert clarification.match_voice_command("what's the weather") is None
