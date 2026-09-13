# Gesture Hold & Transfer

Touchless, multi-device, multi-person file transfer over local WiFi. Select text/files/images on one device, **close your hand (fist)** to grab them, walk to another device, and **open your hand (palm)** to receive — the Huawei AirShare model, built on MediaPipe hand tracking + InsightFace recognition, with no cloud, no accounts, and no internet required.

## Quick Start

```powershell
# 1. Install dependencies
pip install -r backend/requirements.txt

# 2. Run the server (models auto-download to D: drive by default)
python run_https.py

# 3. Open on any device on the same WiFi
https://<your-lan-ip>:8443
# Accept the self-signed certificate warning on first load
```

See [QUICK_START.md](QUICK_START.md) for a step-by-step walkthrough of the gesture flow.

## How It Works

1. **Select** something on a device — type text, or choose one or more files/images (multi-file selection bundles everything into one transfer).
2. **Close your hand (fist)** on that device — grabs the selection; it enters transit.
3. **Walk to another device** — the item stays "in transit," visible with a live preview and a **Cancel** button on every device this person is signed into.
4. **Open your hand (palm)** on a *different* device — delivers the whole bundle there. Opening your hand on the same device that grabbed it does nothing (prevents accidental self-delivery — see [Bugs/001](Bugs/001-shared-open-hand-self-delivery.md)).

Transfers are **person-tracked, not device-tracked**: the same person's laptop, phone, and tablet all recognize each other (via a link code, or automatically via face recognition once one device has seen you), while a different person using the app at the same time is fully isolated — no crosstalk, no artificial cap on how many people or devices can be connected at once.

## Features

- **Gesture-based transfer** — close hand to grab, open hand to release, cross-device only
- **Multi-file bundles** — select text plus any number of files/images, grab once, deliver all of them together
- **Multi-device, multi-person** — several people can each use several devices simultaneously with no interference
- **Cancel anytime** — abort an in-flight transfer from any of your devices without a gesture
- **Camera on/off toggle** — fully stops the camera, hand detection, and face frames when off (saves CPU/battery)
- **Auto-reconnect** — survives WiFi blips and phone screen locks (exponential backoff)
- **15-minute grace period** — a dropped socket doesn't invalidate your link code instantly
- **Face recognition auto-join** — walk up to a second device and it recognizes you, no code needed
- **Gesture discrimination** — a 3-test confidence filter (pose confidence, motion spike, gesture lock) rejects fidgeting and accidental hand-relaxing
- **Local-only** — self-signed HTTPS on your LAN; nothing leaves your network, nothing persists after the server restarts

## System Requirements

- **OS**: Windows 10/11 (paths and scripts are Windows-oriented; the Python/FastAPI core is portable)
- **Storage**: ~340MB for face-recognition models — configurable via `GESTURE_HOLD_STORAGE` (defaults to `D:\gesture-hold-data`, falls back to `~/.gesture-hold-data` if unavailable)
- **Camera**: one per device, for hand tracking and face recognition
- **Network**: local WiFi only — no internet needed to run

## Documentation

| Document | Purpose |
|----------|---------|
| **[QUICK_START.md](QUICK_START.md)** | Step-by-step gesture flow, color-coded confidence, common mistakes |
| **[DEPLOYMENT.md](DEPLOYMENT.md)** | Full setup, multi-user flows, troubleshooting |
| **[GESTURE_DEBUG.md](GESTURE_DEBUG.md)** | How gesture classification + discrimination works |
| **[IMPROVEMENTS.md](IMPROVEMENTS.md)** | Historical technical changelog |
| **[Bugs/](Bugs/README.md)** | Every real bug hit during development — symptom, root cause, fix, verification |

## Configuration

| Environment Variable | Default | Purpose |
|---|---|---|
| `GESTURE_HOLD_STORAGE` | `D:\gesture-hold-data` | Where face-recognition models download to |
| `GESTURE_FACE_GPU` | `0` (CPU) | Set to `1` to opt into DirectML GPU inference for face recognition — off by default because it has been observed to crash the process natively on some GPUs; see [Bugs/003](Bugs/003-directml-native-crash.md) |
| `GESTURE_FACE_MODEL` | `buffalo_l` | InsightFace model bundle name |
| `GESTURE_FACE_MIN_DET` | `0.5` | Minimum face-detection confidence to accept a match |

## Architecture

```
Any device (browser)
├── Camera feed + MediaPipe HandLandmarker (local, ~15fps)
├── Live gesture readout (color-coded confidence: green/orange/gray)
├── Multi-file selection queue -> one bundled grab
└── WebSocket: landmarks out, gesture/transfer/presence updates in

Server (FastAPI + Uvicorn, one process)
├── Gesture classification (TensorFlow Lite, CPU)
├── Gesture discrimination (pose confidence + motion spike + gesture lock)
├── Face recognition (InsightFace SCRFD + ArcFace, CPU by default)
├── SessionManager: identity, presence, and the grab/carry/release state machine
└── In-memory only -- nothing persists across a restart, 15-min grace on disconnect

Network: local WiFi only, self-signed HTTPS certificate (auto-generated on first run)
```

## Testing

```bash
# Full unit test suite
python -m pytest tests/ -v

# Check live multi-user status
curl -k https://localhost:8443/status

# Verify model storage location
python -c "from backend.storage_config import get_storage_dir; print(get_storage_dir())"
```

## Troubleshooting

**Gestures won't fire?**
Check the gesture-readout color: green = will fire, orange = borderline, gray = too low confidence (make a clearer fist / more open palm). See [GESTURE_DEBUG.md](GESTURE_DEBUG.md).

**Opened your hand but nothing transferred?**
You may have opened it on the *same* device that grabbed the item — that's intentional (see [Bugs/001](Bugs/001-shared-open-hand-self-delivery.md)). Walk to a different device and open your hand there.

**"Unknown link code" after a WiFi blip?**
Codes survive 15 minutes of disconnection — rejoin within that window with the same code. See [Bugs/004](Bugs/004-link-code-instant-destruction.md).

**Server exits with no error message?**
If it happens right after a "ready on gpu (DirectML)" log line, that's a native GPU crash — face recognition defaults to CPU now specifically to avoid this. Confirm `GESTURE_FACE_GPU` isn't set to `1`. See [Bugs/003](Bugs/003-directml-native-crash.md).

**Models downloading to C: instead of D:?**
```powershell
$env:GESTURE_HOLD_STORAGE = "D:\gesture-hold-data"
python run_https.py
```

## Credits

- Hand detection: MediaPipe HandLandmarker
- Face recognition: InsightFace (`buffalo_l`, SCRFD + ArcFace)
- Gesture classification: TensorFlow Lite
- Server: FastAPI + Uvicorn
- Originally inspired by [kinivi/hand-gesture-recognition-mediapipe](https://github.com/kinivi/hand-gesture-recognition-mediapipe)

## License

Open source — use and modify freely.
