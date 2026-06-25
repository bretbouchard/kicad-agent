---
phase: 98-ai-routing-strategy-advisor
reviewed: 2026-06-25T00:00:00Z
depth: standard
files_reviewed: 10
files_reviewed_list:
  - src/kicad_agent/routing/strategy_prompts.py
  - src/kicad_agent/routing/strategy_parser.py
  - src/kicad_agent/routing/ai_strategy.py
  - src/kicad_agent/routing/strategy_validator.py
  - scripts/phase98_eval.py
  - tests/test_phase98_strategy_prompts.py
  - tests/test_phase98_strategy_parser.py
  - tests/test_phase98_ai_strategy.py
  - tests/test_phase98_strategy_validator.py
  - tests/test_phase98_eval.py
findings:
  critical: 0
  warning: 4
  info: 5
  total: 9
status: issues_found
---

# Phase 98: Code Review Report

**Reviewed:** 2026-06-25T00:00:00Z
**Depth:** standard
**Files Reviewed:** 10
**Status:** issues_found

## Summary

Phase 98 implements an AI Routing Strategy Advisor with a strong defense-in-depth
architecture. The core security property holds: **model output never reaches file
mutation without passing through R-4 validation, and any failure degrades safely
to the trusted DeterministicStrategy via R-6 fallback.** The structural subtyping
contract (`AiRoutingStrategy.__bases__ == (object,)`) is verified by
`test_no_inheritance_from_protocol`, and the Protocol remains
`@runtime_checkable`-free (correctly rejecting `issubclass`).

The implementation demonstrates mature defensive engineering:
- `parse_strategy_json` never raises (returns `{}` on total failure)
- `_coerce_backend` wraps `RouterBackend(value.lower())` in try/except (Council M-1)
- Unknown backends degrade to ASTAR (lowest privilege)
- The eval harness copies fixtures to temp dirs before routing (T-98-03-01)
- Integration tests use three independent skip guards (`mlx_vlm`, `kicad-cli`, Freerouting)

No critical or security issues were found. Four warnings address logic/robustness
gaps that should be resolved before merging to avoid subtle measurement bugs and
edge-case crashes. Five info-level items document minor improvements.

## Warnings

### WR-01: `model_output_chars` is always 0 for AI strategy results

**File:** `scripts/phase98_eval.py:85-154` and `:482-490`
**Issue:** `run_strategy_with_orchestrator` accepts a `model_output_chars`
parameter (default 0) intended to capture the raw model output length for AI
runs (SC-1 diagnostic). However, the caller in `main()` never passes it:

```python
ai_result = run_strategy_with_orchestrator(
    ai_strategy,
    pcb_path=pcb_copy_ai,
    project_dir=project_dir,
    strategy_name="AiRoutingStrategy",
    # model_output_chars NOT passed -> always 0
)
```

This means every AI result in the eval output reports
`model_output_chars: 0`, rendering the diagnostic useless for interpreting SC-1
parse-success rates. The `StrategyEvalResult.model_output_chars` field is also
untested for the non-zero case.

**Fix:** Either (a) remove the field if it's not wired up (YAGNI), or (b)
capture the raw output. Option (b) requires `AiRoutingStrategy.strategize` to
expose the raw model output, which currently isn't surfaced. The cleanest fix
is to remove `model_output_chars` from the dataclass and the function signature
until the diagnostic is actually needed:

```python
# Remove model_output_chars from StrategyEvalResult and run_strategy_with_orchestrator
# Or, if keeping for future use, add a TODO with a linked Bead for wiring it up.
```

### WR-02: SC-2 "matches or beats" counts ties as wins, masking R-6 fallbacks

**File:** `scripts/phase98_eval.py:303-330`
**Issue:** `evaluate_sc2` uses `ai.via_count <= det.via_count` (and similarly for
trace length and completion). When the AI strategy falls back to
DeterministicStrategy (R-6), the AI result is byte-identical to the deterministic
baseline — so all three metrics are ties, and SC-2 reports "AI wins 3/3 metrics."

This can make a 100% fallback run look like a perfect AI victory, masking the
fact that the model contributed nothing. The `parse_success=False` flag is
tracked separately, but the SC-2 summary line (`"AI wins 3/3 metrics"`) is the
most visible output and gives a false positive.

**Fix:** Short-circuit SC-2 when the AI result is a fallback. Either return an
empty winners list, or annotate the result:

```python
def evaluate_sc2(det: StrategyEvalResult, ai: StrategyEvalResult) -> list[str]:
    # If AI fell back, it contributed nothing — don't credit it with ties.
    if not ai.parse_success:
        return []  # or ["(fallback — no AI contribution)"]
    winners: list[str] = []
    if ai.completion_pct >= det.completion_pct:
        winners.append("completion_pct")
    # ...
```

### WR-03: `run_drc` output path collision when called twice on same PCB

**File:** `scripts/phase98_eval.py:167-193`
**Issue:** `run_drc` writes the DRC report to `pcb_path.with_suffix(".drc.json")`.
In `main()`, the deterministic baseline and the AI strategy run on DIFFERENT
copies of the fixture (`pcb_copy` and `pcb_copy_ai`), so the `.drc.json` files
land at different paths (e.g., `.../smd_test_board.drc.json` for both, since both
copies share the same stem). The second `run_drc` call overwrites the first's
report file.

This is not currently a bug because the report is read immediately and the
result is captured in a `StrategyEvalResult` before the second call. However, it
becomes one if (a) error handling changes to preserve the report for debugging,
or (b) the two copies ever share the same filename (which they currently do —
both are named `<fixture>.kicad_pcb` inside the same `tmp_dir`).

**Fix:** Give each DRC report a unique name, or read+delete the report after
parsing:

```python
def run_drc(pcb_path: Path, *, tag: str = "") -> tuple[bool, int]:
    suffix = f".{tag}.drc.json" if tag else ".drc.json"
    out_path = pcb_path.with_suffix(suffix)
    # ...
```

Then call `run_drc(pcb_copy, tag="det")` and `run_drc(pcb_copy_ai, tag="ai")`.

### WR-04: `_AiStrategyError` message contains raw exception text in `routing_notes`

**File:** `src/kicad_agent/routing/ai_strategy.py:168-181`
**Issue:** When the broad `except Exception` fires, the fallback result's
`routing_notes` is set to `f"ai_fallback: {type(exc).__name__}: {exc}"`. The
`exc` text comes from arbitrary exceptions (model errors, parse errors,
validation errors). If the model output contains prompt-injection-style content
or paths/credentials leaked into error messages, that content lands in the
audit trail `routing_notes` field unchecked.

The audit trail is consumed by `RoutingAuditLog` (Phase 100) and may be
displayed in dashboards. While the model output itself is sandboxed (never
reaches file mutation), error messages derived from it can still leak into
logs.

**Fix:** Truncate and sanitize the exception text. Keep the exception type
(trusted) but limit the message length and strip newlines:

```python
exc_msg = str(exc).strip().replace("\n", " ")[:200]
return replace(
    fallback,
    routing_notes=f"ai_fallback: {type(exc).__name__}: {exc_msg}",
)
```

## Info

### IN-01: Net names interpolated into prompt without escaping

**File:** `src/kicad_agent/routing/strategy_prompts.py:38-42`
**Issue:** Net names from `netlist.keys()` are inserted directly into the prompt
f-string. If a net name contained backticks, `{`, `}`, or `"`, it could
degrade prompt structure. In practice, KiCad net names are restricted in
character set (no whitespace, limited special chars), so this is low-risk.
Noted for completeness — the prompt is sent to the model, not executed as code.
**Fix:** Optional: wrap net names in quotes and escape backslashes:
`name.replace("\\", "\\\\").replace('"', '\\"')`.

### IN-02: `_extract_brace_spans` has O(n²) worst-case on deeply nested input

**File:** `src/kicad_agent/routing/strategy_parser.py:82-125`
**Issue:** The outer `while i < n` loop advances `i = start + 1` when a brace
span fails to close, meaning the same characters are re-scanned. For a string
of `n` opening braces with no closing brace, this is O(n²). Model output is
typically <8KB so this is unlikely to matter in practice, but a malicious or
truncated output could cause noticeable latency.
**Fix:** Acceptable for current input sizes. If this ever matters, track
visited positions or bail out after a max scan length.

### IN-03: `ValidationResult` class is dead code

**File:** `src/kicad_agent/routing/strategy_validator.py:238-249`
**Issue:** `ValidationResult` is defined with `__slots__ = ()` and a docstring
stating it's a "placeholder for future structured-validation return type." No
code references it, and it's not in `__all__` (the module has no `__all__`).
Per the project's SLC and YAGNI rules, speculative placeholders should be
tracked as a Bead rather than shipped.
**Fix:** Remove the class. Re-add when a consumer needs it, or create a Bead
labeled `future-enhancement` documenting the intent.

### IN-04: `test_f4_net_coverage_violation_falls_back` assertion is loose

**File:** `tests/test_phase98_ai_strategy.py:218-234`
**Issue:** The test asserts `result.routing_notes.startswith("ai_fallback:")`
plus an OR condition (`"net_priorities" in ... or "ValueError" in ...`). The OR
makes the test pass even if the error message format changes significantly. This
is a minor test-robustness issue.
**Fix:** Tighten to assert the specific violation type:
`assert "missing from net_priorities" in result.routing_notes`.

### IN-05: `test_help_mentions_flags` expects `--help` to exit 0

**File:** `tests/test_phase98_eval.py:361-369`
**Issue:** `pytest.raises(SystemExit)` with `exc_info.value.code == 0` — argparse
exits with code 0 on `--help`, which is correct, but the test would also pass if
argparse exited with code 2 (argument error) and the code happened to be set to
0 elsewhere. This is a minor test-clarity issue.
**Fix:** Add a comment documenting that argparse exits 0 on `--help` and 2 on
parse errors, so future readers understand the assertion.

---

_Reviewed: 2026-06-25T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
