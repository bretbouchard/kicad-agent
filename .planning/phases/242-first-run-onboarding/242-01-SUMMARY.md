---
phase: 242
type: summary
status: complete
---

# Phase 242 Summary — First-run Onboarding

## Status: COMPLETE

First-time users now see a guided 3-step tour instead of a blank
project sidebar. The tour walks them through:

1. **Welcome + pick a starter** — LED Blinker, ESP32 Breakout, or
   Op-amp Preamp.
2. **Run a chat** — the canonical prompt for the picked starter is
   pre-filled in the compose bar; the user just hits return.
3. **View result** — explains the inline schematic/PCB render and
   the "Open in KiCad" button.

Gap F3 from `GAP-ANALYSIS-CURRENT.md` closed.

## What Was Added This Phase

| File | Change |
|------|--------|
| `macos-app/Sources/KiCadAgent/State/OnboardingState.swift` | NEW — SwiftData `@Model` with hard-coded canonical id, plus `OnboardingStateStore.current(in:)` fetch-or-create façade |
| `macos-app/Sources/KiCadAgent/Views/Onboarding/Starters.swift` | NEW — 3 starter projects as a value type catalog (id, name, icon, blurb, prompt) |
| `macos-app/Sources/KiCadAgent/Views/Onboarding/OnboardingFlowView.swift` | NEW — 3-step page view with welcome → chat → result; per-step Back/Continue/Start designing CTAs; always-visible Skip; custom page dots |
| `macos-app/Sources/KiCadAgent/Views/AppRootView.swift` | MODIFIED — `@Query` for `OnboardingState`; routing logic: project → LiquidGlassShell, no project + tour not dismissed → OnboardingFlowView, no project + tour dismissed → ChatPlaceholderView with re-entry link |
| `macos-app/Sources/KiCadAgent/Views/ProjectSidebar.swift` | MODIFIED — new `onShowTour` closure; empty-state row with "Show welcome tour" link |
| `macos-app/Sources/KiCadAgent/Views/ChatPlaceholderView.swift` | MODIFIED — optional `onShowTour` closure; secondary "Show welcome tour" link under primary CTA |
| `macos-app/Sources/KiCadAgent/Views/Chat/ChatView.swift` | MODIFIED — listens for `.onboardingStarterPicked` NotificationCenter event; prefills `inputDraft` if it's currently empty (idempotent) |
| `macos-app/Sources/KiCadAgent/KiCadAgentApp.swift` | MODIFIED — added `OnboardingState.self` to `ModelSchemaRegistry.v600Schema` and `makeContainer` |
| `macos-app/Sources/KiCadAgent/Views/Onboarding/KiCadInstallView.swift` | DELETED — orphaned since Phase 220 removed the install path |
| `macos-app/Tests/KiCadAgentTests/OnboardingFlowTests.swift` | NEW — 8 tests |

## OnboardingState (the persistence layer)

`@Model` with a hard-coded `canonicalId` UUID. Single-row semantics:
the `OnboardingStateStore.current(in:)` helper does fetch-or-create
on the canonical id, so multiple app launches never accumulate
duplicate state rows. Fields:

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `id` | UUID | `canonicalId` | Stable key for the one-and-only row |
| `dismissed` | Bool | `false` | User clicked Skip; don't re-nag |
| `completed` | Bool | `false` | User finished all 3 steps |
| `currentStep` | Int | `0` | 0-based step index; survives mid-tour crash |
| `lastShownAt` | Date? | `nil` | For "show me the tour again" rate-limiting |

`OnboardingState` is added to `ModelSchemaRegistry.v600Schema` and
`makeContainer(configuration:)`. Schema bump is *not* required
because the schema is already at v6.0.0 (CloudKit Phase 177 says
bump on **additions**; we are adding a brand-new model class which
counts as a schema change in CloudKit's eyes but is locally
backwards-compatible — see the model version tag for clarity).

## Routing logic in AppRootView

```swift
@ViewBuilder
private var detailContent: some View {
    if let selected = selectedProject {
        LiquidGlassShell(project: selected)
    } else if shouldShowOnboarding {
        OnboardingFlowView(
            onPickStarter: pickStarter,
            onComplete: completeOnboarding,
            onSkip: skipOnboarding
        )
    } else {
        ChatPlaceholderView(
            onStartFirstDesign: createProject,
            onShowTour: showTour
        )
    }
}

private var shouldShowOnboarding: Bool {
    guard projects.isEmpty, !onboardingCompletedInSession else { return false }
    guard let state = onboardingStates.first else { return true }
    return !state.dismissed && !state.completed
}
```

`onboardingCompletedInSession` is a transient `@State` flag that
prevents the tour from re-flashing if the user immediately creates
a second project in the same session (otherwise: pick starter →
project created → tour auto-completes → user creates another
project → tour re-shows because projects.isEmpty is false now but
we just navigated away).

## Starter pre-fill via NotificationCenter

`AppRootView.pickStarter(_:)` posts a notification after creating
the project:

```swift
NotificationCenter.default.post(
    name: .onboardingStarterPicked,
    object: nil,
    userInfo: [
        "projectId": project.id.uuidString,
        "prompt": starter.prompt
    ]
)
```

`ChatView` listens via `.onReceive` and pre-fills `inputDraft`:

```swift
.onReceive(NotificationCenter.default.publisher(for: .onboardingStarterPicked)) { note in
    if let prompt = note.userInfo?["prompt"] as? String,
       !prompt.isEmpty,
       inputDraft.isEmpty {
        inputDraft = prompt
    }
}
```

The `inputDraft.isEmpty` guard makes the prefill idempotent — a
second notification (or a re-entry) doesn't clobber what the user
has already typed.

## Orphaned code removal (Task 5)

`KiCadInstallView.swift` was orphaned since Phase 220 (KiCad no
longer required). `grep -rn "KiCadInstallView"` confirmed only
self-references in the file itself and its `#Preview` blocks. Deleted.

## Tests (all 8 passing)

| Test | What it verifies |
|------|-----------------|
| `OnboardingState: round-trips through SwiftData` | Default state on first launch (dismissed=false, completed=false, currentStep=0, lastShownAt=nil) |
| `OnboardingState: re-fetching returns the same canonical row, not a duplicate` | Multiple `current(in:)` calls return the same row; container has exactly 1 |
| `OnboardingState: canonical id is stable across runs` | Hard-coded UUID constant — defends against accidental UUID() refactor |
| `OnboardingState: skip sets dismissed but not completed` | Skip semantics |
| `OnboardingState: complete sets both flags` | Complete semantics + lastShownAt timestamp |
| `OnboardingStarter: catalog has exactly 3 starters` | Count is the contract |
| `OnboardingStarter: each starter has a non-empty prompt` | No empty prompts, ≤ 200 chars (compose bar preview size) |
| `OnboardingStarter: ids are unique` | No collisions in starter catalog |

## Verification

```
swift build
✔ Build complete! (54.55s, no errors, no new warnings)

swift test --filter "OnboardingFlowTests"
✔ All 8 tests passed
✔ Test run with 8 tests in 1 suite passed after 0.019 seconds.

swift test --filter "ImageAttachmentPipelineTests|ChatPipelineE2ETests|OnboardingFlowTests"
✔ Test run with 31 tests in 3 suites passed after 1.378 seconds.
```

The pre-existing `MLXLocalProvider.minimumVRAMBytes` test failure
and the SwiftData fatal-error process crash are unrelated to this
phase (both existed before Phase 242).

## What's NOT in this slice (deferred)

- **Marketing videos** — text + icon only, per plan.
- **Model setup wizard** — BYOK flow handles that in Settings.
- **Animated transitions between steps** — using simple opacity +
  trailing-edge move transition; could be more elaborate in
  Phase 250 if requested.
- **Tour re-entry button placement on the main toolbar** — currently
  only in the sidebar's empty-state row and the placeholder view.
  Could add a Help menu item as a follow-up.

## Stupid-Proof Verification

- **User-stupid**: Skip button is always visible in the top-right of
  every step. Hitting it lands you on the empty workspace with a
  re-entry link. No way to be trapped in the tour.
- **Magic-stupid**: First launch shows the tour automatically.
  Picking a starter creates the project, switches to it, and
  pre-fills the chat prompt. Hit return → the model responds.
  Zero ceremony.
- **Returning user**: Already-completed tours don't re-show.
  Skip-only users get the tour again on next empty-workspace
  launch (re-engagement), but not on subsequent app launches if
  they have a project.
- **Sidebar empty state**: "Show welcome tour" link is always
  available, even after dismissal, so the user can re-trigger
  the tour if they want to see it again.
