//
//  ProviderAvailability.swift
//  VoltaPCBCore
//
//  Phase 1 / Task 0 — VoltaPCBCore Foundation
//
//  Provider availability state for component / CAD / routing / compliance
//  providers. Mirrors the KCProviderAvailability pattern from Volta but
//  adds an `.offlineCacheOnly` case to cover the component-provider
//  lifecycle where the local SQLite cache can serve results even when
//  the upstream network API is unreachable.
//
//  ponytail: enum with associated value. Exhaustive switching in merge engine.
//

import Foundation

/// Provider availability states for component/CAD/routing/compliance providers.
/// Mirrors the KCProviderAvailability pattern but with four cases covering
/// the component provider lifecycle (including offline cache).
public enum ProviderAvailability: Sendable, Equatable {
    /// Provider is ready to serve live requests right now.
    case available

    /// Provider needs user action (API key, OAuth, login). Reason is
    /// user-readable and the UI surfaces a deep-link to Settings.
    case requiresAuth(reason: String)

    /// Provider exists but cannot serve requests. Reason is user-readable.
    /// Examples: network down, rate limited, upstream 5xx.
    case unavailable(reason: String)

    /// Provider's upstream is unreachable but a stale cache is available.
    /// Merge engine may use cached results with a confidence penalty.
    case offlineCacheOnly(reason: String)

    /// True only when `.available`. Convenience for merge-engine filters.
    public var isAvailable: Bool {
        if case .available = self { return true }
        return false
    }
}
