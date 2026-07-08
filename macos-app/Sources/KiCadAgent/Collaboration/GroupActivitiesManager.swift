//
//  GroupActivitiesManager.swift
//  KiCadAgent
//
//  Phase 187 — Group Activities v1
//
//  FaceTime-style collaboration sessions. 4-participant cap (LIVE-01).
//  Single-machine multicast test stub — Phase 187.1 ships two-device test
//  (recognized blocker).
//
//  LIVE-01/02/06/07: live collaboration requirements.
//

import Foundation
import GroupActivities
import OSLog

/// Coordinator for GroupActivities sessions.
///
/// ponytail: protocol-based — no concrete dependency on GroupActivities
/// in tests. DefaultGroupActivitiesManager wraps real GroupSession;
/// MockGroupActivitiesManager used in tests.
@MainActor
@Observable
final class GroupActivitiesManager {
    /// Maximum participants per session (LIVE-01 cap).
    static let maxParticipants = 4

    /// Current session state.
    private(set) var sessionState: SessionState = .idle

    /// Active participants (count capped at 4).
    private(set) var participants: [Participant] = []

    /// Active group session (nil when no session active).
    private(set) var session: GroupSession<KiCadAgentActivity>?

    init() {}

    /// Start a new session. Returns true if started (or already in one).
    @discardableResult
    func startSession(activity: KiCadAgentActivity) async -> Bool {
        guard sessionState != .active else { return true }
        do {
            session = try await GroupSession(for: activity)
            sessionState = .active
            participants = [Participant.local()]
            Logger.models.info("GroupActivities session started id=\(activity.id.uuidString.prefix(8))")
            return true
        } catch {
            sessionState = .error(message: error.localizedDescription)
            Logger.models.error("GroupActivities start failed: \(error.localizedDescription)")
            return false
        }
    }

    /// Add a participant. Returns false if cap reached.
    @discardableResult
    func addParticipant(_ participant: Participant) -> Bool {
        guard participants.count < Self.maxParticipants else {
            Logger.models.warning("GroupActivities at cap (\(Self.maxParticipants)) — refusing \(participant.displayName)")
            return false
        }
        participants.append(participant)
        return true
    }

    /// Remove a participant.
    func removeParticipant(id: UUID) {
        participants.removeAll { $0.id == id }
    }

    /// End the session.
    func endSession() {
        session?.end()
        session = nil
        sessionState = .idle
        participants = []
        Logger.models.info("GroupActivities session ended")
    }

    /// True when at participant cap.
    var atParticipantCap: Bool {
        participants.count >= Self.maxParticipants
    }
}

/// Session lifecycle state.
enum SessionState: Equatable, Sendable {
    case idle
    case active
    case error(message: String)
}

/// One participant in a live session.
struct Participant: Identifiable, Sendable, Equatable {
    let id: UUID
    let displayName: String
    let isLocal: Bool

    static func local() -> Participant {
        Participant(id: UUID(), displayName: "You", isLocal: true)
    }
}

/// The GroupActivities activity descriptor for KiCad Agent.
struct KiCadAgentActivity: GroupActivity, Hashable {
    var metadata: GroupActivityMetadata {
        var meta = GroupActivityMetadata()
        meta.type = .generic
        meta.title = "KiCad Agent Design Session"
        meta.subtitle = "Real-time hardware design collaboration"
        return meta
    }

    let id = UUID()

    static let activityIdentifier = "com.kicadagent.app.design-session"
}
