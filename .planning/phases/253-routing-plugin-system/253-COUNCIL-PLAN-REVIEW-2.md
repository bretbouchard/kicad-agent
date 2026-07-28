# Council of Ricks — Gate 1 Plan Review (Iteration 2)

**Phase:** 253 (Routing Plugin System)
**Plans reviewed:** Task 2 REDO (DSN port), Task 6 (Sandbox cleanup)
**Review date:** 2026-07-28
**Iteration:** 2 of 3 (per bureaucracy.md §7.5)
**Reviewers:** Rick Sanchez (code), Rick C-137 (security), Slick Rick (SLC), Evil Morty (synthesis), Rick Prime (design), Rickfucius (history)
**Verdict:** **APPROVE-WITH-MINOR-FIXES — execution unblocked after 2 small plan edits**

---

## Executive Summary

- **Prior findings (iteration 1):** 16 total (2 P0, 3 P1, 6 P2, 5 P3)
- **Resolved:** 15 of 16
- **Partial:** 1 of 16 (L-03 — grep incomplete)
- **New findings (iteration 2):** 2 (both MEDIUM/P2)
- **Verdict:** APPROVE-WITH-MINOR-FIXES — all P0/P1 findings from iteration 1 are fully resolved. Two new MEDIUM findings are small, specific plan-text edits that do not require re-review. Apply the fixes, then execute.

The author (Fizz) addressed every prior finding with specific, citable revisions. The sandbox-rule violations that blocked iteration 1 (C-01 `which`/PATH lookup, C-02 EasyEDA feature flag) are both eliminated. The SpecctraDSNReader/DSNConverter relationship is now clearly defined (one tokenizer, one semantic layer). Git LFS is set up before the binary commit. The commit strategy is split for independent revertability. Two new MEDIUM issues were introduced by the revisions — both are acceptance-grep gaps that can be fixed in under 5 minutes of plan editing.

---

## Per-Finding Verification Table

| # | Finding | Severity | Status | Citation |
|---|---------|----------|--------|----------|
| C-01 | `probeJava()` uses `which java` PATH lookup | P0 | **RESOLVED** | Task 6e (lines 127-168): New sub-task replaces `probeJava()` with `/usr/libexec/java_home` system framework call. New `JavaLocator.swift` (~80 LOC) + `JavaLocatorTests.swift` (~100 LOC). Acceptance grep: `grep -rn "/usr/bin/env.*which\|/usr/bin/which" macos-app/Sources/Volta/Routing/` returns 0 matches. JRE bundling (gold standard) explicitly deferred to future milestone in Out of Scope. |
| C-02 | EasyEDA feature flag keeps shell-out fallback | P0 | **RESOLVED** | Task 6b (lines 46-79): "Council C-02 — NO FEATURE FLAG, NO SHELL-OUT FALLBACK... The web API is the ONLY path. If it breaks, ship a fix. The shell-out path is deleted entirely. No fallback flag." Acceptance: `grep -rn "easyeda2kicad\|findEasyEda2Kicad\|pip install easyeda\|useWebAPI" macos-app/Sources/` returns 0 matches. Cumulative acceptance also verifies no `useWebAPI` flag and no shell-out `Process` in `EasyEdaProvider.swift`. |
| H-01 | DSNConverter.swift header comments reference Python pcbnew | P1 | **RESOLVED** | Task 2 D2 (lines 82-90): "DSNConverter.swift header cleanup (Council H-01)" section explicitly says: "Update header comments to reflect native Swift DSN pipeline — remove all references to Python pcbnew, kicad-cli, and shell-out as conversion mechanisms." Acceptance grep extended to include `kicad-cli\|kicad_cli` in addition to `pcbnew` patterns. Verified DSNConverter.swift lines 13-16 still contain the stale comments — the plan now explicitly calls out cleaning them. |
| H-02 | 57.7 MB binary in git without Git LFS | P1 | **RESOLVED** | Task 6c (lines 80-105): "Set up Git LFS first (Council H-02). Add `macos-app/Resources/freerouting.jar filter=lfs diff=lfs merge=lfs -text` to `.gitattributes` BEFORE the binary commit." Acceptance: `git lfs ls-files` shows LFS tracking, `.gitattributes` has LFS rule. The plan correctly notes that LFS must be set up BEFORE the commit — retroactive LFS migration doesn't shrink history. |
| H-03 | SpecctraDSNReader vs DSNConverter duplication risk | P1 | **RESOLVED** | Task 2 D2 (line 84): "Relationship (Council H-03): SpecctraDSNReader is the semantic interpreter on top of `DSNConverter`. The single tokenizer lives in `DSNConverter` (`tokenize()`, `findSection()`, `validateBalance()`). SpecctraDSNReader calls `DSNConverter.tokenize()` and `DSNConverter.findSection()` to parse the (wiring ...) section... One tokenizer, one semantic layer — no divergent parsing." This matches option (a) from iteration 1 — SpecctraDSNReader wraps DSNConverter. |
| M-01 | Test fixture provenance unclear | P2 | **RESOLVED** | Task 2 D5 (lines 201-206): "Test fixture provenance (Council M-01)" section added. Board fixture verified at `simple_2layer_led.kicad_pcb`. DSN snapshot fixtures to be ported from `fe68b91:tests/test_phase105_c02_dsn_wiring.py` as Swift string literals. Parity harness defined. No external fixtures (no JAR dependency in unit tests). |
| M-02 | 6a ValidationPanel replacement is vague | P2 | **RESOLVED** | Task 6a (line 35): "Functional delta assessment (Council M-02): kicad-cli DRC provided external Design Rule Check (clearance, trace width, via drill, etc.). NativeERC provides Electrical Rule Check (unconnected pins, power-pin shorts, etc.). These are complementary, not equivalent. The replacement badge text MUST be 'Native ERC only — DRC via KiCad app' (honest about scope gap)." Tooltip documents the gap. |
| M-03 | 6d conditional existence of batch_erc_parity.py | P2 | **RESOLVED** | Task 6d (line 113): "Definitive deletion (Council M-03): `batch_erc_parity.py` exists at `.planning/phases/234a-corpus-and-driver/scripts/batch_erc_parity.py` (verified). Delete it." Full-repo reference audit added: `grep -rln "batch_erc_parity" .` across CI configs, Makefiles, scripts, docs. |
| M-04 | 6b EasyEDA undocumented API risk | P2 | **RESOLVED** | Task 6b (lines 59-64): "Council M-04 — Schema validation" section. Four mitigations: (1) strict `Codable` decoding, (2) `EasyEdaError.responseSchemaMismatch(rawResponse:)` on decode failure, (3) debug-level response logging for 7 days post-launch, (4) `CIWeekly/easyeda_ping_test` for early breaking-change detection. |
| M-05 | Commit 3 (Task 2) combines too much surface area | P2 | **RESOLVED** | Task 2 commit strategy (lines 210-215): "Four commits (Council M-05: split original commit 3 into 3a + 3b for smaller blast radius)." Commit 3a: SegmentSplicer + splicer tests. Commit 3b: FreeroutingProvider wiring + dsnConversionUnavailable deletion. "Independently revertable (3a reverts the splicer; 3b reverts the wiring without touching the splicer)." |
| M-06 | Task 6 acceptance grep missing `which` pattern | P2 | **RESOLVED** | Task 6 cumulative acceptance (line 190): `grep -rn "/usr/bin/env.*which\|/usr/bin/which" macos-app/Sources/Volta/Routing/` returns 0 matches. The pattern correctly targets the specific PATH-lookup idiom, not bare `which` (which appears in comments/docs). |
| L-01 | R-4 (4+ layer stackup) deferral lacks tracking artifact | P3 | **RESOLVED** | Task 2 out of scope (line 247): "Tracking: Bead with labels `council-deferred,phase-253,deferred-to-task-2b` — created at execution time, with trigger condition '4-layer test fixture exists' and visibility in ROADMAP '## Deferred' section." Labels and trigger condition are specified per four-state taxonomy (DEFERRED-TO-NAMED-TARGET). Note: Bead creation is deferred to execution time — the bureaucracy hooks will enforce this. |
| L-02 | Task 6 dependency claim is incorrect | P3 | **RESOLVED** | Task 6 header (line 6): "Depends on: PROJECT.md sandbox rule (already shipped in `cf1fb3b`). Sub-tasks 6a (delete KiCadCLIDetector), 6b (EasyEda rewrite), and 6d (replace Python parity test) are independent of Task 2 and can execute in parallel with it. Only 6c's end-to-end smoke test depends on Task 2's native DSN pipeline (the code changes in 6c — bundling the JAR, updating `jarPath()` — are independent). Sub-task 6e (Java resolution) is independent." |
| L-03 | Task 6 cumulative grep missing `freerouting.jar` hardcoded path check | P3 | **PARTIAL** | Task 6 cumulative acceptance (line 191): `grep -rn "/Applications/Freerouting\|/opt/homebrew/Cellar/freerouting\|/Library/Application Support/freerouting" macos-app/Sources/` returns 0 matches. Verified against actual `defaultJARSearchPaths` array (FreeroutingProvider.swift:91-98): grep catches 5 of 6 entries, but MISSES `~/.volta/tools/freerouting.jar` (line 97). Also, the plan doesn't explicitly call out deleting the `defaultJARSearchPaths` array and the `locateJAR()` function (lines 321-338). See new finding N-02. |
| L-04 | SnapAngle enum case name could be clearer | P3 | **RESOLVED** | Task 2 D1 (line 62): `case fortyFive = "fortyfive_degree"` — renamed from `fortyfiveDegree` to `fortyFive`, matching Swift naming convention. |
| L-05 | DSNConverter `stripQuotes` doesn't handle escaped quotes | P3 | **RESOLVED** | Task 2 D2 (line 89): "Add `DSNConverter.stripQuotesAndUnescape()` helper (Council L-05) that handles Specctra DSN doubled-quote escaping per Council WR-03: outer quotes stripped, then `""` → `"` unescape." Old `stripQuotes()` deprecated with `@available(*, deprecated, message: "Use stripQuotesAndUnescape()")` for one-release source compatibility. |

---

## New Findings (Introduced by Revisions)

### N-01: Task 6c DEBUG dev path fallback contradicts acceptance grep [MEDIUM]

- **Severity:** P2 (MEDIUM)
- **Location:** Task 6c, step 4 (line 88) vs. acceptance criteria (line 99)
- **Description:** Step 4 says: "only fall back to the dev path for `DEBUG` builds where the JAR hasn't been copied yet." This implies the string `/Users/bretbouchard/apps/freerouting` remains in source code under `#if DEBUG`. However, the acceptance grep (line 99) requires: `grep -rn "/Users/bretbouchard/apps/freerouting" macos-app/Sources/` returns 0 matches. A `grep -rn` search does not skip `#if DEBUG` blocks — the dev path string would be found and the acceptance criterion would fail. This is an internal contradiction in the plan.
- **Evidence:** Read Task 6c step 4 and acceptance criteria. Verified that `grep -rn` does not exclude `#if DEBUG` blocks.
- **Fix:** Replace the hardcoded dev path with an environment variable: `ProcessInfo.processInfo.environment["FREEROUTING_JAR_PATH"]` for dev builds. This keeps the dev path out of source code entirely. Alternatively, require the JAR to be copied to `macos-app/Resources/` for all builds (including DEBUG) and remove the fallback. The first option is preferred — it's how the PyInstaller daemon pattern works.
- **Resolution state:** ADDED-AS-PHASE — fix in current phase before execution.

### N-02: L-03 grep is incomplete — `defaultJARSearchPaths` entries not fully covered [MEDIUM]

- **Severity:** P2 (MEDIUM)
- **Location:** Task 6 cumulative acceptance (line 191) and Task 6c body (line 88)
- **Description:** Verified `defaultJARSearchPaths` array at `FreeroutingProvider.swift:91-98` contains 6 entries:
  1. `/Applications/Freerouting.app/Contents/Java/freerouting.jar` — caught by L-03 grep
  2. `/Applications/Freerouting.app/Contents/Java/Freerouting.jar` — caught by L-03 grep
  3. `/opt/homebrew/Cellar/freerouting/*/libexec/freerouting.jar` — caught by L-03 grep
  4. `/Library/Application Support/freerouting/freerouting.jar` — caught by L-03 grep
  5. `~/Library/Application Support/freerouting/freerouting.jar` — caught by L-03 grep (substring match on `/Library/Application Support/freerouting`)
  6. `~/.volta/tools/freerouting.jar` — **NOT caught by L-03 grep**

  Entry 6 (`~/.volta/tools/freerouting.jar`) is a host-filesystem path that would survive the acceptance grep. Additionally, the plan says "Update `FreeroutingProvider.jarPath()`" but the actual method is `locateJAR()` (line 321) — the plan doesn't explicitly call out deleting `defaultJARSearchPaths` or updating/deleting `locateJAR()`. If the implementor creates a new method and leaves `defaultJARSearchPaths` + `locateJAR()` as dead code, the `~/.volta` path survives.
- **Evidence:** Read `FreeroutingProvider.swift:91-98` (verified all 6 paths). Read `FreeroutingProvider.swift:321-338` (verified `locateJAR()` function). Read L-03 grep pattern (line 191) — confirmed `.volta` is not matched.
- **Fix:** Two additions to Task 6c:
  1. Explicitly call out: "Delete the `defaultJARSearchPaths` static array (lines 91-98) and the `locateJAR()` function (lines 321-338). Replace `locateJAR()` with `Bundle.main.url(forResource: "freerouting", withExtension: "jar")`."
  2. Add acceptance: `grep -rn "defaultJARSearchPaths\|locateJAR\|\.volta" macos-app/Sources/Volta/Routing/` returns 0 matches.
- **Resolution state:** ADDED-AS-PHASE — fix in current phase before execution.

---

## Council Consensus

### Wave Alpha (Core)

| Member | Verdict | Key concern |
|---|---|---|
| Rick Sanchez (Code) | APPROVE-WITH-MINOR-FIXES | All 16 prior findings resolved. N-01 and N-02 are small plan-text fixes — no re-review needed. SpecctraDSNReader/DSNConverter relationship is now clean (one tokenizer, one semantic layer). |
| Rick C-137 (Security) | APPROVE | No security vulnerabilities. EasyEDA web API has proper schema validation with `Codable` + error type. No secrets, no auth changes. |
| Slick Rick (SLC) | APPROVE | C-02 feature flag is GONE — no workaround, no fallback. The web API is the only path. This is the SLC discipline working as intended. N-01/N-02 are grep completeness issues, not SLC violations. |
| Evil Morty (Synthesis) | APPROVE-WITH-MINOR-FIXES | 15/16 resolved, 1 partial. 2 new MEDIUM findings are acceptance-grep gaps. All P0/P1 from iteration 1 are fully resolved. Fix N-01 and N-02 in the plan text, then execute. |

### Wave Beta (Wisdom)

| Member | Verdict | Key concern |
|---|---|---|
| Rick Prime (Design) | APPROVE | No UI/UX concerns. ValidationPanel badge text "Native ERC only — DRC via KiCad app" is honest about functional scope. |
| Rickfucius (History) | APPROVE-WITH-MINOR-FIXES | The feature-flag anti-pattern (Phase 99 repeat) is eliminated. The Java resolution follows the pragmatic path iteration 1 accepted, with JRE bundling tracked as future enhancement. N-01 is a classic "debug escape hatch becomes permanent" pattern — fix it now so it doesn't become the next Phase 99 snap_angle. |

---

## Final Council Decision

**Evil Morty's Ruling: APPROVE-WITH-MINOR-FIXES — execution unblocked after 2 plan edits**

### All 16 prior findings — resolution status

| Finding | Severity | Status |
|---------|----------|--------|
| C-01 | P0 | RESOLVED |
| C-02 | P0 | RESOLVED |
| H-01 | P1 | RESOLVED |
| H-02 | P1 | RESOLVED |
| H-03 | P1 | RESOLVED |
| M-01 | P2 | RESOLVED |
| M-02 | P2 | RESOLVED |
| M-03 | P2 | RESOLVED |
| M-04 | P2 | RESOLVED |
| M-05 | P2 | RESOLVED |
| M-06 | P2 | RESOLVED |
| L-01 | P3 | RESOLVED |
| L-02 | P3 | RESOLVED |
| L-03 | P3 | PARTIAL (subsumed by N-02) |
| L-04 | P3 | RESOLVED |
| L-05 | P3 | RESOLVED |

### Must-fix items before execution begins (2 new findings)

1. **[N-01] Fix Task 6c DEBUG dev path contradiction** — Replace the hardcoded dev path fallback with `ProcessInfo.processInfo.environment["FREEROUTING_JAR_PATH"]` for dev builds, OR require the JAR in `macos-app/Resources/` for all builds. The acceptance grep `grep -rn "/Users/bretbouchard/apps/freerouting" macos-app/Sources/` returning 0 matches is incompatible with the dev path being in source, even under `#if DEBUG`.

2. **[N-02] Complete the L-03 acceptance grep** — Add `grep -rn "defaultJARSearchPaths\|locateJAR\|\.volta" macos-app/Sources/Volta/Routing/` returns 0 matches. Explicitly call out deleting `defaultJARSearchPaths` (lines 91-98) and `locateJAR()` (lines 321-338) in Task 6c's body text.

### Why APPROVE-WITH-MINOR-FIXES instead of REJECT

- All 5 P0/P1 findings from iteration 1 are fully resolved with specific, citable plan revisions.
- The 2 new MEDIUM findings are plan-text edits (add grep patterns, resolve a contradiction), not structural plan defects.
- Neither new finding requires re-review — they are acceptance-criteria completions, not architectural changes.
- We are at iteration 2 of 3. Escalation gate (proceed/manual/abandon) is not warranted for grep-pattern additions.
- The author demonstrated thorough response to all 16 prior findings — the revision quality is high.

### Execution guidance

After applying fixes N-01 and N-02 to the plan files:
1. Execution is UNBLOCKED.
2. No re-review required — the fixes are mechanical plan-text edits.
3. The bureaucracy hooks (finding_resolution_enforcer, drift detector) will verify compliance during execution.
4. Create the R-4 deferral Bead (`council-deferred,phase-253,deferred-to-task-2b`) at execution start, not at end — the bureaucracy requires tracking artifacts to exist before work begins.

### Sandbox-rule note (non-blocking)

The `/usr/libexec/java_home` approach in 6e eliminates `which`/PATH resolution (the specific C-01 finding) but does not fully satisfy the sandbox rule's "all subprocesses must resolve from `Bundle.main.resourcePath`" clause — Java itself is still resolved from the host filesystem. This was accepted as pragmatic in iteration 1, and JRE bundling (gold standard) is tracked as a future enhancement. This is noted for the record, not as a blocking finding. A future phase should bundle a JRE to achieve full sandbox compliance.

---

**Review completed:** 2026-07-28
**Review duration:** ~12 minutes
**Iteration:** 2 of 3
