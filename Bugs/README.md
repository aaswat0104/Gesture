# Bugs Folder

Every real bug hit during development of this app, in the order it was found. Each file is: what broke, why, how it was fixed, and how it was verified. Kept so the reasoning behind a fix doesn't have to be re-derived if something regresses.

| # | Bug | Severity |
|---|-----|----------|
| [001](001-shared-open-hand-self-delivery.md) | Grab and release shared one ambiguous method — opening your hand on the same device silently self-delivered | Critical |
| [002](002-gesture-confidence-boundary.md) | Gesture confidence threshold used `>` instead of `>=`, dropping exactly-80% frames | High |
| [003](003-directml-native-crash.md) | DirectML GPU face inference crashed the whole Python process with no traceback | Critical |
| [004](004-link-code-instant-destruction.md) | Link codes were destroyed the instant the last device disconnected | High |
| [005](005-c-drive-model-storage.md) | InsightFace model downloads filled the C: drive | Medium |
| [006](006-fidgeting-false-gesture-triggers.md) | Any single-frame gesture classification fired an action, so fidgeting/relaxing triggered accidental close/open | High |
| [007](007-page-level-scrollbar-on-large-image.md) | Receiving a large image grew `#held-content` past the viewport, putting a scrollbar on the whole page | Low |

## Format

Each bug file follows the same shape:
- **Symptom** — what the user actually saw/reported (often a raw log excerpt)
- **Root cause** — the actual mechanism, not just the symptom
- **Fix** — what changed, with file references
- **Verification** — how it was confirmed fixed (test, manual repro, or both)
