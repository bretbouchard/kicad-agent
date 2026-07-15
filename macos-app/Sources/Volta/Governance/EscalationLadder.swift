//
//  EscalationLadder.swift
//  Volta
//
//  Phase 169 — Obdurate Runtime
//
//  Escalation ladder with auto-trigger on failures. Mirrors the Rick
//  Escalation Ladder in ~/.claude/rules/bureaucracy.md §4:
//
//      Tier 1 — first failure → single retry
//      Tier 2 — 2+ failures   → strategy switch
//      Tier 3 — 3+ failures   → external AI consult
//      Tier 4 — 5+ failures   → halt for human input
//
//  GOV-08: "Escalation ladder (T1 retry → T2 strategy switch → T3
//  external AI → T4 halt)."
//
//  The ladder tracks failures per task key (typically the op name). When
//  the tier increases, an `KCEscalationNotification` is posted with the
//  new tier, task key, and latest failure details so observers (UI banner,
//  audit journal) can react.
//
//  Reset semantics: a successful op call clears the failure count for
//  that task key (per bureaucracy.md §4 "reset() clears failure_counts
//  after successful retry").
//

import Foundation
import OSLog

// MARK: - EscalationTier

enum EscalationTier: Int, Codable, Sendable, Comparable {
    case none = 0
    case t1 = 1
    case t2 = 2
    case t3 = 3
    case t4 = 4

    /// Human-readable name per bureaucracy.md.
    var name: String {
        switch self {
        case .none: return "none"
        case .t1:   return "T1-retry"
        case .t2:   return "T2-strategy-switch"
        case .t3:   return "T3-external-AI"
        case .t4:   return "T4-halt"
        }
    }

    /// Threshold failure count for this tier (inclusive). At-or-above
    /// count → this tier. bureaucracy.md §4 ladder:
    ///   1 → T1, 2 → T2, 3 → T3, 5 → T4.
    var threshold: Int {
        switch self {
        case .none: return 0
        case .t1:   return 1
        case .t2:   return 2
        case .t3:   return 3
        case .t4:   return 5
        }
    }

    static func < (lhs: EscalationTier, rhs: EscalationTier) -> Bool {
        lhs.rawValue < rhs.rawValue
    }
}

// MARK: - Severity

enum FindingSeverity: String, Codable, Sendable, Comparable {
    case critical   // P0
    case high       // P1
    case medium     // P2
    case low        // P3
    case info       // P4

    /// Numeric priority (lower = more severe).
    var priority: Int {
        switch self {
        case .critical: return 0
        case .high:     return 1
        case .medium:   return 2
        case .low:      return 3
        case .info:     return 4
        }
    }

    static func < (lhs: FindingSeverity, rhs: FindingSeverity) -> Bool {
        lhs.priority < rhs.priority
    }
}

// MARK: - EscalationNotification payload

/// Notification payload posted via NotificationCenter when tier increases.
struct EscalationNotificationPayload: Sendable {
    let taskKey: String
    let newTier: EscalationTier
    let previousTier: EscalationTier
    let failureCount: Int
    let latestDetails: [String]
    let severity: FindingSeverity

    init(taskKey: String,
                newTier: EscalationTier,
                previousTier: EscalationTier,
                failureCount: Int,
                latestDetails: [String],
                severity: FindingSeverity) {
        self.taskKey = taskKey
        self.newTier = newTier
        self.previousTier = previousTier
        self.failureCount = failureCount
        self.latestDetails = latestDetails
        self.severity = severity
    }
}

/// Notification name posted when the ladder escalates a task.
extension Notification.Name {
    static let kcEscalation = Notification.Name("com.kicadagent.escalation")
}

// MARK: - EscalationLadder

final class EscalationLadder: @unchecked Sendable {

    private static let logger = Logger(subsystem: "com.kicadagent.app", category: "governance")

    private let lock = NSLock()

    /// Failure count per task key (typically op name).
    private var failureCounts: [String: Int] = [:]
    /// Latest details per task key (most recent first, capped at 5).
    private var failureDetails: [String: [String]] = [:]
    /// Latest severity per task key.
    private var failureSeverity: [String: FindingSeverity] = [:]
    /// Highest tier reached per task key (for monotonic escalation tracking).
    private var highestTier: [String: EscalationTier] = [:]

    init() {}

    // MARK: - Failure recording

    /// Record a failure for `taskKey`. Auto-escalates if the failure count
    /// crosses a tier threshold. Posts `kcEscalation` notification on
    /// tier increase.
    @discardableResult
    func recordFailure(taskKey: String,
                              severity: FindingSeverity = .high,
                              details: [String] = []) -> EscalationTier {
        lock.lock()
        let prevCount = failureCounts[taskKey] ?? 0
        let newCount = prevCount + 1
        failureCounts[taskKey] = newCount

        // Stash details (cap at 5 most recent).
        var det = failureDetails[taskKey] ?? []
        det.insert(contentsOf: details, at: 0)
        if det.count > 5 { det = Array(det.prefix(5)) }
        failureDetails[taskKey] = det

        // Stash severity (max-severity wins).
        let prevSev = failureSeverity[taskKey] ?? .info
        failureSeverity[taskKey] = (severity < prevSev) ? severity : prevSev

        let prevTier = highestTier[taskKey] ?? .none
        let newTier = EscalationLadder.tierForCount(newCount)
        // Monotonic escalation: tier only goes up (bureaucracy §4).
        let finalTier = max(prevTier, newTier)
        highestTier[taskKey] = finalTier

        let prevTierForNotify = prevTier   // capture for notification
        let payloadSeverity = failureSeverity[taskKey] ?? severity

        lock.unlock()

        Self.logger.error("EscalationLadder: \(taskKey, privacy: .public) failure \(newCount) → tier \(finalTier.name, privacy: .public)")

        if finalTier > prevTierForNotify {
            let payload = EscalationNotificationPayload(
                taskKey: taskKey,
                newTier: finalTier,
                previousTier: prevTierForNotify,
                failureCount: newCount,
                latestDetails: det,
                severity: payloadSeverity
            )
            // Post synchronously — observers that want main-thread delivery
            // should register with a main-queue `queue:` parameter.
            // Async dispatch risks losing the notification under test
            // runloops and tight escalation loops.
            NotificationCenter.default.post(
                name: .kcEscalation,
                object: nil,
                userInfo: ["payload": payload]
            )
        }
        return finalTier
    }

    /// Record a success — clears the failure count for `taskKey` (per §4).
    func recordSuccess(taskKey: String) {
        lock.lock(); defer { lock.unlock() }
        failureCounts.removeValue(forKey: taskKey)
        failureDetails.removeValue(forKey: taskKey)
        failureSeverity.removeValue(forKey: taskKey)
        highestTier.removeValue(forKey: taskKey)
    }

    /// Reset everything (panic button / milestone boundary).
    func reset() {
        lock.lock(); defer { lock.unlock() }
        failureCounts.removeAll()
        failureDetails.removeAll()
        failureSeverity.removeAll()
        highestTier.removeAll()
    }

    // MARK: - Queries

    func currentTier(for taskKey: String) -> EscalationTier {
        lock.lock(); defer { lock.unlock() }
        return highestTier[taskKey] ?? .none
    }

    func failureCount(for taskKey: String) -> Int {
        lock.lock(); defer { lock.unlock() }
        return failureCounts[taskKey] ?? 0
    }

    /// Per bureaucracy.md §4: at T4 the ladder halts for human input.
    func humanInputRequired(for taskKey: String) -> Bool {
        currentTier(for: taskKey) >= .t4
    }

    /// Snapshot of all task keys and their tiers (for UI / journal).
    func snapshot() -> [String: EscalationTier] {
        lock.lock(); defer { lock.unlock() }
        return highestTier
    }

    // MARK: - Tier math

    /// Compute tier from failure count. bureaucracy.md §4 thresholds.
    static func tierForCount(_ count: Int) -> EscalationTier {
        if count >= 5 { return .t4 }
        if count >= 3 { return .t3 }
        if count >= 2 { return .t2 }
        if count >= 1 { return .t1 }
        return .none
    }
}
