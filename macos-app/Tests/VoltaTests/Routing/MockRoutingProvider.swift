//
//  MockRoutingProvider.swift
//  VoltaTests
//
//  Phase 253 Task 1 — Test fixture for RoutingProvider.
//
//  Mock provider conforming to RoutingProvider from VoltaPCBCore. Lets
//  registry + adapter tests exercise the protocol surface without
//  shelling out to Freerouting / KiCad. Tracks call counts and the
//  last observed RoutingRules for assertion.
//

import Foundation
@testable import VoltaPCBCore

/// Mock routing provider for testing.
final class MockRoutingProvider: RoutingProvider, @unchecked Sendable {
    let name: String
    let displayName: String
    let capabilities: Set<RoutingCapability>
    let mockAvailability: ProviderAvailability
    let mockResult: RoutingResult?
    let mockEstimate: TimeInterval?
    let shouldThrow: Bool

    /// Number of times `route(...)` was invoked.
    private(set) var routeCallCount: Int = 0
    /// Last RoutingRules passed to `route(...)`.
    private(set) var lastRules: RoutingRules?

    init(
        name: String,
        displayName: String,
        capabilities: Set<RoutingCapability> = [.autoroute, .offline],
        mockAvailability: ProviderAvailability = .available,
        mockResult: RoutingResult? = nil,
        mockEstimate: TimeInterval? = 5.0,
        shouldThrow: Bool = false
    ) {
        self.name = name
        self.displayName = displayName
        self.capabilities = capabilities
        self.mockAvailability = mockAvailability
        self.mockResult = mockResult
        self.mockEstimate = mockEstimate
        self.shouldThrow = shouldThrow
    }

    var availability: ProviderAvailability { mockAvailability }

    func route(
        pcbFile: URL,
        rules: RoutingRules,
        progress: (@Sendable (RoutingProgress) -> Void)?
    ) async throws -> RoutingResult {
        routeCallCount += 1
        lastRules = rules
        progress?(.started)
        progress?(.completed)
        if shouldThrow {
            throw RoutingTestError.simulatedFailure
        }
        guard let result = mockResult else {
            throw RoutingTestError.noMockResult
        }
        return result
    }

    func estimateTime(board: PCBSummary) -> TimeInterval? {
        mockEstimate
    }
}

/// Errors raised by MockRoutingProvider under test conditions.
enum RoutingTestError: Error, Equatable {
    case simulatedFailure
    case noMockResult
}