//
//  EasyEdaErrorTests.swift
//  VoltaTests
//
//  Phase 4 / Task 6b — Sandbox Cleanup.
//
//  Tests for EasyEdaError error cases.
//

import XCTest
@testable import Volta

final class EasyEdaErrorTests: XCTestCase {

    func test_networkError_hasDescription() {
        let error = EasyEdaError.networkError(underlying: "DNS failure")
        XCTAssertTrue(error.errorDescription?.contains("DNS failure") ?? false)
    }

    func test_httpError_hasDescription() {
        let error = EasyEdaError.httpError(status: 503)
        XCTAssertEqual(error.errorDescription, "EasyEDA API returned HTTP 503.")
    }

    func test_responseSchemaMismatch_carriesRawBody() {
        let raw = #"{"unexpected":"shape"}"#
        let error = EasyEdaError.responseSchemaMismatch(rawResponse: raw)
        XCTAssertTrue(error.errorDescription?.contains("EasyEDA response schema mismatch") ?? false)
        // Raw body must be in description (truncated) for debuggability.
        XCTAssertTrue(error.errorDescription?.contains("EasyEDA") ?? false)
    }

    func test_incompleteProduct_carriesFieldName() {
        let error = EasyEdaError.incompleteProduct(missingField: "footprintUuid")
        XCTAssertTrue(error.errorDescription?.contains("footprintUuid") ?? false)
    }

    func test_allCases_areSendable() {
        // Compile-time check that EasyEdaError conforms to Sendable.
        let errors: [EasyEdaError] = [
            .networkError(underlying: "x"),
            .httpError(status: 500),
            .responseSchemaMismatch(rawResponse: "{}"),
            .incompleteProduct(missingField: "x")
        ]
        XCTAssertEqual(errors.count, 4)
    }
}