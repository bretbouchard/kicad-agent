# Council Review — SwiftUI Liquid Glass Perspective

**Reviewer:** swiftui-liquid-glass specialist
**Subject:** v7.0 Vendor-Neutral Manufacturing Layer — Mac App UI
**Date:** 2026-07-10
**Verdict:** Manufacturing layer is data-complete and well-modeled on the Python side; **zero manufacturing UI exists in the Swift app today**. This review describes what should be built and how it maps to the existing Liquid Glass design system.

---

## 0. Critical context: the app does NOT use `.glassEffect()` yet

The most important finding for any SwiftUI work on this codebase: `macos-app/Sources/Volta/Theme/LiquidGlassModifiers.swift` explicitly documents that the app runs on the **macOS 26.x SDK**, where `.background(.regularMaterial)` produces the canonical material. The dedicated `.glassEffect()` modifier ships with the **macOS 27 SDK**, which has not landed yet. The three custom modifiers are the single source of truth:

- `.liquidGlassPanel(corner:)` — standard cards, chat bubbles, sidebar items. Material: `.regular`.
- `.liquidGlassHero(corner:)` — sheets, modals, hero cards. Material: `.ultraThin`.
- `.liquidGlassToolbar(corner:)` — in-content toolbar strips. Material: `.thin`.

All three honor `@Environment(\.accessibilityReduceTransparency)` and swap to opaque `controlBackgroundColor` when the user enables Reduce Transparency (A11Y-06). **Any new manufacturing UI MUST use these modifiers, not raw `.glassEffect()`.** When the SDK 27 migration happens (already noted as deferred in Phase 161 notes), these modifiers become the single swap point.

Design tokens are centralized in `DesignTokens.swift`:
- `Spacing` (xxs=4, xs=8, sm=12, md=16, lg=24, xl=32, xxl=48) on an 8px grid
- `CornerRadius` (small=4, standard=8, large=12, xl=16)
- `Typography` (hero, title, heading, body, caption, mono)
- `ColorTokens` (action, destructive, warning, success, secondaryText, tertiaryText)

All new manufacturing views must draw exclusively from these tokens — no hardcoded colors, spacing, or radii.

---

## 1. What SwiftUI views should exist for the manufacturing workflow?

**None exist today.** A grep for `manufactur|boardspec|handoff|vendordrc` across `macos-app/Sources` returns zero hits. The entire manufacturing feature surface is invisible to the Mac user. This is the single biggest UX gap in v7.0.

The manufacturing workflow is a linear pipeline (BoardSpec → Vendor DRC → Build → Handoff) that maps naturally onto a dedicated navigation destination. Recommended view tree, all under a new `Views/Manufacturing/` folder:

```
ManufacturingWorkspaceView          // top-level tab/section per project
├── BoardSpecEditorView             // META-04/META-05 spec editing
├── VendorDrcResultsView            // DRC-01 vendor check display
│   └── VendorViolationRow          // single violation with severity badge
├── BuildHistoryView                // BUILD-02 versioned builds list
│   ├── BuildCard                   // single build summary
│   └── BuildDiffView               // BUILD-10 build-to-build comparison
├── HandoffWizardView               // HANDOFF-01..09 package creation flow
│   ├── HandoffVendorPickerStep
│   ├── HandoffValidationStep        // tri-state DRC/ERC/vendor gate
│   ├── HandoffReadmePreviewStep     // readme.md preview before bundling
│   └── HandoffResultStep            // success/failure + share/QuickLook
└── ManufacturingManifestView       // manifest.json read-only inspector
```

**Integration point:** The workspace should be reachable from the existing `LiquidGlassShell` toolbar (a "Manufacturing" toolbar button alongside the existing Settings/Share items) and/or as a detail tab within a project. The existing `NavigationSplitView` in `AppRootView.swift` (sidebar + detail) means the manufacturing workspace is a new detail destination, not a new sidebar column.

**Data bridge:** Python ↔ Swift goes through the existing MCP daemon (`MCPClient.swift` + `DaemonMessenger.swift`). The manufacturing CLI subcommands (`build`, `handoff`, `drc-vendor`, `board-metadata`) become MCP tool calls. The Swift side needs Codable value types mirroring the Python dataclasses (see §3 for the BoardSpec example). These belong in a new `Models/Manufacturing/` folder, following the existing `KC*` value-type prefix convention (e.g. `KCBoardSpec`, `KCVendorDrcResult`, `KCHandoffResult`, `KCBuild`).

---

## 2. BoardSpec editor — surface finish picker, color pickers, impedance table

The `BoardSpec` model (`src/volta/manufacturing/board_spec.py`) has these editable dimensions:
- `surface_finish`: enum of 6 (HASL, ENIG, HASL_LEAD_FREE, HARD_GOLD, OSP, ENEPIG)
- `copper_weight_outer_oz` / `copper_weight_inner_oz`: floats > 0
- `soldermask_color`: enum of 8 (GREEN, RED, BLUE, BLACK, WHITE, YELLOW, PURPLE, MATTE_BLACK)
- `silkscreen_color`: enum of 2 (WHITE, BLACK)
- `impedance_requirements`: tuple of `{net_name, target_ohms, reference_layer}`

### Recommended layout

A `Form`-based editor (macOS-native forms are the right pattern for structured field editing) grouped into a `GlassEffectContainer`-equivalent — but since this app uses custom modifiers, wrap each section group in `.liquidGlassPanel()`.

```swift
struct BoardSpecEditorView: View {
    @Binding var spec: KCBoardSpec

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.lg) {
                surfaceFinishSection
                colorSection
                copperWeightSection
                impedanceTableSection
            }
            .padding(Spacing.lg)
        }
        .navigationTitle("Board Specifications")
    }

    private var surfaceFinishSection: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            Label("Surface Finish", systemImage: "circle.lefthalf.filled")
                .font(Typography.heading)
            Picker("Finish", selection: $spec.surfaceFinish) {
                ForEach(KCSurfaceFinish.allCases) { finish in
                    Text(finish.displayName).tag(finish)
                }
            }
            .pickerStyle(.radioGroup)  // 6 options — radio group reads better than menu
            if let note = spec.surfaceFinish.costNote {
                Text(note)
                    .font(Typography.caption)
                    .foregroundStyle(ColorTokens.secondaryText)
            }
        }
        .liquidGlassPanel()
    }
}
```

### Color pickers — show the actual color

Soldermask/silkscreen colors are visual. A plain `Picker` with text labels wastes the affordance. Use a color-swatch grid where each option is a small filled rounded rect in the actual color, selectable via a checkmark overlay:

```swift
private var colorSection: some View {
    VStack(alignment: .leading, spacing: Spacing.sm) {
        Label("Soldermask", systemImage: "paintpalette")
            .font(Typography.heading)
        HStack(spacing: Spacing.xs) {
            ForEach(KCSoldermaskColor.allCases) { color in
                ColorSwatchButton(
                    color: color.swiftUIColor,
                    label: color.displayName,
                    isSelected: spec.soldermaskColor == color
                ) { spec.soldermaskColor = color }
            }
        }
        // Silkscreen is only 2 options (white/black) — a 2-item segmented Picker
        // is more appropriate than a swatch grid here.
        Picker("Silkscreen", selection: $spec.silkscreenColor) {
            ForEach(KCSilkscreenColor.allCases) { c in Text(c.displayName).tag(c) }
        }
        .pickerStyle(.segmented)
    }
    .liquidGlassPanel()
}
```

The swatch button reuses the existing design system:
```swift
struct ColorSwatchButton: View {
    let color: Color; let label: String
    let isSelected: Bool; let action: () -> Void

    var body: some View {
        Button(action: action) {
            RoundedRectangle(cornerRadius: CornerRadius.standard, style: .continuous)
                .fill(color)
                .frame(width: 44, height: 44)
                .overlay(
                    isSelected
                        ? Image(systemName: "checkmark.circle.fill")
                            .foregroundStyle(.white, .black.opacity(0.6))
                        : nil
                )
                .overlay(
                    RoundedRectangle(cornerRadius: CornerRadius.standard)
                        .strokeBorder(Color.primary.opacity(0.2), lineWidth: StrokeWidth.hairline)
                )
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
        .accessibilityValue(isSelected ? "selected" : "not selected")
    }
}
```

### Impedance table — editable list

The impedance requirements are a dynamic list (add/remove rows). A `Table` is overkill for a typically-small list (3-8 controlled-impedance nets). Use a `List` with inline editing fields and an add-row affordance. Common target values (50, 75, 90, 100, 120 ohms per the model docstring) can be offered as quick-pick chips.

```swift
private var impedanceTableSection: some View {
    VStack(alignment: .leading, spacing: Spacing.sm) {
        HStack {
            Label("Controlled Impedance", systemImage: "waveform.path")
                .font(Typography.heading)
            Spacer()
            Button { spec.impedance.append(.empty) } label: {
                Label("Add", systemImage: "plus")
            }
            .buttonStyle(.bordered)
        }
        if spec.impedance.isEmpty {
            Text("No controlled-impedance nets specified.")
                .font(Typography.body)
                .foregroundStyle(ColorTokens.tertiaryText)
        } else {
            ForEach($spec.impedance) { $req in
                ImpedanceRow(requirement: $req) { spec.impedance.removeAll { $0.id == req.id } }
            }
        }
    }
    .liquidGlassPanel()
}
```

---

## 3. Vendor DRC results — violation list, severity badges, fix suggestions

`VendorDrcResult` (`vendor_drc.py`) returns a tuple of `Violation` instances (`erc_drc.py`), each with `{description, severity, type, items}`. Severity is tri-state: ERROR / WARNING / EXCLUSION. The check types are: `vendor_trace_width`, `vendor_drill_size`, `vendor_annular_ring`, `vendor_via_diameter`, `vendor_clearance`. Each violation's `items` dict carries `actual_mm` and `required_mm` — this is the data for a "how to fix" hint.

### Recommended layout

The app already has the right pattern in `ApprovalGatesView.swift`: severity-colored icon, title, timestamp, contextual rows, and the `LabeledRow` + `EscalationBadge` reusable components. The vendor DRC view should reuse `LabeledRow` and mirror the severity-color mapping from `ApprovalGatesView.severityColor`.

```swift
struct VendorDrcResultsView: View {
    let result: KCVendorDrcResult
    @State private var severityFilter: SeverityFilter = .all

    var body: some View {
        VStack(spacing: 0) {
            summaryHeader
            Divider().opacity(0.3)
            filterBar
            violationList
        }
    }

    private var summaryHeader: some View {
        HStack(spacing: Spacing.md) {
            Image(systemName: result.passed ? "checkmark.seal.fill" : "exclamationmark.triangle.fill")
                .font(.system(size: 28))
                .foregroundStyle(result.passed ? ColorTokens.success : ColorTokens.destructive)
            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text(result.passed ? "Passes \(result.vendor) requirements" : "\(result.errors.count) violations")
                    .font(Typography.title)
                Text("\(result.profileName) — \(result.checksRun.count) checks run")
                    .font(Typography.caption)
                    .foregroundStyle(ColorTokens.tertiaryText)
            }
            Spacer()
            // Pass/fail hero badge
            PassFailBadge(passed: result.passed)
        }
        .liquidGlassHero()
        .padding(Spacing.lg)
    }
}
```

### Violation row with severity badge and fix suggestion

The `items` dict on each violation carries `actual_mm` and `required_mm`. This is enough to render a concrete "increase to Xmm" suggestion without an LLM call:

```swift
struct VendorViolationRow: View {
    let violation: KCViolation

    var body: some View {
        HStack(alignment: .top, spacing: Spacing.sm) {
            SeverityBadge(severity: violation.severity)
            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text(violation.description)
                    .font(Typography.body)
                    .textSelection(.enabled)
                if let fix = fixSuggestion {
                    Label(fix, systemImage: "wrench.and.screwdriver")
                        .font(Typography.caption)
                        .foregroundStyle(ColorTokens.warning)
                }
                // Render the items dict as compact chips
                if !violation.items.isEmpty {
                    FlowLayout(spacing: Spacing.xs) {
                        ForEach(violation.items, id: \.key) { key, value in
                            Chip(text: "\(key): \(formatted(value))")
                        }
                    }
                }
            }
            Spacer()
        }
        .padding(Spacing.sm)
        .liquidGlassPanel()
    }

    private var fixSuggestion: String? {
        guard let actual = violation.items.first(where: { $0.key == "actual_mm" })?.value,
              let required = violation.items.first(where: { $0.key == "required_mm" })?.value
        else { return nil }
        return "Increase from \(actual)mm to at least \(required)mm"
    }
}
```

### Severity badge — reuse the escalation-badge pattern

`ApprovalGatesView.swift` already has `EscalationBadge`. Extract the badge pattern into a shared `SeverityBadge` that maps `KCSeverity` to color + icon, since both the approval gates and the DRC results need it:

```swift
struct SeverityBadge: View {
    let severity: KCSeverity
    var body: some View {
        Label(severity.label, systemImage: severity.systemImage)
            .font(Typography.caption.weight(.semibold))
            .padding(.horizontal, Spacing.xs)
            .padding(.vertical, Spacing.xxs)
            .background(severity.color.opacity(0.15), in: Capsule())
            .foregroundStyle(severity.color)
            .accessibilityLabel("Severity: \(severity.label)")
    }
}

extension KCSeverity {
    var color: Color {
        switch self {
        case .error:     return ColorTokens.destructive
        case .warning:   return ColorTokens.warning
        case .exclusion: return ColorTokens.tertiaryText
        }
    }
    var systemImage: String {
        switch self {
        case .error:     return "xmark.octagon.fill"
        case .warning:   return "exclamationmark.triangle.fill"
        case .exclusion: return "minus.circle"
        }
    }
}
```

---

## 4. Build history — timeline, cards, status badges

The `Build` record (`build.py`) has a forward-only lifecycle: `DRAFT → VALIDATED → EXPORTED → HANDED_OFF`. Each build carries `build_id`, `board_rev`, `git_sha`, `created_at`, `status`, and artifacts. `BuildDiff` (`diff_builds`) compares two builds with `*_added` / `*_removed` tuples.

### Recommended layout: list of cards with a lifecycle progress indicator

A vertical timeline (the app already has `DecisionTimelineView.swift` with the vertical-dot-and-line pattern) is the right metaphor, but each entry is richer than a timeline row — it's a card with a status progress bar showing where the build sits in the 4-stage lifecycle.

```swift
struct BuildHistoryView: View {
    let builds: [KCBuild]

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: Spacing.md) {
                ForEach(builds.sorted(by: { $0.createdAt > $1.createdAt })) { build in
                    BuildCard(build: build)
                }
            }
            .padding(Spacing.lg)
        }
        .navigationTitle("Build History")
    }
}

struct BuildCard: View {
    let build: KCBuild

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            HStack {
                VStack(alignment: .leading, spacing: Spacing.xxs) {
                    Text("Build \(build.boardRev)")
                        .font(Typography.heading)
                    Text(build.createdAt.formatted(date: .abbreviated, time: .standard))
                        .font(Typography.caption)
                        .foregroundStyle(ColorTokens.tertiaryText)
                }
                Spacer()
                BuildStatusBadge(status: build.status)
            }
            BuildLifecycleProgress(status: build.status)
            HStack(spacing: Spacing.lg) {
                Label(build.gitSha.prefix(8), systemImage: "number")
                    .font(Typography.mono)
                Label("\(build.artifacts.count) artifacts", systemImage: "doc.fill.on.doc")
            }
            .font(Typography.caption)
            .foregroundStyle(ColorTokens.secondaryText)
        }
        .liquidGlassPanel()
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Build \(build.boardRev), \(build.status.label)")
    }
}
```

### Lifecycle progress — the 4-stage bar

```swift
struct BuildLifecycleProgress: View {
    let status: KCBUILDStatus
    private let stages: [KCBUILDStatus] = [.draft, .validated, .exported, .handedOff]

    var body: some View {
        HStack(spacing: Spacing.xxs) {
            ForEach(stages, id: \.self) { stage in
                Capsule()
                    .fill(stage <= status ? ColorTokens.success : ColorTokens.tertiaryText.opacity(0.2))
                    .frame(height: 4)
            }
        }
        .accessibilityLabel("Lifecycle progress: \(status.label), stage \(currentIndex + 1) of 4")
    }
}
```

### Build diff view

`BuildDiff` gives `source_files_added/removed`, `artifacts_added/removed`, and three bool flags (`status_changed`, `git_sha_changed`, `board_rev_changed`). A two-column comparison (left = old, right = new) with green/red annotations for added/removed is the standard macOS pattern (Xcode diff, Fork). Reuse `LabeledRow` for the bool flags.

---

## 5. Handoff package creation flow — wizard with validation gate

`export_handoff` (`handoff.py`) is an 11-step pipeline with a hard pre-handoff validation gate (DRC/ERC/vendor DRC). The tri-state validation (`True` = passed, `False` = blocks, `None` = inconclusive) is the critical UX element. **Do not use a single "Create Package" button** — the validation gate must be visible before the user commits, because a failed DRC produces NO zip (per HANDOFF-06/Pitfall 5).

### Recommended: a 4-step wizard in a sheet

This is the highest-stakes manufacturing action (produces artifacts destined for a fab house), so it deserves a guided flow, not a fire-and-forget button. Present as a `.sheet` with `interactiveDismissDisabled(true)` once packaging starts.

```
Step 1: Vendor picker         — Picker of 11 profiles + "generic" + include_step/render toggles
Step 2: Pre-flight validation — runs DRC/ERC/vendor DRC; shows tri-state results; blocks "Next" on hard False
Step 3: Readme preview        — renders the generated readme.md (markdown) before bundling
Step 4: Package + result      — ProgressView during zip; success shows share/QuickLook; failure shows error
```

```swift
struct HandoffWizardView: View {
    @State private var step: HandoffStep = .vendor
    @State private var vendor: String = "jlcpcb"
    @State private var includeStep = true
    @State private var validation: KCHandoffValidation?
    @State private var isPackaging = false
    @State private var result: KCHandoffResult?
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 0) {
            HandoffStepIndicator(currentStep: step)
                .padding(Spacing.md)
            Divider().opacity(0.3)
            Group {
                switch step {
                case .vendor:    vendorPickerStep
                case .validation: validationStep
                case .readme:    readmePreviewStep
                case .result:    resultStep
                }
            }
            .frame(maxHeight: .infinity)
            Divider().opacity(0.3)
            wizardFooter
        }
        .frame(minWidth: 560, minHeight: 520)
        .interactiveDismissDisabled(isPackaging)
    }

    private var wizardFooter: some View {
        HStack {
            if step != .vendor && result == nil {
                Button("Back") { step = step.previous() }
                    .buttonStyle(.bordered)
            }
            Spacer()
            if step == .result {
                Button("Done") { dismiss() }
                    .buttonStyle(.borderedProminent)
            } else if step == .validation {
                Button("Next") { step = .readme }
                    .buttonStyle(.borderedProminent)
                    .disabled(validation?.hasBlockers != false)  // blocks on hard False
            } else {
                Button("Next") { step = step.next() }
                    .buttonStyle(.borderedProminent)
            }
        }
        .padding(Spacing.md)
    }
}
```

### Step indicator — horizontal, 4 dots

```swift
struct HandoffStepIndicator: View {
    let currentStep: HandoffStep

    var body: some View {
        HStack(spacing: Spacing.sm) {
            ForEach(HandoffStep.allCases) { step in
                HStack(spacing: Spacing.xxs) {
                    Circle()
                        .fill(step <= currentStep ? ColorTokens.action : ColorTokens.tertiaryText.opacity(0.3))
                        .frame(width: 8, height: 8)
                    Text(step.shortLabel)
                        .font(Typography.caption)
                        .foregroundStyle(step <= currentStep ? Color.primary : ColorTokens.secondaryText)
                }
                if step != HandoffStep.allCases.last {
                    Rectangle()
                        .fill(ColorTokens.tertiaryText.opacity(0.2))
                        .frame(height: 1)
                        .frame(maxWidth: 60)
                }
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Step \(currentStep.index + 1) of 4: \(currentStep.label)")
    }
}
```

### Packaging progress — indeterminate with phase label

`export_handoff` is a single MCP call (the Python side does all 11 steps). From Swift's perspective, it's one async call that may take 10-60 seconds (Gerber/drill/CPL/BOM/STEP/PDF exports). Show an indeterminate `ProgressView` with a rotating phase label so the user knows it hasn't frozen:

```swift
private var resultStep: some View {
    Group {
        if isPackaging {
            VStack(spacing: Spacing.md) {
                ProgressView()
                    .controlSize(.large)
                Text(packagingPhaseLabel)
                    .font(Typography.body)
                    .foregroundStyle(ColorTokens.secondaryText)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if let result, result.success {
            HandoffSuccessView(result: result)
        } else if let result {
            HandoffFailureView(error: result.errorMessage)
        }
    }
    .task { await runPackaging() }
}
```

The phase label can rotate on a timer ("Exporting Gerbers…" → "Generating drill files…" → "Building manifest…" → "Compressing…") since the Swift side can't introspect Python pipeline progress without a streaming protocol. This is an honest affordance — it communicates "work is happening" without lying about specific sub-step completion.

---

## 6. Handoff zip sharing — NSSharingService AND QuickLook

Both. They serve different moments in the workflow:

**NSSharingServicePicker** (via `ShareLink`): the natural "I just made this, send it to my CM" action. The app already uses `ShareLink` in `LiquidGlassShell.toolbarContent` for sharing the project name. For a file URL, SwiftUI's `ShareLink(item:)` accepts a `URL` directly:

```swift
struct HandoffSuccessView: View {
    let result: KCHandoffResult

    var body: some View {
        VStack(spacing: Spacing.lg) {
            Image(systemName: "checkmark.seal.fill")
                .font(.system(size: 48))
                .foregroundStyle(ColorTokens.success)
            Text("Handoff package ready")
                .font(Typography.title)
            Text("\(result.zipFileName) — \(formattedSize(result.zipSizeBytes))")
                .font(Typography.caption)
                .foregroundStyle(ColorTokens.secondaryText)

            HStack(spacing: Spacing.sm) {
                ShareLink(item: result.zipURL) {
                    Label("Share", systemImage: "square.and.arrow.up")
                }
                .buttonStyle(.borderedProminent)

                Button {
                    NSWorkspace.shared.activateFileViewerSelecting([result.zipURL])
                } label: {
                    Label("Reveal in Finder", systemImage: "folder")
                }
                .buttonStyle(.bordered)

                QuickLookButton(url: result.zipURL)  // QuickLook for zip contents
            }
        }
        .liquidGlassHero()
        .padding(Spacing.xg)
    }
}
```

**QuickLook** (via `QLPreviewPanel` or the newer `.quickLookPreview`): useful for previewing the zip's *contents* (the readme.md, manifest.json, individual Gerbers) without unzipping. macOS QuickLook supports zip archives natively. For in-app preview of individual artifacts (e.g., the generated readme or the PDF), use the SwiftUI `.quickLookPreview(_:)` scene modifier on a bound URL.

The readme preview step (§8) is separate from this — it shows the readme *before* bundling.

---

## 7. Liquid Glass treatments for manufacturing UI

The app's custom modifier system is the constraint here. Specific recommendations:

1. **BoardSpec editor sections**: each section group (surface finish, colors, copper, impedance) gets `.liquidGlassPanel()`. This creates the card-stack aesthetic that matches the existing `ConversationRow` and `ApprovalGatesView` patterns.

2. **Vendor DRC summary header**: use `.liquidGlassHero()` (the `ultraThin` material + shadow) for the pass/fail summary. This is the most prominent element on the DRC screen and deserves the hero treatment, mirroring how `ApprovalGatesView` uses `.liquidGlassPanel()` but elevating to hero for the result banner.

3. **Handoff wizard**: the wizard container is a sheet — use `.liquidGlassHero()` on the overall sheet background (consistent with `SettingsSheet`). The step indicator and footer use `.liquidGlassToolbar()`.

4. **Violation rows and build cards**: `.liquidGlassPanel()` — these are list items, matching `ConversationRow`.

5. **Severity/status badges**: capsules with 15% opacity background tint (`severity.color.opacity(0.15)`). This is already the pattern in `DaemonBadge` inside `LiquidGlassShell.swift` (`color.opacity(0.12), in: Capsule()`). Do NOT add glass to badges — they need to read as solid, semantic chips.

6. **When SDK 27 lands**: all five `.liquidGlassPanel/Hero/Toolbar` modifiers become the single swap point to `.glassEffect(.regular/.prominent, in:)`. The manufacturing UI automatically inherits the migration. Do NOT introduce raw `.glassEffect()` calls in manufacturing views — route everything through the theme modifiers so the future migration is one file, not dozens.

7. **Glass intensity (WWDC26)**: when macOS 27 ships with the system-wide Liquid Glass intensity switch, the DRC violation badges and status indicators must remain readable at minimum intensity. Because badges use solid opacity tints (not glass), they're immune. The `.liquidGlassPanel` cards will dim — verify that violation description text remains legible at minimum intensity by keeping `.foregroundStyle(Color.primary)` (already the pattern).

---

## 8. Readme preview before bundling

`_generate_readme` in `handoff.py` produces a markdown string with sections: title, board specs, impedance table, validation results, artifacts table, contact. The preview should render this as formatted markdown (not raw source) so the user can verify it reads correctly before it ships to the CM.

### Recommended: render with AttributedString + SwiftUI

macOS has native markdown parsing via `AttributedString(markdown:)`. For a read-only preview (the readme is generated, not user-edited in v7.0), this is sufficient — no need for a full webview or third-party markdown renderer:

```swift
struct HandoffReadmePreviewStep: View {
    let readmeMarkdown: String

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.md) {
                if let attributed = try? AttributedString(markdown: readmeMarkdown) {
                    Text(attributed)
                        .textSelection(.enabled)
                } else {
                    Text(readmeMarkdown)
                        .font(Typography.mono)
                        .textSelection(.enabled)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(Spacing.lg)
        }
        .liquidGlassPanel()
    }
}
```

**Caveat:** `AttributedString(markdown:)` supports a subset of CommonMark. The readme uses GFM-style tables (`| Net | Target | ...`), which `AttributedString(markdown:)` does NOT render as tables — it'll show the raw pipe characters. For table rendering, either:
- (a) Pre-process the markdown to extract tables and render them as SwiftUI `Grid`/`Table`, or
- (b) Use a `WebView` (native in macOS 26+ per the WebKit-for-SwiftUI WWDC25 session) with a markdown-to-HTML pre-render.

Option (a) is lighter for a read-only preview with at most 2 small tables (impedance + artifacts). The impedance table has 3 columns; the artifacts table has 2. A simple regex split on `|` with header-row detection is sufficient.

**Do NOT make the readme editable in v7.0.** The readme is generated from BoardSpec + validation results. If the user wants to change it, they edit the BoardSpec and re-generate. Making the readme directly editable would create a divergence between the spec and the readme that the manifest can't reconcile.

---

## 9. Accessibility concerns with manufacturing data

The app has strong a11y foundations (A11Y-05/06/07/08 in `LiquidGlassModifiers.swift`). Manufacturing data adds specific concerns:

1. **Color-encoded meaning must have text alternatives.** The soldermask color swatches (§2) use color alone to convey the option. Each swatch MUST have `.accessibilityLabel(color.displayName)` and `.accessibilityValue(isSelected ? "selected" : "not selected")` — already in the code sketch above. The build lifecycle progress bar (§4) uses green-filled capsules — it MUST have `.accessibilityLabel("Lifecycle progress: stage \(n) of 4, \(status.label)")`.

2. **Tri-state validation must be screen-reader-friendly.** The `HandoffValidation` tri-state (`True`/`False`/`None`) maps to "passed"/"failed"/"inconclusive". Do NOT rely on color (green/red/grey) alone — use explicit text labels and `accessibilityValue`. "Inconclusive" is the tricky one: it means "kicad-cli not installed or no schematic" and must be communicated distinctly from "passed" so a VoiceOver user doesn't ship an unvalidated board.

3. **Numeric measurements (mm) must be spoken with units.** Violation rows show `0.127mm`. VoiceOver reads "0.127 M M" if not annotated. Use `accessibilityValue("\(value, specifier: "%.3f") millimeters")` on measurement text.

4. **Long violation descriptions need `textSelection(.enabled)`.** Already the pattern in `LabeledRow` (line 139 of `ApprovalGatesView.swift`). Violation descriptions can be long and technical — users will want to copy them into bug reports or CM emails.

5. **High contrast (A11Y-07) and increase contrast (A11Y-08):** severity badges at 15% opacity background may disappear in high-contrast mode. The `ColorTokens` semantic colors adapt, but the opacity overlay may need to increase to 25-30% under `accessibilityShowButtonShapes` or when the system reports increased contrast. Test with `accessibilityEnabled` settings.

6. **Reduce Motion (already handled in `LiquidGlassShell`):** the handoff wizard's step transitions and the packaging phase-label rotation should respect `@Environment(\.accessibilityReduceMotion)`. The phase label can rotate text without animation; the step indicator should cross-fade rather than slide when reduceMotion is true.

7. **DRC violation counts in dynamic tables:** if a board has 500+ violations (realistic for a dense PCB), the `LazyVStack` must lazy-load (already the pattern in `DecisionTimelineView` with `onLoadMore`). Add pagination or virtualization — do NOT render 500 glass-panel rows simultaneously.

---

## 10. Ideal macOS manufacturing workflow UI — the complete picture

The ideal workflow integrates manufacturing into the existing project-centric NavigationSplitView without becoming a separate app-mode:

**Navigation:** Add a "Manufacturing" section to the project detail area. The existing `LiquidGlassShell` has a chat-centric layout (header, content, compose). Manufacturing is a different mode — recommend a segmented control or a sidebar-within-detail that switches between "Design" (chat) and "Manufacture" (workspace). This mirrors how Xcode separates editing from archiving.

**Progressive disclosure:** The manufacturing surface is complex (specs, DRC, builds, handoff). Don't dump it all at once. The natural flow is:
1. User designs a board (existing chat flow)
2. User opens Manufacturing workspace → sees BoardSpec editor (empty defaults)
3. User runs Vendor DRC → sees results (may show violations to fix)
4. User iterates until DRC passes
5. User creates a Build (snapshot)
6. User runs Handoff wizard → gets a zip

Each step unlocks the next. The UI should visually disable downstream steps until upstream is complete — e.g., the Handoff button is disabled until DRC passes, with a tooltip explaining why.

**Command integration:** Beyond the GUI, expose `build`, `handoff`, `drc-vendor`, `board-metadata` as commands the user can invoke from the chat compose bar ("run a JLCPCB DRC check"). The existing `GSDConversation` views (QuestioningView, ExecuteView, VerifyView) already handle a staged workflow — the manufacturing commands can surface as special message types in the chat that render inline results (DRC violations as cards, build summaries as cards) rather than requiring a full mode switch.

**Native macOS affordances:**
- Drag-and-drop: let users drag a Gerber zip out of the app to Finder/Mail
- Services menu: register the app as a handler for `.kicad_pcb` so "Manufacture this board" appears in Finder's Open With
- Spotlight: index build records by `build_id` and `board_rev` so they're searchable
- Notifications: post a UserNotification when a long-running handoff completes (the app already uses `NotificationCenter` for escalation tiers)

---

## Summary of recommended work (if this becomes a phase)

The manufacturing layer is the most polished part of v7.0 that has **zero user-facing surface**. Priority order:

| Priority | View | Why |
|----------|------|-----|
| P0 | `HandoffWizardView` | The terminal action — without it, the entire manufacturing layer is CLI-only |
| P0 | `VendorDrcResultsView` | Users can't fix what they can't see; DRC violations are the main loop |
| P1 | `BoardSpecEditorView` | Specs are the input to the whole pipeline; needs a GUI for non-CLI users |
| P1 | `KCBoardSpec`/`KCViolation`/`KCHandoffResult` Codable mirrors | Required bridge for any of the above to function |
| P2 | `BuildHistoryView` | Important for versioning, but builds are usable via CLI today |
| P2 | `ManufacturingManifestView` | Read-only inspector; manifest.json is human-readable already |
| P3 | Chat-integrated manufacturing commands | The "run DRC from the compose bar" flow |

The existing design system (`DesignTokens`, `LiquidGlassModifiers`, `LabeledRow`, `SeverityBadge` pattern from `EscalationBadge`) covers ~80% of the component needs. The main new work is the data bridge (Codable mirrors of the Python dataclasses) and the wizard flow.
