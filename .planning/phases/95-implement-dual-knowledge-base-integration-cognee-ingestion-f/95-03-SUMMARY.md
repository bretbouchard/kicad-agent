---
phase: 95-implement-dual-knowledge-base-integration-cognee-ingestion-f
plan: 03
subsystem: llm
tags: [knowledge-base, token-budget, tiktoken, sanitization, prompt-injection, cli-flag]
dependency_graph:
  requires:
    - phase: "95-02"
      provides: ["KnowledgeManager", "get_context_for_op", "OP_SECTION_MAP", "CORE_RULES", "_truncate_section"]
  provides:
    - "Token budget enforcement via _enforce_token_budget()"
    - "Knowledge context sanitization via ContextBuilder.sanitize()"
    - "knowledge_context parameter on build_text_prompt, build_error_summary, _build_prompt"
    - "--no-knowledge CLI flag"
    - "KnowledgeManager wired into TextIntentParser, TextErrorFixer, InferenceWrapper"
  affects: ["llm/text_prompts.py", "llm/context_builder.py", "inference/wrapper.py", "llm/text_parsers.py", "cli.py"]
tech_stack:
  added: ["tiktoken (combined budget enforcement)"]
  patterns: ["combined-token-budget", "sanitized-knowledge-injection", "optional-knowledge-context"]
key_files:
  created: []
  modified:
    - path: "src/kicad_agent/llm/knowledge.py"
      lines_changed: 55
    - path: "src/kicad_agent/llm/text_prompts.py"
      lines_changed: 22
    - path: "src/kicad_agent/llm/context_builder.py"
      lines_changed: 10
    - path: "src/kicad_agent/inference/wrapper.py"
      lines_changed: 30
    - path: "src/kicad_agent/llm/text_parsers.py"
      lines_changed: 40
    - path: "src/kicad_agent/cli.py"
      lines_changed: 20
    - path: "tests/test_knowledge.py"
      lines_changed: 270
key-decisions:
  - "Combined budget enforcement via _enforce_token_budget() applied after per-section caps (two-tier: per-section 800 + total 2000)"
  - "ContextBuilder.sanitize() called on final combined output (not per-section) to strip injection patterns"
  - "Optional knowledge_manager parameter on TextIntentParser/TextErrorFixer (backward compatible, no existing callers affected)"
  - "KnowledgeManager created locally in _handle_analyze (not global) to respect lifecycle per CLI invocation"
  - "--no-knowledge flag on legacy operation parser (knowledge injection is LLM-path only, not executor path)"
patterns-established:
  - "Two-tier token budget: per-section cap (800) via _truncate_section, combined cap (2000) via _enforce_token_budget"
  - "Optional knowledge_context parameter pattern: all prompt builders accept knowledge_context='' default"
requirements-completed: ["D-02", "D-03", "D-04", "D-05"]
metrics:
  started: "2026-06-15T04:46:55Z"
  completed: "2026-06-15T04:54:48Z"
  duration: 7m 53s
  duration_minutes: 8
  commits: 5
  files_modified: 7
---

# Phase 95 Plan 03: KnowledgeManager Integration and Token Budget Enforcement Summary

**One-liner:** Token budget enforcement with tiktoken, ContextBuilder sanitization, knowledge_context injection into three prompt builders, --no-knowledge CLI flag, and execution path wiring into TextIntentParser/TextErrorFixer/InferenceWrapper.

## What Changed

Added two-tier token budget enforcement (per-section 800 + combined 2000) to KnowledgeManager, sanitized all knowledge output via ContextBuilder.sanitize() to prevent prompt injection, and wired knowledge context injection into all three prompt builder integration points (build_text_prompt, build_error_summary, _build_prompt). Added --no-knowledge CLI flag. Wired KnowledgeManager into the actual LLM execution paths: TextIntentParser, TextErrorFixer, and InferenceWrapper.analyze().

## Key Components

### `_enforce_token_budget(text, max_tokens)` in knowledge.py
Combined budget enforcement applied after per-section caps. Uses tiktoken for token counting with character-based fallback (~4 chars/token) if tiktoken is unavailable. Logs WARNING when truncation occurs.

### `get_context_for_op()` enhancements
Now calls `_enforce_token_budget()` on combined output and `ContextBuilder.sanitize()` on the final result before returning. Logs "First knowledge lookup (lazy load)" on first call.

### `build_text_prompt()` knowledge_context parameter
Accepts optional `knowledge_context: str = ""` parameter. Injects knowledge between system prompt and user context under a `## KiCad Reference Knowledge` header. Backward compatible -- empty default means no change for existing callers.

### `build_error_summary()` knowledge_context parameter
Accepts optional `knowledge_context: str = ""` parameter. Prepends knowledge to the parts list before ERC/DRC status lines. Backward compatible.

### `_build_prompt()` knowledge_context parameter
Accepts optional `knowledge_context: str = ""` parameter. Appends knowledge to system message content under a `## KiCad Reference Knowledge` header. Backward compatible.

### `--no-knowledge` CLI flag
Added to `_build_operation_parser()` in cli.py. `store_true` action with `default=False`. Sets `KnowledgeManager(disabled=True)` when used.

### TextIntentParser/TextErrorFixer knowledge wiring
Both accept optional `knowledge_manager` parameter in `__init__()`. TextIntentParser calls `km.get_context_for_op(op_type)` in `parse()` and passes to `build_text_prompt`. TextErrorFixer does the same in `fix()` with default op_type `"repair_schematic"`. Both backward compatible.

### InferenceWrapper knowledge wiring
Accepts optional `knowledge_manager` parameter in `__init__()`. `analyze()` calls `km.get_context_for_op("analyze")` and passes to `_build_prompt()`. `generate_analysis()` function also accepts and forwards `knowledge_manager`.

### _handle_analyze CLI wiring
Creates `KnowledgeManager()` instance and passes to `generate_analysis(knowledge_manager=km)`.

## TDD Gate Compliance

| Gate | Commit | Status |
|------|--------|--------|
| RED (Task 1) | `0b8ae97` | 10 token budget tests written, all fail with ImportError |
| GREEN (Task 1) | `2474092` | _enforce_token_budget implemented, 34/34 pass |
| RED (Task 2) | `682d127` | 7 prompt integration tests written, all fail |
| GREEN (Task 2) | `b9c6f0a` | 4 files modified, 41/41 pass |
| Task 3 | `a49051e` | Execution wiring + E2E tests, 47/47 pass |

## Test Coverage

47 tests across 9 test classes:
- `TestChunkByH2` (5 tests): basic splitting, preamble, empty, duplicates, no body
- `TestTruncateSection` (3 tests): short, empty, paragraph boundary
- `TestCoreRules` (2 tests): content, non-empty
- `TestKnowledgeManager` (9 tests): path resolution, core rules, missing docs, caching, dedup, full doc, disabled, env var, default budget
- `TestOpSectionMapCoverage` (2 tests): all ops mapped, all categories covered
- `TestExports` (1 test): __all__ complete
- `TestKnowledgeRegistration` (2 tests): lazy import, no-anthropic import
- `TestTokenBudget` (10 tests): small pass-through, large truncation, per-section cap, combined truncation, warning log, tiktoken fallback, core rules under 200 tokens, env var override, sanitization, logging
- `TestPromptIntegration` (7 tests): knowledge injection, backward compat, error summary prepend, error summary compat, _build_prompt append, flag exists, flag parses true)
- `TestExecutionWiring` (6 tests): import exists, flag disables, knowledge flows to prompt, E2E flow, coverage assertion ops, coverage assertion categories)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed missing `logging` import in test file**
- **Found during:** Task 1 GREEN phase
- **Issue:** Test file used `logging.WARNING` without importing `logging` module
- **Fix:** Added `import logging` to test imports
- **Files modified:** `tests/test_knowledge.py`
- **Commit:** `2474092` (bundled with GREEN commit)

**2. [Rule 1 - Bug] Fixed cli package vs module import conflict**
- **Found during:** Task 2 GREEN phase
- **Issue:** `from kicad_agent.cli import _build_operation_parser` failed because `cli/` package directory shadows `cli.py` module. The `cli/__init__.py` only re-exports `main` and `_handle_gate`.
- **Fix:** Tests import via `kicad_agent.cli` package then access `_cli_impl._build_operation_parser` through the package's internal module reference.
- **Files modified:** `tests/test_knowledge.py`
- **Commit:** `b9c6f0a` (bundled with GREEN commit)

## Known Stubs

None. All functions are fully implemented with real behavior.

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| None | | T-95-05 (prompt injection via knowledge content) mitigated by ContextBuilder.sanitize() on all output |
| None | | T-95-06 (DoS via large knowledge) mitigated by per-section 800 cap + total 2000 budget |

## Self-Check: PASSED

- [x] `src/kicad_agent/llm/knowledge.py` modified (55 lines added: _enforce_token_budget + sanitization)
- [x] `src/kicad_agent/llm/text_prompts.py` modified (22 lines changed: knowledge_context param)
- [x] `src/kicad_agent/llm/context_builder.py` modified (10 lines changed: knowledge_context param)
- [x] `src/kicad_agent/inference/wrapper.py` modified (30 lines changed: knowledge_manager + _build_prompt wiring)
- [x] `src/kicad_agent/llm/text_parsers.py` modified (40 lines changed: knowledge_manager on parsers)
- [x] `src/kicad_agent/cli.py` modified (20 lines changed: --no-knowledge flag + analyze wiring)
- [x] `tests/test_knowledge.py` modified (270 lines added: 23 new tests)
- [x] Commit `0b8ae97` exists (RED Task 1)
- [x] Commit `2474092` exists (GREEN Task 1)
- [x] Commit `682d127` exists (RED Task 2)
- [x] Commit `b9c6f0a` exists (GREEN Task 2)
- [x] Commit `a49051e` exists (Task 3)
- [x] 47/47 tests pass
- [x] 10/10 context_builder tests pass
- [x] `build_text_prompt('intent_parse', 'test')` works unchanged (backward compat)
- [x] No hardcoded operation counts in any test
- [x] No accidental file deletions
