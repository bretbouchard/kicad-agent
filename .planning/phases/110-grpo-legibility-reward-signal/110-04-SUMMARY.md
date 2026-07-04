---
phase: 110-grpo-legibility-reward-signal
plan: 04
subsystem: training-grpo-integration
tags: [grpo, legibility, reward-integration, phase-110]
dependency_graph:
  requires:
    - "Plan 01 reward module (LegibilityReward + caps + CapInputs)"
    - "Phase 109 CritiqueResult (SHIPPED)"
    - "Phase 110 Plan 04 config.json training block"
    - "Phase 100 CR-01 frozen dataclasses"
  provides:
    - "LegibilityRewardAdapter — bridges reward module + CritiqueResult + D-03 combine"
    - "RewardWeights dataclass (sum=1.0 validated)"
    - "AdvantageWeightedTrainer with optional legibility_adapter + critique registry"
    - "Multi-objective compute_group_rewards (D-03 wired)"
  affects:
    - "src/kicad_agent/training/grpo.py (extended __init__ + compute_group_rewards)"
    - ".planning/config.json (training block added)"
tech_stack:
  added: []
  patterns:
    - "frozen dataclass adapter (Phase 100 CR-01)"
    - "post-rollout critique registry keyed by sample_id (CR-110-03 — no hasattr on sample)"
    - "HI-110-05 source-gated completeness resolution"
    - "LO-110-11 broad except on reward computation (training never crashes on bad critique)"
    - "backward-compat via optional adapter=None (regression-safe extension)"
key_files:
  created:
    - "src/kicad_agent/training/legibility_reward_adapter.py"
    - "tests/test_legibility_reward_adapter.py"
    - "tests/test_grpo_legibility_integration.py"
  modified:
    - "src/kicad_agent/training/grpo.py"
    - ".planning/config.json"
decisions:
  - "CR-110-03: critique registry keyed by sample_id, NOT added to MazeSample (maze samples are abstract puzzles)"
  - "HI-110-05: completeness_source explicit ('none' default folds weight into correctness; v1 trains 80/20)"
  - "LO-110-11: compute_legibility catches KeyError/ValueError -> 0.0 with warning (training continues)"
  - "Backward compat preserved via legibility_adapter=None default"
metrics:
  duration: "1 commit"
  tasks_completed: 2
  files_touched: 5
  completed_date: "2026-07-04"
---

# Phase 110 Plan 04: GRPO Loop Integration Summary

Wires Plan 01's LegibilityReward + caps + CapInputs into the existing GRPO training loop as a multi-objective reward (D-03: 0.40 correctness / 0.40 completeness / 0.20 legibility). All weights configurable via `.planning/config.json`. Backward compatible — pre-Phase-110 behavior preserved when `legibility_adapter=None`.

## What Was Built

### Task 1: LegibilityRewardAdapter (`src/kicad_agent/training/legibility_reward_adapter.py`)

Frozen dataclass bridging Plan 01 reward module + Phase 109 CritiqueResult + D-04 caps + D-03 multi-objective combine. Key invariants:

- **CR-110-01 closed**: `compute_legibility(critique, cap_inputs)` consumes `CritiqueResult.factors_view()` directly (MappingProxyType) — no dict shape conversion.
- **CR-110-04 closed**: Caps consume `CapInputs` value object — no loose float parameters.
- **HI-110-05 closed**: `completeness_source` is explicit (`"none"` default, `"layout_result"`, `"fixed_value"`). When `"none"` (or when completeness is None), the completeness weight folds into correctness so v1 trains as `0.8*correctness + 0.2*legibility`.
- **LO-110-11 closed**: `compute_legibility` catches `KeyError` / `ValueError` from `LegibilityReward.score()` (malformed factors) and returns `0.0` with a logged warning. Training never crashes on a single bad critique.

`RewardWeights` dataclass validates `sum=1.0 ± 1e-6` (training stability guard). `from_config(config)` parses the `.planning/config.json` training block.

### Task 2: GRPO extension + config block

`AdvantageWeightedTrainer.__init__` accepts `legibility_adapter: Any = None` (backward compat — None preserves pre-Phase-110 behavior). Two registries initialized:

- `_critique_registry: dict[int, tuple[CritiqueResult, CapInputs]]` — CR-110-03 architecture (separate post-rollout step keyed by `sample_id`, NOT an attribute on `MazeSample`).
- `_layout_result_registry: dict[int, Any]` — populated by future Plan 05 training script when LayoutResult is available per sample (HI-110-05 completeness source).

`compute_group_rewards()` extended:
- Adapter=None → pre-Phase-110 behavior (correctness only)
- Adapter + critique registered → 3-term `combine()` with per-step `reward_decomposition` INFO log
- Adapter + no critique registered → reward collapses to correctness (logged at debug)

`_resolve_completeness(sample)` implements HI-110-05 source-gated completeness: `"none"` returns None (combine folds weight), `"fixed_value"` returns the configured constant, `"layout_result"` returns `len(layout.positions) / expected_count` if a layout is registered.

`.planning/config.json` gains a `training` block:
```json
{
  "training": {
    "reward_weights": {"correctness": 0.40, "completeness": 0.40, "legibility": 0.20},
    "completeness_source": "none",
    "legibility_factor_weights": {"density": 0.25, "clarity": 0.25, "spacing": 0.25, "organization": 0.25},
    "anti_hack": {"compactness_threshold_ratio": 2.0, "crossings_floor_min": 1, "crossings_floor_multiplier": 0.3, "alignment_jitter_mm": 0.1}
  }
}
```

## Test Results

- `test_legibility_reward_adapter.py`: 14/14 pass (caps composition, combine math, from_config, LO-110-11 malformed critique robustness, frozen check)
- `test_grpo_legibility_integration.py`: 12/12 pass (trainer param, backward compat, multi-objective combine, sample_id lookup, HI-110-05 fold, LO-110-11 in loop, registry helpers, config.json shape)
- **Regression check**: 47/47 existing GRPO tests still pass (no regressions — backward compat confirmed via `legibility_adapter=None` default)

**Total: 26 new + 47 existing = 73 tests pass.**

## Commits

- `2a98e396`: `feat(110-04): wire legibility reward into GRPO loop (D-03 multi-objective)`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] MagicMock reward_model broke predict_reward path**
- **Found during:** Task 2 implementation
- **Issue:** Integration tests used `MagicMock()` for `reward_model`. PyTorch is installed locally, so `predict_reward` calls `model._tokenizer.encode(chain_text)` which returns a MagicMock that can't unpack into `(token_ids, attention_mask)`. Tests crashed before reaching the new adapter code.
- **Fix:** Added `_patch_predict_reward(monkeypatch, ...)` helper that patches `kicad_agent.training.reward_model.predict_reward` to return a deterministic `PredictedReward`. Tests now exercise the new adapter wiring without depending on torch behavior.
- **Files modified:** `tests/test_grpo_legibility_integration.py`
- **Commit:** `2a98e396`

**2. [Rule 3 - Blocking] Frozen dataclass instance can't be patched in-place**
- **Found during:** Task 2 implementation
- **Issue:** Test 7 (`test_critique_registry_lookup_by_sample_id`) tried to spy on `adapter.compute_legibility` by assigning a MagicMock to the attribute — failed with `FrozenInstanceError`.
- **Fix:** Patch the **class** method via `monkeypatch.setattr(LegibilityRewardAdapter, "compute_legibility", _counting_compute)` instead of the instance. The counting wrapper calls through to the original implementation and records the call count.
- **Files modified:** `tests/test_grpo_legibility_integration.py`
- **Commit:** `2a98e396`

## Self-Check: PASSED

- `src/kicad_agent/training/legibility_reward_adapter.py` exists
- `tests/test_legibility_reward_adapter.py` exists
- `tests/test_grpo_legibility_integration.py` exists
- `src/kicad_agent/training/grpo.py` modified (extended __init__ + compute_group_rewards + register_critique)
- `.planning/config.json` modified (training block added)
- Commit `2a98e396` present in git log
- All 26 new + 47 existing tests pass
- CR-110-03 closed: `grep -n "hasattr" src/kicad_agent/training/grpo.py | grep critique` returns 0 matches
- HI-110-05 closed: `grep -n "completeness_source" src/kicad_agent/training/grpo.py` returns matches
- LO-110-11 closed: `grep -n "reward_decomposition" src/kicad_agent/training/grpo.py` returns the INFO log
