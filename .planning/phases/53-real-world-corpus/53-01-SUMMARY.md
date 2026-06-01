---
phase: 53-real-world-corpus
plan: 01
subsystem: training
tags: [corpus-curation, real-world-data, license-tracking, quality-gates, project-index]
dependency_graph:
  requires: [52-01]
  provides: [corpus-curator, project-index]
  affects: [training]
tech_stack:
  added: [pydantic-curated-project, project-index-search]
  patterns: [quality-gates, spdx-license-tracking, keyword-classification]
key_files:
  created:
    - src/kicad_agent/training/corpus_curator.py
    - src/kicad_agent/training/project_index.py
    - tests/test_corpus_curator.py
  modified: []
decisions:
  - "Used git clone --depth 1 for repo downloads instead of FileFetcher (FileFetcher requires PyGithub client, adds unnecessary dependency for full-repo download)"
  - "build_schematic_graph called with sch_path=Path kwarg matching actual API signature (plan assumed positional str arg)"
  - "50 curated source projects defined inline as _default_sources (plan suggested extracting to JSON later)"
metrics:
  duration: 4m
  completed: 2026-06-01
  tasks: 2
  files: 3
  tests: 40
  commits: 1
---

# Phase 53 Real-World Corpus Summary

Curated corpus pipeline with quality gates, SPDX license tracking, and searchable index over 50+ open-source hardware projects for circuit-level training data.

## Plan Completed

### Plan 53-01: CuratedProject Schema, CorpusCurator, and ProjectIndex

**Commit:** 2da4f47

- `CuratedProject` Pydantic schema with name, source_url, license (SPDX), category, complexity_score (0-10), erc_status, component/net/sheet counts, commercial_use_compatible flag
- `CorpusCurator` pipeline: download -> validate -> parse -> classify -> index
  - Quality gates: >= 5 components, >= 3 nets, parse without errors
  - Classification via keyword matching across 10 categories (audio, power, microcontroller, sensor, communication, display, motor, robotics, analog, digital)
  - Complexity scoring based on log-scaled component/net/sheet counts
  - URL domain validation (github.com, hackaday.io only)
  - SHA256 content hash for integrity verification
  - 50MB max download size
- 50+ curated open-source hardware sources across diverse categories
- `ProjectIndex` with search/filter by category, complexity range, license compatibility, component count (ANDed filters)
- `IndexStats` with summary statistics
- JSONL and JSON serialization for persistence

## Key Technical Decisions

1. **git clone --depth 1** for downloads instead of FileFetcher -- FileFetcher requires a PyGithub client object and is designed for sparse file fetching. Full-repo download via shallow git clone is simpler and more robust.

2. **build_schematic_graph kwarg** -- Plan assumed `build_schematic_graph(filepath)` but actual signature is `build_schematic_graph(sch_path=Path, sample_id=0, ...)`. Used keyword arg `sch_path=sch`.

3. **SPDX validation** -- Accepts NOASSERTION (GitHub's default for unidentified licenses) and any string >= 2 chars. Full SPDX catalog validation deferred.

## Deviations from Plan

### [Rule 3 - Blocking] Fixed FileFetcher and build_schematic_graph API mismatches
- **Found during:** Task 1 implementation
- **Issue:** Plan used `FileFetcher()` (no args) but constructor requires `github_client` and `staging_dir`. Plan used `build_schematic_graph(str)` but actual signature takes `sch_path=Path`.
- **Fix:** Replaced FileFetcher with `git clone --depth 1` for whole-repo download. Used keyword arg `sch_path=sch` for schematic graph builder.
- **Files modified:** src/kicad_agent/training/corpus_curator.py
- **Commit:** 2da4f47

## Test Coverage

- **40 tests** in `tests/test_corpus_curator.py`
- TestCuratedProjectSchema (8): validation, defaults, erc_status pattern
- TestCorpusCurator (16): license compatibility, classification, complexity, validation, batch, dedup, sources count
- TestLicenseCompatibility (5): MIT, Apache, CERN-OHL, CC-BY-NC, NOASSERTION
- TestCorpusCuratorSerialization (1): JSONL round-trip
- TestProjectIndex (10): build, search by category/complexity/license/components, combined filters, stats, JSON round-trip

## Verification

```
$ python -c "from kicad_agent.training.corpus_curator import CorpusCurator; c = CorpusCurator(); print(f'{len(c._default_sources())} default sources')"
50 default sources

$ python -c "from kicad_agent.training.corpus_curator import CorpusCurator; c = CorpusCurator(); print(c.classify_project('esp32-audio-shield', 'Audio shield for ESP32', ['audio', 'esp32']))"
audio
```
