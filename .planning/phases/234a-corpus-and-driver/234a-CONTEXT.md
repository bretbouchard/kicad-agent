# Phase 234: 1000-Schematic Swift ERC Batch Test - Context

**Gathered:** 2026-07-14
**Status:** Ready for planning
**Source:** v11.0 Roadmap (Phase 230-236) — auto-derived

<domain>
## Phase Boundary

Validate the Swift `NativeERC.run()` engine against Python `native_erc` on a statistically
meaningful sample of real KiCad schematics, generate a parity report, and fix any
discrepancies surfaced. Phase 218 shipped the Swift engine and tested it on 50 boards
(100% pass); Phase 234 scales that to 1000 and produces an explicit FP/FN report.

In scope:
- Running `NativeERC.run()` on 1000 schematics
- Running Python `native_erc` on the same 1000 schematics
- Generating a parity report (pass rate, FP count, FN count, agreement rate)
- Fixing the most common FP/FN root causes surfaced by the comparison
- Test harness that can be re-run as the Swift engine evolves

Out of scope (handled by other phases):
- Swift DRC parity (Phase 218 already covered 50 boards; this phase focuses on ERC)
- Vision input (Phase 236)
- New ERC check types (Phase 218 already shipped the 4-check engine)
- Python engine fixes (Python is the reference, not the target)

</domain>

<decisions>
## Implementation Decisions

### Corpus selection
- 1000 schematics sampled from the 28K KiCad corpus (referenced by Phase 218)
- Stratified sample preferred: same proportion of pass/fail/input/mixed as the 50-board
  batch used by Phase 218 to keep the parity signal meaningful
- Sampling reproducible: fixed RNG seed so re-runs compare apples-to-apples

### Reference truth
- Python `native_erc` is the reference (not ground truth — it's already what
  Phase 218 was validated against)
- Goal is parity (Swift matches Python) not perfection — both engines may miss
  the same bugs and that's fine
- `kicad-cli` ERC remains a tertiary sanity check on a small subset (e.g. 50)

### Parity report
- Per-check breakdown: which of the 4 ERC checks diverged
  (checkPinTypeConflicts, checkPowerNets, checkNoConnects, checkDanglingWires)
- Per-schematic record: schematic path, Python result, Swift result, agreement bool
- Top-N disagreement patterns listed with example schematic paths
- Report format: Markdown summary + raw JSON for programmatic use
- Report written to `.planning/phases/234-1000-schematic-swift-erc-batch-test/PARITY-REPORT.md`
  (committed) so the result is visible across sessions

### "Fix" scope
- Only fix root causes that affect ≥5 schematics (single-schematic drift = noise)
- Document fixes in SUMMARY.md
- Re-run after fix and confirm parity improves
- Cap fix loop at 2 iterations to avoid endless engineering

### Claude's Discretion
- Exact sampling algorithm (stratified, random, or first-1000-after-seed)
- Report layout and tooling (Swift test harness vs Python driver vs both)
- How to organize the 1000 schematics in the local file system
  (copy? symlink? pre-staged list?)
- Tolerance for known edge cases (empty schematics, missing power flags, etc.)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Swift ERC engine
- `macos-app/Sources/KiCadAgent/Validation/NativeERC.swift` — the 4-check engine being tested
- `macos-app/Sources/KiCadAgent/Views/ValidationPanel.swift:35-37` — Phase 231 wiring (calls `NativeERC.run()`)

### Python reference
- `daemon/kicad_daemon/handlers/erc_handler.py` (or equivalent) — Python `native_erc` reference impl
- `daemon/tests/test_native_erc.py` — existing Python ERC tests, useful as fixture format

### Corpus & prior test
- `.planning/phases/218-native-erc-drc-engine/218-01-SUMMARY.md` — the 50-board pass
- `data/erc_corpus/` or similar — the 28K schematic corpus referenced by Phase 218

### Test infrastructure
- `macos-app/Tests/KiCadAgentTests/` — existing Swift test patterns
- `daemon/tests/` — existing Python test patterns

</canonical_refs>

<specifics>
## Specific Ideas

- Phase 218 already proved 50/50 pass against kicad-cli ground truth. Phase 234 is
  the "scale it" milestone — same engine, more data, more rigor
- The 28K corpus is referenced multiple times in Phase 218 docs; check
  `data/erc_corpus/` or `corpus/` directories for the actual location
- Swift `NativeERC.run(schematicURL:)` is a synchronous function — easy to call from
  a CLI driver or XCTest. The 1000-run batch is the work, not the wiring
- Parity report should be a useful artifact for shipping confidence:
  "NativeERC verified at 99.X% parity on 1000-schematic sample"
- This phase is the deliverable for Swift ERC being App Store ready

</specifics>

<deferred>
## Deferred Ideas

- DRC parity at 1000 (Phase 218 already did DRC at 50; would be Phase 234-DRC if needed)
- Multi-engine comparison (Apple Foundation Models, MLX) — out of scope, not a parity question
- Netlist-level parity (deeper than ERC) — out of scope
- New ERC check types — Phase 218 fixed the check set; not adding more

---

*Phase: 234-1000-schematic-swift-erc-batch-test*
*Context gathered: 2026-07-14 via v11.0 roadmap extraction*
