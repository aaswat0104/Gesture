"""Centralized state: identity, held items, and the acquire/transfer/release
state machine. Pure Python, no ML/network deps, so it's cheap to unit test.
"""
from __future__ import annotations

import secrets
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


def _new_id() -> str:
    return secrets.token_hex(8)


def _new_link_code() -> str:
    return secrets.token_hex(3).upper()  # 6 hex chars, easy to read/type


@dataclass
class ContentPiece:
    """One file/text/image inside a (possibly multi-item) transfer bundle."""
    content_type: str  # "text" | "image" | "file"
    content: str
    filename: Optional[str] = None  # set for "image"/"file", any type is fine


@dataclass
class HeldItem:
    """A bundle in transit. Almost always one ContentPiece, but grabbing with
    multiple files/images selected bundles them all into one HeldItem so a
    single grab/release cycle transfers all of them together, atomically."""
    contents: list  # list[ContentPiece], always at least one
    origin_device: str
    delivered_to: set = field(default_factory=set)
    created_at: float = field(default_factory=time.time)


@dataclass
class DeviceSession:
    device_id: str
    person_id: str
    device_name: str
    point_history: deque = field(default_factory=lambda: deque(maxlen=16))
    finger_gesture_history: deque = field(default_factory=lambda: deque(maxlen=16))
    # List of {"content_type", "content", "filename"} dicts queued to grab.
    # A list (not a single dict) so multiple files/images can be selected and
    # grabbed together as one bundle.
    selection: list = field(default_factory=list)
    # Gesture debounce: a classifier result is only acted on once it has been
    # the same value for GESTURE_STABILITY_FRAMES in a row (see
    # SessionManager.stable_gesture). Not tracked for display -- the live
    # "hand: X" readout uses the raw per-frame classification, only the
    # acquire/release ACTION is gated on stability.
    _pending_sign: Optional[str] = None
    _pending_count: int = 0
    _confirmed_sign: Optional[str] = None


class UnknownLinkCode(Exception):
    pass


GESTURE_STABILITY_FRAMES = 3  # ~450ms at the client's 150ms send interval

# How long a person's identity (link code, held item, enrolled face) survives
# after their LAST device disconnects. Was 0 -- state was destroyed the
# instant the last socket dropped, so a phone locking its screen or a wifi
# blip permanently invalidated the link code the user had just written down,
# and re-entering it came back "Unknown link code".
PERSON_GRACE_SECONDS = 900  # 15 minutes


class SessionManager:
    """Single source of truth for identity + hold/transfer/release state.

    Kept in-memory only (per the session-only privacy choice): nothing here
    is written to disk, and a person's state is dropped PERSON_GRACE_SECONDS
    after their last device disconnects (not instantly -- see
    disconnect_device).
    """

    def __init__(self) -> None:
        self.devices: dict[str, DeviceSession] = {}
        self.link_codes: dict[str, str] = {}  # link_code -> person_id
        self.person_link_code: dict[str, str] = {}  # person_id -> link_code (reverse lookup)
        self.person_devices: dict[str, set[str]] = {}  # person_id -> device_ids
        self.held: dict[str, Optional[HeldItem]] = {}  # person_id -> HeldItem
        self.face_embeddings: dict[str, list[list[float]]] = {}  # person_id -> vectors
        # person_id -> unix ts after which an unattended person is purged.
        # Present only while a person has zero connected devices.
        self.person_expires_at: dict[str, float] = {}
        # Track which device grabbed the current held item (for multi-device transfer only)
        self.grabbed_by: dict[str, str] = {}  # person_id -> device_id that grabbed it

    # -- identity -----------------------------------------------------

    def join(self, link_code: Optional[str], device_name: str) -> DeviceSession:
        self._sweep_expired()
        link_code = (link_code or "").strip().upper()
        if link_code:
            person_id = self.link_codes.get(link_code)
            if person_id is None:
                raise UnknownLinkCode(link_code)
            # Reclaimed within the grace window: cancel the pending purge.
            self.person_expires_at.pop(person_id, None)
        else:
            person_id = _new_id()
            link_code = _new_link_code()
            self.link_codes[link_code] = person_id
            self.person_link_code[person_id] = link_code
            self.person_devices.setdefault(person_id, set())
            self.held.setdefault(person_id, None)

        device_id = _new_id()
        session = DeviceSession(device_id=device_id, person_id=person_id, device_name=device_name)
        self.devices[device_id] = session
        self.person_devices.setdefault(person_id, set()).add(device_id)
        session._link_code = link_code  # stashed for the join response only
        return session

    def disconnect_device(self, device_id: str) -> None:
        session = self.devices.pop(device_id, None)
        if session is None:
            return
        peers = self.person_devices.get(session.person_id)
        if peers:
            peers.discard(device_id)
            if not peers:
                # Last device gone -- but DON'T destroy the person yet. A
                # dropped socket (screen lock, wifi blip, tab reload) looks
                # identical to leaving for good, and nuking state here is what
                # made written-down link codes stop working. Purged later by
                # _sweep_expired() if nobody comes back.
                self.person_expires_at[session.person_id] = time.time() + PERSON_GRACE_SECONDS
        self._sweep_expired()

    def devices_for(self, person_id: str) -> list[str]:
        return list(self.person_devices.get(person_id, ()))

    def _sweep_expired(self) -> None:
        """Purge people whose grace window ran out with no device reconnecting."""
        now = time.time()
        for person_id, expires_at in list(self.person_expires_at.items()):
            if expires_at > now:
                continue
            self.person_expires_at.pop(person_id, None)
            self.person_devices.pop(person_id, None)
            self.held.pop(person_id, None)
            self.face_embeddings.pop(person_id, None)
            code = self.person_link_code.pop(person_id, None)
            if code is not None:
                self.link_codes.pop(code, None)

    def active_person_count(self) -> int:
        """People with at least one device actually connected -- people inside
        their disconnect grace window shouldn't inflate the presence count."""
        return sum(1 for devices in self.person_devices.values() if devices)

    # -- selection (what a grab would pick up right now) ---------------

    def set_selection(self, device_id: str, items: list[dict]) -> None:
        """Replace this device's whole selection queue at once. `items` is a
        list of {"content_type", "content", "filename"} dicts -- one text
        entry plus any number of files/images, all bundled into one grab."""
        session = self.devices[device_id]
        session.selection = list(items)

    # -- the grab / carry / release state machine ----------------------
    #
    # CLOSE hand = grab() -- pick up this device's selection, mark it "in
    # transit" so no other grab can start until this one resolves.
    # OPEN hand  = release() -- deliver the in-transit item to THIS device,
    # but ONLY if it was grabbed on a DIFFERENT device. Opening your hand on
    # the very device that grabbed it is a deliberate no-op (action
    # "same_device"): otherwise a relaxed fist right after grabbing would
    # instantly self-deliver before you've walked anywhere.
    #
    # grab() and release() used to be one shared open_hand() method with a
    # three-way branch (acquire-if-empty / no-op-if-same-device /
    # deliver-if-different-device). Both gestures called into it, which
    # meant OPEN on an empty slot silently re-ran the "acquire" branch and
    # grabbed your own selection -- so a plain open-hand with nothing
    # incoming quietly became a phantom grab, corrupting grabbed_by for the
    # real transfer. Splitting them removes that ambiguity entirely.

    def grab(self, device_id: str) -> dict:
        """CLOSE hand: acquire this device's current selection as the item
        in transit. Returns one of:
          - "grabbed": newly picked up, item in transit
          - "already_grabbed": this same device already holds it (no-op)
          - "busy": a DIFFERENT device already has something in transit
          - "nothing_to_hold": nothing is selected on this device to grab
        """
        session = self.devices[device_id]
        person_id = session.person_id
        item = self.held.get(person_id)

        if item is not None:
            if self.grabbed_by.get(person_id) == device_id:
                return {"action": "already_grabbed", "item": item}
            return {"action": "busy", "item": item}

        if not session.selection:
            return {"action": "nothing_to_hold"}

        contents = [
            ContentPiece(
                content_type=entry["content_type"],
                content=entry["content"],
                filename=entry.get("filename"),
            )
            for entry in session.selection
        ]
        item = HeldItem(contents=contents, origin_device=device_id)
        self.held[person_id] = item
        self.grabbed_by[person_id] = device_id
        return {"action": "grabbed", "item": item}

    def release(self, device_id: str) -> dict:
        """OPEN hand: deliver the in-transit item to THIS device -- but only
        if it was grabbed on a DIFFERENT device. Returns one of:
          - "delivered": received here, transfer complete (slot cleared)
          - "same_device": you grabbed it here; walk to another device first
          - "nothing_held": nothing is currently in transit
        """
        session = self.devices[device_id]
        person_id = session.person_id
        item = self.held.get(person_id)

        if item is None:
            return {"action": "nothing_held"}

        if self.grabbed_by.get(person_id) == device_id:
            return {"action": "same_device", "item": item}

        item.delivered_to.add(device_id)
        # Single-hop delivery: the transfer is complete once a different
        # device receives it, freeing the slot for the next grab.
        self.held[person_id] = None
        self.grabbed_by.pop(person_id, None)
        return {"action": "delivered", "item": item}

    def cancel_transfer(self, person_id: str) -> dict:
        """Cancel an in-transit item without delivering it anywhere (e.g. the
        Cancel button on a receiving device's incoming-transfer preview)."""
        item = self.held.get(person_id)
        if item is None:
            return {"action": "noop"}
        self.held[person_id] = None
        self.grabbed_by.pop(person_id, None)
        return {"action": "cancelled", "item": item}

    # -- gesture debounce ----------------------------------------------

    def stable_gesture(self, device_id: str, hand_sign: str) -> Optional[str]:
        """Turns a noisy per-frame classification into an edge-triggered
        signal: returns `hand_sign` only on the single frame where it BECOMES
        stable (seen GESTURE_STABILITY_FRAMES times in a row and wasn't the
        last thing acted on), else None.

        Exists because a raw single-frame trigger reacts to the ~0.3s your
        hand spends transitioning through a fist-like shape while relaxing
        after an Open gesture -- which, fed straight into close_hand(),
        releases whatever you just picked up before you can walk anywhere.
        """
        session = self.devices[device_id]
        if hand_sign == session._pending_sign:
            session._pending_count += 1
        else:
            session._pending_sign = hand_sign
            session._pending_count = 1

        if (
            session._pending_count >= GESTURE_STABILITY_FRAMES
            and session._confirmed_sign != hand_sign
        ):
            session._confirmed_sign = hand_sign
            return hand_sign
        return None

    # -- face-match convenience layer (session-only) -------------------

    def enroll_face(self, person_id: str, vector: list[float]) -> None:
        self.face_embeddings.setdefault(person_id, []).append(vector)
        # Cap how many samples we keep per person; oldest first out.
        if len(self.face_embeddings[person_id]) > 5:
            self.face_embeddings[person_id].pop(0)

    def link_code_for(self, person_id: str) -> Optional[str]:
        return self.person_link_code.get(person_id)

    def match_face(self, vector: list[float]) -> tuple[Optional[str], float]:
        """Cosine similarity against every enrolled person. Returns (person_id, score)."""
        best_person, best_score = None, 0.0
        for person_id, samples in self.face_embeddings.items():
            for sample in samples:
                score = _cosine_similarity(vector, sample)
                if score > best_score:
                    best_person, best_score = person_id, score
        return best_person, best_score


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
