# Phase 5: Compliance + File Import

**Phase:** 5
**Status:** Future
**Requirements:** REQ-09, REQ-11
**Target:** Complete the four-protocol architecture with compliance providers and SnapMagic file import

---

## Goal

Define `ComplianceProvider` protocol, add SnapMagic file import for CAD models (since their API is dead), build local compliance rules, and research SiliconExpert accessibility. This completes the "our shit vs their shit" plugin architecture across all four domains.

---

## Tasks

### Task 1: ComplianceProvider Protocol
**Requirements:** REQ-11.1, REQ-11.2

- Define `ComplianceProvider: Sendable` protocol
  - `func checkCompliance(partNumber: String) async throws -> ComplianceReport`
  - `var capabilities: Set<ComplianceCapability> { get }`
- Define types: `ComplianceReport`, `ComplianceCapability`, `LifecycleStatus`
- Create `ComplianceProviderRegistry: ObservableObject` (same pattern)
- LifecycleStatus: active, notRecommended, obsolete, eol, discontinued

**Acceptance:**
- Protocol + registry defined, tested with mock provider

### Task 2: SnapMagic File Import
**Requirements:** REQ-09.1–09.4

- `SnapMagicImportProvider: CADModelProvider`
- Import flow: user selects .zip or individual files from SnapMagic download
- Parse .kicad_mod, .kicad_sym files — validate against KiCad format spec
- Extract metadata from filename convention (MPN embedded in SnapMagic downloads)
- Cache imported files permanently in `~/.volta/cache/snapmagic/`
- Source attribution: provider = "snapmagic-import"
- Capabilities: [.footprints, .symbols] (3D models if included in import)

**Acceptance:**
- User imports a SnapMagic-downloaded part → appears in search results
- Invalid/corrupt files rejected with helpful error
- Imported parts merge with Digi-Key pricing data by MPN

### Task 3: Local Compliance Rules
**Requirements:** REQ-11.3

- `LocalComplianceProvider: ComplianceProvider`
- Rules engine using cached Digi-Key product status data:
  - Active → OK
  - Not Recommended for New Designs → warning
  - Obsolete / EOL → error
  - Discontinued → error
- RoHS status from cached specs (if available)
- No external API calls — purely local inference from cached data
- Capabilities: [.lifecycleStatus, .rohs]

**Acceptance:**
- EOL parts flagged with warning in search results
- Compliance data merges with component view from Phase 1
- Works fully offline (uses cached data only)

### Task 4: ~~SiliconExpert Research~~ — DROPPED 2026-07-28
**Requirements:** REQ-11.4
**Status:** Dropped from scope (Bret decision — enterprise-only access confirmed blocked for indie ISV)

- ~~Research SiliconExpert API accessibility for indie ISV~~
- ~~If accessible: prototype `SiliconExpertProvider` adapter~~
- Research docs preserved in RESEARCH/SILICONEXPERT_ACCESS_INVESTIGATION.md for the historical record
- Local compliance rules (Task 3) and the four-protocol architecture still complete without SiliconExpert

### Task 5: Compliance Warnings in UI
- Compliance badge on component search results (green/yellow/red)
- ComponentDetailView: compliance section with lifecycle status, RoHS, risk level
- BOM view: compliance summary across all components
- Export: compliance report for manufacturing handoff

**Acceptance:**
- Search results show compliance status at a glance
- BOM export includes compliance warnings
- User can filter by compliance status

---

## Acceptance Criteria

1. ✅ `ComplianceProvider` protocol + registry defined
2. ✅ SnapMagic file import works (user downloads → imports → searches)
3. ✅ Local compliance rules flag EOL/obsolete parts
4. ✅ SiliconExpert evaluated with documented recommendation
5. ✅ Compliance warnings visible in search results and BOM
6. ✅ Four-protocol plugin architecture complete: ComponentData, CADModel, Routing, Compliance
7. ✅ Adding any new provider type requires only: conform to protocol, call register()

---

## Architecture Completion

This phase completes the four-protocol plugin system:

```
ComponentDataProvider Registry   → [Digi-Key, Mouser, Octopart, JLCPCB, jlcparts]
CADModelProvider Registry        → [easyeda2kicad, Octopart, SnapMagic-import]
RoutingProvider Registry          → [Freerouting, KiCad native, cloud?]
ComplianceProvider Registry       → [Local rules, SiliconExpert?]
```

Every external service is a pluggable adapter. The core app knows only protocols and registries. Adding or removing a provider never touches core code. This is the "our shit vs their shit" architecture in its final form.
