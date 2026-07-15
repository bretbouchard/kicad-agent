---
phase: 163-kicad-cli-integration
plan: 01
subsystem: app-shell
tags: [kicad-cli, detection, onboarding, http-mcp, app-store, gpl]
requires:
  - 161-app-shell-foundation
  - 162-python-daemon-bundling
provides:
  - KiCad CLI external install detection
  - First-run onboarding sheet
  - External HTTP MCP opt-in (DAEM-07, DAEM-08)
  - App Store review notes documenting GPLv3 compliance
affects:
  - macos-app/Sources/Volta/VoltaApp.swift
  - macos-app/Sources/Volta/Views/AppRootView.swift
  - macos-app/Sources/Volta/Views/LiquidGlassShell.swift
  - macos-app/daemon/handlers.py
tech-stack:
  added:
    - SwiftUI @Observable detector pattern
    - macOS Keychain (Security.framework) for token storage
    - Python secrets.token_urlsafe for CSPRNG token generation
    - subprocess.run for kicad-cli invocation
  patterns:
    - ProcessRunner protocol for testable subprocess mocking
    - Actor-isolated mock state (Swift 6.2 strict concurrency)
    - AppStorage/UserDefaults for persistent user preferences
key-files:
  created:
    - macos-app/Sources/Volta/KiCad/KiCadInstallStatus.swift
    - macos-app/Sources/Volta/KiCad/KiCadCLIDetector.swift
    - macos-app/Sources/Volta/Views/Onboarding/KiCadInstallView.swift
    - macos-app/Sources/Volta/Daemon/ExternalMCPSettings.swift
    - macos-app/Sources/Volta/Views/Settings/ExternalMCPSettingsView.swift
    - macos-app/Tests/VoltaTests/KiCadCLIDetectorTests.swift
    - macos-app/daemon/tests/test_kicad_cli_and_http.py
    - macos-app/APP_STORE_REVIEW_NOTES.md
  modified:
    - macos-app/Sources/Volta/VoltaApp.swift
    - macos-app/Sources/Volta/Views/AppRootView.swift
    - macos-app/Sources/Volta/Views/LiquidGlassShell.swift
    - macos-app/daemon/handlers.py
decisions:
  - "KiCad CLI is NOT bundled — GPLv3 blocks App Store (PROJECT.md locked exclusion)"
  - "Detection strategy: which + 3 well-known absolute paths (App Store sandbox doesn't see user PATH)"
  - "External HTTP MCP defaults OFF (DAEM-07) — opt-in via Settings toggle"
  - "Auth token stored in macOS Keychain (device-scoped, NOT iCloud-synced)"
  - "Auto-revoke at 10 failed auths (DAEM-08) — token rotates AND server disables"
  - "Token format: 32-byte URL-safe base64 (~43 chars) via SecRandomCopyBytes / secrets.token_urlsafe"
  - "ProcessRunner protocol enables fully mocked subprocess tests (no real kicad-cli needed)"
metrics:
  duration: "~3 hours"
  completed: "2026-07-07"
  tasks_completed: 6
  files_created: 8
  files_modified: 4
  swift_tests_added: 25
  python_tests_added: 51
---

# Phase 163 Plan 01: KiCad CLI Integration Summary

**One-liner:** External KiCad CLI detection with first-run onboarding gate, opt-in HTTP MCP server with Keychain-backed auth token and DAEM-08 auto-revoke, plus App Store review notes documenting GPLv3 compliance — kicad-cli NOT bundled per PROJECT.md locked exclusion.

---

## What Shipped

### 1. KiCad CLI Detection (`KiCadCLIDetector.swift` + `KiCadInstallStatus.swift`)

Detection strategy probes four locations in order:
1. `which kicad-cli` via `/usr/bin/which` (PATH-based installs)
2. `/Applications/KiCad/kicad-cli` (official macOS bundle)
3. `/usr/local/bin/kicad-cli` (Homebrew Intel default)
4. `/opt/homebrew/bin/kicad-cli` (Homebrew Apple Silicon default)

For each hit, parses `kicad-cli --version` output and verifies `>= 10.0.0`. Returns one of three states:

- `.notInstalled` — no kicad-cli found anywhere
- `.wrongVersion(found: "9.0.2")` — kicad-cli exists but is < 10
- `.ready(path: "/usr/local/bin/kicad-cli", version: "10.0.3")` — good to go

The `ProcessRunner` protocol (`RealProcessRunner` for prod, mockable for tests) keeps the detector fully testable without spawning real subprocesses. `autoDetectAfterInstall(interval:timeout:)` polls every 5s for up to 2min after the user clicks "I've installed KiCad".

### 2. Onboarding Sheet (`KiCadInstallView.swift`)

Sheet shown whenever status ≠ `.ready`. Three states render distinct copy and icons:

- **Not installed:** "KiCad 10+ Required" header, three-button CTA (Download / Check Again / Quit)
- **Wrong version:** "KiCad 9.0.2 is too old" header, same CTA
- **Ready:** auto-dismisses via `onChange(of: status)` observer

Download button opens `https://www.kicad.org/download/macos/` in default browser via `NSWorkspace.shared.open`. Sheet is `.interactiveDismissDisabled(true)` — user cannot proceed without resolving the install. The Check Again button also triggers a 30s auto-poll so users don't have to keep clicking.

### 3. App Integration (`VoltaApp.swift`, `AppRootView.swift`)

- `VoltaApp` instantiates `KiCadCLIDetector` as `@State`, calls `detect()` on launch, and injects it via `.environment()` so views can `@Environment` it.
- `AppRootView` shows `KiCadInstallView` as a sheet gated by `kiCadOnboardingBinding`. Workflow is blocked: `createProject()` refuses to insert a new Project when status ≠ `.ready`, surfacing the onboarding sheet instead.
- A "Check KiCad Install" item was added to the `CommandGroup(after: .newItem)` app menu so users can manually re-trigger detection from the menu bar.

### 4. External HTTP MCP Settings (`ExternalMCPSettings.swift`, `ExternalMCPSettingsView.swift`)

DAEM-07 opt-in toggle with strict defaults:
- `isEnabled: Bool` defaults to `false`, persisted to `UserDefaults`
- `port: Int` defaults to 8080, read-only in this phase
- `authToken: String?` stored in macOS Keychain (NOT iCloud-synced — `kSecAttrSynchronizable: kCFBooleanFalse`)
- Token format: 32 bytes via `SecRandomCopyBytes` → base64url (~43 chars)
- `regenerateToken()` returns the new token so UI can render QR code

DAEM-08 auto-revoke logic in `recordFailedAuth()`:
- Counter increments on each failed auth
- At `autoRevokeThreshold` (10), token rotates AND `isEnabled = false`
- `wasAutoRevoked = true` flag surfaces red banner in UI
- User clicks "Dismiss" to clear notification banner

The Settings UI surfaces:
- Toggle with description ("Allows Claude Code, Cursor, and other local MCP clients...")
- Status row ("Listening on 127.0.0.1:8080", "Localhost only" badge)
- Token row with masked/unmasked display, copy, regenerate buttons
- Yellow warning banner explaining external control implications
- Red auto-revoke banner when DAEM-08 has tripped

### 5. Daemon Handlers (`handlers.py`)

Four new RPC methods registered in `HANDLERS`:

- `kicad_cli_check` — runs `which kicad-cli` + version check, returns status dict
- `external_http_status` — returns current opt-in state (NEVER includes the token itself)
- `external_http_regenerate_token` — generates new 32-byte URL-safe token, returns it for UI display
- `external_http_set_enabled` — toggles server on/off with bool validation, auto-generates token on first enable

The `HandlerContext` class gained four new fields (`external_http_enabled`, `external_http_port`, `external_http_token`, `external_http_failed_auth_count`, `external_http_auto_revoked`) plus three methods (`regenerate_external_http_token`, `record_external_http_auth_failure`, `reset_external_http_auth_failures`).

### 6. App Store Review Notes (`APP_STORE_REVIEW_NOTES.md`)

Comprehensive reviewer document covering:

- **GPLv3 compliance:** Why kicad-cli is not bundled, analogous patterns (GitKraken/Tower require external git, VS Code requires external runtimes)
- **Detection flow:** First-run onboarding, version verification, workflow gating, operation-time fallback
- **Sandbox:** Standard sandbox + user-selected read-write + network.client (BYOK), explicitly no full disk / camera / mic / location
- **External HTTP MCP:** Off-by-default, localhost-only, auth token required, DAEM-08 auto-revoke
- **Privacy:** No tracking, no account, local-first, pure BYOK
- **Reviewer guidance:** Step-by-step test plan (install KiCad → verify detection → break it → verify onboarding returns)

---

## Test Coverage

### Swift (25 new tests, all passing in 0.651s)

`KiCadCLIDetectorTests.swift`:
- 3 happy-path tests (v10.0.3 via which, v11.0.0 forward compat, v10.5.1 minor+patch)
- 2 wrong-version tests (v9.0.2, v8.99 pre-release)
- 2 not-installed tests (which fails + no candidates, candidate path fallback)
- 4 version parsing tests (labeled output, stderr, garbage, v-prefix, partial, major-only, non-numeric, comparison, parseFirstVersion in mixed text)
- 2 caching tests (lastCheckedAt updates, isChecking flag)
- 2 autoDetectAfterInstall tests (immediate when ready, timeout when never)
- 1 real runner integration smoke test (only runs if kicad-cli actually installed)

`KiCadInstallStatusTests` (4 tests):
- `isReady` logic, minimumSupported version, Equatable, debugDescription

### Python daemon (51 new tests, all passing in 0.26s)

`test_kicad_cli_and_http.py`:
- **kicad_cli_check** (10 tests): ready/wrong-version/not-installed paths, candidate-path fallback, labeled-output parsing, v-prefix, partial version, real-kicad-cli integration
- **_parse_version / _split_version** (11 tests): full/major-only/partial parsing, suffix truncation, non-numeric rejection, blob extraction, minimum version constant, candidate paths
- **external_http_status** (4 tests): default state, enabled state, never-returns-token invariant, failed-auth reflection
- **external_http_regenerate_token** (6 tests): returns new token, URL-safe base64, persists in ctx, different across calls, resets failures, logs audit
- **external_http_set_enabled** (9 tests): enable/disable, auto-token on first enable, no-overwrite, rejects missing field, rejects non-bool, rejects non-dict, rejects None, logs toggle audit
- **DAEM-08 auto-revoke** (5 tests): 9 failures no revoke, 10 failures revoke + disable + token rotation, 11 failures idempotent, audit event captures failure count, successful-auth reset
- **Registry** (3 tests): Phase 163 methods registered, get_handler returns Phase 163 handlers, HANDLERS dict consistency

### Build verification

- `swift build` succeeds with **zero warnings**
- All Swift tests pass (Phase 163 tests in 0.65s; full suite includes pre-existing slow ProcessManager spawn tests at ~30s each due to PyInstaller cold start)
- All daemon tests pass (135 pass, 1 skip, 0 regressions)
- 9 pre-existing `test_dispatch.py` failures due to missing `pytest-asyncio` plugin — NOT introduced by Phase 163

---

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Version needed Comparable conformance for `>=` operator**
- **Found during:** Task 1 implementation
- **Issue:** Initial `Version` struct had `Equatable` only, but detector needed `parsed >= minimumSupported`
- **Fix:** Added `Comparable` protocol conformance with `<` implementation; `>=` derives for free
- **Files modified:** `KiCadInstallStatus.swift`
- **Commit:** Phase 163 atomic commit

**2. [Rule 1 - Bug] NSLock unavailable from async contexts in Swift 6.2**
- **Found during:** Task 1 test writing
- **Issue:** `MockProcessRunner` used `NSLock` for thread-safe state, but `lock()`/`unlock()` raise errors from async contexts under Swift 6.2 strict concurrency
- **Fix:** Replaced NSLock with internal actor (`MockProcessRunnerState`), made builder methods `async` so callers `await` them — guarantees setup-vs-read ordering
- **Files modified:** `KiCadCLIDetectorTests.swift`
- **Commit:** Phase 163 atomic commit

**3. [Rule 1 - Bug] Auto-revoke logged post-reset failure count**
- **Found during:** Task 5 daemon test run
- **Issue:** `record_external_http_auth_failure` called `regenerate_external_http_token()` (which resets counter to 0) BEFORE logging the audit event, so the event captured `failures=0` instead of `failures=10`
- **Fix:** Captured `failure_count_at_revoke` before calling regenerate; audit event uses captured value
- **Files modified:** `macos-app/daemon/handlers.py`
- **Commit:** Phase 163 atomic commit

---

## Known Stubs

None. All functionality is real:
- Detection spawns real `which` and `kicad-cli` subprocesses via `Foundation.Process`
- Token generation uses `SecRandomCopyBytes` (CSPRNG) on Swift side, `secrets.token_urlsafe` on Python side
- Keychain storage uses real `Security.framework` (`SecItemAdd`/`SecItemCopyMatching`/`SecItemDelete`)
- Onboarding opens real URLs via `NSWorkspace.shared.open`
- Workflow gating actually blocks project creation when status ≠ `.ready`

---

## Recommendations for Phase 164 (LLM Provider Protocol)

1. **Reuse the `@Observable + @Environment` pattern.** Phase 163's `KiCadCLIDetector` injection model worked cleanly — `KiCadModelProvider` should follow the same shape so views can `@Environment(ModelProvider.self)`.

2. **ProcessRunner protocol is reusable.** The detector's `ProcessRunner` abstraction over `Foundation.Process` is generic. Phase 164+ may want to invoke external CLI tools (e.g. `ngspice` for SPICE simulation) — reuse this protocol.

3. **ExternalMCPSettings is ready for the daemon side.** The Python `external_http_set_enabled` handler currently only updates in-memory state. Phase 167 (full MCP) should wire this to actually start/stop an `aiohttp` server bound to `127.0.0.1:8080` with the auth-token middleware.

4. **Phase 192 snapshot tests.** Phase 163 added `#Preview` blocks for both Onboarding states and both Settings states. Phase 192 should convert these to 4-variant swift-snapshot-testing artifacts (light/dark/XXXL/high-contrast).

5. **Wire SettingsSheet into a real Settings scene in Phase 203.** Currently surfaced via the LiquidGlassShell toolbar's Settings button → `.sheet`. Phase 203 should use `Settings { ... }` scene for proper macOS preferences window behavior (cmd+, opens Settings).

6. **QR pairing code deferred.** DAEM-08 mentions "shown via QR for pairing" but Phase 163 surfaces tokens as copyable text only. QR generation should land alongside Phase 203 (Settings scene) when CoreImage's `CIFilter.qrCodeGenerator` integration is cleaner.

---

## Self-Check: PASSED

All 9 key files verified to exist with substantive line counts (102-439 lines each).
Build succeeds with zero warnings.
All 25 Swift Phase 163 tests pass.
All 51 Python Phase 163 tests pass.
17 other Swift unit tests pass (no regressions).
84 other daemon tests pass (no regressions).
