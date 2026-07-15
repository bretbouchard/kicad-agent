//
//  KCCostLedgerTests.swift
//  VoltaTests
//
//  Phase 165 — Provider Router
//
//  Tests for KCCostLedger:
//    - Append + de-dup
//    - Per-message warning threshold (T-165-03 mitigation)
//    - Range queries: today / thisWeek / allTime
//    - Per-provider breakdown
//    - clear()
//    - record(usage:) convenience
//

import Testing
import Foundation
@testable import Volta

@MainActor
@Suite("KCCostLedger")
struct KCCostLedgerTests {

    // MARK: - Append

    @Test("append stores an entry")
    func appendStoresEntry() {
        let ledger = KCCostLedger()
        let entry = KCCostEntry(
            providerKind: .openAI,
            taskType: .complexReasoning,
            inputTokens: 100,
            outputTokens: 50,
            costUSD: 0.05
        )
        ledger.append(entry)

        #expect(ledger.entries.count == 1)
        #expect(ledger.entries.first?.providerKind == .openAI)
        #expect(ledger.entries.first?.costUSD == 0.05)
    }

    @Test("Duplicate id is dropped")
    func duplicateDropped() {
        let ledger = KCCostLedger()
        let id = UUID()
        let entry1 = KCCostEntry(id: id, providerKind: .appleLocal, taskType: .quickReply, inputTokens: 10, outputTokens: 5, costUSD: 0)
        let entry2 = KCCostEntry(id: id, providerKind: .appleLocal, taskType: .quickReply, inputTokens: 10, outputTokens: 5, costUSD: 0)

        ledger.append(entry1)
        ledger.append(entry2)

        #expect(ledger.entries.count == 1)
    }

    // MARK: - Record convenience

    @Test("record(providerKind:...) builds and stores an entry")
    func recordConvenienceBuildsEntry() {
        let ledger = KCCostLedger()
        let entry = ledger.record(
            providerKind: .anthropic,
            taskType: .vision,
            inputTokens: 200,
            outputTokens: 100,
            costUSD: 0.12
        )

        #expect(entry.providerKind == .anthropic)
        #expect(entry.taskType == .vision)
        #expect(ledger.entries.count == 1)
        #expect(ledger.entries.first?.id == entry.id)
    }

    @Test("record(usage:...) translates KCUsage correctly")
    func recordUsageTranslates() {
        let ledger = KCCostLedger()
        let usage = KCUsage(inputTokens: 150, outputTokens: 75, estimatedCostUSD: 0.08)
        ledger.record(usage: usage, providerKind: .gemini, taskType: .complexReasoning)

        #expect(ledger.entries.count == 1)
        let entry = ledger.entries[0]
        #expect(entry.inputTokens == 150)
        #expect(entry.outputTokens == 75)
        #expect(entry.costUSD == 0.08)
    }

    // MARK: - Warning threshold (T-165-03)

    @Test("Entry above threshold sets lastEntryExceededThreshold")
    func thresholdTripsOnExpensiveEntry() {
        let ledger = KCCostLedger()
        ledger.perMessageWarningThreshold = 10

        let cheap = KCCostEntry(providerKind: .appleLocal, taskType: .quickReply, inputTokens: 10, outputTokens: 5, costUSD: 0)
        ledger.append(cheap)
        #expect(ledger.lastEntryExceededThreshold == false)

        let expensive = KCCostEntry(providerKind: .openAI, taskType: .complexReasoning, inputTokens: 50000, outputTokens: 20000, costUSD: 15)
        ledger.append(expensive)
        #expect(ledger.lastEntryExceededThreshold)
    }

    @Test("acknowledgeWarning clears the flag")
    func acknowledgeClearsFlag() {
        let ledger = KCCostLedger()
        ledger.perMessageWarningThreshold = 5
        ledger.append(KCCostEntry(providerKind: .openAI, taskType: .complexReasoning, inputTokens: 100, outputTokens: 100, costUSD: 10))
        #expect(ledger.lastEntryExceededThreshold)

        ledger.acknowledgeWarning()
        #expect(!ledger.lastEntryExceededThreshold)
    }

    // MARK: - Summary queries

    @Test("allTime aggregates all entries")
    func allTimeAggregatesAll() {
        let ledger = KCCostLedger()
        ledger.record(providerKind: .appleLocal, taskType: .quickReply, inputTokens: 10, outputTokens: 5, costUSD: 0)
        ledger.record(providerKind: .openAI, taskType: .complexReasoning, inputTokens: 100, outputTokens: 50, costUSD: 0.05)
        ledger.record(providerKind: .openAI, taskType: .vision, inputTokens: 200, outputTokens: 100, costUSD: 0.10)

        let allTime = ledger.allTime
        #expect(allTime.callCount == 3)
        #expect(allTime.inputTokens == 310)
        #expect(allTime.outputTokens == 155)
        #expect(allTime.totalCostUSD == 0.15)
    }

    @Test("Per-provider breakdown splits by kind")
    func perProviderBreakdown() {
        let ledger = KCCostLedger()
        ledger.record(providerKind: .appleLocal, taskType: .quickReply, inputTokens: 10, outputTokens: 5, costUSD: 0)
        ledger.record(providerKind: .appleLocal, taskType: .quickReply, inputTokens: 20, outputTokens: 10, costUSD: 0)
        ledger.record(providerKind: .openAI, taskType: .complexReasoning, inputTokens: 100, outputTokens: 50, costUSD: 0.05)

        let allTime = ledger.allTime
        #expect(allTime.perProvider.count == 2)

        let apple = allTime.perProvider.first { $0.providerKind == .appleLocal }
        #expect(apple?.callCount == 2)
        #expect(apple?.inputTokens == 30)
        #expect(apple?.totalCostUSD == 0)

        let openai = allTime.perProvider.first { $0.providerKind == .openAI }
        #expect(openai?.callCount == 1)
        #expect(openai?.totalCostUSD == 0.05)
    }

    @Test("today filter excludes old entries")
    func todayFilterExcludesOld() {
        let ledger = KCCostLedger()
        // Old entry — should not appear in `today`.
        let oldDate = Date().addingTimeInterval(-2 * 24 * 60 * 60) // 2 days ago
        let oldEntry = KCCostEntry(
            timestamp: oldDate,
            providerKind: .openAI,
            taskType: .complexReasoning,
            inputTokens: 100,
            outputTokens: 50,
            costUSD: 0.05
        )
        ledger.append(oldEntry)
        // Fresh entry.
        ledger.record(providerKind: .appleLocal, taskType: .quickReply, inputTokens: 10, outputTokens: 5, costUSD: 0)

        let today = ledger.today
        #expect(today.callCount == 1)
        #expect(today.inputTokens == 10)
        #expect(today.totalCostUSD == 0)
    }

    @Test("thisWeek filter includes last 7 days")
    func thisWeekIncludesRecentOnly() {
        let ledger = KCCostLedger()
        // 3 days ago — should appear in `thisWeek`.
        let recentDate = Date().addingTimeInterval(-3 * 24 * 60 * 60)
        ledger.append(KCCostEntry(
            timestamp: recentDate,
            providerKind: .openAI,
            taskType: .complexReasoning,
            inputTokens: 100,
            outputTokens: 50,
            costUSD: 0.05
        ))
        // 30 days ago — should NOT appear.
        let oldDate = Date().addingTimeInterval(-30 * 24 * 60 * 60)
        ledger.append(KCCostEntry(
            timestamp: oldDate,
            providerKind: .openAI,
            taskType: .vision,
            inputTokens: 200,
            outputTokens: 100,
            costUSD: 0.10
        ))

        let week = ledger.thisWeek
        #expect(week.callCount == 1)
        #expect(week.totalCostUSD == 0.05)
    }

    @Test("summary(from:nil) returns all entries")
    func summaryFromNilIsAll() {
        let ledger = KCCostLedger()
        ledger.record(providerKind: .appleLocal, taskType: .quickReply, inputTokens: 10, outputTokens: 5, costUSD: 0)
        let summary = ledger.summary(from: nil, named: "Test")
        #expect(summary.callCount == 1)
        #expect(summary.rangeName == "Test")
    }

    // MARK: - clear

    @Test("clear wipes all entries")
    func clearWipesEntries() {
        let ledger = KCCostLedger()
        ledger.record(providerKind: .openAI, taskType: .complexReasoning, inputTokens: 100, outputTokens: 50, costUSD: 0.05)
        #expect(ledger.entries.count == 1)

        ledger.clear()
        #expect(ledger.entries.isEmpty)
        #expect(ledger.allTime.callCount == 0)
    }

    // MARK: - entries(for:)

    @Test("entries(for:) filters by provider")
    func entriesForProvider() {
        let ledger = KCCostLedger()
        ledger.record(providerKind: .appleLocal, taskType: .quickReply, inputTokens: 10, outputTokens: 5, costUSD: 0)
        ledger.record(providerKind: .openAI, taskType: .complexReasoning, inputTokens: 100, outputTokens: 50, costUSD: 0.05)
        ledger.record(providerKind: .openAI, taskType: .vision, inputTokens: 200, outputTokens: 100, costUSD: 0.10)

        let openaiEntries = ledger.entries(for: .openAI)
        #expect(openaiEntries.count == 2)
        #expect(openaiEntries.allSatisfy { $0.providerKind == .openAI })
    }

    // MARK: - Empty ledger

    @Test("Empty ledger returns zero summary")
    func emptyLedger() {
        let ledger = KCCostLedger()
        #expect(ledger.entries.isEmpty)
        #expect(ledger.today.callCount == 0)
        #expect(ledger.allTime.totalCostUSD == 0)
        #expect(ledger.thisWeek.perProvider.isEmpty)
    }

    // MARK: - KCCostEntry preconditions

    @Test("KCCostEntry accepts non-negative values")
    func entryAcceptsNonNegative() {
        // Precondition failures abort the process — can't be caught via `throws:`.
        // Verify only the happy path; the precondition in KCCostEntry.init
        // handles the negative case at runtime.
        _ = KCCostEntry(providerKind: .openAI, taskType: .quickReply, inputTokens: 0, outputTokens: 0, costUSD: 0)
        _ = KCCostEntry(providerKind: .openAI, taskType: .quickReply, inputTokens: 100, outputTokens: 50, costUSD: 0.05)
    }
}
