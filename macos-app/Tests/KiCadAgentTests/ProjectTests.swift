//
//  ProjectTests.swift
//  KiCadAgentTests
//
//  Phase 161 — App Shell Foundation
//
//  Tests for the Project SwiftData model.
//  Uses swift-testing framework (TEST-01).
//

import Testing
import Foundation
import SwiftData
@testable import KiCadAgent

@Suite("Project Model")
struct ProjectTests {

    // MARK: - Defaults

    @Test("Default initializer sets sane defaults")
    func defaultsAreSane() {
        let project = Project.newDefault()
        #expect(project.name == "Untitled Project")
        #expect(project.projectDescription.isEmpty)
        #expect(project.conversations.isEmpty)
        #expect(project.id != UUID(uuidString: "00000000-0000-0000-0000-000000000000"))
        #expect(project.createdAt <= .now)
        #expect(project.lastModifiedAt <= .now)
    }

    // MARK: - Identity

    @Test("Each Project gets a unique UUID")
    func uniqueIds() {
        let a = Project.newDefault()
        let b = Project.newDefault()
        #expect(a.id != b.id)
    }

    // MARK: - Mutation tracking

    @Test("touch() bumps lastModifiedAt")
    func touchBumpsTimestamp() async {
        let project = Project(name: "Test", createdAt: .distantPast, lastModifiedAt: .distantPast)
        // Wait a beat so .now is strictly greater.
        try? await Task.sleep(for: .milliseconds(10))
        project.touch()
        #expect(project.lastModifiedAt > .distantPast)
        // createdAt must remain unchanged.
        #expect(project.createdAt == .distantPast)
    }

    // MARK: - Validation
    // Note: precondition crash tests are not run in-process (swift-testing
    // requires `#expect(processExitsWith:)` which spawns a subprocess — heavy
    // for a Phase 161 smoke test). Validation is exercised by the UI guard
    // in `ProjectForm` (Phase 165). The precondition is the safety net.

    // MARK: - SwiftData round-trip

    @MainActor
    @Test("Project persists in SwiftData in-memory container")
    func swiftDataPersist() throws {
        let container = try ModelContainer(
            for: Project.self, Conversation.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true)
        )
        let ctx = container.mainContext
        let project = Project(name: "Persist Test", projectDescription: "", createdAt: .now, lastModifiedAt: .now)
        ctx.insert(project)
        try ctx.save()

        let fetched = try ctx.fetch(FetchDescriptor<Project>())
        #expect(fetched.count == 1)
        #expect(fetched.first?.name == "Persist Test")
    }

    // MARK: - Conversation relationship

    @MainActor
    @Test("Adding conversation links back via inverse relationship")
    func conversationInverse() throws {
        let container = try ModelContainer(
            for: Project.self, Conversation.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true)
        )
        let ctx = container.mainContext
        let project = Project(name: "Parent", projectDescription: "", createdAt: .now, lastModifiedAt: .now)
        ctx.insert(project)
        let convo = Conversation(project: project, title: "First chat")
        ctx.insert(convo)
        try ctx.save()

        #expect(project.conversations.count == 1)
        #expect(project.conversations.first?.id == convo.id)
        #expect(convo.project?.id == project.id)
    }
}
