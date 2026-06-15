---
phase: 95-implement-dual-knowledge-base-integration-cognee-ingestion-f
plan: 01
subsystem: knowledge-ingestion
tags: [cognee, jsonl, mcp, knowledge-graph]

# Dependency graph
requires: []
provides:
  - scripts/ingest_cognee.py standalone JSON MCP payload generator for Cognee ingestion
  - tests/test_cognee_ingestion.py 26 tests covering doc resolution, JSON output, exit codes
affects: [95-02, 95-03]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "JSONL MCP payload generator pattern: pure functions return JSON-serializable dicts, main() writes JSONL"
    - "Dedicated dataset name 'kicad-agent-reference' to avoid Cognee collisions"

key-files:
  created:
    - scripts/ingest_cognee.py
    - tests/test_cognee_ingestion.py
  modified: []

key-decisions:
  - "argv=None in main() defaults to empty list, not sys.argv[1:], to prevent pytest arg leakage"
  - "Used 'remember' tool name (Cognee v1.0 API) per RESEARCH.md recommendation over legacy 'add'+'cognify'"

patterns-established:
  - "Standalone ingestion script: pure functions (ingest_doc, verify_ingestion) + main() with argparse and JSONL output"

requirements-completed: [D-01]

# Metrics
started: 2026-06-15T04:38:57Z
completed: 2026-06-15T04:42:32Z
duration: 3m
duration_minutes: 3
commits: 2
files_modified: 2
---

# Phase 95 Plan 01: Cognee Ingestion Script Summary

**Standalone JSONL MCP payload generator for Cognee ingestion of 4 KiCad reference docs with remember/recall calls**

## Performance

- **Duration:** 3m
- **Started:** 2026-06-15T04:38:57Z
- **Completed:** 2026-06-15T04:42:32Z
- **Tasks:** 1 (TDD: RED + GREEN)
- **Commits:** 2 (test RED, feat GREEN)
- **Files modified:** 2

## Accomplishments
- Created `scripts/ingest_cognee.py` following `validate_op_count.py` pattern with `main()->int`, ROOT resolution, argparse
- `ingest_doc()` pure function returns `{"tool": "remember", "data": "[Source: ...]...", "dataset_name": "kicad-agent-reference"}` -- no MCP calls
- `verify_ingestion()` pure function returns recall verification query payloads for post-ingestion validation
- `main()` writes JSONL to stdout or `--output` file with per-doc status logging to stderr and exit codes 0/1/2
- 26 tests covering all behaviors: doc resolution, dataset naming, pure function outputs, JSON serialization, exit codes, payload ordering

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): Add failing tests** - `1db1f2b` (test)
2. **Task 1 (GREEN): Implement ingestion script** - `d2eaf5b` (feat)

## Files Created/Modified
- `scripts/ingest_cognee.py` - Standalone Cognee ingestion helper: reads docs/*.md, outputs JSON MCP payloads (163 lines)
- `tests/test_cognee_ingestion.py` - 26 tests for doc resolution, JSON output, exit codes, payload ordering (282 lines)

## Decisions Made
- `argv=None` in `main()` defaults to empty list `[]` rather than `sys.argv[1:]` to prevent pytest command-line arguments from leaking into argparse during test execution. The `__main__` block passes `sys.argv[1:]` explicitly.
- Used `remember` tool name (Cognee v1.0 API) per RESEARCH.md Pitfall 1 recommendation, over legacy `add`+`cognify` path referenced in CONTEXT.md D-01.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed pytest arg leakage into argparse**
- **Found during:** Task 1 GREEN phase
- **Issue:** `main(argv=None)` defaulted to `sys.argv[1:]`, causing pytest arguments (`tests/test_cognee_ingestion.py -x -q`) to leak into argparse, producing `SystemExit: 2` with "unrecognized arguments" error
- **Fix:** Changed default from `sys.argv[1:]` to empty list `[]`. The `__main__` block now passes `sys.argv[1:]` explicitly.
- **Files modified:** `scripts/ingest_cognee.py`
- **Verification:** All 26 tests pass after fix
- **Committed in:** `d2eaf5b` (part of GREEN commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Bug fix necessary for test execution. No scope creep.

## Issues Encountered
- Reference docs (kicad_agent_reference.md, pcb_editor_reference.md, gerbview_reference.md, kicad_docs.md) were not present in the worktree because the worktree branch was 45 commits behind master. Cherry-picked the doc commits (7f45c96, 9130f83, 3aeefbb) into the worktree as unstaged files so tests could resolve them. These docs are not committed as part of this plan -- they belong to a prior phase's commits that the worktree branch doesn't contain.

## User Setup Required

None - no external service configuration required. The script generates JSON payloads only; actual Cognee MCP execution is a separate manual step.

## Next Phase Readiness
- Ingestion script ready for use: run `python scripts/ingest_cognee.py` to generate JSONL, then pipe to Claude Code for Cognee ingestion
- Plan 95-02 (KnowledgeManager section injection) can proceed independently
- No blockers

---
*Phase: 95-implement-dual-knowledge-base-integration-cognee-ingestion-f*
*Completed: 2026-06-15*
