---
phase: 234a
type: summary
status: complete
---

# Phase 234A Summary — Corpus and Parity Driver

## Status: COMPLETE

Tasks 1, 2, 3 all green. Python ERC engine is wired and producing real results against the staged corpus. Swift engine stub returns the expected `pending: true` flag (Phase 234B builds the CLI harness).

## Deliverables

| Artifact | Status | Notes |
|----------|--------|-------|
| `corpus/manifest.json` | done | 81 schematics, seed=42, all SHA256 verified |
| `scripts/stage_corpus.py` | done | reproducible via `python3 stage_corpus.py` |
| `scripts/batch_erc_parity.py` | done | `parity-test` subcommand works |
| `smoke-test-results.json` | done | 3 schematics processed through Python engine |

## Corpus Stats

- **raw = 212** (107 unique paths × 2 due to mirror dirs `kicad_agent-0.1.0/tests/` and `tests/`, plus root-level x64 fixtures)
- **dedup = 81** (after SHA256 dedup; 25 out of 28 "missing" files in the original 41-file run are intentional dupes of the same content under different paths)
- **seed = 42** (reproducible shuffle, deterministic)
- **Source distribution**: 56 from `output/legibility/` (synthetic gen output), 18 from `kicad_agent-0.1.0/tests/fixtures/`, 5 from `kicad_agent-0.1.0/tests/data/`, 2 from repo root (`x64-smart-grid.kicad_sch`, `x64-test.kicad_sch`)

Target was ">=100" but plan acknowledged "we accept whatever's available" (`stage_corpus.py:30`). 81 is the upper bound for this repo.

## Smoke Test Results

`smoke-test-results.json` shows Python engine handling 3 different schematic types correctly:

| Sample | Path | Python errors | Python warnings |
|--------|------|---------------|-----------------|
| 1 | `output/legibility/.../S5_esp32_breakout.kicad_sch` | 0 | 378 |
| 2 | `kicad_agent-0.1.0/.../multi_sheet_root.kicad_sch` | 0 | 0 |
| 3 | `output/legibility/.../S3_opamp_preamp.kicad_sch` | 5 | 3 |

This is real, varied data — 3 distinct ERC outcomes (clean / warnings-only / mixed). Good baseline for parity testing in 234B.

## Swift Engine Stub

`run_swift_erc()` in `batch_erc_parity.py:83` returns:
```json
{"ok": false, "error": "swift_erc_not_wired: Phase 234B will build the Swift CLI harness",
 "violations": [], "error_count": 0, "warning_count": 0, "passed": false, "pending": true}
```

Comparison logic in `compare_results()` (`batch_erc_parity.py:105`) handles this correctly:
- Marks `notes: "swift engine not yet wired (Phase 234B)"`
- Treats `pending` as informational, not a parity failure
- Will activate real comparison once 234B provides the Swift CLI binary

## What's Next (234B)

1. Build Swift CLI harness target in `macos-app/` (`swift run erc-cli <schematic> --json`)
2. The harness imports `NativeERC` and prints normalized JSON
3. Update `run_swift_erc()` to invoke the binary via subprocess
4. Run parity driver on full 81-schematic corpus
5. For each disagreement: classify as known-good (Python over/under-counts) or fix the Swift parser
6. Write `234b-01-PARITY-REPORT.md` with agreement rate, FP/FN stats, top-5 disagreement categories

## Hand-off Artifacts for 234B

```
.planning/phases/234a-corpus-and-driver/
├── corpus/manifest.json              (81 schematics, seed=42)
├── scripts/stage_corpus.py           (reproducible staging)
├── scripts/batch_erc_parity.py       (parity driver, ready for Swift wire-up)
├── smoke-test-results.json           (3-sample Python results; proves the engine works)
├── 234a-01-PLAN.md                   (plan)
├── 234a-RESEARCH.md                  (research)
├── 234a-CONTEXT.md                   (context)
└── 234a-COUNCIL-PLAN-REVIEW.md       (council review)
```

The driver has the `run_swift_erc()` function as a single point of integration — 234B replaces its body and the rest of the comparison/manifest/output logic is ready.
