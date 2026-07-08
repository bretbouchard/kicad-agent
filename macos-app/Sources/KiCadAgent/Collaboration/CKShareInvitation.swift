//
//  CKShareInvitation.swift
//  KiCadAgent
//
//  Phase 188 — CKShare Invitations
//
//  CKShare wrapper for inviting collaborators to a project. Generates
//  share URLs that participants accept in their Mail / Messages app.
//
//  COLLAB-01/02/03/04/09: invitation requirements.
//

import Foundation
import CloudKit
import OSLog

/// Coordinator for CKShare invitation lifecycle.
@MainActor
@Observable
final class CKShareInvitation {
    /// Active share for the current project (nil when not shared).
    private(set) var share: CKShare?

    /// True when a share URL has been generated.
    var isShared: Bool { share != nil }

    /// Generate or fetch the share URL for the project.
    func makeShareURL(recordID: CKRecord.ID, title: String) async throws -> URL {
        // If existing share, return its URL.
        if let existing = share {
            return existing.url
        }

        // Create new share.
        let newShare = CKShare(rootRecordID: recordID)
        newShare[CKShareTitleKey] = title
        newShare.publicPermission = .none
        newShare.systemFields = try archiveSystemFields(newShare)
        self.share = newShare

        Logger.models.info("CKShare created for recordID=\(recordID.recordName, privacy: .public)")
        return newShare.url
    }

    /// Revoke the current share.
    func revoke() {
        share = nil
        Logger.models.info("CKShare revoked")
    }

    /// Participant operations.
    func addParticipant(_ participant: CKShare.Participant) {
        share?.addParticipant(participant)
    }

    func removeParticipant(_ participant: CKShare.Participant) {
        share?.removeParticipant(participant)
    }

    /// Archive systemFields for stable round-trip persistence.
    private func archiveSystemFields(_ share: CKShare) throws -> Data {
        try NSKeyedArchiver.archivedData(withRootObject: share, requiringSecureCoding: true)
    }
}

/// Invitation permissions — what participants can do.
enum InvitationPermission: String, Codable, Sendable, CaseIterable {
    case read      // View only
    case write     // Edit but not share
    case admin     // Full control including sharing

    var ckPermission: CKShare.ParticipantPermission {
        switch self {
        case .read: return .readOnly
        case .write: return .readWrite
        case .admin: return .readWrite // Admin is a role, not a permission
        }
    }

    var label: String {
        switch self {
        case .read: return "Can View"
        case .write: return "Can Edit"
        case .admin: return "Admin"
        }
    }
}
