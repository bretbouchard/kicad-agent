---
status: clean
phase: 205-board-metadata-foundation
depth: standard
files_reviewed: 10
critical: 0
warning: 0
info: 2
total: 2
reviewed: 2026-07-10T20:00:00Z
---

# Phase 205 Code Review

## Scope

10 source files reviewed (standard depth):

| File | Changes |
|------|---------|
| `src/kicad_agent/parser/pcb_native_types.py` | +NativeTitleBlock dataclass, +title_block field on NativeBoard |
| `src/kicad_agent/parser/pcb_native_parser.py` | +_extract_title_block, removed from _UNSUPPORTED_ELEMENTS, +_KNOWN_TOP_LEVEL |
| `src/kicad_agent/manufacturing/__init__.py` | New package init |
| `src/kicad_agent/manufacturing/board_spec.py` | New: BoardSpec model + enums + load/save |
| `src/kicad_agent/ops/pcb_raw_writer.py` | +set_title_block_fields block-level rebuild method |
| `src/kicad_agent/ops/_schema_pcb.py` | +3 Op classes (ReadBoardMetadata, SetBoardMetadata, SetBoardRevision) |
| `src/kicad_agent/ops/schema.py` | +3 classes in import/union/__all__ |
| `src/kicad_agent/ops/registry.py` | +3 _RAW_CATALOG entries |
| `src/kicad_agent/ops/handlers/query.py` | +read_board_metadata handler |
| `src/kicad_agent/ops/handlers/pcb.py` | +set_board_metadata, +set_board_revision handlers |

## Findings

### IR-01 [info] — Duplicated title_block parsing logic

**File:** `src/kicad_agent/ops/handlers/query.py:55-71`, `src/kicad_agent/parser/pcb_native_parser.py:1265-1294`, `src/kicad_agent/ops/pcb_raw_writer.py:992-1010`

The title_block field extraction logic (find string children, iterate numbered comments, build comments_map) is duplicated in three places: the native parser extractor, the query handler, and the raw writer's existing-value reader. Each has slightly different output types (tuple vs list) but identical parsing logic.

**Assessment:** Acceptable for Phase 205 — the three consumers have different requirements (frozen tuple for parser, mutable list for handler, list for raw writer). A shared helper would add a cross-module dependency for marginal DRY benefit. Track for potential consolidation in a future refactor phase.

### IR-02 [info] — sexpdata.loads called without depth pre-scan in query handler

**File:** `src/kicad_agent/ops/handlers/query.py:47`

The query handler calls `sexpdata.loads(ir.raw_content)` directly, without the depth pre-scan (`_pre_scan_depth`) that the native parser uses (CRITICAL-1). If `ir.raw_content` contained deeply nested malicious content, this could trigger RecursionError.

**Assessment:** Low risk — `ir.raw_content` has already been parsed by the executor's parse pipeline (which uses the native parser with depth pre-scan) before the handler is invoked. The raw_content in the IR is trusted by this point. No action needed for Phase 205.

## Summary

Code is clean. All new code follows existing patterns:
- Frozen dataclass convention (CR-01) — NativeTitleBlock matches NativeGeneral pattern
- Raw-writer + commit_raw_content mutation path — matches move_footprint handler pattern
- Pydantic model with Field constraints — matches ManufacturerProfile pattern
- atomic_write for sidecar persistence — canonical write function
- Registry/schema/union added atomically — prevents validate_registry_completeness failure

No critical or warning-level issues found.
