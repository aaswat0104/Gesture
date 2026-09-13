"""Single FastAPI app: serves the frontend and the one /ws endpoint that
carries everything (landmarks in, gesture/state updates out). Deliberately
one process, one file tying the pieces together -- no microservices, no
message queue, no database.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import time

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from backend import clarification, face_engine
from backend.inference import GestureEngine, pre_process_point_history
from backend.session_manager import DeviceSession, SessionManager, UnknownLinkCode
from backend.gesture_discriminator import GestureDiscriminator, compute_pose_confidence
from backend.hand_identifier import hand_geometry_vector, hand_matches_person

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")
presence_log = logging.getLogger("app.presence")

app = FastAPI()
manager = SessionManager()
connections: dict[str, WebSocket] = {}
engines: dict[str, GestureEngine] = {}
discriminators: dict[str, GestureDiscriminator] = {}  # device_id -> gesture filter
_last_hand_sign: dict[str, str] = {}  # device_id -> last logged sign, to log only on change
_hand_samples: dict[str, list[list[float]]] = {}  # person_id -> hand geometry samples (for ID)


def _decode_and_embed(data_url: str) -> list[float] | None:
    """Strips a "data:image/jpeg;base64,..." prefix, decodes it, runs it
    through the face engine. Blocking -- callers must run this in a thread."""
    if not data_url:
        return None
    try:
        raw = data_url.split(",", 1)[1] if "," in data_url else data_url
        jpeg_bytes = base64.b64decode(raw)
    except Exception:
        return None
    return face_engine.embed_frame(jpeg_bytes)


@app.get("/status")
async def status() -> dict:
    """Multi-user system status. Shows all active people and their devices.

    Persists in-memory only (session-only privacy: nothing here survives restart).
    """
    devices = [
        {
            "device_id": d.device_id,
            "device_name": d.device_name,
            "person_id": d.person_id,
            "connected": d.device_id in connections,
        }
        for d in manager.devices.values()
    ]

    # Group devices by person
    people = {}
    for person_id in manager.person_devices:
        if manager.person_devices[person_id]:  # Only people with active devices
            devices_for_person = [
                d for d in devices
                if d["person_id"] == person_id and d["connected"]
            ]
            if devices_for_person:
                people[person_id] = {
                    "person_id": person_id,
                    "devices": devices_for_person,
                    "hand_samples": len(_hand_samples.get(person_id, [])),  # For debugging
                    "is_holding": manager.held.get(person_id) is not None,
                }

    return {
        "device_count": len(devices),
        "person_count": manager.active_person_count(),
        "devices": devices,
        "people": people,  # NEW: grouped by person
        "system_info": {
            "grace_period_sec": 900,
            "gesture_discriminator_enabled": True,
            "hand_identification_enabled": True,
        },
    }


async def _safe_send(ws: WebSocket, payload: dict, device_id: str | None = None) -> None:
    """A socket can be mid-close (another task already got a disconnect for
    it) between us reading `connections` and actually sending -- that's a
    race, not a bug in the caller, so it must never take the whole handler
    down. Drop the dead connection here rather than re-raising."""
    try:
        await ws.send_json(payload)
    except Exception:
        if device_id is not None:
            connections.pop(device_id, None)


async def _broadcast_presence() -> None:
    payload = {
        "type": "presence",
        "device_count": len(manager.devices),
        "person_count": manager.active_person_count(),
    }
    for device_id, ws in list(connections.items()):
        await _safe_send(ws, payload, device_id)


def _device_name(device_id: str | None) -> str:
    session = manager.devices.get(device_id) if device_id else None
    return session.device_name if session else "unknown device"


async def _broadcast_device_list(person_id: str) -> None:
    """Feeds the "Your devices" panel: sent whenever a person's own device
    roster changes (join / disconnect), scoped to just that person's
    devices -- unlike presence, which is a global count for everyone."""
    device_ids = manager.devices_for(person_id)
    payload = {
        "type": "device_list",
        "devices": [{"device_id": d, "device_name": _device_name(d)} for d in device_ids],
    }
    await _broadcast_to_person(person_id, payload)


def _content_items(item) -> list[dict]:
    """Serialize a HeldItem's bundle of ContentPieces for the wire."""
    return [
        {"content_type": c.content_type, "content": c.content, "filename": c.filename}
        for c in item.contents
    ]


def _item_summary(item) -> str:
    """Short human-readable label for logs: "photo.jpg" or "3 items"."""
    if len(item.contents) == 1:
        c = item.contents[0]
        return c.filename or c.content_type
    return f"{len(item.contents)} items"


def _transfer_pending_payload(item, grabbed_by_device_id: str) -> dict:
    """Sent to every device of the person right after a successful grab.
    The grabbing device sees "you're carrying this, walk elsewhere"; every
    other device sees an incoming-transfer preview with a Cancel option.
    `items` is always a list -- one entry for a single file, several for a
    bundled multi-file grab -- so the client renders both the same way."""
    return {
        "type": "transfer_pending",
        "items": _content_items(item),
        "grabbed_by_device_id": grabbed_by_device_id,
        "grabbed_by_device_name": _device_name(grabbed_by_device_id),
    }


def _transfer_delivered_payload(item, delivered_to_device_id: str) -> dict:
    """Sent to every device of the person once release() completes the hop."""
    return {
        "type": "transfer_delivered",
        "items": _content_items(item),
        "origin_device_name": _device_name(item.origin_device),
        "delivered_to_device_id": delivered_to_device_id,
        "delivered_to_device_name": _device_name(delivered_to_device_id),
    }


async def _broadcast_to_person(person_id: str, payload: dict) -> None:
    for device_id in manager.devices_for(person_id):
        ws = connections.get(device_id)
        if ws is not None:
            await _safe_send(ws, payload, device_id)


async def _apply_gesture_action(device_id: str, hand_sign: str, ws: WebSocket) -> None:
    """
    Gesture semantics (Huawei AirShare / "hot potato" model):
    - CLOSE (fist): grab() -- pick up this device's selection, item enters transit
    - OPEN (palm): release() -- deliver the in-transit item to THIS device,
      but ONLY if it was grabbed on a DIFFERENT device

    Flow: Select on A -> Close hand on A (grab) -> walk to B ->
          Open hand on B (receive, transfer complete, slot freed)

    SAFETY: Opening your hand on the same device that grabbed the item does
    nothing -- see session_manager.SessionManager.release() for why grab()
    and release() are two separate methods instead of one shared handler.
    """
    session = manager.devices[device_id]
    person_id = session.person_id

    if hand_sign == "Close":
        result = manager.grab(device_id)
        action = result["action"]
        if action == "nothing_to_hold":
            await ws.send_json({"type": "clarify_request", **clarification.NOTHING_SELECTED})
        elif action == "grabbed":
            item = result["item"]
            log.info(f"GRAB device={session.device_name!r} grabbed {_item_summary(item)!r}")
            await _broadcast_to_person(person_id, _transfer_pending_payload(item, device_id))
        elif action == "already_grabbed":
            pass  # idempotent -- already carrying it, no need to re-announce
        elif action == "busy":
            item = result["item"]
            await ws.send_json({
                "type": "clarify_request",
                "question": (
                    f"Already carrying {_item_summary(item)!r} from "
                    f"{_device_name(item.origin_device)}. Deliver or cancel it first."
                ),
                "options": [],
            })

    elif hand_sign == "Open":
        result = manager.release(device_id)
        action = result["action"]
        if action == "same_device":
            log.info(f"OPEN_SAME_DEVICE device={session.device_name!r} grabbed here -- walk elsewhere to deliver")
            await ws.send_json({
                "type": "clarify_request",
                "question": "You grabbed this on THIS device. Walk to another device and open your hand there to deliver it.",
                "options": [],
            })
        elif action == "delivered":
            item = result["item"]
            log.info(f"DELIVER device={session.device_name!r} received {_item_summary(item)!r} from {_device_name(item.origin_device)!r}")
            await _broadcast_to_person(person_id, _transfer_delivered_payload(item, device_id))
        elif action == "nothing_held":
            pass  # nothing incoming -- silent no-op


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    device_id: str | None = None

    try:
        while True:
            data = await websocket.receive_json()
            mtype = data.get("type")

            if mtype == "face_probe" and device_id is None:
                # This IS the "walk to any device and it recognizes you"
                # behaviour: a confident match auto-joins with no code entry
                # at all. A weaker-but-plausible match still gets suggested
                # (prefilled, not submitted) so a borderline read doesn't
                # silently link the wrong person's session.
                embedding = await asyncio.to_thread(_decode_and_embed, data.get("frame", ""))
                link_code, auto = None, False
                if embedding:
                    matched_person, score = manager.match_face(embedding)
                    if matched_person is not None and score >= 0.40:
                        link_code = manager.link_code_for(matched_person)
                        auto = score >= 0.50
                await websocket.send_json(
                    {"type": "face_suggestion", "link_code": link_code, "auto": auto}
                )
                continue

            if mtype == "join":
                try:
                    session: DeviceSession = manager.join(
                        data.get("link_code"), data.get("device_name", "device")
                    )
                except UnknownLinkCode:
                    await websocket.send_json({"type": "error", "message": "Unknown link code"})
                    continue
                device_id = session.device_id
                connections[device_id] = websocket
                presence_log.info(
                    f"JOIN device={session.device_name!r} device_id={device_id[:8]} "
                    f"person_id={session.person_id[:8]} at {time.strftime('%Y-%m-%d %H:%M:%S')}"
                )
                await websocket.send_json(
                    {
                        "type": "joined",
                        "device_id": device_id,
                        "person_id": session.person_id,
                        "link_code": getattr(session, "_link_code", None),
                    }
                )
                # Newly joined device: if a transfer is currently in flight for
                # this person, bring it up to speed immediately instead of
                # leaving it blind until the next grab/release event.
                pending_item = manager.held.get(session.person_id)
                if pending_item is not None:
                    grabber = manager.grabbed_by.get(session.person_id)
                    await websocket.send_json(_transfer_pending_payload(pending_item, grabber))
                await _broadcast_device_list(session.person_id)
                await _broadcast_presence()
                continue

            if device_id is None:
                await websocket.send_json({"type": "error", "message": "Send 'join' first"})
                continue

            session = manager.devices[device_id]

            if mtype == "select_content":
                # `items` is always a list -- one text entry plus any number
                # of files/images the client has queued, all bundled into
                # one grab. The client resends the whole list on every
                # change (add/remove/edit), so this just replaces it.
                items = data.get("items", [])
                manager.set_selection(device_id, items)
                log.info(
                    f"select_content device={session.device_name!r} "
                    f"queued={len(items)} item(s): "
                    f"{[i.get('filename') or i['content_type'] for i in items]}"
                )

            elif mtype == "hand_landmarks":
                engine = engines.get(device_id)
                if engine is None:
                    engine = engines[device_id] = GestureEngine()

                discriminator = discriminators.get(device_id)
                if discriminator is None:
                    discriminator = discriminators[device_id] = GestureDiscriminator()

                landmarks = data["landmarks"]
                hand_sign = engine.classify_hand_sign(landmarks)

                # Compute hand pose confidence (how "open" or "closed")
                pose_confidence = compute_pose_confidence(landmarks, hand_sign)

                # Store hand geometry for person identification
                hand_geom = hand_geometry_vector(landmarks)
                if hand_geom:
                    _hand_samples.setdefault(session.person_id, []).append(hand_geom)
                    # Keep only last 8 samples per person
                    if len(_hand_samples[session.person_id]) > 8:
                        _hand_samples[session.person_id].pop(0)

                if _last_hand_sign.get(device_id) != hand_sign:
                    _last_hand_sign[device_id] = hand_sign
                    log.info(
                        f"gesture device={session.device_name!r} hand_sign={hand_sign!r} "
                        f"confidence={pose_confidence:.2f}"
                    )

                # HIGH-CONFIDENCE gesture discrimination:
                # Only fire Open/Close if the gesture is intentional, not fidgeting
                gesture_event = discriminator.process(
                    hand_sign=hand_sign,
                    landmarks=landmarks,
                    pose_confidence=pose_confidence,
                )

                if hand_sign == "Pointer" and len(landmarks) > 8:
                    session.point_history.append(list(landmarks[8]))
                else:
                    session.point_history.append([0, 0])

                finger_gesture = None
                if len(session.point_history) == session.point_history.maxlen:
                    processed = pre_process_point_history(list(session.point_history))
                    finger_gesture = engine.classify_finger_gesture(processed)

                await websocket.send_json(
                    {
                        "type": "gesture_result",
                        "hand_sign": hand_sign,
                        "finger_gesture": finger_gesture,
                        "pose_confidence": round(pose_confidence, 2),
                        "motion_level": round(
                            discriminator.motion_magnitude_history[-1]
                            if discriminator.motion_magnitude_history
                            else 0, 2
                        ),
                    }
                )
                # Only act on high-confidence gestures (not fidgeting)
                if gesture_event:
                    log.info(
                        f"HIGH_CONFIDENCE_GESTURE device={session.device_name!r} "
                        f"gesture={gesture_event.gesture!r} confidence={gesture_event.confidence:.2f} "
                        f"reason={gesture_event.reason}"
                    )
                    await _apply_gesture_action(device_id, gesture_event.gesture, websocket)

            elif mtype == "face_frame":
                # After joining: keep enrolling (builds up a few samples per
                # person) and report back the live match confidence, so the
                # UI can show "recognized" without it gating anything --
                # account identity already governs the actual transfer.
                embedding = await asyncio.to_thread(_decode_and_embed, data.get("frame", ""))
                if embedding:
                    manager.enroll_face(session.person_id, embedding)
                    matched_person, score = manager.match_face(embedding)
                    await websocket.send_json(
                        {
                            "type": "face_match",
                            "matched": matched_person == session.person_id,
                            "score": round(score, 2),
                        }
                    )

            elif mtype == "cancel_transfer":
                result = manager.cancel_transfer(session.person_id)
                if result["action"] == "cancelled":
                    log.info(f"CANCEL device={session.device_name!r} cancelled the in-flight transfer")
                    await _broadcast_to_person(
                        session.person_id,
                        {"type": "transfer_cancelled", "cancelled_by_device_name": session.device_name},
                    )

            elif mtype == "voice_text":
                action = clarification.match_voice_command(data.get("text", ""))
                if action == "open_hand":
                    await _apply_gesture_action(device_id, "Open", websocket)
                elif action == "close_hand":
                    await _apply_gesture_action(device_id, "Close", websocket)
                else:
                    await websocket.send_json({"type": "voice_unrecognized"})

            elif mtype == "clarify_response":
                result = clarification.resolve(
                    data.get("choice", ""), data.get("other_text", ""), session.selection
                )
                await websocket.send_json({"type": "clarify_result", **result})

    except WebSocketDisconnect:
        pass
    except Exception:  # self-repair: log and drop this connection, keep the server up
        log.exception("WebSocket handler error, closing connection")
    finally:
        if device_id is not None:
            leaving_session = manager.devices.get(device_id)
            name = leaving_session.device_name if leaving_session else "?"
            person_id = leaving_session.person_id if leaving_session else None
            manager.disconnect_device(device_id)
            connections.pop(device_id, None)
            engines.pop(device_id, None)
            discriminators.pop(device_id, None)
            _last_hand_sign.pop(device_id, None)
            presence_log.info(
                f"LEAVE device={name!r} device_id={device_id[:8]} "
                f"at {time.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            if person_id is not None:
                await _broadcast_device_list(person_id)
            await _broadcast_presence()


app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
