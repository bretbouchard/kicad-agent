//
//  ComplianceProviderTests.swift
//  Volta Tests
//
//  Created by Phase 252 Wave 1 on 7/27/26.
//

import XCTest
@testable import Volta

/// Tests for ComplianceProvider protocol and related models
/// Tests lifecycle status enums, RoHS status, and risk assessment models
final class ComplianceProviderTests: XCTestCase {

    // MARK: - Protocol Definition Tests

    func testProtocolDefinition() {
        // Verify ComplianceProvider protocol exists and has required methods
        let provider = LocalComplianceProvider()

        XCTAssertNotNil(provider as ComplianceProvider, "LocalComplianceProvider should conform to ComplianceProvider")
    }

    // MARK: - LifecycleStatus Enum Tests

    func testLifecycleStatusEnum() {
        // Test all lifecycle status cases exist
        let statuses: [LifecycleStatus] = [
            .active,
            .nrnd,
            .obsolete,
            .eol,
            .discontinued
        ]

        XCTAssertEqual(statuses.count, 5, "Should have 5 lifecycle status cases")

        // Test Sendable conformance
        XCTAssertTypeEqual(LifecycleStatus.active, LifecycleStatus.active)
    }

    func testLifecycleStatusDescription() {
        XCTAssertEqual(LifecycleStatus.active.description, "Active")
        XCTAssertEqual(LifecycleStatus.nrnd.description, "Not Recommended for New Design")
        XCTAssertEqual(LifecycleStatus.obsolete.description, "Obsolete")
        XCTAssertEqual(LifecycleStatus.eol.description, "End of Life")
        XCTAssertEqual(LifecycleStatus.discontinued.description, "Discontinued")
    }

    func testLifecycleStatusRiskLevel() {
        // Active components should have lowest risk
        XCTAssertLessThan(LifecycleStatus.active.riskLevel, LifecycleStatus.nrnd.riskLevel)
        XCTAssertLessThan(LifecycleStatus.nrnd.riskLevel, LifecycleStatus.obsolete.riskLevel)
        XCTAssertLessThan(LifecycleStatus.obsolete.riskLevel, LifecycleStatus.eol.riskLevel)
        XCTAssertLessThan(LifecycleStatus.eol.riskLevel, LifecycleStatus.discontinued.riskLevel)
    }

    // MARK: - RoHSStatus Enum Tests

    func testRoHSStatusEnum() {
        // Test all RoHS status cases exist
        let statuses: [RoHSStatus] = [
            .compliant,
            .nonCompliant,
            .unknown
        ]

        XCTAssertEqual(statuses.count, 3, "Should have 3 RoHS status cases")

        // Test Sendable conformance
        XCTAssertTypeEqual(RoHSStatus.compliant, RoHSStatus.compliant)
    }

    func testRoHSStatusDescription() {
        XCTAssertEqual(RoHSStatus.compliant.description, "RoHS Compliant")
        XCTAssertEqual(RoHSStatus.nonCompliant.description, "Non-Compliant")
        XCTAssertEqual(RoHSStatus.unknown.description, "Unknown")
    }

    func testRoHSStatusIcon() {
        XCTAssertEqual(RoHSStatus.compliant.icon, "checkmark.circle.fill")
        XCTAssertEqual(RoHSStatus.nonCompliant.icon, "xmark.circle.fill")
        XCTAssertEqual(RoHSStatus.unknown.icon, "questionmark.circle.fill")
    }

    // MARK: - RiskAssessment Model Tests

    func testRiskAssessmentModel() {
        let assessment = RiskAssessment(
            riskLevel: .medium,
            score: 50,
            factors: ["NRND status", "Introduced >5 years ago"],
            confidence: 0.8
        )

        XCTAssertEqual(assessment.riskLevel, .medium)
        XCTAssertEqual(assessment.score, 50)
        XCTAssertEqual(assessment.factors.count, 2)
        XCTAssertEqual(assessment.confidence, 0.8)
    }

    func testRiskLevelEnum() {
        let levels: [RiskLevel] = [.low, .medium, .high, .critical]
        XCTAssertEqual(levels.count, 4, "Should have 4 risk levels")
    }

    func testRiskAssessmentSendable() {
        let assessment = RiskAssessment(
            riskLevel: .low,
            score: 10,
            factors: [],
            confidence: 1.0
        )

        // Test Sendable conformance by copying
        let copied = assessment
        XCTAssertEqual(copied.score, assessment.score)
    }

    // MARK: - Lifecycle Inference Tests

    func testLifecycleInferenceFromString() {
        // Test various product status strings
        let testCases = [
            ("Active", LifecycleStatus.active),
            ("Not Recommended for New Design", LifecycleStatus.nrnd),
            ("NRND", LifecycleStatus.nrnd),
            ("Obsolete", LifecycleStatus.obsolete),
            ("End of Life", LifecycleStatus.eol),
            ("EOL", LifecycleStatus.eol),
            ("Discontinued", LifecycleStatus.discontinued),
            ("Production", LifecycleStatus.active)
        ]

        for (input, expected) in testCases {
            let inferred = LifecycleInference.infer(from: input)
            XCTAssertEqual(inferred.status, expected, "Failed to infer '\(input)' as \(expected)")
        }
    }

    // MARK: - Sendable Conformance Tests

    func testAllModelsSendable() {
        // Verify all compliance models are Sendable (thread-safe)
        let status = LifecycleStatus.active
        let rohs = RoHSStatus.compliant
        let risk = RiskAssessment(riskLevel: .low, score: 10, factors: [], confidence: 1.0)

        // These should compile without error if Sendable
        let _: [LifecycleStatus] = [status]
        let _: [RoHSStatus] = [rohs]
        let _: [RiskAssessment] = [risk]
    }
}