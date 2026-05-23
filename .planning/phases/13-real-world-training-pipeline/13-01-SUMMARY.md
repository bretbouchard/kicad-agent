---
phase: 13-real-world-training-pipeline
plan: 01
subsystem: crawler
tags: [github-api, rate-limiting, file-fetching, kicad-discovery]
dependency_graph:
  requires: [PyGithub>=2.9.1]
  provides: [GithubDiscovery, FileFetcher, RateLimiter, RepoInfo, KicadFilePair, FetchedFile]
  affects: [pyproject.toml]
tech_stack:
  added: [PyGithub>=2.9.1]
  patterns: [frozen-dataclass, barrel-exports, rate-limiter, sparse-file-fetch]
key_files:
  created:
    - src/kicad_agent/crawler/__init__.py
    - src/kicad_agent/crawler/rate_limiter.py
    - src/kicad_agent/crawler/github_discovery.py
    - src/kicad_agent/crawler/file_fetcher.py
    - tests/test_crawler_discovery.py
  modified:
    - pyproject.toml
decisions:
  - FakePaginatedList concrete class used for mock iteration instead of MagicMock.__iter__ (MagicMock iteration protocol unreliable)
  - Rate limit mock defaults set to 1000 remaining (above 50 threshold) to avoid real time.sleep in tests
  - file_fetcher.py included in Task 1 commit to satisfy __init__.py barrel imports; tests committed separately in Task 2
metrics:
  duration: 14 min
  completed: 2026-05-23
---

# Phase 13 Plan 01: GitHub Repo Discovery and KiCad File Pair Extraction Summary

One-liner: GitHub crawler with PyGithub search, rate-limit-aware pagination, tree-based file pair extraction, and sparse Contents API file fetching -- 20 tests passing.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create crawler package with types, rate limiter, and GitHub discovery | ce9f3ed | crawler/__init__.py, rate_limiter.py, github_discovery.py, file_fetcher.py, pyproject.toml |
| 2 | File fetcher and crawler unit tests | 0f5cff8 | tests/test_crawler_discovery.py |

## What Was Built

### Rate Limiter (`rate_limiter.py`)
- `RateLimiter` class wrapping PyGithub's rate limit tracking
- Threshold of 50 remaining requests before preemptive sleep
- Calculated sleep based on reset timestamp (no hardcoded delays)
- Supports both `core` and `search` API rate limit resources

### GitHub Discovery (`github_discovery.py`)
- `RepoInfo` frozen dataclass: full_name, html_url, stars, description, default_branch
- `KicadFilePair` frozen dataclass: schematic_path, pcb_path, base_name
- `GithubDiscovery` class with PyGithub `Auth.Token` authentication
- `discover_repos()`: multi-query search with deduplication by full_name
- `find_kicad_pairs()`: Git Tree API with recursive listing, base-name matching
- `discover_pairs()`: combines search + pairing, filters repos with zero pairs
- Error resilience: catches GithubException, logs warnings, returns empty results

### File Fetcher (`file_fetcher.py`)
- `FetchedFile` frozen dataclass: repo_name, path, local_path, content_hash
- `FileFetcher` class with Contents API sparse file retrieval
- Path traversal protection via `Path(file_path).name` sanitization
- Extension validation: only .kicad_sch and .kicad_pcb accepted
- Repo-specific subdirectories to avoid name collisions
- SHA256 content hash for deduplication
- `fetch_pair()` for fetching both schematic and PCB in one call

### Tests (`test_crawler_discovery.py`)
- 20 tests across 3 test classes
- TestRateLimiter: 5 tests (no-sleep, sleep, past-reset, remaining property, search resource)
- TestGithubDiscovery: 8 tests (repo info list, dedup, max_repos, pair matching, error handling, orphaned files, discover_pairs filter, nested paths)
- TestFileFetcher: 7 tests (staging dir write, error handling, extension rejection, directory response, pair fetching, partial failure, repo subdirectory)
- All GitHub API calls mocked via `_FakePaginatedList` and `MagicMock`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed mock iteration hanging tests**
- **Found during:** Task 2 test execution
- **Issue:** MagicMock `__iter__` pattern caused infinite iteration when PyGithub's PaginatedList protocol was simulated
- **Fix:** Created `_FakePaginatedList` concrete class with proper `__iter__` instead of MagicMock
- **Files modified:** tests/test_crawler_discovery.py
- **Commit:** 0f5cff8

**2. [Rule 1 - Bug] Fixed rate limit mock causing real sleep in tests**
- **Found during:** Task 2 test execution
- **Issue:** Default `search_remaining=30` in mock was below the 50 threshold, causing real `time.sleep(3600)` calls
- **Fix:** Changed default `search_remaining` to 1000 (above threshold)
- **Files modified:** tests/test_crawler_discovery.py
- **Commit:** 0f5cff8

**3. [Rule 1 - Bug] Fixed html_url assertion mismatch in test helper**
- **Found during:** Task 2 test execution
- **Issue:** `_make_mock_repo` used hardcoded default html_url instead of constructing from full_name
- **Fix:** Removed html_url parameter, constructed from `f"https://github.com/{full_name}"`
- **Files modified:** tests/test_crawler_discovery.py
- **Commit:** 0f5cff8

## Verification Results

- 20/20 crawler tests passing (0.21s)
- Full test suite: 936 passed, 1 failed (pre-existing), 1 skipped
- PyGithub 2.9.1 installed and importable
- All barrel imports succeed: `from kicad_agent.crawler import GithubDiscovery, FileFetcher, RateLimiter, RepoInfo, KicadFilePair`

## Self-Check: PASSED

- All 5 source/test files found on disk
- Both commits (ce9f3ed, 0f5cff8) found in git log
- No accidental file deletions in either commit
- No untracked files remaining
