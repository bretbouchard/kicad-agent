---
phase: 111-convention-library
plan: 03
subsystem: conventions
tags: [conventions, cli, autolayout, integration]
requires:
  - "111-01 (Convention ABC, LayoutView, Loader, Serializers)"
  - "111-02 (v1 catalog, ConventionEngine)"
  - "Phase 48 design-rules CLI (template for check-conventions subcommand)"
provides:
  - "check-conventions CLI subcommand (markdown + JSON + --apply + --config)"
  - "Phase 108 autolayout integration: load / evaluate / suggest_adjustments"
affects:
  - "src/kicad_agent/cli/check_conventions_cmd.py (new)"
  - "src/kicad_agent/cli.py (registration + routing)"
  - "src/kicad_agent/cli/__init__.py (re-export _SUBCOMMANDS)"
  - "src/kicad_agent/conventions/autolayout_integration.py (new)"
tech-stack:
  added: []
  patterns:
    - "P0-2 real-API contract: parse_schematic + SchematicRawWriter (no fictional APIs)"
    - "P1-3 dedupe-by-rule_id for whole-layout transforms"
    - "P1-4 round-trip: Convention.apply → to_mutations → apply_mutations → atomic_write"
key-files:
  created:
    - src/kicad_agent/cli/check_conventions_cmd.py
    - src/kicad_agent/conventions/autolayout_integration.py
    - tests/test_check_conventions_cmd.py
    - tests/test_autolayout_integration.py
  modified:
    - src/kicad_agent/cli.py
    - src/kicad_agent/cli/__init__.py
decisions:
  - "check-conventions mirrors Phase 48 design-rules CLI structure"
  - "P1-3 dedupe enforced in BOTH CLI --apply and autolayout_integration"
  - "Phase 108 integration surface is the autolayout_integration module (not engine.py directly)"
  - "atomic_write + SchematicRawWriter.apply_mutations for --apply writes (P0-2, P101-INV-01)"
metrics:
  duration: ~10 minutes
  completed: 2026-07-04
---

# Phase 111 Plan 03: CLI + Autolayout Integration Summary

Wired the convention library into the CLI (`kicad-agent check-conventions`) and provided a stable Phase 108 autolayout integration surface (`load_conventions_as_constraints`, `evaluate_placement`, `suggest_placement_adjustments`). Phase 111 ships complete.

## What Was Built

### check-conventions CLI Subcommand (`cli/check_conventions_cmd.py`)
- Mirrors Phase 48 `design-rules` CLI structure
- Markdown default output, JSON via `--format json`
- `--apply` runs TRANSFORM conventions and writes the modified schematic via `SchematicRawWriter.apply_mutations` + `atomic_write`
- `--config` and bounded auto-discovery (P2-3 stops at `.git` ancestor)
- P2-2: Rejects non-`.kicad_sch` paths with exit code 2
- Exit codes: 0 (no errors), 1 (errors found), 2 (invocation error)

### Phase 108 Autolayout Integration (`conventions/autolayout_integration.py`)
- `load_conventions_as_constraints(config)` — returns enabled Convention list
- `evaluate_placement(layout, conventions)` — wraps ConventionEngine.run
- `suggest_placement_adjustments(layout, violations, conventions)` — applies TRANSFORM conventions deduped by rule_id (P1-3)
- `discover_config()` — convenience wrapper for Phase 108 startup
- Stable integration surface — Phase 108 imports from here, not from engine.py directly

## Round 1 Council Fixes Applied

| Fix | How |
|---|---|
| P0-2 (real APIs) | `parse_schematic(path)` (NOT fictional `parse_schematic_file`); `SchematicRawWriter.apply_mutations` (NOT fictional `SchematicIR.serialize`). AST-stripped source check enforces no fictional calls in executable code. |
| P1-3 (dedupe) | `suggest_placement_adjustments` AND CLI `--apply` both dedupe violations by `rule_id`. Each convention's `apply()` runs at most ONCE per call. Enforced by `test_suggest_placement_adjustments_dedupes_by_rule_id` and `test_check_conventions_apply_dedupes_by_rule_id`. |
| P1-4 (round-trip) | TRANSFORM → `LayoutView.to_mutations()` (emits `new_x`/`new_y` per P1-R2-1) → `SchematicRawWriter.apply_mutations` → `atomic_write`. Never `SchematicIR.serialize` (does not exist). |
| P2-2 (path traversal) | `Path.resolve()` + suffix check on `.kicad_sch`. Test 11 verifies exit 2 on non-matching paths. |
| P101-INV-01 (kiutils.to_file) | Never used. AST-stripped grep enforces `.to_file(` is absent. |

## End-to-End Round-Trip (P1-4 + P1-R2-1)

The complete `--apply` write path now works correctly:

1. User runs `kicad-agent check-conventions board.kicad_sch --apply`
2. CLI parses the schematic via `parse_schematic(path) → ParseResult`
3. Builds `SchematicIR(_parse_result=parse_result)` and `LayoutView.from_schematic_ir(ir)`
4. `ConventionEngine.run(layout)` produces violations
5. CLI dedupes violations by `rule_id` (P1-3) and runs each TRANSFORM convention's `apply()`
6. The resulting `LayoutView.to_mutations()` emits `{"op": "move_symbol", "ref": ..., "new_x": ..., "new_y": ...}` dicts (P1-R2-1: `new_x`/`new_y` keys, NOT legacy `x`/`y`)
7. `SchematicRawWriter.apply_mutations(raw_content, mutations)` produces modified S-expression text
8. `atomic_write(path, new_content)` persists to disk via tempfile + fsync + os.replace

**Critical P1-R2-1 fix:** SchematicRawWriter.apply_mutation reads only `new_x`/`new_y` keys (lines 420-421) and silently ignores `angle`. The original plan specified `x`/`y`/`angle` mutation keys, which would silently no-op the entire `--apply` path. Plan 01 Task 1's `LayoutView.to_mutations()` was updated to emit `new_x`/`new_y` exclusively.

## Phase 108 Integration Surface

Phase 108 (when it lands) will import:
```python
from kicad_agent.conventions.autolayout_integration import (
    load_conventions_as_constraints,
    evaluate_placement,
    suggest_placement_adjustments,
    discover_config,
)
```

The `discover_config()` helper handles `.kicad-agent/conventions.yaml` auto-discovery with the P2-3 bounded upward walk. Phase 108 calls these at startup and after each placement iteration; the integration module isolates Phase 108 from any future `engine.py` or `catalog/__init__.py` API changes.

## Self-Check: PASSED

- All 4 created/modified files exist
- Task 1 commit: `6ae52550`
- Task 2 commit: `a40edfa5`
- 22 tests passing across `tests/test_{check_conventions_cmd,autolayout_integration}.py`
- 85 tests passing across all 7 phase 111 test files (regression-free)
- `_SUBCOMMANDS` contains `check-conventions`
- `--apply` path uses `atomic_write` + `SchematicRawWriter` (grep-verified)
- No `parse_schematic_file`, `.serialize()`, or `.to_file(` calls (AST-stripped grep)
- Integration surface exports all 4 functions (verified)
- `kicad-agent check-conventions --help` prints usage successfully
