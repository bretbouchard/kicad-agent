---
phase: 171-liquid-glass-ui-shell
plan: 01
status: complete
shipped_at: 2026-07-08
commit: 077b2658
---

# Phase 171 — Liquid Glass UI Shell: Summary

## What Shipped

| File | Role | LOC |
|------|------|-----|
| `Views/WindowManager.swift` | @Observable multi-window registry, 100-window cap (T-171-04), active window tracking, idempotent register | 78 |
| `Views/ToolbarView.swift` | Extracted toolbar (4 actions: New Project / New Window / Share / Settings) + ToolbarButton + LiquidGlassAnimation tokens | 110 |
| `Views/LiquidGlassShell.swift` | Refactored: WindowManager integration (register on appear, unregister on disappear), Reduce Motion/Transparency observation | +25/-15 |
| `Theme/LiquidGlassModifiers.swift` | Centralized `LiquidGlassPanelModifier` — 3 prominence levels, accessibilityReduceTransparency swaps material → opaque | +95/-50 |
| `VoltaApp.swift` | WindowManager injected at scene level via `.environment(windowManager)` | +3 |
| `Tests/LiquidGlassShellTests.swift` | 4-variant trait tests (light/dark/XXXL/a11y) + 7 WindowManager tests | 169 |

## Requirements Closed

- **CHAT-05** — Shell ready for chat interface wiring (Phase 175)
- **A11Y-03** — Every toolbar element has `accessibilityLabel` + `accessibilityHint` + `.isButton` trait
- **A11Y-06** — Reduce Motion + Reduce Transparency respected per Apple HIG

## Threat Mitigations

- **T-171-04** (Denial of Service — unbounded windows): WindowManager enforces 100-window cap. `register()` returns false when `openProjectIds.count >= 100`. Test: `windowManagerCap()` proves cap enforcement.
- **T-171-01** (Spoofing — New Project): Accepted, no external data.
- **T-171-02** (Tampering — Share): Reuses SwiftUI `ShareLink` (system-sanitized).
- **T-171-03** (Info Disclosure — Settings): Accepted, local settings only.

## Test Results

```
swift build: ✅ Build complete! (29.36s)
swift test:  169 passed, 2 failed (pre-existing ProcessManager checksum from Phase 162)
```

Phase 171 specific tests (all pass):
- `LiquidGlassShell instantiates in light mode` ✓
- `LiquidGlassShell instantiates in dark mode` ✓
- `LiquidGlassShell instantiates at Dynamic Type XXXL` ✓
- `LiquidGlassShell instantiates with full accessibility` ✓
- `ToolbarView instantiates with all 4 actions` ✓
- `ToolbarButton has accessibility label + hint + button trait` ✓
- `WindowManager registers and tracks open projects` ✓
- `WindowManager unregisters closed projects` ✓
- `WindowManager enforces 100-window cap (T-171-04)` ✓
- `WindowManager idempotent on re-registration` ✓
- `WindowManager setActive promotes to active` ✓
- `WindowManager setActive rejects unregistered` ✓

## Pre-existing Failures (Not Phase 171 Regressions)

1. `Spawn launches daemon and ping works end-to-end` — Phase 162 checksum verification (daemon binary checksum mismatch in dev mode)
2. `Idempotent spawn returns same PID` — same root cause

These are tracked as Phase 162 dev-mode checksum issues, unrelated to UI shell work.

## Architectural Decisions

1. **@Observable over ObservableObject** — consistent with existing DaemonSupervisor / KiCadCLIDetector pattern (Phase 161). Modern Observation framework, no `@Published` boilerplate.

2. **`@MainActor` on WindowManager** — all window state mutations on main thread. SwiftUI requires this for view observation.

3. **WindowManager as @State at App level** — single instance per process, injected via `.environment()`. Survives window creation/destruction.

4. **Centralized LiquidGlassPanelModifier** — single ViewModifier handling all 3 prominence levels. Easier to audit, easier to extend (Phase 172 may add `.glassEffect()` from macOS 27 SDK).

5. **Reduce Transparency: material → controlBackgroundColor** — Apple HIG compliant. Solid background guarantees legibility when user explicitly opts out of translucency.

6. **No NSWindow references** — pure SwiftUI state. WindowGroup handles actual NSWindow lifecycle natively.

## ponytail Notes

- ToolbarView uses closures, not ViewBuilder enums — composable and testable
- ToolbarButton is one type, not four — same style, same a11y pattern
- LiquidGlassAnimation: two tokens (default spring + gentle ease), not a zoo of variants
- WindowManager has zero dependencies — just Foundation + OSLog

## What's Next

- **Phase 172** — Inline Rendering (SVG schematic, PNG PCB, pipeline view) — uses LiquidGlassPanelModifier for rendering surfaces
- **Phase 173** — GSD Conversation Engine — uses ToolbarView's onSettings for config access
- **Phase 175** — Chat Interface — fills in composeBar wiring (currently Phase 165 placeholder)
