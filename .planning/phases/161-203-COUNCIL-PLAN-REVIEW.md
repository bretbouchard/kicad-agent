# Council of Ricks Plan Review — v6.0 KiCad Agent: The Closed Box

**Review Date:** 2026-07-07
**Reviewer:** Council of Ricks (Heavy + Standard waves)
**Scope:** 43 phase plans (161-203), 138 requirements, 6 research docs, stupid-proof audit
**Verdict:** **REJECT — Re-plan required before Gate 1 execution**

---

## Executive Summary

**Total findings:** 19
- **P0 (Blocks execution):** 4
- **P1 (Blocks merge of related phases):** 6
- **P2 (Quality/completeness gaps):** 6
- **P3 (Advisory/polish):** 3

**Bottom line:** The v6.0 milestone is **architecturally sound and the vision holds** — stupid-proof audit passed, all 10 pitfalls have phase coverage, Fastlane integration is correctly parallel-executable, all 43 phases have plans, 135/138 requirements explicitly mapped. **However, four P0 blockers must be fixed before any execution begins:** (1) Phase 162 directly contradicts Phase 163 by bundling GPLv3 `kicad-cli` (App Store killer), (2) Phase 181 ships production code with `try/except ImportError` stubs that violate SLC, (3) Phase 202 (iPhone) declares `depends_on: []` despite hard dependencies on Memory + Collaboration + Group Activities tracks, and (4) Phase 203 is missing from the ROADMAP progress table (orphan phase risk).

The bureaucracy enforces these as **ADDED-AS-PHASE** fixes — they cannot defer to v1.x. Council Gate 1 is BLOCKED until re-plan lands.

---

## Stack Assessment

**Detected Project Stack:**
- **Project Type:** Native macOS + iOS app (SwiftUI, Liquid Glass, macOS 27+)
- **UI Framework:** SwiftUI + Liquid Glass (iOS 26+ visual language)
- **Concurrency:** Swift Concurrency (async/await, actors)
- **AI Stack:** FoundationModels + MLX-Swift + HF Hub + BYOK cloud providers
- **Backend:** Python daemon via PyInstaller (bundled subprocess, stdio MCP)
- **Storage:** SwiftData + CloudKit (private DB, CKShare, iCloud Drive)
- **Collaboration:** Group Activities v1 (4-participant cap), CKShare invitations
- **Testing:** swift-testing + XCUITest + SwiftCheck + mull-xcode + 4-variant snapshots
- **Build/Ship:** Fastlane (match, pilot, deliver, snapshot, build_daemon)
- **External Deps:** KiCad 10+ (external install, GPLv3 compliance), v5.0 SKIDL/SPICE (Track F)

**Council Wave Composition (this session):**
- **Wave Alpha (Core):** Rick Sanchez (code-reviewer), Rick C-137 (security), Slick Rick (SLC), Evil Morty
- **Wave Beta (Wisdom):** Rick Prime (design/architecture), Rickfucius (history/patterns)
- **Wave Gamma (Domain):** Apple Elitist Rick, Raspberry Pi Rick (daemon/subprocess), embedded-firmware-rick (PyInstaller signing)
- **Wave Delta (Pipeline):** architect, gsd-plan-checker, gsd-roadmapper
- **Wave Epsilon (Fresh Eyes):** kicad-rick (PCB domain on app code), compliance-rick (regulatory on Apple stack)
- **Total reviewers:** 13/84

---

## Requirement Coverage Audit

**Total requirements (REQUIREMENTS.md):** 138 active + 10 future-deferred = 148 IDs
**Requirements explicitly cited in plans:** 135/138 active (97.8%)
**Missing from plans:** 3

| REQ ID | Description | Status | Resolution |
|---|---|---|---|
| **GOV-09** | Four-state resolution taxonomy (IMPLEMENTED, ADDED-AS-PHASE, SUPERSEDED-BY-ALTERNATIVE, DEFERRED-TO-NAMED-TARGET) | NOT in any plan's `requirements:` list | **P1 — ADDED-AS-PHASE**. Phase 169 must add GOV-09 to its requirements list and add a task that implements the four-state taxonomy in the Obdurate Runtime (already implemented in `~/.claude/rules/bureaucracy.md §7` and `finding_resolution_enforcer.py`, but the v6.0 app must ship its own Swift port). Cannot defer — this is a P1 governance requirement. |
| **PIPE-03** | User can tap any pipeline step to drill into detail (intent, ops called, verification results) | Implicit in Phase 172 (Inline Rendering) but not cited | **P2 — ADDED-AS-PHASE**. Add PIPE-03 to Phase 172's `requirements:` list. Add explicit task: "PipelineStepDetailView showing intent, ops called, verification results." |
| **TEST-12** | Nightly stress tests (10-hour daemon, multi-account CloudKit, multi-session Group Activities) | Partial — Phase 197 covers 10-hour daemon, but multi-account CloudKit and multi-session Group Activities nightly stress missing | **P2 — ADDED-AS-PHASE**. Add TEST-12 to Phase 197's `requirements:` list. Add task: "Nightly stress workflow (.github/workflows/nightly-stress.yml) running (a) 10-hour daemon memory leak test, (b) multi-account CloudKit simulation via test fixtures, (c) multi-session Group Activities test (requires 2+ physical devices per Pitfall 10 note)." |

**Traceability gap:** REQUIREMENTS.md line 237 says "Traceability (filled by roadmapper — every REQ-ID maps to exactly one phase)" but the table is empty. **P2 — ADDED-AS-PHASE:** Roadmapper must populate the traceability table in REQUIREMENTS.md before Gate 1.

---

## P0 Pitfall Prevention Audit

All 10 pitfalls from `PITFALLS.md` have phase coverage. **However, the phase numbers in PITFALLS.md are STALE — they reference a pre-roadmap track structure that doesn't match the actual ROADMAP.**

| Pitfall | Severity | PITFALLS.md says | ROADMAP actually assigns | Status |
|---|---|---|---|---|
| 1. PyInstaller dylib signing | P0 | Phase 161 | Phase 162 (6 mentions) | ✅ Covered, doc drift |
| 2. stdio MCP buffering deadlock | P0 | Phase 169 | Phase 167 (5 mentions) | ✅ Covered, doc drift |
| 3. FoundationModels unavailability | P0 | Phase 163 | Phase 164 (3 mentions) | ✅ Covered, doc drift |
| 4. SwiftData CloudKit migration loss | P0 | Phase 173 | Phase 177 (10 mentions) | ✅ Covered, doc drift |
| 5. Generative hash instability | P0 | Phase 183 | Phase 184 (5 mentions) | ✅ Covered, doc drift |
| 6. iCloud Drive bundle corruption | P1 | Phase 190 | Phase 190 (7 mentions) | ✅ Covered, matches |
| 7. MLX-Swift Metal memory pressure | P1 | Phase 165 | Phase 164 (3 mentions) | ⚠ Phase 165 has 0 mentions — actual coverage is in Phase 164 Task 3 |
| 8. SwiftData query perf with millions of events | P1 | Phase 175 | Phase 178 + Phase 180 (8 mentions) | ✅ Covered, doc drift |
| 9. App Store GPL rejection | P0 | Phase 162 | Phase 163 (4 mentions) | ✅ Covered, doc drift |
| 10. CKShare participant permission edge cases | P2 | Phase 192 | Phase 188 (5 mentions) | ✅ Covered, doc drift |

**Finding P2-DOC-DRIFT:** `PITFALLS.md` "Pitfall-to-Phase Mapping" table (lines 358-376) is **stale** — 8 of 10 pitfall phase numbers are wrong. **P2 — IMPLEMENTED in this review (corrected table above); update PITFALLS.md before Gate 1.**

---

## Critical Findings (P0 — Blocks Execution)

### P0-01: Phase 162 bundles GPLv3 kicad-cli — contradicts Phase 163, violates Out-of-Scope

**Location:** `.planning/phases/162-python-daemon-bundling/162-01-PLAN.md:93`
**Severity:** P0 (App Store rejection certain)
**Confidence:** 1.0

**Evidence:**

Phase 162 Task 1 explicitly bundles kicad-cli:
```
- Bundle kicad-cli from system: /usr/local/bin/kicad-cli → kicad-cli (bundled resource)
```

Phase 163 objective explicitly prohibits this:
```
Detect external KiCad 10+ installation, guide users through one-time setup... This ensures
App Store GPL compliance (Pitfall 9) while enabling advanced workflows for power users.

Purpose: Enable KiCad CLI operations (ERC/DRC, rendering, export) without bundling GPLv3
kicad-cli — without this, the app cannot validate schematics, render PCBs, or export
manufacturing files.
```

REQUIREMENTS.md "Out of Scope (Locked Exclusions)":
```
- Bundled kicad-cli — GPLv3 blocks App Store. Require external KiCad install (one-time setup).
```

**Why this is wrong:** Bundling kicad-cli makes the entire .app GPL-encumbered. Mac App Store will reject submission (Pitfall 9). The Out-of-Scope rule is a "locked exclusion" — meaning this is non-negotiable.

**Required fix:** Edit Phase 162 Task 1 to:
1. Remove the `Bundle kicad-cli from system` line entirely.
2. Add explicit note: "kicad-cli is NOT bundled — Phase 163 detects external install per App Store GPL compliance (Pitfall 9 prevention)."
3. The daemon bundles only Python stdlib + volta library + ops/registry.

**Resolution state:** ADDED-AS-PHASE — must be fixed in Phase 162 plan before Gate 1.

---

### P0-02: Phase 181 ships production code with `try/except ImportError` stubs

**Location:** `.planning/phases/181-skidl-compiler/181-01-PLAN.md:161-164, 241, 262`
**Severity:** P0 (SLC violation)
**Confidence:** 0.95

**Evidence:**

Phase 181 Task 2 explicitly ships stub code:
```
4. **Dependency stub for v5.0** (until Phase 156 lands):
   - Add `try/except ImportError` for v5.0 SKIDL modules
   - If v5.0 SKIDL not available: log warning, use stub IR format
   - Once v5.0 lands: remove stub, import real SKIDL IR types
```

Line 262 even has a "remove stub" task — confirming the stub ships:
```
1. Remove v5.0 ImportError stub
```

**Why this is wrong:** Bret's CLAUDE.md SLC rule is explicit:
> "NO workarounds, NO exceptions. Forbidden: 'It works but...' solutions, stub methods, TODO without tickets, 'good enough' fixes."

A stub that "logs a warning and uses stub IR format" is exactly the anti-pattern SLC forbids. If v5.0 isn't ready, Phase 181 should not execute — Track F is already correctly marked BLOCKED on v5.0 in the ROADMAP. The plan contradicts its own dependency declaration.

**Required fix:** Two valid options:

**Option A (preferred):** Plan 181-01 stays BLOCKED. No execution until v5.0 Phase 156 lands. The plan describes the architecture but does NOT ship code with ImportError stubs. Once v5.0 lands, plan executes against real SKIDL IR.

**Option B (fallback if v5.0 won't land before v6.0 ship):** Phase 181 emits ONLY the IR dataclasses (Task 1) with a `# v5.0-dependent` header. No compiler body ships. No stub IR format. No "use stub" runtime path. Document in plan: "Phase 181 ships dataclasses only; compiler body deferred to v6.1 when v5.0 lands."

**Resolution state:** ADDED-AS-PHASE — must re-plan Phase 181 before Track F execution.

---

### P0-03: Phase 202 (iPhone) declares `depends_on: []` despite hard dependencies

**Location:** `.planning/phases/202-iphone-companion/202-01-PLAN.md:5`
**Severity:** P0 (Plan cannot execute correctly)
**Confidence:** 1.0

**Evidence:**

Phase 202 frontmatter:
```yaml
depends_on: []
```

But Phase 202 Truths section requires:
- "iPhone app shows same conversation as Mac (CloudKit sync)" → needs Phase 176 (SwiftData Models) + Phase 177 (CloudKit Sync)
- "iPhone pairs with Mac automatically via iCloud Keychain" → needs Phase 166 (BYOK Keychain)
- "iPhone renders schematics (SVG) and PCBs (PNG) streamed from Mac" → needs Phase 172 (Inline Rendering) + Phase 162 (Python Daemon) + Phase 163 (KiCad CLI)
- (Implicit) iPhone participates in live sessions → needs Phase 187 (Group Activities)

ROADMAP line 775: `Phase 187 depends on Phase 186 (Group Activities needs genealogy)` — but Phase 202 is supposed to support Group Activities too. If iPhone ships before Group Activities, LIVE-* requirements cannot be satisfied on iPhone.

**Why this is wrong:** An empty `depends_on:` will cause the GSD executor to schedule Phase 202 in parallel with Foundation, which will fail because the iPhone app references SwiftData models, CloudKit config, and Bonjour discovery patterns that don't exist yet.

**Required fix:** Update Phase 202 frontmatter:
```yaml
depends_on:
  - 176-01  # SwiftData Models (CloudKit sync models)
  - 177-01  # CloudKit Sync (Mac<->iPhone sync)
  - 166-01  # BYOK Keychain (iCloud Keychain pairing)
  - 172-01  # Inline Rendering (SVG/PNG render protocol)
  - 162-01  # Python Daemon (Mac daemon must exist)
  - 163-01  # KiCad CLI Integration (external KiCad)
  - 187-01  # Group Activities (iPhone participates in live sessions)
```

**Resolution state:** ADDED-AS-PHASE — must update Phase 202 plan before Gate 1.

---

### P0-04: Phase 203 missing from ROADMAP progress table

**Location:** `.planning/ROADMAP.md` "Progress Tracking" table (lines ~720-765)
**Severity:** P0 (Orphan phase risk — execution will skip it)
**Confidence:** 1.0

**Evidence:**

ROADMAP "Progress Tracking" table lists Phases 161-202 (42 phases) but Phase 203 is missing entirely. Header says "Total: 42 phases, 132 requirements mapped" — but actual scope is 43 phases (161-203) and 138 requirements.

Phase 203 is listed in the phase list (line 51) and has a complete plan, but the progress table that the GSD executor uses to track completion does NOT include it.

**Why this is wrong:** When `/gsd-execute-phase` runs through the milestone, it iterates the progress table. Phase 203 will be silently skipped — no Fastlane integration will ship, no TestFlight distribution, no App Store automation. This is a P0 ship blocker.

**Required fix:**
1. Add `203. Build & Ship Automation (Fastlane) | 0/1 | Not started | -` to the progress table.
2. Update header: `**Total:** 43 phases, 138 requirements mapped, 100% coverage, X plans written`
3. Update Track Overview to include Phase 203 in Track H (or create Track I: Build/Ship).

**Resolution state:** ADDED-AS-PHASE — must update ROADMAP before Gate 1.

---

## High Findings (P1 — Blocks merge of related phases)

### P1-01: ROADMAP claims "100% coverage" but 3 requirements are missing

**Location:** `.planning/ROADMAP.md:767`
**Severity:** P1
**Confidence:** 1.0

ROADMAP line 767: `**Total:** 42 phases, 132 requirements mapped, 100% coverage, **7 plans written for phases 171-175, 201-202**`

But REQUIREMENTS.md has 138 requirements, and 3 (GOV-09, PIPE-03, TEST-12) are missing from plans. **"100% coverage" claim is false.**

**Resolution state:** ADDED-AS-PHASE — fix ROADMAP claim, add 3 missing requirements to their phases (see Requirement Coverage Audit above).

---

### P1-02: Phase 167 ships MCP tool handlers as stubs

**Location:** `.planning/phases/167-stdio-mcp-client/167-01-PLAN.md:72`
**Severity:** P1
**Confidence:** 0.9

Phase 167 Task 1:
```
3. Implements list_tools() and call_tool() handlers (stubs for now, full implementation in Phase 168)
```

This is acceptable **only if** Phase 168 is executed immediately after Phase 167 and Phase 167 is never merged alone. But the GSD state machine allows merging Phase 167 independently — a stub `call_tool()` would silently fail in production.

**Required fix:** Either (a) merge Phase 167 + Phase 168 as a single execution unit (mark 167 as `dependent_exec_only: true`), or (b) have Phase 167 implement a minimal real `call_tool()` that handles the `initialize` method only and explicitly errors on all others with "Phase 168 not yet loaded."

**Resolution state:** ADDED-AS-PHASE.

---

### P1-03: PITFALLS.md phase mapping table is stale (8/10 wrong)

**Location:** `.planning/research/v6/PITFALLS.md:358-376`
**Severity:** P1
**Confidence:** 1.0

The "Pitfall-to-Phase Mapping" table is a critical cross-reference for verifiers — but 8 of 10 entries point to wrong phases. A verifier checking "Pitfall 4 prevention" would look at Phase 173 (per the table) and find nothing — the actual prevention is in Phase 177.

**Required fix:** Replace the table with the corrected version from this review's P0 Pitfall Prevention Audit section.

**Resolution state:** IMPLEMENTED in this review (corrected mapping documented above) — update PITFALLS.md to match before Gate 1.

---

### P1-04: Phase 165 lacks Pitfall 7 (MLX VRAM) coverage

**Location:** `.planning/phases/165-provider-router/165-01-PLAN.md` (entire file)
**Severity:** P1
**Confidence:** 0.9

Phase 165 (Provider Router) is supposed to handle Pitfall 7 per ROADMAP line 758:
```
- Phase 197: MLX-Swift Metal memory pressure (Pitfall 7)
```

Wait — ROADMAP line 758 actually says Phase **197**, not 165. And Phase 164 has the VRAM detection in Task 3. So Pitfall 7 IS covered (in Phase 164 Task 3), but the ROADMAP line is also wrong (says 197, should say 164).

**Required fix:**
1. Update ROADMAP Pitfall line: `- Phase 164: MLX-Swift Metal memory pressure (Pitfall 7)`
2. Add Pitfall 7 cross-reference to Phase 165 plan header (even though detection lives in 164, the Router uses `isLowMemoryDevice` flag to downgrade model).

**Resolution state:** ADDED-AS-PHASE.

---

### P1-05: Phase 166 BYOK Keychain describes "device-local by default" AND "iCloud sync opt-out" simultaneously

**Location:** `.planning/phases/166-byok-keychain-storage/166-01-PLAN.md:22,23,95,96`
**Severity:** P1 (Requirement ambiguity)
**Confidence:** 0.85

Phase 166 truths:
```
- "API keys stored in device-local Keychain by default"
- "iCloud Keychain sync is opt-out (user must explicitly disable, warned on disable)"
```

These contradict. "Device-local by default" means `kSecAttrSynchronizable: false` initially. "iCloud sync opt-out" means `kSecAttrSynchronizable: true` initially. They cannot both be the default.

MOD-04 (REQUIREMENTS.md line 54):
```
**MOD-04**: API keys are stored in Keychain (device-local by default, opt-in iCloud Keychain sync)
```

MOD-04 says **device-local by default, opt-in iCloud sync**. Phase 166 has it backwards (treating iCloud as default).

**Required fix:** Phase 166 must use `kSecAttrSynchronizable: false` as default. iCloud Keychain sync is **opt-in** (user explicitly enables via Settings toggle, warned about device-swap implications).

**Resolution state:** ADDED-AS-PHASE — Phase 166 plan must be corrected before Gate 1.

---

### P1-06: Phase 203 missing threat model section

**Location:** `.planning/phases/203-build-and-ship-automation-fastlane/203-01-PLAN.md` (entire file)
**Severity:** P1
**Confidence:** 0.85

All other phases (162, 167, 169, 177, 188, 190, 202) have a `<threat_model>` section with STRIDE threats. Phase 203 has zero threat model references. Yet Phase 203 introduces significant new attack surface:
- Match repo (private GitHub with certs) — supply chain risk
- App Store Connect API key in CI — credential leak risk
- TestFlight external testers — distribution abuse risk
- PyInstaller build invocation — arbitrary code execution risk

**Required fix:** Add `<threat_model>` section to Phase 203 with at least:
- T-203-01 (S): Match repo compromise → use branch protection + signed commits
- T-203-02 (I): App Store Connect API key leak → use GitHub Secrets, rotate annually
- T-203-03 (D): CI runner compromised → use ephemeral runners, no persistent state
- T-203-04 (E): TestFlight tester abuse → use pinned tester roster, audit log

**Resolution state:** ADDED-AS-PHASE.

---

## Medium Findings (P2 — Quality/completeness gaps)

### P2-01: Stupid-proof augmentations not yet applied to REQUIREMENTS.md

**Location:** `.planning/REQUIREMENTS.md` (entire file)
**Severity:** P2

The stupid-proof audit (`STUPID-PROOF-AUDIT.md`) recommends "Apply 46 augmentations to REQUIREMENTS.md (next step)" — and on inspection, MANY have already been applied inline as italicized failure-mode clauses. But the audit was performed against 132 requirements and REQUIREMENTS.md now has 138 (6 new requirements added post-audit). The 6 new ones may not have been audited.

**Required fix:** Re-run stupid-proof audit on the 6 new requirements (need to identify which 6 were added — diff against the 132 list in audit doc).

**Resolution state:** ADDED-AS-PHASE — complete audit before Gate 1.

---

### P2-02: Phase 175 depends on 171 but not 172/173/174

**Location:** `.planning/phases/175-chat-interface/175-01-PLAN.md` frontmatter `depends_on: [171]`
**Severity:** P2

Chat Interface (175) needs Inline Rendering (172) for SVG/PNG display, GSD Conversation Engine (173) for spec/roadmap cards, and Approval Gates UI (174) for gate prompts. But it only depends on 171.

**Required fix:** Update frontmatter to include 172, 173, 174 in depends_on.

**Resolution state:** ADDED-AS-PHASE.

---

### P2-03: Phase 191 wave=1 but should be parallel-executable from Phase 161

**Location:** `.planning/phases/191-swift-testing-framework/191-01-PLAN.md` `wave: 1`
**Severity:** P2

Per task description: "Fastlane build stack (Phase 203, parallel-executable from Phase 161)". But Phase 191 (swift-testing framework) is also a parallel-executable track — testing infrastructure can be set up before any features land (write tests against protocols/stubs, then fill in as features ship). Yet 191 is `wave: 1` and `depends_on: []` (which is correct) but it's not called out as parallel-executable in the ROADMAP Track Overview.

**Required fix:** Update Track Overview to explicitly call out Phase 191 (and 192-200) as parallel-executable from Phase 161, similar to Phase 203. Track H is "Quality (parallel-executable)".

**Resolution state:** ADDED-AS-PHASE.

---

### P2-04: Phase 197 references Pitfall 11 but PITFALLS.md only has 10 pitfalls

**Location:** `.planning/phases/192-snapshot-testing/192-01-PLAN.md:45` (mentions "Pitfall 11")
**Severity:** P2

Phase 192 mentions "Pitfall 11" but PITFALLS.md only documents 10 pitfalls. Pitfall 11 (snapshot test fragility / frozen time) is real and referenced but never documented in PITFALLS.md.

**Required fix:** Add Pitfall 11 (Snapshot Test Fragility) to PITFALLS.md with full description, prevention (frozen time fixtures), and phase mapping (Phase 192).

**Resolution state:** ADDED-AS-PHASE.

---

### P2-05: TEST-13 through TEST-18 (Fastlane requirements) — verification unclear in Phase 203

**Location:** `.planning/phases/203-build-and-ship-automation-fastlane/203-01-PLAN.md`
**Severity:** P2

Phase 203 lists TEST-13 through TEST-18 in requirements. Good. But verification gates say:
- `fastlane build` succeeds on clean machine
- `fastlane test` reports pass to JUnit + xcresult
- etc.

These are lane-level verifications, not requirement-level. TEST-15 (TestFlight every merge to main) needs verification that an automated CI workflow exists on `main` branch pushes. TEST-17 (precheck catches rejection risks in CI before merge) needs verification that `precheck` runs on PR (not just pre-release).

**Required fix:** Add explicit per-requirement verification matrix:
- TEST-13: No bespoke xcodebuild scripts in `.github/workflows/` (grep verification)
- TEST-14: Match repo has branch protection (GitHub API check)
- TEST-15: TestFlight workflow triggers on `push: branches: [main]`
- TEST-16: `deliver` works end-to-end (sandbox test)
- TEST-17: `precheck` runs in PR workflow (not release workflow)
- TEST-18: `build_daemon` lane exists in Fastfile

**Resolution state:** ADDED-AS-PHASE.

---

### P2-06: Group Activities simulator limitation not addressed in test plan

**Location:** `.planning/phases/187-group-activities-v1/187-01-PLAN.md`
**Severity:** P2

PITFALLS.md note (line 337): "Group Activities — Often works on single device — requires 2+ physical devices (no simulator)". Phase 187 acknowledges this in threats but test plan needs explicit hardware budget line item: "Requires 2+ physical Macs for Group Activities testing."

**Required fix:** Add to Phase 187 Implementation Notes: "Test plan requires 2 physical Macs (M-series) with FaceTime/iMessage signed in. Budget hardware allocation in Phase 187 prep."

**Resolution state:** ADDED-AS-PHASE.

---

## Low Findings (P3 — Advisory/polish)

### P3-01: Phase 162 references Python 3.11 but STACK.md recommends 3.11.11

Phase 162 line 100: `sys.path.insert(0, '/usr/local/lib/python3.11/site-packages')` — hardcoded path. Phase 162 should use PyInstaller's `--paths` flag instead of runtime sys.path manipulation.

**Resolution state:** SUPERSEDED-BY-ALTERNATIVE — PyInstaller bundling eliminates need for sys.path hacks; the alternative is "let PyInstaller bundle the dependencies correctly via spec file hiddenimports."

---

### P3-02: Phase 203 Appfile uses `bretbouchard` bundle ID placeholder

Phase 203 Appfile: `app_identifier("com.bretbouchard.volta")` — should be parameterized via `ENV['APP_BUNDLE_ID']` to support team scaling.

**Resolution state:** DEFERRED-TO-NAMED-TARGET — v1.x when team scales beyond solo dev. Trigger: Second developer joins.

---

### P3-03: Phase 181 dependency stub narrative is confusing

Phase 181 mentions "dependency stub" 9 times — but the intent is "design architecture, defer execution." Recommend renaming "stub" to "architecture-only phase" throughout for clarity.

**Resolution state:** SUPERSEDED-BY-ALTERNATIVE — addressing via P0-02 fix (no stubs ship).

---

## Historical Context & Pattern Wisdom (Rickfucius)

**Status:** ⚠️ PATTERNS FOUND — apply Confucius-stored patterns

### Relevant Patterns

#### Compiler Model (Conversation = Source of Truth)
- **Category:** architecture
- **Historical Context:** Phase 26 (cartridge production) and Phase 101 (schematic raw writer) both established the pattern: "mutate IR, derive file." v6.0 generalizes this to "conversation IS the IR."
- **Pattern Compliance:** ✅ Follows — Phases 173, 180, 181-185 all align.
- **Recommendation:** Continue. This is the strongest architectural decision in v6.0.

#### FoundationModels Availability Fallback (Tier 1 Domain Authority)
- **Category:** error_message
- **Historical Context:** Phase 98 AI routing strategy — assume model unavailable, route deterministically. Same pattern applies to FoundationModels.
- **Pattern Compliance:** ✅ Follows — Phase 164 implements graceful degradation.
- **Recommendation:** Follow Phase 98's `StrategyValidator` pattern for runtime safety.

#### PyInstaller + Code Signing Hardship
- **Category:** error_message
- **Historical Context:** Multiple HN/Reddit threads, KiCad forum posts about `killed: 9` on PyInstaller apps. v5.x had similar issue with binary distribution.
- **Pattern Compliance:** ✅ Follows — Phase 162 Task 2 follows `codesign --force --deep` pattern.
- **Recommendation:** Clean-machine test is mandatory, not optional.

### Anti-Patterns Detected

#### "Stub for now, real later"
- **Problem:** Stubs become permanent. Code rots around them.
- **Solution:** Either implement fully OR block the phase.
- **Current Violations:** Phase 181 (P0-02), Phase 167 (P1-02).
- **Recommendation:** Apply SLC rule: NO stubs in production code.

#### "Bundling GPL tools to simplify install"
- **Problem:** App Store rejection, GPL contamination.
- **Solution:** External install requirement.
- **Current Violations:** Phase 162 (P0-01).
- **Recommendation:** External install is the only path.

**Rickfucius Decision:** ⚠️ DOCUMENT DEVIATION — Phase 162 GPL bundling must be removed (not just documented). Phase 181 stubs must be removed (not just flagged).

---

## SLC Validation (Slick Rick)
**Status:** ❌ FAIL

### SLC Anti-Patterns Detected
- **Stubs in production code:** 2 (Phase 167, Phase 181)
- **Workarounds:** 1 (Phase 162 kicad-cli bundling — workaround for "user doesn't have KiCad")
- **TODOs without tickets:** 0 (clean — all phases have plan IDs)
- **Contradictions with locked exclusions:** 1 (Phase 162 vs Out-of-Scope)

### SLC Decision: ❌ REJECT

**Reasoning:** Three SLC violations found, all P0 or P1. The v6.0 milestone CANNOT ship with stubs in Phase 181 or GPL bundling in Phase 162. Phase 167's stub-for-Phase-168 is borderline acceptable IF executed as a merged unit.

---

## Security Review (Rick C-137)
**Status:** ✅ PASS (with caveats)

### Vulnerabilities Found

None at HIGH confidence. The plans correctly address:
- HTTP MCP opt-in default off (Phase 163) ✅
- Auth token rotation + rate limiting (Phase 163) ✅
- BYOK zero proxying (Phase 166) ✅
- Keychain device-local default (Phase 166, modulo P1-05 ambiguity) ⚠
- Path traversal in MCP stdio (Phase 162 threat model) ✅
- Code signing verification (Phase 162) ✅
- Blast radius scoped to user directories (Phase 162) ✅

### Security Summary
- High: 0
- Medium: 1 (P1-05 BYOK Keychain default ambiguity)
- Low: 1 (P1-06 Phase 203 missing threat model)

**Security Decision:** ✅ APPROVE (with P1-05 and P1-06 fixes as conditions)

---

## Code Quality Review (Rick Sanchez)
**Status:** ⚠️ PARTIAL PASS

### Plan Quality Assessment

**Strengths:**
- Every plan has objective, context references, tasks with files, verify gates, success criteria
- Threat models in 7/8 critical phases (missing only Phase 203 — P1-06)
- Pitfall prevention cross-references (most plans cite specific pitfalls)
- Stupid-proof augmentations baked into success criteria
- Fastlane Phase 203 is exemplary (6 lanes, match integration, snapshot automation)

**Weaknesses:**
- Dependency graph errors (P0-03 Phase 202, P2-02 Phase 175)
- Stub anti-patterns (P0-02 Phase 181, P1-02 Phase 167)
- Phase 162 contradicts its own sibling phase (P0-01)
- ROADMAP progress table incomplete (P0-04)

### Code Summary
- Critical: 4 (all P0)
- High: 6 (P1)
- Medium: 6 (P2)
- Low: 3 (P3)

**Code Decision:** ❌ REJECT — fix P0 blockers before Gate 1

---

## Design Review (Rick Prime)
**Status:** ✅ PASS

**Review Mode:** Systematic (80%) + Avant-Garde ULTRATHINK (20%)

### Findings

**Systematic:**
- Liquid Glass visual language consistently applied (Phase 171) ✅
- 4-variant snapshot tests baked in (Phase 192) ✅
- Dynamic Type XXXL tested (Phase 195) ✅
- A11Y labels/hints enforced via SwiftLint (Phase 201) ✅
- Stupid-proof recovery paths specified for most failure modes ✅

**Avant-Garde ULTRATHINK:**
- Psychological Impact: 32/40 — Liquid Glass + conversation-as-source-of-truth is distinctive
- Technical Execution: 36/40 — Fastlane + Obdurate Runtime + Event Sourcing is committed
- Design Innovation: 30/40 — Native Apple alignment is correct, but not avant-garde
- Production Viability: 38/40 — Plan quality is high, dependencies are mostly correct

**Avant-Garde Score:** 136/160
**Verdict:** ✅ AVANT-GARDE EXCELLENCE

**Design Decision:** ✅ APPROVE

---

## Apple Platform Review (Apple Elitist Rick)
**Status:** ✅ PASS

### Deprecated APIs Found
None — no GCGamepad, no OpenGL ES, no UIWebView references in any plan.

### Swift 6 Concurrency
- Phase 162 uses `Task.detached` for shutdown ✅
- Phase 164 uses async/await for availability checks ✅
- Phase 187 uses async GroupActivities API ✅

### Platform Optimization
- FoundationModels availability check at launch ✅ (Phase 164)
- MLX-Swift Metal acceleration with VRAM detection ✅ (Phase 164 Task 3)
- CloudKit private DB with explicit VersionedSchema ✅ (Phase 177)
- CKShare with proper userRole checks ✅ (Phase 188)
- Group Activities with FaceTime share sheet ✅ (Phase 187)
- iCloud Drive bundle via NSFileCoordinator ✅ (Phase 190)

**Apple Decision:** ✅ APPROVE

---

## Embedded/Daemon Review (Raspberry Pi Rick)
**Status:** ⚠️ PARTIAL PASS

### Subprocess Lifecycle
- Phase 162 ProcessManager has spawn/healthCheck/shutdown ✅
- Crash loop detection (5 in 60s) ✅
- 30-second watchdog for stdio deadlock ✅
- SIGTERM graceful + SIGKILL force ✅

### Concerns
- Phase 162 hardcodes Python path (P3-01)
- Phase 167 stub call_tool (P1-02) — daemon will return "not implemented" for real RPC calls between Phase 167 and 168 execution

**Embedded Decision:** ⚠️ DOCUMENT DEVIATION — Phase 167+168 must execute as merged unit.

---

## Fresh Eyes Cross-Domain (Compliance Rick, KiCad Rick)
**Status:** ⚠️ FINDINGS

### Compliance Rick (Regulatory view on app code)
- App Store GPL risk correctly identified (Phase 163) ✅
- BUT Phase 162 reintroduces the risk (P0-01) ❌
- Privacy policy mention for FoundationModels (PITFALLS.md Security Mistakes table) — not explicitly in any plan. **P2-NEW: Add privacy policy requirement to Phase 164 or 175.**

### KiCad Rick (PCB view on app code)
- KiCad file generation uses volta ops (Phase 182) ✅
- ERC/DRC gates enforced before file marked valid (Phase 185) ✅
- External KiCad install requirement is correct architecture (Phase 163) ✅
- Hash gold master tests prevent generative drift (Phase 184) ✅

**Fresh Eyes Decision:** ⚠️ FIX P0-01 (GPL conflict is the standout finding).

---

## Final Council Decision

**Evil Morty's Ruling:** **❌ REJECT**

### Decision Summary
- **SLC Validation:** ❌ FAIL (3 violations)
- **Security Review:** ✅ PASS (with conditions)
- **Code Quality:** ❌ REJECT (4 P0 blockers)
- **Design Review:** ✅ APPROVE
- **Apple Platform:** ✅ APPROVE
- **Embedded/Daemon:** ⚠️ PARTIAL
- **Historical Context:** ⚠️ DOCUMENT DEVIATION
- **Fresh Eyes:** ⚠️ FIX P0-01

### All Issues to Fix Before Gate 1 (ALL severities block execution)

**P0 (Must fix before any execution):**
1. **P0-01** — Remove `Bundle kicad-cli` from Phase 162 Task 1 (GPL violation)
2. **P0-02** — Re-plan Phase 181 to NOT ship ImportError stubs (block phase until v5.0 OR ship dataclasses only)
3. **P0-03** — Update Phase 202 `depends_on:` with Memory + Collab + Group Activities deps
4. **P0-04** — Add Phase 203 to ROADMAP progress table; update counts (43 phases, 138 reqs)

**P1 (Must fix before related track executes):**
5. **P1-01** — Fix ROADMAP "100% coverage" claim; add GOV-09, PIPE-03, TEST-12 to plans
6. **P1-02** — Merge Phase 167+168 execution OR add minimal real `call_tool` to Phase 167
7. **P1-03** — Update PITFALLS.md pitfall-to-phase mapping table (corrected version above)
8. **P1-04** — Fix ROADMAP Pitfall 7 phase reference (197 → 164)
9. **P1-05** — Fix Phase 166 BYOK Keychain default (iCloud sync is opt-IN, not opt-OUT)
10. **P1-06** — Add threat model section to Phase 203

**P2 (Must fix before merge):**
11. **P2-01** — Re-run stupid-proof audit on 6 new requirements
12. **P2-02** — Update Phase 175 depends_on to include 172, 173, 174
13. **P2-03** — Document Track H (Phases 191-200) as parallel-executable from Phase 161
14. **P2-04** — Add Pitfall 11 (snapshot fragility) to PITFALLS.md
15. **P2-05** — Add per-requirement verification matrix to Phase 203
16. **P2-06** — Add hardware budget note to Phase 187 (2+ physical Macs for Group Activities)

**P3 (Advisory):**
17. **P3-01** — Use PyInstaller `--paths` flag instead of sys.path hacks in Phase 162
18. **P3-02** — Parameterize Appfile bundle IDs via ENV (defer to v1.x)
19. **P3-03** — Clarify Phase 181 "stub" → "architecture-only phase"

### Council Consensus

**Wave Alpha (Core):**
- Rick Sanchez (Code): ❌ REJECT
- Rick C-137 (Security): ✅ APPROVE (with conditions)
- Slick Rick (SLC): ❌ REJECT
- Evil Morty: ❌ REJECT

**Wave Beta (Wisdom):**
- Rick Prime (Design): ✅ APPROVE
- Rickfucius (Historian): ⚠️ DOCUMENT DEVIATION

**Wave Gamma (Domain):**
- Apple Elitist Rick: ✅ APPROVE
- Raspberry Pi Rick: ⚠️ PARTIAL
- embedded-firmware-rick: ⚠️ DOCUMENT DEVIATION

**Wave Delta (Pipeline):**
- architect: ❌ REJECT (dependency graph errors)
- gsd-plan-checker: ❌ REJECT (3 missing requirements)
- gsd-roadmapper: ❌ REJECT (traceability table empty)

**Wave Epsilon (Fresh Eyes):**
- kicad-rick: ✅ APPROVE (KiCad architecture correct)
- compliance-rick: ❌ REJECT (P0-01 GPL conflict)

**Final:**
- **Evil Morty:** ❌ REJECT

---

## Required Re-Plan Workflow

Per bureaucracy §7.5: Plans cannot execute until Council returns clean.

1. **Author updates Phase 162, 181, 202, ROADMAP, PITFALLS, Phase 166, Phase 167, Phase 175, Phase 203** with fixes above.
2. **Author re-runs `/council-of-ricks --plans 161-203`** (this command).
3. **Council reviews ONLY the diff** — fast turnaround, focused on P0/P1 fixes.
4. **Council returns APPROVE** → execution may begin.
5. **Max 3 revision iterations** before escalation gate (proceed/manual/abandon).

---

**Council Motto:** "43 plans. 6 waves. Zero compromises. Every phase reviewed. Every conflict surfaced. Stubs blocked. GPL blocked. Evil Morty makes the final call. No appeals until clean."

**Review Completed:** 2026-07-07
**Review Duration:** ~45 minutes
**Next Action:** Author addresses P0-01 through P0-04, then re-submits for Council Gate 1 re-review.
