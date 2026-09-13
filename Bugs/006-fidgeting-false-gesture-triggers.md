# 006 — Fidgeting/relaxing fired accidental gesture actions

**Severity:** High — made the app feel completely unreliable ("i had my hand closed and i opened it but it didn't receive the image file").

## Symptom

Natural hand relaxation right after an intentional Open gesture would pass through a fist-like shape for a few frames, which — fed straight into the old single-frame classifier → action pipeline — fired an accidental Close and wiped whatever was just picked up before the user could physically walk to another device.

## Root cause

The original pipeline acted on every single-frame gesture classification with no debouncing or confidence filtering at all: `hand_sign == "Open"` → act immediately, no matter how transient or ambiguous that one frame was.

## Fix, in two layers

1. **Frame stability** (`backend/session_manager.py`'s `stable_gesture()`): requires `GESTURE_STABILITY_FRAMES` (3) consecutive matching classifications before treating a transition as real, and only fires once per transition (not every frame the pose is held).
2. **Pose + motion discrimination** (`backend/gesture_discriminator.py`, added later): a 3-test system on top of frame stability —
   - **Pose confidence** ≥ 80%: the hand must be unambiguously open or closed (all fingers clearly extended/curled), not partway.
   - **Motion spike**: the classification change must coincide with actual hand movement (a real gesture involves motion; fidgeting-in-place mostly doesn't).
   - **Gesture lock**: the pose must hold stable for 5+ frames after the motion, not bounce between states.

## Verification

- `test_stable_gesture_close_after_open_needs_its_own_stability` — a single stray Close frame right after a confirmed Open does not immediately fire.
- `test_stable_gesture_flicker_does_not_fire` — Open/Open/Close/Open/Open (never 3 in a row) never fires.
- Manual server-log verification: fidgety hand movement stays below the confidence/motion thresholds and produces no `HIGH_CONFIDENCE_GESTURE` log line, while deliberate open/close cycles do, with the specific test (`high_pose_confidence`, `motion_spike`, or `gesture_lock`) that passed logged for debugging.
