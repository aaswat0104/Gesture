"""SCRFD detection + ArcFace embeddings, via InsightFace's buffalo_l bundle.

Ported from the CIMS project's services/geo_reports/faces.py -- same model,
same CPU-tuned ONNX Runtime session options, same "never raises, degrades to
no-match" contract. Trimmed down for this app's shape: CIMS matches many
stored photos against a database of reports; this only ever needs one face
embedding from one live frame, compared against a few in-memory vectors
already held by session_manager.py. No SQLite, no retention job, no batching
-- that machinery earns its keep at CIMS's scale, not at "two devices, one
person's face."

Calibration carried over from CIMS's own measurements on real photos: cosine
similarity for two DIFFERENT people topped out at 0.218, and the same person
normally lands above 0.40. session_manager.probe_face() uses 0.40 as the
"good enough to suggest" floor for that reason.
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Optional

# Must be set BEFORE onnxruntime/insightface get imported anywhere (including
# transitively) -- ONNX Runtime and the oneDNN backend it pulls in read these
# once at their own init time, not per-call. Same model, same det_size, same
# accuracy: this only tells the CPU execution provider to actually use every
# core instead of whatever default thread count it guessed, which is the
# "optimize the pipeline, don't touch accuracy" lever requested.
os.environ.setdefault("OMP_NUM_THREADS", str(os.cpu_count() or 4))
os.environ.setdefault("ORT_NUM_THREADS", str(os.cpu_count() or 4))

import cv2  # module-level: avoids re-import bookkeeping on every embed_frame() call
import numpy as np

# This version of insightface has NO env-var override for its model cache --
# every download path (utils/storage.py, utils/filesystem.py) hardcodes
# root='~/.insightface' as a default *parameter*, not an env lookup. The only
# real redirect is passing root= explicitly into FaceAnalysis(), which is
# what _load() does below. Left at its default this lands in ~/.insightface
# on the C: drive, which cost a lost afternoon once already on this machine.
_MODEL_ROOT = str(Path(__file__).resolve().parents[1] / ".insightface_cache")

log = logging.getLogger("app.face_engine")

_MODEL = os.getenv("GESTURE_FACE_MODEL", "buffalo_l")
_MIN_DET = float(os.getenv("GESTURE_FACE_MIN_DET", "0.5"))
# Default OFF: DirectML on this GPU (RTX 2050) has been observed to crash the
# whole Python process during actual inference (app.get()), not just at load
# time -- a native access violation in the DirectML/ONNX Runtime DLL, which
# bypasses every Python try/except and kills the server with no traceback.
# Face recognition only runs every 2-6s (see main.py's FACE_ENROLL_INTERVAL_MS
# equivalent), so CPU's extra ~50-150ms per frame is invisible; it isn't worth
# trading server stability for. Set GESTURE_FACE_GPU=1 to opt back into GPU.
_GPU_REQUESTED_BY_USER = os.getenv("GESTURE_FACE_GPU", "0") == "1"

_app = None
_app_lock = threading.Lock()
_load_failed = False


def _build(providers: list[str], ctx_id: int):
    from insightface.app import FaceAnalysis

    app = FaceAnalysis(
        name=_MODEL,
        root=_MODEL_ROOT,
        providers=providers,
        allowed_modules=["detection", "recognition"],
    )
    app.prepare(ctx_id=ctx_id, det_size=(320, 320))
    return app


def _load():
    """Loads once, lazily. CPU by default -- see _GPU_REQUESTED_BY_USER above
    for why DirectML is opt-in rather than auto-detected: a crash during
    actual inference is a native access violation, not a Python exception,
    so there is no try/except that can catch it and fall back after the
    fact. The only safe way to avoid it is to not select that provider
    unless the user has explicitly asked for it via GESTURE_FACE_GPU=1."""
    global _app, _load_failed
    if _app is not None or _load_failed:
        return _app
    with _app_lock:
        if _app is not None or _load_failed:
            return _app

        if _GPU_REQUESTED_BY_USER:
            import onnxruntime as ort

            if "DmlExecutionProvider" in ort.get_available_providers():
                try:
                    _app = _build(["DmlExecutionProvider", "CPUExecutionProvider"], ctx_id=0)
                    log.info(f"face_engine: {_MODEL} ready on gpu (DirectML) -- opted in via GESTURE_FACE_GPU=1")
                    return _app
                except Exception as e:
                    log.warning(f"face_engine: GPU init failed ({e}), falling back to cpu")
            else:
                log.warning("face_engine: GESTURE_FACE_GPU=1 set but DmlExecutionProvider unavailable, using cpu")

        try:
            _app = _build(["CPUExecutionProvider"], ctx_id=-1)
            log.info(f"face_engine: {_MODEL} ready on cpu")
        except Exception as e:
            _load_failed = True
            log.warning(f"face_engine: model unavailable, face matching disabled ({e})")
    return _app


def available() -> bool:
    return _load() is not None


def embed_frame(jpeg_bytes: bytes) -> Optional[list[float]]:
    """One face embedding (512-d, L2-normalized) from a single JPEG frame.

    Picks the largest detected face if more than one is in frame -- the
    person looking at their own device's camera is presumed to be the
    subject, not whoever walks past in the background.

    Blocking (ONNX + OpenCV decode): call via asyncio.to_thread from the
    WebSocket handler, never directly on the event loop.
    """
    app = _load()
    if app is None or not jpeg_bytes:
        return None
    try:
        arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return None
        faces = [f for f in app.get(img) if float(f.det_score) >= _MIN_DET]
        if not faces:
            return None
        faces.sort(key=lambda f: -(f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
        return [float(v) for v in faces[0].normed_embedding]
    except Exception as e:
        log.warning(f"face_engine: embed failed: {e}")
        return None
