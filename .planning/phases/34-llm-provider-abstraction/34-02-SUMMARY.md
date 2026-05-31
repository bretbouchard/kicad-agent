---
phase: 34-llm-provider-abstraction
plan: 02
subsystem: llm
tags: [provider, protocol, migration, consumer, pipeline, abstraction]

# Dependency graph
requires:
  - phase: 34-01
    provides: "LLMProvider protocol, AnthropicProvider, MockProvider, get_provider() factory"
provides:
  - "All 6 LLM consumers accept provider parameter via constructor"
  - "ComponentSuggester also accepts client parameter (was missing)"
  - "pipeline.py uses get_provider() as fallback for all 3 consumer wiring points"
  - "KICAD_LLM_PROVIDER=mock enables MockProvider for entire pipeline"
affects: [34-03, "all LLM tests requiring MockProvider injection"]

# Tech tracking
tech-stack:
  added: []
patterns: ["provider > client > LLMClient constructor priority chain", "get_provider() fallback in pipeline wiring"]

key-files:
  created: []
  modified:
    - src/kicad_agent/llm/design_critic.py
    - src/kicad_agent/llm/error_fixer.py
    - src/kicad_agent/llm/component_suggester.py
    - src/kicad_agent/llm/intent_parser.py
    - src/kicad_agent/llm/unified_parsers.py
    - src/kicad_agent/llm/pipeline.py

key-decisions:
  - "Provider parameter takes strict priority over client over LLMClient creation"
  - "ComponentSuggester gains both client and provider params (was missing client)"
  - "UnifiedIntentParser and UnifiedErrorFixer make client optional with LLMClient fallback"
  - "pipeline.py uses get_provider() only when no HybridLLMClient configured"

patterns-established:
  - "Consumer migration pattern: TYPE_CHECKING import of LLMProvider, provider param in constructor, priority chain provider > client > LLMClient"
  - "Pipeline fallback pattern: hybrid_client check first, then get_provider() as catch-all"

requirements-completed: [LLM-15]

# Metrics
duration: 4min
completed: 2026-05-31
---

# Phase 34 Plan 02: Consumer Migration Summary

**All 6 LLM consumers (DesignCritic, ErrorFixer, IntentParser, ComponentSuggester, UnifiedIntentParser, UnifiedErrorFixer) accept LLMProvider via constructor with provider > client > LLMClient priority chain**

## Performance

- **Duration:** 4 min
- **Started:** 2026-05-31T04:32:32Z
- **Completed:** 2026-05-31T04:36:37Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- All 6 LLM consumer files accept optional `provider` parameter via constructor
- ComponentSuggester now also accepts `client` parameter (was missing from original implementation)
- pipeline.py uses `get_provider()` as fallback at all 3 consumer wiring points (IntentParser, ErrorFixer, DesignCritic)
- `KICAD_LLM_PROVIDER=mock` enables MockProvider for entire pipeline without ANTHROPIC_API_KEY
- 107 LLM tests pass with zero regressions and zero test modifications
- End-to-end verification confirms MockProvider injection works for all 6 consumers

## Task Commits

Each task was committed atomically:

1. **Task 1: Migrate DesignCritic, ErrorFixer, IntentParser, ComponentSuggester** - `0316bd7` (feat)
2. **Task 2: Migrate UnifiedParsers and pipeline.py** - `7fbfa20` (feat)

## Files Created/Modified
- `src/kicad_agent/llm/design_critic.py` - Added provider parameter to constructor with LLMProvider TYPE_CHECKING import
- `src/kicad_agent/llm/error_fixer.py` - Added provider parameter to constructor with LLMProvider TYPE_CHECKING import
- `src/kicad_agent/llm/intent_parser.py` - Added provider parameter to constructor with LLMProvider TYPE_CHECKING import
- `src/kicad_agent/llm/component_suggester.py` - Added both client and provider parameters (was missing client), added TYPE_CHECKING block with LLMBackend and LLMProvider imports
- `src/kicad_agent/llm/unified_parsers.py` - Updated UnifiedIntentParser and UnifiedErrorFixer constructors to accept optional provider, made client optional with LLMClient fallback
- `src/kicad_agent/llm/pipeline.py` - Updated 3 consumer wiring points to use get_provider() fallback when no HybridLLMClient configured

## Decisions Made
- Provider parameter takes strict priority over client over LLMClient creation in all consumers -- consistent priority chain across codebase
- ComponentSuggester gains both `client` and `provider` params to match the pattern used by all other consumers (was only accepting `model`)
- UnifiedIntentParser and UnifiedErrorFixer constructors changed from `client: LLMBackend` (required) to `client: LLMBackend | None = None` (optional) -- backward compatible since all existing callers pass client explicitly
- pipeline.py only calls `get_provider()` when no HybridLLMClient is configured -- HybridLLMClient routing logic stays intact

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Provider abstraction complete across all consumers -- any future provider (Ollama, OpenAI, etc.) can be added to get_provider() factory and immediately available to all pipeline stages
- MockProvider injection available for all future tests requiring LLM interaction without API keys
- Phase 34 complete if no additional provider implementations needed

---
*Phase: 34-llm-provider-abstraction*
*Completed: 2026-05-31*

## Self-Check: PASSED

- FOUND: src/kicad_agent/llm/design_critic.py
- FOUND: src/kicad_agent/llm/error_fixer.py
- FOUND: src/kicad_agent/llm/component_suggester.py
- FOUND: src/kicad_agent/llm/intent_parser.py
- FOUND: src/kicad_agent/llm/unified_parsers.py
- FOUND: src/kicad_agent/llm/pipeline.py
- FOUND: 0316bd7 (Task 1 commit)
- FOUND: 7fbfa20 (Task 2 commit)
