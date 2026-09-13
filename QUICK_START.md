# Quick Start: Gesture Transfer (Huawei AirShare Model)

## The 4-Step Flow

### Step 1: Start Server
```powershell
python run_https.py
# You'll see: https://localhost:8443 (laptop) and https://192.168.31.49:8443 (phone)
```

### Step 2: Open on Two Devices (Same WiFi)
- **Device A (Laptop)**: `https://localhost:8443`
- **Device B (Phone)**: `https://192.168.31.49:8443`
- Accept certificate warning on first load

### Step 3: Transfer a File (The Key Part - NOW FIXED!)
**Device A (Laptop)**:
```
1. Type text OR select a file
   └─ You'll see it in the "Held" section (empty for now)

2. CLOSE YOUR HAND (make a FIST)
   └─ 🟢 Green confidence (high) = gesture fires
   └─ System: "Grabbed file" → file now held
   └─ You see: "Opened on Laptop"
```

**Device B (Phone)** ← Walk over:
```
1. OPEN YOUR HAND (spread fingers, palm forward)
   └─ 🟢 Green confidence (high) = gesture fires
   └─ System: "Released file" → file received
   └─ You see: "Closed on Phone" + file appears
   
2. Now Device B has the file!
```

### Step 4: Transfer Again (Same Person, Different File)
**Device A**:
```
1. Select a DIFFERENT file
2. Close hand (fist) → grabs it
```

**Device B**:
```
1. Open hand (palm) → receives the new file
```

---

## Gesture Meanings (Huawei AirShare Model)

| Gesture | Action | What Happens |
|---------|--------|-------------|
| 👊 **Close Hand (Fist)** | **GRAB** | Acquire selected file from current device |
| ✋ **Open Hand (Palm)** | **RELEASE** | Receive held file on this device |

---

## Color-Coded Feedback

Watch the **gesture-readout** in the app:

```
hand: Close (75%) motion:45%    ← 🟠 orange = partial confidence
hand: Close (92%) motion:0%     ← 🟢 green = high confidence (FIRES!)
hand: Open (100%) motion:0%     ← 🟢 green = high confidence (FIRES!)
```

- 🟢 **Green** (≥70%): Gesture will fire
- 🟠 **Orange** (40-70%): Partial
- ⚫ **Gray** (<40%): Ignored (fidgeting)

---

## Common Mistakes & Fixes

### "Nothing happens when I close hand"
**Problem**: Fingers not clearly curled, or confidence too low (gray display)
**Fix**: Make a TIGHT FIST with all fingers curled
```
Bad:  Fingers partially curled  → confidence 45% → ignored
Good: All fingers in a fist     → confidence 92% → fires ✓
```

### "Gesture fires but file doesn't transfer"
**Problem**: First device didn't grab (Close didn't fire)
**Fix**: Check Device A:
1. Is gesture-readout showing 🟢 green for Close?
2. If gray, make tighter fist
3. Wait for "Grabbed" message

### "I'm on Device B but don't see the file"
**Problem**: No file is actually held (A didn't grab it)
**Fix**:
1. On Device A: Close hand → should see "Grabbed file"
2. Check server logs for `GRAB` message
3. Then on Device B: Open hand

### "Device B shows its own file instead of A's file"
**Problem**: Device B has its own selection and you didn't grab from A first
**Fix**:
1. Clear Device B selection (delete text / deselect file)
2. Grab from Device A (close hand on A)
3. Then open hand on B

---

## Multi-Person Example

**Person A (3 devices)**:
- Select photo.jpg on Laptop
- Close hand (grab) → photo.jpg held
- Open hand on Phone → photo.jpg received
- Open hand on Tablet → photo.jpg received (all have it now)

**Person B (2 devices)**:
- Select notes.txt on Phone
- Close hand (grab) → notes.txt held
- Open hand on Laptop → notes.txt received
- No interference with Person A's photo!

---

## Troubleshooting

### Server won't start
```powershell
# Make sure D: drive is accessible
dir D:\gesture-hold-data
# If not, set:
$env:GESTURE_HOLD_STORAGE = "E:\my-path"
python run_https.py
```

### Certificate warning on phone
**Expected!** Self-signed cert is local-only (secure):
1. Tap "Advanced"
2. Tap "Proceed anyway"
3. You're in!

### Slow gesture recognition
1. Better lighting (avoid shadows on hands)
2. Hold hand still after gesture (let it stabilize)
3. Use bigger, clearer hand movements

### "Unknown link code" after WiFi blip
**Fixed!** Codes now survive 15 minutes of disconnection:
- Phone lock? Code stays valid
- WiFi cut out? Rejoin within 15 min
- Past 15 min? Code expired (new session)

---

## What's Inside

**Backend (Python)**:
- FastAPI server on localhost:8443
- WebSocket for real-time sync
- Multi-user session manager
- Hand gesture classification + discrimination
- Face recognition (optional, on D: drive)

**Frontend (Browser)**:
- Camera + hand detection (MediaPipe)
- Color-coded confidence display
- Auto-reconnect (survives WiFi blips)
- Multi-device file transfer

**Storage**:
- D: drive for models (340MB)
- In-memory session state (no disk)
- Privacy: destroyed on server restart

---

## Test It Now

```bash
# 1. Start server
python run_https.py

# 2. Open two browser tabs (or two devices)
# Device A: https://localhost:8443
# Device B: https://192.168.31.49:8443

# 3. Device A: Type "hello world"
# 4. Device A: Make a FIST (close hand) → watch for GREEN
# 5. Device B: Open hand (spread fingers) → watch for GREEN
# 6. Device B now has "hello world"!

# 7. Device A: Select a new image file
# 8. Device A: Close hand again
# 9. Device B: Open hand → gets the image
```

---

## More Info

- **[DEPLOYMENT.md](DEPLOYMENT.md)** → Full setup guide
- **[GESTURE_DEBUG.md](GESTURE_DEBUG.md)** → Deep-dive into gesture system
- **[IMPROVEMENTS.md](IMPROVEMENTS.md)** → What's been fixed
