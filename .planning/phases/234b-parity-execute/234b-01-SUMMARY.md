---
phase: 234b
type: summary
status: complete
---

# Phase 234B Summary — Swift ERC CLI + Parity Report

## Status: COMPLETE

- **Swift CLI harness built** at `.planning/phases/234b-parity-execute/erc-cli` (200KB, 22s to compile)
- **Parity driver wired** with both Python (`run_native_erc`) and Swift (subprocess to erc-cli) engines
- **Full 81-schematic parity run** completed
- **Report written** at `234b-01-PARITY-REPORT.md`
- **Latent bug found and fixed** in `batch_erc_parity.py` (Python `passed` key normalization)

## Key Numbers

| Metric | Value |
|--------|-------|
| Corpus size | 81 schematics (dedup from 212) |
| Run time | 22 seconds |
| Agreed (passed + error_count match) | 49/81 (60%) |
| Error count match | 49/81 (60%) |
| Warning count match | 63/81 (78%) |
| Both passed | 49/81 (60%) |

## Deliverables

| File | Purpose |
|------|---------|
| `macos-app/Sources/erc-cli/main.swift` | CLI source (100 lines) |
| `.planning/phases/234b-parity-execute/erc-cli` | Compiled binary |
| `.planning/phases/234b-parity-execute/scripts/build_erc_cli.sh` | Rebuild script |
| `.planning/phases/234b-parity-execute/parity-results.json` | Full 81-schematic run |
| `.planning/phases/234b-parity-execute/234b-01-PARITY-REPORT.md` | Detailed analysis |
| `.planning/phases/234a-corpus-and-driver/scripts/batch_erc_parity.py` | Updated with Swift wire-up |

## Top Disagreement Findings

1. **Classification philosophy**: Both engines implement the same 4 checks, but classify
   the same condition under different check-ids (e.g., unconnected power pin is
   `ERC_PIN_CONFLICT` warning in Python, `ERC_UNCONNECTED_PIN` error in Swift). 24/32
   disagreements are this category.

2. **Python parser gap** (6 cases): Python fails to resolve pins for chips with >20
   pins (x64-smart-grid, astable_555, and 4 other synthetic fixtures). Swift catches
   these correctly.

3. **Swift parser gap** (2 cases): Swift misses 1 pin conflict each in 2 op-amp
   schematics where Python catches it. Likely a label-position resolution edge case.

## Bug Found

`batch_erc_parity.py:74` was reading `raw.get("passed", False)` but the Python
`NativeErcResult.to_dict()` emits key `"clean"`, not `"passed"`. Result: 100% of
schematics had `passed=False` in the normalized output, masking real signal.

Fix: accept both keys (`raw.get("passed", raw.get("clean", False))`).

After fix: agreement rate went from 0% → 60%, exposing the real 32-schematic
disagreement set.

## What's Next (234C, proposed)

Fix the 8 real parser gaps surfaced by parity:
- 6 Python cases: pin resolution for >20-pin ICs
- 2 Swift cases: label-position resolution for op-amp configs

After fix, re-run parity — target 90%+ agreement.
