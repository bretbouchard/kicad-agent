# Council of Ricks — Gate 2 Execution Review (Task 6 Sandbox Cleanup)

**Phase:** 253 (Routing Plugin System)
**Task:** 6 — Sandbox Cleanup Sweep (4 commits)
**Review date:** 2026-07-28
**Reviewer:** Evil Morty (Council of Ricks Orchestrator)
**Plan:** `.planning/phases/253-routing-plugin-system/TASK6_SANDBOX_CLEANUP_PLAN.md`

## Commits under review

| # | SHA | Title |
|---|-----|-------|
| 6a | `f33e876` | refactor(ki-cad): delete KiCadCLIDetector + KiCadInstallStatus |
| 6b | `d89d63a` | refactor(easy-eda): rewrite provider to direct web API |
| 6c+6e | `fdc56ee` | refactor(routing): bundle freerouting.jar + sandbox-clean Java resolution |
| 6d | `14210a7` | test(erc): replace batch_erc_parity.py with Swift ERCParityTests |

## Sandbox discipline (codified in `PROJECT.md` `cf1fb3b`)

> All subprocesses and bundled tools (Python daemon, Freerouting JAR, helper binaries) must resolve from `Bundle.main.resourcePath`. No host-filesystem lookups (e.g. `/Applications/KiCad/`), no `which`/PATH resolution, no `pip install` requiring user environment.

---

## SLC Validation (Slick Rick)

**Status:** PARTIAL PASS

### SLC Anti-Patterns Detected

- **Workarounds**: 0 found in commits under review
- **Stub methods**: 1 found (P1 — see 6b finding below)
- **TODO/FIXME without tickets**: 0 new (pre-existing TODOs in unrelated files not counted)
- **Incomplete implementations**: 1 found (P1 — EasyEda conversion logic missing)

### SLC Criteria Assessment

- [x] **Simple**: Sandbox cleanup is clear in purpose. Each commit removes one violation class.
- [ ] **Lovable**: EasyEda provider produces non-functional CAD models (empty KiCad envelopes with no geometry). Users downloading parts will get unusable files.
- [x] **Complete**: KiCad detector deletion, Freerouting JAR bundling, and ERC parity test replacement are complete.
- [x] **Secure**: No host-filesystem lookups remain in `macos-app/Sources/Volta/Routing/`. No `which`/PATH resolution. JAR is LFS-tracked with verified SHA-256.

**SLC Decision**: REJECT — stub method violation in EasyEda provider

---

## Code Quality Review (Rick Sanchez)

### 6a (f33e876) — KiCadCLIDetector Deletion

**Status**: PASS

- `KiCadCLIDetector.swift` (292 LOC), `KiCadInstallStatus.swift` (102 LOC), `KiCadCLIDetectorTests.swift` (429 LOC) — all deleted
- `ProcessRunner.swift` extracted to `Common/` — protocol preserved, `RealProcessRunner` intact
- `ValidationPanel.swift:127` — `statusBadge()` returns exactly "Native ERC only — DRC via KiCad app" (matches plan requirement)
- `LiquidGlassShell.swift:184-189` — "prefer daemon" preference dropped, native Swift renderer only
- `QualityTesting.swift:72` — `KiCadCLIDetectorTests` removed from TestRegistry
- `PostOpGate.swift:9` — comment updated "via kicad-cli" to "via native Swift"
- `grep -rn "KiCadCLIDetector|KiCadInstallStatus|kicad_cli_check" macos-app/Sources/` — 0 functional matches (1 comment reference in ProcessRunner.swift header)

### 6b (d89d63a) — EasyEda Provider Rewrite

**Status**: FAIL — see P1 finding below

- `EasyEdaAPI.swift` (214 LOC) — URLSession + strict Codable, `EasyEdaError.responseSchemaMismatch` exists with raw body
- `EasyEdaProvider.swift` — no shell-out, no feature flag, no `findEasyEda2Kicad()`
- `EasyEdaAPITests.swift` (319 LOC) — URLProtocol stubs, offline mocking
- `EasyEdaErrorTests.swift` (48 LOC) — all error cases covered
- `ProviderPriority.swift` — `"easyeda2kicad"` removed from array, `"easyeda"` remains (functional change, verified intended)
- Doc comment cleanups in JLCPCB/LCSC/Octopart/CADModelProvider/CADModelRef/ComponentSource — all correct
- `grep -rn "easyeda2kicad" macos-app/Sources/` — 0 matches (confirmed)

### 6c+6e (fdc56ee) — Freerouting JAR Bundling + Java Resolution

**Status**: PASS

- `.gitattributes` — LFS tracking for `macos-app/Resources/freerouting.jar`
- `git lfs ls-files` — `f5ed374182 * macos-app/Resources/freerouting.jar` (LFS-tracked)
- `shasum -a 256` — `f5ed374182900ccc78e473518bbb9f6b869f4a07159495f663a76f52bb10523b` (matches commit message)
- `FreeroutingProvider.swift:319-329` — `jarPath()` uses `Bundle.main.url(forResource:withExtension:)` first, `$FREEROUTING_JAR_PATH` second (dev escape hatch only)
- `FreeroutingProvider.swift:288-314` — `probeJava()` uses `$JAVA_HOME` + `/usr/libexec/java_home` (no `which`/PATH)
- `defaultJARSearchPaths` and `locateJAR()` deleted — `grep -rn "defaultJARSearchPaths|locateJAR" macos-app/Sources/Volta/Routing/` returns 0 matches
- `project.yml` — JAR added to resources build phase
- No `#if DEBUG` hardcoded paths (grep confirms)
- `grep -rn "/Users/bretbouchard/apps/freerouting" macos-app/Sources/` — 0 matches
- `grep -rn "/usr/bin/env.*which|/usr/bin/which" macos-app/Sources/Volta/Routing/` — 0 matches

### 6d (14210a7) — ERC Parity Tests

**Status**: PASS

- `batch_erc_parity.py` (284 LOC) deleted from `.planning/phases/234a-corpus-and-driver/scripts/`
- `ERCParityTests.swift` (248 LOC) — real Swift test using `Process` to spawn `erc-cli`, `JSONDecoder` to parse, `NativeERC.run()` for direct comparison
- `erc-cli/main.swift` — comment-only change (verified: only doc comments updated, no code logic changed)
- `grep -rn "batch_erc_parity" macos-app/` — 0 matches (confirmed)

---

## Security Review (Rick C-137)

**Status**: PASS

- No host-filesystem lookups in `macos-app/Sources/Volta/Routing/`
- No `which`/PATH resolution in routing pipeline
- JAR verified via SHA-256 checksum
- `EasyEdaAPIClient` uses `URLSessionConfiguration.ephemeral` (no persistent cookies/cache)
- Default URLSession trust evaluation (system root CAs) — acceptable for public API with no credentials transmitted
- No new secret exposure or credential handling introduced

---

## Architecture Review (Rick Prime)

**Status**: PASS with notes

- `ProcessRunner` extraction to `Common/ProcessRunner.swift` is architecturally sound — shared abstraction used by `FreeroutingProvider` and (previously) `EasyEdaProvider` tests
- `EasyEdaAPIClient` design is clean: strict Codable, envelope-or-direct decode, `Sendable` conformance, injectable `URLSession` for testing
- `EasyEdaError` taxonomy is well-structured: `networkError`, `httpError`, `responseSchemaMismatch`, `incompleteProduct`
- `ERCParityTests` correctly uses `Process` for CLI subprocess + in-process `NativeERC.run()` comparison
- Note: `probeJava()` now uses `Process` directly instead of `ProcessRunner` protocol — see P2 finding

---

## Historical Context (Rickfucius)

- Phase 163 introduced `KiCadCLIDetector` for external CLI detection — correct at the time, now sandbox-violating per `cf1fb3b`
- `easyeda2kicad` was a Python CLI that performed full EasyEDA-to-KiCad format conversion (SVG to symbol, JSON to footprint). The new web API client fetches raw API payloads but does NOT replicate the conversion logic.
- `batch_erc_parity.py` was a Phase 234A Python harness — replacing it with Swift `ERCParityTests` aligns with the Python-to-Swift migration pattern established in Phase 234B.

---

## Findings

### [P1] COMMIT 6b: EasyEda provider stub envelopes produce non-functional CAD models

- **Commit**: d89d63a
- **Category**: SLC
- **File**: `macos-app/Sources/Volta/Providers/EasyEda/EasyEdaProvider.swift:126-151`
- **Issue**: `makeKiCadSymbolLib()` and `makeKiCadFootprint()` produce minimal KiCad-format envelopes that pass the validation gate (`(kicad_symbol_lib` and `(module` prefix checks) but contain NO actual CAD geometry. The symbol has a single zero-length hidden pin at origin. The footprint has no pads, no outline, no courtyards. The `EasyEdaSymbol.svg` field (containing the real symbol SVG from the API) and `EasyEdaFootprint.data` field (containing the real footprint JSON) are fetched but NEVER written to disk or used. The prior `easyeda2kicad` CLI performed full format conversion; the new implementation fetches data but discards it, writing empty envelopes instead.
- **Evidence**:
  ```swift
  // makeKiCadSymbolLib produces:
  (kicad_symbol_lib
      (version 20211014)
      (generator "easyeda-volta")
      (symbol "S001"
          (pin unspecified (at 0 0 0) (length 0) hide yes))
          (symbol "C2040" (extends "RP2040"))
      )
  )
  // makeKiCadFootprint produces:
  (module "Footprint"
      (layer F.Cu)
      (descr "Generated by Volta from EasyEDA F001")
      (fp_text reference "C2040")
  )
  ```
  The `symbol.svg` and `footprint.data` fields are fetched via `api.fetchSymbol()` and `api.fetchFootprint()` but never appear in the output files.
- **Resolution**: ADDED-AS-PHASE
- **Suggested fix**: Implement real EasyEDA-to-KiCad format conversion (parse `EasyEdaSymbol.svg` into KiCad symbol pins/graphics, parse `EasyEdaFootprint.data` JSON into KiCad pad/outline/courtyard geometry). Alternatively, if conversion is out of scope for Phase 4, document the provider as metadata-only and remove `.footprints` and `.symbols` from `capabilities` until conversion is implemented. The plan's assumption that "the easyeda2kicad CLI is just a wrapper around [the API]" was incorrect — the CLI performed significant format conversion that is not replicated here.

### [P2] COMMIT 6c+6e: probeJava() blocks cooperative thread pool

- **Commit**: fdc56ee
- **Category**: Architecture
- **File**: `macos-app/Sources/Volta/Routing/FreeroutingProvider.swift:297-313`
- **Issue**: `probeJava()` is an `async` function that calls `process.waitUntilExit()` synchronously, blocking a Swift cooperative thread pool thread. The previous implementation used `ProcessRunner` which dispatched to `DispatchQueue.global()`. Blocking async context can starve the cooperative thread pool under load.
- **Evidence**:
  ```swift
  func probeJava() async -> String? {
      // ...
      try process.run()
      process.waitUntilExit()  // <-- BLOCKS cooperative thread
      // ...
  }
  ```
- **Resolution**: ADDED-AS-PHASE
- **Suggested fix**: Wrap `Process` execution in `withCheckedThrowingContinuation` + `DispatchQueue.global().async` (same pattern as `RealProcessRunner`), or extract to a `JavaLocator` type that uses the injected `ProcessRunner`.

### [P2] COMMIT 6c+6e: probeJava() bypasses ProcessRunner protocol

- **Commit**: fdc56ee
- **Category**: Architecture / Test
- **File**: `macos-app/Sources/Volta/Routing/FreeroutingProvider.swift:288-314`
- **Issue**: `probeJava()` uses `Process` directly instead of the injected `ProcessRunner` protocol. This makes Java detection untestable — tests cannot mock the `/usr/libexec/java_home` subprocess result. The `FreeroutingProcessRunner` mock in `FreeroutingProviderTests.swift` still has a `whichResults` field that is now dead code (test `availabilityNoJar` passes `whichResults: [:]`). Additionally, the plan called for a separate `JavaLocator.swift` file (~80 LOC) and `JavaLocatorTests.swift` (~100 LOC) — neither was created.
- **Evidence**: `probeJava()` instantiates `Process()` directly; `FreeroutingProcessRunner.whichResults` is never read by any code path in the new implementation.
- **Resolution**: ADDED-AS-PHASE
- **Suggested fix**: Route `probeJava()` through `ProcessRunner` (e.g., `runner.run(executable: "/usr/libexec/java_home", arguments: [])`). Extract to `JavaLocator.swift` per plan. Create `JavaLocatorTests.swift` with stubbed output.

### [P2] COMMIT 6b: CacheManagerTests uses stale provider name "easyeda2kicad"

- **Commit**: d89d63a (missed update)
- **Category**: Test
- **File**: `macos-app/Tests/VoltaTests/Cache/CacheManagerTests.swift:104`
- **Issue**: Test calls `cache.cadCacheDir(provider: "easyeda2kicad", ...)` but the provider was renamed to `"easyeda"`. The test still passes (it only checks the path contains "C2040") but uses a provider name that no longer exists in production.
- **Evidence**:
  ```swift
  let dir = cache.cadCacheDir(provider: "easyeda2kicad", lcscPartNumber: "C2040")
  ```
- **Resolution**: IMPLEMENTED (should be fixed in this phase)
- **Suggested fix**: Change `"easyeda2kicad"` to `"easyeda"`.

### [P3] COMMIT 6b: MergeEngineV2Tests stale comment

- **Commit**: d89d63a (missed update)
- **Category**: Doc
- **File**: `macos-app/Tests/VoltaTests/Providers/Merge/MergeEngineV2Tests.swift:70`
- **Issue**: Comment says "Default order: digikey < octopart < mouser < easyeda2kicad < easyeda < jlcparts" but `easyeda2kicad` was removed from the priority array.
- **Resolution**: IMPLEMENTED (should be fixed in this phase)
- **Suggested fix**: Update comment to "Default order: digikey < octopart < mouser < easyeda < jlcparts".

### [P3] COMMIT 6c+6e: Stale FreeroutingError messages

- **Commit**: fdc56ee
- **Category**: Doc
- **File**: `macos-app/Sources/Volta/Routing/FreeroutingProvider.swift:51,54`
- **Issue**: `javaNotFound` message says "ensure `java` is on PATH" — but the whole point of 6e was to remove PATH-based resolution. `jarNotFound` message says "Download from freerouting.app or `brew install freerouting`" — but the JAR is now BUNDLED.
- **Resolution**: IMPLEMENTED (should be fixed in this phase)
- **Suggested fix**: Update `javaNotFound` to reference `$JAVA_HOME` or `java_home`. Update `jarNotFound` to say "Bundled freerouting.jar not found — the app bundle may be corrupted."

### [P3] COMMIT 6d: ERCParityTests typo "ponystail"

- **Commit**: 14210a7
- **Category**: Style
- **File**: `macos-app/Tests/VoltaTests/ERC/ERCParityTests.swift:110` (approx)
- **Issue**: Comment says `// ponystail:` instead of `// ponytail:`.
- **Resolution**: IMPLEMENTED (should be fixed in this phase)
- **Suggested fix**: Fix spelling to `ponytail`.

### [P3] COMMIT 6c+6e: JavaLocator.swift / JavaLocatorTests.swift not created (plan deviation)

- **Commit**: fdc56ee
- **Category**: Architecture
- **File**: N/A (files not created)
- **Issue**: Plan called for `macos-app/Sources/Volta/Routing/JavaLocator.swift` (~80 LOC) and `macos-app/Tests/VoltaTests/Routing/JavaLocatorTests.swift` (~100 LOC). Neither was created — `probeJava()` logic was inlined in `FreeroutingProvider.swift` instead.
- **Resolution**: SUPERSEDED-BY-ALTERNATIVE (inline implementation is functionally equivalent; separate file extraction deferred to refactor phase)
- **Suggested fix**: Accept the inline implementation as a deviation. If testability becomes a concern, extract to `JavaLocator.swift` per the P2 finding above.

### [P3] COMMIT 6a: Daemon kicad_cli_check dead code (out of scope)

- **Commit**: f33e876 (not cleaned up)
- **Category**: Architecture
- **File**: `macos-app/daemon/handlers.py:221`, `macos-app/daemon/tests/test_kicad_cli_and_http.py`
- **Issue**: The daemon still has `def kicad_cli_check(...)` registered as an MCP method, which calls `shutil.which("kicad-cli")` and probes `/Applications/KiCad/kicad-cli` (host-filesystem lookups). The Swift app no longer calls this handler (ValidationPanel dropped the MCP call), making it dead code. Plan line 22 explicitly says "The Python daemon is NOT a violation under the new rule — No action needed."
- **Resolution**: DEFERRED-TO-NAMED-TARGET (daemon cleanup tracked for Phase 5 Python-to-Swift migration per plan "Out of scope" section)
- **Suggested fix**: Track for Phase 5. Remove `kicad_cli_check` from `handlers.py` method registry when daemon is migrated or decommissioned.

---

## Council Consensus

**Wave Alpha (Core):**
- Rick Sanchez (Code): REJECT (P1 stub method)
- Rick C-137 (Security): PASS (no sandbox violations introduced)
- Slick Rick (SLC): REJECT (stub method violation)

**Wave Beta (Wisdom):**
- Rick Prime (Design/Architecture): PASS with notes (probeJava thread blocking + ProcessRunner bypass)
- Rickfucius (Historian): Patterns confirm easyeda2kicad performed conversion; gap is real

**Final:**
- Evil Morty: **REJECT**

---

## Verdict: REJECT

**Summary**: 9 findings (0 P0, 1 P1, 3 P2, 5 P3). The P1 finding (EasyEda provider stub envelopes) blocks merge. The `makeKiCadSymbolLib` and `makeKiCadFootprint` functions produce non-functional CAD models — they pass the validation gate's prefix check but contain no actual geometry (no pins, no pads). The `EasyEdaSymbol.svg` and `EasyEdaFootprint.data` fields are fetched from the API but never written to disk. The prior `easyeda2kicad` CLI performed full EasyEDA-to-KiCad format conversion that is not replicated here. The plan's assumption that "the CLI is just a wrapper around the API" was incorrect.

The P1 must be resolved before merge: either implement real format conversion, or document the provider as metadata-only (remove `.footprints` and `.symbols` from `capabilities`) until conversion lands in a follow-up phase. All other findings (P2/P3) are tracked with ADDED-AS-PHASE or IMPLEMENTED resolutions.

**Finding counts**: P0=0, P1=1, P2=3, P3=5

---

**Review completed**: 2026-07-28
