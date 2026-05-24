---
phase: 15-ai-generation-wiring
plan: 01
subsystem: llm
tags: [anthropic, claude, tool-use, pydantic, llm-integration]
dependency_graph:
  requires: [generation/intent.py, ops/schema.py]
  provides: [llm/client.py, llm/tools.py, llm/intent_parser.py, llm/component_suggester.py, llm/context_builder.py]
  affects: [pyproject.toml]
tech_stack:
  added: [anthropic>=0.61.0 (optional)]
  patterns: [anthropic-tool-use, pydantic-model-json-schema, lazy-import-with-importerror]
key_files:
  created:
    - src/kicad_agent/llm/__init__.py
    - src/kicad_agent/llm/client.py
    - src/kicad_agent/llm/tools.py
    - src/kicad_agent/llm/context_builder.py
    - src/kicad_agent/llm/intent_parser.py
    - src/kicad_agent/llm/component_suggester.py
    - tests/conftest_llm.py
    - tests/__init__.py
  modified:
    - pyproject.toml
    - tests/conftest.py
decisions:
  - anthropic as optional [llm] dependency; base install works without it
  - __init__.py uses _check_anthropic_available() guard for clear ImportError
  - conftest_llm.py registered via pytest_plugins in conftest.py for fixture discovery
  - ComponentSuggestion as frozen dataclass (not Pydantic model) for simplicity
  - ContextBuilder uses static methods (no instance state needed)
metrics:
  duration: 7 min
  completed: 2026-05-24
  tasks: 2
  files: 9
  tests: 19
---

# Phase 15 Plan 01: LLM Integration Layer Summary

Natural language to GenerationIntent conversion via Anthropic SDK tool use, with component suggestion, context sanitization, and optional dependency isolation.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | LLM client, tool definitions, and context builder | 42a2e82 | client.py, tools.py, context_builder.py, __init__.py, conftest_llm.py, test_llm_context_builder.py, pyproject.toml |
| 2 | IntentParser and ComponentSuggester with mocked Anthropic calls | 4d9c42b | intent_parser.py, component_suggester.py, test_llm_intent_parser.py, test_llm_component_suggester.py, __init__.py, conftest.py, pyproject.toml |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] conftest_llm.py fixture discovery**
- **Found during:** Task 2
- **Issue:** Pytest only auto-discovers files named exactly `conftest.py`, not `conftest_llm.py`
- **Fix:** Registered conftest_llm as pytest plugin via `pytest_plugins = ["conftest_llm"]` in conftest.py; added `tests` to pythonpath in pyproject.toml; created `tests/__init__.py` for package import support
- **Files modified:** tests/conftest.py, tests/__init__.py, pyproject.toml
- **Commit:** 4d9c42b

**2. [Rule 1 - Bug] __builtins__.__import__ type error in test**
- **Found during:** Task 1
- **Issue:** `__builtins__` is a dict in module context (not a module), causing `AttributeError: 'dict' object has no attribute '__import__'`
- **Fix:** Changed to `import builtins; real_import = builtins.__import__`
- **Files modified:** tests/test_llm_context_builder.py
- **Commit:** 42a2e82

**3. [Rule 1 - Bug] __init__.py ImportError catch too broad**
- **Found during:** Task 1
- **Issue:** `__getattr__` caught all ImportErrors (including missing Task 2 modules) and re-raised as "install anthropic" message
- **Fix:** Added explicit `_check_anthropic_available()` guard before importlib.import_module; removed broad except ImportError
- **Files modified:** src/kicad_agent/llm/__init__.py
- **Commit:** 42a2e82

## Decisions Made

1. **anthropic as optional dependency**: Added `llm = ["anthropic>=0.61.0"]` to pyproject.toml. Base install works without LLM features. Clear ImportError with install instructions when anthropic is missing.

2. **Lazy import guard pattern**: `__init__.py` uses `_check_anthropic_available()` to explicitly test for anthropic before attempting any module import, providing a clear error message distinct from missing-module errors.

3. **ComponentSuggestion as frozen dataclass**: Simpler than Pydantic model since these are read-only value objects returned from LLM calls.

4. **ContextBuilder with static methods**: No instance state needed; all methods operate on input parameters.

## Test Results

```
19 LLM tests passed (0 failures)
1032 total tests passed (full suite, 0 regressions)
```

## Verification

- [x] All LLM module tests pass with mocked Anthropic client
- [x] anthropic is optional: base install imports work without anthropic
- [x] Tool schemas are valid JSON Schema
- [x] Existing test suite unaffected (1032 passed, 1 skipped)

## Self-Check: PASSED

All claimed files verified present. All commit hashes verified in git log.
