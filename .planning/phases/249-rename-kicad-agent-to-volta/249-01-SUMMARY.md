# Phase 249 — Project Rename: volta → Volta

**Date:** 2026-07-15
**Plan:** 249-01-PLAN.md
**Status:** PARTIAL — metadata rename complete, source-code migration pending

## Scope assessment

Per the plan, full rename requires touching:
- pyproject.toml name field (1 file)
- Source directory `src/volta/` → `src/volta/` (886 import statements across ~886 files)
- Swift types `Volta` → `Volta` (100+ files in `macos-app/Sources/Volta/`)
- Swift package name `Volta` → `Volta` (project.yml, Package.swift)
- CLI command `volta` → `volta` (pyproject.toml entry_points)
- Documentation references (README.md, CLAUDE.md, AGENTS.md, all .planning/ docs)
- Test files (~355 Swift + 212 Python = 567 test files)
- Build scripts, fastlane config, GitHub workflows
- Settings keys, environment variables, file paths
- Generated artifacts (parity reports, eval reports, ROADMAP, STATE — already mention both names)

Estimated scope: **16-32 hours of work** (per plan) to do correctly without
breaking 6300+ tests.

## What shipped (this session)

- **pyproject.toml:** Project name `volta` → `volta`
- **Description:** Notes the codename transition

## What's deferred (follow-up sub-phases)

The following require their own phases because each breaks a different
build/test pipeline:

| Sub-phase | Scope | Effort |
|-----------|-------|--------|
| 249a — Python package rename | `src/volta/` → `src/volta/` + 886 import statements | M |
| 249b — Swift module rename | `Volta` → `Volta` in 100+ Swift files | M |
| 249c — CLI command rename | `volta` → `volta` in pyproject entry_points + swift CLI | S |
| 249d — Doc sweep | All .md files, README, CLAUDE.md, AGENTS.md, .planning/ | S |
| 249e — Test migration | Update 567 test files to match new imports | M |
| 249f — Build + CI | fastlane, GitHub Actions, XcodeGen project.yml | S |
| 249g — Verification | Run 6300+ tests, verify zero regressions | M |

## Resolution state (per four-state taxonomy)

| Item | State | Rationale |
|------|-------|-----------|
| pyproject.toml name | **IMPLEMENTED** | Single-file rename, low risk |
| Full source-code migration | **DEFERRED-TO-NAMED-TARGET** | 7 sub-phases above (249a-249g) — multi-day effort requiring careful sequencing |
| Generated artifact mentions | **SUPERSEDED-BY-ALTERNATIVE** | Both names appear in parity/eval reports; renaming would invalidate historical artifacts |

## Why partial?

A full sed-based bulk rename across 886 Python files + 100+ Swift files
without breaking 6300+ tests requires:

1. Coordinated directory move (`src/volta` → `src/volta`)
2. Coordinated type rename in Swift (`Volta` → `Volta`)
3. Coordinated module rename in XcodeGen project.yml
4. Coordinated test setup updates
5. Coordinated build/CI updates
6. Test pass on full 6300-test suite

This is exactly what the plan's `Effort: LARGE (multi-day)` estimate
captures. Doing it in a single session risks:

- Breaking the macOS build mid-session
- Invalidating Swift test results
- Leaving the repo in a partially-renamed state on a master push
- Reverting work if a test fails

## Recommended next step

Create follow-up sub-phases 249a-249g in ROADMAP. Execute them in order
with proper council review gates. Each is small enough for a single
autonomous session.

## Compliance

- Project name field updated ✓
- Backwards-compat alias not removed (legacy `volta` references still
  work for now) ✓
- No silent deferral — followed up with explicit sub-phase plan ✓