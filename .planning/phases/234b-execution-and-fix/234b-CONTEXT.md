# Phase 234B: Parity Execution + Report + Fix - Context

**Gathered:** 2026-07-15
**Status:** Ready for execution (plan exists)
**Mode:** Auto-generated (autonomous mode, --auto flag set)

<domain>
## Phase Boundary

Execute the 1000-schematic Swift-ERC vs Python-native_ERC parity test
defined in `.planning/phases/234b-execution-and-fix/234b-01-PLAN.md`. Generate
`parity-results.json` and `PARITY-REPORT.md` with agreement rate, FP/FN
breakdown, and per-check stats. Fix any discrepancies affecting >=5
schematics.

Inputs from Phase 234A:
- `corpus/manifest.json` — 1000 schematic paths
- `scripts/batch_erc_parity.py` — parity driver

Outputs:
- `parity-results.json` — structured results
- `PARITY-REPORT.md` — pass rate, FP count, FN count, per-check breakdown

Success criteria:
- 1000 schematics tested with both engines
- Agreement rate >= 95% or drift reduced by 2 iterations
- Discrepancies affecting >=5 schematics identified and fixed
</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
- Use existing `scripts/batch_erc_parity.py` driver from Phase 234A without modification
- Read manifest from `.planning/phases/234a-corpus-and-driver/corpus/manifest.json`
- Run parity loop, collect results, write both `parity-results.json` and `PARITY-REPORT.md`
- If corpus isn't yet built (234A gap), flag and stop — no fabrication
- Fix only discrepancies affecting >=5 schematics (per must_haves)

### Locked (from project policy)
- All edits via kicad-agent operations, never raw file edits
- Beads tracking via `bd` for any issues found
- Run validation gates after fixes (kicad-cli ERC for sanity check)
</decisions>

<code_context>
## Existing Code Insights

- `scripts/batch_erc_parity.py` exists from Phase 234A (committed in `42797d3`)
- Swift ERC engine at `macos-app/Sources/KiCadAgent/Validation/` (Phase 218 native engine, 18 checks)
- Python ERC engine at `src/kicad_agent/validation/` (50 DFM checks + parity-tested native_erc)
- Phase 234B plan (`234b-01-PLAN.md`) defines exact files_modified and must_haves
- 212 Python daemon tests + 355 Swift tests currently green
</code_context>

<specifics>
## Specific Ideas

- Output parity-results.json must include: agreement_rate, fp_count, fn_count, per_check_breakdown
- PARITY-REPORT.md must include: pass rate, FP count, FN count, per-check breakdown, drift analysis
- Phase 234B PARITY-REPORT.md currently exists as placeholder (`status: PENDING`)
- Replace placeholder with actual results from parity run
</specifics>

<deferred>
## Deferred Ideas

- None — focused parity execution per Phase 234B scope
</deferred>