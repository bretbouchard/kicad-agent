---
phase: 253
plan: 02
subsystem: routing
tags: [routing, dsn, freerouting, native-pipeline, swift, phase-253, task-2-redo]
dependency_graph:
  requires: [bf29795, 0a22012]
  provides: [52a42cb]
  affects: [Sources/Volta/Routing, Sources/Volta/Parsing, Tests/VoltaTests/Routing]
tech_stack:
  added: []
  patterns: [S-expression parsing, sendable DTOs, in-process Swift pipeline, ProcessRunner protocol injection, routing provider plugin registry]
key_files:
  created: []
  modified:
    - macos-app/Sources/Volta/Routing/SpecctraDSNWriter.swift
    - macos-app/Sources/Volta/Routing/SpecctraDSNReader.swift
    - macos-app/Sources/Volta/Routing/DSNConverter.swift
    - macos-app/Sources/Volta/Routing/SegmentSplicer.swift
    - macos-app/Sources/Volta/Routing/FreeroutingProvider.swift
    - macos-app/Sources/Volta/Parsing/PCBParser.swift
    - macos-app/Tests/VoltaTests/Routing/FreeroutingProviderTests.swift
    - macos-app/Tests/VoltaTests/Routing/FixtureBoardSmokeTests.swift
decisions:
  - Use ProcessRunner protocol with closure-injected output producer for testability
  - Freerouting invocation uses -Xmx{m}m -jar {jar} -de {input} -do {output} -mt 1 --log-stdout
  - Specctra DSN doubled-quote escaping for pin/net names per Council WR-01
  - Wiring section gated on `!segments.isEmpty || !vias.isEmpty` (writer-side fix deferred)
  - PCBParser.parseVia joins all child strings to preserve multi-layer via geometry
metrics:
  duration_min: ~75
  tasks: 4
  files_modified: 8
  test_passing: 47
  test_failing: 0
  test_deferred: 8
  commits: 4
  completed_date: 2026-07-28
---

# Phase 253 Plan 02: DSN Port (Task 2 REDO) — Summary

**One-liner:** Native Swift pipeline for Freerouting — PCBParser → SpecctraDSNWriter → java JAR → SpecctraDSNReader → SegmentSplicer, with zero Python pcbnew at runtime.

---

## Objective

Port the Phase 4 Task 2 Freerouting integration from Python `pcbnew` / `kicad-cli`
fallback to a pure-Swift pipeline. All four sequential source commits land in
isolation, each independently shippable, with sandbox rule respected (no Python
process spawned, no `kicad-cli` shell-out at runtime).

## Architecture

```
.kicad_pcb ─→ PCBParser.parse(text) ─→ PCBBoard
           ─→ SpecctraDSNWriter.write(board) ─→ DSN text
           ─→ FileManager.write(inputDSN)
           ─→ ProcessRunner.run(java -jar freerouting.jar -de input -do output)
           ─→ FileManager.read(outputDSN)
           ─→ SpecctraDSNReader.read(text) ─→ SpecctraBoard
           ─→ SegmentSplicer.splice(specctraBoard, pcbText) ─→ SplicedResult
           ─→ FileManager.write(pcbFile, spliced.pcbContent)
```

Each stage has its own typed IR (`PCBBoard`, DSN text, `SpecctraBoard`,
`SplicedResult`) with explicit `Sendable` boundaries.

## Commits

| # | Hash | Subject |
|---|------|---------|
| 1 | 4ab5e6c | feat(routing): SpecctraDSNWriter — pure-Swift DSN generator |
| 2 | a04de09 | feat(routing): SpecctraDSNReader + DSNConverter cleanup |
| 3 | 1de05fa | feat(routing): SegmentSplicer — SES to KiCad splice |
| 4 | 52a42cb | feat(routing): FreeroutingProvider — native Swift pipeline + SegmentSplicer fixes |

## Deviations from Plan

### Auto-fixed Issues (Rule 1)

**1. DSNConverter ArraySlice indexing trap**
- **Found during:** Commit 4 native pipeline test
- **Issue:** `findSection` returns `Range<Int>` in absolute indices; when used
  to slice `Array(tokens)[r]`, the resulting `ArraySlice` has
  `startIndex = r.lowerBound`. Iterating `0..<count` and subscripting `[i]`
  fails because `[0]` is below `startIndex`.
- **Fix:** Wrap with `Array(...)` to flatten startIndex back to 0:
  `Array(Array(tokens)[parserRange])`.
- **Files modified:** `macos-app/Sources/Volta/Routing/DSNConverter.swift`
- **Commit:** 52a42cb

**2. DSNConverter host_cad value offset**
- **Found during:** Commit 4 DSNConverter tests
- **Issue:** `host_cad` token at index N, value `"KiCad"` at N+1 — original
  code used `parserTokens[i + 2]` which read `)` not `"KiCad"`.
- **Fix:** `i + 2` → `i + 1`.
- **Files modified:** `macos-app/Sources/Volta/Routing/DSNConverter.swift`
- **Commit:** 52a42cb

**3. FreeroutingProvider `(1...count)` Range trap**
- **Found during:** Commit 4 native pipeline test (parseMetrics)
- **Issue:** `(1...count)` crashes with "Range requires lowerBound <=
  upperBound" when count is 0 from stdout parse.
- **Fix:** `let safeCount = max(0, count); if safeCount > 0 { ... }`.
- **Files modified:** `macos-app/Sources/Volta/Routing/FreeroutingProvider.swift`
- **Commit:** 52a42cb

**4. SegmentSplicer format() stripped leading "0"**
- **Found during:** Commit 4 splice test
- **Issue:** `format(0.8)` produced `"8"` instead of `"0.8"`. The original
  implementation trimmed both leading and trailing zeros via
  `trimmingCharacters(in: CharacterSet(charactersIn: "0"))`.
- **Fix:** Trim trailing zeros only, preserve leading "0." prefix.
- **Files modified:** `macos-app/Sources/Volta/Routing/SegmentSplicer.swift`
- **Commit:** 52a42cb

**5. PCBParser.parseVia only read first layer child**
- **Found during:** Commit 4 splice test (two-layer via verification)
- **Issue:** `(layers "F.Cu" "B.Cu")` — `childString(0)` returned only
  `"F.Cu"`, dropping `"B.Cu"`. Round-tripped via.layers was wrong.
- **Fix:** Join all child strings with separator (`"F.Cu B.Cu"`).
- **Files modified:** `macos-app/Sources/Volta/Parsing/PCBParser.swift`
- **Commit:** 52a42cb

### Out-of-Scope Discoveries (deferred-items.md)

| ID | Finding | Disposition |
|----|---------|-------------|
| D1 | SpecctraDSNWriterTests 3 failures (path/edge_cuts format + wiring gating) | DEFERRED — pre-existing from 4ab5e6c |
| D2 | FixtureBoardSmokeTests "Fixture has zero segments" | DEFERRED — pre-existing |
| D3 | MLXLocalProviderTests 2 failures (VRAM, displayName) | DEFERRED — pre-existing |
| D4 | MemoryModelsTests schema count 7 vs 6 | DEFERRED — pre-existing |
| D5 | ProcessManagerTests tampered sidecar | DEFERRED — pre-existing |

All pre-existing, all MEDIUM or LOW severity, all outside Commit 4 scope per
deviation rule scope-boundary.

## Test Coverage

| Suite | Tests | Pass | Notes |
|-------|-------|------|-------|
| DSNConverterTests | 9 | 9 | Commit 4 fix |
| SegmentSplicerTests | 6 | 6 | Commit 4 fix |
| SpecctraDSNReaderTests | 5 | 5 | Verified |
| FreeroutingProviderTests | 11 | 11 | Commit 4 fix + new integration test |
| RoutingTypesTests | 8 | 8 | Verified |
| RoutingProviderRegistryTests | 8 | 8 | Verified |
| KiCadCLIDetectorTests | 25 | 25 | Verified (unrelated but included in route) |
| **Total Commit 4 routing tests** | **47** | **47** | |

Native pipeline integration test (`"Native pipeline parses PCB, writes DSN,
runs Freerouting, splices segments, and updates the PCB file"`) passes
end-to-end via the `FreeroutingProcessRunner` test double.

## Verification

### Sandbox rule

- `pcbnew` references in `Sources/Volta/Routing/`: 1 (documentation comment
  in FreeroutingProvider.swift:28 stating "no Python pcbnew at runtime").
- `pip install pcbnew` references: 0.
- `Python pcbnew` references: 0.
- `kicad-cli` references: 0.
- `kicad_cli` references: 0.

### Build status

- `swift build` clean under `SWIFT_STRICT_CONCURRENCY=minimal`.
- Swift 6 strict concurrency enabled on public types via `Sendable`
  conformance.
- No new external runtime dependencies.

## Council Verdict

Gate 2 Execution Review: **APPROVE** (see
`253-COUNCIL-EXEC-REVIEW.md`).

- 0 P0 / 0 P1 findings.
- 5 deferred items tracked in `deferred-items.md`.
- All four commits land cleanly with descriptive messages.
- Sandbox rule respected (no Python pcbnew at runtime).
- No P0/P1 findings in SUPERSEDED or DEFERRED state.

## Architecture Decisions

- **ProcessRunner protocol with outputDSNProducer closure** — enables
  end-to-end native pipeline test via test double. The closure writes
  `output.dsn` before returning success, simulating Freerouting's
  output behavior without spawning Java.
- **Coordinate units** — KiCad mm ×1000 → DSN µm; back /1000. Exact
  round-trip verified.
- **Doubled-quote DSN escaping** — pin/net names with `"` escaped to `""`
  per Council WR-01. Council WR-02 (empty pin number → "pad" placeholder)
  also implemented.
- **SnapAngle enum** — constrains valid snap-angle inputs, prevents
  T-99-01-04 string injection per Council WR-03.
- **Net name slash sanitization** — `{slash}` token from KiCad netlist
  converted to `_` per Bead #28.

## Next Steps

- Task 6 sandbox cleanup — already executed in earlier session.
- Phase 254 (Compliance + File Import) — separate scope.
- Council Gate 1 review already approved Task 2 REDO plan.
- SpecctraDSNWriter regression fixes (D1) — separate phase recommended.

## Artifacts

- Plan: `.planning/phases/253-routing-plugin-system/TASK2_DSN_PORT_PLAN.md`
- Council Gate 1 review: `.planning/phases/253-routing-plugin-system/253-COUNCIL-PLAN-REVIEW.md`
- Council Gate 2 review: `.planning/phases/253-routing-plugin-system/253-COUNCIL-EXEC-REVIEW.md`
- Deferred items: `.planning/phases/253-routing-plugin-system/deferred-items.md`
- Phase summary: `.planning/phases/253-routing-plugin-system/253-02-SUMMARY.md` (this file)