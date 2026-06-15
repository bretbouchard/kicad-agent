---
phase: 95
plan: 02
subsystem: llm
tags: [knowledge-base, section-chunking, op-mapping, local-model]
dependency_graph:
  requires: []
  provides: ["KnowledgeManager", "get_context_for_op", "OP_SECTION_MAP", "CORE_RULES"]
  affects: ["llm/text_prompts.py", "llm/context_builder.py", "llm/local_client.py"]
tech_stack:
  added: ["tiktoken (optional, fallback to char-based)"]
  patterns: ["lazy-loading", "category-default-override", "paragraph-boundary-truncation"]
key_files:
  created:
    - path: "src/kicad_agent/llm/knowledge.py"
      lines: 792
    - path: "tests/test_knowledge.py"
      lines: 335
  modified:
    - path: "src/kicad_agent/llm/__init__.py"
      lines_changed: 3
decisions: []
metrics:
  duration_seconds: 222
  completed_date: "2026-06-15"
---

# Phase 95 Plan 02: KnowledgeManager Core Module Summary

**One-liner:** KnowledgeManager with H2 section chunking, per-operation doc mapping covering all 117 registry ops, and paragraph-boundary-aware token truncation.

## What Changed

Created the central knowledge module (`knowledge.py`) that loads KiCad reference documents, chunks them by `##` header sections, and maps operations to relevant doc sections for prompt injection. Registered in `llm/__init__.py` as a lazy import that does not require the `anthropic` package.

## Key Components

### `_chunk_by_h2(text) -> dict[str, str]`
Splits markdown into sections keyed by `##` header titles. Text before the first header is ignored. Duplicate headers use last-wins semantics (second occurrence overwrites first), matching the plan's spec for handling kicad_docs.md which has repeated sections.

### `_truncate_section(text, max_tokens=800) -> str`
Caps individual sections at 800 tokens. Uses tiktoken when available, falling back to ~4 chars/token heuristic. Splits on double-newline boundaries to preserve complete paragraphs.

### `CORE_RULES` constant
Five critical KiCad rules always injected into every prompt: pin at=connection point, Y-axis inversion, R/C 3.81mm offset, wire termination at (at), grid snap values.

### `OP_SECTION_MAP` (117 entries)
Covers ALL 117 operations from OPERATION_REGISTRY via a two-tier mapping:
1. **Per-op overrides** (~100 ops) for specific section mappings
2. **Category defaults** (21 categories) as fallback

Built dynamically from `OPERATION_REGISTRY` -- no hardcoded operation counts.

### `_CATEGORY_DEFAULTS` (21 categories)
Maps every registry category to relevant doc sections. Verified by dynamic test against `OPERATION_REGISTRY`.

### `KnowledgeManager` class
- Lazy loading: docs parsed on first `get_context_for_op()` call, cached thereafter
- Graceful degradation: missing `docs/` returns CORE_RULES only with warning log
- Full-doc injection: headerless files (gerbview_reference.md) injected in entirety
- Deduplication: by `(doc_name, section_name)` tuple pairs, not doc_name alone
- Configurable budget: `KICAD_KNOWLEDGE_TOKEN_BUDGET` env var (default 2000)
- Disabled mode: returns empty string when `disabled=True`

### `llm/__init__.py` registration
- Added to `_lazy` dict, `_no_anthropic_required` set, and `__all__` list

## TDD Gate Compliance

| Gate | Commit | Status |
|------|--------|--------|
| RED | `ecb7a76` | 16 test cases written, all fail with ModuleNotFoundError |
| GREEN | `14573f5` | knowledge.py implemented, 23/24 tests pass |
| Task 2 | `5554453` | __init__.py registration, 24/24 tests pass |

## Test Coverage

24 tests across 6 test classes:
- `TestChunkByH2` (5 tests): basic splitting, preamble ignoring, empty input, duplicate headers, empty body
- `TestTruncateSection` (3 tests): short text, empty text, long text paragraph boundary
- `TestCoreRules` (2 tests): content verification, non-empty check
- `TestKnowledgeManager` (9 tests): path resolution, core rules inclusion, missing docs, caching, deduplication, full-doc loading, disabled mode, env var budget, default budget
- `TestOpSectionMapCoverage` (2 tests): all 117 registry ops covered, all 21 categories covered
- `TestKnowledgeRegistration` (2 tests): lazy import, no-anthropic import)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed gerbview full-doc injection test**
- **Found during:** Task 1 GREEN phase
- **Issue:** Test `test_full_doc_injection_for_no_header_docs` called `get_context_for_op("add_component")` expecting gerbview content, but `add_component` maps to `kicad_agent_reference.md` sections, not gerbview. The gerbview doc WAS correctly loaded as a full doc, but no op maps to it in the default OP_SECTION_MAP.
- **Fix:** Rewrote test to verify `_full_docs` dict directly (checking that gerbview loads as full doc, not sections), rather than relying on an indirect operation mapping path that would never include gerbview content for `add_component`.
- **Files modified:** `tests/test_knowledge.py`
- **Commit:** `14573f5` (bundled with GREEN commit)

## Known Stubs

None. All functions are fully implemented with real behavior.

## Threat Flags

None. All threat model items (T-95-01 through T-95-04) are mitigated:
- T-95-01: Path resolution uses `Path.resolve()` + restricted to known DOC_FILES list + `is_dir()` check
- T-95-02: OP_SECTION_MAP uses hardcoded doc filenames, never from user input
- T-95-03: Source docs are project-controlled markdown in git
- T-95-04: Lazy loading + in-memory cache + one-time parse

## Self-Check: PASSED

- [x] `src/kicad_agent/llm/knowledge.py` exists (792 lines)
- [x] `tests/test_knowledge.py` exists (335 lines)
- [x] `src/kicad_agent/llm/__init__.py` modified (3 lines added)
- [x] Commit `ecb7a76` exists (RED)
- [x] Commit `14573f5` exists (GREEN)
- [x] Commit `5554453` exists (Task 2)
- [x] 24/24 tests pass
- [x] `from kicad_agent.llm import KnowledgeManager` succeeds
- [x] OP_SECTION_MAP covers all 117 ops (dynamic test)
- [x] _CATEGORY_DEFAULTS covers all 21 categories (dynamic test)
