import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from backend.session_manager import SessionManager, UnknownLinkCode


def _text(content: str) -> list:
    """Selection queue with a single text entry -- set_selection() always
    takes a list now (to support multi-file bundles), so tests that only
    care about one plain-text item go through this helper."""
    return [{"content_type": "text", "content": content, "filename": None}]


def _file(filename: str, content: str = "data:fake") -> dict:
    return {"content_type": "file", "content": content, "filename": filename}


def test_join_without_code_creates_new_person_and_code():
    m = SessionManager()
    session = m.join(None, "laptop")
    assert session.person_id
    assert getattr(session, "_link_code")
    assert m.link_codes[session._link_code] == session.person_id


def test_second_device_joins_same_person_via_code():
    m = SessionManager()
    a = m.join(None, "laptop")
    b = m.join(a._link_code, "phone")
    assert b.person_id == a.person_id
    assert set(m.devices_for(a.person_id)) == {a.device_id, b.device_id}


def test_unknown_link_code_rejected():
    m = SessionManager()
    with pytest.raises(UnknownLinkCode):
        m.join("ZZZZZZ", "phone")


def test_grab_with_no_selection_yields_nothing_to_hold():
    m = SessionManager()
    a = m.join(None, "laptop")
    result = m.grab(a.device_id)
    assert result["action"] == "nothing_to_hold"


def test_grab_then_release_transfers_to_second_device():
    """The canonical flow: select on A, close hand on A (grab), walk to B,
    open hand on B (release) -- item lands on B and the slot clears."""
    m = SessionManager()
    a = m.join(None, "laptop")
    b = m.join(a._link_code, "phone")

    m.set_selection(a.device_id, _text("hello world"))
    grabbed = m.grab(a.device_id)
    assert grabbed["action"] == "grabbed"
    assert grabbed["item"].origin_device == a.device_id

    delivered = m.release(b.device_id)
    assert delivered["action"] == "delivered"
    assert delivered["item"].delivered_to == {b.device_id}
    # Transfer complete: the slot is free for a new grab.
    assert m.held[a.person_id] is None
    assert a.person_id not in m.grabbed_by


def test_release_on_the_grabbing_device_does_not_transfer():
    """The exact bug being guarded against: opening your hand on the SAME
    device that grabbed the item must not self-deliver it. Only a
    DIFFERENT device's open-hand completes the transfer."""
    m = SessionManager()
    a = m.join(None, "laptop")
    b = m.join(a._link_code, "phone")

    m.set_selection(a.device_id, _text("hello"))
    m.grab(a.device_id)

    same_device = m.release(a.device_id)
    assert same_device["action"] == "same_device"
    # Nothing changed -- still in transit, still grabbed by A.
    assert m.held[a.person_id] is not None
    assert m.grabbed_by[a.person_id] == a.device_id

    # Only when a DIFFERENT device opens its hand does it actually deliver.
    delivered = m.release(b.device_id)
    assert delivered["action"] == "delivered"
    assert m.held[a.person_id] is None


def test_regrabbing_on_same_device_is_idempotent():
    m = SessionManager()
    a = m.join(None, "laptop")
    m.set_selection(a.device_id, _text("hello"))
    m.grab(a.device_id)

    result = m.grab(a.device_id)
    assert result["action"] == "already_grabbed"


def test_grab_on_a_different_device_while_something_is_in_transit_is_busy():
    m = SessionManager()
    a = m.join(None, "laptop")
    b = m.join(a._link_code, "phone")

    m.set_selection(a.device_id, _text("first"))
    m.grab(a.device_id)

    m.set_selection(b.device_id, _text("second"))
    result = m.grab(b.device_id)
    assert result["action"] == "busy"
    # The original grab is untouched.
    assert m.held[a.person_id].contents[0].content == "first"


def test_release_then_grab_again_is_a_fresh_transfer():
    m = SessionManager()
    a = m.join(None, "laptop")
    b = m.join(a._link_code, "phone")

    m.set_selection(a.device_id, _text("first"))
    m.grab(a.device_id)
    m.release(b.device_id)

    m.set_selection(a.device_id, _text("second"))
    result = m.grab(a.device_id)
    assert result["action"] == "grabbed"
    assert result["item"].contents[0].content == "second"


def test_grab_bundles_multiple_selected_items_into_one_transfer():
    """Selecting text plus two files and grabbing once must carry all three
    together, atomically -- not as three separate single-item transfers."""
    m = SessionManager()
    a = m.join(None, "laptop")
    b = m.join(a._link_code, "phone")

    m.set_selection(
        a.device_id,
        [
            {"content_type": "text", "content": "caption", "filename": None},
            _file("photo1.jpg"),
            _file("photo2.jpg"),
        ],
    )
    grabbed = m.grab(a.device_id)
    assert grabbed["action"] == "grabbed"
    assert len(grabbed["item"].contents) == 3

    delivered = m.release(b.device_id)
    assert delivered["action"] == "delivered"
    filenames = {c.filename for c in delivered["item"].contents if c.filename}
    assert filenames == {"photo1.jpg", "photo2.jpg"}
    # One bundle, one hop -- slot is freed same as a single-item transfer.
    assert m.held[a.person_id] is None


def test_grab_with_empty_selection_list_yields_nothing_to_hold():
    m = SessionManager()
    a = m.join(None, "laptop")
    m.set_selection(a.device_id, [])
    result = m.grab(a.device_id)
    assert result["action"] == "nothing_to_hold"


def test_cancel_transfer_clears_in_flight_item_without_delivering():
    m = SessionManager()
    a = m.join(None, "laptop")
    m.set_selection(a.device_id, _text("secret"))
    m.grab(a.device_id)

    cancelled = m.cancel_transfer(a.person_id)
    assert cancelled["action"] == "cancelled"
    assert m.held[a.person_id] is None
    assert a.person_id not in m.grabbed_by


def test_cancel_transfer_with_nothing_held_is_a_noop():
    m = SessionManager()
    a = m.join(None, "laptop")
    result = m.cancel_transfer(a.person_id)
    assert result["action"] == "noop"


def test_release_with_nothing_held_is_a_noop():
    m = SessionManager()
    a = m.join(None, "laptop")
    result = m.release(a.device_id)
    assert result["action"] == "nothing_held"


def test_disconnect_last_device_keeps_code_alive_during_grace():
    m = SessionManager()
    a = m.join(None, "laptop")
    m.set_selection(a.device_id, _text("secret"))
    m.grab(a.device_id)
    person_id = a.person_id
    code = a._link_code

    m.disconnect_device(a.device_id)

    # Grace window: the code must still work, because a dropped socket is
    # indistinguishable from a screen lock or a tab reload.
    assert code in m.link_codes
    b = m.join(code, "phone")
    assert b.person_id == person_id
    assert person_id not in m.person_expires_at  # reclaiming cancels the purge


def test_person_state_purged_after_grace_window_expires():
    m = SessionManager()
    a = m.join(None, "laptop")
    person_id, code = a.person_id, a._link_code
    m.set_selection(a.device_id, _text("hi"))
    m.grab(a.device_id)

    m.disconnect_device(a.device_id)
    # Pretend the grace window already elapsed.
    m.person_expires_at[person_id] = time.time() - 1
    m._sweep_expired()

    assert person_id not in m.held
    assert person_id not in m.person_devices
    assert code not in m.link_codes


def test_expired_link_code_is_rejected_on_join():
    m = SessionManager()
    a = m.join(None, "laptop")
    code = a._link_code
    m.disconnect_device(a.device_id)
    m.person_expires_at[a.person_id] = time.time() - 1

    with pytest.raises(UnknownLinkCode):
        m.join(code, "phone")


def test_active_person_count_ignores_disconnected_people():
    m = SessionManager()
    a = m.join(None, "laptop")
    b = m.join(None, "other person")
    assert m.active_person_count() == 2

    m.disconnect_device(a.device_id)
    # a is inside their grace window -- still in person_devices, but nobody
    # is actually connected for them, so they must not be counted as online.
    assert m.active_person_count() == 1
    assert b.person_id in m.person_devices


def test_disconnect_one_of_two_devices_keeps_person_state():
    m = SessionManager()
    a = m.join(None, "laptop")
    b = m.join(a._link_code, "phone")
    m.set_selection(a.device_id, _text("hi"))
    m.grab(a.device_id)

    m.disconnect_device(b.device_id)

    assert a.person_id in m.held
    assert m.held[a.person_id] is not None
    assert m.devices_for(a.person_id) == [a.device_id]


def test_face_match_empty_when_nothing_enrolled():
    m = SessionManager()
    person_id, score = m.match_face([0.1, 0.2, 0.3])
    assert person_id is None
    assert score == 0.0


def test_link_code_for_returns_person_code():
    m = SessionManager()
    a = m.join(None, "laptop")
    assert m.link_code_for(a.person_id) == a._link_code


def test_stable_gesture_requires_consecutive_frames():
    m = SessionManager()
    a = m.join(None, "laptop")
    assert m.stable_gesture(a.device_id, "Open") is None
    assert m.stable_gesture(a.device_id, "Open") is None
    assert m.stable_gesture(a.device_id, "Open") == "Open"  # 3rd consecutive frame


def test_stable_gesture_flicker_does_not_fire():
    m = SessionManager()
    a = m.join(None, "laptop")
    # Two frames of Open, one stray Close, back to Open -- never 3 in a row.
    assert m.stable_gesture(a.device_id, "Open") is None
    assert m.stable_gesture(a.device_id, "Open") is None
    assert m.stable_gesture(a.device_id, "Close") is None
    assert m.stable_gesture(a.device_id, "Open") is None
    assert m.stable_gesture(a.device_id, "Open") is None


def test_stable_gesture_fires_once_per_transition_not_every_frame():
    m = SessionManager()
    a = m.join(None, "laptop")
    for _ in range(3):
        m.stable_gesture(a.device_id, "Open")
    # Already confirmed "Open" -- holding the same pose must not re-fire.
    assert m.stable_gesture(a.device_id, "Open") is None
    assert m.stable_gesture(a.device_id, "Open") is None


def test_stable_gesture_close_after_open_needs_its_own_stability():
    m = SessionManager()
    a = m.join(None, "laptop")
    for _ in range(3):
        m.stable_gesture(a.device_id, "Open")
    # A single stray Close frame (e.g. hand relaxing) must not immediately
    # count as a confirmed Close -- this is the exact bug that let closing
    # your hand right after opening it silently wipe a transfer.
    assert m.stable_gesture(a.device_id, "Close") is None
    assert m.stable_gesture(a.device_id, "Close") is None
    assert m.stable_gesture(a.device_id, "Close") == "Close"
