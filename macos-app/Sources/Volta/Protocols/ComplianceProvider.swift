//
//  ComplianceProvider.swift
//  Volta
//
//  Created by Phase 252 Wave 1 on 7/27/26.
//

import Foundation

// MARK: - Compliance Provider Protocol

/// Protocol for compliance-related component information
/// Provides lifecycle status, RoHS compliance, risk assessment, and alternative parts
protocol ComplianceProvider: Sendable {
    /// Get lifecycle status for a component MPN
    func getLifecycleStatus(mpn: String) async throws -> LifecycleStatus

    /// Check RoHS compliance status
    func checkRoHSCompliance(mpn: String) async throws -> RoHSStatus

    /// Assess component risk level
    func assessRisk(mpn: String) async throws -> RiskAssessment

    /// Get alternative parts for a component
    func getAlternatives(mpn: String) async throws -> [ComponentPart]
}

// MARK: - Lifecycle Status

/// Lifecycle status of a component
enum LifecycleStatus: String, Sendable, Codable {
    case active
    case nrnd  // Not Recommended for New Design
    case obsolete
    case eol  // End of Life
    case discontinued

    /// Human-readable description
    var description: String {
        switch self {
        case .active: return "Active"
        case .nrnd: return "Not Recommended for New Design"
        case .obsolete: return "Obsolete"
        case .eol: return "End of Life"
        case .discontinued: return "Discontinued"
        }
    }

    /// Risk level associated with this lifecycle status (0-100)
    var riskLevel: Int {
        switch self {
        case .active: return 10
        case .nrnd: return 50
        case .obsolete: return 70
        case .eol: return 85
        case .discontinued: return 100
        }
    }
}

// MARK: - RoHS Status

/// RoHS compliance status
enum RoHSStatus: String, Sendable, Codable {
    case compliant
    case nonCompliant
    case unknown

    /// Human-readable description
    var description: String {
        switch self {
        case .compliant: return "RoHS Compliant"
        case .nonCompliant: return "Non-Compliant"
        case .unknown: return "Unknown"
        }
    }

    /// SF Symbol icon for UI display
    var icon: String {
        switch self {
        case .compliant: return "checkmark.circle.fill"
        case .nonCompliant: return "xmark.circle.fill"
        case .unknown: return "questionmark.circle.fill"
        }
    }
}

// MARK: - Risk Assessment

/// Risk assessment for a component
struct RiskAssessment: Sendable, Codable {
    /// Risk level category
    let riskLevel: RiskLevel
    /// Numeric risk score (0-100)
    let score: Int
    /// Factors contributing to risk assessment
    let factors: [String]
    /// Confidence in assessment (0.0-1.0)
    let confidence: Double
}

/// Risk level categories
enum RiskLevel: String, Sendable, Codable {
    case low
    case medium
    case high
    case critical

    /// Color for UI display
    var color: String {
        switch self {
        case .low: return "green"
        case .medium: return "yellow"
        case .high: return "orange"
        case .critical: return "red"
        }
    }
}

// MARK: - Lifecycle Inference

/// Infer lifecycle status from product status strings
enum LifecycleInference {
    /// Infer lifecycle status from product status description
    static func infer(from status: String) -> (status: LifecycleStatus, confidence: Double) {
        let normalized = status.lowercased()

        // Check for NRND indicators
        let nrndKeywords = ["not recommended", "nrnd", "phase out", "phase-out", "last time buy"]
        if nrndKeywords.contains(where: { normalized.contains($0) }) {
            return (.nrnd, 0.9)
        }

        // Check for EOL indicators
        let eolKeywords = ["end of life", "eol", "obsolete", "no longer available", "production ended"]
        if eolKeywords.contains(where: { normalized.contains($0) }) {
            return (.eol, 0.95)
        }

        // Check for discontinued
        let discontinuedKeywords = ["discontinued", "terminated", "cancelled"]
        if discontinuedKeywords.contains(where: { normalized.contains($0) }) {
            return (.discontinued, 1.0)
        }

        // Check for active status
        let activeKeywords = ["active", "production", "available", "in production", "full production"]
        if activeKeywords.contains(where: { normalized.contains($0) }) {
            return (.active, 0.95)
        }

        // Default to active with low confidence if status is ambiguous
        return (.active, 0.3)
    }
}