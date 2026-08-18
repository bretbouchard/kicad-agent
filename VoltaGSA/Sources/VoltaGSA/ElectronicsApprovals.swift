import Foundation
import GSAModeledWorld
import GSAObdurate

/// Approval flows for consequential electronics operations (KERNEL-008).
/// The system never decides silently: a destructive or outward-facing
/// operation by a non-founder principal is denied until a named human
/// approves an `ApprovalRequest` that declares — in plain language and in
/// exact scope — the authority an approval confers. Approved requests mint
/// scoped, expiring grants; nothing else mints this authority.
public struct ElectronicsApprovals: Sendable {
    /// How long conferments from these flows live, in seconds.
    public static let defaultTTL: TimeInterval = 600

    private let ledger: ApprovalLedger

    public init(ledger: ApprovalLedger) {
        self.ledger = ledger
    }

    /// Authority for an agent to run a governed export: invoke
    /// `electronics.export` for the TTL window. Exports are release
    /// artifacts headed for manufacturing (M2.4 scope), so they are
    /// consequential by default.
    public func requestExportAuthority(
        requester: Principal,
        human: Principal,
        projectName: String
    ) async -> ApprovalRequest {
        await ledger.submit(ApprovalRequest(
            title: "Export electronics project “\(projectName)”",
            decision: "Allow \(requester.rawValue) to write export manifests for \(projectName) (capability electronics.export) for \(Int(Self.defaultTTL / 60)) minutes.",
            supportingEvidence: [
                "Exporting writes reproducible manifest artifacts inside the platform's allowed roots.",
                "The manifest's digest is recorded as artifact evidence; the file is re-verified against its sha256 before the result is accepted.",
            ],
            requestedOf: human,
            requestedBy: requester,
            grantsScope: GrantScope(capabilities: ["electronics.export"]),
            grantsTTL: Self.defaultTTL
        ))
    }

    /// Authority for an agent to request a manufacturing quote: invoke
    /// `electronics.manufacturing.quote` for the TTL window. A quote request
    /// is the outward-facing step of fabrication — it hands a board package
    /// to a manufacturer (JLCPCB et al.) — so the Phase 2 plan routes it
    /// behind a capability with approvals (M2.4 first flow). The package
    /// under quote is digest-verified at invocation; the request package
    /// itself is written as sha256 evidence.
    public func requestManufacturingQuoteAuthority(
        requester: Principal,
        human: Principal,
        projectName: String,
        provider: String
    ) async -> ApprovalRequest {
        await ledger.submit(ApprovalRequest(
            title: "Request manufacturing quote for “\(projectName)”",
            decision: "Allow \(requester.rawValue) to submit manufacturing quote-request packages for \(projectName) to \(provider) (capability electronics.manufacturing.quote) for \(Int(Self.defaultTTL / 60)) minutes.",
            supportingEvidence: [
                "The Gerber/BOM export package under quote is verified against its recorded sha256 before the request is built.",
                "The provider-facing quote-request package is written inside the platform's allowed roots and recorded as artifact evidence with its digest.",
            ],
            requestedOf: human,
            requestedBy: requester,
            grantsScope: GrantScope(capabilities: ["electronics.manufacturing.quote"]),
            grantsTTL: Self.defaultTTL
        ))
    }

    /// Authority for an agent to delete a governed project: delete over
    /// the electronics types for the TTL window. Deletion is a tombstone —
    /// history survives, but the objects leave the live world permanently
    /// and their identities are never reused. Raw KiCad files are not
    /// touched; only the governed mirror.
    public func requestProjectDeletionAuthority(
        requester: Principal,
        human: Principal,
        projectName: String,
        projectObjectID: WorldObjectID
    ) async -> ApprovalRequest {
        await ledger.submit(ApprovalRequest(
            title: "Delete electronics project “\(projectName)”",
            decision: "Allow \(requester.rawValue) to delete this project, its schematics, and its components (\(projectObjectID)) from the governed world for \(Int(Self.defaultTTL / 60)) minutes. Deleted identities are never reused.",
            supportingEvidence: [
                "Deletion tombstones the project, its schematics, and its components in one transaction.",
                "Change history survives for audit, but the objects cannot be resurrected under the same identity.",
            ],
            requestedOf: human,
            requestedBy: requester,
            grantsScope: GrantScope(
                kinds: [.delete],
                typeNames: ElectronicsSchema.allTypeNames
            ),
            grantsTTL: Self.defaultTTL
        ))
    }

/// Authority for an agent to transmit a quoted package to a
    /// fabricator: invoke `electronics.manufacturing.upload` for the TTL
    /// window (M2.4 upload path). Uploading publishes the board design to
    /// an external manufacturer — the quote package is digest-verified at
    /// invocation and the transmission lands as sha256-pinned evidence.
    public func requestManufacturingUploadAuthority(
        requester: Principal,
        human: Principal,
        projectName: String,
        provider: String
    ) async -> ApprovalRequest {
        await ledger.submit(ApprovalRequest(
            title: "Upload quoted package for \(projectName) to \(provider)",
            decision: "Allow \(requester.rawValue) to transmit the quoted manufacturing package for \(projectName) to \(provider) (capability electronics.manufacturing.upload) for \(Int(Self.defaultTTL / 60)) minutes.",
            supportingEvidence: [
                "The quote package under transmission is verified against its recorded sha256 before the upload manifest is built.",
                "The fabricator-facing transmission record is written inside the platform's allowed roots and recorded as artifact evidence with its digest.",
            ],
            requestedOf: human,
            requestedBy: requester,
            grantsScope: GrantScope(capabilities: ["electronics.manufacturing.upload"]),
            grantsTTL: Self.defaultTTL
        ))
    }

    /// Authority for an agent to run an external compliance/provider
    /// check: invoke `electronics.compliance.check` for the TTL window
    /// (M2.4 external provider checks). The check crosses the system
    /// boundary with design data; when a package is under review it is
    /// digest-verified and the record lands as sha256 evidence.
    public func requestComplianceCheckAuthority(
        requester: Principal,
        human: Principal,
        projectName: String,
        provider: String,
        checkType: String
    ) async -> ApprovalRequest {
        await ledger.submit(ApprovalRequest(
            title: "Run \(checkType) compliance check on \(projectName)",
            decision: "Allow \(requester.rawValue) to request \(checkType) checks from \(provider) for \(projectName) (capability electronics.compliance.check) for \(Int(Self.defaultTTL / 60)) minutes.",
            supportingEvidence: [
                "The compliance request crosses the system boundary with project data; any package under review is digest-verified before the record is built.",
                "The provider-facing check record is written inside the platform's allowed roots and recorded as artifact evidence with its digest.",
            ],
            requestedOf: human,
            requestedBy: requester,
            grantsScope: GrantScope(capabilities: ["electronics.compliance.check"]),
            grantsTTL: Self.defaultTTL
        ))
    }

    /// Records the human's decision on a request created by this flow.
    public func decide(
        _ requestID: UUID,
        as approver: Principal,
        approved: Bool,
        note: String? = nil
    ) async throws {
        _ = try await ledger.decide(
            requestID,
            as: approver,
            approved: approved,
            note: note
        )
    }

    /// Mints the authority an approved request confers onto the platform
    /// policy. Rejected or pending requests issue nothing.
    @discardableResult
    public func mintAuthority(
        for requestID: UUID,
        on policy: Obdurate
    ) async throws -> AuthorityGrant {
        try await ledger.issueGrantedAuthority(for: requestID, on: policy)
    }

    /// Undecided, unexpired requests, oldest first.
    public func pending() async -> [ApprovalRequest] {
        await ledger.pending()
    }
}
