# Task 6 — Sandbox Cleanup Sweep

**Phase:** 4 (Routing Plugin System)
**Status:** Planning — awaiting Council review
**Created:** 2026-07-28
**Depends on:** Task 2 REDO (DSN port lands first, then this sweep), PROJECT.md sandbox rule (already shipped in `cf1fb3b`)
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
- `macos-app/Sources/Volta/Views/ValidationPanel.swift:121-135` — drop the `kicad_cli_check` MCP call, replace with a status badge that says "Native validation only"
- `macos-app/Sources/Volta/Governance/PostOpGate.swift:9` — change "via kicad-cli" comment to "via native Swift"
- `macos-app/Sources/Volta/Views/LiquidGlassShell.swift:187` — flip "Prefer daemon (real kicad-cli) when MCP is wired; otherwise fall back" → native ERC/DRC is the only path, drop the preference language
- `macos-app/project.yml` — drop the two file references from the Sources list

**Acceptance:**
- `grep -rn "KiCadCLIDetector\|KiCadInstallStatus\|kicad_cli_check" macos-app/Sources/` returns 0 matches
- ValidationPanel renders without crashing (uses only `NativeERC` results)
- `xcodebuild` succeeds — no missing-file build errors

### 6b — Rewrite `EasyEdaProvider` to direct web API

Current state (`macos-app/Sources/Volta/Providers/EasyEda/EasyEdaProvider.swift`): shells out to `easyeda2kicad` Python CLI, 7 search paths, tells user to `pip install easyeda2kicad`.

**Replacement strategy:** hit the EasyEDA web API directly. The `easyeda2kicad` CLI is just a wrapper around:
- `https://easyeda.com/api/products/{lcscId}` — product metadata
- `https://easyeda.com/api/eda/product/symbol/{...}` — schematic symbol SVG
- `https://easyeda.com/api/eda/product/footprint/{...}` — PCB footprint JSON

For LCSC IDs only (which is how `EasyEdaProvider` works — no keyword search).

**Files:**
- `macos-app/Sources/Volta/Providers/EasyEda/EasyEdaProvider.swift` — rewrite to use `URLSession` + `Codable` decoding (no subprocess)
- `macos-app/Sources/Volta/Providers/EasyEda/EasyEdaAPI.swift` — new file, ~150 LOC for the API client + response models
- Delete `findEasyEda2Kicad()` and all `which`-based discovery
- Delete `pip install easyeda2kicad` error message
- `macos-app/Tests/VoltaTests/Providers/EasyEda/` — add `EasyEdaAPITests.swift` with `URLProtocol` stub for offline tests

**Acceptance:**
- `grep -rn "easyeda2kicad\|findEasyEda2Kicad\|pip install easyeda" macos-app/Sources/` returns 0 matches
- `EasyEdaProvider.availability` no longer queries the filesystem
- API tests pass with stubbed HTTP responses (no real EasyEDA calls in CI)

**Risk:** EasyEDA web API may rate-limit or change shape. Mitigation: feature flag `EasyEdaProvider.useWebAPI = true` defaults to true, false falls back to the previous shell-out path (still available, just not preferred). This lets us revert if the API behaves unexpectedly.

### 6c — Move `freerouting.jar` into `.app/Contents/Resources/`

Current state: hardcoded `/Users/bretbouchard/apps/freerouting/freerouting.jar` lookup in `FreeroutingProvider`. Outside any bundle.

**Replacement strategy:**
1. Copy `freerouting.jar` from `/Users/bretbouchard/apps/freerouting/` (or its known canonical source — verify with Bret) into `macos-app/Resources/freerouting.jar` and commit it (binary, but it's a release artifact, not source).
2. Update `macos-app/project.yml` to declare it as a bundled resource for the .app target.
3. Update `FreeroutingProvider.jarPath()` to look up via `Bundle.main.url(forResource: "freerouting", withExtension: "jar")` first; only fall back to the dev path for `DEBUG` builds where the JAR hasn't been copied yet.
4. Add a checksum verification step (already partially in `ProcessManager` pattern — borrow it).

**Files:**
- `macos-app/Resources/freerouting.jar` — new file (binary, ~57.7 MB). Verify SHA-256 in the commit message.
- `macos-app/Sources/Volta/Routing/FreeroutingProvider.swift` — modify `jarPath()` lookup
- `macos-app/project.yml` — add resource declaration
- `macos-app/Tests/VoltaTests/Routing/FreeroutingProviderTests.swift` — add JAR-resolvable test

**Acceptance:**
- `grep -rn "/Users/bretbouchard/apps/freerouting" macos-app/Sources/` returns 0 matches
- `freerouting.jar` is present at `macos-app/Resources/freerouting.jar`
- `Bundle.main.resourcePath/freerouting.jar` resolves in tests
- FreeroutingProvider routes a real .kicad_pcb end-to-end via the bundled JAR (manual smoke test, Bret signs off)

**Binary in git:** the JAR is 57.7 MB. Acceptable per Volta's existing pattern (PyInstaller daemon is similar size). Document the commit includes a large binary in the message body.

### 6d — Replace `batch_erc_parity.py` with Swift test runner

Current state: `macos-app/Sources/erc-cli/main.swift` is a separate Swift CLI built for `batch_erc_parity.py` to compare Swift `NativeERC` vs Python `native_erc`. Pure Swift on the language axis but the test harness is Python.

**Replacement strategy:**
- Keep `erc-cli/main.swift` (it's pure Swift and produces JSON).
- Delete `batch_erc_parity.py` if it exists in the repo.
- Replace with `macos-app/Tests/VoltaTests/ERC/ERCParityTests.swift` — a Swift test that invokes `erc-cli` via `Process` and compares results against the Swift `NativeERC` directly. No Python in the loop.

**Files:**
- `batch_erc_parity.py` — delete (verify it's not in repo first)
- `macos-app/Tests/VoltaTests/ERC/ERCParityTests.swift` — new file, ~200 LOC

**Acceptance:**
- `grep -rln "batch_erc_parity" macos-app/ tests/` returns 0 matches
- `ERCParityTests` runs and passes on a small corpus

---

## Commit strategy

Four commits, each independently shippable:

1. **`chore(kicad-detector): delete KiCadCLIDetector + KiCadInstallStatus — native ERC only`** — 6a
2. **`feat(easyeda): direct EasyEDA web API — drop easyeda2kicad shell-out`** — 6b
3. **`chore(freerouting): bundle freerouting.jar in Resources — Bundle.main lookup`** — 6c
4. **`test(erc): replace batch_erc_parity.py with Swift test runner`** — 6d

Ordering rationale: 6a is the cleanest delete (lowest risk, highest leverage). 6b is a feature rewrite with a fallback flag (revertable). 6c has the largest blast radius (binary in git). 6d is a test infra change. Each can land independently.

## Acceptance criteria (cumulative)

- [ ] `grep -rn "kicad-cli\|kicad_cli\|pcbnew\|easyeda2kicad\|pip install" macos-app/Sources/` returns 0 matches
- [ ] `grep -rn "/Users/bretbouchard/apps/freerouting" macos-app/Sources/` returns 0 matches
- [ ] `ls macos-app/Resources/freerouting.jar` exists
- [ ] All VoltaTests + VoltaPCBTests targets pass
- [ ] Bundle structure verification: `find .app/Contents/Resources -name "*.jar"` returns freerouting.jar

## Risks + mitigations

| Risk | Mitigation |
|---|---|
| 6a deletes API surface some consumer depends on | Search for callers first (`grep -rln "KiCadCLIDetector\|KiCadInstallStatus"`); none in current code, but validate before commit |
| 6b EasyEDA web API may rate-limit or change shape | Feature flag `useWebAPI` defaults true; false falls back to shell-out path; revert possible without code revert |
| 6c 57.7 MB binary in git | Document in commit message; add to `.gitattributes` if LFS desired later; one-time cost |
| 6d ERC parity corpus may not match between Swift and Python after removal | Verify corpus exists in Swift test target before deleting Python harness |

## Out of scope

- Replacing the Python daemon with native Swift ops — that's a much larger refactor (1.5k LOC deletes, 500 LOC rewiring) that crosses into Phase 5 territory. Tracked separately.
- Removing `erc-cli` binary itself — it's pure Swift and sandbox-clean when bundled. The cleanup here is only the Python test harness around it.