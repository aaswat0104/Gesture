// Loaded as a module. SRI isn't supported on JS `import` statements by any
// browser yet (only on <script>/<link> tags), so this URL is pinned to an
// exact version instead; expected file hash (sha256, base64) for manual
// verification: 538oH5YZFQ2TcCPDVbrhcOkSDjueQ/HiOip77gcZdmk=
import {
  HandLandmarker,
  FilesetResolver,
} from "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/vision_bundle.mjs";

const HAND_MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task";
const WASM_BASE =
  "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm";

// Hand detection cadence. This used to run on every requestAnimationFrame
// (~60/sec): MediaPipe's WASM hand landmarker costs ~15-30ms of CPU per
// call, so a single open tab could saturate a core, and several tabs made
// the whole laptop crawl. The server only accepts landmarks every 150ms
// anyway, so anything above ~15fps was pure waste -- the overlay dots are
// the only thing that benefits, and they look fine at 15fps.
const DETECT_INTERVAL_MS = 66; // ~15fps
const HAND_SEND_INTERVAL_MS = 150;

// Face frames leave the browser as JPEGs for server-side recognition, so
// they're the expensive path on BOTH ends. Before joining we need them
// often (that's what makes "walk up and it knows you" work); after joining,
// identity is already settled, so they drop to a trickle and stop entirely
// once the server has enough samples to recognise you on another device.
const FACE_PROBE_INTERVAL_MS = 2000;
const FACE_ENROLL_INTERVAL_MS = 6000;
const MAX_ENROLL_FRAMES = 8;

const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 8000;

const $ = (id) => document.getElementById(id);
const statusLine = $("status-line");
const presenceLine = $("presence-line");
const video = $("video");
const overlay = $("overlay");
const overlayCtx = overlay.getContext("2d");

// Offscreen, small, JPEG -- this is what actually leaves the browser for
// face recognition (the InsightFace/ArcFace model runs server-side on
// pixels, unlike hand tracking which only ever sends landmark points).
const faceCanvas = document.createElement("canvas");
faceCanvas.width = 320;
faceCanvas.height = 240;
const faceCtx = faceCanvas.getContext("2d");

let ws = null;
let deviceId = null;
let myLinkCode = null; // remembered so a reconnect can rejoin the same person
let joinInFlight = false;
let userEditedCode = false; // don't clobber what they typed with a face guess
let handLandmarker = null;
let lastDetectAt = 0;
let lastHandSendAt = 0;
let lastFaceSentAt = 0;
let enrollFramesSent = 0;
let autoJoinAttempted = false;
let hintTimer = null;
let reconnectDelay = RECONNECT_BASE_MS;
let reconnectTimer = null;
let selectDebounce = null;
let faceFrameTimer = null;

// Camera on/off. OFF fully stops the media stream and every loop touching
// it -- detection, overlay drawing, face frames -- rather than just hiding
// the preview, since the point is saving CPU/battery, not just privacy.
let cameraOn = true;
let mediaStream = null;

// Multi-file selection queue: one optional text entry plus any number of
// files/images. Grabbing (close hand) bundles everything queued here into
// ONE transfer -- see backend/session_manager.py's HeldItem.contents.
let queuedText = "";
let queuedFiles = []; // [{content_type, content, filename}]

function showHint(text, ms = 4000) {
  const hintEl = $("hint-line");
  if (hintEl) {
    hintEl.textContent = text;
    clearTimeout(hintTimer);
    if (ms) hintTimer = setTimeout(() => (hintEl.textContent = ""), ms);
  }
}

// ---------------------------------------------------------------- WebSocket

function connectWs() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onopen = () => {
    reconnectDelay = RECONNECT_BASE_MS;
    if (myLinkCode) {
      // We were joined before the socket dropped -- rejoin the same person
      // automatically instead of dumping the user back on the join screen.
      statusLine.textContent = "reconnected, rejoining...";
      doJoin(myLinkCode);
    } else {
      statusLine.textContent = "connected, not joined yet";
    }
  };

  ws.onmessage = (event) => handleServerMessage(JSON.parse(event.data));

  ws.onclose = () => {
    // A dropped socket used to be terminal: the page said "disconnected"
    // forever and the Join button then silently did nothing, because send()
    // discards messages when the socket isn't OPEN. That's what "it closes
    // on its own and I can't even join" was.
    deviceId = null;
    joinInFlight = false;
    statusLine.textContent = `disconnected, retrying in ${Math.round(reconnectDelay / 1000)}s...`;
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(connectWs, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX_MS);
  };

  ws.onerror = () => (statusLine.textContent = "connection error");
}

function send(msg) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(msg));
    return true;
  }
  return false;
}

function doJoin(code) {
  if (joinInFlight) return;
  const name = $("device-name-input").value.trim() || "device";
  joinInFlight = true;
  const sent = send({ type: "join", link_code: code || null, device_name: name });
  if (!sent) {
    joinInFlight = false;
    showHint("Not connected to the server yet -- reconnecting, try again in a moment.");
  }
}

function handleServerMessage(msg) {
  switch (msg.type) {
    case "joined":
      deviceId = msg.device_id;
      joinInFlight = false;
      myLinkCode = msg.link_code || myLinkCode;
      enrollFramesSent = 0;
      statusLine.textContent = `joined as "${$("device-name-input").value.trim() || "device"}"`;
      $("join-panel").hidden = true;
      $("app-panel").hidden = false;
      if (myLinkCode) {
        $("link-code-display").hidden = false;
        $("link-code-value").textContent = myLinkCode;
      }
      break;

    case "error":
      joinInFlight = false;
      statusLine.textContent = `error: ${msg.message}`;
      // This used to only update the tiny grey status line in the corner,
      // which is invisible when you're staring at the code you just typed.
      showHint(
        msg.message === "Unknown link code"
          ? "That link code isn't valid. Codes live in server memory: restarting " +
            "the server, or all your devices being away for 15+ minutes, makes a " +
            "new one. Use the code currently shown on your other device."
          : `Error: ${msg.message}`,
        8000
      );
      break;

    case "face_suggestion":
      // Never overwrite a code the user is actually typing.
      if (msg.link_code && !userEditedCode) $("link-code-input").value = msg.link_code;
      if (msg.auto && msg.link_code && deviceId === null && !autoJoinAttempted) {
        autoJoinAttempted = true;
        statusLine.textContent = "face recognized, joining...";
        doJoin(msg.link_code);
      }
      break;

    case "face_match":
      $("face-readout").textContent = msg.matched
        ? `face: recognized (${Math.round(msg.score * 100)}%)`
        : `face: not you (${Math.round(msg.score * 100)}%)`;
      break;

    case "presence":
      presenceLine.textContent = `${msg.person_count} people online (${msg.device_count} devices)`;
      break;

    case "gesture_result": {
      // Show both raw classification AND confidence
      const confidence = msg.pose_confidence ? `(${Math.round(msg.pose_confidence * 100)}%)` : "";
      const motion = msg.motion_level ? ` motion:${Math.round(msg.motion_level * 100)}%` : "";
      const el = $("gesture-readout");
      el.textContent = `hand: ${msg.hand_sign ?? "--"} ${confidence}${motion}`;
      // Highlight when high-confidence gestures fire (different color)
      if (msg.pose_confidence > 0.7) {
        el.style.color = "#0f0"; // green = high confidence
      } else if (msg.pose_confidence > 0.4) {
        el.style.color = "#fa0"; // orange = medium
      } else {
        el.style.color = "#888"; // gray = low
      }
      break;
    }

    // Sent right after a successful grab (close hand). Shown on the
    // grabbing device as "you're carrying this" and on every other device
    // of the same person as an incoming-transfer preview with Cancel.
    // `items` is always an array -- one entry for a single file, several
    // for a bundled multi-file grab.
    case "transfer_pending": {
      $("transfer-pending-section").hidden = false;
      const title = $("transfer-pending-title");
      const desc = $("transfer-pending-desc");
      const label = describeItems(msg.items);
      if (msg.grabbed_by_device_id === deviceId) {
        title.textContent = "You're carrying this";
        desc.textContent = `${label} -- walk to another device and open your hand there to deliver it.`;
      } else {
        title.textContent = "Incoming transfer";
        desc.textContent = `${label} from ${msg.grabbed_by_device_name} -- open your hand to receive it.`;
      }
      break;
    }

    // Sent once a different device successfully opens its hand: the hop
    // is complete and the transit slot is free for the next grab.
    case "transfer_delivered":
      $("transfer-pending-section").hidden = true;
      renderHeld(msg.items, msg.origin_device_name, msg.delivered_to_device_name);
      $("activity-line").textContent =
        msg.delivered_to_device_id === deviceId
          ? `Received from ${msg.origin_device_name}`
          : `Delivered to ${msg.delivered_to_device_name}`;
      break;

    case "transfer_cancelled":
      $("transfer-pending-section").hidden = true;
      showHint(
        `Transfer cancelled${msg.cancelled_by_device_name ? " by " + msg.cancelled_by_device_name : ""}.`,
        3000
      );
      break;

    // This person's current device roster -- fills the "Your devices" panel.
    case "device_list":
      renderDevices(msg.devices);
      break;

    // Covers "nothing selected to grab", "already carrying something else",
    // and "you grabbed this here -- walk to another device to deliver it".
    case "clarify_request":
      showHint(msg.question || "Action needs clarification.", 4000);
      break;
  }
}

function describeItems(items) {
  if (!items || items.length === 0) return "nothing";
  if (items.length === 1) return items[0].filename || items[0].content_type;
  return `${items.length} items`;
}

// -------------------------------------------------------------- Join panel

$("join-btn").onclick = () => doJoin($("link-code-input").value.trim());
$("link-code-input").oninput = () => (userEditedCode = true);

// Lets you abort an in-flight transfer without needing to physically
// return to the grabbing device and do a release gesture there.
$("cancel-transfer-btn").onclick = () => send({ type: "cancel_transfer" });

// ------------------------------------------------------------------ Camera
//
// Starts immediately on page load, not after joining: face recognition
// needs to run BEFORE join too, to auto-join a recognized face on sight.

async function startCamera() {
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
    video.srcObject = mediaStream;
    await video.play();
  } catch (e) {
    showHint(`Camera unavailable: ${e.message}. Gestures and face recognition need it.`, 0);
    return;
  }

  if (!handLandmarker) {
    const fileset = await FilesetResolver.forVisionTasks(WASM_BASE);
    handLandmarker = await HandLandmarker.createFromOptions(fileset, {
      baseOptions: { modelAssetPath: HAND_MODEL_URL },
      runningMode: "VIDEO",
      numHands: 1,
    });
    requestAnimationFrame(detectLoop);
  }
  clearInterval(faceFrameTimer);
  faceFrameTimer = setInterval(sendFaceFrame, 1000);
}

// Fully pauses: stops every camera track (releases the hardware/indicator
// light, not just hides the <video>), and detectLoop/sendFaceFrame both
// check `cameraOn` so they do zero work while off -- this is a genuine
// stop, not a cosmetic one, since the point is saving CPU and battery.
function stopCamera() {
  if (mediaStream) {
    mediaStream.getTracks().forEach((t) => t.stop());
    mediaStream = null;
  }
  video.srcObject = null;
  clearInterval(faceFrameTimer);
  overlayCtx.clearRect(0, 0, overlay.width, overlay.height);
}

$("camera-toggle-btn").onclick = async () => {
  cameraOn = !cameraOn;
  $("camera-toggle-btn").textContent = cameraOn ? "Turn camera off" : "Turn camera on";
  $("camera-off-placeholder").hidden = cameraOn;
  if (cameraOn) {
    await startCamera();
  } else {
    stopCamera();
    $("gesture-readout").textContent = "hand: -- (camera off)";
    $("face-readout").textContent = "face: camera off";
  }
};

function detectLoop() {
  requestAnimationFrame(detectLoop);

  const now = performance.now();
  // Hidden tab, or camera deliberately turned off: do nothing at all.
  // Background tabs still running hand detection are exactly why several
  // open copies of this page bogged the machine down.
  if (!cameraOn || document.hidden || !handLandmarker || video.readyState < 2) return;
  if (now - lastDetectAt < DETECT_INTERVAL_MS) return;
  lastDetectAt = now;

  const result = handLandmarker.detectForVideo(video, now);
  drawOverlay(result);

  if (result.landmarks && result.landmarks[0] && now - lastHandSendAt > HAND_SEND_INTERVAL_MS) {
    lastHandSendAt = now;
    // Mirror x before sending: the trained model expects a selfie-view
    // (mirrored) frame, same as app.py's cv.flip(image, 1) -- the video
    // element only LOOKS mirrored on screen (that's CSS), the raw
    // landmarks HandLandmarker returns are from the unflipped camera
    // feed, so without this the classifier sees a left-right-swapped
    // hand it was never trained on.
    const points = result.landmarks[0].map((p) => [1 - p.x, p.y]);
    if (deviceId) send({ type: "hand_landmarks", landmarks: points });
  }
}

function sendFaceFrame() {
  if (!cameraOn || document.hidden || video.readyState < 2) return;

  const now = performance.now();
  if (deviceId) {
    // Joined: this only tops up enrollment and the cosmetic readout.
    if (enrollFramesSent >= MAX_ENROLL_FRAMES) return;
    if (now - lastFaceSentAt < FACE_ENROLL_INTERVAL_MS) return;
  } else if (now - lastFaceSentAt < FACE_PROBE_INTERVAL_MS) {
    return;
  }
  lastFaceSentAt = now;

  faceCtx.drawImage(video, 0, 0, faceCanvas.width, faceCanvas.height);
  const frame = faceCanvas.toDataURL("image/jpeg", 0.6);
  if (deviceId) {
    if (send({ type: "face_frame", frame })) enrollFramesSent += 1;
  } else {
    send({ type: "face_probe", frame });
  }
}

function drawOverlay(result) {
  overlayCtx.clearRect(0, 0, overlay.width, overlay.height);
  if (!result.landmarks || !result.landmarks[0]) return;
  overlayCtx.fillStyle = "#00e5ff";
  for (const p of result.landmarks[0]) {
    overlayCtx.beginPath();
    overlayCtx.arc(p.x * overlay.width, p.y * overlay.height, 3, 0, Math.PI * 2);
    overlayCtx.fill();
  }
}

// --------------------------------------------------------------- Selection

function sendSelection() {
  const items = [];
  if (queuedText.trim()) {
    items.push({ content_type: "text", content: queuedText, filename: null });
  }
  items.push(...queuedFiles);
  send({ type: "select_content", items });
}

$("text-selection").oninput = (e) => {
  // Debounced: this used to fire a WebSocket message per keystroke.
  queuedText = e.target.value;
  clearTimeout(selectDebounce);
  selectDebounce = setTimeout(sendSelection, 300);
};

$("file-selection").onchange = (e) => {
  const files = Array.from(e.target.files || []);
  if (files.length === 0) return;
  let remaining = files.length;
  for (const file of files) {
    const contentType = file.type.startsWith("image/") ? "image" : "file";
    const reader = new FileReader();
    reader.onload = () => {
      queuedFiles.push({ content_type: contentType, content: reader.result, filename: file.name });
      renderQueuedItems();
      if (--remaining === 0) sendSelection();
    };
    reader.readAsDataURL(file);
  }
  // Let the same file be re-picked later (e.g. re-adding after removing it).
  e.target.value = "";
};

function renderQueuedItems() {
  const list = $("queued-items-list");
  list.replaceChildren();
  queuedFiles.forEach((item, index) => {
    const li = document.createElement("li");
    const label = document.createElement("span");
    label.textContent = `${item.content_type === "image" ? "🖼" : "📄"} ${item.filename}`;
    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "remove-item-btn";
    removeBtn.textContent = "×";
    removeBtn.onclick = () => {
      queuedFiles.splice(index, 1);
      renderQueuedItems();
      sendSelection();
    };
    li.append(label, removeBtn);
    list.appendChild(li);
  });
}

// ------------------------------------------------------------- Rendering

function renderHeld(items, originDeviceName, deliveredToDeviceName) {
  const empty = $("held-empty");
  const content = $("held-content");
  if (!items || items.length === 0) {
    empty.hidden = false;
    content.hidden = true;
    return;
  }
  empty.hidden = true;
  content.hidden = false;
  content.replaceChildren();

  for (const item of items) {
    const card = document.createElement("div");
    card.className = "received-item";

    if (item.content_type === "text") {
      const textEl = document.createElement("div");
      textEl.className = "held-text";
      textEl.textContent = item.content;
      card.appendChild(textEl);
    } else if (item.content_type === "image") {
      const imgEl = document.createElement("img");
      imgEl.className = "held-image";
      imgEl.src = item.content;
      const downloadEl = document.createElement("a");
      downloadEl.href = item.content;
      downloadEl.download = item.filename || "image.jpg";
      downloadEl.textContent = "Download image";
      card.append(imgEl, downloadEl);
    } else {
      const fileEl = document.createElement("a");
      fileEl.href = item.content;
      fileEl.download = item.filename || "file";
      fileEl.textContent = `Download ${item.filename || "file"}`;
      card.appendChild(fileEl);
    }
    content.appendChild(card);
  }

  const meta = document.createElement("div");
  meta.id = "held-meta";
  meta.textContent = `from ${originDeviceName}, delivered to ${deliveredToDeviceName}`;
  content.appendChild(meta);
}

function renderDevices(devices) {
  const list = $("devices-list");
  list.replaceChildren();
  for (const d of devices || []) {
    const li = document.createElement("li");
    li.textContent = d.device_name + (d.device_id === deviceId ? " (this device)" : "");
    list.appendChild(li);
  }
}

connectWs();
startCamera();
