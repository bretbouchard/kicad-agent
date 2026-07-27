//
//  ComponentDetailView.swift
//  Volta
//
//  Phase 1 / Task 6 — SwiftUI Search Interface
//

import SwiftUI
import VoltaPCBCore

/// Detailed view for a single component — all data from merged providers.
struct ComponentDetailView: View {
    let component: UnifiedComponent

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                // Header
                headerSection

                // Pricing
                if let pricing = component.pricing, !pricing.isEmpty {
                    pricingSection(pricing)
                }

                // Stock
                if let stock = component.stock, !stock.isEmpty {
                    stockSection(stock)
                }

                // Specs
                if let specs = component.specs, !specs.isEmpty {
                    specsSection(specs)
                }

                // CAD models
                if let cad = component.cadModels, !cad.isEmpty {
                    cadSection(cad)
                }

                // Sources
                sourcesSection
            }
            .padding()
        }
        .navigationTitle(component.partNumber)
    }

    private var headerSection: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(component.partNumber)
                .font(.largeTitle)
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
        VStack(alignment: .leading, spacing: 6) {
            Text("Pricing")
                .font(.headline)
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
        VStack(alignment: .leading, spacing: 6) {
            Text("Stock")
                .font(.headline)
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
        VStack(alignment: .leading, spacing: 6) {
            Text("Specifications")
                .font(.headline)
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
        VStack(alignment: .leading, spacing: 6) {
            Text("CAD Models")
                .font(.headline)
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
