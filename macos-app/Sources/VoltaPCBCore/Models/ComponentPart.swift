//
//  ComponentPart.swift
//  VoltaPCBCore
//
//  Phase 252 — Compliance Provider Foundation
//
//  Lightweight vendor-neutral reference to a component part. Used by
//  ComplianceProvider.getAlternatives() to return candidate replacement
//  parts without the full UnifiedComponent payload (which carries pricing,
//  stock, CAD refs, etc. that compliance alternatives don't need).
//
//  Distinction from UnifiedComponent:
//    - ComponentPart: MPN + manufacturer + optional description. Cheap to
//      construct, no merge-engine footprint. "This MPN is a viable alt."
//    - UnifiedComponent: full provider-merged data. Heavy. Use when the
//      alternative needs to flow into the BOM.
//
//  ponytail: identity is mpn alone, not a UUID. Two providers that both
//  know about "STM32F411CEU6" return the same ComponentPart — duplicates
//  dedupe cleanly in the UI list. UUIDs would force every caller to dedup.
//

import Foundation

/// Lightweight vendor-neutral reference to a component part. Returned by
/// ComplianceProvider.getAlternatives() to suggest candidate replacements.
public struct ComponentPart: Sendable, Hashable, Codable, Identifiable {
    /// Manufacturer Part Number — the canonical identifier.
    public let mpn: String

    /// Component manufacturer name (e.g., "STMicroelectronics").
    public let manufacturer: String

    /// Optional human-readable description.
    public let description: String?

    /// Stable identity for SwiftUI lists — derived from mpn + manufacturer.
    public var id: String { "\(manufacturer)::\(mpn)" }

    public init(mpn: String, manufacturer: String, description: String? = nil) {
        self.mpn = mpn
        self.manufacturer = manufacturer
        self.description = description
    }
}