//
//  KCCostLedger.swift
//  Volta
//
//  Phase 165 — Provider Router
//
//  Append-only ledger of token usage + cost per provider call. Per MOD-12:
//  "App shows token usage and cost estimate per message." The ledger records
//  every call (per-message) and is queryable for aggregates (per-day,
//  per-week, all-time, per-provider).
//
//  Per MOD-12: ledger is surfaced in two places — (1) per-message badges in
//  the chat UI (consumes `KCUsage` directly from the KCToken stream), and
//  (2) aggregate summaries in Settings (consumes `dailyTotal` etc.).
//
//  Per Pitfall 6 / T-165-03 mitigation: Decimal for all currency. Per-call
//  cost is validated against a runaway-spend threshold (default $1k/msg).
//
//  Concurrency: the append path runs on the main actor (UI-driven) for
//  simplicity. Background append is supported via `appendFromStream` which
//  hops back to the main actor internally. The ledger is `@unchecked Sendable`
//  because all mutation happens inside MainActor-isolated methods.
//

import Foundation
import OSLog

/// One row in the cost ledger. Immutable value type.
struct KCCostEntry: Sendable, Equatable, Identifiable, Codable {
    let id: UUID
    let timestamp: Date
    let providerKind: KCProviderKind
    let taskType: KCTaskType
    let inputTokens: Int
    let outputTokens: Int
    let costUSD: Decimal

    init(
        id: UUID = UUID(),
        timestamp: Date = Date(),
        providerKind: KCProviderKind,
        taskType: KCTaskType,
        inputTokens: Int,
        outputTokens: Int,
        costUSD: Decimal
    ) {
        precondition(inputTokens >= 0)
        precondition(outputTokens >= 0)
        precondition(costUSD >= 0)
        self.id = id
        self.timestamp = timestamp
        self.providerKind = providerKind
        self.taskType = taskType
        self.inputTokens = inputTokens
        self.outputTokens = outputTokens
        self.costUSD = costUSD
    }
}

/// Per-provider aggregate row.
struct KCProviderTotals: Sendable, Equatable {
    let providerKind: KCProviderKind
    let callCount: Int
    let inputTokens: Int
    let outputTokens: Int
    let totalCostUSD: Decimal
}

/// Range-of-time aggregate. Used by Settings UI: today, this week, all-time.
struct KCCostSummary: Sendable, Equatable {
    let rangeName: String
    let callCount: Int
    let inputTokens: Int
    let outputTokens: Int
    let totalCostUSD: Decimal
    let perProvider: [KCProviderTotals]
}

/// Default per-message spend warning threshold. ponytail: declared outside
/// the @MainActor class so `KCRoutingPreferences.default` can reference it
/// from a non-isolated context.
enum KCCostLedgerDefaults {
    static let perMessageWarningThreshold: Decimal = 1000
}

/// Append-only cost ledger. ObservableObject so Settings UI re-renders on
/// each append. The chat UI reads `KCUsage` directly from the token stream
/// for per-message badges (no ledger round-trip); the ledger is for
/// aggregate tracking per MOD-12.
@MainActor
final class KCCostLedger: ObservableObject {
    /// All recorded entries. Public read; mutation only via `append`.
    @Published private(set) var entries: [KCCostEntry] = []

    /// Maximum single-message cost before the runaway-spend warning fires.
    /// Per T-165-03 mitigation. Default $1000 (production override via
    /// Settings is Phase 166+ work).
    var perMessageWarningThreshold: Decimal = KCCostLedgerDefaults.perMessageWarningThreshold

    /// Convenience threshold used in tests + Settings UI display.
    /// ponytail: forwarded to the non-isolated namespace constant.
    nonisolated static let defaultPerMessageWarningThreshold: Decimal = KCCostLedgerDefaults.perMessageWarningThreshold

    /// Tracks whether the last append crossed the per-message warning
    /// threshold. Settings UI surfaces this. Reset by `acknowledgeWarning()`.
    @Published private(set) var lastEntryExceededThreshold: Bool = false

    init() {}

    // MARK: - Append

    /// Record a completed call. Idempotent on `entry.id` — duplicate appends
    /// for the same id are silently dropped.
    func append(_ entry: KCCostEntry) {
        // De-dup by id (some streaming paths may double-report).
        if entries.contains(where: { $0.id == entry.id }) {
            Logger.models.debug("KCCostLedger: dropping duplicate entry \(entry.id.uuidString.prefix(8))")
            return
        }
        entries.append(entry)
        lastEntryExceededThreshold = entry.costUSD >= self.perMessageWarningThreshold
        if lastEntryExceededThreshold {
            let threshold = self.perMessageWarningThreshold
            Logger.models.warning("KCCostLedger: entry \(entry.id.uuidString.prefix(8)) cost \(entry.costUSD) crossed per-message warning threshold (\(threshold))")
        }
    }

    /// Convenience: record a completed call from raw fields.
    @discardableResult
    func record(
        providerKind: KCProviderKind,
        taskType: KCTaskType,
        inputTokens: Int,
        outputTokens: Int,
        costUSD: Decimal,
        timestamp: Date = Date()
    ) -> KCCostEntry {
        let entry = KCCostEntry(
            timestamp: timestamp,
            providerKind: providerKind,
            taskType: taskType,
            inputTokens: inputTokens,
            outputTokens: outputTokens,
            costUSD: costUSD
        )
        append(entry)
        return entry
    }

    /// Record from a `KCUsage` payload captured during a stream.
    @discardableResult
    func record(
        usage: KCUsage,
        providerKind: KCProviderKind,
        taskType: KCTaskType,
        timestamp: Date = Date()
    ) -> KCCostEntry {
        record(
            providerKind: providerKind,
            taskType: taskType,
            inputTokens: usage.inputTokens,
            outputTokens: usage.outputTokens,
            costUSD: usage.estimatedCostUSD,
            timestamp: timestamp
        )
    }

    func acknowledgeWarning() {
        lastEntryExceededThreshold = false
    }

    // MARK: - Mutations

    /// Clear all entries. Used by the "Reset ledger" action in Settings.
    func clear() {
        entries.removeAll()
        lastEntryExceededThreshold = false
    }

    // MARK: - Queries

    /// Today's total (UTC midnight rollover).
    var today: KCCostSummary {
        summary(from: Calendar.current.startOfDay(for: Date()), named: "Today")
    }

    /// This week's total (last 7 days).
    var thisWeek: KCCostSummary {
        let start = Date().addingTimeInterval(-7 * 24 * 60 * 60)
        return summary(from: start, named: "This Week")
    }

    /// All-time total.
    var allTime: KCCostSummary {
        summary(from: nil, named: "All Time")
    }

    /// Aggregate over an arbitrary range. `from == nil` means all entries.
    func summary(from start: Date?, named rangeName: String) -> KCCostSummary {
        let filtered: [KCCostEntry]
        if let start {
            filtered = entries.filter { $0.timestamp >= start }
        } else {
            filtered = entries
        }

        var perProviderMap: [KCProviderKind: (Int, Int, Int, Decimal)] = [:]
        var totalCalls = 0
        var totalIn = 0
        var totalOut = 0
        var totalCost: Decimal = 0

        for entry in filtered {
            totalCalls += 1
            totalIn += entry.inputTokens
            totalOut += entry.outputTokens
            totalCost += entry.costUSD

            if let existing = perProviderMap[entry.providerKind] {
                perProviderMap[entry.providerKind] = (
                    existing.0 + 1,
                    existing.1 + entry.inputTokens,
                    existing.2 + entry.outputTokens,
                    existing.3 + entry.costUSD
                )
            } else {
                perProviderMap[entry.providerKind] = (
                    1,
                    entry.inputTokens,
                    entry.outputTokens,
                    entry.costUSD
                )
            }
        }

        let perProvider = perProviderMap.map { kind, totals in
            KCProviderTotals(
                providerKind: kind,
                callCount: totals.0,
                inputTokens: totals.1,
                outputTokens: totals.2,
                totalCostUSD: totals.3
            )
        }.sorted { $0.providerKind.rawValue < $1.providerKind.rawValue }

        return KCCostSummary(
            rangeName: rangeName,
            callCount: totalCalls,
            inputTokens: totalIn,
            outputTokens: totalOut,
            totalCostUSD: totalCost,
            perProvider: perProvider
        )
    }

    /// Filter entries by provider. Useful for per-provider drill-down UI.
    func entries(for providerKind: KCProviderKind) -> [KCCostEntry] {
        entries.filter { $0.providerKind == providerKind }
    }
}
