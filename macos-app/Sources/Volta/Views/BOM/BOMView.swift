//
//  BOMView.swift
//  Volta
//
//  Phase 3 / Task 4 — BOM View with Assembly Highlighting
//
//  Displays a bill of materials with multi-distributor pricing and
//  assembly-ready indicators. Supports CSV export with distributor links.
//
//  Features:
//    - Per-component list with part number, manufacturer, description
//    - Multi-distributor pricing (cheapest highlighted)
//    - Assembly-ready badge (from JLCPCB assembly data)
//    - Single-source risk warning
//    - CSV export with distributor ordering links
//    - Total cost rollup (at quantity)
//

import SwiftUI
import OSLog
import VoltaPCBCore

/// BOM line item view model.
struct BOMLineItem: Identifiable, Hashable {
    let id = UUID()
    let component: UnifiedComponent
    let quantity: Int
    let assemblyAvailability: AssemblyAvailability?

    /// Best (lowest) unit price across all distributors.
    var bestUnitPrice: Double? {
        component.pricing?.map { $0.unitPrice }.min()
    }

    /// Total cost for this line item at quantity.
    var lineTotal: Double? {
        guard let price = bestUnitPrice else { return nil }
        return price * Double(quantity)
    }

    /// Number of distributors with pricing data.
    var distributorCount: Int {
        component.pricing?.count ?? 0
    }

    /// True if only one distributor has this part (supply risk).
    var isSingleSource: Bool {
        distributorCount == 1
    }

    /// Assembly-ready status.
    var assemblyStatus: AssemblyStatus {
        guard let avail = assemblyAvailability else { return .unknown }
        if avail.isBasicAssembly { return .basicAssembly }
        if avail.isAssemblyReady { return .extendedAssembly }
        return .notAssemblyReady
    }
}

/// Assembly readiness classification.
enum AssemblyStatus: String {
    case basicAssembly = "Basic"
    case extendedAssembly = "Extended"
    case notAssemblyReady = "Not Available"
    case unknown = "Unknown"

    var color: Color {
        switch self {
        case .basicAssembly: return .green
        case .extendedAssembly: return .blue
        case .notAssemblyReady: return .red
        case .unknown: return .gray
        }
    }
}

/// Main BOM view.
struct BOMView: View {
    let items: [BOMLineItem]

    @State private var searchText = ""
    @State private var showingExportSheet = false
    @State private var showSingleSourceOnly = false

    var filteredItems: [BOMLineItem] {
        var result = items
        if !searchText.isEmpty {
            result = result.filter { item in
                item.component.partNumber.localizedCaseInsensitiveContains(searchText) ||
                item.component.manufacturer.localizedCaseInsensitiveContains(searchText) ||
                item.component.description.localizedCaseInsensitiveContains(searchText)
            }
        }
        if showSingleSourceOnly {
            result = result.filter { $0.isSingleSource }
        }
        return result
    }

    var totalCost: Double {
        filteredItems.compactMap { $0.lineTotal }.reduce(0, +)
    }

    var assemblyReadyCount: Int {
        items.filter { $0.assemblyStatus == .basicAssembly || $0.assemblyStatus == .extendedAssembly }.count
    }

    var singleSourceCount: Int {
        items.filter { $0.isSingleSource }.count
    }

    var body: some View {
        VStack(spacing: 0) {
            // Summary bar
            summaryBar

            Divider()

            // Table
            ScrollView {
                LazyVStack(spacing: 0) {
                    // Header
                    BOMHeaderRow()

                    Divider()

                    ForEach(filteredItems) { item in
                        BOMItemRow(item: item)
                        Divider()
                            .opacity(0.5)
                    }
                }
            }
        }
        .navigationTitle("Bill of Materials")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button(action: { showingExportSheet = true }) {
                    Label("Export CSV", systemImage: "square.and.arrow.up")
                }
                .disabled(items.isEmpty)
            }
        }
        .searchable(text: $searchText, prompt: "Search components")
        .sheet(isPresented: $showingExportSheet) {
            ExportSheet(items: filteredItems, totalCost: totalCost)
        }
    }

    // MARK: - Summary

    private var summaryBar: some View {
        HStack(spacing: 16) {
            Label("\(items.count) parts", systemImage: "cpu")
                .font(.headline)

            Divider()
                .frame(height: 20)

            Label("\(assemblyReadyCount) assembly-ready", systemImage: "checkmark.seal.fill")
                .foregroundStyle(.green)
                .font(.subheadline)

            Divider()
                .frame(height: 20)

            if singleSourceCount > 0 {
                Label("\(singleSourceCount) single-source", systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(.orange)
                    .font(.subheadline)
            }

            Spacer()

            VStack(alignment: .trailing) {
                Text("Estimated Total")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text(String(format: "$%.2f", totalCost))
                    .font(.headline)
            }
        }
        .padding(.horizontal)
        .padding(.vertical, 8)
    }
}

// MARK: - Header Row

private struct BOMHeaderRow: View {
    var body: some View {
        HStack(spacing: 8) {
            Text("Qty")
                .frame(width: 40, alignment: .center)
            Text("Part Number")
                .frame(maxWidth: .infinity, alignment: .leading)
            Text("Manufacturer")
                .frame(width: 120, alignment: .leading)
            Text("Description")
                .frame(maxWidth: .infinity, alignment: .leading)
            Text("Assembly")
                .frame(width: 90, alignment: .center)
            Text("Sources")
                .frame(width: 60, alignment: .center)
            Text("Best Price")
                .frame(width: 80, alignment: .trailing)
            Text("Line Total")
                .frame(width: 80, alignment: .trailing)
        }
        .font(.caption)
        .fontWeight(.semibold)
        .foregroundStyle(.secondary)
        .padding(.horizontal)
        .padding(.vertical, 6)
        .background(Color(nsColor: .controlBackgroundColor))
    }
}

// MARK: - Item Row

private struct BOMItemRow: View {
    let item: BOMLineItem

    var body: some View {
        HStack(spacing: 8) {
            // Quantity
            Text("\(item.quantity)")
                .frame(width: 40, alignment: .center)
                .font(.system(.body, design: .monospaced))

            // Part Number
            VStack(alignment: .leading, spacing: 2) {
                Text(item.component.partNumber)
                    .font(.system(.body, design: .monospaced))
                    .fontWeight(.medium)
                if let lcsc = item.component.lcscPartNumber {
                    Text("LCSC: \(lcsc)")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            // Manufacturer
            Text(item.component.manufacturer)
                .frame(width: 120, alignment: .leading)
                .font(.caption)
                .lineLimit(1)

            // Description
            Text(item.component.description)
                .frame(maxWidth: .infinity, alignment: .leading)
                .font(.caption)
                .lineLimit(2)

            // Assembly badge
            AssemblyBadge(status: item.assemblyStatus)
                .frame(width: 90, alignment: .center)

            // Source count
            HStack(spacing: 2) {
                Text("\(item.distributorCount)")
                    .font(.caption)
                if item.isSingleSource {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .foregroundStyle(.orange)
                        .font(.caption2)
                }
            }
            .frame(width: 60, alignment: .center)

            // Best price
            if let price = item.bestUnitPrice {
                Text(String(format: "$%.4f", price))
                    .frame(width: 80, alignment: .trailing)
                    .font(.system(.caption, design: .monospaced))
            } else {
                Text("—")
                    .frame(width: 80, alignment: .trailing)
                    .foregroundStyle(.secondary)
            }

            // Line total
            if let total = item.lineTotal {
                Text(String(format: "$%.2f", total))
                    .frame(width: 80, alignment: .trailing)
                    .font(.system(.caption, design: .monospaced))
                    .fontWeight(.medium)
            } else {
                Text("—")
                    .frame(width: 80, alignment: .trailing)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal)
        .padding(.vertical, 6)
        // Highlight single-source items
        .background(item.isSingleSource ? Color.orange.opacity(0.06) : Color.clear)
    }
}

// MARK: - Assembly Badge

private struct AssemblyBadge: View {
    let status: AssemblyStatus

    var body: some View {
        Text(status.rawValue)
            .font(.caption2)
            .fontWeight(.medium)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(status.color.opacity(0.2))
            .foregroundStyle(status.color)
            .clipShape(Capsule())
    }
}

// MARK: - Export Sheet

private struct ExportSheet: View {
    let items: [BOMLineItem]
    let totalCost: Double
    @Environment(\.dismiss) private var dismiss
    @State private var csvText = ""
    @State private var showSavedAlert = false
    @State private var savedURL: URL?

    var body: some View {
        VStack(spacing: 16) {
            Text("Export BOM")
                .font(.headline)

            Text("Export \(items.count) line items as CSV")
                .foregroundStyle(.secondary)

            HStack {
                Button("Copy to Clipboard") {
                    csvText = generateCSV()
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(csvText, forType: .string)
                }
                Button("Save File…") {
                    saveCSV()
                }
                .buttonStyle(.borderedProminent)
            }

            if let url = savedURL {
                Text("Saved to: \(url.path)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Button("Done") { dismiss() }
                .padding(.top)
        }
        .padding()
        .frame(width: 400)
    }

    private func generateCSV() -> String {
        var lines: [String] = []

        // Header
        lines.append("Qty,Part Number,Manufacturer,Description,Assembly,LCSC,Best Unit Price,Line Total,Currency,Distributors")

        // Data rows
        for item in items {
            let c = item.component
            let assembly = item.assemblyStatus.rawValue
            let lcsc = c.lcscPartNumber ?? ""
            let bestPrice = item.bestUnitPrice.map { String(format: "%.4f", $0) } ?? ""
            let lineTotal = item.lineTotal.map { String(format: "%.2f", $0) } ?? ""
            let distributors = (c.pricing ?? []).map { $0.distributor }.joined(separator: "; ")

            let row = [
                "\(item.quantity)",
                escapeCSV(c.partNumber),
                escapeCSV(c.manufacturer),
                escapeCSV(c.description),
                escapeCSV(assembly),
                escapeCSV(lcsc),
                bestPrice,
                lineTotal,
                "USD",
                escapeCSV(distributors),
            ].joined(separator: ",")
            lines.append(row)
        }

        // Summary
        lines.append("")
        lines.append(",,,,,,,Total,\(String(format: "%.2f", totalCost)),USD,")

        return lines.joined(separator: "\n")
    }

    private func escapeCSV(_ field: String) -> String {
        if field.contains(",") || field.contains("\"") || field.contains("\n") {
            return "\"\(field.replacingOccurrences(of: "\"", with: "\"\""))\""
        }
        return field
    }

    private func saveCSV() {
        let csv = generateCSV()
        let panel = NSSavePanel()
        panel.allowedContentTypes = [.commaSeparatedText]
        panel.nameFieldStringValue = "bom.csv"
        panel.canCreateDirectories = true

        if panel.runModal() == .OK, let url = panel.url {
            do {
                try csv.write(to: url, atomically: true, encoding: .utf8)
                savedURL = url
                showSavedAlert = true
            } catch {
                Logger.models.error("BOM CSV export failed: \(error)")
            }
        }
    }
}
