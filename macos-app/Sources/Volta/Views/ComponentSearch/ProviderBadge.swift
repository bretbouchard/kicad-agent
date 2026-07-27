//
//  ProviderBadge.swift
//  Volta
//
//  Phase 1 / Task 6 — SwiftUI Search Interface
//
//  Small badge showing which provider contributed data for a component.
//

import SwiftUI

/// Compact badge displaying a provider name with color coding.
struct ProviderBadge: View {
    let providerName: String

    var body: some View {
        Text(displayName)
            .font(.caption2)
            .fontWeight(.medium)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(color.opacity(0.2))
            .foregroundStyle(color)
            .clipShape(Capsule())
    }

    /// Human-readable name for common providers.
    private var displayName: String {
        switch providerName {
        case "digikey": return "Digi-Key"
        case "easyeda2kicad": return "EasyEDA"
        case "mouser": return "Mouser"
        case "octopart": return "Octopart"
        case "octopart-cad": return "SnapEDA"
        case "jlcparts": return "JLC"
        case "jlcpcb": return "Assembly"
        case "lcsc": return "LCSC"
        default: return providerName.capitalized
        }
    }

    /// Color per provider for visual distinction.
    private var color: Color {
        switch providerName {
        case "digikey": return .yellow
        case "easyeda2kicad": return .blue
        case "mouser": return .red
        case "octopart": return .purple
        case "octopart-cad": return .indigo
        case "jlcparts": return .orange
        case "jlcpcb": return .teal
        case "lcsc": return .cyan
        default: return .gray
        }
    }
}
