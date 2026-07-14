---
phase: 234
review_type: plan
status: APPROVE-WITH-FINDINGS
review_date: 2026-07-14
reviewers: [Rick Sanchez, Rick C-137, Rick Prime, Rickfucius, Slick Rick, Apple Elitist Rick]
findings_count: 12
---

# Council of Ricks Plan Review — Phase 234: 1000-Schematic Swift ERC Batch Test

## Executive Summary

**Verdict: APPROVE-WITH-FINDINGS** (not REJECT)

The plan attempts an ambitious scope (1000-schematic parity test) that exceeds available corpus resources and has 8 tasks exceeding the 5-task threshold. However, the core technical approach is sound and well-researched. The plan should be **split into 2 phases** to manage scope: Phase 234A (corpus acquisition + driver implementation) and Phase 234B (full execution + verification).

---

## Issue Breakdown

### CRITICAL Findings (2)

#### CRIT-01: Corpus Resource Mismatch — 107 Local vs 1000 Required
- **Location**: PLAN.md:83, RESEARCH.md:140-157
- **Problem**: Plan requires 1000 schematics from a "28K corpus", but only ~107 .kicad_sch files exist locally. CorpusCurator downloads from GitHub, but:
  1. Downloads 50+ projects (avg 2-3 schematics each = ~150 schematics)
  2. Quality gates filter for >=5 components, >=3 nets
  3. No plan to scale from 150 to 1000
- **Evidence**: `find . -name "*.kicad_sch" | wc -l` returns 107
- **Impact**: Phase cannot start without corpus expansion strategy
- **Resolution**: ADDED-AS-PHASE — add corpus expansion task to Phase 234

#### CRIT-02: Task Volume Exceeds Threshold (8 > 5)
- **Location**: PLAN.md
- **Problem**: Plan contains 8 tasks exceeding the 5-task maximum per plan
- **Evidence**: 234-01-01 through 234-01-08
- **Impact**: Plan too large for single execution phase
- **Resolution**: SUPERSEDED-BY-ALTERNATIVE — split into Phase 234A and Phase 234B

### HIGH Findings (4)

#### HIGH-01: Task ID Inconsistency Between Documents
- **Location**: PLAN.md vs VALIDATION.md
- **Problem**: PLAN.md has 8 tasks (234-01-01 to 234-01-08), VALIDATION.md references 7 tasks (234-01 to 234-07), plus references test_corpus_staging.py not in PLAN.md
- **Evidence**: VALIDATION.md:41-47 table vs PLAN.md:83-299 task definitions
- **Impact**: Cannot verify requirements coverage
- **Resolution**: ADDED-AS-PHASE — reconcile task IDs in both documents

#### HIGH-02: Missing REQ-08 in Frontmatter Requirements
- **Location**: PLAN.md:14-21
- **Problem**: Frontmatter requirements list ends at REQ-06, but CONTEXT.md:308 and PLAN.md:312 reference REQ-08 (Fix cap at 2 iterations)
- **Evidence**: REQ-08 defined in PLAN.md:312 but not in `<requirements>` frontmatter
- **Resolution**: ADDED-AS-PHASE — add REQ-08 to frontmatter

#### HIGH-03: Swift Invocation Not Explicit in Task 234-01-06
- **Location**: PLAN.md:219-242
- **Problem**: Task 234-01-06 "Implement Fixes and Re-run" mentions Python but not explicit Swift invocation via subprocess
- **Evidence**: No `--engine swift` flag or Swift callable mentioned
- **Resolution**: ADDED-AS-PHASE — add explicit Swift invocation method

#### HIGH-04: Corpus Download Reliability Not Addressed
- **Location**: PLAN.md:83-104
- **Problem**: CorpusCurator downloads via git clone with 120s timeout, 50MB max. No retry or fallback strategy documented
- **Evidence**: corpus_curator.py:342-350
- **Impact**: Network failures could block entire phase
- **Resolution**: ADDED-AS-PHASE — add corpus staging verification task

### MEDIUM Findings (4)

#### MED-01: Missing <read> Wrappers in <files> Elements
- **Location**: PLAN.md:89, 112, 144, 171, 201, 225, 254, 281
- **Problem**: XML-style <files> elements lack proper structure with <read>/<write> wrappers
- **Evidence**: `<files><create>path</create></files>` pattern
- **Resolution**: ADDED-AS-PHASE — format files elements per specification

#### MED-02: Missing <automated> Commands in <verify> Elements
- **Location**: PLAN.md:99-102, 127-130, 158-161, 184-187, 212-215, 237-240, 269-272, 292-295
- **Problem**: Verification blocks lack `<automated>` wrapper elements
- **Evidence**: `<verify>command</verify>` should be `<verify><automated>command</automated></verify>`
- **Resolution**: ADDED-AS-PHASE — add automated wrappers

#### MED-03: VALIDATION.md References Non-Existent test file
- **Location**: VALIDATION.md:55, 148
- **Problem**: References `scripts/test_corpus_staging.py` and `tests/test_swift_erc_run.py` not created in PLAN.md
- **Evidence**: Missing from PLAN.md:89-115 files list
- **Resolution**: ADDED-AS-PHASE — add missing test files to plan

#### MED-04: Fix Loop Complexity Not Justified
- **Location**: PLAN.md:228-235
- **Problem**: Fix loop assumes Swift/Python discrepancies are structural (pin resolution, position rounding) but 2 iterations may not suffice for 1000 schematics
- **Evidence**: CONTEXT.md:219-220 mentions "Common fixes: position rounding tolerance, pin type alias handling, net name normalization"
- **Resolution**: ADDED-AS-PHASE — add iteration tracking with early termination if improvement < threshold

### LOW Findings (2)

#### LOW-01: must_haves Has 6 Items (Target 3-5)
- **Location**: PLAN.md:21-28
- **Problem**: must_haves section has 6 truths but guideline says 3-5
- **Evidence**: 6 items: acquire, Python run, Swift run, parity report, FP/FN rates, top-N patterns
- **Resolution**: ADDED-AS-PHASE — consolidate or split

#### LOW-02: Dependencies Field Empty
- **Location**: PLAN.md:6
- **Problem**: `depends_on: []` is empty but Phase 234 depends on Phase 218 (native engine) and Phase 231 (Swift ERC wired)
- **Evidence**: CONTEXT.md:218-219, ROADMAP.md:266-267
- **Resolution**: ADDED-AS-PHASE — populate dependencies field

---

## Code Quality Assessment (Rick Sanchez)

**Status**: VERIFIED

### Strengths
- Clean separation of concerns: corpus acquisition, driver implementation, execution, reporting, verification
- Good use of existing patterns from Phase 218 (50-board test)
- Parallel execution with ProcessPoolExecutor is appropriate
- Error handling for parse failures, timeouts included

### Concerns
- Task 234-01-05 FIX-PLAN.md creation is vague — needs concrete format
- No progress checkpointing for resumption after failure
- Swift invocation via `subprocess.run(["xcrun", "swift", ...])` not documented

---

## Security Assessment (Rick C-137)

**Status**: VERIFIED

### Threat Model Applied
- T-53-02: SHA256 checksums in manifest (PLAN.md:92)
- T-53-05: MAX_DOWNLOAD_SIZE=50MB in CorpusCurator (corpus_curator.py:320)
- T-53-06: Domain validation for github.com/hackaday.io only

### No Issues Detected
- No hardcoded secrets
- File paths validated via Path objects
- Timeouts enforced in subprocess calls

---

## SLC Compliance (Slick Rick)

**Status**: CONDITIONAL PASS — plan-scoped

### Simple: PARTIAL
- Corpus acquisition is opaque (downloads from GitHub)
- No clear documentation for running the 1000-schematic batch

### Lovable: N/A
- Not a user-facing feature

### Complete: NOT COMPLETE
- Corpus acquisition method is underspecified
- Swift invocation mechanism not fully defined
- No fallback for GitHub unavailability

---

## Design Assessment (Rick Prime)

**Status**: VERIFIED with Concerns

### Architecture
- Good pipeline: Corpus -> Python Driver -> Swift Execution -> Comparison -> Report
- Nyquist-compliant validation strategy (Phase 218 proved ground truth)
- Report as artifact for audit trail is correct

### Concerns
- Phase 234 tries to do too much in one wave
- Should be split: 234A (150 schematics proof), 234B (scale to 1000)

---

## Historical Context (Rickfucius)

**Pattern Match**: Phase 218 used exact same pattern (50-board test) with 100% pass. CorpusCurator has 50+ default sources.

**Past Mistake to Avoid**: Phase 218 used `data/erc_corpus/` which was 50 schematics. Do not assume 28K exists locally.

**Recommended Approach**:
1. First run CorpusCurator with existing 50 sources
2. Verify at least 150 schematics pass quality gates
3. If needed, add more sources from corpus_curator.py default_sources()

---

## Apple Platform Assessment (Apple Elitist Rick)

**Status**: VERIFIED

### No Deprecated APIs Used
- Current Swift code uses modern patterns
- No GCGamepad (deprecated iOS 10.0)
- No OpenGL ES
- No UIWebView

### Swift 6 Concurrency
- NativeERC.run() is synchronous — appropriate for batch processing
- No @MainActor violations evident

---

## Recommendations

### Immediate Actions (ADDED-AS-PHASE)

1. **Split plan into 2 phases**: 
   - Phase 234A: Corpus acquisition (target 150 schematics) + driver implementation
   - Phase 234B: Full execution (scale to 1000 if corpus available) + fixes

2. **Reconcile task IDs**: Ensure PLAN.md and VALIDATION.md have matching task references

3. **Add missing files**: Create `scripts/test_corpus_staging.py` and verify test files exist

4. **Explicit Swift invocation**: Document exact subprocess command for Swift engine

5. **Population dependencies**: Add Phase 218 and Phase 231 to `depends_on` field

6. **Format files elements**: Add <read>/<write> wrappers per XML schema

### Wave 0 Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| REQ-01 | ✅ Tracked | Wave 1 |
| REQ-02 | ✅ Tracked | Wave 1 |
| REQ-03 | ✅ Tracked | Wave 1 |
| REQ-04 | ✅ Tracked | Wave 1 |
| REQ-05 | ✅ Tracked | Wave 1 |
| REQ-06 | ✅ Tracked | Wave 1 |
| REQ-08 | ⚠️ Missing | Present in body, not frontmatter |

---

## Council Consensus

| Specialist | Recommendation |
|------------|---------------|
| Rick Sanchez (Code) | APPROVE-WITH-FINDINGS |
| Rick C-137 (Security) | VERIFIED — no issues |
| Rick Prime (Design) | APPROVE-WITH-FINDINGS |
| Rickfucius (Wisdom) | DEFER — verify corpus availability |
| Slick Rick (SLC) | CONDITIONAL — must fix corpus scoping |
| Apple Elitist Rick | VERIFIED — no deprecated APIs |

---

## Final Recommendation

**APPROVE-WITH-FINDINGS** — Split into Phase 234A and Phase 234B to manage scope. Address corpus acquisition uncertainty before proceeding. The technical approach is sound but the plan is over-scoped for a single execution phase.

**Resolution State Changes**:
- All CRITICAL findings → ADDED-AS-PHASE (new phased approach)
- All HIGH/MED/LOW findings → ADDED-AS-PHASE (documentation improvements)

---

*This review follows the Council of Ricks protocol. Evil Morty's final decision may supersede individual recommendations.*