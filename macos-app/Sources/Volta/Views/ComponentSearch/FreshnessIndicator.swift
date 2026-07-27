//
//  FreshnessIndicator.swift
//  Volta
//
//  Phase 2 / Task 6 — Stale Data UI
//
//  Per-field freshness indicator. Shows "Updated 2h ago" labels and
//  highlights stale data in yellow when >2x TTL.
//

import SwiftUI

/// Freshness level for cached data.
enum DataFreshness: Comparable {
    case fresh       // Within TTL
    case stale       // Past TTL but <2x TTL
    case veryStale   // >2x TTL
    case permanent   // CAD models (never expire)
    case unknown     // No timestamp available

    var color: Color {
        switch self {
        case .fresh:     return .green
        case .stale:     return .yellow
        case .veryStale: return .orange
        case .permanent: return .blue
        case .unknown:   return .secondary
        }
    }

    var label: String {
        switch self {
        case .fresh:     return "Fresh"
        case .stale:     return "Stale"
        case .veryStale: return "Very stale"
        case .permanent: return "Permanent"
        case .unknown:   return "Unknown"
        }
    }
}

/// Compute freshness for a data field based on its source's lastUpdated date.
struct FreshnessCalculator {
    /// TTL thresholds per data type (in seconds).
    static let pricingTTL: TimeInterval = 24 * 3600    // 24 hours
    static let stockTTL: TimeInterval = 3600           // 1 hour
    static let specsTTL: TimeInterval = 30 * 24 * 3600 // 30 days

    /// Compute freshness for a data type given its age.
    static func freshness(age: TimeInterval, ttl: TimeInterval, isPermanent: Bool = false) -> DataFreshness {
        if isPermanent { return .permanent }
        if age < ttl { return .fresh }
        if age < ttl * 2 { return .stale }
        return .veryStale
    }

    /// Format an age as a human-readable string.
    static func formatAge(_ age: TimeInterval) -> String {
        if age < 60 {
            return "Updated just now"
        } else if age < 3600 {
            let mins = Int(age / 60)
            return "Updated \(mins)m ago"
        } else if age < 24 * 3600 {
            let hours = Int(age / 3600)
            return "Updated \(hours)h ago"
        } else if age < 30 * 24 * 3600 {
            let days = Int(age / (24 * 3600))
            return "Updated \(days)d ago"
        } else {
            let months = Int(age / (30 * 24 * 3600))
            return "Updated \(months)mo ago"
        }
    }
}

/// Compact freshness badge for inline use in component detail view.
struct FreshnessBadge: View {
    let freshness: DataFreshness
    let ageLabel: String?

    var body: some View {
        HStack(spacing: 3) {
            Circle()
                .fill(freshness.color)
                .frame(width: 6, height: 6)
            if let ageLabel {
                Text(ageLabel)
                    .font(.caption2)
            } else {
                Text(freshness.label)
                    .font(.caption2)
            }
        }
        .foregroundStyle(freshness.color)
    }
}
