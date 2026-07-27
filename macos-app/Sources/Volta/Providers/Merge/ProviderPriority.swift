//
//  ProviderPriority.swift
//  Volta
//
//  Phase 2 / Task 4 — Merge Engine v2
//
//  Provider priority configuration. Controls which provider's data wins
//  when multiple sources disagree. User can reorder in settings.
//

import Foundation

/// Provider priority ordering for the merge engine.
///
/// When two providers return different values for the same field (e.g.,
/// different stock counts), the provider with higher priority wins.
/// Default priority is based on data freshness and authority:
///   1. Digi-Key (first-party, real-time)
///   2. Octopart/Nexar (aggregator, near-real-time)
///   3. Mouser (first-party, near-real-time)
///   4. jlcparts (offline snapshot, stale)
final class ProviderPriority: @unchecked Sendable {
    /// Ordered list of provider names. Index 0 = highest priority.
    private var order: [String]
    private let lock = NSLock()

    static let `default` = ProviderPriority()

    init(order: [String] = [
        "digikey",
        "octopart",
        "mouser",
        "easyeda2kicad",
        "easyeda",
        "jlcparts",
    ]) {
        self.order = order
    }

    /// Get the priority rank for a provider (lower = higher priority).
    func rank(for providerName: String) -> Int {
        lock.lock()
        defer { lock.unlock() }
        return order.firstIndex(of: providerName) ?? Int.max
    }

    /// Compare two provider names. Returns true if `a` has higher priority than `b`.
    func isHigherPriority(_ a: String, than b: String) -> Bool {
        rank(for: a) < rank(for: b)
    }

    /// Update the priority order. Notifies observers.
    func updateOrder(_ newOrder: [String]) {
        lock.lock()
        order = newOrder
        lock.unlock()
    }

    /// Current priority order (defensive copy).
    var currentOrder: [String] {
        lock.lock()
        defer { lock.unlock() }
        return order
    }
}
