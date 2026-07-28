# Council of Ricks — Gate 1 Plan Review

**Phase:** 253 (Routing Plugin System)
**Plans reviewed:** Task 2 REDO (DSN port), Task 6 (Sandbox cleanup)
**Review date:** 2026-07-28
**Reviewers:** Rick Sanchez (code), Rick C-137 (security), Slick Rick (SLC), Evil Morty (synthesis), Rick Prime (design), Rickfucius (history)
**Verdict:** **REJECT — revisions required before execution**

---

## Executive Summary

- **Total findings:** 16
- **Critical (P0):** 2
- **High (P1):** 3
- **Medium (P2):** 6
- **Low (P3):** 5

Both plans are well-structured with clear source-of-truth references, measurable acceptance criteria, and independently shippable commit strategies. However, two critical sandbox-rule violations survive both plans: (1) `probeJava()` still uses `which java` PATH lookup, and (2) the EasyEDA feature-flag mitigation keeps a shell-out fallback that violates the sandbox rule. These must be resolved before execution.

---

## Stack Assessment

- **Project type:** macOS native app (Swift, SwiftUI)
- **Build system:** Xcode/xcodebuild, Fastlane
- **Concurrency:** Swift 6 strict concurrency
- **Platform:** macOS 26+ (FoundationModels, Liquid Glass)
- **Sandbox rule:** Codified at `cf1fb3b` in PROJECT.md
- **Existing routing infra:** RoutingProvider protocol (`bf29795`), FreeroutingProvider (`0a22012`), DSNConverter (parser-only)

**Council wave composition:**
- **Wave Alpha (Core):** Rick Sanchez, Rick C-137, Slick Rick, Evil Morty
- **Wave Beta (Wisdom):** Rick Prime, Rickfucius
- **Total reviewers:** 6

---

## SLC Validation (Slick Rick)

**Status:** FAIL

### SLC Anti-Patterns Detected

| # | Anti-pattern | Location | Severity |
|---|---|---|---|
| C-02 | Feature flag keeps sandbox-violating fallback code path ("good enough" temporary fix) | Task 6b risk mitigation | CRITICAL |
| H-01 | Existing DSNConverter.swift comments reference kicad-cli/Python pcbnew as the conversion mechanism — not cleaned up by Task 2 | `DSNConverter.swift:13-16` | HIGH |

### SLC Criteria Assessment

- [ ] **Simple:** Plans are clear and well-organized. PASS.
- [ ] **Lovable:** Routing pipeline will be delightful once sandbox-clean. PARTIAL — feature-flag fallback is not lovable.
- [x] **Complete:** User journey from .kicad_pcb → DSN → Freerouting → routed .kicad_pcb is fully covered. PASS.
- [ ] **No workarounds:** Feature flag in 6b is a workaround. FAIL.

**SLC Decision:** REJECT — C-02 must be resolved.

---

## Security Review (Rick C-137)

**Status:** PASS (no security vulnerabilities in the plans themselves)

The plans do not introduce secrets, authentication changes, or network exposure. The EasyEDA web API rewrite (6b) does introduce outbound HTTP to `easyeda.com` — this needs App Sandbox network entitlement review, but is not a vulnerability per se.

**Security note:** The `probeJava()` PATH lookup is a sandbox violation (C-01) but not a security vulnerability in the OWASP sense. It is a compliance violation against the project's own sandbox rule.

---

## Code Quality Review (Rick Sanchez)

**Status:** FAIL

### Findings

#### C-01 — `probeJava()` uses `which java` PATH lookup — sandbox violation not addressed [CRITICAL]
- **Severity:** Critical (P0)
- **Location:** `macos-app/Sources/Volta/Routing/FreeroutingProvider.swift:289-317`
- **Description:** `probeJava()` calls `/usr/bin/env which java` and `/usr/bin/which java` and falls back to `/usr/bin/java`. The sandbox rule (`cf1fb3b`) states: "No host-filesystem lookups, no `which`/PATH resolution." Neither Task 2 nor Task 6 addresses this. After both plans execute, `FreeroutingProvider` will have a bundled JAR (6c) and native DSN pipeline (Task 2), but Java itself is still resolved via PATH — a direct sandbox violation.
- **Evidence:** Read FreeroutingProvider.swift lines 289-317. Read PROJECT.md sandbox rule at line 147. Grep for `which` in Sources confirms the pattern.
- **Fix:** Add a sub-task (6e or amend 6c) that resolves Java from `Bundle.main` or bundles a JRE. At minimum, use `/usr/libexec/java_home` (macOS standard) instead of `which`, and document why this is sandbox-compliant (it's a system framework, not PATH resolution). If bundling a JRE is required, create a tracked deferral.
- **Resolution state:** ADDED-AS-PHASE — must be addressed in current phase (253).

#### H-01 — DSNConverter.swift comments reference kicad-cli/Python pcbnew — not cleaned up [HIGH]
- **Severity:** High (P1)
- **Location:** `macos-app/Sources/Volta/Routing/DSNConverter.swift:13-16`
- **Description:** DSNConverter.swift header comments say: "Full .kicad_pcb DSN round-trip is delegated to Python (pcbnew bindings) since kicad-cli 9.x has no specctra subcommand." Task 2's D2 says "Extension of existing DSNConverter.swift" but does not mention updating these stale comments. The acceptance grep (`pcbnew|pip install pcbnew|Python pcbnew`) would catch this — but the plan doesn't explicitly call out cleaning DSNConverter's header.
- **Evidence:** Read DSNConverter.swift lines 13-16. Task 2 D2 references DSNConverter but only for extension, not cleanup.
- **Fix:** Add explicit step to D2: "Update DSNConverter.swift header comments to reflect native Swift DSN writer — remove all references to Python pcbnew and kicad-cli as conversion mechanisms."
- **Resolution state:** ADDED-AS-PHASE — must be fixed in current phase.

#### H-03 — SpecctraDSNReader vs DSNConverter relationship unclear — duplication risk [HIGH]
- **Severity:** High (P1)
- **Location:** Task 2 D2 plan, `macos-app/Sources/Volta/Routing/DSNConverter.swift`
- **Description:** D2 says "Extension of existing DSNConverter.swift to capture full wire/via geometry" but then defines a separate `SpecctraDSNReader` struct with its own `read()` method. DSNConverter already has `parseSummary()` and `tokenize()`. Will SpecctraDSNReader reuse DSNConverter's tokenizer? Or duplicate it? Two DSN parsers in the same module is a maintenance hazard — if one fixes a tokenization bug, the other won't.
- **Evidence:** Read DSNConverter.swift (has tokenize, findSection, validateBalance). Task 2 D2 defines SpecctraDSNReader as a separate struct. No mention of reusing DSNConverter internals.
- **Fix:** Clarify the relationship. Either (a) SpecctraDSNReader wraps DSNConverter (calls `parseSummary` for metadata, adds wiring parsing on top), or (b) SpecctraDSNReader replaces DSNConverter entirely (deprecate the old one). Option (a) is preferred — keeps one tokenizer, extends its output.
- **Resolution state:** ADDED-AS-PHASE — plan must clarify before execution.

#### M-05 — Commit 3 (Task 2) combines too much surface area [MEDIUM]
- **Severity:** Medium (P2)
- **Location:** Task 2 commit strategy, commit 3
- **Description:** Commit 3 combines D3 (SegmentSplicer ~300 LOC) + D4 (FreeroutingProvider wiring ~50 LOC) + D5/splicer tests (~150 LOC). That's ~500 LOC in one commit. If a bug is found in the splicer, reverting also reverts the FreeroutingProvider wiring.
- **Fix:** Split commit 3 into: 3a (SegmentSplicer + tests), 3b (FreeroutingProvider wiring + dsnConversionUnavailable deletion). Each is independently revertable.
- **Resolution state:** ADDED-AS-PHASE — revise commit strategy.

---

## Design Review (Rick Prime)

**Status:** PASS (no UI/UX changes in these plans)

The plans are infrastructure-level (routing pipeline + sandbox cleanup). No UI surfaces are modified except 6a's ValidationPanel badge text, which is trivial. No design system or accessibility concerns.

---

## Historical Context (Rickfucius)

**Status:** PATTERNS FOUND

### Relevant Pattern: Python-to-Swift Port Fidelity
- **Category:** code/porting
- **Historical context:** Phase 223 (PCBParser.swift) ported `pcb_native_parser.py` to Swift. The port was successful because it used snapshot parity tests against Python output for the same fixture. The same approach is recommended here.
- **Pattern compliance:** Task 2 follows this pattern (parity tests, fixture reuse). GOOD.
- **Recommendation:** Follow Phase 223's approach — port one function at a time, snapshot-test each against Python output, then integrate.

### Relevant Pattern: Sandbox Discipline Enforcement
- **Category:** architecture/security
- **Historical context:** The sandbox rule was codified at `cf1fb3b` after the kicad-cli load-bearing review found that Volta's app-sandbox claims were undermined by PATH-based lookups. The rule is absolute — no exceptions for "it's just a system path."
- **Pattern compliance:** Task 6 addresses 4 of 5 known violations. The 5th (Java PATH lookup) is missed. This repeats the pattern from Phase 203 where the daemon was bundled but kicad-cli was still called via PATH — partial compliance that was later caught and fixed.
- **Recommendation:** Add Java resolution to Task 6. Don't repeat the partial-compliance pattern.

### Anti-Pattern: Feature Flag as Workaround
- **Category:** code/anti-pattern
- **Problem:** Using a feature flag to keep a violating code path "just in case" defeats the purpose of the cleanup. The flag becomes permanent debt.
- **Historical evidence:** Phase 99 had a similar pattern with the `snap_angle` feature flag that was supposed to be temporary — it's still in the codebase.
- **Current violations:** Task 6b `useWebAPI` flag keeps the `easyeda2kicad` shell-out path.
- **Resolution:** Delete the shell-out path entirely. If the web API breaks, ship a fix — don't keep a fallback that violates the sandbox rule.

---

## Detailed Findings (All Severities)

### Critical (P0) — Blocks execution

#### C-01: `probeJava()` uses `which java` — sandbox violation not addressed
- **Plan:** Both Task 2 and Task 6
- **Location:** `FreeroutingProvider.swift:289-317`
- **Description:** `probeJava()` uses `/usr/bin/env which java` and `/usr/bin/which java` — direct PATH resolution. The sandbox rule prohibits this. Neither plan addresses Java resolution. After Task 2 (native DSN pipeline) + Task 6c (bundled JAR), the FreeroutingProvider still calls `which java` to find the runtime.
- **Also affected:** `defaultJARSearchPaths` (lines 91-98) includes `/Applications/`, `/opt/homebrew/`, `/Library/`, `~/Library/`, `~/.volta/` — all host-filesystem paths. Task 6c fixes the JAR path via `Bundle.main.url(forResource:)` but the Java path is untouched.
- **Fix:** Add sub-task 6e: "Resolve Java runtime from bundle or system framework." Options: (a) bundle a minimal JRE in `.app/Contents/PlugIns/Java.runtime` (Eclipse pattern), (b) use `/usr/libexec/java_home` (macOS standard — not PATH, not `which`), (c) use `Process(executableURL: URL(fileURLWithPath: "/usr/bin/java"))` directly (system path, not PATH lookup — may be acceptable under sandbox rule since it's a fixed system path, not discovery). Option (b) or (c) is pragmatic; (a) is the gold standard.
- **Resolution state:** ADDED-AS-PHASE
- **Reasoning:** Direct sandbox-rule violation. Both plans modify FreeroutingProvider but neither touches probeJava. The acceptance grep criteria don't include `which` as a search pattern, so this violation would pass undetected.

#### C-02: EasyEDA feature flag keeps sandbox-violating shell-out fallback
- **Plan:** Task 6b risk mitigation
- **Location:** Task 6b plan, risk table: "false falls back to the previous shell-out path (still available, just not preferred)"
- **Description:** The plan says to delete `findEasyEda2Kicad()` and the `pip install` error message, but the risk mitigation says `useWebAPI = false` falls back to the shell-out path. This is contradictory — if you delete `findEasyEda2Kicad()`, what does the fallback use? And even if it uses `ProcessRunner` directly, it still requires `easyeda2kicad` to be installed via `pip install`, which violates the sandbox rule. A feature flag that keeps a violating code path is an SLC workaround.
- **Fix:** Delete the shell-out path entirely. No feature flag. If the EasyEDA web API breaks, ship a fix. The whole point of 6b is to remove the `easyeda2kicad` dependency — a fallback that re-introduces it defeats the purpose.
- **Resolution state:** ADDED-AS-PHASE
- **Reasoning:** SLC violation — "no workarounds, no 'good enough' temporary fixes." Feature flag is a workaround that keeps violating code alive.

### High (P1) — Blocks execution

#### H-01: DSNConverter.swift header comments not cleaned up
- **Plan:** Task 2 D2
- **Location:** `DSNConverter.swift:13-16`
- **Description:** Comments say "Full .kicad_pcb DSN round-trip is delegated to Python (pcbnew bindings) since kicad-cli 9.x has no specctra subcommand." After Task 2, this is false — the round-trip is native Swift. The acceptance grep would catch `Python pcbnew` in these comments, but the plan doesn't explicitly call out cleaning them.
- **Fix:** Add to D2: "Update DSNConverter.swift header to reflect native Swift DSN pipeline. Remove all references to Python pcbnew, kicad-cli, and shell-out as conversion mechanisms."
- **Resolution state:** ADDED-AS-PHASE

#### H-02: 57.7 MB binary in git without Git LFS
- **Plan:** Task 6c
- **Location:** Task 6c plan, binary in git note
- **Description:** Committing a 57.7 MB JAR directly to git permanently bloats the repository history. Git LFS is mentioned as a "later" option, but once the binary is in history, switching to LFS doesn't help — the blob is already in every clone's history. The PyInstaller daemon comparison is noted, but two wrongs don't make a right.
- **Fix:** Use Git LFS from the first commit. Add `macos-app/Resources/freerouting.jar` to `.gitattributes` as LFS-tracked before committing the binary. If LFS is not set up for the repo, set it up as part of 6c.
- **Resolution state:** ADDED-AS-PHASE

#### H-03: SpecctraDSNReader vs DSNConverter duplication risk
- **Plan:** Task 2 D2
- **Description:** D2 defines a new `SpecctraDSNReader` struct but says "Extension of existing DSNConverter.swift." Two DSN parsers in the same module risk divergent tokenization. DSNConverter already has `tokenize()`, `findSection()`, `validateBalance()` — SpecctraDSNReader should reuse these, not reimplement.
- **Fix:** Clarify in D2: "SpecctraDSNReader wraps DSNConverter — calls `DSNConverter.tokenize()` and `DSNConverter.findSection()` for parsing, adds wiring-section extraction on top. DSNConverter is the single tokenizer; SpecctraDSNReader is the semantic interpreter." Or: "SpecctraDSNReader replaces DSNConverter — DSNConverter is deprecated and removed."
- **Resolution state:** ADDED-AS-PHASE

### Medium (P2) — Must fix before merge

#### M-01: Test fixture provenance unclear
- **Plan:** Task 2 D5
- **Description:** The plan references "existing 6 fixture assertions on `simple_2layer_led.kicad_pcb`" and the Python parity test from `fe68b91`. The fixture file exists at `macos-app/Tests/VoltaTests/Routing/Fixtures/simple_2layer_led.kicad_pcb` (verified). But the plan doesn't mention porting the Python test's fixture data or creating additional fixtures for the new writer/reader/splicer tests. The round-trip parity test needs a known-good DSN output to compare against — where does that come from?
- **Fix:** Add to D5: "Port the Python fixture data from `fe68b91:tests/test_phase105_c02_dsn_wiring.py` — extract the expected DSN strings and embed them as Swift string literals in the test files. The `simple_2layer_led.kicad_pcb` fixture already exists in the test target."
- **Resolution state:** ADDED-AS-PHASE

#### M-02: 6a ValidationPanel replacement is vague
- **Plan:** Task 6a
- **Description:** "replace with a status badge that says 'Native validation only'" — what does this mean functionally? The existing `kicad_cli_check` provided DRC via kicad-cli. NativeERC provides ERC. Is there a gap between what kicad-cli DRC checked and what NativeERC covers? The plan doesn't assess this.
- **Fix:** Add to 6a: "Document the functional delta between kicad-cli DRC and NativeERC. If kicad-cli checked things NativeERC doesn't, list them as known gaps in the ValidationPanel UI. The badge text should be 'Native ERC/DRC' not 'Native validation only' — be specific about what's covered."
- **Resolution state:** ADDED-AS-PHASE

#### M-03: 6d conditional existence of batch_erc_parity.py
- **Plan:** Task 6d
- **Description:** Plan says "Delete `batch_erc_parity.py` if it exists in the repo." The file exists at `.planning/phases/234a-corpus-and-driver/scripts/batch_erc_parity.py` (verified). The conditional "if" suggests the author didn't verify. Plans should be definitive.
- **Fix:** Update 6d: "Delete `.planning/phases/234a-corpus-and-driver/scripts/batch_erc_parity.py` (verified exists). Also grep for any references to `batch_erc_parity` in CI configs, Makefiles, or scripts that might break."
- **Resolution state:** ADDED-AS-PHASE

#### M-04: 6b EasyEDA undocumented API risk
- **Plan:** Task 6b
- **Description:** The plan hits `easyeda.com/api/products/{lcscId}` — an undocumented API. The plan acknowledges rate-limiting but not API breaking changes. If EasyEDA changes their API shape, the provider breaks with no fallback (once the feature flag is removed per C-02).
- **Fix:** Add to 6b risks: "EasyEDA web API is undocumented and may change without notice. Mitigation: add response schema validation with `Codable` — if the response doesn't decode, throw a clear error rather than crashing. Log the raw response for debugging. Consider adding a CI test that pings the API weekly to detect breaking changes early."
- **Resolution state:** ADDED-AS-PHASE

#### M-05: Commit 3 surface area too large
- **Plan:** Task 2 commit strategy
- **Description:** Commit 3 combines SegmentSplicer (~300 LOC) + FreeroutingProvider wiring (~50 LOC) + splicer tests (~150 LOC). ~500 LOC in one commit. If a splicer bug is found post-merge, reverting also reverts the FreeroutingProvider wiring, undoing the native pipeline.
- **Fix:** Split into: 3a `feat(routing): SegmentSplicer — SES to KiCad splicer` (D3 + splicer tests), 3b `feat(routing): FreeroutingProvider native pipeline — delete pcbnew fallback` (D4 + FreeroutingProvider tests).
- **Resolution state:** ADDED-AS-PHASE

#### M-06: Task 6 acceptance grep missing `which` pattern
- **Plan:** Task 6 cumulative acceptance criteria
- **Description:** The grep `kicad-cli|kicad_cli|pcbnew|easyeda2kicad|pip install` doesn't include `which` as a search pattern. After 6a deletes KiCadCLIDetector (which uses `which kicad-cli`), FreeroutingProvider still uses `which java`. The acceptance criteria wouldn't catch this.
- **Fix:** Add `which` to the grep: `grep -rn "kicad-cli\|kicad_cli\|pcbnew\|easyeda2kicad\|pip install\|/usr/bin/env.*which\|/usr/bin/which" macos-app/Sources/` returns 0 matches. (Note: `which` as a bare word is too broad — it appears in comments and documentation. Use the specific pattern `/usr/bin/env.*which\|/usr/bin/which` to catch the actual PATH-lookup pattern.)
- **Resolution state:** ADDED-AS-PHASE

### Low (P3) — Must fix before merge

#### L-01: R-4 (4+ layer stackup) deferral lacks tracking artifact
- **Plan:** Task 2 out of scope
- **Description:** "Stackup-based padstack details for 4+ copper layers (R-4) — port only the 2-layer default path. R-4 lands as Task 2b follow-up if a 4-layer test fixture exists." No Bead or tracking artifact for this deferral.
- **Fix:** Create a Bead with label `council-deferred,phase-253,deferred-to-task-2b` for R-4. Add to ROADMAP "## Deferred" section. Trigger condition: "4-layer test fixture exists."
- **Resolution state:** DEFERRED-TO-NAMED-TARGET — trigger: Task 2b when 4-layer fixture exists.

#### L-02: Task 6 dependency claim is incorrect
- **Plan:** Task 6 header
- **Description:** "Depends on: Task 2 REDO (DSN port lands first, then this sweep)" — but sub-tasks 6a (delete KiCadCLIDetector), 6b (EasyEda rewrite), and 6d (replace Python parity test) are independent of Task 2. Only 6c's end-to-end smoke test depends on Task 2's native DSN pipeline. The code changes in 6c (bundling the JAR, updating `jarPath()`) are independent.
- **Fix:** Update Task 6 header: "Depends on: Task 2 REDO for 6c smoke test only. Sub-tasks 6a, 6b, 6d are independent and can execute in parallel with Task 2."
- **Resolution state:** ADDED-AS-PHASE

#### L-03: Task 6 cumulative grep missing `freerouting.jar` hardcoded path check
- **Plan:** Task 6 acceptance criteria
- **Description:** The cumulative grep checks `kicad-cli|kicad_cli|pcbnew|easyeda2kicad|pip install` but the `freerouting.jar` hardcoded path check is separate (`grep -rn "/Users/bretbouchard/apps/freerouting" macos-app/Sources/`). This is fine, but the `defaultJARSearchPaths` array also contains `/Applications/Freerouting.app/...`, `/opt/homebrew/Cellar/...` etc. — those are also host-filesystem paths that should be grepped out.
- **Fix:** Add to acceptance: `grep -rn "/Applications/Freerouting\|/opt/homebrew/Cellar/freerouting\|/Library/Application Support/freerouting" macos-app/Sources/` returns 0 matches.
- **Resolution state:** ADDED-AS-PHASE

#### L-04: SnapAngle enum case name could be clearer
- **Plan:** Task 2 D1
- **Description:** `case fortyfiveDegree = "fortyfive_degree"` — the case name `fortyfiveDegree` is awkward. Swift convention would be `case fortyFiveDegrees` or `case degrees45`. Minor style point.
- **Fix:** Consider `case fortyFive = "fortyfive_degree"` or `case angle45 = "fortyfive_degree"`. Not blocking — cosmetic.
- **Resolution state:** ADDED-AS-PHASE

#### L-05: DSNConverter `stripQuotes` doesn't handle escaped quotes
- **Plan:** Task 2 D2 (uses DSNConverter internals)
- **Description:** `DSNConverter.stripQuotes()` only strips outer quotes. DSN net names with embedded quotes (per Council WR-03: "pin names with whitespace/quotes get DSN doubled-quote escaping") need unescaping. If SpecctraDSNReader reuses `stripQuotes`, it won't handle `""` → `"` unescaping.
- **Fix:** Add a `stripQuotesAndUnescape()` helper or extend `stripQuotes` to handle doubled-quote escaping (`""` → `"`). Document the DSN quoting rules.
- **Resolution state:** ADDED-AS-PHASE

---

## Council Consensus

### Wave Alpha (Core)
| Member | Verdict | Key concern |
|---|---|---|
| Rick Sanchez (Code) | REJECT | C-01 probeJava, H-03 duplication risk |
| Rick C-137 (Security) | PASS | No security vulnerabilities introduced |
| Slick Rick (SLC) | REJECT | C-02 feature flag workaround violates SLC |
| Evil Morty (Synthesis) | REJECT | 2 P0 + 3 P1 findings must be resolved |

### Wave Beta (Wisdom)
| Member | Verdict | Key concern |
|---|---|---|
| Rick Prime (Design) | PASS | No UI/UX concerns |
| Rickfucius (History) | REJECT | Anti-pattern: feature flag as workaround (repeats Phase 99 pattern) |

---

## Final Council Decision

**Evil Morty's Ruling: REJECT — revise and resubmit**

### Required plan revisions before execution:

1. **[C-01] Add Java resolution sub-task to Task 6** — `probeJava()` must not use `which`/PATH. Use `/usr/libexec/java_home` (macOS framework) or bundle a JRE. Add `which` to the acceptance grep.

2. **[C-02] Delete EasyEDA feature flag** — No fallback to shell-out path. The web API is the only path. If it breaks, ship a fix. SLC means no workarounds.

3. **[H-01] Add DSNConverter.swift header cleanup to Task 2 D2** — Remove all Python pcbnew / kicad-cli references from comments.

4. **[H-02] Use Git LFS for freerouting.jar** — Set up `.gitattributes` LFS tracking before committing the 57.7 MB binary.

5. **[H-03] Clarify SpecctraDSNReader vs DSNConverter relationship** — SpecctraDSNReader should reuse DSNConverter's tokenizer, not duplicate it.

6. **[M-01 through M-06] Address all medium findings** — Test fixture provenance, ValidationPanel functional delta, batch_erc_parity.py definitive deletion, EasyEDA API schema validation, split commit 3, add `which` to grep.

7. **[L-01 through L-05] Address all low findings** — Create Bead for R-4 deferral, fix dependency claim, expand grep patterns, SnapAngle naming, quote unescaping.

### Revision iteration: 1 of 3 (per bureaucracy.md §7.5)

---

**Review completed:** 2026-07-28
**Review duration:** ~15 minutes
