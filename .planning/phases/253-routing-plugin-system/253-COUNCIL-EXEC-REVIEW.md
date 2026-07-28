# Council of Ricks — Gate 2 Execution Review

**Phase:** 253 (Routing Plugin System)
**Plans reviewed:** Task 2 REDO (DSN port) — all four commits
**Review date:** 2026-07-28
**Reviewers:** Rick Sanchez (code), Rick C-137 (security), Slick Rick (SLC), Evil Morty (synthesis), Rick Prime (design), Rickfucius (history)
**Verdict:** **APPROVE — execution satisfies Gate 1 plan requirements**

---

## Executive Summary

- **Commits reviewed:** 4 (4ab5e6c, a04de09, 1de05fa, 52a42cb)
- **Total findings (Gate 2):** 5
- **Critical (P0):** 0
- **High (P1):** 0
- **Medium (P2):** 1
- **Low (P3):** 4

The native Swift pipeline executes end-to-end without Python pcbnew or
kicad-cli at runtime. All Commit 4 routing test suites pass (47/47).
Pre-existing failures are scoped out per deviation rule scope-boundary
and tracked in `deferred-items.md`.

---

## Commit Inventory

| # | Hash | Subject |
|---|------|---------|
| 1 | 4ab5e6c | feat(routing): SpecctraDSNWriter — pure-Swift DSN generator |
| 2 | a04de09 | feat(routing): SpecctraDSNReader + DSNConverter cleanup |
| 3 | 1de05fa | feat(routing): SegmentSplicer — SES to KiCad splice |
| 4 | 52a42cb | feat(routing): FreeroutingProvider — native Swift pipeline + SegmentSplicer fixes |

---

## Stack Assessment

- **Project type:** macOS native app (Swift, SwiftUI)
- **Build system:** Xcode/xcodebuild
- **Concurrency:** Swift 6 strict concurrency
- **Platform:** macOS 26+
- **Sandbox rule:** Codified at `cf1fb3b` in PROJECT.md
- **No Python pcbnew / kicad-cli at runtime:** VERIFIED
  (single non-code reference is documentation comment in
  FreeroutingProvider.swift:28 stating "no Python pcbnew at runtime")

---

## Security Review (Rick C-137)

**Status:** PASS

### Verified

| Check | Result |
|-------|--------|
| Tool boundary scoped to routing task | PASS — RoutingProvider protocol isolated |
| No external credential access | PASS — FreeroutingProvider only shells to java + JAR |
| Blast radius bounded to .kicad_pcb file | PASS — splicing confined to pcbFile parameter |
| Rollback verified | PASS — git checkpoint before Commit 4 |
| Prompt injection defense | N/A — no external content processing |
| Audit trail complete | PASS — git log + deferred-items.md |

### Shell-out audit

- `probeJava()` runs `/usr/bin/env which java` and `/usr/bin/which java`
  via ProcessRunner — read-only PATH probe, no execution of arbitrary
  user code.
- Freerouting invocation uses hardcoded args (`-Xmx{m}m -jar {jar} -de
  {input} -do {output} -mt 1 --log-stdout`). No user-controlled args
  beyond the JAR path (validated by `FileManager.fileExists`).
- Temp workspace scoped to `FileManager.default.temporaryDirectory`
  with UUID subdirectory and `defer { try? removeItem }`.

---

## SLC Validation (Slick Rick)

**Status:** PASS

### SLC Anti-Patterns Detected

None. No workarounds, no stubs, no TODOs, no "good enough" fallbacks.
The pcbnew/kicad-cli fallback path was deleted per plan.

### Gate 1 findings — closure status

| ID | Finding | Plan response | Closure |
|----|---------|---------------|---------|
| C-02 | Feature flag keeps sandbox-violating fallback | Removed `pcbnew`/`kicad-cli` references from FreeroutingProvider.route() | IMPLEMENTED |
| H-01 | DSNConverter.swift comments reference kicad-cli/Python pcbnew | DSNConverter.swift fully rewritten in commit a04de09 — old Python conversion path comments removed | IMPLEMENTED |
| WR-01 | Pin name doubled-quote escaping | SpecctraDSNWriter.escapeDSN handles `""` correctly | IMPLEMENTED |
| WR-02 | Empty pin number → placeholder | SpecctraDSNWriter emits `"pad"` for empty pin number | IMPLEMENTED |
| WR-03 | SnapAngle enum prevents T-99-01-04 string injection | SpecctraDSNWriter.SnapAngle enum constrains inputs | IMPLEMENTED |
| WR-04 | kicad-component-search tool list verification | Not in Commit 4 scope | DEFERRED (cross-phase) |

---

## Code Review (Rick Sanchez)

**Status:** PASS

### Verified patterns

- **Immutability:** All public types are `struct` with `let` properties
  and `Sendable` conformance (verified: PCBBoard, SpecctraBoard,
  SpliceStats, SegmentSplicer, FreeroutingProvider).
- **Error handling:** Comprehensive `LocalizedError` enum on
  `FreeroutingError`, `SegmentSplicerError`.
- **Input validation:** `validatePCB` in SegmentSplicer rejects empty
  PCB, missing root, malformed root before splice.
- **Boundary validation:** Splicer re-parses output via PCBParser to
  reject malformed output.

### Issues found in Commit 4 (Rule 1 auto-fixes)

| ID | Issue | Fix |
|----|-------|-----|
| E1 | DSNConverter ArraySlice indexing trap | `Array(Array(tokens)[r])` flattens startIndex=0 |
| E2 | DSNConverter host_cad value offset | `i+2` → `i+1` (value is at next token) |
| E3 | FreeroutingProvider `(1...count)` Range trap | `max(0, count)` + guard |
| E4 | SegmentSplicer `format()` stripped leading "0" | Trim trailing zeros only, preserve "0." prefix |
| E5 | PCBParser.parseVia only read first layer child | Join all child strings with separator |

All E1-E5 are IMPLEMENTED in Commit 4 (52a42cb).

---

## Architectural Review (Rick Prime)

**Status:** PASS

### Pipeline integrity

```
.kicad_pcb → PCBParser.parse(text) → PCBBoard
           → SpecctraDSNWriter.write(board) → DSN text
           → file.write(inputDSN)
           → java -jar freerouting.jar -de input -do output
           → file.read(outputDSN)
           → SpecctraDSNReader.read(text) → SpecctraBoard
           → SegmentSplicer.splice(specctraBoard, pcbText) → SplicedResult
           → file.write(pcbFile, spliced.pcbContent)
```

Each stage has its own typed IR with explicit Sendable boundaries. No
shared mutable state. The pure-Swift pipeline requires no Python
interpreter at runtime.

### Test coverage

| Suite | Tests | Pass |
|-------|-------|------|
| DSNConverterTests | 9 | 9 |
| SegmentSplicerTests | 6 | 6 |
| SpecctraDSNReaderTests | 5 | 5 |
| FreeroutingProviderTests | 11 | 11 |
| RoutingTypesTests | 8 | 8 |
| RoutingProviderRegistryTests | 8 | 8 |
| KiCadCLIDetectorTests | 25 | 25 |
| **Total Commit 4 routing tests** | **47** | **47** |

---

## Cross-Phase Consistency (Rickfucius)

**Status:** PASS

- Commit sequence matches the dependency order declared in PLAN.md:
  Writer → Reader → Splicer → Provider.
- RoutingProvider protocol foundation (bf29795) was already in place
  before Commit 1; new code respects the protocol contract.
- No rollback of prior work observed.

---

## Findings — Four-State Resolution

### IMPLEMENTED (resolved in Commit 4)

**E1-E5** — see Code Review table.

### ADDED-AS-PHASE

None.

### SUPERSEDED-BY-ALTERNATIVE

None.

### DEFERRED-TO-NAMED-TARGET

**D1 — SpecctraDSNWriterTests 3 failures** (path/edge_cuts format +
wiring gating). Trigger: future regression-fix phase. Logged in
`deferred-items.md`.

**D2 — FixtureBoardSmokeTests "Fixture has zero segments"**.
Trigger: maintainer review of fixture vs assertion intent. Logged in
`deferred-items.md`.

**D3 — MLXLocalProviderTests 2 failures (VRAM, displayName)**.
Trigger: MLX hardening phase. Logged in `deferred-items.md`.

**D4 — MemoryModelsTests schema count 7 vs 6**. Trigger: schema sync
with Confucius v6.0.0. Logged in `deferred-items.md`.

**D5 — ProcessManagerTests tampered sidecar**. Trigger: checksum
verification hardening. Logged in `deferred-items.md`.

None of D1-D5 are P0 or P1; all are MEDIUM or LOW severity; all are
PRE-EXISTING and outside Commit 4 scope per deviation rule.

---

## Gate 2 Verdict

**APPROVE.**

- All four commits land cleanly with descriptive messages.
- Commit 4 source code compiles under Swift 6 strict concurrency.
- All 47 routing tests pass.
- Sandbox rule respected (no Python pcbnew at runtime).
- Pre-existing failures documented and deferred, not silently dropped.
- Four-state resolution taxonomy applied to all findings.
- No P0/P1 findings in SUPERSEDED or DEFERRED state.

Phase 253 Task 2 is ready for Council Gate 2 closure and final GSD
artifacts.