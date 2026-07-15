# Phase 236 — Vision Input (Camera → Schematic) Summary

**Date:** 2026-07-15
**Plan:** 236-01-PLAN.md
**Status:** DEFERRED-TO-NAMED-TARGET (v12.0 mobile-first milestone)

## Status

| Component | Status |
|-----------|--------|
| `KCAttachment` SwiftData model | EXISTS (Phase 239 partial) |
| Camera capture pipeline | NOT IMPLEMENTED |
| Vision-language prompt builder | NOT IMPLEMENTED |
| Volta v2 adapter vision-token routing | NOT IMPLEMENTED |
| "Snap photo → SKiDL" UI | NOT IMPLEMENTED |

## Resolution state

DEFERRED — vision input requires mobile-first effort (camera entitlements,
AVFoundation integration, visionOS hand-tracking). Deferred to v12.0 per
the four-state taxonomy. Recorded in ROADMAP.md Phase 236 description.

## Next steps

- v12.0 phase: wire camera capture via `AVCaptureSession`
- v12.0 phase: encode image → base64 → vision-token slot in prompt
- v12.0 phase: low-light / perspective-fixing preprocessing
- v12.0 phase: end-to-end "Snap photo → SKiDL" evaluation
