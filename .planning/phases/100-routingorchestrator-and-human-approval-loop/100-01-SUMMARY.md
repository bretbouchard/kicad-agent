---
phase: 100-routingorchestrator-and-human-approval-loop
plan: 01
subsystem: parser-native-types
tags: [immutability, cr-01, wr-07, phase-100, refactor, council-deferred]
requires:
  - Phase 99 Council Exec Review (CR-01 deferral)
  - Phase 76 native parser introduction
provides:
  - Frozen NativeBoard type hierarchy (14 dataclasses)
  - Immutable PcbIR.add_net/remove_net/rename_net/swap_footprint
  - Snapshot-safe board foundation for Phase 100 Plan 02 rollback
affects:
  - src/kicad_agent/parser/pcb_native_types.py
  - src/kicad_agent/parser/pcb_native_parser.py
  - src/kicad_agent/ir/pcb_ir.py
tech-stack:
  added: []
  patterns:
    - "dataclasses.replace for immutable mutation"
    - "MappingProxyType read-only dict view"
    - "construct-once parser pattern (locals then single constructor call)"
key-files:
  created:
    - tests/test_phase100_cr01_immutability.py
  modified:
    - src/kicad_agent/parser/pcb_native_types.py
    - src/kicad_agent/parser/pcb_native_parser.py
    - src/kicad_agent/ir/pcb_ir.py
    - tests/test_pcb_native_parser.py
    - tests/test_pcb_native_types.py
    - tests/test_pcb_native_adapter.py
decisions:
  - "Properties dict stored as _properties_tuple, exposed via MappingProxyType property"
  - "PcbIR.footprints/nets return list() views over tuple storage for backward compat"
  - "Parser extractors use construct-once pattern (no replace needed — board doesn't exist yet)"
metrics:
  duration: ~45 min
  completed: 2026-06-25
  tasks: 2
  files_changed: 7
  tests_added: 8
  regression_pass_count: 365
---

# Phase 100 Plan 01: CR-01 NativeBoard Immutability Refactor Summary

Frozen all 14 NativeBoard dataclasses and migrated every native-path mutation site to `dataclasses.replace()`, closing the §7.7-deferred CR-01 critical finding from Phase 99 Council Exec Review and the subsumed WR-07 in-place pad mutation bug. Phase 100 Plan 02 (RoutingOrchestrator) can now build its rollback mechanism on immutable board snapshots.

## What Changed

### NativeBoard type hierarchy (`pcb_native_types.py`)

All 14 dataclasses converted from `@dataclass` to `@dataclass(frozen=True)`:

- `NativeNet`, `NativeNetClass`, `NativePad`, `NativeFootprint`
- `NativeSegment`, `NativeVia`, `NativeGraphicItem`, `NativeZone`
- `NativeBoardOutline`, `NativeGeneral`, `NativeStackupLayer`, `NativeStackup`
- `NativeSetup`, `NativeBoard`

16 `list[...] = field(default_factory=list)` fields converted to `tuple[...] = ()` defaults. Direct attribute assignment now raises `FrozenInstanceError`; collection-typed fields cannot be appended to.

`NativeFootprint.properties` (formerly a mutable `dict`) is now exposed as a `MappingProxyType` read-only view over an internal `_properties_tuple: tuple[tuple[str, str], ...]` storage. Readers (`fp.properties.get("Reference")`) work unchanged; writers (`fp.properties["x"] = "y"`) raise `TypeError`.

`NativeBoard.__post_init__` materializes the default `NativeGeneral()` via `object.__setattr__` (the frozen-safe default pattern). The kiutils-compat properties (`graphicItems`, `traceItems`, `layers`) now return `list(...)` views over tuple storage.

### PcbIR mutation methods (`pcb_ir.py`, native-path branches only)

Four mutation methods rewritten to use `dataclasses.replace`:

- **`add_net`**: `self._native_board = replace(self._native_board, nets=(*self._native_board.nets, net))`
- **`remove_net`**: rebuilds `footprints` (each fp's `pads` rebuilt via `replace(pad, net_name="", net_number=0)` for matching pads) and `nets` (filtered tuple) via a single `replace` call on the board
- **`rename_net`**: rebuilds `nets` (name updated via `replace(n, name=new_name)`) and `footprints`/`pads` (net_name propagated) via a single `replace` call
- **`swap_footprint`**: rebuilds the swapped footprint's pads via `replace`, then rebuilds the footprint (`replace(fp, lib_id=..., pads=...)`), then rebuilds the board's footprints tuple

Each method produces a brand-new `NativeBoard` object — `id(ir._native_board)` changes after every mutation, which is exactly the snapshot semantics Plan 02's rollback requires. The kiutils fallback branches (`else:` paths) are untouched — they mutate mutable kiutils objects, which is out of scope per Council C3.

`PcbIR.footprints`, `PcbIR.nets`, and `PcbIR.trace_items` now return `list(...)` views over the tuple storage, preserving the public API for downstream consumers (adapter tests, routing code) that expect lists.

### NativeParser extractors (`pcb_native_parser.py`)

The parser previously used a create-then-set pattern (`fp = NativeFootprint(); fp.lib_id = ...; fp.pads = ...`) across every extractor. Since the dataclasses are now frozen, this pattern is impossible. Every extractor was refactored to the **construct-once pattern**: build locals first, then construct the dataclass in a single constructor call at the end of the loop iteration.

Affected extractors:

- `_build_board` — single `NativeBoard(...)` constructor call with all fields
- `_extract_footprints` — accumulates `props_pairs`, `pads`, `graphic_items` as locals; constructs `NativeFootprint` once
- `_extract_pads` — builds locals; constructs `NativePad` once
- `_extract_segments`, `_extract_vias` — same pattern
- `_extract_zones` — same pattern, including a local `keepout_lookup` dict that's folded into the constructor
- `_extract_net_classes` — same pattern
- `_extract_general`, `_extract_setup` — construct-once
- `_parse_graphic_block` — builds locals; constructs `NativeGraphicItem` once

All extractors that previously returned `list[...]` now return `tuple[...]` (frozen-friendly). `_build_board` passes these tuples directly to the `NativeBoard` constructor.

### Tests

**New file**: `tests/test_phase100_cr01_immutability.py` (8 tests):

1. `test_all_native_dataclasses_frozen` — all 14 classes have `__dataclass_params__.frozen is True`
2. `test_frozen_assignment_raises` — `FrozenInstanceError` on direct assignment to `NativePad.net_name`, `NativeNet.name`, `NativeBoard.version`, `NativeFootprint.lib_id`, `NativeZone.layer`
3. `test_list_fields_are_tuples` — 15 collection fields default to `tuple`, not `list`
4. `test_properties_is_readonly_view` — `NativeFootprint.properties` returns a view where mutation raises `TypeError`
5. `test_replace_works` — `dataclasses.replace` produces a new instance with the original unchanged
6. `test_kiutils_compat_properties_preserved` — `graphicItems`, `traceItems`, `layers` still return lists
7. `test_add_net_uses_replace` — `id(ir._native_board)` changes after `add_net` (proves new object via replace)
8. `test_remove_net_rebuilds_immutably` — `id` changes, no pad has the removed net, other nets preserved

**Updated existing tests** (contract changes from immutability migration):

- `tests/test_pcb_native_types.py`: `== []` assertions on collection fields updated to `== ()`
- `tests/test_pcb_native_parser.py`: `test_net_classes_default_empty` accepts `(list, tuple)`; `test_native_board_graphicItems_property` uses equality instead of identity (graphicItems now returns a list view); `test_graphicItems_returns_same_list`, `test_traceItems_combines_segments_and_vias`, `test_layers_returns_general_layers`, `test_empty_board_defaults` rewritten to construct immutably; `zone.layers == ["B.Cu"]` updated to `("B.Cu",)`
- `tests/test_pcb_native_adapter.py`: `test_ir_board_graphicItems_compatible` uses equality; `test_ir_board_zones_compat` accepts `(list, tuple)`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Migrated `swap_footprint` mutation site not listed in plan**
- **Found during:** Task 2
- **Issue:** The plan listed 7 mutation sites (add_net, remove_net, rename_net, _build_board, _extract_footprints properties/graphic_items, _extract_zones polygon_points). Once the dataclasses were frozen, `swap_footprint` (pcb_ir.py:354, 360, 363-364) also crashed with `FrozenInstanceError` because it mutated `fp.lib_id`, `pad.net_name`, `pad.net_number` in place. This site was missed during planning but is a real native-path mutation.
- **Fix:** Rewrote the native branch of `swap_footprint` to rebuild pads via `replace`, rebuild the footprint via `replace`, and rebuild the board's footprints tuple via `replace`. Behavior preserved: lib_id updated, pad nets preserved for matching pad numbers, others cleared.
- **Files modified:** `src/kicad_agent/ir/pcb_ir.py`
- **Commit:** 11e0de7

**2. [Rule 1 - Bug] Migrated `_extract_net_classes` and remaining parser extractors**
- **Found during:** Task 2 regression run
- **Issue:** The plan's Task 2 action focused on `_build_board`, `_extract_footprints`, and `_extract_zones`, but the parser's create-then-set pattern extended to `_extract_net_classes`, `_extract_pads`, `_extract_segments`, `_extract_vias`, `_extract_general`, `_extract_setup`, and `_parse_graphic_block`. All of these mutated freshly-constructed dataclasses and would have crashed once frozen.
- **Fix:** Refactored every extractor to the construct-once pattern (build locals, single constructor call at end). This is the same pattern the plan specified for the three listed extractors, applied uniformly.
- **Files modified:** `src/kicad_agent/parser/pcb_native_parser.py`
- **Commit:** 11e0de7

**3. [Rule 1 - Bug] Updated existing tests with stale mutable-contract assertions**
- **Found during:** Task 2 regression run
- **Issue:** Multiple existing tests asserted `isinstance(board.nets, list)`, `board.footprints == []`, `board.graphicItems is board.graphic_items`, etc. These encoded the old mutable contract and failed once collection fields became tuples and properties returned list views.
- **Fix:** Updated assertions to reflect the new immutable contract: `== ()` for empty collection fields, `(list, tuple)` for isinstance checks on raw fields, equality instead of identity for list-returning properties. No behavioral coverage was lost — the same invariants are tested, just against the correct expected types.
- **Files modified:** `tests/test_pcb_native_types.py`, `tests/test_pcb_native_parser.py`, `tests/test_pcb_native_adapter.py`
- **Commit:** 11e0de7

### Auth Gates

None.

## Verification

### Immutability suite (8/8 pass)

```
$ .venv/bin/python -m pytest tests/test_phase100_cr01_immutability.py -q
........                                                                 [100%]
8 passed
```

### Full regression suite (365/365 pass)

```
$ .venv/bin/python -m pytest tests/test_pcb_native_parser.py tests/test_pcb_native_types.py \
    tests/test_pcb_native_adapter.py tests/test_routing.py tests/test_routing_submodules.py \
    tests/test_multi_pass_router.py tests/test_routing_geometry.py tests/test_routing_gate.py \
    tests/test_routing_coverage.py tests/test_phase62_routing.py tests/test_auto_route_freerouting.py \
    tests/test_phase100_cr01_immutability.py -q
365 passed in 21.57s
```

### Grep acceptance criteria

- `grep -c "@dataclass(frozen=True)" src/kicad_agent/parser/pcb_native_types.py` → **14** (was 0)
- `grep -c "field(default_factory=list)" src/kicad_agent/parser/pcb_native_types.py` → **0** (was 16)
- `grep -c "replace(" src/kicad_agent/ir/pcb_ir.py` → **16** (>= 3 required)
- Native-path mutation patterns in `pcb_ir.py` → **0** (the two remaining `self.board.nets` matches are inside `else:` kiutils fallback branches, explicitly out of scope per Council C3)
- Parser mutation patterns (`board.X =`, `fp.X =`, `pad.X =`, `seg.X =`, `via.X =`, `zone.X =`, `gi.X =`, `nc.X =`, `.append(...)`) → **0**

### TDD Gate Compliance

- `test(100-01): add failing immutability tests for CR-01` (ae5cafb) — RED gate
- `feat(100-01): freeze 14 NativeBoard dataclasses for CR-01` (d3514e6) — GREEN gate (Task 1)
- `feat(100-01): migrate NativeBoard mutation sites to dataclasses.replace` (11e0de7) — GREEN gate (Task 2)

All three gate commits present in the correct order.

## Known Stubs

None. All mutation sites migrated to real `dataclasses.replace` implementations — no placeholder behavior.

## Threat Flags

None. The plan's `<threat_model>` covered the three relevant threats (T-100-01-01 tampering mitigated by frozen=True, T-100-01-02 properties disclosure accepted, T-100-01-03 DoS accepted). No new security-relevant surface was introduced.

## Foundation Ready for Plan 02

Phase 100 Plan 02 (RoutingOrchestrator) requires immutable board snapshots for its rollback mechanism. With CR-01 closed:

- `PcbIR.add_net` / `remove_net` / `rename_net` / `swap_footprint` all produce new `NativeBoard` objects
- The old `NativeBoard` reference remains valid and unchanged — perfect for snapshot-based rollback
- `id(ir._native_board)` changes after every mutation, making it trivially verifiable that a rollback restored the pre-route state

Plan 02 can proceed without any further immutability work.

## Self-Check: PASSED

- All 4 modified/created source files exist on disk
- SUMMARY.md exists at the expected path
- All 3 commits present in git log: `ae5cafb` (RED), `d3514e6` (Task 1 GREEN), `11e0de7` (Task 2 GREEN)
- `grep -c "@dataclass(frozen=True)" pcb_native_types.py` returns 14
- `grep -c "field(default_factory=list)" pcb_native_types.py` returns 0
- `grep -c "replace(" pcb_ir.py` returns 16 (>= 3 required)
- 365 regression tests pass
