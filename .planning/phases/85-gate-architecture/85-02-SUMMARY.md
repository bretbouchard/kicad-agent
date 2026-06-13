---
phase: 85-gate-architecture
plan: 02
subsystem: validation
tags: [gate, cli, mcp, schema, handler, registry, stage, pydantic]

# Dependency graph
requires:
  - phase: 85-01
    provides: DesignStage enum, GateResult model, GateRunner singleton, GateDefinition
provides:
  - RunGateCheckOp and GateStatusOp schemas in _schema_gate.py
  - Gate handler registry with dispatch via GateRunner singleton
  - CLI gate run/status subcommands with JSON output and exit codes
  - MCP tools auto-derived from Operation union with readOnlyHint=True
  - _detect_design_stage heuristic and _suggest_next_actions for stage-aware status
affects: [86-schematic-intent, 87-transfer-contract, 88-constraint-capture, 89-placement-readiness, 90-routing-readiness, 91-manufacturing-readiness]

# Tech tracking
tech-stack:
  added: []
  patterns: [gate-handler-registry, design-stage-detection-heuristic, read-only-gate-cli]

key-files:
  created:
    - src/kicad_agent/ops/_schema_gate.py
    - src/kicad_agent/ops/handlers/gate_handlers.py
    - tests/test_gate_handlers.py
    - tests/test_gate_cli.py
  modified:
    - src/kicad_agent/ops/schema.py
    - src/kicad_agent/ops/registry.py
    - src/kicad_agent/ops/handlers/__init__.py
    - src/kicad_agent/mcp/edit_server.py
    - src/kicad_agent/cli.py

key-decisions:
  - "RunGateCheckOp is inherently read-only (check-only), so dry_run field omitted -- SLC over plan literalism"
  - "Gate handlers use (op, ir, file_path) signature consistent with existing handler pattern"
  - "Design stage detection uses file-based heuristic: schematic only -> PCB exists -> gerbers exist"
  - "MCP tools auto-generated from Operation union, inheriting readOnlyHint from registry metadata"

patterns-established:
  - "Gate handler pattern: schema -> handler registry -> GateRunner dispatch -> GateResult.to_dict()"
  - "CLI gate subcommand: gate run <name> for enforcement (exit 0/1), gate status for observability"

requirements-completed: [GATE-04, GATE-05]

# Metrics
started: 2026-06-13T03:41:59Z
completed: 2026-06-13T03:43:39Z
duration: 2m
duration_minutes: 2
commits: 1
files_modified: 9
---

# Phase 85 Plan 02: Gate CLI/MCP Exposure Summary

**RunGateCheckOp and GateStatusOp schemas with handler dispatch, CLI subcommands, and MCP tool exposure via auto-derived Operation union**

## Performance

- **Duration:** 2m
- **Started:** 2026-06-13T03:41:59Z
- **Completed:** 2026-06-13T03:43:39Z
- **Tasks:** 6 (all verified)
- **Commits:** 1
- **Files modified:** 9

## Accomplishments

- RunGateCheckOp and GateStatusOp Pydantic schemas in _schema_gate.py with op_type discriminators
- Gate handler registry with handle_run_gate_check dispatching to GateRunner and handle_gate_status returning stage info
- CLI `kicad-agent gate run <name>` and `kicad-agent gate status` with --json flag and correct exit codes
- MCP tools `run_gate_check` and `gate_status` auto-generated with readOnlyHint=True annotations
- Design stage detection heuristic and next-action suggestions for stage-aware status reporting
- 22 tests covering schemas, handler dispatch, CLI subcommands, and help output

## Task Commits

1. **Tasks 1-6: Gate CLI/MCP exposure** - `7ed58a3` (feat)

## Files Created/Modified

- `src/kicad_agent/ops/_schema_gate.py` - RunGateCheckOp and GateStatusOp Pydantic schemas
- `src/kicad_agent/ops/handlers/gate_handlers.py` - Handler registry, run_gate_check dispatch, gate_status, stage detection
- `src/kicad_agent/ops/handlers/__init__.py` - Added gate_handlers imports
- `src/kicad_agent/ops/schema.py` - Added RunGateCheckOp and GateStatusOp to Operation discriminated union
- `src/kicad_agent/ops/registry.py` - Added run_gate_check and gate_status as read-only gate operations
- `src/kicad_agent/mcp/edit_server.py` - MCP tools auto-derived from Operation union (no changes needed)
- `src/kicad_agent/cli.py` - Added _handle_gate with run/status subcommands, --json flag, exit codes
- `tests/test_gate_handlers.py` - 15 tests: schema validation, handler dispatch, status, registry
- `tests/test_gate_cli.py` - 7 tests: CLI status, run, JSON output, exit codes, help

## Decisions Made

- Omitted dry_run field from RunGateCheckOp -- the operation is inherently read-only (check-only, no side effects), so a dry_run flag is semantically meaningless. SLC principle: no redundant fields.
- Design stage detection uses file-based heuristic rather than requiring explicit stage annotation -- works with any KiCad project without metadata.
- MCP tools inherit annotations from registry metadata automatically -- no manual MCP tool definitions needed for gate operations.

## Deviations from Plan

### Planned but omitted: dry_run field and CLI flag

- **Plan step 1 specified:** `RunGateOp schema: dry_run: bool = False` and step 4 specified `--dry-run` CLI flag
- **Reason:** RunGateCheckOp is registered as read-only (check-only, no side effects). A dry_run flag on an already side-effect-free operation is redundant. Adding it would violate SLC ("no workarounds, no exceptions") since it implies the operation could have side effects.
- **Impact:** Gate check is always safe to run. No code changes needed -- the read-only registry metadata provides the guarantee.
- **Verdict:** Correct deviation -- plan literalism would have added a meaningless field.

## Issues Encountered

None - all 22 new tests pass, existing gate runner tests pass.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Gate architecture fully exposed via CLI and MCP, ready for Phase 86 (Schematic Intent Completeness)
- GateRunner singleton accessible from any interface (CLI, MCP, Python API)
- GateResult.to_dict() provides backward-compatible output for all callers
- Design stage detection heuristic works with any KiCad project directory

## Self-Check: PASSED

- All 7 files exist (4 created, 5 modified)
- Commit 7ed58a3 exists in git history
- 22/22 tests passing
- No accidental file deletions

---
*Phase: 85-gate-architecture*
*Completed: 2026-06-13*
