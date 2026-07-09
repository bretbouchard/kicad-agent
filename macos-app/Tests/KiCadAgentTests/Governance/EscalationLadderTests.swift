//
//  EscalationLadderTests.swift
//  KiCadAgentTests
//
//  Phase 169 — Obdurate Runtime
//

import Testing
import Foundation
@testable import KiCadAgent

@Suite("EscalationLadder")
struct EscalationLadderTests {

    @Test("First failure → T1")
    func firstFailureT1() {
        let ladder = EscalationLadder()
        let tier = ladder.recordFailure(taskKey: "add_component", severity: .high, details: ["boom"])
        #expect(tier == .t1)
        #expect(ladder.currentTier(for: "add_component") == .t1)
        #expect(ladder.failureCount(for: "add_component") == 1)
    }

    @Test("2 failures → T2, 3 → T3, 5 → T4")
    func tierProgression() {
        let ladder = EscalationLadder()
        #expect(ladder.recordFailure(taskKey: "x") == .t1)
        #expect(ladder.recordFailure(taskKey: "x") == .t2)
        #expect(ladder.recordFailure(taskKey: "x") == .t3)
        // Tier 4 threshold is 5 — count 4 stays at T3.
        _ = ladder.recordFailure(taskKey: "x")
        #expect(ladder.currentTier(for: "x") == .t3)
        #expect(ladder.recordFailure(taskKey: "x") == .t4)
    }

    @Test("humanInputRequired at T4")
    func humanInputAtT4() {
        let ladder = EscalationLadder()
        for _ in 0..<5 {
            _ = ladder.recordFailure(taskKey: "halted")
        }
        #expect(ladder.humanInputRequired(for: "halted") == true)
    }

    @Test("recordSuccess clears the failure count")
    func successClears() {
        let ladder = EscalationLadder()
        _ = ladder.recordFailure(taskKey: "y")
        _ = ladder.recordFailure(taskKey: "y")
        ladder.recordSuccess(taskKey: "y")
        #expect(ladder.currentTier(for: "y") == .none)
        #expect(ladder.failureCount(for: "y") == 0)
    }

    @Test("reset clears all")
    func resetAll() {
        let ladder = EscalationLadder()
        _ = ladder.recordFailure(taskKey: "a")
        _ = ladder.recordFailure(taskKey: "b")
        ladder.reset()
        #expect(ladder.snapshot().isEmpty)
    }

    @Test("Tier escalation is monotonic — never decreases until success")
    func monotonicEscalation() {
        let ladder = EscalationLadder()
        // Bump to T3 with 3 failures of severity high.
        _ = ladder.recordFailure(taskKey: "z", severity: .high)
        _ = ladder.recordFailure(taskKey: "z", severity: .high)
        _ = ladder.recordFailure(taskKey: "z", severity: .high)
        let before = ladder.currentTier(for: "z")
        // More failures must not decrease tier.
        _ = ladder.recordFailure(taskKey: "z", severity: .high)
        let after = ladder.currentTier(for: "z")
        #expect(after.rawValue >= before.rawValue)
    }

    @Test("Tier thresholds match bureaucracy §4")
    func tierMath() {
        #expect(EscalationLadder.tierForCount(0) == .none)
        #expect(EscalationLadder.tierForCount(1) == .t1)
        #expect(EscalationLadder.tierForCount(2) == .t2)
        #expect(EscalationLadder.tierForCount(3) == .t3)
        #expect(EscalationLadder.tierForCount(4) == .t3)
        #expect(EscalationLadder.tierForCount(5) == .t4)
        #expect(EscalationLadder.tierForCount(10) == .t4)
    }

    @Test("Severity enum ordering")
    func severityOrdering() {
        #expect(FindingSeverity.critical < FindingSeverity.high)
        #expect(FindingSeverity.high < FindingSeverity.medium)
        #expect(FindingSeverity.medium < FindingSeverity.low)
    }

    @Test("Notification posted on tier increase")
    func notificationPosted() async throws {
        let ladder = EscalationLadder()
        let taskKey = "notify-test"

        // Use an actor to safely collect the notification payload.
        actor Collector {
            var receivedTier: EscalationTier = .none
            var didReceive = false
            func set(_ tier: EscalationTier) {
                receivedTier = tier
                didReceive = true
            }
        }
        let collector = Collector()

        let observer = NotificationCenter.default.addObserver(
            forName: .kcEscalation,
            object: nil,
            queue: .main
        ) { note in
            guard let payload = note.userInfo?["payload"] as? EscalationNotificationPayload else { return }
            // Filter by taskKey: NotificationCenter.default is process-wide,
            // so parallel tests posting .kcEscalation notifications would
            // otherwise pollute this collector with other tiers.
            guard payload.taskKey == taskKey else { return }
            Task { await collector.set(payload.newTier) }
        }
        defer { NotificationCenter.default.removeObserver(observer) }

        // Two failures to escalate from none → T1 → T2.
        _ = ladder.recordFailure(taskKey: taskKey)   // T1
        _ = ladder.recordFailure(taskKey: taskKey)   // T2

        // Allow the main-queue async dispatch + Task to fire.
        try await Task.sleep(for: .milliseconds(200))

        let didReceive = await collector.didReceive
        let receivedTier = await collector.receivedTier
        #expect(didReceive)
        #expect(receivedTier == .t2)
    }
}
