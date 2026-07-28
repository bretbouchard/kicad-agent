# Phase 4: Routing Plugin System

**Phase:** 4
**Status:** Future (blocked on core app maturity)
**Requirements:** REQ-10
**Target:** Apply the same provider plugin pattern to auto-routing engines
**Last refined:** 2026-07-28 (Quilter removed from scope; REQ-10.4 reduced to DeepPCB only)

---

## Architecture Decisions (Pre-Execution)

These are provisional pending alignment with the actual `VoltaPCBCore` source. When execution begins, the protocol shape should be validated against the existing `ComponentDataProvider` / `ComponentProviderRegistry` pattern already shipped in Phase 1.

### AD-1: `RoutingProvider` mirrors `ComponentDataProvider` shape
- Same Sendable constraint
- Same `ProviderAvailability` enum
- Same registry pattern: register/unregister, runtime discovery
- **Difference:** output is `RoutingResult` (mutated .kicad_pcb + log + metrics) not `UnifiedComponent`

### AD-2: Domain isolation
- No provider knows about KiCad, Freerouting, or DeepPCB specifics — only the protocol contract
- Format conversions (DSN↔kicad_pcb, .kicad_pcb→cloud upload) live inside each adapter, not the core

### AD-3: `RoutingRules` is vendor-neutral
- Layer count, design rules (clearance, trace width, via size), net classes — single struct every adapter must accept
- Each adapter may extend with adapter-specific config in its own namespace, but the common surface stays interchangeable

### AD-4: Long-running operation semantics
- `route(...)` is async — but Freerouting can take 10+ minutes
- Must support cancellation, progress streaming, and a `RoutingHandle` for the UI to observe (or similar)
- Cloud routers need queue polling or webhook — protocol will have to accommodate both

### AD-5: Cloud routing is research-gated, not code-gated
- DeepPCB adapter is NOT in scope to build until REQ-10.4 produces a positive accessibility verdict
- If blocked: Task 4 ships as a research outcome doc and Phase 4 completes without a cloud adapter

---

## Pre-Flight Checklist

Before writing any Phase 4 code, confirm:

- [ ] Phase 3 merged to master (✅ verified 2026-07-26)
- [ ] `RoutingProviderRegistry` design aligned with `ComponentProviderRegistry` (open `VoltaPCBCore`, check shape)
- [ ] Freerouting JAR + Java install verification harness ready (CI smoke test or local check script)
- [ ] KiCad CLI invocation path confirmed against the installed KiCad version (paths differ across macOS installs)

---

## Goal

Define `RoutingProvider` protocol and registry, implement Freerouting as the first adapter, and evaluate cloud AI routing services. Users can select their preferred routing engine in settings, and switching routers requires zero changes to core app code.

---

## Tasks

### Task 1: RoutingProvider Protocol
**Requirements:** REQ-10.1, REQ-10.2

- Define `RoutingProvider: Sendable` protocol
  - `var name: String { get }`
  - `var displayName: String { get }`
  - `var availability: ProviderAvailability { get async }`
  - `func route(pcbFile: URL, rules: RoutingRules) async throws -> RoutingResult`
  - `func estimateTime(board: PCBSummary) -> TimeInterval?`
- Define supporting types: `RoutingRules`, `RoutingResult`, `PCBSummary`
- Create `RoutingProviderRegistry: ObservableObject` (same pattern as component registries)

**Acceptance:**
- Protocol defined, Sendable, compiles in Swift 6.2
- Registry works with mock routing provider

### Task 2: Freerouting Adapter
**Requirements:** REQ-10.3

- Detect Freerouting installation (Java JAR, check common paths)
- Shell out via Process: `java -jar freerouting.jar -d <input.dsn> -do <output.dsn>`
- Convert KiCad .kicad_pcb → Specctra .dsn (input format Freerouting expects)
- Convert Freerouting output .dsn → KiCad .kicad_pcb (routes applied)
- Handle: no Java installed, Freerouting not found, routing failures
- Timeout: configurable (default 10 minutes for large boards)
- Progress: parse Freerouting stdout for completion percentage

**Acceptance:**
- Route a simple 2-layer board end-to-end via Freerouting
- Results import back into Volta PCB
- Java/Freerouting not installed → helpful install instructions

### Task 3: KiCad Native Router Baseline
**Requirements:** REQ-10.5

- Integrate KiCad's built-in router (available via KiCad CLI)
- Shim: wrap KiCad's interactive router in the RoutingProvider protocol
- This is the always-available fallback (if KiCad is installed)

**Acceptance:**
- KiCad native router works as baseline when no other router configured
- Results comparable quality to Freerouting for simple boards

### Task 4: Cloud Routing Research — ✅ COMPLETE 2026-07-28
**Requirements:** REQ-10.4
**Status:** Research verdict reached. **No adapter code in Phase 4.** Trigger conditions documented for re-evaluation.

- **Full verdict:** `RESEARCH/PHASE4_DEEPPPCB_VERDICT.md`
- **Outcome:** DeepPCB API exists but is Enterprise-tier ($900/month) with no public REST docs and no self-serve signup. Matches the SiliconExpert / SnapMagic dead-end pattern.
- **Quilter AI:** dropped from scope 2026-07-28 (Bret decision); research in `RESEARCH/CLOUD_ROUTING_EVALUATION.md` preserved for reference.
- **Re-evaluation trigger:** any of (a) DeepPCB publishes self-serve REST docs at `docs.deeppcb.ai`, (b) DeepPCB surfaces API key after standard signup, (c) Volta PCB adds a B2B / enterprise tier, (d) a different cloud router emerges with KiCad-native + self-serve + indie-friendly pricing.

**Acceptance:**
- Evaluation document with clear recommendation
- If accessible: prototype adapter for at least one cloud router
- If blocked: document as deferred with trigger condition

### Task 5: Routing Settings UI
- Provider selection (radio list of available routers)
- Per-provider configuration (layer count, design rules, timeout)
- "Route this board" action with progress indicator
- Result preview: before/after comparison

**Acceptance:**
- User can select routing provider in settings
- Routing progress visible
- Results importable into Volta PCB canvas

---

## Acceptance Criteria

1. ✅ `RoutingProvider` protocol + registry defined (same pattern as Phase 1)
2. ✅ Freerouting routes a real board end-to-end
3. ✅ KiCad native router available as baseline
4. ✅ Cloud routing evaluated with documented recommendation → see `RESEARCH/PHASE4_DEEPPPCB_VERDICT.md`
5. ✅ Settings UI for provider selection
6. ✅ Zero core app changes needed to add a new routing provider

**Per-task execution notes:** `PHASE4_EXECUTION_NOTES.md` (file paths, type signatures, test expectations, dependency order). Use this doc when the worktree spins up.
