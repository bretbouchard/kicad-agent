---
phase: 17-package-and-distribution
plan: 01
subsystem: infra
tags: [setuptools, setuptools-scm, packaging, pypi, build, wheel, sdist]

# Dependency graph
requires: []
provides:
  - "Complete pyproject.toml with [build-system], dynamic versioning, full metadata"
  - "Dynamic __version__ via importlib.metadata in __init__.py"
  - "Packaging smoke tests covering version, imports, CLI, and build"
affects: [17-02, 17-03, ci-cd]

# Tech tracking
tech-stack:
  added: [setuptools>=75.0, setuptools-scm>=10.0, mkdocs-material>=9.7, mkdocstrings-python>=2.0]
  patterns: [importlib.metadata dynamic versioning, src-layout package discovery, setuptools-scm git-tag versioning]

key-files:
  created:
    - tests/test_packaging.py
  modified:
    - pyproject.toml
    - src/kicad_agent/__init__.py

key-decisions:
  - "Removed License classifier to resolve PEP 639 conflict with license field in setuptools>=75"
  - "Registered pytest.mark.slow in pyproject.toml for build integration test"
  - "Fallback version 0.0.0 makes setuptools-scm failures obvious (not silent)"

patterns-established:
  - "Dynamic versioning: importlib.metadata.version() in __init__.py, setuptools-scm derives from git tags"
  - "Build verification: test_packaging.py confirms wheel/sdist production and correct contents"

requirements-completed: [DIST-01, DIST-02]

# Metrics
duration: 9min
completed: 2026-05-24
---

# Phase 17 Plan 01: Package Build System and Metadata Summary

**setuptools build system with setuptools-scm dynamic versioning from git tags and complete pyproject.toml metadata**

## Performance

- **Duration:** 9 min
- **Started:** 2026-05-24T01:31:56Z
- **Completed:** 2026-05-24T01:41:22Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Added [build-system] section with setuptools backend and setuptools-scm for version derivation from git state
- Replaced hardcoded version with dynamic versioning; __init__.py now reads from importlib.metadata
- Added complete package metadata: readme, license (MIT), classifiers, project URLs, docs optional-dependencies
- Created comprehensive packaging smoke tests (7 tests) covering version, imports, CLI, and build
- Verified python -m build produces both sdist and wheel; wheel contains 136 Python files, no tests/

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: Packaging smoke tests** - `593d85b` (test)
2. **Task 1 GREEN: Build system and dynamic versioning** - `181562c` (feat)

## Files Created/Modified
- `pyproject.toml` - Added [build-system], dynamic version, classifiers, project URLs, docs deps, setuptools config
- `src/kicad_agent/__init__.py` - Dynamic __version__ via importlib.metadata with PackageNotFoundError fallback
- `tests/test_packaging.py` - 7 smoke tests: version validation, public imports, CLI schema, build integration

## Decisions Made
- Removed `License :: OSI Approved :: MIT License` classifier because PEP 639 in setuptools>=75 conflicts with `license = "MIT"` field -- the license field supersedes the classifier
- Registered `pytest.mark.slow` marker in pyproject.toml to eliminate UnknownMarkWarning for build tests
- Fallback version "0.0.0" chosen so setuptools-scm failures are immediately visible, not silent

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed License classifier for PEP 639 compliance**
- **Found during:** Task 1 (pip install -e . failed)
- **Issue:** setuptools>=75 enforces PEP 639: `License :: OSI Approved :: MIT License` classifier conflicts with `license = "MIT"` field, causing InvalidConfigError
- **Fix:** Removed the license classifier line; `license = "MIT"` field is the correct PEP 639 approach
- **Files modified:** pyproject.toml
- **Verification:** `pip install -e .` succeeds, build produces valid wheel
- **Committed in:** 181562c (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Minor -- plan specified the classifier, but newer setuptools rejects it. No scope creep.

## Issues Encountered
None beyond the PEP 639 classifier conflict documented above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Build system complete, ready for 17-02 (CI/CD configuration)
- `pip install .` and `python -m build` both produce valid distributable packages
- setuptools-scm will derive version from git tags once tagged (e.g., `v0.1.0` tag produces `0.1.0` version)

## Self-Check: PASSED

- FOUND: pyproject.toml
- FOUND: src/kicad_agent/__init__.py
- FOUND: tests/test_packaging.py
- FOUND: 593d85b (test commit)
- FOUND: 181562c (feat commit)

---
*Phase: 17-package-and-distribution*
*Completed: 2026-05-24*
