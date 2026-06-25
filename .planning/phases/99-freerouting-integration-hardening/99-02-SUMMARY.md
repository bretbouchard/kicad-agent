---
phase: 99-freerouting-integration-hardening
plan: 02
subsystem: routing
tags: [freerouting, dsn, ses, via-padstacks, blind-via, buried-via, multi-layer, phase-99]
requires:
  - "Phase 76 NativeParser (NativeBoard, NativeStackup, NativeFootprint)"
  - "Phase 89 freerouting.py (export_dsn, route_with_freerouting, parse_ses)"
  - "Plan 99-01 (NativeBoard-backed DSN, per-class via padstacks H-2, snap_angle threading)"
provides:
  - "NativeStackupLayer dataclass + _extract_stackup_layers helper (R-4 stackup typing)"
  - "Stackup-based via padstack emission: THT always, blind+buried when 4+ copper layers"
  - "parse_ses extracts via padstack name + coords from (wiring (via PADSTACK X Y ...))"
  - "SesVia.from_layer/to_layer fields with padstack-name-derived defaults"
  - "ses_to_kicad_sexpr routes through bridge.ViaSegment.to_sexpr (WARN-2 canonical emitter)"
  - "_parse_wiring_section handles actual Freerouting v2.2.4 SES format (polyline_path)"
  - "Reference SES fixture captured from Freerouting v2.2.4 on Arduino_Mega (H-3)"
affects:
  - "Plan 99-03 SC-3/SC-4 (baseline measurement can now produce valid routed boards)"
  - "Freerouting v2.2.4 (FreerouteBatch.java scoring fix enables routing without NPE)"
  - "bridge.py TrackSegment/ViaSegment.to_sexpr (UUID now quoted, KiCad 10 compatible)"
tech-stack:
  added: []
  patterns:
    - "Stackup-based via padstack emission (THT always, blind/buried when 4+ copper)"
    - "SES via layer derivation from padstack name (Via[0-In1] -> F.Cu/In1.Cu)"
    - "Single canonical via emitter (ViaSegment.to_sexpr replaces parallel f-string builder)"
    - "(wiring ...) section parsing for Freerouting v2.2.4 SES format"
    - "Quoted UUID emission matching KiCad 10 fixture format (M-4 smoke test verified)"
key-files:
  created:
    - tests/test_phase99_dsn_r4_viatypes.py
    - tests/test_phase99_ses_r6_multilayer.py
    - tests/test_phase99_r6_roundtrip.py
    - tests/test_phase99_r3_keepout_compliance.py
    - tests/fixtures/Arduino_Mega/reference_freerouting_output.ses
  modified:
    - src/kicad_agent/parser/pcb_native_types.py
    - src/kicad_agent/parser/pcb_native_parser.py
    - src/kicad_agent/routing/dsn_generator.py
    - src/kicad_agent/routing/freerouting.py
    - src/kicad_agent/routing/bridge.py
    - src/kicad_agent/routing/FreerouteBatch.java
    - src/kicad_agent/routing/FreerouteBatch.class
    - tests/test_routing.py
decisions:
  - "Via[0-1] special-cased to F.Cu/B.Cu (canonical THT padstack, not numeric span)"
  - "SES via format discovered to be (via PADSTACK X Y ...) NOT (via LAYER1 LAYER2 ...) — research A4 assumption corrected by reference SES capture (H-3)"
  - "polyline_path is the actual Freerouting v2.2.4 wire format, not path — parser extended to handle both"
  - "parse_ses rewritten to scan (wiring ...) section first; net-nested scan kept as legacy fallback"
  - "All 6 RouterScoringSettings fields initialized upfront (not whack-a-mole per NPE)"
  - "UUID quoting fixed in bridge.py (M-4 smoke test: kicad-cli pcb drc exit 0 confirms acceptance)"
  - "Microvia padstacks deferred (H-1): rare in hobby boards, Freerouting support unverified, no fixture"
metrics:
  duration: "35 min"
  completed: "2026-06-25"
  tasks: 2
  files_created: 5
  files_modified: 8
  tests_added: 18
---

# Phase 99 Plan 02: Via Types + SES Multi-layer Bridge (R-4, R-6) Summary

Closed the remaining DSN-side gap (R-4: per-stackup via padstacks) and the SES-side gap (R-6: multi-layer via parse + canonical bridge emission). Extended `NativeStackup` with typed `NativeStackupLayer` objects, added stackup-aware via padstack emission (THT always, blind+buried when 4+ copper layers), rewrote `parse_ses` to handle the actual Freerouting v2.2.4 `(wiring ...)` section format, and routed `ses_to_kicad_sexpr` through the canonical `ViaSegment.to_sexpr` (WARN-2). Three Rule 1 bug fixes discovered during reference SES capture (Step B.5): empty pad number parse error, FreerouteBatch scoring NPE, and unquoted UUID incompatibility with KiCad 10.

## What Shipped

### R-4: Per-Stackup Via Padstacks (Task 1)

**NativeStackupLayer type** (`pcb_native_types.py`): minimal dataclass with `name`, `type`, `thickness`. `NativeStackup.layers` is now `list[NativeStackupLayer]` (typed); the mutable default is preserved for backward compat with Phase 76 consumers.

**Stackup extraction** (`pcb_native_parser.py:_extract_stackup_layers`): iterates `(layer "NAME" (type "copper"|"core"|"prepreg") (thickness N) ...)` entries, emits typed `NativeStackupLayer` objects. Pattern follows `_extract_zones` (`_find_symbol` + `_find_first_value` + typed append).

**Padstack emission** (`dsn_generator.py:_emit_via_padstacks`): replaces the single hardcoded `Via[0-1]` padstack with a helper that emits:
- THT `Via[0-1]`: always, shapes on all copper layers
- Blind `Via[0-In1]`: when stackup has >=4 copper layers, shapes on F.Cu + first inner
- Buried `Via[In1-In2]`: when stackup has >=4 copper layers, shapes on first two inner layers

`_copper_signal_layers` filters stackup to `type == "copper"` AND name ends in `.Cu` (excludes mask/silk layers that some stackups annotate with type "copper"). Falls back to `["F.Cu", "B.Cu"]` for boards without explicit stackup metadata.

**DSN layer declaration extension** (Rule 2): when the caller uses default layers but the board has a richer stackup, `generate_dsn` extends the DSN `(layer ...)` declarations with inner copper layers so padstack shapes on `In1.Cu`/`In2.Cu` reference declared layers. Without this, Freerouting would reject blind/buried padstacks whose shapes land on undeclared layers.

### R-6: SES Multi-layer Via Parse + Bridge (Task 2)

**SesVia extension** (`freerouting.py`): added `from_layer`/`to_layer` fields with defaults `"F.Cu"`/`"B.Cu"` for backward compat with legacy SES fixtures.

**parse_ses rewrite** (`freerouting.py`): the actual Freerouting v2.2.4 SES format places wires and vias in a top-level `(wiring ...)` section, NOT nested inside `(net ...)` blocks as the plan/research assumed. Three new helpers:
- `_parse_wiring_section`: extracts the `(wiring ...)` block and dispatches to wire/via parsers
- `_parse_wire_block`: handles both `(polyline_path LAYER WIDTH coords...)` (actual v2.2.4 format) and `(path LAYER WIDTH coords...)` (legacy/future)
- `_parse_via_block`: handles `(via "PADSTACK" X Y ...)` (actual v2.2.4 format) and explicit-layer form `(via F.Cu In1.Cu X Y SIZE DRILL)`

The legacy net-nested scan is preserved as a fallback (only runs when the wiring section yields nothing).

**Via layer derivation** (`_layers_from_padstack_name`): decodes padstack names:
- `Via[0-1]` -> F.Cu/B.Cu (canonical THT padstack, special-cased)
- `Via[0-In1]` -> F.Cu/In1.Cu (blind)
- `Via[In1-In2]` -> In1.Cu/In2.Cu (buried)

**ses_to_kicad_sexpr refactor** (WARN-2): DELETED the parallel f-string via builder that hardcoded `(layers "F.Cu" "B.Cu")`. Now constructs a `ViaSegment` and calls `.to_sexpr(uuid_tag=u)` — single canonical emitter, single source of truth for via S-expr format.

### Rule 1 Bug Fixes (Discovered During Reference SES Capture)

**Empty pad number parse error** (`dsn_generator.py`): MountingHole pads have empty `pad.number`, producing `(pin TH_3200:3200_um  0 0)` with collapsed whitespace. Freerouting's Specctra parser expects exactly 4 tokens after `pin` and misparsed the next image declaration. Fix: substitute `"pad"` placeholder when `pad.number` is empty.

**FreerouteBatch scoring NPE** (`FreerouteBatch.java`): Freerouting v2.2.4's `RouterScoringSettings` default constructor leaves `clearanceViolationPenalty` and `bendPenalty` null, causing `NullPointerException` in `BoardStatistics.calculateScore`. Fix: initialize all 6 scoring fields upfront (`startRipupCosts`, `viaCosts`, `planeViaCosts`, `unroutedNetPenalty`, `clearanceViolationPenalty`, `bendPenalty`).

**Unquoted UUID incompatibility** (`bridge.py`): `TrackSegment.to_sexpr` and `ViaSegment.to_sexpr` emitted `(uuid X)` unquoted, but KiCad 10 requires `(uuid "X")` quoted (verified in real fixtures: `(uuid "00000000-0000-0000-0000-0000551afce5")`). M-4 smoke test confirmed `kicad-cli pcb drc` accepts the quoted form (exit 0, parsed successfully) — the unquoted form would have been rejected.

## Reference SES Inspection (H-3 Fix)

Captured `tests/fixtures/Arduino_Mega/reference_freerouting_output.ses` from Freerouting v2.2.4 (30KB, 1198 lines). Key findings (corrected the plan/research assumptions):

1. **Via format**: `(via "Via[0-1]" X Y (net NAME N) (clearance_class default))` — NO explicit layer tokens, NO size/drill in the via line (those come from the padstack definition). The plan assumed `(via LAYER1 LAYER2 X Y SIZE DRILL)`. Research A4 was theoretical; actual format verified.

2. **Wire format**: `(wire (polyline_path LAYER WIDTH coords...) (net NAME N) ...)` — uses `polyline_path`, NOT `path`. The parser now handles both.

3. **Section structure**: wires and vias live in a top-level `(wiring ...)` section, NOT nested inside `(net ...)` blocks. The `(network ...)` section only contains net declarations (pin lists).

4. **Y-orientation**: `(via ...)` and `(polyline_path ...)` coordinates use the SAME Y-orientation (both Y-negated from SES math-up to KiCad Y-down). The existing `y = -float(y) / resolution` rule at freerouting.py:445 applies uniformly.

5. **Coordinates**: floating-point values (e.g., `117519.3`), not integers. Parser regex updated to handle floats.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Empty pad number broke Freerouting parse**
- **Found during:** Task 2 Step B.5 (reference SES capture failed with parse error)
- **Issue:** MountingHole pads have empty `pad.number`, collapsing `(pin PADSTACK NAME X Y)` to 3 tokens
- **Fix:** Substitute `"pad"` placeholder when `pad.number` is empty
- **Files modified:** src/kicad_agent/routing/dsn_generator.py
- **Commit:** 88177e2

**2. [Rule 1 - Bug] FreerouteBatch scoring NPE on null fields**
- **Found during:** Task 2 Step B.5 (Freerouting crashed during routing)
- **Issue:** RouterScoringSettings default constructor leaves clearanceViolationPenalty + bendPenalty null
- **Fix:** Initialize all 6 scoring fields upfront
- **Files modified:** src/kicad_agent/routing/FreerouteBatch.java, FreerouteBatch.class
- **Commit:** 88177e2

**3. [Rule 1 - Bug] Unquoted UUID incompatible with KiCad 10**
- **Found during:** Task 2 Step C (M-4 smoke test)
- **Issue:** bridge.py emitted `(uuid X)` unquoted; KiCad 10 requires `(uuid "X")`
- **Fix:** Quote UUID in both TrackSegment.to_sexpr and ViaSegment.to_sexpr
- **Files modified:** src/kicad_agent/routing/bridge.py, tests/test_routing.py
- **Commit:** 88177e2

**4. [Rule 2 - Critical] DSN layer declarations missing for multi-layer padstacks**
- **Found during:** Task 1 GREEN (4-layer blind/buried padstacks referenced undeclared In1.Cu/In2.Cu)
- **Issue:** `generate_dsn` defaulted to `layers=["F.Cu", "B.Cu"]` even for 4-layer boards, so blind/buried padstack shapes landed on undeclared layers
- **Fix:** Extend default layers list with inner copper layers from stackup
- **Files modified:** src/kicad_agent/routing/dsn_generator.py
- **Commit:** 1e22d20

### Deferred Items (H-1 Fix)

**R-4 microvia padstack emission deferred**

The plan lists microvia as the third R-4 via type. Deferred because:
1. Microvias are rare in hobby boards (CONTEXT.md target audience)
2. Freerouting v2.2.4 microvia support is uncertain and unverified
3. No fixture exercises microvias

Resolution: add `Via[0-In1-Micro]` padstack with single-layer pair and smaller drill, smoke test Freerouting v2.2.4 acceptance, add `test_microvia_padstack` to `test_phase99_dsn_r4_viatypes.py`. This deferral is enforced by `test_microvia_deferral_documented` (asserts the word "microvia" appears in this SUMMARY — bureaucracy §7.7 no silent scope reduction).

Bead tracking note: Beads MCP tools are not available in this executor's restricted tool set. This SUMMARY documents the deferral per bureaucracy §10. The orchestrator or a subsequent session should create the Bead with `labels: "deferred,feature,phase-99,r-4-microvia"`, `priority: "3"`.

## Threat Flags

None beyond the plan's `<threat_model>`. T-99-02-01 (defensive token classification in parse_ses) implemented — layer tokens must contain "." and not be purely numeric; numeric tokens parsed via try/except; malformed via entries skipped via `continue` not crash. T-99-02-06 (WARN-2 canonical emitter) implemented — parallel f-string builder deleted, single ViaSegment.to_sexpr source of truth.

## Known Stubs

None. All code paths produce real data from NativeBoard (R-4) or actual SES parse output (R-6). The `size_mm`/`drill_mm` defaults of 0.8/0.4 in `_parse_via_block` are fallbacks for the actual Freerouting v2.2.4 format which omits size/drill from via instances (those values come from the padstack definition in the library section) — this is correct behavior, not a stub.

## TDD Gate Compliance

Both tasks followed RED/GREEN cycle with commits:
- **Task 1 (R-4):** `test(99-02): add failing tests...` (ea6ba24, RED) -> `feat(99-02): per-stackup via padstacks (R-4)` (1e22d20, GREEN)
- **Task 2 (R-6):** `test(99-02): add failing tests for R-6 SES via layers...` (1924ef1, RED) -> `fix(99-02): extract via layers from SES, route through ViaSegment.to_sexpr (R-6, WARN-2)` (88177e2, GREEN)

No REFACTOR commits needed — code was clean after GREEN.

## Test Results

- **New Phase 99 tests:** 18 tests across 4 files, all passing (2 skipped intentionally: microvia SUMMARY check + R-3 Category 3 keepout)
- **Regression (routing/bridge/smd/native/IR/adapter):** 346 tests, all passing
- **M-4 smoke test:** kicad-cli pcb drc on minimal PCB with quoted UUID via -> exit 0, parsed successfully
- **Reference SES:** captured from Freerouting v2.2.4 on Arduino_Mega, 8 wires + 3 vias extracted correctly

## Self-Check: PASSED

Verified post-commit:
- All 5 created test files + reference SES fixture exist at expected absolute paths
- All 4 task commits present in git log (ea6ba24, 1e22d20, 1924ef1, 88177e2)
- `from_layer` appears 8 times in freerouting.py (>=3 required)
- `ViaSegment` appears 3 times in freerouting.py (>=1 required, in ses_to_kicad_sexpr context)
- `NativeStackupLayer` dataclass exists in pcb_native_types.py
- `_extract_stackup_layers` helper exists in pcb_native_parser.py
- Real Freerouting roundtrip on Arduino_Mega produces valid SES (RC 0, 8 wires, 3 vias)
