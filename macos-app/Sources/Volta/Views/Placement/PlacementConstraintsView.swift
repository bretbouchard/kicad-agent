//
//  PlacementConstraintsView.swift
//  Volta
//
//  volta-24 follow-on: compact editor for contextual placement rules.
//
//  Rules carry design intent ("connector on the bottom edge", "keep the
//  regulator away from the analog section") with provenance and
//  rationale; they are enforced by the placement engine and gated after
//  placement (see Models/Placement/PlacementConstraints.swift).
//

import SwiftUI

struct PlacementConstraintsView: View {
    @Binding var constraints: [PlacementConstraint]
    @State private var selection: PlacementConstraint.ID?
    @State private var draft = PlacementDraft()

    var body: some View {
        List(selection: $selection) {
            Section("Placement rules (\(constraints.count))") {
                if constraints.isEmpty {
                    Text("No placement rules — components place by wirelength alone.")
                        .foregroundStyle(.secondary)
                        .font(.callout)
                }
                ForEach(constraints) { rule in
                    PlacementRuleRow(rule: rule)
                        .tag(rule.id)
                        .contextMenu {
                            Button("Delete", role: .destructive) {
                                constraints.removeAll { $0.id == rule.id }
                            }
                        }
                }
            }
        }
        .frame(minWidth: 320, minHeight: 240)
        .safeAreaInset(edge: .bottom) {
            PlacementRuleComposer(draft: $draft) { newRule in
                if let validated = try? newRule.validated() {
                    constraints.append(validated)
                    draft = PlacementDraft()
                }
            }
            .padding()
            .background(.bar)
        }
    }
}

// MARK: - Row

private struct PlacementRuleRow: View {
    let rule: PlacementConstraint

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack {
                Image(systemName: icon)
                    .foregroundStyle(.tint)
                Text(summary)
                    .font(.body.weight(.medium))
                Spacer()
                Text(rule.source.rawValue)
                    .font(.caption)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(.quaternary, in: Capsule())
            }
            if !rule.rationale.isEmpty {
                Text(rule.rationale)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
        }
        .padding(.vertical, 2)
    }

    private var icon: String {
        switch rule.ruleType {
        case .avoid: "exclamationmark.triangle"
        case .approach: "arrow.triangle.branch"
        case .edgeAffinity: "rectangle.inset.bottom.leading"
        case .region: "rectangle.dashed"
        case .orientation: "rotate.right"
        }
    }

    private var summary: String {
        let refs = rule.refs.joined(separator: ", ")
        switch rule.ruleType {
        case .avoid:
            let mm = rule.mm.map { String(format: "%.0f", $0) } ?? "?"
            return "\(refs) ≥ \(mm)mm from \((rule.refsB ?? []).joined(separator: ", "))"
        case .approach:
            let mm = rule.mm.map { String(format: "%.0f", $0) } ?? "?"
            return "\(refs) ≤ \(mm)mm from \((rule.refsB ?? []).joined(separator: ", "))"
        case .edgeAffinity:
            let mm = rule.mm.map { String(format: "%.0f", $0) } ?? "5"
            return "\(refs) within \(mm)mm of \(rule.edge?.rawValue ?? "?") edge"
        case .region:
            return "\(refs) in \(rule.regionName ?? "region")"
        case .orientation:
            return "\(refs) rotated \(rule.rotation.map { Int($0) } ?? 0)°"
        }
    }
}

// MARK: - Composer

private struct PlacementDraft {
    var ruleType: PlacementRuleType = .avoid
    var refs = ""
    var refsB = ""
    var mm = 10.0
    var edge: PlacementEdge = .bottom
    var regionMinX = 0.0
    var regionMinY = 0.0
    var regionMaxX = 50.0
    var regionMaxY = 40.0
    var rotation = 0.0
    var rationale = ""

    func toRule() -> PlacementConstraint {
        let refsList = refs.split(whereSeparator: { $0.isWhitespace })
            .map(String.init)
        let refsBList = refsB.split(whereSeparator: { $0.isWhitespace })
            .map(String.init)
        return PlacementConstraint(
            ruleType: ruleType,
            refs: refsList,
            refsB: refsBList.isEmpty ? nil : refsBList,
            mm: ruleType == .orientation ? nil : mm,
            edge: ruleType == .edgeAffinity ? edge : nil,
            region: ruleType == .region
                ? [regionMinX, regionMinY, regionMaxX, regionMaxY] : nil,
            rotation: ruleType == .orientation ? rotation : nil,
            rationale: rationale
        )
    }
}

private struct PlacementRuleComposer: View {
    @Binding var draft: PlacementDraft
    let onAdd: (PlacementConstraint) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Picker("Rule", selection: $draft.ruleType) {
                ForEach(PlacementRuleType.allCases, id: \.self) { type in
                    Text(label(for: type)).tag(type)
                }
            }
            .pickerStyle(.segmented)

            HStack {
                TextField("Refs (space separated)", text: $draft.refs)
                    .textFieldStyle(.roundedBorder)
                if draft.ruleType == .avoid || draft.ruleType == .approach {
                    TextField("From refs", text: $draft.refsB)
                        .textFieldStyle(.roundedBorder)
                }
            }

            switch draft.ruleType {
            case .avoid, .approach, .edgeAffinity:
                HStack {
                    Text("mm:")
                    TextField("mm", value: $draft.mm, format: .number)
                        .textFieldStyle(.roundedBorder)
                        .frame(width: 70)
                    if draft.ruleType == .edgeAffinity {
                        Picker("Edge", selection: $draft.edge) {
                            ForEach(PlacementEdge.allCases, id: \.self) { edge in
                                Text(edge.rawValue.capitalized).tag(edge)
                            }
                        }
                        .pickerStyle(.menu)
                    }
                }
            case .region:
                HStack {
                    decimalField("x1", $draft.regionMinX)
                    decimalField("y1", $draft.regionMinY)
                    decimalField("x2", $draft.regionMaxX)
                    decimalField("y2", $draft.regionMaxY)
                }
            case .orientation:
                HStack {
                    Text("°")
                    TextField("degrees", value: $draft.rotation, format: .number)
                        .textFieldStyle(.roundedBorder)
                        .frame(width: 70)
                }
            }

            TextField("Why? (rationale)", text: $draft.rationale)
                .textFieldStyle(.roundedBorder)

            HStack {
                Spacer()
                Button("Add Rule") { onAdd(draft.toRule()) }
                    .buttonStyle(.borderedProminent)
                    .disabled(draft.refs.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
    }

    private func label(for type: PlacementRuleType) -> String {
        switch type {
        case .avoid: "Avoid"
        case .approach: "Near"
        case .edgeAffinity: "Edge"
        case .region: "Region"
        case .orientation: "Orient"
        }
    }

    private func decimalField(_ label: String, _ value: Binding<Double>) -> some View {
        HStack(spacing: 2) {
            Text(label).foregroundStyle(.secondary)
            TextField(label, value: value, format: .number)
                .textFieldStyle(.roundedBorder)
                .frame(width: 56)
        }
    }
}
