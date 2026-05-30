---
phase: 33-undo-redo-stack
plan: 02
subsystem: mcp
tags: [undo, redo, mcp, meta-tools, dispatch, lifespan]
dependency_graph:
  requires: [33-01]
  provides: [undo-redo-mcp-tools]
  affects: [edit_server, mcp-clients]
tech_stack:
  added: [UndoStack-in-lifespan, asyncio.to_thread-for-undo/redo]
  patterns: [meta-tool-with-destructive-hint]
key_files:
  created: []
  modified:
    - src/kicad_agent/mcp/edit_server.py
    - tests/test_mcp/test_edit_server.py
decisions:
  - Undo/redo use destructiveHint=True (not readOnlyHint) since they mutate files
  - target_file is optional -- None means most recently modified file
  - KICAD_UNDO_MAX_SIZE env var defaults to 50 with try/except fallback
metrics:
  duration: 3m
  completed: "2026-05-30"
  tasks_completed: 1
  files_modified: 2
  tests_added: 11
  tests_passing: 46 (edit_server) + 29 (undo_stack) = 75
---

# Phase 33 Plan 02: Undo/Redo MCP Meta-Tools Summary

Exposed undo and redo as MCP meta-tools in the edit server, wired UndoStack into server lifespan with env var configuration.

## One-liner

Undo/redo MCP meta-tools with destructiveHint, dispatch via asyncio.to_thread, UndoStack wired in server_lifespan with KICAD_UNDO_MAX_SIZE env var.

## Changes Made

### Task 1: Wire UndoStack in server_lifespan, add undo/redo meta-tools and dispatch

**src/kicad_agent/mcp/edit_server.py:**
- Imported `UndoStack` from `kicad_agent.ops.undo_stack`
- Modified `server_lifespan()` to parse `KICAD_UNDO_MAX_SIZE` env var (try/except defaulting to 50), create `UndoStack(max_size=max_undo)`, and pass to `OperationExecutor`
- Added `undo` and `redo` entries to `_META_TOOLS` with `destructiveHint=True` and optional `target_file` parameter
- Added dispatch cases for "undo" and "redo" in `dispatch_tool()` using `asyncio.to_thread(executor.undo/redo, target_file)`
- Updated `list_tools()` docstring from "4 meta-tools" to "6 meta-tools"

**tests/test_mcp/test_edit_server.py:**
- Updated `test_generates_4_meta_tools` to `test_generates_6_meta_tools` (expects 6, includes undo/redo)
- Updated `test_total_tool_count` from 61 to 63 (57 ops + 6 meta)
- Updated `test_meta_tools_are_read_only` to exclude undo/redo from read-only assertion
- Added `test_undo_redo_have_destructive_hint` in `TestToolAnnotations`
- Added `TestUndoRedoDispatch` class with 5 tests: dispatch calls executor, error cases, no target_file
- Added `TestLifespanUndoStack` class with 3 tests: default max_size, custom max_size, invalid max_size

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Functionality] test_meta_tools_are_read_only excluded undo/redo**
- **Found during:** Task 1 (GREEN phase)
- **Issue:** Existing test iterated ALL meta-tools asserting readOnlyHint=True, but undo/redo are destructive not read-only
- **Fix:** Updated test to filter out undo/redo from read-only assertion
- **Files modified:** tests/test_mcp/test_edit_server.py
- **Commit:** e80fba0

None - plan executed exactly as written aside from the above auto-fix.

## Verification Results

- MCP server tests: 46 passed (was 35, +11 new)
- UndoStack tests: 29 passed (no regression)

## Self-Check

- [x] `src/kicad_agent/mcp/edit_server.py` exists and contains undo/redo meta-tools
- [x] `tests/test_mcp/test_edit_server.py` exists with 11 new tests
- [x] Commit e80fba0 exists in git log
