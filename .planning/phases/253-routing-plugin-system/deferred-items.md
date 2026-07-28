# Phase 253 Task 2 — Deferred Items

Items NOT addressed by Commit 4 work, per deviation rule scope-boundary:
"Only auto-fix issues DIRECTLY caused by the current task's changes.
Pre-existing warnings, linting errors, or failures in unrelated files
are out of scope."

---

## IMPLEMENTED (resolved during Commit 4)

### MockProcessRunner redeclaration between KiCadCLIDetectorTests and FreeroutingProviderTests

- **Status:** IMPLEMENTED (no longer blocking)
- **Original issue:** Both test files declared `MockProcessRunner` causing
  "invalid redeclaration" compile error in the VoltaTests target.
- **Resolution:** KiCadCLIDetectorTests keeps its `MockProcessRunner`.
  FreeroutingProviderTests uses `FreeroutingProcessRunner` (renamed from
  prior `MockProcessRunner` per source commit 52a42cb message).
- **Verified by:** 25/25 KiCadCLIDetectorTests pass, 11/11
  FreeroutingProviderTests pass, full VoltaTests target compiles.

---

## DEFERRED (out of scope for Commit 4)

### SpecctraDSNWriterTests — 3 pre-existing failures (commit 4ab5e6c)

| Test | Pattern expected | Pattern actually emitted |
|------|------------------|--------------------------|
| `Boundary falls back to footprint AABB + 5mm margin when no Edge.Cuts` | `"45000 45000 55000 55000"` (single space) | `(path pcb 0  45000 45000  55000 45000  55000 55000  45000 55000  45000 45000)` (double space between pairs) |
| `Boundary uses Edge.Cuts when present` | `"10000 20000 110000 120000"` | Same double-space issue |
| `(wiring ...) vias carry (type fix) and via padstack name` | `(via Via[0-1] 105000 100000 (net "NET_A") (type fix))` | Not emitted — wiring block is gated on `!board.segments.isEmpty` but test board has only vias |

- **Cause:** SpecctraDSNWriter was committed in 4ab5e6c with claimed
  "20 unit tests pass" but the gating logic and path formatting don't
  match these test assertions.
- **Scope boundary:** Commit 4 does not modify SpecctraDSNWriter.swift.
  Fixing these requires touching the writer AND the tests, neither of
  which is in Commit 4's task scope.
- **Trigger for resolution:** Separate phase / commit dedicated to
  SpecctraDSNWriter regression fixes. Owner: whoever picks up DSN
  writer hardening.

### FixtureBoardSmokeTests — "Fixture has zero segments"

- **Cause:** Test asserts the `simple_2layer_led.kicad_pcb` fixture has
  zero segments so Freerouting has something to route. Actual fixture
  has 1 segment (grep count verified).
- **Scope boundary:** Commit 4 modified `FixtureBoardSmokeTests.swift`
  only to remove a pre-existing `Bundle.module` block that blocked
  test target compile. Did not address fixture content vs assertion.
- **Trigger for resolution:** Maintainer reviews fixture vs assertion
  intent — either change fixture or change assertion.

### MLXLocalProviderTests — 2 failures

- `minimumVRAMBytes is exactly 3GB per Pitfall 7` — expected 3 GiB,
  actual 7 GB.
- `displayName includes model id` — expected `"MLX: mlx-community/gemma3"`,
  actual `"Volta PCB v2 (Local, MLX)"`.
- **Scope boundary:** Unrelated to routing. Pre-existing failures in
  MLX module.

### MemoryModelsTests — "Schema registry lists 6 models in v6.0.0 schema"

- Expected 6 models, actual 7.
- **Scope boundary:** Unrelated to routing. Pre-existing.

### ProcessManagerTests — "Checksum verification rejects tampered sidecar"

- **Scope boundary:** Unrelated to routing. Pre-existing.

---

## Pre-existing test summary

| Suite | Pass | Fail | Scope |
|-------|------|------|-------|
| DSNConverterTests | 9 | 0 | Commit 4 (fixed) |
| SegmentSplicerTests | 6 | 0 | Commit 4 (fixed) |
| SpecctraDSNReaderTests | 5 | 0 | Commit 4 (verified) |
| FreeroutingProviderTests | 11 | 0 | Commit 4 (fixed) |
| RoutingTypesTests | 8 | 0 | Commit 4 (verified) |
| RoutingProviderRegistryTests | 8 | 0 | Commit 4 (verified) |
| KiCadCLIDetectorTests | 25 | 0 | Commit 4 (verified) |
| SpecctraDSNWriterTests | 22 | 3 | Pre-existing, deferred |
| FixtureBoardSmokeTests | n/a | 1 | Pre-existing, deferred |
| MLXLocalProviderTests | n/a | 2 | Pre-existing, deferred |
| MemoryModelsTests | n/a | 1 | Pre-existing, deferred |
| ProcessManagerTests | n/a | 1 | Pre-existing, deferred |

Total Commit 4 routing tests: 47/47 pass.
Total pre-existing failures in test suite: 8 (deferred).