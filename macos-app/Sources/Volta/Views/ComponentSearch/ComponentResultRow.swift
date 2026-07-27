//
//  ComponentResultRow.swift
//  Volta
//
//  Phase 1 / Task 6 — SwiftUI Search Interface
//

import SwiftUI
import VoltaPCBCore

/// Single result row in the component search list.
struct ComponentResultRow: View {
    let component: UnifiedComponent

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(component.partNumber)
                    .font(.headline)
                Spacer()
                if let pricing = component.pricing?.first {
                    Text(String(format: "$%.2f", pricing.unitPrice))
                        .font(.headline)
                        .foregroundStyle(.green)
                }
            }

            Text(component.description)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(2)

            HStack(spacing: 6) {
                Text(component.manufacturer)
                    .font(.caption2)
                    .foregroundStyle(.secondary)

                if let stock = component.stock?.first {
                    Text("\(stock.quantityAvailable) in stock")
                        .font(.caption2)
                        .foregroundStyle(stock.quantityAvailable > 0 ? .green : .red)
                }

                Spacer()

                // Provider badges + freshness dot
                HStack(spacing: 3) {
                    ForEach(component.sources, id: \.id) { source in
                        ProviderBadge(providerName: source.provider)
                    }
                    if let lastUpdated = component.sources.map(\.lastUpdated).max() {
                        let age = Date().timeIntervalSince(lastUpdated)
                        let freshness = FreshnessCalculator.freshness(
                            age: age,
                            ttl: FreshnessCalculator.pricingTTL
                        )
                        Circle()
                            .fill(freshness.color)
                            .frame(width: 6, height: 6)
                            .help(FreshnessCalculator.formatAge(age))
                    }
                }
            }
        }
        .padding(.vertical, 4)
    }
}
