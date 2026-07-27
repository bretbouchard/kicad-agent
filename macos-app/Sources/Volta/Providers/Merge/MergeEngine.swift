//
//  MergeEngine.swift
//  Volta
//
//  Phase 1 / Task 4 — Merge Engine
//
//  Combines results from ComponentDataProvider + CADModelProvider registries
//  into unified component results. MPN deduplication + priority-based field
//  merge. Error isolation — one provider failing doesn't affect others.
//

import Foundation
import OSLog
import VoltaPCBCore

/// Merges results from multiple provider registries into unified components.
///
/// Priority rules:
/// - Pricing: Digi-Key first, others as fallback
/// - Specs: Digi-Key first (most comprehensive parametric data)
/// - Datasheets: Digi-Key (direct PDF links)
/// - CAD models: easyeda2kicad first, others as fallback
/// - Sources: all providers preserved in `sources` array
final class MergeEngine: @unchecked Sendable {
    private let componentRegistry: ComponentProviderRegistry
    private let cadRegistry: CADModelProviderRegistry
    private let queryTimeout: TimeInterval

    init(
        componentRegistry: ComponentProviderRegistry,
        cadRegistry: CADModelProviderRegistry,
        queryTimeout: TimeInterval = 10
    ) {
        self.componentRegistry = componentRegistry
        self.cadRegistry = cadRegistry
        self.queryTimeout = queryTimeout
    }

    /// Search all providers in parallel, merge results by MPN.
    /// Returns unified components with data from multiple sources merged.
    func search(keyword: String) async -> [UnifiedComponent] {
        // Fan out both registries concurrently. Each registry handles its own
        // per-provider error isolation internally.
        async let componentResults = componentRegistry.searchAll(keyword: keyword)
        async let cadResults = cadRegistry.searchAll(keyword: keyword)

        let components = await componentResults
        let cadComponents = await cadResults

        // Merge by normalized MPN.
        var byMPN: [String: UnifiedComponent] = [:]

        // Component data providers first (pricing, stock, specs).
        for component in components {
            let key = Self.normalizeMPN(component.partNumber)
            if var existing = byMPN[key] {
                existing.merge(from: component)
                byMPN[key] = existing
            } else {
                byMPN[key] = component
            }
        }

        // CAD model providers — merge CAD models into existing components
        // or create new entries for parts only found via CAD search.
        for cadComponent in cadComponents {
            let key = Self.normalizeMPN(cadComponent.partNumber)
            if var existing = byMPN[key] {
                existing.mergeCAD(from: cadComponent)
                byMPN[key] = existing
            } else {
                byMPN[key] = cadComponent
            }
        }

        return Array(byMPN.values).sorted { $0.partNumber < $1.partNumber }
    }

    // MARK: - Helpers

    /// Normalize MPN for dedup: uppercase, remove spaces and dashes.
    static func normalizeMPN(_ mpn: String) -> String {
        mpn.uppercased()
            .replacingOccurrences(of: " ", with: "")
            .replacingOccurrences(of: "-", with: "")
    }
}

// MARK: - UnifiedComponent Merge Extension

extension UnifiedComponent {
    /// Merge data from another component (same MPN, different provider).
    /// Priority: existing values win unless the new provider has data the
    /// existing one lacks.
    mutating func merge(from other: UnifiedComponent) {
        // Merge sources
        sources.append(contentsOf: other.sources)

        // Merge pricing — prefer existing (Digi-Key typically loaded first)
        if pricing == nil { pricing = other.pricing }
        else if let otherPricing = other.pricing {
            var merged = pricing!
            for op in otherPricing {
                if !merged.contains(where: { $0.distributor == op.distributor }) {
                    merged.append(op)
                }
            }
            pricing = merged
        }

        // Merge stock
        if stock == nil { stock = other.stock }
        else if let otherStock = other.stock {
            var merged = stock!
            for os in otherStock {
                if !merged.contains(where: { $0.distributor == os.distributor }) {
                    merged.append(os)
                }
            }
            stock = merged
        }

        // Merge specs — prefer existing (Digi-Key has most comprehensive)
        if specs == nil { specs = other.specs }
        else if let otherSpecs = other.specs {
            var merged = specs!
            for (k, v) in otherSpecs where merged[k] == nil {
                merged[k] = v
            }
            specs = merged
        }

        // Datasheet — prefer existing
        if datasheetURL == nil { datasheetURL = other.datasheetURL }

        // Category — prefer existing
        if category == nil { category = other.category }
    }

    /// Merge only CAD model data from another component.
    mutating func mergeCAD(from other: UnifiedComponent) {
        sources.append(contentsOf: other.sources)
        if cadModels == nil { cadModels = other.cadModels }
        else if let otherCAD = other.cadModels {
            var merged = cadModels!
            for cad in otherCAD {
                if !merged.contains(where: { $0.filePath == cad.filePath }) {
                    merged.append(cad)
                }
            }
            cadModels = merged
        }
    }
}
