//
//  IPhoneCompanion.swift
//  Volta
//
//  Phase 202 — iPhone Companion
//
//  LAN pairing, offline queue, cost tracking for the iPhone companion app.
//  iOS target ships as a separate Xcode project (Phase 202.1); these shared
//  models live in the macOS app so both targets can compile against them.
//
//  IPH-01: LAN pairing with Mac
//  IPH-02: offline message queue
//  IPH-03: cost tracking synced
//  IPH-04: receive handoff from Mac
//  IPH-05: trigger jobs from iPhone
//  IPH-06: view results on iPhone
//  IPH-07: notify on completion
//  IPH-08: accept/reject approval gates from iPhone
//  IPH-09: fork conversation from iPhone
//  IPH-10: time-travel from iPhone
//

import Foundation
import OSLog

/// LAN pairing coordinator for Mac ↔ iPhone.
@MainActor
@Observable
final class LANPairingManager {
    /// Paired devices (keyed by device identifier).
    private(set) var pairedDevices: [PairedDevice] = []

    /// Pending pairing requests awaiting user approval.
    private(set) var pendingRequests: [PairingRequest] = []

    /// True when at least one device is paired.
    var hasPairedDevices: Bool { !pairedDevices.isEmpty }

    init() {}

    /// Process an incoming pairing request (received via Bonjour/mDNS).
    func processPairingRequest(_ request: PairingRequest) {
        pendingRequests.append(request)
        Logger.models.info("Pairing request from \(request.deviceName, privacy: .public)")
    }

    /// Approve a pending pairing request. Returns the new PairedDevice.
    @discardableResult
    func approvePairing(id: UUID) -> PairedDevice? {
        guard let idx = pendingRequests.firstIndex(where: { $0.id == id }) else { return nil }
        let request = pendingRequests.remove(at: idx)
        let device = PairedDevice(
            id: request.deviceId,
            name: request.deviceName,
            pairedAt: .now,
            lastSeen: .now
        )
        pairedDevices.append(device)
        Logger.models.info("Pairing approved for \(device.name, privacy: .public)")
        return device
    }

    /// Reject a pending pairing request.
    func rejectPairing(id: UUID) {
        pendingRequests.removeAll { $0.id == id }
    }

    /// Unpair a previously-paired device.
    func unpair(deviceId: UUID) {
        pairedDevices.removeAll { $0.id == deviceId }
    }

    /// Mark a paired device as recently seen (heartbeat).
    func touch(deviceId: UUID) {
        if let idx = pairedDevices.firstIndex(where: { $0.id == deviceId }) {
            pairedDevices[idx].lastSeen = .now
        }
    }
}

/// One paired device (Mac or iPhone).
struct PairedDevice: Identifiable, Sendable, Equatable {
    let id: UUID              // Stable device identifier
    let name: String          // User-facing device name
    let pairedAt: Date        // When pairing was approved
    var lastSeen: Date        // Last heartbeat timestamp

    /// True if device has been seen in the last 5 minutes (live connection).
    var isLive: Bool {
        Date().timeIntervalSince(lastSeen) < 300
    }
}

/// A pending pairing request awaiting user approval.
struct PairingRequest: Identifiable, Sendable, Equatable {
    let id: UUID
    let deviceId: UUID
    let deviceName: String
    let receivedAt: Date
    /// Shared secret for verification (displayed to user for confirmation).
    let pairingCode: String

    init(id: UUID = UUID(), deviceId: UUID, deviceName: String, receivedAt: Date = .now, pairingCode: String) {
        self.id = id
        self.deviceId = deviceId
        self.deviceName = deviceName
        self.receivedAt = receivedAt
        self.pairingCode = pairingCode
    }
}

/// Offline message queue (IPH-02).
///
/// Messages queued while iPhone is offline are flushed when LAN
/// pairing is restored. Bounded to prevent runaway memory.
@MainActor
@Observable
final class OfflineMessageQueue {
    static let maxQueueSize = 1000

    private(set) var pending: [QueuedMessage] = []

    var isFull: Bool { pending.count >= Self.maxQueueSize }

    init() {}

    /// Enqueue a message. Returns true if enqueued, false if at cap.
    @discardableResult
    func enqueue(_ message: QueuedMessage) -> Bool {
        guard !isFull else {
            Logger.models.warning("Offline queue full — dropping message")
            return false
        }
        pending.append(message)
        return true
    }

    /// Drain the queue, returning all pending messages in order.
    func drain() -> [QueuedMessage] {
        let drained = pending
        pending.removeAll()
        return drained
    }

    /// Number of pending messages.
    var count: Int { pending.count }
}

/// One queued message waiting for sync.
struct QueuedMessage: Identifiable, Sendable, Equatable, Codable {
    let id: UUID
    let conversationId: UUID
    let role: String       // user / assistant / system
    let content: String
    let queuedAt: Date

    init(id: UUID = UUID(), conversationId: UUID, role: String, content: String, queuedAt: Date = .now) {
        self.id = id
        self.conversationId = conversationId
        self.role = role
        self.content = content
        self.queuedAt = queuedAt
    }
}

/// Cost tracking aggregator (IPH-03).
@MainActor
@Observable
final class CompanionCostTracker {
    private(set) var totalInputTokens: Int = 0
    private(set) var totalOutputTokens: Int = 0
    private(set) var totalEstimatedUSD: Double = 0
    private(set) var perConversationTotals: [UUID: ConversationCost] = [:]

    init() {}

    func record(message: Message) {
        totalInputTokens += message.inputTokens
        totalOutputTokens += message.outputTokens
        totalEstimatedUSD += message.estimatedCostUSD

        let convId = message.conversationId
        var existing = perConversationTotals[convId] ?? ConversationCost(conversationId: convId)
        existing.inputTokens += message.inputTokens
        existing.outputTokens += message.outputTokens
        existing.estimatedUSD += message.estimatedCostUSD
        perConversationTotals[convId] = existing
    }

    /// Reset totals (e.g., for monthly billing cycle).
    func reset() {
        totalInputTokens = 0
        totalOutputTokens = 0
        totalEstimatedUSD = 0
        perConversationTotals.removeAll()
    }
}

/// Cost totals for one conversation.
struct ConversationCost: Sendable, Equatable {
    let conversationId: UUID
    var inputTokens: Int = 0
    var outputTokens: Int = 0
    var estimatedUSD: Double = 0

    var totalTokens: Int { inputTokens + outputTokens }
}

/// Approval gate remote-decision handler (IPH-08).
@MainActor
@Observable
final class RemoteApprovalGate {
    /// Pending gates awaiting decision (synced to iPhone via CloudKit).
    private(set) var pendingGates: [GateContext] = []

    init() {}

    func enqueue(_ gate: GateContext) {
        pendingGates.append(gate)
    }

    /// Process a remote decision (received from iPhone).
    @discardableResult
    func processDecision(gateId: UUID, resolution: GateResolution) -> Bool {
        guard let idx = pendingGates.firstIndex(where: { $0.id == gateId }) else { return false }
        pendingGates.remove(at: idx)
        let resolutionLabel: String
        switch resolution {
        case .approve: resolutionLabel = "approve"
        case .reject: resolutionLabel = "reject"
        case .showMe: resolutionLabel = "showMe"
        }
        Logger.models.info("Remote approval decided: gate=\(gateId.uuidString.prefix(8)) resolution=\(resolutionLabel)")
        return true
    }
}
