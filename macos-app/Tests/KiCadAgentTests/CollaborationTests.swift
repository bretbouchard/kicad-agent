//
//  CollaborationTests.swift
//  KiCadAgentTests
//
//  Phase 186 + 187 + 188 + 189 + 190 — Track G Collaboration
//
//  Tests ProjectBranch model, GroupActivitiesManager (4-participant cap),
//  CKShareInvitation, CollaborationActivityFeed, KicadAgentDocument.
//
//  Note: Phase 187.1 ships physical two-device migration test (recognized
//  blocker). Phase 188.1 ships real CloudKit container integration test.
//

import Testing
import Foundation
import SwiftData
@testable import KiCadAgent

@Suite("Collaboration Track G", .disabled(if: ProcessInfo.processInfo.environment["CI_SKIP_SMOKE"] != nil))
struct CollaborationTests {

    // MARK: - ProjectBranch (Phase 186)

    @Test("BranchType has five cases")
    func branchTypeCases() {
        #expect(BranchType.allCases.count == 5)
        #expect(BranchType.allCases.contains(.fork))
        #expect(BranchType.allCases.contains(.rollback))
    }

    @Test("BranchOutcome has four cases")
    func branchOutcomeCases() {
        #expect(BranchOutcome.allCases.count == 4)
    }

    @Test("BranchType label is human-readable")
    func branchTypeLabels() {
        #expect(BranchType.fork.label == "Fork")
        #expect(BranchType.falseStart.label == "False Start")
        #expect(BranchType.continuation.label == "Continuation")
    }

    @Test("ProjectBranch persists with parent linkage", .tags(.collaboration))
    @MainActor
    func projectBranchPersist() throws {
        let container = try makeContainer()
        let ctx = container.mainContext
        let project = Project(name: "T")
        ctx.insert(project)
        let root = ProjectBranch(project: project, branchType: .continuation, label: "Main")
        ctx.insert(root)
        let child = ProjectBranch(project: project, branchType: .fork, parentBranchId: root.id, label: "Alt 1")
        ctx.insert(child)
        try ctx.save()

        let fetched = try ctx.fetch(FetchDescriptor<ProjectBranch>())
        #expect(fetched.count == 2)
        #expect(fetched.first(where: { $0.label == "Alt 1" })?.parentBranchId == root.id)
    }

    @Test("ProjectBranch outcome round-trips")
    @MainActor
    func branchOutcomeRoundTrip() throws {
        let container = try makeContainer()
        let ctx = container.mainContext
        let project = Project(name: "T")
        ctx.insert(project)
        let branch = ProjectBranch(
            project: project,
            branchType: .exploration,
            label: "Side Quest",
            outcome: .abandoned
        )
        ctx.insert(branch)
        try ctx.save()

        let fetched = try ctx.fetch(FetchDescriptor<ProjectBranch>()).first
        #expect(fetched?.outcome == .abandoned)
    }

    // MARK: - GroupActivitiesManager (Phase 187)

    @Test("GroupActivitiesManager starts idle", .tags(.collaboration))
    @MainActor
    func groupActivitiesIdle() {
        let manager = GroupActivitiesManager()
        #expect(manager.sessionState == .idle)
        #expect(manager.participants.isEmpty)
    }

    @Test("GroupActivitiesManager enforces 4-participant cap (LIVE-01)", .tags(.collaboration))
    @MainActor
    func participantCap() {
        let manager = GroupActivitiesManager()
        for i in 0..<4 {
            let p = Participant(id: UUID(), displayName: "P\(i)", isLocal: false)
            #expect(manager.addParticipant(p) == true)
        }
        #expect(manager.atParticipantCap == true)

        let overflow = Participant(id: UUID(), displayName: "P5", isLocal: false)
        #expect(manager.addParticipant(overflow) == false)
        #expect(manager.participants.count == 4)
    }

    @Test("GroupActivitiesManager removes participants", .tags(.collaboration))
    @MainActor
    func participantRemove() {
        let manager = GroupActivitiesManager()
        let p1 = Participant(id: UUID(), displayName: "A", isLocal: false)
        let p2 = Participant(id: UUID(), displayName: "B", isLocal: false)
        _ = manager.addParticipant(p1)
        _ = manager.addParticipant(p2)
        manager.removeParticipant(id: p1.id)
        #expect(manager.participants.count == 1)
        #expect(manager.participants.first?.displayName == "B")
    }

    @Test("Participant.local returns local-flagged participant")
    func participantLocal() {
        let local = Participant.local()
        #expect(local.isLocal == true)
        #expect(local.displayName == "You")
    }

    // MARK: - CKShareInvitation (Phase 188)

    @Test("CKShareInvitation starts unshared", .tags(.collaboration))
    @MainActor
    func ckShareIdle() {
        let invitation = CKShareInvitation()
        #expect(invitation.isShared == false)
    }

    @Test("CKShareInvitation revokes cleanly", .tags(.collaboration))
    @MainActor
    func ckShareRevoke() {
        let invitation = CKShareInvitation()
        invitation.revoke()
        #expect(invitation.isShared == false)
    }

    @Test("InvitationPermission maps to CK permissions")
    func invitationPermissionMapping() {
        #expect(InvitationPermission.read.ckPermission == .readOnly)
        #expect(InvitationPermission.write.ckPermission == .readWrite)
    }

    @Test("InvitationPermission has three cases")
    func invitationPermissionCases() {
        #expect(InvitationPermission.allCases.count == 3)
    }

    // MARK: - CollaborationActivityFeed (Phase 189)

    @Test("CollaborationEvent kinds have icons + colors")
    func collaborationKinds() {
        #expect(CollaborationEventKind.decision.icon == "checkmark.seal")
        #expect(CollaborationEventKind.joined.icon == "arrow.down.to.line")
    }

    @Test("CollaborationActivityFeed instantiates with empty events", .tags(.ui, .a11y, .collaboration))
    @MainActor
    func activityFeedEmpty() {
        let view = CollaborationActivityFeed(
            events: [],
            participants: [Participant.local()],
            onManagePermissions: {}
        )
        _ = view
    }

    @Test("CollaborationActivityFeed instantiates with events", .tags(.ui, .a11y, .collaboration))
    @MainActor
    func activityFeedWithEvents() {
        let events = [
            CollaborationEvent(kind: .decision, participantName: "Alice", summary: "Approved spec"),
            CollaborationEvent(kind: .change, participantName: "Bob", summary: "Edited title"),
            CollaborationEvent(kind: .joined, participantName: "Carol", summary: "Joined session")
        ]
        let participants = [
            Participant(id: UUID(), displayName: "Alice", isLocal: false),
            Participant(id: UUID(), displayName: "Bob", isLocal: false),
            Participant.local()
        ]
        let view = CollaborationActivityFeed(
            events: events,
            participants: participants,
            onManagePermissions: {}
        )
        .preferredColorScheme(.dark)
        _ = view
    }

    // MARK: - KicadAgentDocument (Phase 190)

    @Test("KicadAgentDocument instantiates with defaults")
    func documentDefaults() {
        let doc = KicadAgentDocument()
        #expect(doc.manifestVersion == 1)
        #expect(doc.projectMetadata.name == "Untitled")
    }

    @Test("BundleManifest encodes + decodes")
    func manifestRoundTrip() throws {
        let manifest = BundleManifest(
            version: 1,
            project: ProjectMetadata(name: "Test", description: "Test project"),
            createdAt: .now,
            kicadAgentVersion: "6.0.0"
        )
        let data = try JSONEncoder().encode(manifest)
        let decoded = try JSONDecoder().decode(BundleManifest.self, from: data)
        #expect(decoded.version == 1)
        #expect(decoded.project.name == "Test")
    }

    @Test("KicadAgentDocumentError messages are descriptive")
    func documentErrors() {
        let err1 = KicadAgentDocumentError.invalidBundle("missing manifest")
        #expect(err1.localizedDescription.contains("missing manifest"))

        let err2 = KicadAgentDocumentError.unsupportedVersion(99)
        #expect(err2.localizedDescription.contains("99"))
    }

    // MARK: - ProjectGenealogyView (Phase 186 UI)

    @Test("ProjectGenealogyView instantiates with branches", .tags(.ui, .a11y, .collaboration))
    @MainActor
    func genealogyViewInstantiates() throws {
        let container = try makeContainer()
        let ctx = container.mainContext
        let project = Project(name: "Test")
        ctx.insert(project)
        let branches = [
            ProjectBranch(project: project, branchType: .continuation, label: "Main"),
            ProjectBranch(project: project, branchType: .fork, label: "Alt"),
            ProjectBranch(project: project, branchType: .falseStart, label: "Bad Idea", outcome: .abandoned)
        ]
        for b in branches { ctx.insert(b) }
        try ctx.save()

        let view = ProjectGenealogyView(branches: branches) { _ in }
            .dynamicTypeSize(.accessibility3)
        _ = view
    }

    // MARK: - Helpers

    @MainActor
    private func makeContainer() throws -> ModelContainer {
        try ModelContainer(
            for: Project.self, Conversation.self, Message.self, Decision.self,
                 ValueChange.self, ProjectSnapshot.self, ProjectBranch.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true)
        )
    }
}
