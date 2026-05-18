# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-17)

**Core value:** LLM -> intent JSON -> AST mutation -> valid KiCad file. Zero corruption, every time.
**Current focus:** Phase 2 -- Operation Schema and IR Layer

## Current Position

Phase: 2 of 7 (Operation Schema and IR Layer)
Plan: 1 of 3 complete (02-01 done)
Status: In Progress -- Plan 01 complete, continuing to Plan 02
Last activity: 2026-05-18 -- Completed plan 02-01 (Pydantic operation schema with discriminated union)

Progress: [=====.........] 17%

## Performance Metrics

**Velocity:**
- Total plans completed: 3
- Average duration: 5 min
- Total execution time: 0.3 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-foundation | 3 | 16 min | 5 min |
| 02-operation-schema-and-ir-layer | 1 | 2 min | 2 min |

**Recent Trend:**
- Last 5 plans: 01-03 (4 min), 01-02 (8 min), 01-01 (4 min)
- Trend: Stable

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Frozen ParseResult dataclass per parser module for self-containment
- Raw content read before kiutils parsing to preserve PCB/footprint UUIDs
- 50MB sexpdata size limit for DoS mitigation (threat T-01-01)
- File extension validation with clear ValueError messages
- Sequential UUID re-injection instead of (parent_type, parent_index) lookup -- more robust for nested structures
- Two-pass round-trip stability test: first pass normalizes, second pass proves determinism
- UUID format validation (v4 pattern) before injection to mitigate tampering
- Used Regulator_Current.kicad_sym (240 lines) for symbol lib testing instead of large Device.kicad_sym
- Path-based FIXTURE_DIR in tests to avoid collision with globally installed paddle-sdk tests package
- Per-file temp subdirectories in regression suite to avoid name collisions
- Operation.root field with Field(discriminator="op_type") for Pydantic v2 discriminated union
- TargetFile uses BeforeValidator for early path traversal rejection before field validation
- Added PropertySpec model alongside PositionSpec for future property mutation operations

### Pending Todos

None yet.

### Blockers/Concerns

- Phase 1 requires testing against real KiCad 10 files (kiutils round-trip fidelity gaps are known)
- difftastic not installed locally yet (brew install difftastic needed before Phase 6)
- kicad-cli ERC/DRC output format needs verification against KiCad 10 (Phase 3 risk)

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| *(none)* | | | |

## Session Continuity

Last session: 2026-05-18
Stopped at: Completed 02-01 (Pydantic operation schema), continuing to 02-02
Resume file: .planning/phases/02-operation-schema-and-ir-layer/02-02-PLAN.md
