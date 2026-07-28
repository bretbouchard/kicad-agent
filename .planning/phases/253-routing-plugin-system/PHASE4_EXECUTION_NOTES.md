---
title: "Phase 4 — Routing Plugin System: Execution Notes"
tags: [phase-4, routing, execution, planning]
status: ready-for-execution
created: 2026-07-28
depends-on: [Phase 1 (ComponentDataProvider pattern), Phase 3 (final state)]
blocks: [Phase 5 (compliance)] # independent — but Phase 5 isn't blocked on this
---

# Phase 4 — Routing Plugin System: Execution Notes

**Purpose:** Per-task execution manifest for Phase 4. Bridges the gap between PLAN.md (architecture) and actual code changes. Use as the working doc when the worktree spins up.

---

## Source-of-truth references

Before writing any Phase 4 code, **open and confirm** these exist exactly as named. Path prefixes use the conventional `VoltaPCBCore/` module per PROJECT.md. **Verify the actual repo layout** — these are educated guesses and the Volta PCB app structure may have evolved.

| What to find | Conventional location | Reason |
|---|---|---|
| `ComponentDataProvider` Swift protocol | `VoltaPCBCore/Sources/VoltaPCBCore/Providers/ComponentDataProvider.swift` | Phase 4's `RoutingProvider` mirrors this shape (AD-1) |
| `ComponentProviderRegistry` | `VoltaPCBCore/Sources/VoltaPCBCore/Providers/ComponentProviderRegistry.swift` | Phase 4's `RoutingProviderRegistry` mirrors this shape |
| `ProviderAvailability` enum | `VoltaPCBCore/Sources/VoltaPCBCore/Providers/ProviderAvailability.swift` | Reused by `RoutingProvider` directly |
| Existing test base | `VoltaPCBCore/Tests/VoltaPCBCoreTests/Providers/` | New routing tests follow same conventions |
| Settings UI host | `VoltaPCBApp/Sources/VoltaPCBApp/Settings/` or `Views/Settings/` | Routing settings UI lives here |

If any of these paths are wrong, **stop and locate the correct file first** — match naming conventions exactly.

---

## Task-by-task execution notes

### Task 1 — `RoutingProvider` protocol + registry

**New files:**
- `VoltaPCBCore/Sources/VoltaPCBCore/Routing/RoutingProvider.swift` (protocol + supporting types in same file, ≤ 200 LOC)
- `VoltaPCBCore/Sources/VoltaPCBCore/Routing/RoutingProviderRegistry.swift`
- `VoltaPCBCore/Tests/VoltaPCBCoreTests/Routing/MockRoutingProvider.swift` (test fixture)

**Signature sketch (verify against `ComponentDataProvider.swift` for naming):**

```swift
public protocol RoutingProvider: Sendable {
    var name: String { get }
    var displayName: String { get }
    var capabilities: Set<RoutingCapability> { get }
    var availability: ProviderAvailability { get async }

    func route(
        pcbFile: URL,
        rules: RoutingRules,
        progress: (@Sendable (RoutingProgress) -> Void)?
    ) async throws -> RoutingResult

    func estimateTime(board: PCBSummary) -> TimeInterval?
}

public enum RoutingCapability: Sendable, Hashable {
    case autoroute      // fully automatic
    case interactive    // supports step-by-step guidance
    case cloud          // requires network
    case offline        // works fully local
}

public struct RoutingRules: Sendable, Codable, Equatable {
    public var layerCount: Int
    public var clearance: Length          // mm
    public var minTraceWidth: Length      // mm
    public var minViaSize: Length         // mm
    public var netClasses: [NetClass]     // signal, power, analog
    public var timeout: Duration
}

public enum RoutingProgress: Sendable, Equatable {
    case started
    case percent(Double)
    case log(String)
    case completed
}

public struct RoutingResult: Sendable {
    public let pcbFile: URL                  // mutated .kicad_pcb
    public let log: URL                      // saved log file
    public let metrics: RoutingMetrics       // wire count, via count, unrouted nets
    public let providerName: String          // for source attribution
    public let duration: TimeInterval
}

public struct RoutingMetrics: Sendable, Codable, Equatable {
    public let wiresRouted: Int
    public let viasPlaced: Int
    public let unroutedNets: [String]
    public let layers: Int
}

public struct PCBSummary: Sendable, Equatable {
    public let componentCount: Int
    public let netCount: Int
    public let layerCount: Int
    public let boardSize: Size2D
}

public final class RoutingProviderRegistry: ObservableObject, @unchecked Sendable {
    public init()
    public func register(_ provider: RoutingProvider)
    public func unregister(_ provider: RoutingProvider)
    public func provider(named name: String) -> RoutingProvider?
    public var available: [RoutingProvider] { get async }
}
```

**Test expectations (Task 1 only):**
- `MockRoutingProvider` conforms to `RoutingProvider`, returns canned `RoutingResult`
- Registry: register, unregister, dedup, lookup-by-name, "available" filters by `ProviderAvailability`
- Protocol is `Sendable` — compile clean in Swift 6.2 strict concurrency

---

### Task 2 — `FreeroutingProvider` adapter

**New files:**
- `VoltaPCBApp/Sources/VoltaPCBApp/Routing/FreeroutingProvider.swift`
- `VoltaPCBApp/Sources/VoltaPCBApp/Routing/DSNConverter.swift` (DSN ⇄ KiCad conversions)
- `VoltaPCBApp/Tests/VoltaPCBAppTests/Routing/FreeroutingProviderTests.swift`

**External dependencies:**
- Java runtime (`java` on PATH)
- Freerouting JAR — search paths: `/Applications/Freerouting.app/Contents/Java/`, `~/Library/Application Support/freerouting/`, `~/.volta/tools/freerouting.jar`, plus `/opt/homebrew/Cellar/freerouting/*/libexec/`

**Shell-out contract:**

```bash
java -Xmx2g -jar freerouting.jar \
  -de <input.dsn> \
  -do <output.dsn> \
  -mt 1 \                                  # multi-thread
  --log-stdout                             # for progress parsing
```

**DSN ⇄ .kicad_pcb conversion:**
- Inbound: KiCad's built-in CLI `kicad-cli pcb export specctra` (or the Python `kicad-python` wrapper if simpler)
- Outbound: inverse — apply routes from the Freerouting `.dsn` back into a temp `.kicad_pcb` via Specctra DSN routing application (use `kicad-cli pcb import specctra` if available, otherwise use a small Python helper backed by `pcbnew` bindings)

**Error paths to handle:**
- Java not installed → `FreeroutingError.javaNotFound` with macOS install hint (`brew install openjdk`)
- Freerouting JAR not found → `FreeroutingError.jarNotFound` listing search paths the user should check
- DSN conversion failed → surface kicad-cli stderr to the log
- Route timeout (default 10 min, configurable in `RoutingRules.timeout`) → cancel `Process`, write partial result
- All exit codes != 0 → `FreeroutingError.nonZeroExit(code:, stderr:)`

**Test expectations (Task 2):**
- Unit: `DSNConverter` round-trips a synthetic 2-layer netlist (test scaffold can use a fixture `.kicad_pcb` committed to the repo)
- Unit: error mapping for each FreeroutingError case
- Integration: optional, only if CI env has Java + Freerouting — otherwise document as "verified locally by Bret"
- Manual: route a real STM32 dev board end-to-end, import back into a fresh KiCad session, visually confirm

---

### Task 3 — `KiCadNativeRouterProvider` adapter

**New files:**
- `VoltaPCBApp/Sources/VoltaPCBApp/Routing/KiCadNativeRouterProvider.swift`

**Mechanism:**
- Wrap KiCad's interactive router (`kicad-cli pcb route` or headless equivalents) — but be honest: KiCad's interactive router doesn't ship a clean non-interactive CLI
- **Realistic fallback:** this adapter exposes itself as a "use KiCad manually for now" stub that copies the `.kicad_pcb` to a temp location, opens it via `open file.kicad_pcb` (delegates to KiCad app), and waits for the user to save back
- Mark `availability = .requiresManualUserAction` when the user hasn't configured KiCad's path
- `name = "kicad-native"`, `displayName = "KiCad Built-in (manual)"`

**This task exists to keep the registry populated when nothing else is installed. Don't over-engineer — the spike is "don't break the contract when only KiCad native is available."**

**Test expectations (Task 3):**
- Provider registers and reports `availability` based on whether `kicad-cli` is found
- Stub returns clear `requiresManualUserAction` message in `RoutingResult.log`

---

### Task 4 — Cloud routing research — ✅ COMPLETE (no code)

Already shipped as research deliverable. See `RESEARCH/PHASE4_DEEPPPCB_VERDICT.md`. No execution work for this task.

---

### Task 5 — Routing settings UI

**New files:**
- `VoltaPCBApp/Sources/VoltaPCBApp/Settings/RoutingSettingsView.swift`
- `VoltaPCBApp/Sources/VoltaPCBApp/Settings/RoutingProviderPicker.swift` (sub-component)
- Update `VoltaPCBApp/Sources/VoltaPCBApp/Routing/RoutingEngine.swift` to consume `RoutingProviderRegistry`

**UI contract:**
- Settings → Routing panel with:
  - Provider picker (radio list, populated from registry's `available` providers)
  - Per-provider config subview loaded by name
  - "Route this board" action — calls `registry.provider(named:).route(...)` with a streaming progress indicator
  - Before/after preview pane (or just an "open in KiCad to view" button if previews are too expensive)

**Test expectations (Task 5):**
- Snapshot test: `RoutingSettingsView` with a registry containing MockFreeroutingProvider + KiCadNativeStub
- View model test: changing the picker updates the routing target provider
- Acceptance verified by user (Bret) before sign-off

---

## Dependency graph (Phase 4 internal)

```
Task 1 (protocol + registry)
   ├──> Task 2 (Freerouting — depends on Task 1 type signatures)
   ├──> Task 3 (KiCad native — depends on Task 1)
   └──> Task 5 (UI — depends on Task 1)

Task 4 (research) — independent, already complete
```

**Parallelizable after Task 1:**
- Tasks 2 + 3 + 5 can run in three branches once Task 1's signatures stabilize
- Realistically: Task 1 (2 days) → Task 2 (3 days) + Task 3 (1 day, stub) → Task 5 (2 days)

---

## Cross-phase integrations to verify before merge

- ✅ Phase 1 protocols + registries — **STABLE**, mirror directly
- ✅ Phase 2 jlcparts offline fallback — independent, no impact
- ✅ Phase 3 BOM view export — **check**: RoutingResult should be addable to BOM as a downstream action ("route this BOM"), but keep out of scope for Phase 4 unless trivial
- 🔍 VoltaPCBCore module — **must verify** the actual protocol/registry file locations match conventions above

---

## Out of scope (intentional)

- Cloud routing adapter (verdict: deferred, see `PHASE4_DEEPPPCB_VERDICT.md`)
- Custom Volta Router (mentioned in CLOUD_ROUTING_EVALUATION.md "Bret solution" — Bret hasn't defined this; if it materializes, register it as a fourth adapter, no core changes needed)
- SnapEDA-style result metadata enrichment (that's Phase 5 territory if it ships at all)

---

## Exit checklist (Phase 4 → Phase 5)

- [ ] Task 1 types compile clean in Swift 6.2 strict concurrency
- [ ] FreeroutingProvider routes a real .kicad_pcb and imports back without modification
- [ ] KiCadNativeRouterProvider registers, reports availability, errors clearly
- [ ] Routing settings UI has screenshot tests
- [ ] `RoutingProviderRegistry` lets a new dev register a stub provider in ≤ 50 LOC (proves plugin shape)
- [ ] STATE.md frontmatter refreshed to phase 4 complete, milestone progress 4/5 = 80%
- [ ] PR up, Bret reviews, CI green
