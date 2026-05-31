---
phase: 34-llm-provider-abstraction
plan: 01
subsystem: llm
tags: [protocol, provider, anthropic, mock, factory, abstraction]

# Dependency graph
requires:
  - phase: 33
    provides: "LLMClient, LLMBackend protocol, existing LLM infrastructure"
provides:
  - "LLMProvider protocol with generate(), embed(), create_message()"
  - "AnthropicProvider wrapping LLMClient for full passthrough"
  - "MockProvider with deterministic responses for testing"
  - "get_provider() factory with env-based selection and caching"
affects: [34-02, "all LLM consumers: DesignCritic, ErrorFixer, IntentParser, ComponentSuggester"]

# Tech tracking
tech-stack:
  added: []
  patterns: ["runtime_checkable Protocol for structural typing", "factory with env-var selection and instance caching"]

key-files:
  created:
    - src/kicad_agent/llm/provider.py
    - tests/test_llm_provider.py
  modified:
    - src/kicad_agent/llm/__init__.py

key-decisions:
  - "LLMProvider is a superset of LLMBackend -- any class satisfying LLMProvider automatically satisfies LLMBackend"
  - "AnthropicProvider.create_message() delegates with zero modification to preserve tool_use passthrough"
  - "MockProvider uses inner _MockContent/_MockMessage classes matching FakeMessage pattern from conftest_llm.py"
  - "get_provider() caches by provider name string in module-level dict"

patterns-established:
  - "Provider pattern: @runtime_checkable Protocol + concrete implementations + factory with env-var selection"
  - "Lazy import in AnthropicProvider avoids circular dependency with kicad_agent.llm.client"

requirements-completed: [LLM-13, LLM-14, LLM-16, LLM-17]

# Metrics
duration: 6min
completed: 2026-05-31
---

# Phase 34 Plan 01: LLM Provider Abstraction Summary

**LLMProvider protocol with generate/embed/create_message, AnthropicProvider wrapping LLMClient, MockProvider for testing, and get_provider() factory with env-based caching**

## Performance

- **Duration:** 6 min
- **Started:** 2026-05-31T04:22:10Z
- **Completed:** 2026-05-31T04:28:21Z
- **Tasks:** 1
- **Files modified:** 3

## Accomplishments
- LLMProvider protocol establishing the abstraction layer all consumers will migrate to
- AnthropicProvider with full create_message() passthrough preserving tool_use support for DesignCritic, ErrorFixer, IntentParser, ComponentSuggester
- MockProvider with deterministic responses and call tracking for test isolation
- get_provider() factory reading KICAD_LLM_PROVIDER env var with instance caching
- Both providers satisfy LLMProvider AND LLMBackend protocols (verified via isinstance)
- 21 tests covering all protocol, provider, and factory behaviors with zero regressions

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): Add failing tests for LLMProvider** - `e6e36aa` (test)
2. **Task 1 (GREEN): Implement LLMProvider, providers, factory** - `639e904` (feat)

_Note: TDD task with RED/GREEN cycle. No refactor needed._

## Files Created/Modified
- `src/kicad_agent/llm/provider.py` - LLMProvider protocol, AnthropicProvider, MockProvider, get_provider() factory (151 lines)
- `tests/test_llm_provider.py` - 21 tests across 4 test classes: TestMockProvider, TestAnthropicProvider, TestGetProvider, TestProtocolCompliance (273 lines)
- `src/kicad_agent/llm/__init__.py` - Added lazy imports, _no_anthropic_required entries, and __all__ exports for new provider types

## Decisions Made
- LLMProvider is a superset of LLMBackend -- satisfies both protocols with a single class
- AnthropicProvider.create_message() delegates with zero modification -- preserves all Anthropic-specific kwargs (tools, tool_choice, thinking)
- MockProvider uses inner _MockContent/_MockMessage classes matching the FakeMessage pattern already established in conftest_llm.py
- get_provider() caches by provider name string in a module-level dict -- simple, testable, no global state complexity

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed mock target in AnthropicProvider tests**
- **Found during:** Task 1 (GREEN phase -- tests failing)
- **Issue:** Tests patched `kicad_agent.llm.client.anthropic` but `anthropic` is imported locally inside LLMClient methods, not at module level, so the patch target did not exist
- **Fix:** Changed all test mock targets from `kicad_agent.llm.client.anthropic` to `anthropic.Anthropic` matching the conftest_llm.py pattern
- **Files modified:** tests/test_llm_provider.py
- **Verification:** All 21 tests pass, 100 LLM tests pass with zero regressions
- **Committed in:** 639e904 (Task 1 GREEN commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Minor test fix -- mock target correction. No scope creep.

## Issues Encountered
None beyond the mock target fix documented above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Provider abstraction layer complete and ready for consumer migration in plan 34-02
- MockProvider available for all future tests requiring LLM interaction without API keys
- All 4 tool_use consumers (DesignCritic, ErrorFixer, IntentParser, ComponentSuggester) can now migrate to LLMProvider

---
*Phase: 34-llm-provider-abstraction*
*Completed: 2026-05-31*

## Self-Check: PASSED

- FOUND: src/kicad_agent/llm/provider.py
- FOUND: tests/test_llm_provider.py
- FOUND: src/kicad_agent/llm/__init__.py
- FOUND: e6e36aa (RED commit)
- FOUND: 639e904 (GREEN commit)
