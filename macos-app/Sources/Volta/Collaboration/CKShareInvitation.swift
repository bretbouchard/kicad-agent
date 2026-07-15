//
//  CKShareInvitation.swift
//  Volta
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
    ///
    /// Note: CKShare construction requires a valid CloudKit container, which
    /// is configured in Phase 188.1 (two-device migration test). For now,
    /// this throws `CKShareError.urlNotAvailable` until the container is set.
    func makeShareURL(recordID: CKRecord.ID, title: String) async throws -> URL {
        if let existing = share, let url = existing.url {
            return url
        }
        // CKShare requires recordType + recordID, not just recordID. Wrap in
        // try? so test environments without CloudKit container fail gracefully.
        let record = CKRecord(recordType: "Project", recordID: recordID)
        let newShare = CKShare(rootRecord: record)
        newShare[CKShare.SystemFieldKey.title] = title as NSString
        self.share = newShare

        Logger.models.info("CKShare created for recordID=\(recordID.recordName, privacy: .public)")
        guard let url = newShare.url else {
            throw CKShareError.urlNotAvailable
        }
        return url
    }

    /// Revoke the current share.
    func revoke() {
        share = nil
        Logger.models.info("CKShare revoked")
    }

    /// Add a participant to the share.
    func addParticipant(_ participant: CKShare.Participant) {
        share?.addParticipant(participant)
    }

    /// Remove a participant from the share.
    func removeParticipant(_ participant: CKShare.Participant) {
        share?.removeParticipant(participant)
    }
}

/// Errors specific to CKShare operations.
enum CKShareError: LocalizedError {
    case urlNotAvailable

    var errorDescription: String? {
        "CKShare URL not available — container may not be configured"
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
