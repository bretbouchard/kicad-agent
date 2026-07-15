//
//  ConversationTests.swift
//  VoltaTests
//
//  Phase 161 — App Shell Foundation
//
//  Tests for the Conversation SwiftData model.
//  Uses swift-testing framework (TEST-01).
//

import Testing
import Foundation
import SwiftData
@testable import Volta

@Suite("Conversation Model", .serialized)
struct ConversationTests {

    @MainActor
    @Test("Conversation captures projectId and defaults")
    func defaults() throws {
        let container = try ModelContainer(
            for: Project.self, Conversation.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true)
        )
        defer { SwiftDataTestHelpers.drainContainer(container) }
        let ctx = container.mainContext
        let project = Project(name: "P1", projectDescription: "", createdAt: .now, lastModifiedAt: .now)
        ctx.insert(project)
        let convo = Conversation(project: project)
        ctx.insert(convo)

        #expect(convo.id != UUID(uuidString: "00000000-0000-0000-0000-000000000000"))
        #expect(convo.projectId == project.id)
        #expect(convo.title == "New Conversation")
        #expect(convo.startedAt <= .now)
        #expect(convo.lastActivityAt <= .now)
    }

    @MainActor
    @Test("touch() bumps lastActivityAt and cascades to project")
    func touchCascades() async throws {
        let container = try ModelContainer(
            for: Project.self, Conversation.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true)
        )
        defer { SwiftDataTestHelpers.drainContainer(container) }
        let ctx = container.mainContext
        let project = Project(name: "P1", projectDescription: "", createdAt: .distantPast, lastModifiedAt: .distantPast)
        ctx.insert(project)
        let convo = Conversation(project: project, startedAt: .distantPast, lastActivityAt: .distantPast)
        ctx.insert(convo)

        try? await Task.sleep(for: .milliseconds(10))
        convo.touch()

        #expect(convo.lastActivityAt > .distantPast)
        // Cascade: project's lastModifiedAt should also bump.
        #expect(project.lastModifiedAt > .distantPast)
    }

    @MainActor
    @Test("Conversation persists in SwiftData")
    func persist() throws {
        let container = try ModelContainer(
            for: Project.self, Conversation.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true)
        )
        defer { SwiftDataTestHelpers.drainContainer(container) }
        let ctx = container.mainContext
        let project = Project(name: "P1", projectDescription: "", createdAt: .now, lastModifiedAt: .now)
        ctx.insert(project)
        let convo = Conversation(project: project, title: "Persist me")
        ctx.insert(convo)
        try ctx.save()

        let fetched = try ctx.fetch(FetchDescriptor<Conversation>())
        #expect(fetched.count == 1)
        #expect(fetched.first?.title == "Persist me")
    }

    @MainActor
    @Test("Cascade delete removes conversations when project deleted")
    func cascadeDelete() throws {
        let container = try ModelContainer(
            for: Project.self, Conversation.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true)
        )
        defer { SwiftDataTestHelpers.drainContainer(container) }
        let ctx = container.mainContext
        let project = Project(name: "P1", projectDescription: "", createdAt: .now, lastModifiedAt: .now)
        ctx.insert(project)
        ctx.insert(Conversation(project: project))
        ctx.insert(Conversation(project: project))
        try ctx.save()

        #expect(try ctx.fetch(FetchDescriptor<Conversation>()).count == 2)

        ctx.delete(project)
        try ctx.save()

        #expect(try ctx.fetch(FetchDescriptor<Project>()).isEmpty)
        #expect(try ctx.fetch(FetchDescriptor<Conversation>()).isEmpty)
    }

    // Note: precondition-crash test for empty title is intentionally omitted —
    // see ProjectTests.swift for rationale.
}
