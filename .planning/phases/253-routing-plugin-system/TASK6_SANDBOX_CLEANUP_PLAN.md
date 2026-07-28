# Task 6 — Sandbox Cleanup Sweep

**Phase:** 4 (Routing Plugin System)
**Status:** Planning — Council Gate 1 in progress, 16 findings addressed, awaiting re-review
**Created:** 2026-07-28
**Depends on:** PROJECT.md sandbox rule (already shipped in `cf1fb3b`). Sub-tasks 6a (delete KiCadCLIDetector), 6b (EasyEda rewrite), and 6d (replace Python parity test) are **independent of Task 2** and can execute in parallel with it. Only 6c's end-to-end smoke test depends on Task 2's native DSN pipeline (the code changes in 6c — bundling the JAR, updating `jarPath()` — are independent). Sub-task 6e (Java resolution) is independent.
**Goal:** Apply the new sandbox rule (`cf1fb3b`) to the remaining violations identified in the rethink — make every code path bundle-resolvable or sandbox-clean.

---

## Why this exists

`cf1fb3b` codified the sandbox discipline in `PROJECT.md`. But the code has four surviving violations that need cleanup commits. Each is independently shippable and revertable; together they bring Volta into compliance with the rule.

The violations were enumerated in Volta Component Integration thread [10] (event by Fizz, 2026-07-28T05:22:41+00:00):

1. `KiCadCLIDetector` + `KiCadInstallStatus` — look at `/Applications/KiCad/kicad-cli` and `which kicad-cli`
2. `ValidationPanel` `kicad_cli_check` — calls into external kicad-cli
3. `EasyEdaProvider` `easyeda2kicad` fallback — pips into user installs
4. `/Users/bretbouchard/apps/freerouting/freerouting.jar` hardcoded path — outside any bundle

The Python daemon (`ProcessManager` etc.) is **NOT** a violation under the new rule — it runs as a bundled subprocess in `.app/Contents/Resources/`. No action needed.

---

## Sub-tasks

### 6a — Delete `KiCadCLIDetector` + `KiCadInstallStatus`

**Files to delete:**
- `macos-app/Sources/Volta/KiCad/KiCadCLIDetector.swift` (~262 LOC)
- `macos-app/Sources/Volta/KiCad/KiCadInstallStatus.swift` (~80 LOC)

**Files to modify:**
- `macos-app/Sources/Volta/Views/ValidationPanel.swift:121-135` — drop the `kicad_cli_check` MCP call, replace with a status badge. **Functional delta assessment (Council M-02):** kicad-cli DRC provided external Design Rule Check (clearance, trace width, via drill, etc.). NativeERC provides Electrical Rule Check (unconnected pins, power-pin shorts, etc.). These are complementary, not equivalent. The replacement badge text MUST be **"Native ERC only — DRC via KiCad app"** (honest about scope gap). NativeERC remains primary; users needing full DRC open the project in KiCad app. Document this in the badge tooltip.
- `macos-app/Sources/Volta/Governance/PostOpGate.swift:9` — change "via kicad-cli" comment to "via native Swift"
- `macos-app/Sources/Volta/Views/LiquidGlassShell.swift:187` — flip "Prefer daemon (real kicad-cli) when MCP is wired; otherwise fall back" → native ERC/DRC is the only path, drop the preference language
- `macos-app/project.yml` — drop the two file references from the Sources list

**Acceptance:**
- `grep -rn "KiCadCLIDetector\|KiCadInstallStatus\|kicad_cli_check" macos-app/Sources/` returns 0 matches
- ValidationPanel renders without crashing (uses only `NativeERC` results)
- Badge text reads "Native ERC only — DRC via KiCad app" — visible in screenshot test
- `xcodebuild` succeeds — no missing-file build errors

### 6b — Rewrite `EasyEdaProvider` to direct web API (no fallback)

Current state (`macos-app/Sources/Volta/Providers/EasyEda/EasyEdaProvider.swift`): shells out to `easyeda2kicad` Python CLI, 7 search paths, tells user to `pip install easyeda2kicad`.

**Replacement strategy:** hit the EasyEDA web API directly. The `easyeda2kicad` CLI is just a wrapper around:
- `https://easyeda.com/api/products/{lcscId}` — product metadata
- `https://easyeda.com/api/eda/product/symbol/{...}` — schematic symbol SVG
- `https://easyeda.com/api/eda/product/footprint/{...}` — PCB footprint JSON

For LCSC IDs only (which is how `EasyEdaProvider` works — no keyword search).

**Council C-02 — NO FEATURE FLAG, NO SHELL-OUT FALLBACK:** The previous plan had a feature flag `EasyEdaProvider.useWebAPI` that fell back to the `easyeda2kicad` shell-out path when set to false. **This is a workaround that violates SLC** — keeping a sandbox-violating code path "just in case" defeats the purpose of the cleanup. The web API is the ONLY path. If it breaks, ship a fix. The shell-out path is deleted entirely. **No fallback flag.**

**Council M-04 — Schema validation:** The EasyEDA web API is undocumented and may change shape. Mitigation:
1. Use Swift `Codable` for response decoding with strict schema types (no loose `Any` decoding).
2. If response fails to decode (API shape changes), throw `EasyEdaError.responseSchemaMismatch(rawResponse:)` with the raw response body for debugging.
3. Log all API responses (with PII redaction) at `.debug` level for the first 7 days post-launch to catch breaking changes early.
4. Add a `CIWeekly/easyeda_ping_test` to the CI matrix that pings the API weekly and fails the build on schema drift.

**Files:**
- `macos-app/Sources/Volta/Providers/EasyEda/EasyEdaProvider.swift` — rewrite to use `URLSession` + `Codable` decoding (no subprocess)
- `macos-app/Sources/Volta/Providers/EasyEda/EasyEdaAPI.swift` — new file, ~150 LOC for the API client + response models with strict `Codable` types
- **Delete `findEasyEda2Kicad()`** and ALL `which`-based discovery
- **Delete `pip install easyeda2kicad`** error message and the shell-out `Process` invocation
- **Delete `useWebAPI` feature flag** entirely — no fallback to shell-out path
- `macos-app/Tests/VoltaTests/Providers/EasyEda/` — add `EasyEdaAPITests.swift` with `URLProtocol` stub for offline tests
- `macos-app/Tests/VoltaTests/Providers/EasyEda/EasyEdaErrorTests.swift` — schema mismatch error tests

**Acceptance:**
- `grep -rn "easyeda2kicad\|findEasyEda2Kicad\|pip install easyeda\|useWebAPI" macos-app/Sources/` returns 0 matches (catches feature flag + shell-out code)
- `EasyEdaProvider.availability` no longer queries the filesystem or runs subprocesses
- API tests pass with stubbed HTTP responses (no real EasyEDA calls in CI)
- `EasyEdaError.responseSchemaMismatch` thrown on schema-drift test fixture

### 6c — Move `freerouting.jar` into `.app/Contents/Resources/` (Git LFS tracked)

Current state: hardcoded `/Users/bretbouchard/apps/freerouting/freerouting.jar` lookup in `FreeroutingProvider`. Outside any bundle.

**Replacement strategy:**
1. **Set up Git LFS first (Council H-02).** Add `macos-app/Resources/freerouting.jar filter=lfs diff=lfs merge=lfs -text` to `.gitattributes` BEFORE the binary commit. If `git lfs` is not yet initialized for the repo, run `git lfs install` and `git lfs track "macos-app/Resources/freerouting.jar"` as part of 6c. Once a binary is in git history without LFS, it's permanently bloated — LFS migration does NOT retroactively shrink history.
2. Copy `freerouting.jar` from `/Users/bretbouchard/apps/freerouting/` (or its known canonical source — verify with Bret) into `macos-app/Resources/freerouting.jar` and commit it.
3. Update `macos-app/project.yml` to declare it as a bundled resource for the .app target.
4. Update `FreeroutingProvider` JAR resolution to look up via `Bundle.main.url(forResource: "freerouting", withExtension: "jar")` first; for dev builds only, fall back to `ProcessInfo.processInfo.environment["FREEROUTING_JAR_PATH"]` (env var, NOT a hardcoded path in source). The env var is set by the developer at runtime (`export FREEROUTING_JAR_PATH=/path/to/freerouting.jar && xcodebuild ...`) — the source code contains no dev path string. **No `#if DEBUG` fallback with hardcoded paths** (Council N-01: `grep -rn` does not skip `#if DEBUG` blocks, so a hardcoded debug path would fail the acceptance grep).
5. **Delete the `defaultJARSearchPaths` static array (FreeroutingProvider.swift:91-98) and the `locateJAR()` function (lines 321-338) entirely.** Replace `locateJAR()` callers with a single `Bundle.main` lookup. Removing `defaultJARSearchPaths` eliminates the `~/.volta/tools/freerouting.jar` path and all 6 host-filesystem search paths (Council N-02: the host-filesystem paths are all sandbox-rule violations).
6. Add a checksum verification step (already partially in `ProcessManager` pattern — borrow it).

**Files:**
- `macos-app/Resources/freerouting.jar` — new file (binary, ~57.7 MB). Verify SHA-256 in the commit message. Tracked via Git LFS.
- `.gitattributes` — add LFS tracking for the JAR before committing
- `macos-app/Sources/Volta/Routing/FreeroutingProvider.swift` — modify `jarPath()` lookup
- `macos-app/project.yml` — add resource declaration
- `macos-app/Tests/VoltaTests/Routing/FreeroutingProviderTests.swift` — add JAR-resolvable test

**Acceptance:**
- `grep -rn "/Users/bretbouchard/apps/freerouting" macos-app/Sources/` returns 0 matches (N-01: catches any hardcoded dev path, including in `#if DEBUG` blocks — there should be none)
- `grep -rn "defaultJARSearchPaths\|locateJAR\|\.volta" macos-app/Sources/Volta/Routing/` returns 0 matches (N-02: catches the deleted array/function and the `~/.volta` host-filesystem path)
- `git lfs ls-files` shows `macos-app/Resources/freerouting.jar` is LFS-tracked
- `freerouting.jar` is present at `macos-app/Resources/freerouting.jar`
- `Bundle.main.resourcePath/freerouting.jar` resolves in tests
- `FREEROUTING_JAR_PATH` env var is the only documented dev escape hatch (no string in source)
- FreeroutingProvider routes a real .kicad_pcb end-to-end via the bundled JAR (manual smoke test, Bret signs off)

**Binary in git (LFS-tracked):** the JAR is 57.7 MB. LFS keeps it out of working tree clones but the pointer file is in git. Acceptable per Volta's existing pattern (PyInstaller daemon is similar size — note: PyInstaller daemon should also be migrated to LFS in a follow-up; not in scope here).

### 6d — Replace `batch_erc_parity.py` with Swift test runner

Current state: `macos-app/Sources/erc-cli/main.swift` is a separate Swift CLI built for `batch_erc_parity.py` to compare Swift `NativeERC` vs Python `native_erc`. Pure Swift on the language axis but the test harness is Python.

**Replacement strategy:**
- Keep `erc-cli/main.swift` (it's pure Swift and produces JSON).
- **Definitive deletion (Council M-03):** `batch_erc_parity.py` exists at `.planning/phases/234a-corpus-and-driver/scripts/batch_erc_parity.py` (verified). Delete it.
- **Audit references:** Before deletion, `grep -rln "batch_erc_parity" .` across the entire repo (not just `macos-app/` and `tests/`). Check CI configs (`.github/`, `.gitlab-ci.yml`), Makefiles, shell scripts, and docs for callers. Update or remove any references found.
- Replace with `macos-app/Tests/VoltaTests/ERC/ERCParityTests.swift` — a Swift test that invokes `erc-cli` via `Process` and compares results against the Swift `NativeERC` directly. No Python in the loop.

**Files:**
- `.planning/phases/234a-corpus-and-driver/scripts/batch_erc_parity.py` — **DEFINITIVE DELETE** (verified path)
- Any CI config / Makefile / script referencing `batch_erc_parity` — update or remove
- `macos-app/Tests/VoltaTests/ERC/ERCParityTests.swift` — new file, ~200 LOC

**Acceptance:**
- `grep -rln "batch_erc_parity" .` returns 0 matches (full repo sweep, not just macos-app + tests)
- `ERCParityTests` runs and passes on a small corpus
- CI build green after deletion (no broken references)

### 6e — Resolve Java runtime sandbox-clean (Council C-01)

Current state: `FreeroutingProvider.probeJava()` (lines 289-317) calls `/usr/bin/env which java` and `/usr/bin/which java` — direct PATH resolution. After 6c (bundled JAR), the Java runtime is the last PATH-based lookup in the routing pipeline. The sandbox rule (`cf1fb3b`) prohibits `which`/PATH resolution.

**Replacement strategy:** Use `/usr/libexec/java_home` (macOS system framework — not PATH, not `which`, not subprocess lookup). This is a standard macOS helper that returns the active Java installation directory. It's a system framework call, not a host-filesystem search.

```swift
// Before (sandbox-rule violation):
func probeJava() -> URL? {
    // Tries /usr/bin/env which java, /usr/bin/which java, /usr/bin/java
    // Falls back to $JAVA_HOME, $PATH
}

// After (sandbox-clean):
func probeJava() -> URL? {
    // 1. Check $JAVA_HOME first (user-set env var, explicit user intent)
    if let home = ProcessInfo.processInfo.environment["JAVA_HOME"] {
        return URL(fileURLWithPath: "\(home)/bin/java")
    }
    // 2. Call /usr/libexec/java_home (macOS system framework)
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/usr/libexec/java_home")
    // ... execute, parse stdout for the JAVA_HOME path ...
    // 3. Fall back to /usr/bin/java as last resort (system path, fixed)
    return URL(fileURLWithPath: "/usr/bin/java")
}
```

**Why this is sandbox-clean:**
- `/usr/libexec/java_home` is a macOS-provided system framework binary at a fixed system path (not a host-filesystem search or PATH lookup)
- It returns the user's configured JDK location from `JAVA_HOME` (system pref) or the highest-version JDK in `/Library/Java/JavaVirtualMachines/`
- It's a single, deterministic system call — not `which` resolution

**Why not bundle a JRE (gold standard):** A full JRE bundle adds 100-200 MB to the .app. For v1, using `java_home` is pragmatic — users on macOS for PCB work already have Java for other tools (KiCad requires it, for example). JRE bundling is tracked as a future enhancement, not in scope for Phase 4.

**Files:**
- `macos-app/Sources/Volta/Routing/FreeroutingProvider.swift:289-317` — replace `probeJava()` body with the new implementation
- `macos-app/Sources/Volta/Routing/JavaLocator.swift` — new file, ~80 LOC for the `java_home` invocation + parsing
- `macos-app/Tests/VoltaTests/Routing/JavaLocatorTests.swift` — new file, ~100 LOC. Tests with stubbed `/usr/libexec/java_home` output. Edge cases: missing JAVA_HOME, missing java_home binary, multiple JDKs.

**Acceptance:**
- `grep -rn "/usr/bin/env.*which\|/usr/bin/which\|Process.*launchPath.*which" macos-app/Sources/Volta/Routing/` returns 0 matches (catches the old `which` lookup)
- `probeJava()` returns `/usr/libexec/java_home` output via subprocess, never calls `which`
- `JavaLocatorTests` pass with stubbed subprocess output

---

## Commit strategy

Five commits, each independently shippable:

1. **`chore(kicad-detector): delete KiCadCLIDetector + KiCadInstallStatus — native ERC only`** — 6a
2. **`feat(easyeda): direct EasyEDA web API — drop easyeda2kicad shell-out entirely (no fallback)** — 6b (Council C-02: NO feature flag)
3. **`chore(freerouting): bundle freerouting.jar in Resources via Git LFS** — 6c (Council H-02: LFS before binary commit)
4. **`test(erc): replace batch_erc_parity.py with Swift test runner** — 6d
5. **`fix(routing): resolve Java via /usr/libexec/java_home — drop which lookup** — 6e (Council C-01)

Ordering rationale: 6a is the cleanest delete (lowest risk, highest leverage). 6b is a feature rewrite with NO fallback (revertable by code revert only — no flag). 6c has the largest blast radius (LFS + binary). 6d is a test infra change. 6e is a small, focused runtime fix. Each can land independently. 6a, 6b, 6d, 6e can execute in parallel with Task 2 (no dependency). 6c's end-to-end smoke test depends on Task 2.

## Acceptance criteria (cumulative)

- [ ] `grep -rn "kicad-cli\|kicad_cli\|pcbnew\|easyeda2kicad\|pip install" macos-app/Sources/` returns 0 matches
- [ ] `grep -rn "/Users/bretbouchard/apps/freerouting" macos-app/Sources/` returns 0 matches
- [ ] `grep -rn "/usr/bin/env.*which\|/usr/bin/which" macos-app/Sources/Volta/Routing/` returns 0 matches (Council M-06: catches Java PATH lookup)
- [ ] `grep -rn "/Applications/Freerouting\|/opt/homebrew/Cellar/freerouting\|/Library/Application Support/freerouting\|\.volta" macos-app/Sources/` returns 0 matches (Council L-03 + N-02: catches freerouting.jar hardcoded search paths including `~/.volta`)
- [ ] `grep -rn "defaultJARSearchPaths\|locateJAR" macos-app/Sources/Volta/Routing/` returns 0 matches (Council N-02: confirms the dead array and function are deleted)
- [ ] `ls macos-app/Resources/freerouting.jar` exists AND `git lfs ls-files | grep freerouting.jar` confirms LFS tracking
- [ ] `git lfs ls-files` confirms `.gitattributes` has LFS rule for `freerouting.jar`
- [ ] All VoltaTests + VoltaPCBTests targets pass
- [ ] Bundle structure verification: `find .app/Contents/Resources -name "*.jar"` returns freerouting.jar
- [ ] No `useWebAPI` feature flag in `EasyEdaProvider.swift` (Council C-02: NO fallback)
- [ ] No shell-out `Process` invocation in `EasyEdaProvider.swift` (Council C-02: NO fallback)

## Risks + mitigations

| Risk | Mitigation |
|---|---|
| 6a deletes API surface some consumer depends on | Search for callers first (`grep -rln "KiCadCLIDetector\|KiCadInstallStatus"`); none in current code, but validate before commit. ValidationPanel badge text explicitly says "Native ERC only — DRC via KiCad app" to be honest about functional delta. |
| 6b EasyEDA web API may rate-limit, change shape, or return malformed JSON | (Council C-02) NO fallback — web API is the only path. (Council M-04) Strict `Codable` decoding with `EasyEdaError.responseSchemaMismatch(rawResponse:)` thrown on shape drift. Log raw responses for 7 days post-launch. Add `CIWeekly/easyeda_ping_test` to detect breaking changes early. |
| 6c 57.7 MB binary in git (without LFS bloats history permanently) | (Council H-02) Set up `.gitattributes` LFS tracking BEFORE the binary commit. Run `git lfs install` + `git lfs track "macos-app/Resources/freerouting.jar"` as part of 6c. Document commit includes LFS pointer file, not raw binary. |
| 6d ERC parity corpus may not match between Swift and Python after removal | Verify corpus exists in Swift test target before deleting Python harness. `grep -rln "batch_erc_parity" .` audit covers CI configs, Makefiles, docs — all references must be removed. |
| 6e `/usr/libexec/java_home` returns no path on systems without JDK | `JavaLocator` returns nil in that case; `FreeroutingProvider.availability` reports `.requiresManualUserAction` with install hint pointing to `brew install openjdk`. JRE bundling (gold standard) is out of scope for Phase 4. |
| `which` and PATH-based lookups may exist elsewhere we haven't audited | Council grep covers `macos-app/Sources/` exhaustively. Any out-of-tree lookup (CI scripts, build tooling) is out of scope for Phase 4. |

## Out of scope

- **Bundling a full JRE** (~150 MB) for Java runtime (Council C-01 alternative) — defer to a future milestone when `.app` size budget allows. Tracked with `git lfs track` patterns + potential future SwiftPM JRE distribution. Not in Phase 4.
- Replacing the Python daemon with native Swift ops — that's a much larger refactor (1.5k LOC deletes, 500 LOC rewiring) that crosses into Phase 5 territory. Tracked separately.
- Removing `erc-cli` binary itself — it's pure Swift and sandbox-clean when bundled. The cleanup here is only the Python test harness around it.