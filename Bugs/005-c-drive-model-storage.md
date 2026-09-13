# 005 — InsightFace models filled the C: drive

**Severity:** Medium — cost a lost afternoon once; recurring risk on any fresh machine.

## Symptom

C: drive dropped to 0 bytes free during initial setup. Investigation traced it to the `buffalo_l` face-recognition model bundle (~340MB) downloading to `~/.insightface`.

## Root cause

The installed version of `insightface` has **no environment-variable override** for its model cache directory — every download path in `insightface/utils/storage.py` and `utils/filesystem.py` hardcodes `root='~/.insightface'` as a Python default *parameter*, not something read from an env var. Setting `INSIGHTFACE_HOME` alone (the documented approach for newer versions) does nothing on this version.

## Fix

Pass `root=` explicitly into every `FaceAnalysis(...)` construction (`backend/face_engine.py`'s `_build()`), pointed at a project-local `.insightface_cache` directory. Later generalized into `backend/storage_config.py`, which resolves a configurable storage root (`GESTURE_HOLD_STORAGE` env var, defaulting to `D:\gesture-hold-data`) so model downloads land on whichever drive actually has room, not wherever the library's own default happens to point.

## Verification

- `python -c "from backend.storage_config import get_storage_dir; print(get_storage_dir())"` confirms the resolved path.
- Booted the server fresh and confirmed the log line `[storage] InsightFace models: D:\gesture-hold-data\insightface` before any model download starts, and that C: drive usage doesn't move.
