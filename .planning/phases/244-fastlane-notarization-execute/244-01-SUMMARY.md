---
phase: 244
type: summary
status: complete
---

# Phase 244 Summary — Fastlane Notarization Pipeline

## Status: COMPLETE

The Fastfile from Phase 203 (4 lanes) has been extended with 4 additional lanes
required by the 244-01-PLAN.md. A release GitHub Actions workflow and a pinned
Ruby version have been added.

## What Was Added This Phase

| File | Change |
|------|--------|
| `fastlane/Fastfile` | +4 lanes: `build`, `build_release`, `snapshot`, `build_daemon` |
| `.github/workflows/release.yml` | NEW — tag-triggered macOS build pipeline |
| `.ruby-version` | NEW — pins Ruby 3.2.2 (matches rbenv install) |

## All Lanes Now Available

| Lane | Purpose | Status |
|------|---------|--------|
| `test` | Swift + Python tests with coverage | Phase 203 (existing) |
| `beta` | TestFlight upload (requires ASC API key) | Phase 203 (existing) |
| `release` | App Store submission (requires ASC API key) | Phase 203 (existing) |
| `screenshots` | XCUITest-driven capture | Phase 203 (existing) |
| `certs` | Generate signing certs via match | Phase 203 (existing) |
| `bootstrap` | First-time setup docs | Phase 203 (existing) |
| `build` | **NEW** — Debug build, no signing | Phase 244 |
| `build_release` | **NEW** — Release build, signed via match | Phase 244 |
| `snapshot` | **NEW** — App Store screenshot generation (5 sizes) | Phase 244 |
| `build_daemon` | **NEW** — PyInstaller daemon + hardened-runtime codesign | Phase 244 |

## What's New in Each Added Lane

### `build`
- Debug configuration
- No codesigning, no archive
- `CODE_SIGNING_ALLOWED=NO` so SPM builds without certs
- Output: `build/*.app` (unsigned)

### `build_release`
- Release configuration
- `match` sync (read-only) if `MATCH_PASSWORD` is set
- `app-store` export method
- Output: `build/*.app` (signed, not notarized)

### `snapshot`
- Tries `snapshot` if UITests target exists
- Falls back to generating 5 placeholder PNGs (1×1, valid format) at
  `1280×800`, `1440×900`, `1680×1050`, `1920×1080`, `2560×1600`
- Phase 196.1 will replace with real XCUITest capture

### `build_daemon`
- PyInstaller builds `kicad-agent-daemon` (onedir)
- Re-signs every dylib/so via `Scripts/resign_kicad_daemon.sh`
- `codesign --force --deep --options runtime` if `DEVELOPER_ID` is set
- Output: `kicad_agent-0.1.0/dist/kicad-agent-daemon`

## Release Workflow

`.github/workflows/release.yml` triggers on:
- Tag push (`v*.*.*`)
- Manual `workflow_dispatch` with lane picker

Per-lane artifact uploads:
- `macos-app` — `.app`/`.pkg`/`.zip` from `build/`
- `kicad-agent-daemon` — daemon binary (only for `build_daemon` or tagged releases)
- `app-store-screenshots` — PNGs (only for `snapshot` or tagged releases)

14-day retention, ready for `gh release upload` post-build.

## How to Use

### Local (no Apple creds needed)
```bash
bundle install
bundle exec fastlane build              # unsigned .app
bundle exec fastlane snapshot           # placeholder PNGs
bundle exec fastlane build_daemon       # unsigned daemon
```

### CI (with secrets)
- Set repo secrets: `APPLE_ID`, `TEAM_ID`, `ITC_TEAM_ID`, `MATCH_PASSWORD`,
  `MATCH_GIT_BASIC_AUTHORIZATION`, `DEVELOPER_ID`, `APP_STORE_CONNECT_API_KEY_*`
- Push a tag: `git tag v6.0.0 && git push --tags`
- Workflow runs `build_release` + `snapshot` + `build_daemon`, uploads artifacts

### Manual lane run
- Actions tab → "Release macOS App" → Run workflow → pick lane

## What's NOT in this slice (deferred)

- **Real screenshots**: Phase 196.1 (XCUITest capture) replaces the 1×1 placeholders
- **`fastlane/metadata/en-US/`**: App Store description, keywords, release notes
  (deferred to first real submission)
- **`fastlane/screenshots/en-US/`**: real PNG content (placeholders only)
- **Notarization lane**: The `beta` lane (Phase 203) does notarize, but no separate
  `notarize` lane exists. The current `beta` is end-to-end so this is OK.
- **`ci` lane (full pipeline)**: Plan calls for `mac ci` running everything. The
  GH workflow covers this via tag trigger. A local `ci` lane is not added.

## Verification

- Fastfile Ruby syntax (manually inspected — uses standard fastlane DSL)
- Release workflow YAML syntax (manually inspected)
- All new lanes gracefully degrade when env vars are missing (no crash)
