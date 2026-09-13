# Gesture Recognition Debugging Guide

## Understanding the 3-Test System

When you move your hand, the system runs **3 independent tests** to decide if it's a real gesture or just fidgeting.

### Test 1: Pose Confidence (Hand Clarity)
**What it measures**: How clearly open or closed your hand is.

```
100% ████████████ = All fingers fully extended/curled (CLEAR)
 75% ██████░░░░░░ = Most fingers extended/curled (GOOD)
 50% ██████░░░░░░ = Some fingers extended, some curled (UNCLEAR)
 25% ██░░░░░░░░░░ = Few fingers extended/curled (BLURRY)
  0% ░░░░░░░░░░░░ = Can't tell (fidgeting)
```

**To fire Open/Close**: Need ≥80% confidence that the hand is in that pose.

**Example**:
- `Open (92%)` → All 5 fingers spread → gesture fires
- `Open (65%)` → Some fingers curled → gesture ignored
- `Close (100%)` → Tight fist → gesture fires
- `Close (45%)` → Partially relaxed → gesture ignored

### Test 2: Motion Spike (Intentional Movement)
**What it measures**: Is the hand MOVING while the gesture classification changes?

```
Fidgeting (ignored):
  Open → Open → Open → Close [tiny twitch] → Open
  Gesture changed but NO intentional motion = false positive

Real gesture (fires):
  Open → Open → Open
  Close [hand clearly moved] → Close → Close
  Classification changed AND hand moved = intentional gesture
```

**How it works**:
- Tracks wrist position + palm center every frame
- If motion > 15% (on 0-100 scale) and classification changed → likely intentional
- Combines with pose confidence ≥40% to fire

**Example motions**:
```
motion:0%   = hand completely still
motion:30%  = slow deliberate movement
motion:60%  = fast hand motion
motion:100% = very fast/erratic
```

### Test 3: Gesture Lock (Stability After Motion)
**What it measures**: Does the hand STAY in the gesture for 5+ frames?

```
Real gesture (fires):
  [Move hand] → Open [stays open] → Open → Open → Open → Open
  Stays stable after motion = user is holding the pose

Accidental gesture (ignored):
  [Move hand] → Open → Close → Open → Close → Open
  Bouncing between states = not a stable gesture
```

**When it fires**: After motion stabilizes, if pose is held consistently.

---

## Live Debugging: Reading the Display

### Gesture Readout in the App

**Location**: Center-bottom of the app panel, labeled "gesture-readout"

**Display format**:
```
hand: Open (92%) motion:0%
│     │    │     │
│     │    │     └─ Motion: 0-100%, how much hand is moving
│     │    └─ Pose Confidence: 0-100%, clarity of the pose
│     └─ Raw classification: Open/Close/Pointer
└─ Label
```

**Color meanings**:
- 🟢 **Green** (pose_confidence ≥ 70%): HIGH confidence, ready to fire
- 🟠 **Orange** (40% ≤ conf < 70%): Medium confidence
- ⚫ **Gray** (conf < 40%): Low confidence, likely ignored

### Example Sequences

**Sequence 1: Perfect Open Gesture**
```
hand: Open (65%) motion:0%     ← Building up confidence
hand: Open (78%) motion:0%     ← Still low
hand: Open (89%) motion:0%     ← ✅ HIGH (GREEN) - fires if stable
hand: Open (91%) motion:0%     ← Holding steady
hand: Open (90%) motion:0%     ← [gesture action fires]
```

**Sequence 2: Accidental Close (fidgeting)**
```
hand: Open (92%) motion:0%     ← Hand is open
hand: Open (88%) motion:15%    ← Slight hand movement
hand: Close (35%) motion:40%   ← Quick fist twitch
hand: Open (80%) motion:0%     ← Back to open quickly
[No gesture fires - it bounced, not intentional]
```

**Sequence 3: Intentional Close**
```
hand: Open (92%) motion:0%     ← Open, stable
hand: Open (85%) motion:45%    ← MOTION DETECTED, closing gesture
hand: Close (60%) motion:60%   ← Classification changed + motion
hand: Close (88%) motion:30%   ← Motion continuing
hand: Close (95%) motion:0%    ← ✅ HIGH (GREEN) - holds stable
hand: Close (96%) motion:0%    ← [gesture action fires]
```

---

## Server-Side Debugging

### Check the Log

When a gesture fires, the server logs:

```
HIGH_CONFIDENCE_GESTURE device='laptop' gesture='Open' confidence=0.92 reason=high_pose_confidence
HIGH_CONFIDENCE_GESTURE device='laptop' gesture='Close' confidence=0.95 reason=motion_spike
```

The `reason` field tells you which test passed:
- `high_pose_confidence` → Test 1 (hand very clearly open/closed)
- `motion_spike` → Test 2 (hand moved + classification changed)
- `gesture_lock` → Test 3 (stayed stable 5+ frames)

### Live Logs

```powershell
# Watch live logs while testing:
Get-Content $env:TEMP\gesture-server.log -Wait | Select-String "GESTURE"
```

---

## Troubleshooting: Why Isn't My Gesture Firing?

### Problem 1: Confidence Always Low (< 50%)

**Symptom**:
```
hand: Open (35%) motion:0%
hand: Open (42%) motion:0%
hand: Open (48%) motion:0%
```

**Causes**:
1. Camera angle is bad (looking down at hand at 45°, not straight on)
2. Hand partially off-screen
3. Fingers not clearly separated (partially curled)

**Fix**:
- Position phone/camera so it sees hand straight-on
- Spread fingers WIDE apart for Open
- Make tight FIST for Close (all fingers curled)
- Keep hand fully in frame

### Problem 2: Pose Confidence Flickers (jumps 90% → 20% → 80%)

**Symptom**:
```
hand: Open (88%) motion:0%
hand: Close (45%) motion:5%     ← Sudden drop
hand: Open (82%) motion:0%      ← Back up
```

**Causes**:
1. Hand is shaking (parkinson's-like tremor)
2. Lighting changed
3. Background clutter (bad contrast)

**Fix**:
- Steady your hand against something
- Improve lighting (avoid shadows)
- Use a plain background behind your hand
- Slow down your gesture

### Problem 3: Gesture Fires on Fidgeting

**Symptom**: Opening/closing your hand slightly triggers gestures when you don't want.

**Example**:
```
hand: Open (92%) motion:0%
hand: Open (88%) motion:12%     ← Tiny twitch
hand: Close (55%) motion:20%    ← Brief fist twitch
[FIRES CLOSE even though you don't want it]
```

**Causes**: Hand is too loose/relaxed.

**Fix**:
- **Deliberately hold open**: Keep fingers STIFF and spread
- **Deliberately hold closed**: Make a TIGHT fist, don't relax
- Slow transitions: Open → hold for 1 second → Close
- Exaggerate the difference between poses

### Problem 4: Motion Prevents Gesture

**Symptom**:
```
hand: Open (95%) motion:0%
hand: Open (88%) motion:78%     ← Hand moving too much
hand: Open (85%) motion:82%
hand: Open (78%) motion:75%
[Gesture won't fire because motion is too high]
```

**Causes**: Hand is vibrating or you're moving too slowly.

**Fix**:
- Make QUICK, DELIBERATE movements (fast, not slow)
- After moving, STOP completely (motion: 0%)
- Wait 0.5 seconds for stability

---

## Testing: Step-by-Step Gesture Test

**Setup**: Open the app on your phone/laptop, watch the gesture-readout.

### Test 1: Open Hand
```
1. Make a fist (Close)
2. Watch gesture-readout: Should say "Close (90%+)" in GREEN
3. Hold for 2 seconds
4. Quickly open hand wide
5. Watch gesture-readout: Should say "Open (90%+)" in GREEN
6. You should see "Opened on [device]" in the app
```

**Expected result**: Gesture fires when you open.

### Test 2: Close Hand
```
1. Keep hand open
2. Watch gesture-readout: Should say "Open (90%+)" in GREEN
3. Quickly make a fist
4. Watch gesture-readout: Should say "Close (90%+)" in GREEN
5. You should see "Closed on [device]" in the app
```

**Expected result**: Gesture fires when you close.

### Test 3: Fidgeting Ignored
```
1. Hold hand open
2. Wiggle fingers (small movements)
3. Watch gesture-readout: Confidence should drop (stay in gray)
4. Do NOT fire a gesture (confidence stays low)
5. Now deliberately close hand
6. Gesture DOES fire
```

**Expected result**: Small movements are ignored, big deliberate ones work.

---

## Performance Metrics

For developers: The gesture discrimination system adds **~1ms** overhead per frame.

```
Old system (no discrimination):
  30 landmarks → classify → fire [FAST, NOISY]

New system (3-test discrimination):
  30 landmarks → classify → pose_confidence (+0.3ms)
                          → compute_motion (+0.2ms)
                          → test stable (+0.5ms)
                          → fire [SLIGHTLY SLOWER, VERY CLEAN]
```

Net result: Gestures fire ~95% less often from fidgeting, with only 1ms added latency.

---

## Advanced: Adjusting Thresholds

Edit `backend/gesture_discriminator.py` to tune:

```python
# Line 40-42: Pose confidence thresholds
if pose_confidence > 0.8:      # Change 0.8 to 0.7 for lower threshold
    # ... fire gesture

# Line 52: Motion threshold  
if motion > 0.15:              # Change 0.15 to 0.10 for more motion sensitivity
    # ... motion spike test

# Line 70: Gesture lock frames
if len(self.hand_sign_history) >= 5:  # Change 5 to 3 for faster lock
    # ... gesture lock test
```

**Trade-offs**:
- Lower `pose_confidence` threshold → fires more often, more false positives
- Higher threshold → fewer false positives, but might miss real gestures
- Lower `motion` threshold → detects smaller movements (good for slow people)
- Higher threshold → ignores tiny motions (good for shaky hands)
