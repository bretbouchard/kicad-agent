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
    @Environment(GSAPlatformHost.self) private var gsaPlatformHost

    let component: UnifiedComponent

    /// Closure called when user taps refresh. Parent view handles re-query.
    var onRefresh: (() -> Void)?

    @State private var assemblyAvailability: AssemblyAvailability?
    @State private var governedProviderCheck: GSAPlatformHost.ProviderCheckResult?
    @State private var governedComplianceCheck: GSAPlatformHost.ComplianceCheckResult?
    @State private var isCheckingAssembly = false
    @State private var isCheckingCompliance = false
    @State private var assemblyCheckError: String?
    @State private var complianceCheckError: String?

    private let assemblyProvider = JlcpcbApiProvider()
    private let complianceProvider = LocalComplianceProvider()

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

                if component.lcscPartNumber != nil {
                    assemblySection
                }

                complianceSection

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

    @ViewBuilder
    private var assemblySection: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("Assembly Data")
                    .font(.headline)
                Spacer()
                if isCheckingAssembly {
                    ProgressView()
                        .controlSize(.small)
                } else {
                    Button("Check Assembly") {
                        Task { await performGovernedAssemblyCheck() }
                    }
                    .buttonStyle(.borderedProminent)
                }
            }

            if let lcscPartNumber = component.lcscPartNumber {
                Text("LCSC: \(lcscPartNumber)")
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
            }

            if let assemblyAvailability {
                HStack {
                    AssemblyBadge(status: assemblyStatus(for: assemblyAvailability))
                    if let deliveryTime = assemblyAvailability.deliveryTime {
                        Text(deliveryTime)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    if let assemblyFee = assemblyAvailability.assemblyFee {
                        Text(String(format: "$%.2f fee", assemblyFee))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                Text(assemblyAvailability.inStock ? "Provider reports assembly stock available." : "Provider reports assembly stock unavailable.")
                    .font(.caption)
                    .foregroundStyle(assemblyAvailability.inStock ? Color.secondary : Color.orange)
            }

            if let governedProviderCheck {
                VStack(alignment: .leading, spacing: 4) {
                    Text(governedProviderCheck.claim)
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                    Text("\(governedProviderCheck.liveEvidenceCount) live evidence · \(governedProviderCheck.historianChainCount) trace")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text(governedProviderCheck.providerReference)
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                    Text(governedProviderCheck.pcbReference)
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                }
            }

            if let assemblyCheckError {
                Label(assemblyCheckError, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption)
                    .foregroundStyle(.orange)
            }
        }
        .padding(8)
        .background(
            RoundedRectangle(cornerRadius: 8)
                .fill(Color.blue.opacity(0.05))
        )
    }

    @ViewBuilder
    private var complianceSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("Compliance")
                    .font(.headline)
                Spacer()
                if isCheckingCompliance {
                    ProgressView()
                        .controlSize(.small)
                } else {
                    Button("Check Compliance") {
                        Task { await performGovernedComplianceCheck() }
                    }
                    .buttonStyle(.bordered)
                }
            }

            if let governedComplianceCheck {
                HStack {
                    Text(governedComplianceCheck.lifecycleStatus.uppercased())
                        .font(.caption2.weight(.medium))
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(Color.orange.opacity(0.15))
                        .clipShape(Capsule())
                    Text(governedComplianceCheck.rohsStatus.uppercased())
                        .font(.caption2.weight(.medium))
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(Color.green.opacity(0.15))
                        .clipShape(Capsule())
                    Text("Risk \(governedComplianceCheck.riskScore)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Text(governedComplianceCheck.claim)
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
                Text("\(governedComplianceCheck.liveEvidenceCount) live evidence · \(governedComplianceCheck.historianChainCount) trace")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text(governedComplianceCheck.componentReference)
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
            }

            if let complianceCheckError {
                Label(complianceCheckError, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption)
                    .foregroundStyle(.orange)
            }
        }
        .padding(8)
        .background(
            RoundedRectangle(cornerRadius: 8)
                .fill(Color.orange.opacity(0.05))
        )
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

    private func assemblyStatus(for availability: AssemblyAvailability) -> AssemblyStatus {
        if availability.isBasicAssembly { return .basicAssembly }
        if availability.isAssemblyReady { return .extendedAssembly }
        return .notAssemblyReady
    }

    @MainActor
    private func performGovernedAssemblyCheck() async {
        guard let lcscPartNumber = component.lcscPartNumber, !lcscPartNumber.isEmpty else {
            assemblyCheckError = "No LCSC part number available for assembly lookup."
            return
        }

        isCheckingAssembly = true
        assemblyCheckError = nil
        defer { isCheckingAssembly = false }

        do {
            guard let availability = try await assemblyProvider.checkAssemblyAvailability(lcscPartNumber: lcscPartNumber) else {
                assemblyAvailability = nil
                governedProviderCheck = nil
                assemblyCheckError = "Assembly provider returned no data for \(lcscPartNumber)."
                return
            }

            assemblyAvailability = availability
            let context = GSAPlatformHost.GovernedProjectContext(
                projectID: UUID(uuidString: "00000000-0000-0000-0000-000000000002")!,
                projectName: "Component Search",
                conversationID: nil,
                revision: 1
            )
            governedProviderCheck = try await gsaPlatformHost.recordProviderAssemblyCheck(
                providerName: assemblyProvider.name,
                subjectIdentifier: lcscPartNumber,
                availability: availability,
                context: context
            )
        } catch {
            assemblyCheckError = error.localizedDescription
        }
    }

    @MainActor
    private func performGovernedComplianceCheck() async {
        isCheckingCompliance = true
        complianceCheckError = nil
        defer { isCheckingCompliance = false }

        do {
            let lifecycleStatus = try await complianceProvider.getLifecycleStatus(mpn: component.partNumber)
            let rohsStatus = try await complianceProvider.checkRoHSCompliance(mpn: component.partNumber)
            let riskAssessment = try await complianceProvider.assessRisk(mpn: component.partNumber)
            let context = GSAPlatformHost.GovernedProjectContext(
                projectID: UUID(uuidString: "00000000-0000-0000-0000-000000000002")!,
                projectName: "Component Search",
                conversationID: nil,
                revision: 1
            )
            governedComplianceCheck = try await gsaPlatformHost.recordComplianceCheck(
                providerName: "local-compliance",
                subjectIdentifier: component.partNumber,
                lifecycleStatus: lifecycleStatus,
                rohsStatus: rohsStatus,
                riskAssessment: riskAssessment,
                context: context
            )
        } catch {
            complianceCheckError = error.localizedDescription
        }
    }
}
