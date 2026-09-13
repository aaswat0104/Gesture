# Gesture Hold & Transfer (multi-device web app)

Evolves the original single-machine `app.py` gesture demo into a browser-based,
multi-device version: open your hand to hold something (text/image), walk to
another device, open your hand there to receive it, close your hand to
release it. See `backend/session_manager.py` for the exact state machine.

## Architecture (short version)

- **Frontend** (`frontend/`): plain HTML/JS. Runs MediaPipe Tasks Web in the
  browser to extract hand + face landmarks (no raw video ever leaves the
  device), sends only the landmark points over WebSocket.
- **Backend** (`backend/`): one FastAPI process. `session_manager.py` is the
  single source of truth for identity and hold/transfer/release state
  (pure Python, unit tested). `inference.py` reuses your existing
  `model/keypoint_classifier` and `model/point_history_classifier`
  TFLite models unchanged to turn landmarks into gesture labels.
- Nothing is persisted to disk — accounts, link codes, and face embeddings
  all live in memory and are dropped when a person's last device disconnects.

No YOLO/ONNX involved — MediaPipe already handles hand and face detection.

## Run it locally

```bash
pip install -r backend/requirements.txt
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Open `https://localhost:8000` — **note:** browsers only allow camera access
(`getUserMedia`) over HTTPS or `localhost`. Localhost works with plain HTTP
for same-machine testing. For a second *physical* device, you need real
HTTPS — see below.

## Testing across two devices / two networks (today, no cloud deploy needed)

Use a tunnel to get a real HTTPS URL pointed at your machine:

```bash
# one-time: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
cloudflared tunnel --url http://localhost:8000
```

This prints an `https://<random>.trycloudflare.com` URL. Open it on Device A
and Device B (any network, any device) — that satisfies the "completely
different network" test case without deploying anything yet.

## Using it

1. Device A: open the URL, leave the link code field blank, click **Join**.
   A 6-character code appears.
2. Device B: open the same URL, type that code, click **Join**.
3. On either device: type text (or click the mic and dictate) or pick an
   image, then show an **open hand** to the camera — that's the hold gesture.
4. Walk to the other device, show an **open hand** there — it receives the
   held item. Showing an open hand again on a device that already received
   it does nothing new (no duplicate transfer).
5. **Close your hand** on either device to release — the next open-hand
   anywhere starts a fresh hold, not a repeat of the old one.

If your hand is open but nothing is selected, the app asks what to do
(save/send/analyze/search) via the rule-based clarification prompt — no LLM
call involved.

## GPU

The backend attempts to load a TFLite GPU delegate and falls back to
multi-threaded CPU if unavailable (reported honestly in the UI as `[gpu]` or
`[cpu]`). TFLite has no official GPU delegate build for Windows, so on most
Windows laptops this will legitimately run on CPU — that's not a bug, it's
disclosed rather than faked.

## Tests

```bash
pip install pytest
python -m pytest tests/ -v
```

`tests/test_session_manager.py` specifically covers the no-duplicate-transfer
guarantee: acquire, transfer once, repeat open-hand is idempotent, close-hand
releases, and the next open-hand is treated as a new interaction.

## What's deliberately not in v1

- No LLM/Claude API call at runtime (rule-based clarification only).
- No external connector integrations (Drive/Notion/Slack-style push) — the
  transfer stays device-to-device via your own account.
- No persistence — restart the server and all sessions are gone by design.
- Face recognition is a *convenience* layer only (prefills the link code on
  a recognized device); the account/link-code is what actually establishes
  identity and gates the transfer.
