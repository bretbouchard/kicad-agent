---
phase: 110-grpo-legibility-reward-signal
plan: 02
subsystem: training-data-sft
tags: [sft, labeller, srs, phase-110, data-pipeline]
dependency_graph:
  requires:
    - "parse_schematic (parser/schematic_parser.py)"
    - "SchematicIR (_parse_result= keyword construction)"
    - "SchematicSpatialExtractor (analysis/schematic_spatial.py)"
    - "SchematicReadabilityScorer (analysis/readability_scorer.py)"
    - "ReadabilityReport.srs / .factors (Phase 48.5 verified chain)"
    - "atomic_write (io/atomic_write.py)"
  provides:
    - "SFTLabeller — verified-chain SRS scoring for crawled .kicad_sch"
    - "scripts/score_sft_dataset.py CLI — corpus walk + JSONL emit"
    - "JSONL row format consumed by Phase 97 SFT trainer"
  affects: []
tech_stack:
  added: []
  patterns:
    - "frozen dataclass with mutable accumulator field (Phase 100 CR-01 exception)"
    - "verified 4-step SRS chain (CR-110-02 fix)"
    - "atomic_write for JSONL output (fsync + rename)"
    - "explicit exit codes (0 success, 1 no data, 2 storage unmounted)"
key_files:
  created:
    - "src/kicad_agent/training/sft_labeller.py"
    - "scripts/score_sft_dataset.py"
    - "tests/test_sft_labeller.py"
  modified: []
decisions:
  - "Verified SRS chain: parse_schematic -> SchematicIR -> SchematicSpatialExtractor -> Scorer (not score_file(path) shorthand)"
  - "overall_srs sourced from ReadabilityReport.srs (NOT factors['overall'] — that key does not exist)"
  - "max_file_mb=50 guard skips oversized files BEFORE parsing (ME-110-10 mitigation)"
  - "LabellerStats as mutable holder passed by reference (CR-01 documented exception)"
metrics:
  duration: "1 commit"
  tasks_completed: 2
  files_touched: 3
  completed_date: "2026-07-04"
---

# Phase 110 Plan 02: SFT Labeller Summary

Real-schematic SFT data path: walks a KiCad corpus, scores each `.kicad_sch` via the verified Phase 48.5 SRS chain, emits JSONL training labels for the Phase 97 SFT trainer.

## What Was Built

### Task 1: SFTLabeller (`src/kicad_agent/training/sft_labeller.py`)

Frozen dataclass with the verified 4-step SRS chain (CR-110-02 fix):

```
parse_schematic(path) -> ParseResult
SchematicIR(_parse_result=parse_result) -> ir
SchematicSpatialExtractor(ir) -> extractor
SchematicReadabilityScorer(extractor).score() -> ReadabilityReport
```

`score_file()` returns a 6-key dict: `density`, `clarity`, `spacing`, `organization`, `overall_srs` (sourced from `report.srs`, NOT `factors["overall"]` — that key does not exist), and `element_count`.

`label_corpus()` catches `SFTLabellerError` per-file, logs the skip, and continues. Custom `SFTLabellerError` wraps all non-FileNotFound failures (no kiutils exception leak across the trust boundary). `LabellerStats` is a mutable holder passed by reference (documented CR-01 exception for accumulators).

`max_file_mb=50` guard (ME-110-10) skips oversized files BEFORE parsing, preventing kiutils OOM on pathological S-expressions.

### Task 2: `scripts/score_sft_dataset.py` CLI

```
python3 scripts/score_sft_dataset.py \
    --corpus-dir /Volumes/Storage/models/kicad-agent/corpus/ \
    --output /Volumes/Storage/models/kicad-agent/datasets/sft/srs_labels.jsonl \
    [--limit N] [--source-tag kicad-crawler] [--max-file-mb 50]
```

Exit codes: 0 success, 1 no schematics scored (wrong corpus dir or all-failed), 2 `/Volumes/Storage` unmounted. Output written atomically via `atomic_write` (parent dirs created). Stats printed to stderr.

## Test Results

- `test_sft_labeller.py`: 10/10 pass (including 3 integration tests on Arduino_Mega fixture)
- Smoke test: `score_sft_dataset.py --corpus-dir tests/fixtures/Arduino_Mega --output /tmp/sft_smoke.jsonl --limit 5` → exit 0, 1 JSONL row, valid JSON

**Total: 10 unit + 1 smoke pass.**

## Commits

- `afaac29d`: `feat(110-02): SFT labeller + CLI for SRS scoring of crawled schematics`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrupt fixture had to use unbalanced paren**
- **Found during:** Task 1 implementation
- **Issue:** Test 3's corrupt fixture used `(kicad_sch NOT VALID KICAD SEXPR {{{)` but kiutils parsed it leniently as an empty schematic — no exception raised. Tests 3 and 5 failed.
- **Fix:** Changed fixture to `(kicad_sch (unbalanced` (unbalanced paren) which forces kiutils to raise `ParseError`. Test now reliably exercises the corrupt-input path.
- **Files modified:** `tests/test_sft_labeller.py`
- **Commit:** `afaac29d`

**2. [Rule 3 - Blocking] macOS resolves /tmp to /private/tmp**
- **Found during:** Task 1 implementation
- **Issue:** Test 4 asserted `parsed["input_path"] == "/tmp/test.kicad_sch"` but macOS `Path.resolve()` returns `/private/tmp/test.kicad_sch` (symlink expansion).
- **Fix:** Test uses `tmp_path` fixture (already resolved path) and asserts against `str(sch_path.resolve())` instead of a hardcoded string.
- **Files modified:** `tests/test_sft_labeller.py`
- **Commit:** `afaac29d`

## Self-Check: PASSED

- `src/kicad_agent/training/sft_labeller.py` exists
- `scripts/score_sft_dataset.py` exists
- `tests/test_sft_labeller.py` exists
- Commit `afaac29d` present in git log
- All 10 tests + 1 smoke pass
