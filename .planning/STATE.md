---
gsd_state_version: 1.0
milestone: v2.4
milestone_name: schematic-intelligence
status: executing
stopped_at: "Phase 40 complete (all 3 plans executed). Phase 40 done."
last_updated: "2026-05-31T23:46:00Z"
last_activity: 2026-05-31
progress:
  total_phases: 40
  completed_phases: 38
  total_plans: 116
  completed_plans: 111
  percent: 96
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-29)

**Core value:** LLM -> intent JSON -> AST mutation -> valid KiCad file. Zero corruption, every time.
**Current focus:** v2.4 Schematic Intelligence — Phases 38-40 (10 plans, building on existing schematic_routing module)
Last activity: 2026-06-01

## Current Position

Phase: 38-40 (Schematic Routing Engine + Net Intelligence + ERC Root Cause)
Status: **Phase 40 complete. All 3 plans executed (3 waves).**
Plans: 38-01..04, 39-01..03, 40-01..03
Last activity: 2026-06-01

### Wave Structure

**Phase 38 (4 plans):**

- Wave 1: 38-01 (pin resolution) + 38-02 (collision detection) — shared schema file, sequential
- Wave 2: 38-03 (connect_pins) — depends on 38-01, 38-02
- Wave 3: 38-04 (batch_connect + regenerate_wiring) — depends on 38-03

**Phase 39 (3 plans):**

- Wave 1: 39-01 (net extraction) + 39-02 (conflict detection) — can run parallel
- Wave 2: 39-03 (net naming) — depends on 39-01

**Phase 40 (3 plans):**

- Wave 1: 40-01 (violation classification)
- Wave 2: 40-02 (root cause diagnosis) — depends on 40-01
- Wave 3: 40-03 (enhanced erc_auto_fix) — depends on 40-02

## Previous Milestone (v2.4 production-hardening)

**Final: 37/37 phases complete. 74 operations, 1900+ tests, structured logging, training infra.**

## Performance Metrics

**Velocity:**

- Total plans completed: 109
- Average duration: 5 min
- Total execution time: 5.5 hours

**Recent Trend:**

- Last 10 plans: 38-01 through 39-03 (all first-execution pass)
- Trend: Stable -- all plans passing on first execution

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [v2.4]: File content snapshots for undo (not Operation objects -- re-execution produces different UUIDs)
- [v2.4]: collections.deque(maxlen=N) for bounded O(1) undo stack
- [v2.4]: Per-executor undo stack keyed by resolved file path
- [v2.4]: Standard undo/redo semantics (new operation clears redo stack)
- [v2.4]: Session-scoped undo (lost on MCP server restart, same as KiCad)
- [v2.4]: LLMProvider protocol is superset of LLMBackend -- providers satisfy both protocols
- [v2.4]: Provider selection via KICAD_LLM_PROVIDER env var (default "anthropic")
- [v2.4]: Lazy LLMClient imports in consumers to avoid hard anthropic dependency
- [v2.4]: ModifyNetClassOp uses Optional[float] fields for partial updates (None=keep existing)
- [v2.4]: write_project_settings operates on raw JSON dict to preserve unknown keys
- [v2.4]: List handlers are read-only (no serialize), returning {items, count}
- [v2.4]: Atomic write via tempfile+os.replace for .kicad_pro (Council FE-02)
- [v2.4]: erc_auto_fix meta-op chains parse_erc to violation dispatch with iteration control (GEN-03)
- [v2.4]: parse_erc imported at module level in erc_auto_fix.py for test mockability
- [v2.4]: validate_power_nets function defaults check_hierarchical=False for backward compat; schema defaults True
- [v2.4]: _check_hierarchical_power reuses sheet traversal pattern from check_sheet_pin_labels
- [v2.4]: modify_copper_zone resolves net via get_net_by_name or creates new net if not found
- [v2.4]: remove_copper_zone prefers UUID lookup, falls back to index, raises ValueError if neither provided
- [v2.4]: Council H-01 fix: 6 repair ops added to schema union -- was 68, now 74
- [v2.4]: Council H-02 fix: ModifyProjectSettingsOp.updates bounded to max_length=50
- [v2.4]: Council M-04 fix: ModifyCopperZoneOp.layer validated with pattern r"^[FB]\.Cu|In[1-9]\d*\.Cu$"
- [v2.4]: Council L-03 fix: RemoveCopperZoneOp has model_validator requiring at least one of zone_uuid/zone_index
- [v2.4-SI]: Plans build on existing schematic_routing/ module (SchematicGraph, wire_router, batch_executor, netlist_parser)
- [v2.4-SI]: Schemas in _schema_schematic_routing.py and _schema_schematic_intel.py (new files)
- [v2.4-SI]: Schematic ops extend existing @register_schematic pattern in executor.py
- [v2.4-SI]: PinResolver uses unit-aware lib symbol indexing via _build_unit_index() for multi-unit IC pin resolution
- [v2.4-SI]: Collision zones use >=2 pins threshold (not >=2 refs) -- vertical wire through IC pin column shorts all pins regardless of component count
- [v2.4-SI]: Pin overlap severity: error (different nets from netlist), warning (same net or unknown) -- defaults to warning without netlist
- [v2.4-SI]: Net labels placed at pin body_position (not wire endpoint) for visual clarity and guaranteed connectivity
- [v2.4-SI]: L-shaped wires use horizontal-first path; collision zone check covers full segment range
- [v2.4-SI]: BatchWiring uses kiutils from_file/to_file for element stripping (not raw S-expression manipulation)
- [v2.4-SI]: Auto-detection of collision zones inside batch_connect when none explicitly provided
- [v2.4-SI]: regenerate_wiring strips wires/labels/no_connects via kiutils, reconnects via NetConnector per-net
- [v2.4-SI]: Voltage pattern regex matches both +3.3V and +3V3 KiCad power naming conventions
- [v2.4-SI]: Power convention detection uses pin_name only, not lib_id -- SchematicGraph filters power symbols
- [v2.4-SI]: Passive components identified by lib_id containing Device:R, Device:C, Device:L
- [v2.4-SI]: Violation classification uses _CLASSIFICATION_RULES ordered list (match_fn, category, root_cause, confidence) -- first match wins
- [v2.4-SI]: ClassifyViolationsOp in _schema_erc_smart.py (separate from _schema_repair.py per D-01)
- [v2.4-SI]: IR position data (pin/wire/label positions) distinguishes #PWR symbols from regular components

### Pending Todos

- Phase 40 complete -- all 3 plans executed
- Next: Verify Phase 40 work or proceed to next milestone phase

### Blockers/Concerns

None.

## Deferred Items

None.

## Session Continuity

Stopped at: Phase 40 complete (all 3 plans executed). Phase 40 done.
Resume with: Verify Phase 40 or proceed to next milestone phase
