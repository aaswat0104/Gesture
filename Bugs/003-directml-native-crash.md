# 003 — DirectML GPU face inference crashed the whole process

**Severity:** Critical — the entire server died mid-session with no error message.

## Symptom

Server log:
```
2026-09-13 13:38:30,582 INFO app.face_engine: face_engine: buffalo_l ready on gpu (DirectML)
2026-09-13 13:38:34,838 INFO app.presence: JOIN device='device' ...
[process exits -- no traceback, no "Shutting down", straight back to the PS prompt]
```

User had to manually relaunch the server multiple times per session, losing all in-memory state each time (link codes, held items) — presenting as "it's closing on its own."

## Root cause

DirectML on the user's GPU (RTX 2050) loads successfully (`FaceAnalysis.prepare()` succeeds and logs "ready on gpu") but crashes with a **native access violation inside the ONNX Runtime / DirectML DLL** during actual inference (`app.get(img)`), not at load time. A native crash like this bypasses every Python `try/except` — there is no way to catch it after the fact, because the OS terminates the process before any Python exception handler runs.

This is the same category of problem as an earlier fix (a broken TFLite GPU delegate for gesture classification), but on the face-recognition path this time, and less visible because the failure only manifests once a real frame is embedded, not at startup.

## Fix

`backend/face_engine.py`: made GPU (DirectML) **opt-in only** via `GESTURE_FACE_GPU=1`, defaulting to CPU. Face recognition only runs every 2-6 seconds (see `frontend/app.js`'s `FACE_ENROLL_INTERVAL_MS`), so CPU's extra ~50-150ms per frame is invisible — there's no real performance reason to risk GPU instability here.

## Verification

- Loaded the CPU-only engine and ran `embed_frame()` through the full SCRFD+ArcFace pipeline on a real JPEG — completed without crashing.
- Booted the actual server, confirmed log line reads `face_engine: buffalo_l ready on cpu` (not gpu), then ran a full multi-device grab/release session end-to-end (visible in later server logs) without the process dying.
