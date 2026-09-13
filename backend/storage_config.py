r"""Storage configuration for models and data.

All models are stored on D: drive (or user-configured location) to avoid
filling up the C: drive. Set GESTURE_HOLD_STORAGE env var to override.

Default: D:\gesture-hold-data
"""
from __future__ import annotations

import os
from pathlib import Path


def get_storage_dir() -> Path:
    """Get the storage directory for models and cache.

    Priority:
    1. GESTURE_HOLD_STORAGE env var
    2. D:\gesture-hold-data (default, free storage)
    3. System temp directory (fallback)
    """
    # Check environment variable first
    env_path = os.getenv("GESTURE_HOLD_STORAGE")
    if env_path:
        path = Path(env_path)
        path.mkdir(parents=True, exist_ok=True)
        return path

    # Try D: drive (primary choice)
    d_drive = Path("D:/gesture-hold-data")
    try:
        d_drive.mkdir(parents=True, exist_ok=True)
        return d_drive
    except Exception:
        pass

    # Fallback to C: (should rarely happen if D: is available)
    fallback = Path.home() / ".gesture-hold-data"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def get_insightface_home() -> Path:
    r"""Get the directory for InsightFace models (~340MB).

    Default: D:\gesture-hold-data\insightface
    """
    base = get_storage_dir()
    face_dir = base / "insightface"
    face_dir.mkdir(parents=True, exist_ok=True)
    return face_dir


def configure_insightface():
    """Set environment variables for InsightFace to use D: drive."""
    insightface_home = str(get_insightface_home())
    os.environ["INSIGHTFACE_HOME"] = insightface_home
    # Also set the model download cache
    os.environ["HF_HOME"] = str(get_storage_dir() / "huggingface")
    print(f"[storage] InsightFace models: {insightface_home}")


def get_storage_usage() -> dict[str, float]:
    """Return storage usage stats (in MB) for all subdirectories."""
    base = get_storage_dir()
    usage = {}

    if not base.exists():
        return usage

    for item in base.iterdir():
        if item.is_dir():
            size_mb = sum(
                f.stat().st_size for f in item.rglob("*") if f.is_file()
            ) / (1024 * 1024)
            usage[item.name] = round(size_mb, 2)

    return usage


if __name__ == "__main__":
    configure_insightface()
    print(f"Storage directory: {get_storage_dir()}")
    print(f"InsightFace home: {get_insightface_home()}")
    usage = get_storage_usage()
    if usage:
        print("Storage usage:")
        for name, size_mb in sorted(usage.items(), key=lambda x: x[1], reverse=True):
            print(f"  {name}: {size_mb:.2f} MB")
    else:
        print("Storage is empty (models will be downloaded on first use)")
