"""Person identification using hand geometry instead of face recognition.
Much lighter, works without face visibility, and uses landmarks we already extract.

Hand geometry: normalized hand size, finger proportions, palm width.
These are unique per person and don't require a separate ML model.
"""
from __future__ import annotations

import math
from typing import Optional


def hand_geometry_vector(landmarks: list[list[float]]) -> Optional[list[float]]:
    """Extract a 8-dimensional hand geometry feature vector from landmarks.

    Returns None if the hand is too small or malformed (fewer than 21 points).

    Features:
    - Hand scale (normalized)
    - Finger lengths (5D: thumb, index, middle, ring, pinky)
    - Palm width

    These are person-specific and consistent across sessions.
    """
    if len(landmarks) < 21:
        return None

    # Wrist is landmark 0, fingertips are 4, 8, 12, 16, 20
    wrist = landmarks[0]

    # Compute hand bounding box for normalization
    min_x = min(p[0] for p in landmarks)
    max_x = max(p[0] for p in landmarks)
    min_y = min(p[1] for p in landmarks)
    max_y = max(p[1] for p in landmarks)

    hand_width = max_x - min_x
    hand_height = max_y - min_y
    hand_scale = math.sqrt(hand_width * hand_width + hand_height * hand_height)

    if hand_scale < 0.01:
        return None

    # Finger lengths: wrist to each fingertip
    finger_lengths = []
    fingertips = [4, 8, 12, 16, 20]  # MediaPipe landmark indices
    for tip_idx in fingertips:
        tip = landmarks[tip_idx]
        dx = tip[0] - wrist[0]
        dy = tip[1] - wrist[1]
        length = math.sqrt(dx * dx + dy * dy)
        # Normalize by hand scale
        finger_lengths.append(length / hand_scale)

    # Palm width: distance between index base and pinky base
    index_base = landmarks[5]
    pinky_base = landmarks[17]
    palm_dx = pinky_base[0] - index_base[0]
    palm_dy = pinky_base[1] - index_base[1]
    palm_width = math.sqrt(palm_dx * palm_dx + palm_dy * palm_dy) / hand_scale

    # Feature vector: [hand_scale, 5 finger lengths, palm_width]
    # (scale is absolute, others are normalized)
    return [hand_scale] + finger_lengths + [palm_width]


def hand_geometry_distance(vec1: list[float], vec2: list[float]) -> float:
    """Euclidean distance between two hand geometry vectors.

    Lower = more similar. Threshold: ~0.3 = same person.
    """
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return float('inf')

    return math.sqrt(sum((a - b) ** 2 for a, b in zip(vec1, vec2)))


def hand_matches_person(landmarks: list[list[float]], person_samples: list[list[float]]) -> tuple[bool, float]:
    """Check if hand landmarks match a known person.

    Returns (matches, confidence) where confidence is 0.0-1.0.
    Matches if distance < 0.35 (95% same person).
    """
    vec = hand_geometry_vector(landmarks)
    if not vec or not person_samples:
        return False, 0.0

    # Find minimum distance to any sample from this person
    min_distance = min(hand_geometry_distance(vec, sample) for sample in person_samples)

    # Convert distance to confidence: lower distance = higher confidence
    # distance 0.0 = identical (confidence 1.0)
    # distance 0.5 = different (confidence 0.0)
    confidence = max(0.0, 1.0 - (min_distance / 0.5))
    matches = min_distance < 0.35

    return matches, confidence
