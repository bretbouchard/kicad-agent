//
//  MergeEngine.swift
//  Volta
//
//  Phase 1 / Task 4 — Merge Engine
//  Phase 2 / Task 4 — Merge Engine v2 (priority + confidence scoring)
//
//  Combines results from ComponentDataProvider + CADModelProvider registries
//  into unified component results. MPN deduplication + priority-based field
//  merge. Error isolation — one provider failing doesn't affect others.
//
//  v2: Provider priority ordering + confidence-based field selection.
//  Instead of "first loaded wins", the provider with higher priority
//  (Digi-Key > Octopart > jlcparts) wins field conflicts.
//

import Foundation
import OSLog
import VoltaPCBCore

/// Merges results from multiple provider registries into unified components.
///
/// Priority rules (v2):
/// - Field conflicts resolved by provider priority rank, not load order
/// - Pricing/stock: highest-priority provider with data wins
/// - Specs: merged from all providers, conflicts resolved by priority
/// - Datasheets: highest-priority provider's link wins
/// - CAD models: merged from all CAD providers (no conflict — additive)
/// - Sources: all providers preserved in `sources` array
final class MergeEngine: @unchecked Sendable {
    private let componentRegistry: ComponentProviderRegistry
    private let cadRegistry: CADModelProviderRegistry
    private let queryTimeout: TimeInterval
    private let priority: ProviderPriority

    init(
        componentRegistry: ComponentProviderRegistry,
        cadRegistry: CADModelProviderRegistry,
        priority: ProviderPriority = .default,
        queryTimeout: TimeInterval = 10
    ) {
        self.componentRegistry = componentRegistry
        self.cadRegistry = cadRegistry
        self.priority = priority
        self.queryTimeout = queryTimeout
    }

    /// Search all providers in parallel, merge results by MPN.
    /// Returns unified components sorted by provider priority.
    func search(keyword: String) async -> [UnifiedComponent] {
        async let componentResults = componentRegistry.searchAll(keyword: keyword)
        async let cadResults = cadRegistry.searchAll(keyword: keyword)

        let components = await componentResults
        let cadComponents = await cadResults

        // Merge by normalized MPN. Sort providers by priority before merging
        // so higher-priority data is applied first.
        var byMPN: [String: UnifiedComponent] = [:]

        let sortedComponents = components.sorted { a, b in
            let aRank = bestRank(for: a.sources)
            let bRank = bestRank(for: b.sources)
            return aRank < bRank
        }

        for component in sortedComponents {
            let key = Self.normalizeMPN(component.partNumber)
            if var existing = byMPN[key] {
                existing.merge(from: component, priority: priority)
                byMPN[key] = existing
            } else {
                byMPN[key] = component
            }
        }

        for cadComponent in cadComponents {
            let key = Self.normalizeMPN(cadComponent.partNumber)
            if var existing = byMPN[key] {
                existing.mergeCAD(from: cadComponent)
                byMPN[key] = existing
            } else {
                byMPN[key] = cadComponent
            }
        }

        // Sort: provider priority first, then alphabetical by MPN.
        return Array(byMPN.values).sorted { a, b in
            let aRank = bestRank(for: a.sources)
            let bRank = bestRank(for: b.sources)
            if aRank != bRank { return aRank < bRank }
            return a.partNumber < b.partNumber
        }
    }

    // MARK: - Helpers

    /// Best (lowest) priority rank among a component's sources.
    private func bestRank(for sources: [ComponentSource]) -> Int {
        sources.map { priority.rank(for: $0.provider) }.min() ?? Int.max
    }

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
    /// Priority v2: uses ProviderPriority to resolve field conflicts.
    /// Higher-priority provider's data wins; lower-priority fills gaps.
    mutating func merge(from other: UnifiedComponent, priority: ProviderPriority) {
        // Always merge sources
        sources.append(contentsOf: other.sources)

        let otherRank = other.sources.map { priority.rank(for: $0.provider) }.min() ?? Int.max
        let existingRank = sources.filter { !$0.provider.isEmpty }
            .map { priority.rank(for: $0.provider) }.min() ?? Int.max
        let otherHasPriority = otherRank < existingRank

        // Pricing — merge per-distributor, prefer higher-priority provider
        if pricing == nil {
            pricing = other.pricing
        } else if let otherPricing = other.pricing {
            if otherHasPriority {
                // Other provider is higher priority — its pricing takes precedence
                var merged = otherPricing
                for ep in pricing! {
                    if !merged.contains(where: { $0.distributor == ep.distributor }) {
                        merged.append(ep)
                    }
                }
                pricing = merged
            } else {
                var merged = pricing!
                for op in otherPricing {
                    if !merged.contains(where: { $0.distributor == op.distributor }) {
                        merged.append(op)
                    }
                }
                pricing = merged
            }
        }

        // Stock — same logic as pricing
        if stock == nil {
            stock = other.stock
        } else if let otherStock = other.stock {
            if otherHasPriority {
                var merged = otherStock
                for es in stock! {
                    if !merged.contains(where: { $0.distributor == es.distributor }) {
                        merged.append(es)
                    }
                }
                stock = merged
            } else {
                var merged = stock!
                for os in otherStock {
                    if !merged.contains(where: { $0.distributor == os.distributor }) {
                        merged.append(os)
                    }
                }
                stock = merged
            }
        }

        // Specs — merge keys, prefer higher-priority provider for conflicting keys
        if specs == nil {
            specs = other.specs
        } else if let otherSpecs = other.specs {
            if otherHasPriority {
                // Other wins conflicts
                var merged = otherSpecs
                for (k, v) in specs! where merged[k] == nil {
                    merged[k] = v
                }
                specs = merged
            } else {
                // Existing wins conflicts
                var merged = specs!
                for (k, v) in otherSpecs where merged[k] == nil {
                    merged[k] = v
                }
                specs = merged
            }
        }

        // Datasheet — prefer higher-priority
        if otherHasPriority || datasheetURL == nil {
            datasheetURL = other.datasheetURL ?? datasheetURL
        }

        // Category — prefer higher-priority
        if otherHasPriority || category == nil {
            category = other.category ?? category
        }

        // LCSC part number — fill if missing
        if lcscPartNumber == nil {
            lcscPartNumber = other.lcscPartNumber
        }
    }

    /// Merge only CAD model data from another component.
    /// CAD models are additive — no priority conflict resolution needed.
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
