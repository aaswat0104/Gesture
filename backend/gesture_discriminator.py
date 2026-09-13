"""Advanced gesture discrimination: distinguish intentional open/close from fidgeting.

The old system fired on any stable gesture classification. This filters out:
- Hand relaxation after opening (natural fist-like pose)
- Fidgeting (random finger movement)
- Hand repositioning (hand moving but gesture doesn't change)

Uses:
1. Hand pose confidence (how "open" or "closed" is the hand, 0-1)
2. Hand motion (velocity, acceleration)
3. Pose consistency (all fingers extended vs. some curled)
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass


@dataclass
class GestureEvent:
    """A high-confidence gesture event."""
    gesture: str  # "Open" or "Close"
    confidence: float  # 0.0-1.0, how certain we are
    reason: str  # why we fired: "high_pose_confidence", "motion_spike", etc.


class GestureDiscriminator:
    """Filters noisy gesture classifications into high-confidence events."""

    def __init__(self):
        # Track motion of hand over last few frames
        self.landmark_history: deque[list[list[float]]] = deque(maxlen=8)
        self.pose_confidence_history: deque[float] = deque(maxlen=8)
        self.hand_sign_history: deque[str] = deque(maxlen=8)
        self.motion_magnitude_history: deque[float] = deque(maxlen=8)
        self.last_fired_gesture: str | None = None

    def process(
        self,
        hand_sign: str,
        landmarks: list[list[float]],
        pose_confidence: float,
    ) -> GestureEvent | None:
        """Process a hand frame and return a high-confidence gesture event or None.

        Args:
            hand_sign: "Open", "Close", or "Pointer" (from classifier)
            landmarks: 21 hand landmark points
            pose_confidence: 0.0-1.0, how "open" or "closed" is the hand

        Returns:
            GestureEvent if a high-confidence gesture is detected, else None.
        """
        self.landmark_history.append(landmarks)
        self.pose_confidence_history.append(pose_confidence)
        self.hand_sign_history.append(hand_sign)

        # Compute hand motion
        motion = self._compute_motion()
        self.motion_magnitude_history.append(motion)

        # Skip if hand is "Pointer" (just pointing, not holding/releasing)
        if hand_sign == "Pointer":
            return None

        # Test 1: High pose confidence (hand is CLEARLY open or closed)
        if pose_confidence >= 0.8:
            # Make sure it's stable (consistent for last few frames)
            if self._is_stable_pose(hand_sign, frames=3):
                # Don't fire the same gesture twice in a row
                if self.last_fired_gesture != hand_sign:
                    self.last_fired_gesture = hand_sign
                    return GestureEvent(
                        gesture=hand_sign,
                        confidence=pose_confidence,
                        reason="high_pose_confidence",
                    )

        # Test 2: Motion spike (hand just moved + gesture classification changed)
        # This catches intentional opening/closing (hand moves deliberately)
        if motion > 0.15 and len(self.hand_sign_history) >= 3:
            prev_sign = self.hand_sign_history[-3]
            # Gesture changed AND motion is high = intentional gesture
            if prev_sign != hand_sign and hand_sign in ("Open", "Close"):
                # Double-check: pose confidence must be above 0.4 (not random jitter)
                if pose_confidence > 0.4:
                    if self.last_fired_gesture != hand_sign:
                        self.last_fired_gesture = hand_sign
                        return GestureEvent(
                            gesture=hand_sign,
                            confidence=pose_confidence * 0.9,
                            reason="motion_spike",
                        )

        # Test 3: Gesture lock (hand stayed in Open/Close for 5+ frames)
        # after we already saw a motion change. This reduces false releases.
        if hand_sign in ("Open", "Close") and len(self.hand_sign_history) >= 5:
            recent = list(self.hand_sign_history)[-5:]
            if all(s == hand_sign for s in recent) and pose_confidence > 0.6:
                # But only if this is a TRANSITION (we weren't already firing this)
                if self.last_fired_gesture != hand_sign:
                    self.last_fired_gesture = hand_sign
                    return GestureEvent(
                        gesture=hand_sign,
                        confidence=min(1.0, pose_confidence * 1.1),
                        reason="gesture_lock",
                    )

        return None

    def _compute_motion(self) -> float:
        """Compute hand motion magnitude: 0.0 = still, 1.0 = fast movement."""
        if len(self.landmark_history) < 2:
            return 0.0

        prev = self.landmark_history[-2]
        curr = self.landmark_history[-1]

        if not prev or not curr or len(prev) < 21 or len(curr) < 21:
            return 0.0

        # Use wrist (landmark 0) as reference point
        dx = curr[0][0] - prev[0][0]
        dy = curr[0][1] - prev[0][1]
        wrist_motion = math.sqrt(dx * dx + dy * dy)

        # Also track palm center movement (average of all landmarks)
        prev_center = (sum(p[0] for p in prev) / len(prev), sum(p[1] for p in prev) / len(prev))
        curr_center = (sum(p[0] for p in curr) / len(curr), sum(p[1] for p in curr) / len(curr))

        dx_center = curr_center[0] - prev_center[0]
        dy_center = curr_center[1] - prev_center[1]
        center_motion = math.sqrt(dx_center * dx_center + dy_center * dy_center)

        # Return average motion (scale to 0-1 range: 0.3 = fast)
        avg_motion = (wrist_motion + center_motion) / 2.0
        return min(1.0, avg_motion / 0.3)

    def _is_stable_pose(self, hand_sign: str, frames: int = 3) -> bool:
        """Check if the same hand sign has been consistent for N frames."""
        if len(self.hand_sign_history) < frames:
            return False
        recent = list(self.hand_sign_history)[-frames:]
        return all(s == hand_sign for s in recent)

    def reset(self) -> None:
        """Clear history (e.g., when user loses connection and reconnects)."""
        self.landmark_history.clear()
        self.pose_confidence_history.clear()
        self.hand_sign_history.clear()
        self.motion_magnitude_history.clear()
        self.last_fired_gesture = None


def compute_pose_confidence(landmarks: list[list[float]], hand_sign: str) -> float:
    """Compute how "open" or "closed" the hand is, 0.0-1.0.

    For "Open": all 5 fingers should be extended.
    For "Close": all 5 fingers should be curled.
    For "Pointer": index extended, others curled.
    """
    if len(landmarks) < 21:
        return 0.5

    wrist = landmarks[0]

    # Fingertip indices: thumb, index, middle, ring, pinky
    fingertips = [4, 8, 12, 16, 20]
    # PIP (middle joint) indices: thumb, index, middle, ring, pinky
    pips = [3, 7, 11, 15, 19]

    # For each finger, compute "extensiveness": distance from wrist to fingertip
    # vs distance from wrist to middle joint (PIP). Fully extended = high ratio.
    extensiveness_scores = []
    for tip_idx, pip_idx in zip(fingertips, pips):
        tip = landmarks[tip_idx]
        pip = landmarks[pip_idx]

        tip_dist = math.sqrt((tip[0] - wrist[0]) ** 2 + (tip[1] - wrist[1]) ** 2)
        pip_dist = math.sqrt((pip[0] - wrist[0]) ** 2 + (pip[1] - wrist[1]) ** 2)

        if pip_dist > 0:
            # Ratio > 1.2 means fingertip is well beyond PIP (extended)
            # Ratio < 1.0 means fingertip is close to PIP (curled)
            ratio = tip_dist / pip_dist
            # Clamp to 0-1 where 1.0 = fully extended, 0.0 = fully curled
            extensiveness = max(0.0, min(1.0, (ratio - 0.8) / 0.4))
            extensiveness_scores.append(extensiveness)

    if not extensiveness_scores:
        return 0.5

    avg_extensiveness = sum(extensiveness_scores) / len(extensiveness_scores)

    if hand_sign == "Open":
        # Open = most fingers extended (threshold: average > 0.7)
        return min(1.0, avg_extensiveness)
    elif hand_sign == "Close":
        # Close = most fingers curled (invert)
        return min(1.0, 1.0 - avg_extensiveness)
    elif hand_sign == "Pointer":
        # Pointer = index extended, others curled
        # Check index finger (index 1 in extensiveness_scores)
        index_extended = extensiveness_scores[1] if len(extensiveness_scores) > 1 else 0
        others_curled = 1.0 - sum(extensiveness_scores[i] for i in [0, 2, 3, 4] if i < len(extensiveness_scores)) / 4.0
        return (index_extended + others_curled) / 2.0

    return avg_extensiveness
