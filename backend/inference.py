"""Thin wrapper around the existing trained models.

Reuses model/keypoint_classifier and model/point_history_classifier
unchanged (no forked copies of your trained-model code). Adds preprocessing
adapted for landmarks the browser already sends normalized (0-1), instead of
the pixel coordinates app.py used.

No GPU delegate here on purpose: TFLite has no official GPU delegate build
for Windows at all, so attempting to load one doesn't just fail cleanly --
`tf.lite.experimental.load_delegate` allocates a Delegate object before the
library load fails, and that half-built object throws on garbage collection
later (`Delegate.__del__ ... AttributeError`), which is exactly the log spam
this used to produce on every single classifier instantiation. These two
models are also tiny (a handful of KB, microseconds of inference) -- a GPU
was never going to matter for them either way. Real GPU use in this project
is in face_engine.py, where it can actually do something (see that file).
"""
from __future__ import annotations

import csv
import itertools
import os
from copy import deepcopy

from model import KeyPointClassifier, PointHistoryClassifier

_KEYPOINT_MODEL = "model/keypoint_classifier/keypoint_classifier.tflite"
_KEYPOINT_LABELS = "model/keypoint_classifier/keypoint_classifier_label.csv"
_POINT_HISTORY_MODEL = "model/point_history_classifier/point_history_classifier.tflite"
_POINT_HISTORY_LABELS = "model/point_history_classifier/point_history_classifier_label.csv"

POINTING_SIGN_LABEL = "Pointer"  # matches this repo's keypoint_classifier_label.csv


def _load_labels(path: str) -> list[str]:
    with open(path, encoding="utf-8-sig") as f:
        return [row[0] for row in csv.reader(f)]


class GestureEngine:
    """One instance per device connection -- TFLite interpreters aren't
    safe to share across concurrently-invoking connections, and per-device
    instances are what let multiple people run gestures in parallel without
    a shared lock/queue."""

    def __init__(self) -> None:
        threads = max(1, os.cpu_count() or 1)
        self.keypoint_classifier = KeyPointClassifier(
            model_path=_KEYPOINT_MODEL, num_threads=threads
        )
        self.point_history_classifier = PointHistoryClassifier(
            model_path=_POINT_HISTORY_MODEL, num_threads=threads
        )
        self.keypoint_labels = _load_labels(_KEYPOINT_LABELS)
        self.point_history_labels = _load_labels(_POINT_HISTORY_LABELS)

    def classify_hand_sign(self, landmarks: list[list[float]]) -> str:
        processed = _pre_process_landmark(landmarks)
        index = self.keypoint_classifier(processed)
        return self.keypoint_labels[index]

    def classify_finger_gesture(self, point_history: list[list[float]]) -> str:
        flat = list(itertools.chain.from_iterable(point_history))
        index = self.point_history_classifier(flat)
        return self.point_history_labels[index]


def pre_process_point_history(point_history: list[list[float]]) -> list[list[float]]:
    """Same idea as app.py's pre_process_point_history, minus the divide by
    image width/height -- the client already sends normalized 0-1 points,
    so that division would be a no-op (width = height = 1)."""
    temp = deepcopy(point_history)
    if not temp:
        return temp
    base_x, base_y = temp[0][0], temp[0][1]
    for point in temp:
        point[0] -= base_x
        point[1] -= base_y
    return temp


def _pre_process_landmark(landmark_list: list[list[float]]) -> list[float]:
    """Same math as app.py's pre_process_landmark: relative-to-base then
    normalize by max abs value. Scale-invariant, so it works whether the
    input is pixel coordinates or MediaPipe's normalized 0-1 coordinates."""
    temp = deepcopy(landmark_list)
    base_x, base_y = temp[0][0], temp[0][1]
    for point in temp:
        point[0] -= base_x
        point[1] -= base_y
    flat = list(itertools.chain.from_iterable(temp))
    max_value = max((abs(v) for v in flat), default=1) or 1
    return [v / max_value for v in flat]
