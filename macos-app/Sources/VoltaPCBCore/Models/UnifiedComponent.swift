//
//  UnifiedComponent.swift
//  VoltaPCBCore
//
//  Phase 1 / Task 0 — VoltaPCBCore Foundation
//
//  Vendor-neutral component model — the unified output of all provider
//  queries. This is the core data structure that flows from providers →
//  merge engine → UI → BOM. Every provider's native response shape is
//  translated into UnifiedComponent at the provider boundary; nothing
//  vendor-specific escapes the provider module.
//
//  Why struct not class: components are values. Two BOM line items with
//  the same MPN should compare equal and merge cleanly. Sendable + struct
//  lets us pass components across actor boundaries without ceremony.
//
//  ponytail: optional collections (pricing?, stock?) not empty arrays.
//  Distinction matters: nil = "provider did not report", [] = "provider
//  reported none available". The BOM risk analyzer treats these oppositely.
//

import Foundation

/// Vendor-neutral component model — the unified output of all provider queries.
/// This is the core data structure that flows from providers → merge engine → UI.
public struct UnifiedComponent: Sendable, Identifiable, Hashable, Codable {
    /// Stable unique ID for Identifiable conformance (SwiftUI lists, etc.).
    /// Not the MPN — the same MPN from two providers is one component with
    /// two ComponentSource entries, not two components.
    public let id: UUID

    /// Manufacturer Part Number (e.g., "STM32F411RET6"). The canonical
    /// merge key across providers.
    public let partNumber: String

    /// Manufacturer display name (e.g., "STMicroelectronics").
    public let manufacturer: String

    /// One-line product description. May be provider-sourced; merge engine
    /// picks the longest non-empty description across providers.
    public let description: String

    /// Which providers have this part. At least one entry after a successful
    /// search; multiple entries after a merge. Each entry carries the
    /// provider's part ID and a confidence score for merge priority.
    public var sources: [ComponentSource]

    /// Per-distributor pricing, one entry per distributor. nil if no provider
    /// reported pricing; empty if provider confirmed no pricing available.
    public var pricing: [PricingData]?

    /// Per-distributor stock, one entry per distributor. nil if no provider
    /// reported stock; empty if provider confirmed no stock info available.
    public var stock: [StockData]?

    /// Parametric specifications (e.g., "Voltage" → "3.3V", "Tolerance" → "1%").
    /// Keys are provider-normalized to camelCase English; values are strings
    /// with unit appended where applicable. nil if no specs reported.
    public var specs: [String: String]?

    /// Cached CAD models — footprints, symbols, 3D models. nil if no CAD
    /// provider has run yet; empty if CAD provider confirmed no models.
    public var cadModels: [CADModelRef]?

    /// Datasheet PDF URL. nil if not available.
    public var datasheetURL: URL?

    /// LCSC part number (e.g., "C2040") — used to map JLCPCB assembly
    /// compatibility. nil for non-LCSC-sourced parts.
    public var lcscPartNumber: String?

    /// Category path (e.g., "Embedded Processors & Controllers"). Provider-
    /// normalized; used for grouping in the picker UI.
    public var category: String?

    public init(
        id: UUID = UUID(),
        partNumber: String,
        manufacturer: String,
        description: String,
        sources: [ComponentSource] = [],
        pricing: [PricingData]? = nil,
        stock: [StockData]? = nil,
        specs: [String: String]? = nil,
        cadModels: [CADModelRef]? = nil,
        datasheetURL: URL? = nil,
        lcscPartNumber: String? = nil,
        category: String? = nil
    ) {
        self.id = id
        self.partNumber = partNumber
        self.manufacturer = manufacturer
        self.description = description
        self.sources = sources
        self.pricing = pricing
        self.stock = stock
        self.specs = specs
        self.cadModels = cadModels
        self.datasheetURL = datasheetURL
        self.lcscPartNumber = lcscPartNumber
        self.category = category
    }
}
