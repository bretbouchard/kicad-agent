---
phase: 110-grpo-legibility-reward-signal
plan: 03
subsystem: training-data-grpo
tags: [grpo, data-builder, jitter, phase-110, data-pipeline]
dependency_graph:
  requires:
    - "Plan 01 reward module (AlignmentJitter)"
    - "parse_schematic / SchematicIR / SchematicSpatialExtractor / SchematicReadabilityScorer (verified chain)"
    - "SchematicRawWriter.move_symbol (Phase 101/102 hardening)"
    - "atomic_write (io/atomic_write.py)"
  provides:
    - "GRPODataBuilder — perturb + score + emit reward deltas"
    - "scripts/generate_grpo_variations.py CLI — corpus walk + JSONL emit"
    - "JSONL row format consumed by Phase 110 Plan 04 training loop"
  affects: []
tech_stack:
  added: []
  patterns:
    - "frozen dataclass with __post_init__ mkdir (mutable output_dir creation)"
    - "verified SRS chain (CR-110-02 / HI-110-06 fix)"
    - "Phase 63 H-12 deterministic seeding (_SEED_SPACING=1_000_000 inlined per HI-110-07)"
    - "ref regex filter for instantiated components only (R?, U? placeholders rejected)"
key_files:
  created:
    - "src/kicad_agent/training/grpo_data_builder.py"
    - "scripts/generate_grpo_variations.py"
    - "tests/test_grpo_data_builder.py"
  modified: []
decisions:
  - "Verified SRS chain used (NOT score_file(path) shorthand)"
  - "Phase 63 H-12 _SEED_SPACING=1_000_000 inlined per HI-110-07"
  - "Uninstantiated refs (R?, U?) filtered — raw writer refuses ambiguous matches"
  - "SchematicRawWriter used (NOT kiutils.to_file — corrupts KiCad 10 files)"
  - "atomic_write for variation files (fsync + rename)"
metrics:
  duration: "1 commit"
  tasks_completed: 2
  files_touched: 3
  completed_date: "2026-07-04"
---

# Phase 110 Plan 03: GRPO Data Builder Summary

Synthetic GRPO exploration data: takes base schematics, generates N perturbed variations per base via D-04 alignment jitter, scores each via the verified SRS chain, emits reward deltas for the per-step advantage signal that GRPO trains on.

## What Was Built

### Task 1: GRPODataBuilder (`src/kicad_agent/training/grpo_data_builder.py`)

Frozen dataclass with the verified SRS chain. `perturb_schematic()` reads raw bytes, parses to extract components, filters to instantiated refs only (`R?`/`U?` placeholders rejected — raw writer refuses ambiguous matches), applies jitter via `SchematicRawWriter.apply_mutation` with `move_symbol` op (Phase 101/102 hardening — never `kiutils.to_file`), writes atomically to `output_dir / "{stem}_var_{seed}.kicad_sch"`.

`score_variation()` runs `_score_schematic()` on both base and variation, returns `{base_srs, variation_srs, reward_delta}`. Each `*_srs` dict has 5 keys (density/clarity/spacing/organization + overall_srs sourced from `report.srs`).

`build_exploration_rows()` generates N variations with Phase 63 H-12/H-13 deterministic seeding (`_SEED_SPACING = 1_000_000` inlined per HI-110-07): `var_seed = seed + i * _SEED_SPACING` for i in range(n_variations). Each row includes `base_path`, `variation_path`, `variation_id`, `base_srs`, `variation_srs`, `reward_delta`, `perturbation_summary` (n_components_moved, mean_displacement_mm), and `seed`.

### Task 2: `scripts/generate_grpo_variations.py` CLI

```
python3 scripts/generate_grpo_variations.py \
    --corpus-dir /Volumes/Storage/models/kicad-agent/corpus/ \
    --output /Volumes/Storage/models/kicad-agent/datasets/grpo/exploration.jsonl \
    --n-variations 8 --seed 42 [--limit N] [--jitter-mm 0.1]
```

Per-base try/except `GRPODataBuilderError` — one bad base (no instantiated refs, parse error, etc.) doesn't abort the full run. Exit codes: 0 success, 1 no variations generated, 2 `/Volumes/Storage` unmounted.

## Test Results

- `test_grpo_data_builder.py`: 11/11 pass (including 7 integration tests on Arduino_Mega fixture)
- Smoke test: 1 base × 3 variations → 3 JSONL rows, all `reward_delta` in `[-1, 1]`

**Total: 11 unit + 1 smoke pass.**

## Commits

- `11217647`: `feat(110-03): GRPO data builder + CLI for variation exploration`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Filter uninstantiated component refs (R?, U?)**
- **Found during:** Task 1 implementation
- **Issue:** Arduino_Mega fixture has 129 components with `Reference='R?'` (uninstantiated KiCad placeholders). `_move_symbol_by_ref` raises `ValueError: Ambiguous move_symbol: 129 symbol blocks share Reference 'R?'` because the raw writer (correctly) refuses to guess which placeholder to move.
- **Fix:** Added `_INSTANTIATED_REF_RE = re.compile(r"^[A-Z]+[0-9]+\Z")` and filtered `perturbable` list before applying mutations. If no instantiated refs exist, raise `GRPODataBuilderError("no instantiated component refs to perturb")`. Real-world schematics in the corpus have instantiated refs; the Arduino_Mega fixture's `R?` symbols are library placeholders that don't represent a real layout.
- **Files modified:** `src/kicad_agent/training/grpo_data_builder.py`
- **Commit:** `11217647`

**2. [Rule 3 - Blocking] atomic_write doesn't mkdir parents**
- **Found during:** Task 1 implementation
- **Issue:** Tests passed `output_dir=tmp_path/"custom"` (non-existent), but `atomic_write` uses `tempfile.mkstemp(dir=file_path.parent)` which raises `FileNotFoundError` if parent doesn't exist.
- **Fix:** Added `__post_init__` that calls `self.output_dir.mkdir(parents=True, exist_ok=True)`. Documented exception to Phase 100 CR-01 (mutable state init in post_init is acceptable since the dataclass fields themselves remain immutable after construction).
- **Files modified:** `src/kicad_agent/training/grpo_data_builder.py`
- **Commit:** `11217647`

## Self-Check: PASSED

- `src/kicad_agent/training/grpo_data_builder.py` exists
- `scripts/generate_grpo_variations.py` exists
- `tests/test_grpo_data_builder.py` exists
- Commit `11217647` present in git log
- All 11 tests + 1 smoke pass
- `_SEED_SPACING = 1_000_000` inlined per HI-110-07: `grep -n "_SEED_SPACING" src/kicad_agent/training/grpo_data_builder.py` returns the constant
