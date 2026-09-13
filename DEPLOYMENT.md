# Deployment Guide: Gesture Hold & Transfer

## 1. Storage Setup (D: Drive)

The system now stores all large models on your **D: drive** to avoid filling C: drive.

### Automatic Setup
Models automatically download to: `D:\gesture-hold-data\insightface` (~340MB)

### Manual Setup (if D: isn't available)
Set environment variable before running:
```powershell
$env:GESTURE_HOLD_STORAGE = "D:\my-custom-path"  # or any path with free space
python run_https.py
```

### Verify Storage
```powershell
python -c "from backend.storage_config import get_storage_usage; print(get_storage_usage())"
```

---

## 2. Running the Server

### Quick Start
```powershell
cd D:\Users\Aaswat\Downloads\opencv-file-opener-main
python run_https.py
```

You'll see:
```
===================================================================
  On this PC:        https://localhost:8443
  On your phone:     https://192.168.31.49:8443
  (accept the self-signed certificate warning on first load)
===================================================================
```

### Accessing from Other Devices
1. Go to: `https://<YOUR-IP>:8443` on any device on the same WiFi
2. Accept the self-signed certificate warning (tap "Advanced" → "Proceed")
3. Allow camera access when prompted

---

## 3. Multi-User System

Multiple people can use the app **simultaneously**. Each person gets their own:
- Link code (e.g., `AB12CD`)
- Held items (files/text)
- Hand geometry profile (for person identification)

### Example Multi-User Flow
```
Person A (Laptop) → opens hand, picks up file → "Opened on Laptop"
Person B (Phone) → arrives, sees their own link code
Person A (Phone) → walks over, opens hand → receives the file

Meanwhile:
Person C (Desktop) → joins separately, opens own file
→ All three operating independently
```

### Check Active Users
```bash
curl -k https://localhost:8443/status
```

Returns:
```json
{
  "person_count": 3,
  "device_count": 5,
  "people": {
    "personA_id": {
      "devices": [{"device_name": "laptop"}, {"device_name": "phone"}],
      "is_holding": true
    },
    "personB_id": {...},
    ...
  }
}
```

---

## 4. Gesture Recognition (NEW: High Confidence Only)

### How It Works

**Old System**: Triggered on ANY stable gesture → fidgeting wipes transfers

**New System**: Uses 3 high-confidence tests:

1. **Pose Confidence** (80%+ certain hand is open/closed)
   - All fingers clearly extended (Open)
   - All fingers clearly curled (Close)

2. **Motion Spike** (intentional gesture = hand moves + classification changes)
   - Fidgeting = no intentional motion
   - Opening/closing = deliberate hand movement

3. **Gesture Lock** (held same pose for 5+ frames after movement)
   - Real gesture = stable after the motion
   - Jitter = changes multiple times

### Debug Gesture Recognition

Watch the **gesture-readout** display in the app:
```
hand: Open (75%) motion:45%    ← medium confidence, medium motion
hand: Open (92%) motion:0%     ← high confidence (GREEN), stable
hand: Close (100%) motion:88%  ← intentional close gesture (fires)
```

**Color meanings**:
- 🟢 **Green**: 70%+ confidence = high-confidence gesture
- 🟠 **Orange**: 40-70% confidence = partial
- ⚫ **Gray**: <40% confidence = likely fidgeting (ignored)

### If Gestures Aren't Firing

1. **Open hand clearly**: all 5 fingers visible, spread apart
2. **Close hand completely**: make a fist, curl all fingers
3. **Deliberate motion**: movement THEN hold the pose stable
4. **Wait 0.5 seconds**: the system needs time to confirm

### Common Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| Fidgeting fires gestures | Fingers partially curled | Keep hand clearly open/closed |
| Gesture won't fire | Low confidence | Spread fingers more, bigger motion |
| Gesture fires randomly | Hand moving too much | Stop moving, hold steady pose |
| Confidence always low | Phone angle bad | Aim camera at hand, not down |

---

## 5. Hand Geometry Identification

The system learns **hand shape** per person:
- Hand size
- Finger lengths and proportions
- Palm width

Used for:
- Person identification (experimental)
- Gesture debugging
- Future: contactless person recognition

Tracked in: `/status` → `"hand_samples": N` (per person)

---

## 6. Performance Tuning

### Hand Detection (15 fps by default)

If the system is still slow:
```javascript
// frontend/app.js, adjust DETECT_INTERVAL_MS:
const DETECT_INTERVAL_MS = 100;  // 10 fps (slower but lighter)
```

### Face Recognition (2 sec before join, 6 sec after)

Already optimized for your GPU/CPU. If face frames cause lag:
```bash
# Temporarily disable face recognition:
# Comment out sendFaceFrame() calls in frontend/app.js
```

### Model Storage Check
```powershell
# See what's taking up space on D:
dir D:\gesture-hold-data -recurse | measure -sum
```

---

## 7. Troubleshooting

### "It closes on its own, can't join"
**Fixed**: Auto-reconnect now retries every 1-8 seconds.
Check status line: "disconnected, retrying in 3s..."

### "Unknown link code" after phone locks
**Fixed**: 15-minute grace period keeps codes alive during disconnects.

### "Gestures not working, fidgeting triggers close"
**Fixed**: 3-test gesture discrimination now ignores accidental movements.

### Models stuck on C: drive
Set `GESTURE_HOLD_STORAGE` before running:
```powershell
$env:GESTURE_HOLD_STORAGE = "D:\gesture-hold-data"
python run_https.py
```

### Certificate warning on phone
**This is normal**: The cert is generated on your laptop, not from a public CA.
- Tap **Advanced** → **Proceed anyway** (or similar)
- Certificate is local-only, never leaves your network

---

## 8. System Architecture

```
Your Laptop (HTTPS Server)
├── Hand Detection (MediaPipe, 15fps, local)
├── Gesture Classification (TensorFlow, optimized)
├── Gesture Discrimination (new: 3-test high-confidence filter)
├── Hand Geometry Tracking (person identification)
├── Face Recognition (InsightFace on D: drive, optional)
└── Session Manager (multi-user state machine)

Your Phone (Browser Client)
├── Camera feed
├── Hand landmark detection (browser-side only)
├── Face frame capture (encrypted, HTTPS only)
└── Gesture visualization (color-coded confidence)

Network: Local WiFi only, no external tunnels
```

---

## 9. Advanced: Custom Model Storage

To use a different storage location:

**Option 1: Environment Variable**
```powershell
$env:GESTURE_HOLD_STORAGE = "E:\models"
python run_https.py
```

**Option 2: Project Symlink** (Windows)
```powershell
mklink /d D:\gesture-hold-data E:\my-fast-ssd\gesture-models
```

**Option 3: Network Drive** (for team)
```powershell
$env:GESTURE_HOLD_STORAGE = "\\server\shared-models"
```

---

## 10. What's New in This Release

✅ **Lighter Model Storage**: ~340MB on D: drive (not C:)
✅ **Multi-User Support**: 3+ people using simultaneously
✅ **Gesture Discrimination**: 3-test confidence filter (no fidgeting false triggers)
✅ **Hand Geometry ID**: Person identification by hand shape
✅ **Better Debugging**: Color-coded confidence + motion display
✅ **Auto-Reconnect**: 1-8s backoff when socket drops
✅ **15-min Grace Period**: Link codes survive phone locks/WiFi blips

---

## Support

For issues or questions:
1. Check `/status` endpoint for system health
2. Watch the gesture-readout colors (indicator of what's happening)
3. Check server logs for detailed gesture + motion data
4. Verify D: drive has free space (`dir D:\gesture-hold-data`)
