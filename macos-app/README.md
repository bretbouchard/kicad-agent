# KiCadAgent — macOS 27+ Liquid Glass App

Native macOS app shell for the KiCad Agent — the closed-box conversational hardware design tool.

## Requirements

- **macOS 27.0+** (Tahoe successor — FoundationModels dependency, Liquid Glass visual language)
- **Xcode 26.5+** (builds against macOS 27 deployment target via SPM)
- **Swift 6.0+** (toolchain ships with Xcode)

> **Note:** The Liquid Glass `.glassEffect()` modifier requires the macOS 27 SDK.
> Until Xcode 27 ships, this app uses `.background(.regularMaterial)` (the canonical
> translucent system material since macOS 12). When the macOS 27 SDK lands, Phase 162
> will re-baseline against the new modifier with no API surface changes. See
> `.planning/phases/161-app-shell-foundation/161-01-SUMMARY.md` for details.

## Build

```bash
cd macos-app
swift build
```

Expected output:

```
Build complete! (X.Xs)
```

## Run

```bash
swift run KiCadAgent
```

This launches the Liquid Glass chat shell. Multi-window via `cmd+N`.

## Test

```bash
swift test --no-parallel --enable-code-coverage
```

**Always run with `--no-parallel`.** SwiftData's in-memory ModelContainer has
a Core Data lifecycle race in parallel execution: when multiple test suites
create local containers and attach them to SwiftUI Views with `@Query`, the
deallocation order is undefined. `ModelContext.reset()` during cleanup can
invalidate models still referenced by `@Query` fault-ins, triggering
`SwiftData/BackingData.swift:835` fatal errors. This is a SwiftData framework
bug, not a project bug — serial execution is the only reliable workaround.

100% line+branch coverage is enforced in CI (TEST-02). Phase 161 covers the
SwiftData models (Project, Conversation). Phase 192 adds full snapshot tests.

## Architecture

| File | Responsibility |
|------|----------------|
| `Sources/KiCadAgent/KiCadAgentApp.swift` | `@main` App, WindowGroup scene, daemon lifecycle hook |
| `Sources/KiCadAgent/DaemonSupervisor.swift` | Daemon lifecycle state machine (Phase 162 wires real spawn) |
| `Sources/KiCadAgent/Views/AppRootView.swift` | NavigationSplitView root, daemon recovery alert |
| `Sources/KiCadAgent/Views/LiquidGlassShell.swift` | Main detail view — chat shell |
| `Sources/KiCadAgent/Views/ChatPlaceholderView.swift` | Empty-state hero card |
| `Sources/KiCadAgent/Views/ProjectSidebar.swift` | Sidebar with project list + create/delete |
| `Sources/KiCadAgent/Models/Project.swift` | SwiftData `@Model` — top-level container |
| `Sources/KiCadAgent/Models/Conversation.swift` | SwiftData `@Model` — conversation envelope |
| `Sources/KiCadAgent/Theme/DesignTokens.swift` | Spacing, typography, color constants |
| `Sources/KiCadAgent/Theme/LiquidGlassModifiers.swift` | Reusable `.regularMaterial` wrappers |
| `Sources/KiCadAgent/Utilities/Logger.swift` | OSLog structured logging helpers |

## Distribution (APP-02)

- **Primary:** Mac App Store via Fastlane `deliver` (Phase 203)
- **Fallback:** Notarized direct download from website if App Store submission is rejected
- **Sandbox:** Enabled (entitlements land with `.xcodeproj` migration in Phase 203)

## Stupid-Proof Status

| Req | Status | Phase |
|-----|--------|-------|
| APP-01 | Daemon recovery UI implemented; supervisor stub surfaces `spawnTimeout` immediately | 161 (real daemon: 162) |
| APP-02 | Notarized direct-download fallback noted above; full signing in 203 | 161 / 203 |
| APP-03 | Daemon binary checksum verification — placeholder for 162 | 162 |
| APP-04 | KiCad install onboarding screen — placeholder for 163 | 163 |
| APP-05 | 5s shutdown timeout + force-kill — placeholder for 162 | 162 |
| APP-06 | Multi-window via WindowGroup; `cmd+N` creates new window natively | 161 |
| APP-07 | System appearance via SwiftUI semantic colors; Dynamic Type via semantic fonts | 161 |

## A11y Status

- Every `Button` has `.accessibilityLabel` ✓
- Every meaningful `Image` has `.accessibilityLabel` or `.accessibilityHidden(true)` ✓
- Color contrast ≥ 4.5:1 via system semantic colors ✓
- Full A11Y-04 (VoiceOver) and A11Y-05 (Dynamic Type XXXL) verification in Phase 192

## Phase 161 — App Shell Foundation

This is the foundational shell. Subsequent phases build on top:

- **162** — Python Daemon Bundling (PyInstaller binary, real supervisor)
- **163** — KiCad Detection + Onboarding
- **165** — Conversation Engine (chat, message list, model integration)
- **168** — Event-Sourced Memory (Track E)
- **192** — Snapshot test infrastructure (Track H)
- **203** — Fastlane build pipeline (Track H)

See `.planning/ROADMAP.md` for the full v6.0 phase plan.
