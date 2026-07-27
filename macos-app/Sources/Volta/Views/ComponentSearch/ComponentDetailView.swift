//
//  ComponentDetailView.swift
//  Volta
//
//  Phase 1 / Task 6 — SwiftUI Search Interface
//  Phase 2 / Task 6 — Stale Data UI (per-field freshness)
//

import SwiftUI
import VoltaPCBCore

/// Detailed view for a single component — all data from merged providers.
struct ComponentDetailView: View {
    let component: UnifiedComponent

    /// Closure called when user taps refresh. Parent view handles re-query.
    var onRefresh: (() -> Void)?

    /// Most recent source update timestamp (for overall freshness).
    private var lastUpdated: Date? {
        component.sources.map(\.lastUpdated).max()
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                headerSection

                if let pricing = component.pricing, !pricing.isEmpty {
                    pricingSection(pricing)
                }

                if let stock = component.stock, !stock.isEmpty {
                    stockSection(stock)
                }

                if let specs = component.specs, !specs.isEmpty {
                    specsSection(specs)
                }

                if let cad = component.cadModels, !cad.isEmpty {
                    cadSection(cad)
                }

                sourcesSection
            }
            .padding()
        }
        .navigationTitle(component.partNumber)
        .toolbar {
            if let onRefresh {
                ToolbarItem(placement: .primaryAction) {
                    Button(action: onRefresh) {
                        Image(systemName: "arrow.clockwise")
                    }
                    .help("Refresh component data")
                }
            }
        }
    }

    private var headerSection: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(component.partNumber)
                    .font(.largeTitle)
                Spacer()
                if let onRefresh {
                    Button(action: onRefresh) {
                        Label("Refresh", systemImage: "arrow.clockwise")
                            .font(.caption)
                    }
                    .buttonStyle(.bordered)
                }
            }
            Text(component.manufacturer)
                .font(.title3)
                .foregroundStyle(.secondary)
            Text(component.description)
                .font(.body)
            if let category = component.category {
                Text(category)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            if let url = component.datasheetURL {
                Link("Datasheet PDF", destination: url)
                    .font(.caption)
            }
        }
    }

    private func pricingSection(_ pricing: [PricingData]) -> some View {
        freshnessSection(title: "Pricing", ttl: FreshnessCalculator.pricingTTL) {
            ForEach(pricing, id: \.self) { p in
                HStack {
                    Text(p.distributor)
                    Spacer()
                    Text(String(format: "$%.2f / %d min", p.unitPrice, p.minOrderQty))
                }
                .font(.callout)
                if let tiers = p.tieredPricing, !tiers.isEmpty {
                    Text("Tiers: " + tiers.map { "\($0.minQty)+: $\(String(format: "%.2f", $0.unitPrice))" }
                        .joined(separator: ", "))
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
        }
    }

    private func stockSection(_ stock: [StockData]) -> some View {
        freshnessSection(title: "Stock", ttl: FreshnessCalculator.stockTTL) {
            ForEach(stock, id: \.self) { s in
                HStack {
                    Text(s.distributor)
                    Spacer()
                    Text("\(s.quantityAvailable) available")
                        .foregroundStyle(s.quantityAvailable > 0 ? .green : .red)
                    if let lead = s.leadTime {
                        Text("(\(lead))")
                            .foregroundStyle(.secondary)
                    }
                }
                .font(.callout)
            }
        }
    }

    private func specsSection(_ specs: [String: String]) -> some View {
        freshnessSection(title: "Specifications", ttl: FreshnessCalculator.specsTTL) {
            ForEach(specs.sorted(by: { $0.key < $1.key }), id: \.key) { key, value in
                HStack {
                    Text(key)
                        .foregroundStyle(.secondary)
                    Spacer()
                    Text(value)
                }
                .font(.callout)
            }
        }
    }

    private func cadSection(_ cad: [CADModelRef]) -> some View {
        freshnessSection(title: "CAD Models", ttl: .infinity, isPermanent: true) {
            ForEach(cad, id: \.filePath) { model in
                HStack {
                    Image(systemName: model.format == .step ? "cube" : "doc")
                    Text(model.format.rawValue)
                    Spacer()
                    Text(model.source)
                        .foregroundStyle(.secondary)
                }
                .font(.callout)
            }
        }
    }

    /// Generic section wrapper that adds freshness badge and stale highlighting.
    @ViewBuilder
    private func freshnessSection<Content: View>(
        title: String,
        ttl: TimeInterval,
        isPermanent: Bool = false,
        @ViewBuilder content: () -> Content
    ) -> some View {
        let freshness = computeFreshness(ttl: ttl, isPermanent: isPermanent)
        let ageLabel = computeAgeLabel()
        let staleBg = freshness == .stale || freshness == .veryStale
            ? Color.yellow.opacity(0.08)
            : Color.clear

        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(title)
                    .font(.headline)
                Spacer()
                FreshnessBadge(freshness: freshness, ageLabel: ageLabel)
            }
            content()
        }
        .padding(8)
        .background(
            RoundedRectangle(cornerRadius: 8)
                .fill(staleBg)
        )
    }

    private func computeFreshness(ttl: TimeInterval, isPermanent: Bool) -> DataFreshness {
        guard let lastUpdated else { return .unknown }
        let age = Date().timeIntervalSince(lastUpdated)
        return FreshnessCalculator.freshness(age: age, ttl: ttl, isPermanent: isPermanent)
    }

    private func computeAgeLabel() -> String? {
        guard let lastUpdated else { return nil }
        let age = Date().timeIntervalSince(lastUpdated)
        return FreshnessCalculator.formatAge(age)
    }

    private var sourcesSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Sources")
                .font(.headline)
            ForEach(component.sources, id: \.id) { source in
                HStack {
                    ProviderBadge(providerName: source.provider)
                    Spacer()
                    Text(String(format: "%.0f%%", source.confidence * 100))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }
    }
}
