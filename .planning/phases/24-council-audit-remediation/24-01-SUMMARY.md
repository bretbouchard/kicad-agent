---
phase: 24-council-audit-remediation
plan: 01
status: complete
started: "2026-05-29T00:00:00Z"
completed: "2026-05-29T00:15:00Z"
---

# Plan 24-01: Security Hardening

## Objective
Harden kicad-agent against all 7 security findings from the Council audit (C-1, C-4, H-3, H-4, H-5, L-1, L-2).

## What Was Built

### Task 1: Path confinement, S-expression escaping, MCP error sanitization
- **C-1**: Path traversal confinement via `resolve().is_relative_to()` in `executor.execute()` and `_execute_create()`. CLI `_handle_route` now passes relative paths.
- **C-4**: All three `_inject_*` functions in `pcb_ir.py` escape values via `_escape_sexpr_value` before interpolation.
- **H-3**: MCP server returns generic error messages with 8-char correlation IDs instead of raw exception text.

### Task 2: Input validation, prompt injection defense, TOCTOU fix, token exposure
- **H-4**: `IntentParser.parse()` sanitizes user descriptions via `ContextBuilder.sanitize()` before passing to LLM.
- **H-5**: `_validate_sexpr_safe_string` validator rejects parens, quotes, newlines in schema string fields (ModifyPropertyOp.new_value, AddLabelOp.name, AddPowerOp.name, AddComponentOp.value, AddDesignRuleOp.condition).
- **L-1**: `_atomic_write` helper in `create_file.py` uses temp file + rename pattern to prevent TOCTOU races. All `write_text` calls replaced.
- **L-2**: GitHub token accessed via `@property` reading from `GITHUB_TOKEN` env var instead of stored as instance attribute.

## Key Files

### Created
- `tests/test_security_hardening.py` (18 tests)

### Modified
- `src/kicad_agent/ops/executor.py` — path confinement
- `src/kicad_agent/ir/pcb_ir.py` — S-expression escaping
- `src/kicad_agent/mcp/server.py` — correlation ID error handling
- `src/kicad_agent/cli.py` — relative path in route handler
- `src/kicad_agent/llm/intent_parser.py` — input sanitization
- `src/kicad_agent/ops/schema.py` — S-expression safe validators
- `src/kicad_agent/ops/create_file.py` — atomic writes
- `src/kicad_agent/crawler/github_discovery.py` — token from env var

## Test Results
- 1496 tests passed, 1 skipped, 0 failures
- 18 new security regression tests all passing

## Deviations
- Path traversal tests use `inspect.getsource()` checks rather than constructing ops with `../../` paths, because `TargetFile` already validates `..` in paths at the schema level. The executor's `is_relative_to()` is a defense-in-depth layer for symlink-based escapes.
