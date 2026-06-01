---
phase: 46-component-function-recognition
plan: 02
subsystem: analysis
tags: [feature-extraction, ml-ready, sklearn, pytorch, confidence-calibration, jsonl, subcircuit, frozen-dataclass]

# Dependency graph
requires:
  - phase: 46-01
    provides: SubcircuitDetector with IC-centric BFS, CircuitClassifier with 13 ordered rules, _extract_features method
provides:
  - SubcircuitFeatures frozen dataclass with 26 fields for ML-ready feature vectors
  - extract_features function computing component counts, feedback, power, density, IC type, signal paths
  - ClassificationResult with feature_vector field for ML pipeline audit trail
  - CircuitClassifier accepting both dict and SubcircuitFeatures input
  - Confidence calibration: feature_vector populated for confidence < 0.5 (ML training data)
  - SubcircuitDetector.to_jsonl method for JSONL training data export
  - Merged features dict (ML fields + legacy classifier fields) for backward compatibility
affects: [domain-intelligence, circuit-qa, ml-training-pipeline]

# Tech tracking
tech-stack:
  added: []
patterns: [frozen-dataclass-feature-vector, merged-features-compat, jsonl-training-export, to_numeric_vector]

key-files:
  created:
    - src/kicad_agent/analysis/feature_extraction.py
  modified:
    - src/kicad_agent/analysis/circuit_classifier.py
    - src/kicad_agent/analysis/subcircuit_detector.py
    - src/kicad_agent/analysis/__init__.py
    - tests/test_subcircuit_detection.py

key-decisions:
  - "SubcircuitFeatures has 26 fields (not 25): subcircuit_id + 25 feature fields"
  - "Features dict merges ML fields (SubcircuitFeatures.to_dict) with legacy classifier fields (_extract_features) for backward compatibility"
  - "ClassificationResult.feature_vector populated only for confidence < 0.5 to minimize storage for high-confidence results"
  - "extract_features accepts optional input_nets/output_nets parameters for topology-level signal counting"

patterns-established:
  - "Feature vector pattern: SubcircuitFeatures frozen dataclass with to_dict/to_json/to_numeric_vector for ML pipeline compatibility"
  - "Merged features pattern: {**ml_features, **legacy_features} for backward compat during migration from dict to dataclass"

requirements-completed: [DOMAIN-03]

# Metrics
duration: 26min
completed: 2026-06-01
---

# Phase 46 Plan 02: Feature Extraction Summary

**ML-ready SubcircuitFeatures with 26-field frozen dataclass, confidence-calibrated ClassificationResult with feature_vector audit, and JSONL training data export from SubcircuitDetector**

## Performance

- **Duration:** 26 min
- **Started:** 2026-06-01T05:02:09Z
- **Completed:** 2026-06-01T05:28:06Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments
- SubcircuitFeatures frozen dataclass with 26 fields producing fixed-length feature vectors per subcircuit
- extract_features function computes component counts, feedback loops, power connections, density, IC type, signal paths from topology data
- ClassificationResult extended with feature_vector field for ML pipeline audit trail
- CircuitClassifier accepts both raw dict and SubcircuitFeatures input, populating feature_vector for unknown/ambiguous results
- SubcircuitDetector.detect() produces merged features dict combining ML fields with legacy classifier fields
- SubcircuitDetector.to_jsonl exports training data as JSONL (one JSON object per subcircuit)
- 35 new TDD tests covering features, confidence, unknown handling, batch, integration, determinism
- 2560 total tests pass (0 regressions)

## Task Commits

Each task was committed atomically:

1. **Task 1: SubcircuitFeatures dataclass and extract_features function** - `cad1bbb` (feat)
2. **Task 2: Confidence calibration and unknown/ambiguous handling** - `5b3128e` (feat)
3. **Task 3: Integrate feature extraction into SubcircuitDetector with JSONL export** - `7802b86` (feat)

**Plan metadata:** `110bd66` (chore: export updates)

## Files Created/Modified
- `src/kicad_agent/analysis/feature_extraction.py` - SubcircuitFeatures frozen dataclass (26 fields), extract_features function, _classify_ic_type helper, to_dict/to_json/to_numeric_vector/from_dict methods
- `src/kicad_agent/analysis/circuit_classifier.py` - ClassificationResult with feature_vector field, classify accepts SubcircuitFeatures, unknown logging with full feature vector
- `src/kicad_agent/analysis/subcircuit_detector.py` - detect() uses extract_features + legacy _extract_features merged, to_jsonl method for ML training export
- `src/kicad_agent/analysis/__init__.py` - Exports SubcircuitFeatures and extract_features
- `tests/test_subcircuit_detection.py` - 35 new tests: TestSubcircuitFeatures (6), TestFeatureExtraction (6), TestFeatureExtractionEdgeCases (6), TestConfidenceCalibration (6), TestUnknownHandling (3), TestBatchClassification (3), TestFeatureIntegration (5)

## Decisions Made
- SubcircuitFeatures has 26 fields total (plan said "25 fields" but that counted only the feature fields, not subcircuit_id)
- Features dict merges ML features with legacy classifier fields ({**ml_features, **legacy_features}) to maintain backward compatibility during migration from raw dict to structured dataclass
- ClassificationResult.feature_vector populated only for confidence < 0.5 to minimize storage overhead for high-confidence results while ensuring ML training data capture for ambiguous/unknown classifications
- extract_features accepts optional input_nets/output_nets set parameters for topology-level signal counting (not required for basic feature extraction)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed to_numeric_vector length assertion (22 vs 23)**
- **Found during:** Task 1 (test_to_numeric_vector)
- **Issue:** Test expected 22 elements but vector has 23 (7 component + 3 topology + 3 feedback + 8 net + 1 path + 1 density)
- **Fix:** Updated test assertion to expect 23 elements
- **Files modified:** tests/test_subcircuit_detection.py
- **Verification:** All 18 Task 1 tests pass
- **Committed in:** cad1bbb

**2. [Rule 1 - Bug] Fixed classifier regression from feature extraction integration**
- **Found during:** Task 3 (full test suite regression)
- **Issue:** New SubcircuitFeatures.to_dict() lacks lib_id, component_type, has_sidechain, has_vca_input, has_multiple_inputs, center_component, connector_count fields that classifier rules depend on
- **Fix:** Features dict merges ML fields (SubcircuitFeatures.to_dict) with legacy fields (_extract_features) for backward compatibility
- **Files modified:** src/kicad_agent/analysis/subcircuit_detector.py
- **Verification:** All 101 subcircuit tests pass, 2560 total tests pass
- **Committed in:** 7802b86

---

**Total deviations:** 2 auto-fixed (2 bugs)
**Impact on plan:** Both auto-fixes necessary for correctness. The merge strategy ensures classifier rules work unchanged while ML features are available. No scope creep.

## Issues Encountered
- Plan's extract_features pseudocode referenced topology.input_nets/output_nets without those being parameters -- added as optional input_nets/output_nets set parameters to the function signature
- Classifier field compatibility required keeping the legacy _extract_features method alongside the new extract_features module, with a merge strategy in detect()

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- SubcircuitFeatures ready for ML training pipeline integration
- JSONL export ready for sklearn/pytorch data loading
- Feature vectors deterministic and reproducible for consistent training data
- CircuitClassifier ready for ML-based augmentation (feature vectors logged for unknowns)

## Self-Check: PASSED

- All 5 source files exist: feature_extraction.py, circuit_classifier.py, subcircuit_detector.py, __init__.py, test_subcircuit_detection.py
- All 4 commits verified: cad1bbb, 5b3128e, 7802b86, 110bd66
- 101 subcircuit tests pass, 2560 total tests pass with no regressions

---
*Phase: 46-component-function-recognition*
*Completed: 2026-06-01*
