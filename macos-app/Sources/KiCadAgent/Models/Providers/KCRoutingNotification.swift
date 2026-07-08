//
//  KCRoutingNotification.swift
//  KiCadAgent
//
//  Phase 165 — Provider Router
//
//  Posts a one-time notification when the router falls back from a user's
//  preferred provider to FoundationModels (per MOD-02 / MOD-10 augmentation:
//  "Unavailable preferred model falls back to FoundationModels with one-time
//  notification").
//
//  Why one-time per swap: spammy notifications on every prompt would train
//  users to dismiss them. The router tracks which (preferredKind → fallbackKind)
//  swaps have already been announced this session; subsequent swaps of the
//  same shape post no notification until the next app launch (or until
//  `reset()` is called by tests).
//
//  Per MOD-02: notification is informational. Routing still happens — we
//  never silently fall back, and we never block on a missing preferred model.
//

import Foundation
import OSLog

/// Notification names posted on fallback. SwiftUI views or the chat shell
/// observe these and surface an inline banner.
extension Notification.Name {
    /// Posted when the router fell back to FoundationModels because the
    /// user's preferred provider was unavailable. `userInfo` carries a
    /// `KCRoutingNotificationPayload`.
    static let kcProviderFallbackOccurred = Notification.Name("kcProviderFallbackOccurred")
}

/// Payload for `.kcProviderFallbackOccurred`.
struct KCRoutingNotificationPayload: Sendable, Equatable {
    /// What the user/system asked for.
    let preferredKind: KCProviderKind
    /// What the router actually used.
    let fallbackKind: KCProviderKind
    /// The task that triggered the swap.
    let taskType: KCTaskType
    /// Why the preferred was unavailable.
    let reason: String

    /// User-facing message.
    var localizedMessage: String {
        // Most common case: fallback to AppleLocal when no cloud configured.
        if fallbackKind == .appleLocal {
            return "\(preferredKind.displayName) isn't available — using \(fallbackKind.displayName). \(reason)"
        }
        return "Routing \(taskType.displayName.lowercased()) to \(fallbackKind.displayName) instead of \(preferredKind.displayName). \(reason)"
    }
}

/// Posts + dedupes fallback notifications. One instance lives alongside the
/// router in the app environment. Sendable + @unchecked: all mutation happens
/// inside the `post` method which is synchronized via NSLock.
final class KCRoutingNotifier: @unchecked Sendable {
    private let lock = NSLock()
    /// Set of "(preferredKind,fallbackKind,taskType)" strings already posted
    /// this session. Prevents re-posting the same fallback shape.
    private var announcedSwaps: Set<String> = []

    /// Custom notification center (default: `.default`). Tests inject a
    /// dedicated instance so they don't pollute the global stream.
    private let center: NotificationCenter

    init(center: NotificationCenter = .default) {
        self.center = center
    }

    /// Post a fallback notification. Returns true if this swap shape was
    /// newly announced (caller may use the result for testing); false if
    /// suppressed as duplicate.
    @discardableResult
    func post(preferred: KCProviderKind, fallback: KCProviderKind, taskType: KCTaskType, reason: String) -> Bool {
        // Defensive: never announce fallback to the same kind.
        guard preferred != fallback else { return false }

        let key = swapKey(preferred: preferred, fallback: fallback, taskType: taskType)
        lock.lock()
        if announcedSwaps.contains(key) {
            lock.unlock()
            return false
        }
        announcedSwaps.insert(key)
        lock.unlock()

        let payload = KCRoutingNotificationPayload(
            preferredKind: preferred,
            fallbackKind: fallback,
            taskType: taskType,
            reason: reason
        )
        center.post(name: .kcProviderFallbackOccurred, object: nil, userInfo: ["payload": payload])
        Logger.models.info("KCRoutingNotifier: \(payload.localizedMessage)")
        return true
    }

    /// Clear announced-swap memory. Tests use this between cases.
    func reset() {
        lock.lock()
        announcedSwaps.removeAll()
        lock.unlock()
    }

    /// Number of distinct swaps announced so far. For test introspection.
    var announcedSwapCount: Int {
        lock.lock()
        defer { lock.unlock() }
        return announcedSwaps.count
    }

    private func swapKey(preferred: KCProviderKind, fallback: KCProviderKind, taskType: KCTaskType) -> String {
        "\(preferred.rawValue)->\(fallback.rawValue)@\(taskType.rawValue)"
    }
}
