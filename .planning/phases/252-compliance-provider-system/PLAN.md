# Phase 252: Compliance Provider System

**Status:** Planning  
**Created:** 2026-07-27  
**Goal:** Implement lifecycle status and compliance tracking for components

---

## Overview

Build a compliance provider system that enables lifecycle tracking (active, NRND, obsolete, EOL), RoHS compliance status, and risk assessment for electronic components. This replaces the blocked SiliconExpert integration with a local cache-based approach plus manual file import workflow.

**Strategy:** Hybrid approach — LocalComplianceProvider (offline, cached data) + SnapMagic File Import (manual workflow)

---

## Requirements Mapping

| Requirement | Source | Implementation |
|-------------|--------|----------------|
| COMP-06 | Lifecycle status | LocalComplianceProvider from cached data |
| COMP-07 | RoHS compliance | Inferred from Digi-Key/Mouser specs |
| COMP-08 | Risk assessment | Simple heuristic based on lifecycle + age |
| COMP-09 | Obsolescence prediction | Based on NRND → EOL transition patterns |
| COMP-10 | Alternative parts | Manual import via SnapMagic workflow |

---

## Technical Approach

### Architecture

```swift
// New ComplianceProvider protocol
protocol ComplianceProvider {
    func getLifecycleStatus(mpn: String) async throws -> LifecycleStatus
    func checkRoHSCompliance(mpn: String) async throws -> RoHSStatus
    func assessRisk(mpn: String) async throws -> RiskAssessment
    func getAlternatives(mpn: String) async throws -> [ComponentPart]
}

// Local implementation (offline, cache-based)
struct LocalComplianceProvider: ComplianceProvider, Sendable {
    private let componentCache: ComponentCache
    private let complianceRules: ComplianceRules
    
    func getLifecycleStatus(mpn: String) async throws -> LifecycleStatus {
        // Infer from cached component data
    }
}
```

### Integration Points

1. **Component Cache** — Leverage existing SwiftData component cache
2. **Provider Registry** — Add `ComplianceProviderRegistry` 
3. **Settings UI** — Add compliance provider settings
4. **File Import** — SnapMagic CSV/JSON import workflow

---

## Task Breakdown

### Task 252-01: ComplianceProvider Protocol Definition

**File:** `Sources/Protocols/ComplianceProvider.swift`

**Subtasks:**
- [ ] Define `ComplianceProvider` protocol with lifecycle methods
- [ ] Define `LifecycleStatus` enum (active, nrnd, obsolete, eol, discontinued)
- [ ] Define `RoHSStatus` enum (compliant, nonCompliant, unknown)
- [ ] Define `RiskAssessment` model (risk level, factors, confidence)
- [ ] Add Sendable conformance for all models

**Tests:**
- [ ] `ComplianceProviderTests.testProtocolDefinition`
- [ ] `ComplianceProviderTests.testLifecycleStatusEnum`
- [ ] `ComplianceProviderTests.testRoHSStatusEnum`

---

### Task 252-02: LocalComplianceProvider Core Implementation

**File:** `Sources/Providers/LocalComplianceProvider.swift`

**Subtasks:**
- [ ] Implement `LocalComplianceProvider` struct
- [ ] Add dependency injection for component cache
- [ ] Implement `getLifecycleStatus()` from cache analysis
- [ ] Implement `checkRoHSCompliance()` from spec parsing
- [ ] Implement `assessRisk()` heuristic algorithm

**Tests:**
- [ ] `LocalComplianceProviderTests.testLifecycleFromCache`
- [ ] `LocalComplianceProviderTests.testRoHSFromSpecs`
- [ ] `LocalComplianceProviderTests.testRiskAssessment`
- [ ] `LocalComplianceProviderTests.testCacheMissHandling`

---

### Task 252-03: Lifecycle Inference Engine

**File:** `Sources/Compliance/LifecycleInference.swift`

**Implementation:**
- [ ] Create lifecycle status inference from product status strings
- [ ] Detect NRND keywords ("not recommended", "phase out")
- [ ] Detect EOL keywords ("end of life", "discontinued")
- [ ] Add confidence scoring for inferred status
- [ ] Handle ambiguous status strings

**Tests:**
- [ ] `LifecycleInferenceTests.testActiveStatus`
- [ ] `LifecycleInferenceTests.testNRNDDetection`
- [ ] `LifecycleInferenceTests.testEOLDetection`
- [ ] `LifecycleInferenceTests.testAmbiguousStatus`
- [ ] `LifecycleInferenceTests.testConfidenceScoring`

---

### Task 252-04: RoHS Compliance Detection

**File:** `Sources/Compliance/RoHSDetector.swift`

**Implementation:**
- [ ] Parse RoHS compliance from component specifications
- [ ] Detect RoHS keywords in spec descriptions
- [ ] Extract RoHS exemption codes if present
- [ ] Handle missing RoHS data gracefully
- [ ] Add country-specific regulation detection

**Tests:**
- [ ] `RoHSDetectorTests.testCompliantDetection`
- [ ] `RoHSDetectorTests.testNonCompliantDetection`
- [ ] `RoHSDetectorTests.testExemptionCodeParsing`
- [ ] `RoHSDetectorTests.testMissingData`

---

### Task 252-05: Risk Assessment Algorithm

**File:** `Sources/Compliance/RiskAssessment.swift`

**Implementation:**
- [ ] Implement risk scoring algorithm (0-100 scale)
- [ ] Factors: lifecycle status, age, stock availability, alternatives
- [ ] Weighted scoring for each risk factor
- [ ] Risk level categorization (low, medium, high, critical)
- [ ] Confidence interval for predictions

**Tests:**
- [ ] `RiskAssessmentTests.testActiveComponentLowRisk`
- [ ] `RiskAssessmentTests.testNRNDComponentMediumRisk`
- [ ] `RiskAssessmentTests.testEOLComponentHighRisk`
- [ ] `RiskAssessmentTests.testWeightedScoring`
- [ ] `RiskAssessmentTests.testConfidenceIntervals`

---

### Task 252-06: SnapMagic File Import Workflow

**File:** `Sources/Import/SnapMagicImport.swift`

**Implementation:**
- [ ] Create file import UI (CSV/JSON support)
- [ ] Parse SnapMagic compliance export format
- [ ] Merge imported data with component cache
- [ ] Add import validation and error handling
- [ ] Support manual user entry of compliance data

**Tests:**
- [ ] `SnapMagicImportTests.testCSVParser`
- [ ] `SnapMagicImportTests.testJSONParser`
- [ ] `SnapMagicImportTests testDataMerge`
- [ ] `SnapMagicImportTests.testImportValidation`
- [ ] `SnapMagicImportTests.testManualEntry`

---

### Task 252-07: Compliance Cache Model

**File:** `Sources/Cache/ComplianceCache.swift`

**Implementation:**
- [ ] Create SwiftData model for compliance cache
- [ ] Add cache expiry logic (30 days for lifecycle, 7 days for stock)
- [ ] Implement cache refresh triggers
- [ ] Add cache size management (LRU eviction)
- [ ] Support incremental updates

**Tests:**
- [ ] `ComplianceCacheTests.testCacheStorage`
- [ ] `ComplianceCacheTests.testCacheExpiry`
- [ ] `ComplianceCacheTests.testCacheRefresh`
- [ ] `ComplianceCacheTests.testLRUEviction`

---

### Task 252-08: Settings UI Integration

**File:** `Volta/Views/Settings/ComplianceSettingsView.swift`

**Implementation:**
- [ ] Add compliance provider settings in Settings
- [ ] Toggle for LocalComplianceProvider
- [ ] File import button and workflow
- [ ] Cache management (clear, refresh, size display)
- [ ] Risk assessment threshold configuration

**Tests:**
- [ ] `ComplianceSettingsViewTests.testProviderToggle`
- [ ] `ComplianceSettingsViewTests.testImportWorkflow`
- [ ] `ComplianceSettingsViewTests.testCacheManagement`

---

### Task 252-09: Provider Registry & Routing

**File:** `Sources/Registry/ComplianceProviderRegistry.swift`

**Implementation:**
- [ ] Create `ComplianceProviderRegistry` 
- [ ] Register LocalComplianceProvider
- [ ] Add provider selection logic
- [ ] Implement fallback to manual import
- [ ] Add audit logging for compliance checks

**Tests:**
- [ ] `ComplianceProviderRegistryTests.testRegistration`
- [ ] `ComplianceProviderRegistryTests.testProviderSelection`
- [ ] `ComplianceProviderRegistryTests.testFallbackLogic`

---

### Task 252-10: UI Components for Compliance Display

**File:** `Volta/Views/Components/ComplianceBadge.swift`

**Implementation:**
- [ ] Create compliance status badge component
- [ ] Add lifecycle status indicator
- [ ] Risk assessment visual indicator (color-coded)
- [ ] Add RoHS compliance icon
- [ ] Tooltip with detailed compliance info

**Tests:**
- [ ] `ComplianceBadgeTests.testLifecycleDisplay`
- [ ] `ComplianceBadgeTests.testRiskIndicator`
- [ ] `ComplianceBadgeTests.testRoHSIcon`

---

### Task 252-11: Error Handling & Edge Cases

**Implementation:**
- [ ] Handle missing compliance data gracefully
- [ ] Add user manual entry workflow
- [ ] Implement data validation checks
- [ ] Add conflict resolution for conflicting data sources
- [ ] Handle import errors gracefully

**Tests:**
- [ ] `LocalComplianceProviderTests.testMissingDataHandling`
- [ ] `SnapMagicImportTests.testErrorRecovery`
- [ ] `ComplianceProviderTests.testDataValidation`

---

### Task 252-12: Documentation & User Guide

**Deliverables:**
- [ ] Update `README.md` with compliance system docs
- [ ] Create SnapMagic import guide
- [ ] Document risk assessment algorithm
- [ ] Create troubleshooting guide
- [ ] Add user guide for manual compliance entry

---

## Dependencies

**Required:**
- ✅ Component cache from Digi-Key/Mouser integration
- ✅ SwiftData infrastructure
- ✅ Settings UI structure
- ✅ Provider registry patterns

**External:**
- SnapMagic export format documentation (for import workflow)
- RoHS compliance regulation reference

---

## Testing Strategy

### Unit Tests
- 30+ tests covering all compliance algorithms
- Mock component data for inference testing
- Cache behavior validation
- Edge case handling (missing data, conflicts)

### Integration Tests
- End-to-end compliance check flow
- File import workflow testing
- Cache refresh cycles
- UI component display testing

### Manual Testing
- Test with real component data from Digi-Key/Mouser
- Verify SnapMagic CSV import workflow
- Validate risk assessment accuracy
- Test Settings UI in Fastlane

---

## Acceptance Criteria

Phase 252 is COMPLETE when:
- ✅ All 30+ unit tests pass
- ✅ Integration tests pass with mock data
- ✅ Manual testing confirms real component compliance detection
- ✅ SnapMagic import workflow works end-to-end
- ✅ Settings UI allows compliance provider configuration
- ✅ SwiftData caching works correctly
- ✅ UI components display compliance status accurately
- ✅ Error handling is graceful and user-friendly
- ✅ Documentation is complete

---

## Estimated Effort

| Task | Estimated Time | Complexity |
|------|----------------|------------|
| 252-01: Protocol Definition | 2h | Low |
| 252-02: Core Implementation | 4h | Medium |
| 252-03: Lifecycle Inference | 3h | Medium |
| 252-04: RoHS Detection | 2h | Low |
| 252-05: Risk Assessment | 4h | Medium |
| 252-06: File Import | 5h | High |
| 252-07: Cache Model | 3h | Medium |
| 252-08: Settings UI | 3h | Medium |
| 252-09: Registry | 2h | Low |
| 252-10: UI Components | 3h | Medium |
| 252-11: Error Handling | 2h | Medium |
| 252-12: Documentation | 2h | Low |
| **Total** | **35h** | **Medium** |

---

## Risks & Mitigations

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| Inaccurate lifecycle inference | Medium | Medium | Confidence scoring + manual review |
| Missing compliance data | High | Low | Manual entry workflow |
| SnapMagic format changes | Low | Medium | Version detection + graceful fallback |
| Cache size growth | Medium | Low | LRU eviction + size limits |

---

## Future Enhancements (Deferred)

- **SiliconExpert integration** — Re-evaluate when revenue > $500K/year OR >5 employees
- **Automated alternative part suggestion** — ML-based recommendation engine
- **Real-time compliance monitoring** — Webhook-based updates from manufacturers
- **Compliance alert system** — Proactive notifications for EOL transitions

---

## Next Steps

1. ✅ Execute Phase 251 (Mouser API Integration)
2. ✅ Execute Phase 252 (Compliance Provider System)
3. ⏭️  Integration testing across all providers
4. ⏭️  User acceptance testing
5. ⏭️  Documentation and deployment

---

*Phase 252 Planning Complete*  
*Ready for execution via `/gsd-execute-phase 252`*