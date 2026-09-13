# 002 — Gesture confidence threshold used `>` instead of `>=`

**Severity:** High — legitimate high-confidence gestures silently didn't fire.

## Symptom

Server log showed a Close gesture at exactly `confidence=0.80` classified but never promoted to a `HIGH_CONFIDENCE_GESTURE` event, while the same device's later gestures at 0.81+ fired fine. The grabbing device's Close never registered, so the transfer state machine never entered "in transit," making the whole flow look broken from the outside.

## Root cause

`backend/gesture_discriminator.py`'s pose-confidence test used a strict inequality:

```python
if pose_confidence > 0.8:   # 0.80 exactly does NOT pass
```

Confidence values are rounded/computed such that hitting exactly the threshold is common, not a rare edge case, so this silently dropped a meaningful fraction of otherwise-valid gestures.

## Fix

Changed to `>= 0.8` in `backend/gesture_discriminator.py`.

## Verification

Manual test: reproduced a Close gesture landing at `confidence=0.80` and confirmed `HIGH_CONFIDENCE_GESTURE` now fires with `reason=high_pose_confidence` at that exact value.
