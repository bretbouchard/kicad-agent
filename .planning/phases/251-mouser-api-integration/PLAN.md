# Phase 251: Mouser API Integration

**Status:** Planning  
**Created:** 2026-07-27  
**Goal:** Integrate Mouser API as component data provider in Volta app

---

## Overview

Integrate Mouser Electronics API into the existing ComponentDataProvider registry to enable real-time pricing, stock, and specification lookups alongside the existing Digi-Key (Nexar) integration.

**API Key Status:** ✅ Stored in macOS Keychain (`com.volta.mouser.api_key`)

---

## Requirements Mapping

| Requirement | Source | Implementation |
|-------------|--------|----------------|
| COMP-01 | Component pricing | Mouser API Part Search endpoint |
| COMP-02 | Real-time stock | Mouser API Stock endpoint |
| COMP-03 | Specifications | Mouser API Part Details endpoint |
| COMP-04 | MPN cross-reference | Mouser API Part Search with MPN |
| COMP-05 | Datasheet access | Mouser API Datasheet endpoint |

---

## Technical Approach

### Architecture

```swift
// Existing ComponentDataProvider protocol
protocol ComponentDataProvider {
    func searchParts(query: String) async throws -> [ComponentPart]
    func getPartDetails(mpn: String) async throws -> ComponentPart
    func getStock(mpn: String) async throws -> StockStatus
}

// New MouserProvider
struct MouserProvider: ComponentProvider, Sendable {
    private let apiKey: String
    private let baseURL = "https://api.mouser.com/api/v1"
    
    func searchParts(query: String) async throws -> [ComponentPart] {
        // Call Mouser Part Search API
    }
}
```

### Integration Points

1. **Provider Registry** — Register `MouserProvider` in existing `ComponentDataProviderRegistry`
2. **Settings UI** — Add Mouser API key configuration in Settings
3. **SwiftData** — Cache Mouser responses alongside Digi-Key data
4. **Fastlane** — Add Mouser API credentials to matchfile signing

---

## Task Breakdown

### Task 251-01: MouserProvider Core Implementation

**File:** `Sources/Providers/MouserProvider.swift`

**Subtasks:**
- [ ] Implement `MouserProvider` struct conforming to `ComponentDataProvider`
- [ ] Add API key retrieval from Keychain (`com.volta.mouser.api_key`)
- [ ] Implement HTTP client with proper headers (API key, Content-Type)
- [ ] Add error handling for rate limits (429) and invalid keys (401)
- [ ] Add request signing per Mouser API requirements

**Tests:**
- [ ] `MouserProviderTests.testAPIKeyRetrieval`
- [ ] `MouserProviderTests.testSearchPartsSuccess`
- [ ] `MouserProviderTests.testSearchPartsRateLimit`
- [ ] `MouserProviderTests.testInvalidAPIKey`

---

### Task 251-02: Part Search Integration

**Endpoint:** `GET /api/v1/search/partsearch`

**Implementation:**
- [ ] Implement `searchParts(query: String)` method
- [ ] Map Mouser JSON response to `ComponentPart` model
- [ ] Handle pagination for large result sets
- [ ] Add query parameter escaping and validation

**Tests:**
- [ ] `MouserProviderTests.testSearchByPartNumber`
- [ ] `MouserProviderTests.testSearchByKeyword`
- [ ] `MouserProviderTests.testPaginationHandling`
- [ ] `MouserProviderTests.testEmptyResults`

---

### Task 251-03: Stock Status Integration

**Endpoint:** `GET /api/v1/stock/part`

**Implementation:**
- [ ] Implement `getStock(mpn: String)` method
- [ ] Map stock quantities to `StockStatus` enum
- [ ] Handle multiple warehouse locations
- [ ] Add last-updated timestamp tracking

**Tests:**
- [ ] `MouserProviderTests.testStockInStock`
- [ ] `MouserProviderTests.testStockOutOfStock`
- [ ] `MouserProviderTests.testStockMultipleWarehouses`
- [ ] `MouserProviderTests.testStockCacheExpiry`

---

### Task 251-04: Part Details Integration

**Endpoint:** `GET /api/v1/parts/{partNumber}`

**Implementation:**
- [ ] Implement `getPartDetails(mpn: String)` method
- [ ] Map specifications to `ComponentSpec` model
- [ ] Parse datasheet URLs and download links
- [ ] Extract pricing tiers (quantity breaks)

**Tests:**
- [ ] `MouserProviderTests.testPartDetailsSuccess`
- [ ] `MouserProviderTests.testPartDetailsNotFound`
- [ ] `MouserProviderTests.testPricingTierParsing`
- [ ] `MouserProviderTests.testDatasheetURLExtraction`

---

### Task 251-05: SwiftData Caching Layer

**File:** `Sources/Cache/MouserCache.swift`

**Implementation:**
- [ ] Create `MouserCache` model for SwiftData
- [ ] Add cache expiry logic (24 hours for stock, 7 days for specs)
- [ ] Implement cache invalidation on API errors
- [ ] Add background refresh for critical stock data

**Tests:**
- [ ] `MouserCacheTests.testCacheHit`
- [ ] `MouserCacheTests.testCacheMiss`
- [ ] `MouserCacheTests.testCacheExpiry`
- [ ] `MouserCacheTests.testCacheInvalidation`

---

### Task 251-06: Settings UI Integration

**File:** `Volta/Views/Settings/ProviderSettingsView.swift`

**Implementation:**
- [ ] Add Mouser provider toggle in Settings
- [ ] Add API key configuration field
- [ ] Add test connection button
- [ ] Display rate limit status and quota

**Tests:**
- [ ] `ProviderSettingsViewTests.testMouserToggle`
- [ ] `ProviderSettingsViewTests.testAPIKeyValidation`
- [ ] `ProviderSettingsViewTests.testConnectionTest`

---

### Task 251-07: Provider Registry Registration

**File:** `Sources/Registry/ComponentDataProviderRegistry.swift`

**Implementation:**
- [ ] Add `MouserProvider` to registry initialization
- [ ] Implement provider priority ordering (Digi-Key, Mouser, Octopart)
- [ ] Add provider fallback logic on failures
- [ ] Log provider selection to audit trail

**Tests:**
- [ ] `ProviderRegistryTests.testMouserRegistration`
- [ ] `ProviderRegistryTests.testProviderPriority`
- [ ] `ProviderRegistryTests.testProviderFallback`

---

### Task 251-08: Error Handling & Edge Cases

**Implementation:**
- [ ] Handle Mouser API downtime gracefully
- [ ] Add retry logic with exponential backoff
- [ ] Implement circuit breaker for repeated failures
- [ ] Add user-friendly error messages

**Tests:**
- [ ] `MouserProviderTests.testRetryLogic`
- [ ] `MouserProviderTests.testCircuitBreaker`
- [ ] `MouserProviderTests.testDowntimeHandling`

---

### Task 251-09: Documentation & Examples

**Deliverables:**
- [ ] Update `README.md` with Mouser integration docs
- [ ] Add example code for part search
- [ ] Document API key setup process
- [ ] Create troubleshooting guide

---

## Dependencies

**Required:**
- ✅ API key stored in Keychain
- ✅ Existing `ComponentDataProvider` protocol
- ✅ SwiftData cache infrastructure
- ✅ Settings UI structure

**External:**
- Mouser API documentation: https://www.mouser.com/api
- API signup: https://www.mouser.com/api (self-serve, free)

---

## Testing Strategy

### Unit Tests
- 25+ tests covering all MouserProvider methods
- Mock HTTP responses for edge cases
- Cache behavior validation
- Error scenario testing

### Integration Tests
- End-to-end part search flow
- Settings UI → API key → actual API call
- Cache refresh cycles
- Provider fallback logic

### Manual Testing
- Test with real Mouser API key
- Verify stock accuracy for known parts
- Test rate limiting behavior
- Validate Settings UI in Fastlane

---

## Acceptance Criteria

Phase 251 is COMPLETE when:
- ✅ All 25+ unit tests pass
- ✅ Integration tests pass with mock API
- ✅ Manual testing confirms real API calls work
- ✅ Settings UI allows API key configuration
- ✅ SwiftData caching works correctly
- ✅ Provider registry includes Mouser
- ✅ Error handling is graceful and user-friendly
- ✅ Documentation is complete

---

## Estimated Effort

| Task | Estimated Time | Complexity |
|------|----------------|------------|
| 251-01: Core Implementation | 4h | Medium |
| 251-02: Part Search | 3h | Medium |
| 251-03: Stock Status | 2h | Low |
| 251-04: Part Details | 3h | Medium |
| 251-05: Caching Layer | 3h | Medium |
| 251-06: Settings UI | 2h | Low |
| 251-07: Registry | 1h | Low |
| 251-08: Error Handling | 2h | Medium |
| 251-09: Documentation | 1h | Low |
| **Total** | **21h** | **Medium** |

---

## Risks & Mitigations

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| API rate limits | Medium | Medium | Implement caching + exponential backoff |
| API changes | Low | High | Version endpoint in base URL |
| Invalid API keys | Low | Low | Validate key in Settings UI |
| Downtime | Low | Medium | Graceful fallback to other providers |

---

## Next Steps

1. ✅ Execute Phase 251 implementation
2. ⏭️  Proceed to Phase 252 (Compliance Provider System)
3. ⏭️  Integration testing with Digi-Key + Mouser
4. ⏭️  User acceptance testing

---

*Phase 251 Planning Complete*  
*Ready for execution via `/gsd-execute-phase 251`*