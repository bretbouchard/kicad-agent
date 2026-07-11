---
phase: 209-crossfile-mcp-integration
plan: crossfile-mcp-integration
role: apple-elitist-rick
reviewed: 2026-07-10
verdict: REJECT (Apple integration gap)
milestone: v7.0 Vendor-Neutral Manufacturing Layer
---

# Phase 209 Council — Apple Elitist Rick Review

**Reviewer:** Apple Elitist Rick (bleeding-edge iOS/macOS/tvOS/visionOS specialist)
**Verdict: REJECT** — The v7.0 manufacturing layer is a solid Python milestone, but
from the Apple platform perspective it is **invisible**. There is zero Swift-side
integration, the one integration path that does exist (governed MCP calls) will
**crash-reject** every manufacturing op, and the sandbox configuration makes the
handoff workflow impossible in a shipping Mac app. The Python work earns a PASS;
the Apple integration earns a hard REJECT.

---

## Executive Summary — The Hard Truth

The v7.0 manufacturing layer (Phases 205-209) shipped 6 Python modules in
`src/kicad_agent/manufacturing/`, 4 CLI subcommands, a `ManufacturerClient` ABC,
and verified MCP auto-exposure via the Operation-union generator. All of that is
clean, well-tested Python. I am not reviewing the Python — the exec reviewer
already approved it and I agree with that verdict.

I am reviewing **how a macOS 27 user experiences this milestone**, and the answer
is: **they don't.** There is:

- **No UI.** Zero SwiftUI views, zero toolbar buttons, zero menu items, zero
  sheet/panel for board metadata, vendor DRC, builds, or handoff. I grepped
  `macos-app/Sources/` for every manufacturing op name and got nothing.
- **No data model bridge.** `BoardSpec` lives in `.kicad_build_spec.json` next
  to the PCB. The Mac app's `Project` SwiftData `@Model` has no field for it.
  The `.kicadagent` document bundle (Phase 190) has no slot for it.
- **A broken call path.** `MCPClient.governedCall` routes every mutating op
  through `IntentGate.validate`, which throws `unknownOp` for anything not in
  its hardcoded 23-op catalog. The 6 manufacturing ops (`build_handoff_export`,
  `build_create`, `build_list`, `build_show`, `drc_vendor`, `set_board_metadata`)
  are **not in that catalog**. A governed call to manufacture a board will throw
  before it ever reaches the daemon.
- **A sandbox wall.** `KiCadAgent.entitlements` grants only
  `files.user-selected.read-write`. `export_handoff` writes
  `builds/handoff_<timestamp>/` under an arbitrary `project_dir`. In a sandboxed
  app (which this is — `com.apple.security.app-sandbox` is `true`), the daemon
  has no entitlement to write there. The handoff will produce a permission error
  or silently land in a container nobody can find.

The exec reviewer noted "0 edits to `mcp/edit_server.py` (INTEG-01 is
verification-only by design — the Operation-union auto-generation made MCP
exposure free)." That is correct and it is the one genuinely good Apple-adjacent
property of this milestone: the manufacturing ops **do** appear in `tools/list`
automatically. But appearing in the tool list and being callable through the Mac
app's governed pipeline are two different things, and only the first is true.

---

## The Ten Review Questions — Answered Brutally

### 1. How does the manufacturing layer connect to the Mac app? Is there a UI for it?

**It doesn't. There is no UI.**

I read every Swift file under `macos-app/Sources/KiCadAgent/Views/` (33 view
files). Not one references board metadata, vendor DRC, builds, handoff, gerbers,
or manufacturing. The closest the app gets to acknowledging manufacturing exists
is a placeholder string in `ChatPlaceholderView.swift:48`:

> "From idea to manufactured PCB."

That is marketing copy, not a feature. The toolbar (`LiquidGlassShell.swift:170`,
`ToolbarView.swift`) has four actions: New Project, New Window, Share, Settings.
The Share button shares `project.name` (a String) via `ShareLink` — not a file,
not a handoff zip, not even a project bundle.

There is no:
- Board metadata inspector (title/rev/company/date editor)
- Vendor picker (PCBWay / JLCPCB / AISLER / OSH Park / Advanced Circuits)
- Vendor DRC results panel
- Build list / build detail view
- Handoff export button or progress UI
- Manifest viewer

The entire manufacturing layer is reachable only via the CLI (`kicad-agent
handoff <pcb>`) or by a raw `MCPClient.call("kicad.build_handoff_export", ...)`
that nobody in the Swift codebase calls. For a milestone whose entire purpose is
"send boards to ANY manufacturer," the Mac app cannot send a board to anyone.

**Severity: HIGH.** This is the headline gap.

### 2. Does the MCP auto-exposure mean the Mac app's MCPClient can call build_handoff_export?

**At the raw-call level: yes. At the governed-call level: NO, it will throw.**

The good news: `edit_server.py:133` (`_generate_operation_tools`) reflects the
Pydantic `Operation` discriminated union, and I confirmed all six manufacturing
ops (`build_handoff_export`, `build_create`, `drc_vendor`, `read_board_metadata`,
`set_board_metadata`, `set_board_revision`) are members of that union in
`src/kicad_agent/ops/schema.py:566-574`. So `tools/list` will advertise them and
`MCPClient.callRaw("tools/call", ...)` will reach the daemon.

The bad news: the Mac app's actual op-execution path is `governedCall`, not
`callRaw`. Look at `MCPClient.swift:316-328`:

```swift
// 1. IntentGate.validate
let validated: IntentResult
do {
    validated = try governance.intentGate.validate(
        op: opName, args: params,
        requirementId: requirementId, intent: intent
    )
} catch let e as IntentGateError {
    ...
    throw GovernedCallError.intentRejected(e)
}
```

And `IntentGate.validate` (`IntentGate.swift`) does:

```swift
guard let meta = Self.catalog[op] else {
    Self.logger.warning("IntentGate: unknown op '\(op, privacy: .public)'")
    throw IntentGateError.unknownOp(op)
}
```

`Self.catalog` is a hardcoded `static let` with 23 ops (`add_component`,
`pcb_add_segment`, `auto_route`, `query_components`, ...). I grepped it for every
manufacturing op name. **Zero matches.** So the moment a user triggers
"manufacture this board" through any governed UI path, the call dies at the gate
with `unknownOp("build_handoff_export")` before the daemon is ever contacted.

This is the Phase 169 "obdurate runtime" doing exactly what it was designed to
do — reject unknown ops — but the catalog was never updated for v7.0. The
`STATE.md` entry for Phase 169 even says: *"Op catalog hardcoded in Swift (Phase
170 replaces with dynamic tools/list from MCP daemon)."* Phase 170 shipped
without doing that replacement, and v7.0 shipped without adding the new ops
manually. So the catalog is stale twice over.

**Severity: CRITICAL.** This is a silent functional regression for any Mac UI
that tries to use the governed path. Raw `callRaw` works but bypasses the entire
governance layer (IntentGate, DriftDetector, WorkflowStateMachine,
VerificationLoop, OpJournal, AutoLearner, EscalationLadder) — which defeats the
purpose of having shipped Phases 169-170.

**Required fix:** Either (a) add the six manufacturing ops to the Swift
`IntentGate.catalog` with correct `OpMeta` (read-only vs mutating, file types,
requirement IDs), or (b) finally do the Phase 170 deferral and have IntentGate
pull the catalog from the daemon's `tools/list` at handshake time. Option (b) is
correct architecturally; option (a) is the SLC patch.

### 3. Is the CLI subcommand approach the right interface, or should there be a Swift-native API?

**The CLI is the right interface for headless/automation. For the Mac app, you
need a Swift-native API layer. Period.**

The CLI subcommands (`handoff`, `build`, `drc-vendor`, `board-metadata` in
`src/kicad_agent/cli.py:731-917`) are well-structured — flat handlers that build
an op dict and dispatch through `handle_operation`. Good for CI, good for
scripting, good for the `/kicad-agent` skill. I have no complaints about the CLI
itself.

But a Mac app should never shell out to a CLI for a core workflow. The correct
Swift-native layer is a set of `@MainActor` service types that wrap
`MCPClient.governedCall` with typed Swift result structs, mirroring the Python
dataclasses. Right now the result of `build_handoff_export` comes back as
`AnyCodable` and has to be re-serialized and decoded by the caller — there is no
`HandoffResult`, no `Build`, no `BoardSpec`, no `Quote` type on the Swift side.

What's missing (this is the v7.1 Apple track, minimum):

```swift
@MainActor
final class ManufacturingService {
    private let client: MCPClient

    func exportHandoff(pcb: URL, vendor: VendorKey?) async throws -> HandoffResult
    func createBuild(pcb: URL, rev: String?) async throws -> Build
    func listBuilds(pcb: URL) async throws -> [Build]
    func runVendorDRC(pcb: URL, vendor: VendorKey) async throws -> DrcResult
    func readBoardMetadata(pcb: URL) async throws -> BoardMetadata
}

// Swift value types mirroring the Python frozen dataclasses
struct HandoffResult: Decodable, Sendable, Equatable {
    let success: Bool
    let zipPath: String
    let validation: HandoffValidation
    let errorMessage: String
}

struct BoardSpec: Codable, Sendable {  // mirror of manufacturing/board_spec.py
    let surfaceFinish: SurfaceFinish
    let copperWeightOuterOz: Double
    let soldermaskColor: SoldermaskColor
    let impedanceRequirements: [ImpedanceRequirement]
}
```

Without this layer, the Mac app would have to hand-roll `[String: Any]` dicts and
parse `AnyCodable` results in every view — which is exactly the anti-pattern
Phase 164's `KiCadModelProvider` protocol was built to prevent ("SDK types never
leak through KC* value types").

**Severity: MEDIUM.** Not blocking the Python milestone, but it blocks any
credible Mac UI for manufacturing.

### 4. Are there macOS-specific concerns (file paths, app sandbox, entitlements for writing to builds/)?

**Yes. This is the second CRITICAL finding. The handoff workflow is impossible
under the current sandbox configuration.**

`macos-app/Resources/KiCadAgent.entitlements`:

```xml
<key>com.apple.security.app-sandbox</key>        <true/>
<key>com.apple.security.files.user-selected.read-write</key>  <true/>
```

That is the entire filesystem entitlement set. There is no
`files.downloads.read-write`, no temporary-exceptions, no
`network.server` is present but irrelevant here.

Now look at `manufacturing/handoff.py:386-400`:

```python
builds_root = project_dir / "builds"
builds_root.mkdir(parents=True, exist_ok=True)
build_dir_name = f"handoff_{dir_timestamp}"
build_dir = builds_root / build_dir_name
build_dir.mkdir(parents=True, exist_ok=False)
```

And the CLI handler (`cli.py:753-760`) sets `project_dir = str(args.pcb.parent)`.

Here is what happens in a sandboxed Mac app:
1. User opens a `.kicad_pcb` via `NSOpenPanel` (user-selected → granted
   read-write access to **that file**).
2. macOS grants the app a security-scoped access to the file, **not** to its
   parent directory's arbitrary subdirectories.
3. `export_handoff` tries to `mkdir(project_dir / "builds")`.
4. The daemon (a separate PyInstaller process spawned by `ProcessManager`) does
   **not** inherit the security-scoped bookmark. Even if it did, the entitlement
   is `user-selected.read-write` which grants the file the user picked — creating
   sibling directories under the parent is **out of scope** for that entitlement
   in a strict sandbox.
5. The mkdir either fails with `EPERM` or, worse, succeeds into the app's own
   container path (if `project_dir` resolved through a sandbox redirect),
   producing a `builds/` directory the user cannot find in Finder.

The `.kicad_build_spec.json` sidecar (`board_spec.py:81`) has the identical
problem — `save_board_spec` writes next to the PCB, which is outside the
user-selected file grant.

**Required fixes (pick a strategy):**

- **(A) Document-based model.** Make the `.kicadagent` bundle (Phase 190 already
  defines `KicadAgentDocument: FileDocument`) the project root. When the user
  opens the bundle, they grant access to the whole directory tree. Write
  `builds/` *inside* the bundle. This is the Apple-correct path and it already
  has half the scaffolding.
- **(B) User-selected directory.** Add an `NSOpenPanel` step that asks the user
  to pick an output directory (not just the PCB), store a security-scoped
  bookmark, pass that bookmark to the daemon. More friction, but works outside a
  bundle.
- **(C) Downloads folder.** Add `com.apple.security.files.downloads.read-write`
  and write handoffs to `~/Downloads`. Acceptable for a "export" workflow, not
  for "builds that belong to this project."

Option (A) is the only one that respects both the sandbox and the
"conversation state IS source of truth" architecture in `PROJECT.md`. The
`.kicadagent` bundle should own `builds/`, `manifest.json`, and
`.kicad_build_spec.json`.

**Severity: CRITICAL.** Without this, no sandboxed build of this app can produce
a handoff package. This is an App Store rejection waiting to happen if anyone
tries to ship.

### 5. How does the handoff zip workflow feel on macOS? Can users share it via NSSharingService?

**It feels like a CLI tool. There is no macOS sharing integration at all.**

The handoff produces `builds/handoff_<timestamp>/handoff.zip`. On macOS, the
user should be able to:
- Drag the zip to Mail / AirDrop / Messages (ProxyIcon / `NSItemProvider`)
- Click a Share button that presents `NSSharingService` for the zip
- Quick Look the `manifest.json` / `readme.md` inside
- Reveal the zip in Finder (`NSWorkspace.activateFileViewerSelecting`)

None of this exists. The current `ShareLink` in `LiquidGlassShell.swift:192`
shares `project.name` (a String):

```swift
ShareLink(item: project.name) {
    Label("Share", systemImage: "square.and.arrow.up")
}
```

That shares the **project name text**, not a file. Useless for manufacturing.

The correct macOS 27 implementation:

```swift
// After handoff export succeeds, share the zip URL.
ShareLink(
    item: handoffZipURL,           // URL to builds/handoff_.../handoff.zip
    preview: SharePreview(
        "Manufacturing Handoff — \(boardName)",
        image: Image(nsImage: boardThumbnail)
    )
) {
    Label("Share Handoff", systemImage: "square.and.arrow.up")
}
```

And for the toolbar, a dedicated `Button` that runs the export with a progress
indicator (the export runs gerbers + drill + BOM + STEP + PDFs — it takes
seconds to tens of seconds, so a `.progress` overlay or `Task` with cancellation
is mandatory, not optional).

**Severity: MEDIUM.** The workflow is technically possible via `callRaw`, but
the UX is "open Terminal, run a CLI, find the zip in Finder." On a macOS 27
Liquid Glass app, that is unacceptable.

### 6. Is the BoardSpec sidecar JSON the right persistence mechanism for a document-based Mac app?

**No. It is the right mechanism for the Python library. It is wrong for the Mac
app's document model.**

`manufacturing/board_spec.py:67-83` persists `BoardSpec` to
`.kicad_build_spec.json` next to the `.kicad_pcb`. This is fine for a
file-system-native tool. But the Mac app has two other persistence layers that
this sidecar ignores:

1. **SwiftData `Project` model** (`Project.swift`) — the in-app database that
   drives the sidebar, conversations, decisions. `Project` has no
   `boardSpec` field, no `surfaceFinish`, no `impedanceRequirements`.
2. **`.kicadagent` document bundle** (`KicadAgentDocument.swift`, Phase 190) —
   a `FileDocument` backed by a directory with `manifest.json`,
   `conversation.jsonl`, `decisions.jsonl`, `snapshots/`, `renders/`. No
   `board_spec.json` slot.

So the sidecar lives in a third location that neither Swift layer knows about.
When the user sets "ENIG finish, 2oz copper, 50Ω impedance on USB nets" in (a
hypothetical) Mac UI, where does it go? If it goes to the sidecar, SwiftData
doesn't know and the sidebar won't reflect it. If it goes to SwiftData, the
Python handoff won't read it (it reads the sidecar).

**Required fix:** The `BoardSpec` must be a first-class citizen of the
`.kicadagent` bundle. Concretely:
- Add `boardSpec: BoardSpec?` to `BundleManifest` in `KicadAgentDocument.swift`.
- Add a Swift `BoardSpec: Codable, Sendable` struct mirroring the Pydantic model.
- On handoff export, the Swift layer writes the sidecar from the bundle's stored
  spec (so the Python `load_board_spec` finds it), OR the Python layer learns to
  read the spec from the bundle.

The sidecar can survive as a **projection** of the bundle for the CLI/Python
path, but it must not be the source of truth for the Mac app.

**Severity: MEDIUM-HIGH.** This is a data-model coherence bug that will cause
"the Mac app says ENIG but the handoff says HASL" reports once a UI exists.

### 7. Should the ManufacturerClient ABC be a Swift protocol instead of (or in addition to) Python ABC?

**In addition to. The Python ABC is correct for the daemon. A Swift protocol is
required for any Mac-native vendor integration.**

`manufacturing/manufacturer_client.py` defines a clean Python ABC:

```python
class ManufacturerClient(ABC):
    @abstractmethod
    def quote(self, board_spec: Any, quantity: int = 1, **kwargs: Any) -> Quote: ...
    @abstractmethod
    def place_order(self, quote: Quote, **kwargs: Any) -> OrderResult: ...
    @abstractmethod
    def get_status(self, order_id: str) -> OrderStatus: ...
```

This is fine for Phase 210's daemon-side adapters (DEFERRED to v7.1). But the
moment a Mac app wants to:
- Show a vendor quote in a SwiftUI sheet
- Let the user place an order with Face ID / Touch ID confirmation
- Poll order status in the background and surface a notification

...it needs a Swift protocol, because those are all main-actor UI concerns that
should not round-trip through `AnyCodable` dicts. The Swift protocol should
mirror the Python ABC exactly so the two stay in lockstep:

```swift
@MainActor
protocol ManufacturerClient: Sendable {
    func quote(spec: BoardSpec, quantity: Int) async throws -> Quote
    func placeOrder(quote: Quote) async throws -> OrderResult
    func getStatus(orderId: String) async throws -> OrderStatus
}

// Daemon-backed implementation for v7.0 parity
@MainActor
final class DaemonManufacturerClient: ManufacturerClient {
    private let mcp: MCPClient
    func quote(spec: BoardSpec, quantity: Int) async throws -> Quote {
        try await mcp.governedCall("kicad.manufacturer_quote",
            params: ["spec": spec.asDict(), "quantity": quantity],
            requirementId: "INTEG-05", intent: "request quote",
            as: Quote.self)
    }
}
```

**Critical nuance — the quote-only scope guard.** The Python ABC's docstring
correctly notes (Pitfall 8): *"If activated, scope to QUOTE ONLY first — quoting
is read-only and safe; ordering has financial consequences."* The Swift protocol
**must** enforce this at the type level: `func placeOrder` should be gated
behind a `LocalAuthentication` challenge (`LAContext.authenticate(reason:)` with
`.deviceOwnerAuthenticationWithBiometrics`) before the call is even allowed to
form. Ordering PCBs is a financial commitment; it should not be a tap-to-commit
button. This is the kind of thing that earns an App Review rejection if done
wrong and a great user experience if done right.

**Severity: LOW for v7.0** (Phase 210 is deferred, no adapters exist yet).
**Severity: HIGH for v7.1** (must be designed before the first adapter ships).

### 8. Does the manufacturing layer respect macOS sandbox conventions?

**No. See finding #4. The layer assumes POSIX filesystem freedom that the
sandbox does not grant.**

Specific violations:
- `handoff.py:386` `mkdir(parents=True)` under `project_dir/builds` — outside
  user-selected-file grant.
- `board_spec.py:81` writes `.kicad_build_spec.json` next to the PCB — outside
  the file grant (sibling file, not the selected file).
- `build.py:116` `Build.save(path)` writes `build.json` under `builds/` — same
  problem, cascaded.
- `build.py:154` `subprocess.run(["git", "rev-parse", "HEAD"], cwd=project_dir)`
  — in a sandbox, `git` may not be invokable from the daemon's context, and
  `project_dir` may not be reachable. The graceful `"unknown"` fallback masks
  this, but it means the build record will always show `git_sha="unknown"` in a
  sandboxed shipping app.
- The daemon itself (`daemon-sandbox.entitlements`) has
  `app-sandbox=true` + `user-selected.read-write` only — so even if the Mac app
  could reach the path, the daemon subprocess cannot.

The `daemon-sandbox.entitlements` is more restrictive than the app's (no
`network.server`), which is good defense-in-depth — but it means the daemon
**cannot** write anywhere except user-selected files, which it has no way to be
granted at runtime because it's a separate process.

**Required architecture change:** The Mac app must obtain the security-scoped
bookmark, `startAccessingSecurityScopedResource()` on the **directory**, and
pass the daemon a path that is already accessible. The cleanest version: the
`.kicadagent` bundle is the granted directory; everything (builds, specs,
manifests) lives inside it; the daemon writes to bundle-relative paths.

**Severity: CRITICAL** (same as #4 — this is the same finding from the filesystem
angle).

### 9. Any deprecated API usage in the Mac app side that touches manufacturing?

**No deprecated APIs, because there is no Mac app manufacturing code to deprecate.**

But since the question is asked, I audited the Mac app's daemon integration layer
(`ProcessManager.swift`, `DaemonMessenger.swift`, `MCPClient.swift`,
`KiCadAgentApp.swift`) for general Apple-platform health, since that's the layer
manufacturing would ride on. Findings:

**GOOD (these are correct):**
- `Package.swift` targets macOS 27 via `unsafeFlags(["-target", "arm64-apple-macosx27.0"])` — correct workaround for the SPM `.v27` enum not existing in Xcode 26.5. The DEVNOTE is honest about removing it when Xcode 27 ships. ✅
- `swift-tools-version: 6.2` — current. ✅
- `@MainActor` isolation on `ProcessManager`, `DaemonMessenger`, `MCPClient` — correct for Swift 6 concurrency. ✅
- `@Observable` macro (not `ObservableObject`) on `ProcessManager` — modern Observation framework, not the deprecated `Combine` pattern. ✅
- `Logger(subsystem:category:)` (OSLog) — correct, not `print()`. ✅
- `ContinuousClock` / `Task.sleep(for:)` — modern Swift Clock API, not `asyncAfter(deadline:)`. ✅
- `SHA256` from `CryptoKit` — correct, not CommonCrypto. ✅
- `Info.plist` has `LSMinimumSystemVersion: 27.0`. ✅

**MINOR FLAGS (not manufacturing-specific, but I am an elitist):**
- `KiCadAgentApp.swift:89` uses `.modelContainer(for: ModelSchemaRegistry.v600Schema)` — correct SwiftData, but the schema is a frozen `[any PersistentModel.Type]` array. When you add `BoardSpecRecord` to SwiftData for manufacturing metadata, you MUST bump to a `VersionedSchema` per the Phase 177 CloudKit constraint noted in the file. Do not silently append to `v600Schema`.
- `LiquidGlassShell.swift:192` `ShareLink(item: project.name)` — works, but once you share files you need `ShareLink(item: URL)` with `SharePreview`. The current form shares text only.
- `ProcessManager.swift:160` hardcodes `/Users/bretbouchard/apps/kicad-agent/...` as a dev-mode path. Fine for now (dev fallback), but it will ship in the binary — strip it for release or gate it behind `#if DEBUG`.
- The `Package.swift` now declares dependencies on `mlx-swift-lm` and `swift-huggingface` (Phase 210) but the manufacturing milestone is Phase 209/210 of a *different* roadmap (v7.0 vs the MLX phases). Confirm these deps are actually needed for the current build target — pulling HuggingFace tokenizers into a binary that only needs manufacturing is bloat.

**DEPRECATION CHECK:** No `GCGamepad`, no `OpenGL`, no `UIWebView`, no
`NSUserNotificationCenter`, no `SiriKit/INExtension`, no `UISceneDelegate`,
no completion-handler async patterns in the daemon layer. The codebase is clean
on deprecations. The problem is missing features, not deprecated ones.

**Severity: N/A** (no findings in scope; the flags above are general code health).

### 10. What's the ideal user journey from the Mac app to manufacturing handoff?

This is what the experience **should** be. None of it exists today.

```
[1] User opens a .kicadagent bundle (or creates one).
    └─ NSOpenPanel grants security-scoped access to the bundle directory.
       The daemon inherits access via the bundle path (sandbox-safe).

[2] User designs via chat (existing v6.0 flow). Board reaches "ready to fab."
    └─ A "Manufacturing Readiness" indicator in the sidebar turns green when
       ManufacturingReadinessGate passes (the Python gate from Phase 91/207
       already exists — surface it in Swift).

[3] User clicks "Manufacture" in the toolbar (new button, Liquid Glass style).
    └─ A ManufacturingSheet appears:
       ├─ Vendor picker (PCBWay / JLCPCB / AISLER / OSH Park / Advanced Circuits / Generic)
       │   Each row shows: name, layer count, min track, lead time, source link.
       ├─ BoardSpec editor: surface finish, copper weight, mask/silk color,
       │   impedance table. Bound to the .kicadagent bundle's BoardSpec.
       ├─ Pre-handoff DRC summary (drc_passed / erc_passed / vendor_drc_passed).
       └─ "Export Handoff" button (glassProminent).

[4] User clicks "Export Handoff."
    └─ Task with progress overlay (gerbers → drill → BOM → STEP → PDFs).
       Cancellable. Runs through governedCall (IntentGate must be fixed first).
       Writes builds/<rev>_<timestamp>/handoff.zip INSIDE the bundle.

[5] On success, a completion card shows:
    ├─ "Handoff ready: handoff.zip (4.2 MB)"
    ├─ ShareLink(item: zipURL)  ← AirDrop / Mail / Messages
    ├─ Button: "Reveal in Finder" (NSWorkspace activateFileViewerSelecting)
    └─ Button: "Upload to <vendor>" (Phase 210, when adapters exist)

[6] (Future) Vendor quote sheet:
    └─ ManufacturerClient.quote() returns Quote structs for 3 vendors.
       Side-by-side price/lead-time comparison. "Place order" requires
       LocalAuthentication (Face ID / Touch ID) per Pitfall 8.
```

That is a macOS 27 Liquid Glass manufacturing workflow. What exists today is a
Python CLI and a tool list. The gap is the entire UI + service + model layer.

---

## Consolidated Severity Table

| # | Finding | Severity | Blocking? |
|---|---------|----------|-----------|
| 1 | Zero Mac app UI for manufacturing | HIGH | Blocks user value |
| 2 | IntentGate catalog missing all 6 manufacturing ops — `governedCall` throws | **CRITICAL** | Blocks any governed Mac call |
| 3 | No Swift-native manufacturing service / value types | MEDIUM | Blocks clean UI |
| 4 | Sandbox + `builds/` directory write — impossible under current entitlements | **CRITICAL** | Blocks shipping |
| 5 | No NSSharingService / ShareLink for handoff zip | MEDIUM | UX gap |
| 6 | BoardSpec sidecar not in SwiftData or .kicadagent bundle | MEDIUM-HIGH | Data coherence |
| 7 | No Swift ManufacturerClient protocol (for v7.1) | LOW (v7.0) / HIGH (v7.1) | Future blocker |
| 8 | Manufacturing layer assumes POSIX freedom — violates sandbox | **CRITICAL** (same as #4) | Blocks shipping |
| 9 | No deprecated APIs (audit clean) | N/A | — |
| 10 | Ideal journey is fully unbuilt | (aggregate) | — |

---

## What Is Good (Credit Where Due)

To be clear about what is **not** broken:

1. **MCP auto-exposure is genuinely elegant.** The Operation-union reflection in
   `edit_server.py:133` means the 6 manufacturing ops appear in `tools/list` for
   free — zero edit_server edits, verified by the exec reviewer. This is the one
   Apple-adjacent win. The Mac app *can* discover these tools; it just can't
   execute them through the governed path.
2. **Frozen dataclasses everywhere.** `BoardSpec`, `Build`, `BuildDiff`,
   `HandoffResult`, `HandoffValidation`, `Quote`, `OrderResult`, `OrderStatus`
   — all `@dataclass(frozen=True)` (CR-01 pattern). This makes the Swift mirror
   trivial (`let` structs, `Codable`, `Sendable`). Good Python discipline that
   pays off on the Apple side.
3. **Atomic writes.** `board_spec.py:82` and `build.py:116` use `atomic_write`
   (tempfile + `os.replace`). On macOS with APFS, this is copy-on-write safe.
   Correct.
4. **Zip-slip defense (TM-2).** `handoff.py:595` uses basename-only arcnames.
   Good — this prevents the classic extraction vulnerability.
5. **Threat model is documented and mitigated** (TM-1 through TM-6 in
   `handoff.py:8-23`). The security thinking is sound; the sandbox integration
   just wasn't part of the threat model.
6. **CLI subcommand structure is clean** — flat handlers, consistent missing-file
   guards, no new dependencies. Good headless story.
7. **The Python daemon layer (`ProcessManager`, `MCPClient`, `DaemonMessenger`)
   is Apple-modern** — `@MainActor`, `@Observable`, OSLog, CryptoKit, structured
   concurrency, no deprecated APIs. This is the foundation manufacturing would
   ride on, and the foundation is solid.

---

## Required Actions (Prioritized)

### v7.0 Patch (before declaring the milestone "Mac-ready")

1. **Add the 6 manufacturing ops to `IntentGate.catalog`** in
   `macos-app/Sources/KiCadAgent/Governance/IntentGate.swift`. Correct metadata:
   - `read_board_metadata`, `list_vendor_drc_profiles` → readonly, `GOV-11`
   - `drc_vendor` → readonly (runs checks), `GOV-11`
   - `build_list`, `build_show` → readonly, `GOV-11`
   - `set_board_metadata`, `set_board_revision` → mutating, `GOV-01`, `kicad_pcb`
   - `build_create`, `build_handoff_export` → mutating, new requirement ID
     (e.g. `MFG-01`), file types `kicad_pcb` + directory scope
   - Without this, `governedCall` rejects every manufacturing op.

2. **Resolve the sandbox write-path.** Decide: `.kicadagent` bundle owns `builds/`
   (recommended), or add a user-selected-directory `NSOpenPanel` step. Update
   `export_handoff` and `Build.save` to accept a granted output directory, not
   derive one from `project_dir`.

3. **Strip the hardcoded `/Users/bretbouchard/...` dev path** from
   `ProcessManager.swift:160` behind `#if DEBUG` or remove for release builds.

### v7.1 (the real Mac manufacturing track)

4. **Swift value types.** `BoardSpec`, `Build`, `BuildStatus`, `HandoffResult`,
   `HandoffValidation`, `Quote`, `OrderResult`, `OrderStatus`, `DrcResult`,
   `VendorProfile` — all as `Codable, Sendable, Equatable` structs mirroring the
   Python models. One Swift file per concept, in a new
   `Sources/KiCadAgent/Manufacturing/` directory.

5. **`ManufacturingService` (@MainActor).** Wraps `MCPClient.governedCall` with
   typed results. One method per manufacturing op. No `AnyCodable` leaks.

6. **Swift `ManufacturerClient` protocol.** Mirror the Python ABC. Gate
   `placeOrder` behind `LAContext` biometric auth. Daemon-backed concrete impl
   for v7.1 parity.

7. **ManufacturingUI.** A `ManufacturingSheet` / `ManufacturingView` with:
   vendor picker, BoardSpec editor, pre-handoff DRC summary, export button with
   progress, completion card with `ShareLink(item: zipURL)`, "Reveal in Finder"
   via `NSWorkspace`.

8. **BoardSpec in the `.kicadagent` bundle.** Add to `BundleManifest` in
   `KicadAgentDocument.swift`. Bump `ModelSchemaRegistry` to a `VersionedSchema`
   if BoardSpec also lands in SwiftData.

9. **IntentGate dynamic catalog** (the Phase 170 deferral). Pull the op catalog
   from the daemon's `tools/list` at handshake so this class of staleness bug
   never recurs. The current hardcoded catalog is technical debt that bites on
   every milestone.

---

## Final Verdict

**REJECT for the Apple platform integration.**

The Python manufacturing layer is a legitimate v7.0 milestone completion — the
exec reviewer's APPROVE is correct for what was scoped. But the milestone
description says this is a project with "BOTH a Python library AND a macOS app,"
and from the macOS app perspective, v7.0 ships **zero usable manufacturing
capability**: no UI, a broken governed call path, and a sandbox wall that makes
the handoff workflow impossible in any shippable configuration.

If the question is "did the Python team deliver their scope?" — yes. If the
question is "can a Mac user manufacture a board with this app after v7.0?" — no.

The fix is well-defined (see Required Actions). The most urgent is the IntentGate
catalog — it is a 6-line Swift patch that turns a silent `unknownOp` crash into a
working call path. Do that immediately, even before v7.1, so that a raw
`callRaw`-based prototype can at least exercise the pipeline.

**Apple Compliance:**
- Python manufacturing layer: ✅ PASS (frozen dataclasses, atomic writes, threat model)
- MCP auto-exposure: ✅ PASS (ops discoverable via tools/list)
- Mac app IntentGate: ❌ FAIL (manufacturing ops rejected as unknown)
- Mac app sandbox: ❌ FAIL (builds/ write impossible under current entitlements)
- Mac app UI: ❌ FAIL (no manufacturing UI exists)
- Mac app data model: ❌ FAIL (BoardSpec not in SwiftData or bundle)
- Deprecated APIs: ✅ PASS (none found)
- Swift 6 concurrency: ✅ PASS (existing daemon layer is clean @MainActor)

**SLC Compliance:** ❌ FAIL → ✅ PASS (after the 3 v7.0 patches above)

I do not hate this work. I hate that a solid Python milestone is shipping without
its Apple counterpart, and that the one integration point that exists is silently
broken. Fix the IntentGate catalog, fix the sandbox write path, and the
foundation is usable. Then v7.1 builds the experience.

— **Apple Elitist Rick**
*"If your Mac app can't do what your CLI does, you don't have a Mac app — you
have a terminal wrapper with a Liquid Glass skin. v7.0's manufacturing layer
deserves better."*
