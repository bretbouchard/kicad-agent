# Task 2 REDO — DSN Writer / Reader / Splicer Port to Swift

**Phase:** 4 (Routing Plugin System)
**Status:** Planning — awaiting Council review
**Replaces:** Task 2 v1 implementation (commit `0a22012`) — that shipped parser-only and deferred DSN generation to Python pcbnew, which violates the sandbox rule
**Created:** 2026-07-28
**Depends on:** Task 1 (RoutingProvider protocol + registry — already shipped at `bf29795`)

---

## Why this exists

Per the Volta Component Integration thread (events [6]–[12]):
- Volta must work in its own macOS app sandbox — no external CLI dependencies at runtime (pcbnew, easyeda2kicad, kicad-cli).
- Task 2 v1 (`0a22012`) shipped with `FreeroutingError.dsnConversionUnavailable` telling the user to `pip install pcbnew`. That breaks the sandbox rule.
- The DSN generation algorithm already exists in the repo's git history: `src/kicad_agent/routing/dsn_generator.py`, last seen at commit `fe68b91` (888 LOC, E2E-verified on 48 footprints / 57 nets / 76 segments). Branches are gone but the commits survive — port the algorithm to Swift.

## Goal

A pure-Swift DSN round-trip pipeline for Freerouting:
1. `PCBBoard` → DSN text (`SpecctraDSNWriter`)
2. DSN text → `RoutingResult` wire/via geometry (`SpecctraDSNReader`, extended from existing `DSNConverter`)
3. DSN routes + `.kicad_pcb` → modified `.kicad_pcb` (`SegmentSplicer`)

Wired into `FreeroutingProvider` so the runtime no longer references Python pcbnew. After this lands, `FreeroutingError.dsnConversionUnavailable` becomes unreachable and gets deleted.

## Source-of-truth references

| What to port | Reference | LOC |
|---|---|---|
| DSN writer | `git show fe68b91:src/kicad_agent/routing/dsn_generator.py` | 888 |
| SES parser → KiCad S-expr | `git show 23b5539:src/kicad_agent/routing/freerouting.py` `parse_ses` + `ses_to_kicad_sexpr` + `import_ses_into_pcb` | ~200 |
| Round-trip parity test | `git show fe68b91:tests/test_phase105_c02_dsn_wiring.py` | 268 |
| Courtyard / netclass / zones | `git show df2e766:src/kicad_agent/routing/dsn_generator.py` (`_build_library_from_native`, `_emit_zones`, `_emit_per_class_padstacks`, `_emit_net_classes`) | ~280 |
| Existing Swift types | `macos-app/Sources/Volta/Parsing/PCBParser.swift` (`PCBBoard` + 7 sub-types) + `SExpression.swift` | already shipped |
| Existing protocol | `macos-app/Sources/VoltaPCBCore/Routing/RoutingProvider.swift` (from `bf29795`) | already shipped |

The Python `NativeBoard` ↔ Swift `PCBBoard` shape is 1:1 — no new parser needed.

## Deliverables

### D1: `SpecctraDSNWriter.swift`

Port of `generate_dsn` + `_emit_wiring_section` from `fe68b91`.

**API surface:**
```swift
public struct SpecctraDSNWriter: Sendable {
    public init(
        layers: [String] = ["F.Cu", "B.Cu"],
        padViaDrillUm: Int = 400,
        padViaSizeUm: Int = 800,
        wireWidthUm: Int = 250,
        clearanceUm: Int = 250,
        snapAngle: SnapAngle = .none
    )

    public func write(_ board: PCBBoard) throws -> String
}

public enum SnapAngle: String, Sendable {
    case none, fortyfiveDegree = "fortyfive_degree", ninetyDegree = "ninety_degree"
}
```

**Behavior (must match Python):**
- mm → um coordinate transform (×1000), exact
- (structure) section: layers + boundary + (control snap_angle)
- (placement) section: grouped by footprint name, (place REF X Y SIDE ROTATION)
- (library) section: (image ...) per footprint with (outline (rect ...)) and (pin ...) + via padstacks
- (network) section: (class ...) per net class + (net "NAME" (pins ...))
- (wiring) section: emitted only when board has pre-routed segments, locked wires as (type fix)
- T-99-01-04 mitigation: snap_angle enum, invalid values throw
- R-1: courtyard-accurate footprint obstacles
- R-4: stackup-based via padstacks for 4+ copper layers
- Rule 1 fix: empty pin number substitutes placeholder "pad"
- Council WR-03: pin names with whitespace/quotes get DSN doubled-quote escaping
- Bead #28: net name sanitization for '/' escape (KiCad 10)

**Files:** `macos-app/Sources/Volta/Routing/SpecctraDSNWriter.swift` (~600 LOC target)

### D2: `SpecctraDSNReader.swift`

Extension of existing `DSNConverter.swift` to capture full wire/via geometry, not just counts for `RoutingMetrics`.

**API surface:**
```swift
public struct SpecctraDSNReader: Sendable {
    public init()
    public func read(_ dsnText: String) throws -> SpecctraBoard
}

public struct SpecctraBoard: Sendable {
    public let placements: [SpecctraPlacement]
    public let images: [SpecctraImage]
    public let network: SpecctraNetwork
    public let wiring: SpecctraWiring    // from (wiring ...) — wires + vias
}

public struct SpecctraWire: Sendable {
    public let netName: String
    public let points: [(x: Int, y: Int)]   // um
    public let widthUm: Int
    public let type: WireType                 // .route, .fix, .normal
}

public struct SpecctraVia: Sendable {
    public let netName: String
    public let position: (x: Int, y: Int)
    public let padstack: String
}
```

**Behavior:**
- Parse the (wiring ...) section emitted by Freerouting
- Quoted/unquoted net name handling (the SES regex fix from `23b5539`)
- Padstack layer mapping: KiCad "*.Cu" → F.Cu/B.Cu based on component side

**Files:** `macos-app/Sources/Volta/Routing/SpecctraDSNReader.swift` (~200 LOC target)

### D3: `SegmentSplicer.swift`

Port of `import_ses_into_pcb` + `ses_to_kicad_sexpr` from `freerouting.py@23b5539`.

**API surface:**
```swift
public struct SegmentSplicer: Sendable {
    public init()
    public func splice(
        specctraBoard: SpecctraBoard,
        into pcbContent: String
    ) throws -> SplicedResult
}

public struct SplicedResult: Sendable {
    public let pcbContent: String    // modified .kicad_pcb text
    public let stats: SpliceStats
}

public struct SpliceStats: Sendable, Equatable {
    public let segmentsInserted: Int
    public let viasInserted: Int
    public let netsRouted: Int
    public let skipped: Int          // nets in DSN but not in PCB
}
```

**Behavior:**
- Match DSN nets to PCB net names (`extract_pcb_net_names` equivalent)
- Convert Specctra (wire ...) → KiCad (segment ...) with mm round-trip
- Convert Specctra (via ...) → KiCad (via ...) with proper drill + size
- Insert before the last closing paren of PCB content
- Preserve S-expression ordering invariants (PCBParser requires specific node order)
- Skip wires for nets not present in PCB (Freerouting may emit empty placeholders)

**Files:** `macos-app/Sources/Volta/Routing/SegmentSplicer.swift` (~300 LOC target)

### D4: Wire `FreeroutingProvider`

Replace pcbnew fallback with native Swift pipeline:

```swift
// Before (commit 0a22012 — violates sandbox rule):
case .dsnConversionUnavailable = "Install pcbnew bindings: pip install pcbnew"

// After:
// 1. PCBBoard = try PCBParser.parse(pcbContent)
// 2. dsnText = try SpecctraDSNWriter().write(board)
// 3. shell out to java -jar (bundled in .app/Resources/freerouting.jar — see Task 6c)
// 4. routedBoard = try SpecctraDSNReader().read(outputDSN)
// 5. (pcbContent, stats) = try SegmentSplicer().splice(specctraBoard: routedBoard, into: pcbContent)
```

Delete:
- `FreeroutingError.dsnConversionUnavailable` case
- All `pcbnew`/`Python pcbnew` references in comments and runtime
- The fallback message strings

**Files:** `macos-app/Sources/Volta/Routing/FreeroutingProvider.swift` (modify, ~50 LOC net change)

### D5: Tests

Three test files in `macos-app/Tests/VoltaTests/Routing/`:

| File | LOC target | Coverage |
|---|---|---|
| `SpecctraDSNWriterTests.swift` | ~250 | (a) emit 2-layer LED fixture → snapshot parse; (b) all (structure)/(placement)/(library)/(network) sub-sections present; (c) snap_angle validation throws; (d) (wiring) emitted when board has tracks; (e) coordinate transform mm→um exact; (f) pin name quoting; (g) empty pin number → "pad" placeholder; (h) courtyard obstacles |
| `SpecctraDSNReaderTests.swift` | ~150 | (a) hand-written DSN → SpecctraBoard; (b) wires + vias geometry captured; (c) quoted + unquoted net names; (d) round-trip from writer→reader preserves geometry within 1µm (parity) |
| `SegmentSplicerTests.swift` | ~150 | (a) splice into 0-segment fixture → PCBParser.parse succeeds; (b) nets-not-in-pcb skipped; (c) via insertion with proper drill/size; (d) splice of full Freerouting fixture (port of fe68b91 fidelity test) |

Total test LOC: ~550

## Commit strategy

Three commits, each independently shippable + revertable:

1. **`feat(routing): SpecctraDSNWriter — pure-Swift DSN generator`** — D1 + D5/writer tests
2. **`feat(routing): SpecctraDSNReader — full geometry capture`** — D2 + D5/reader tests
3. **`feat(routing): SegmentSplicer + FreeroutingProvider native pipeline`** — D3 + D4 + D5/splicer tests

Each commit:
- Compiles clean under Swift 6.2 strict concurrency
- Tests pass (`swift test` for the VoltaTests target)
- No new external dependencies
- Removes the corresponding pcbnew reference (cumulative across commits)

## Acceptance criteria

- [ ] `SpecctraDSNWriter().write(board).contains("(wiring")` iff `board.segments.count > 0`
- [ ] Round-trip parity: `(SpecctraDSNReader().read(writer.write(board)).wiring.wires.first?.points.first?.x)` matches `board.segments.first.start.x * 1000` ± 1µm
- [ ] `grep -rn "pcbnew\|pip install pcbnew\|Python pcbnew" macos-app/Sources/Volta/Routing/` returns 0 matches
- [ ] All 4 routing test files (DSNConverter + 3 new) pass on xcodebuild VoltaTests
- [ ] Existing 6 fixture assertions on `simple_2layer_led.kicad_pcb` still pass
- [ ] `FreeroutingError` enum no longer has `.dsnConversionUnavailable` case

## Risks + mitigations

| Risk | Mitigation |
|---|---|
| Python algorithm has 888 LOC, port to Swift could lose subtle behavior | Snapshot parity tests against Python output for same fixture; diff test for full board round-trip |
| `SExpression` parser may not handle all Specctra DSN syntax edge cases | Specctra DSN is more permissive than KiCad S-expr; spec specific subset, fail closed on unknown nodes |
| Coordinate round-trip drift accumulates over many wires | Single rounding point (`SpecctraDSNWriter.MMToUm` constant), verified exact in test |
| PCBParser node-ordering invariant violated by naive splice insertion | Insert before closing paren of the top-level `(kicad_pcb ...)`; never reorder existing nodes |
| Freerouting JAR not in `.app/Resources/` yet (Task 6c) | This plan wires the pipeline; Task 6c makes the JAR sandbox-resolvable. Until 6c lands, FreeroutingProvider still works in dev (hardcoded `/Users/bretbouchard/apps/freerouting/freerouting.jar`) — sandbox-clean test happens after 6c |

## Out of scope

- Stackup-based padstack details for 4+ copper layers (R-4 in `fe68b91`) — port only the 2-layer default path. R-4 lands as Task 2b follow-up if a 4-layer test fixture exists.
- Cloud routing adapter (Task 4 — already complete as research, no code)
- KiCadNativeRouterProvider stub (Task 3 — separate plan)
- Routing settings UI (Task 5 — separate plan)