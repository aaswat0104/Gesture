# 007 — Receiving a large image put a scrollbar on the whole page

**Severity:** Low — cosmetic/UX, but reported directly by the user as making the page feel broken.

## Symptom

User: "the scroll up and down bar appears on the page when an image is shared which makes the page have a scroll page."

## Root cause

`#held-content` (and its predecessor, the single-item held display) had no height cap on its container — only the `<img>` itself was capped (`max-height: 200px`). Once a bundle held multiple images/files, or a single tall image plus its metadata line pushed total content height past the viewport, `<body>` itself grew taller than the window and the *whole page* scrolled, not just the results panel.

## Fix

`frontend/style.css`: `#held-content { max-height: 420px; overflow-y: auto; }`. The received panel now scrolls internally when its content is tall, and the rest of the page (camera, selection controls, devices list) stays fixed in place regardless of how much was received.

## Verification

Manual: rendered a multi-item bundle (text + image + file) via `renderHeld()` in the browser preview and confirmed scrolling stays contained inside the Received card — `document.body.scrollHeight` no longer exceeds the viewport height when a large image is present.
