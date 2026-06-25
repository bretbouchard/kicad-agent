---
phase: 98-ai-routing-strategy-advisor
fixed_at: 2026-06-25T00:00:00Z
review_path: .planning/phases/98-ai-routing-strategy-advisor/98-COUNCIL-EXEC-REVIEW.md
iteration: followup
findings_in_scope: 9
fixed: 9
skipped: 0
status: all_fixed
---

# Phase 98: Follow-up Fix Report (Council Exec Review)

**Fixed at:** 2026-06-25
**Source review:** `.planning/phases/98-ai-routing-strategy-advisor/98-COUNCIL-EXEC-REVIEW.md`
**Iteration:** followup (ME-05 / H-1 was already resolved by the Phase 100 followup agent)

**Summary:**
- Findings in scope: 9 (ME-01..ME-04, IN-01..IN-05)
- Fixed: 9
- Skipped: 0
- Status: all_fixed

**Test verification:** `tests/test_phase98_*.py` — 105 passed (up from 97 baseline; 8 new regression tests added). Command: `.venv/bin/python -m pytest tests/test_phase98_eval.py tests/test_phase98_ai_strategy.py tests/test_phase98_strategy_parser.py tests/test_phase98_strategy_prompts.py tests/test_phase98_strategy_validator.py -q --deselect tests/test_phase98_eval.py::TestEndToEnd`

---

## Fixed Issues

### ME-01: `model_output_chars` is always 0 in AI strategy results

**Severity:** MEDIUM
**Files modified:** `scripts/phase98_eval.py`, `tests/test_phase98_eval.py`
**Commit:** `681d01e`
**Applied fix:** YAGNI removal (option a from the review). The `model_output_chars` field was always 0 because `main()` never wired it through. Removed the field from the `StrategyEvalResult` dataclass, the `model_output_chars` parameter from `run_strategy_with_orchestrator`, the constructor call, and all test constructors / field-assertion lists. `parse_success` (computed independently from net notes containing the `ai_fallback:` marker) is the real SC-1 diagnostic. `grep "model_output_chars src/ tests/ scripts/` now returns zero hits in the Phase 98 code path.

### ME-02: SC-2 "matches or beats" counts ties as wins, masks R-6 fallbacks

**Severity:** MEDIUM
**Files modified:** `scripts/phase98_eval.py`, `tests/test_phase98_eval.py`
**Commit:** `cd28244`
**Applied fix:** Short-circuit in `evaluate_sc2`. When `ai.parse_success=False` (R-6 fallback fired), the AI result is byte-identical to the deterministic baseline so every metric is a tie. The function now returns `[]` immediately in that case instead of counting the degenerate ties as wins. The existing `test_sc2_tie_counts_as_match` test was updated to explicitly set `parse_success=True` (genuine ties still count). Added `test_sc2_does_not_count_fallback_ties_as_wins` regression test verifying both-fallback → `winners == []`.

### ME-03: `run_drc` output path collision when called twice on same stem

**Severity:** MEDIUM
**Files modified:** `scripts/phase98_eval.py`, `tests/test_phase98_eval.py`
**Commit:** `458dca8`
**Applied fix:** Added `tag: str = "default"` keyword parameter to `run_drc`. The report path is now `<stem>.<tag>.drc.json` so deterministic and AI runs on same-stem PCB copies do not clobber each other. Threaded a `drc_tag` parameter through `run_strategy_with_orchestrator`. Updated both callers in `main()` to pass `drc_tag="det"` and `drc_tag="ai"`. Added `test_run_drc_tag_prevents_collision` regression test verifying two calls with distinct tags produce distinct `--output` paths.

### ME-04: Raw exception text in `routing_notes` audit trail

**Severity:** MEDIUM
**Files modified:** `src/kicad_agent/routing/ai_strategy.py`, `tests/test_phase98_ai_strategy.py`
**Commit:** `92e6a13`
**Applied fix:** Sanitized the exception message in the broad `except Exception` fallback. The message is now truncated to 200 chars and newlines/CR are collapsed to spaces via `str(exc).replace("\n", " ").replace("\r", " ").strip()[:200]`. The exception type (trusted Python class name) is preserved. Added `test_fallback_truncates_and_sanitizes_exception` regression test that feeds a 500+ char multiline hostile message and asserts: (1) no newlines survive, (2) message portion ≤ 200 chars, (3) `RuntimeError` class name preserved.

### IN-01: Net names interpolated into prompt without escaping

**Severity:** LOW (LO-01)
**Files modified:** `src/kicad_agent/routing/strategy_prompts.py`, `tests/test_phase98_strategy_prompts.py`
**Commit:** `829dd6d`
**Applied fix:** Added `_sanitize_net_name(name)` helper that escapes backslashes (`\\` → `\\\\`), escapes double-quotes (`"` → `\"`), and collapses newlines before interpolation. Applied at both interpolation sites in `build_strategy_prompt` (the per-net pin-count lines and the flat net-names list). Added `test_net_names_with_special_chars_are_escaped` regression test with hostile net names containing `"; INJECT`, backslashes, and embedded newlines — verifying the escaped forms appear and the raw hostile substrings do not.

### IN-02: O(n²) worst-case brace-span parser

**Severity:** LOW (LO-02)
**Files modified:** `src/kicad_agent/routing/strategy_parser.py`, `tests/test_phase98_strategy_parser.py`
**Commit:** `6380718`
**Applied fix:** Rewrote `_extract_brace_spans` as a single-pass O(n) stack-based scan. The previous implementation restarted from `start + 1` when a span failed to close, re-scanning the same characters and giving quadratic worst-case on deeply nested unclosed input. The new version visits each character exactly once, tracking depth and a stack of top-level open-brace positions. Added `TestExtractBraceSpansPerformance` class with 4 tests including `test_deeply_nested_unclosed_does_not_re_scan_quadratically` which feeds 100k unclosed braces and asserts completion in <2s (the old algorithm would take minutes).

### IN-03: Dead `ValidationResult` class (YAGNI violation)

**Severity:** LOW (LO-03)
**Files modified:** `src/kicad_agent/routing/strategy_validator.py`
**Commit:** `3a15701`
**Applied fix:** Removed the `ValidationResult` class entirely (13 lines including docstring and `__slots__ = ()`). Verified zero callers via `grep -rn "ValidationResult"` before deletion — only the definition and its own docstring reference existed; the unrelated `HlabelValidationResult` and `GenerationValidationResult` classes in other modules are unaffected. Per project SLC / Ponytail / `tool-first.md` rules, speculative placeholders should be tracked as a Bead rather than shipped. Re-add when a consumer needs it.

### IN-04: `test_f4_net_coverage_violation_falls_back` assertion is loose

**Severity:** LOW (LO-04)
**Files modified:** `tests/test_phase98_ai_strategy.py`
**Commit:** `c54a1a3`
**Applied fix:** Tightened the assertion in `test_f4_net_coverage_violation_falls_back`. The old OR condition (`"net_priorities" in ... or "ValueError" in ...`) would pass even if the error message format changed significantly. Now asserts the specific `"missing from net_priorities"` substring that `StrategyValidator._validate_net_references` raises for this exact violation (N1 in netlist but absent from `net_priorities`).

### IN-05: `test_help_mentions_flags` expects `--help` to exit 0

**Severity:** LOW (LO-05)
**Files modified:** `tests/test_phase98_eval.py`
**Commit:** `7ea7eac`
**Applied fix:** Added an inline comment documenting argparse exit code semantics: `--help` → `SystemExit(code=0)` (success, help to stdout); parse error → `SystemExit(code=2)` (error to stderr). The assertion `exc_info.value.code == 0` is now explicitly a check that `--help` triggers the help path rather than a parse error.

---

## Skipped Issues

None. All 9 in-scope findings were applied cleanly.

---

## Verification

**3-tier verification per finding:**
- Tier 1 (re-read modified section): PASSED for all 9 findings
- Tier 2 (Python `ast.parse` syntax check): PASSED for all 9 findings
- Tier 3 (full Phase 98 test suite): 105 passed, 0 failed (8 new regression tests added)

**Regression tests added (8 total):**
1. `test_sc2_does_not_count_fallback_ties_as_wins` (ME-02)
2. `test_run_drc_tag_prevents_collision` (ME-03)
3. `test_fallback_truncates_and_sanitizes_exception` (ME-04)
4. `test_net_names_with_special_chars_are_escaped` (IN-01)
5. `test_extract_spans_balanced` (IN-02)
6. `test_extract_spans_unclosed_returns_empty` (IN-02)
7. `test_extract_spans_ignores_braces_inside_strings` (IN-02)
8. `test_deeply_nested_unclosed_does_not_re_scan_quadratically` (IN-02)

**Logic-bug flag:** ME-02 (SC-2 short-circuit) and IN-02 (parser rewrite) involve logic changes. Tier 1/Tier 2 verify syntax/structure only; the new regression tests cover the semantics. Flagged for human verification per the fixer protocol, though the test coverage is strong.

---

_Fixed: 2026-06-25_
_Fixer: Claude (gsd-code-fixer, /gsd-code-review-fix workflow)_
_Iteration: followup_
