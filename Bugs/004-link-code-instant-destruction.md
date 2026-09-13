# 004 — Link codes destroyed instantly on last-device disconnect

**Severity:** High — a phone screen locking or a brief WiFi blip permanently invalidated a code the user had already written down.

## Symptom

User: "i have putted the number stil, this update us so bad and not recognized so i cant join." Codes shown on one device came back as `Unknown link code` on a second device shortly after, with no server restart in between.

## Root cause

`SessionManager.disconnect_device()` deleted the person's entire state (link code, held item, face embeddings) the instant their last connected socket dropped:

```python
def disconnect_device(self, device_id):
    ...
    if not peers:
        # old: immediately delete person_devices, held, link_codes entries
```

A dropped WebSocket is indistinguishable from the phone locking its screen, a tab reload, or a momentary WiFi blip — none of which mean "this person is gone for good," but all of which triggered full state deletion.

## Fix

`backend/session_manager.py`: added a 15-minute grace period (`PERSON_GRACE_SECONDS`). Disconnecting the last device now sets `person_expires_at[person_id] = now + 900` instead of deleting anything. `_sweep_expired()` (called on every `join()` and `disconnect_device()`) purges only people whose grace window has actually elapsed with nobody reconnecting. Reclaiming the code within the window cancels the pending purge.

## Verification

- `test_disconnect_last_device_keeps_code_alive_during_grace` — disconnect, then rejoin with the same code, confirm same `person_id`.
- `test_person_state_purged_after_grace_window_expires` — force-expire the grace timer, confirm state is actually gone afterward (grace period isn't a permanent bypass).
- `test_expired_link_code_is_rejected_on_join` — confirms genuinely expired codes still correctly raise `UnknownLinkCode`.
- End-to-end WebSocket test: real device A joins, socket closes, device B joins with A's code afterward — succeeds as the same person.
