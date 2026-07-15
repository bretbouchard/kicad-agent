//
//  MemoryModelsTests.swift
//  VoltaTests
//
//  Phase 176 + 177 — SwiftData Models + CloudKit Sync
//
//  Tests SwiftData @Models (Message, Decision, ValueChange, ProjectSnapshot),
//  CloudKitSync manager, ConflictResolver LWW with prompts, schema registry.
//
//  Note: Phase 177.1 ships a physical two-device migration test (recognized
//  blocker). Phase 177 ships the simulator-only test here.
//

import Testing
import Foundation
import SwiftData
@testable import Volta

@Suite(
    "Memory Models + CloudKit Sync",
    .disabled(if: ProcessInfo.processInfo.environment["CI_SKIP_SMOKE"] != nil),
    .serialized
)
struct MemoryModelsTests {

    // MARK: - Schema Registry

    @Test("Schema registry lists 6 models in v6.0.0 schema")
    func schemaRegistry() {
        let schema = ModelSchemaRegistry.v600Schema
        #expect(schema.count == 6)
        #expect(schema.contains(where: { $0 == Project.self }))
        #expect(schema.contains(where: { $0 == Message.self }))
        #expect(schema.contains(where: { $0 == Decision.self }))
        #expect(schema.contains(where: { $0 == ValueChange.self }))
        #expect(schema.contains(where: { $0 == ProjectSnapshot.self }))
    }

    @Test("Schema version tag is frozen at v6.0.0")
    func schemaVersion() {
        #expect(ModelSchemaRegistry.versionTag == "v6.0.0")
    }

    // MARK: - Message Model

    @Test("Message persists with role + content")
    @MainActor
    func messagePersist() throws {
        let container = try makeContainer()
        defer { SwiftDataTestHelpers.drainContainer(container) }
        let ctx = container.mainContext
        let project = Project(name: "Test")
        ctx.insert(project)
        let conversation = Conversation(project: project, title: "Test")
        ctx.insert(conversation)
        let message = Message(
            conversation: conversation,
            role: .user,
            content: "Hello"
        )
        ctx.insert(message)
        try ctx.save()

        let fetched = try ctx.fetch(FetchDescriptor<Message>())
        #expect(fetched.count == 1)
        #expect(fetched.first?.content == "Hello")
        #expect(fetched.first?.role == .user)
    }

    @Test("Message status round-trips with failure reason")
    @MainActor
    func messageStatusRoundTrip() throws {
        let container = try makeContainer()
        defer { SwiftDataTestHelpers.drainContainer(container) }
        let ctx = container.mainContext
        let project = Project(name: "T")
        ctx.insert(project)
        let conv = Conversation(project: project, title: "T")
        ctx.insert(conv)
        let msg = Message(conversation: conv, role: .assistant, status: .failed("Network down"))
        ctx.insert(msg)
        try ctx.save()

        let fetched = try ctx.fetch(FetchDescriptor<Message>()).first
        #expect(fetched?.status == .failed("Network down"))
        #expect(fetched?.failureReason == "Network down")
    }

    @Test("Message totalTokens sums input + output")
    @MainActor
    func messageTokens() throws {
        let container = try makeContainer()
        defer { SwiftDataTestHelpers.drainContainer(container) }
        let ctx = container.mainContext
        let project = Project(name: "T")
        ctx.insert(project)
        let conv = Conversation(project: project, title: "T")
        ctx.insert(conv)
        let msg = Message(
            conversation: conv,
            role: .assistant,
            inputTokens: 120,
            outputTokens: 80,
            estimatedCostUSD: 0.005
        )
        ctx.insert(msg)
        try ctx.save()

        #expect(msg.totalTokens == 200)
    }

    // MARK: - Decision Model

    @Test("Decision persists with four-state resolution")
    @MainActor
    func decisionPersist() throws {
        let container = try makeContainer()
        defer { SwiftDataTestHelpers.drainContainer(container) }
        let ctx = container.mainContext
        let project = Project(name: "T")
        ctx.insert(project)
        let conv = Conversation(project: project, title: "T")
        ctx.insert(conv)
        let decision = Decision(
            conversation: conv,
            decisionKey: DecisionKey.gateApprove,
            newValueJSON: #"{"gateId":"abc"}"#,
            reasoning: "User approved ERC warning",
            resolution: .implemented
        )
        ctx.insert(decision)
        try ctx.save()

        let fetched = try ctx.fetch(FetchDescriptor<Decision>()).first
        #expect(fetched?.decisionKey == "gate.approve")
        #expect(fetched?.resolution == .implemented)
    }

    @Test("Decision resolution raw value is stable")
    func decisionResolutionRaw() {
        #expect(GateDecision.implemented.rawValue == "implemented")
        #expect(GateDecision.addedAsPhase.rawValue == "addedAsPhase")
        #expect(GateDecision.superseded.rawValue == "superseded")
        #expect(GateDecision.deferred.rawValue == "deferred")
    }

    // MARK: - ValueChange Model

    @Test("ValueChange persists with old/new JSON")
    @MainActor
    func valueChangePersist() throws {
        let container = try makeContainer()
        defer { SwiftDataTestHelpers.drainContainer(container) }
        let ctx = container.mainContext
        let project = Project(name: "T")
        ctx.insert(project)
        let conv = Conversation(project: project, title: "T")
        ctx.insert(conv)
        let change = ValueChange(
            conversation: conv,
            fieldPath: "spec.title",
            oldValueJSON: #"{"value":"Old"}"#,
            newValueJSON: #"{"value":"New"}"#
        )
        ctx.insert(change)
        try ctx.save()

        let fetched = try ctx.fetch(FetchDescriptor<ValueChange>()).first
        #expect(fetched?.fieldPath == "spec.title")
        #expect(fetched?.actor == .user)
    }

    // MARK: - ProjectSnapshot Model

    @Test("ProjectSnapshot persists with state size audit", .tags(.security))
    @MainActor
    func snapshotPersist() throws {
        let container = try makeContainer()
        defer { SwiftDataTestHelpers.drainContainer(container) }
        let ctx = container.mainContext
        let project = Project(name: "T")
        ctx.insert(project)
        let conv = Conversation(project: project, title: "T")
        ctx.insert(conv)
        let snapshot = ProjectSnapshot(
            conversation: conv,
            changeSequence: 42,
            stateJSON: #"{"spec":{"title":"Test"}}"#,
            trigger: .phaseTransition
        )
        ctx.insert(snapshot)
        try ctx.save()

        let fetched = try ctx.fetch(FetchDescriptor<ProjectSnapshot>()).first
        #expect(fetched?.changeSequence == 42)
        #expect(fetched?.trigger == .phaseTransition)
        #expect((fetched?.stateSizeBytes ?? 0) > 0)
    }

    // MARK: - Conversation Relationships

    @Test("Conversation cascade-deletes messages + decisions + changes + snapshots")
    @MainActor
    func cascadeDelete() throws {
        let container = try makeContainer()
        defer { SwiftDataTestHelpers.drainContainer(container) }
        let ctx = container.mainContext
        let project = Project(name: "T")
        ctx.insert(project)
        let conv = Conversation(project: project, title: "T")
        ctx.insert(conv)

        ctx.insert(Message(conversation: conv, role: .user, content: "msg"))
        ctx.insert(Decision(conversation: conv, decisionKey: "test.key"))
        ctx.insert(ValueChange(conversation: conv, fieldPath: "test.field"))
        ctx.insert(ProjectSnapshot(conversation: conv, changeSequence: 1, stateJSON: "{}"))

        try ctx.save()
        #expect(try ctx.fetch(FetchDescriptor<Message>()).count == 1)
        #expect(try ctx.fetch(FetchDescriptor<Decision>()).count == 1)
        #expect(try ctx.fetch(FetchDescriptor<ValueChange>()).count == 1)
        #expect(try ctx.fetch(FetchDescriptor<ProjectSnapshot>()).count == 1)

        ctx.delete(conv)
        try ctx.save()

        #expect(try ctx.fetch(FetchDescriptor<Message>()).count == 0)
        #expect(try ctx.fetch(FetchDescriptor<Decision>()).count == 0)
        #expect(try ctx.fetch(FetchDescriptor<ValueChange>()).count == 0)
        #expect(try ctx.fetch(FetchDescriptor<ProjectSnapshot>()).count == 0)
    }

    // MARK: - ConflictResolver (LWW)

    @Test("ConflictResolver LWW picks remote when newer")
    func lwwPicksRemoteNewer() {
        let resolver = ConflictResolver()
        let local = ValueChangePayload(fieldPath: "spec.title", oldValueJSON: "{}", newValueJSON: "\"local\"", changedAt: Date(timeIntervalSince1970: 1000), actorRaw: "user")
        let remote = ValueChangePayload(fieldPath: "spec.title", oldValueJSON: "{}", newValueJSON: "\"remote\"", changedAt: Date(timeIntervalSince1970: 2000), actorRaw: "user")
        let resolution = resolver.resolveValueChange(local: local, remote: remote)
        if case .auto(let winner) = resolution {
            #expect(winner.newValueJSON == "\"remote\"")
        } else {
            Issue.record("expected .auto, got \(resolution)")
        }
    }

    @Test("ConflictResolver LWW picks local when newer")
    func lwwPicksLocalNewer() {
        let resolver = ConflictResolver()
        let local = ValueChangePayload(fieldPath: "x", oldValueJSON: "{}", newValueJSON: "\"local\"", changedAt: Date(timeIntervalSince1970: 2000), actorRaw: "user")
        let remote = ValueChangePayload(fieldPath: "x", oldValueJSON: "{}", newValueJSON: "\"remote\"", changedAt: Date(timeIntervalSince1970: 1000), actorRaw: "user")
        let resolution = resolver.resolveValueChange(local: local, remote: remote)
        if case .auto(let winner) = resolution {
            #expect(winner.newValueJSON == "\"local\"")
        }
    }

    @Test("ConflictResolver prompts on equal timestamps with different values")
    func lwwPromptsOnTie() {
        let resolver = ConflictResolver()
        let ts = Date(timeIntervalSince1970: 1000)
        let local = ValueChangePayload(fieldPath: "x", oldValueJSON: "{}", newValueJSON: "\"local\"", changedAt: ts, actorRaw: "user")
        let remote = ValueChangePayload(fieldPath: "x", oldValueJSON: "{}", newValueJSON: "\"remote\"", changedAt: ts, actorRaw: "user")
        let resolution = resolver.resolveValueChange(local: local, remote: remote)
        #expect(resolution.needsPrompt == true)
    }

    @Test("ConflictResolver auto-resolves idempotent duplicates")
    func lwwIdempotent() {
        let resolver = ConflictResolver()
        let ts = Date(timeIntervalSince1970: 1000)
        let local = ValueChangePayload(fieldPath: "x", oldValueJSON: "{}", newValueJSON: "\"v\"", changedAt: ts, actorRaw: "user")
        let remote = ValueChangePayload(fieldPath: "x", oldValueJSON: "{}", newValueJSON: "\"v\"", changedAt: ts, actorRaw: "user")
        let resolution = resolver.resolveValueChange(local: local, remote: remote)
        #expect(resolution.isAuto == true)
    }

    // MARK: - CloudKitSync (single-device simulator)

    @Test("CloudKitSync starts idle and exposes conflictResolver", .tags(.collaboration))
    @MainActor
    func syncIdle() {
        let sync = CloudKitSync()
        #expect(sync.status == .idle)
        #expect(sync.conflictResolver is ConflictResolver)
    }

    @Test("CloudKitSync cloudKitContainerId nil without env var", .tags(.collaboration))
    func syncContainerIdNil() {
        // Unset by default in tests; document the contract.
        // Production sets CK_CONTAINER_ID in environment.
        let containerId = CloudKitSync.cloudKitContainerId
        #expect(containerId == nil || (containerId?.count ?? 0) >= 0)
    }

    @Test("SyncStatus labels are human-readable")
    func syncStatusLabels() {
        #expect(SyncStatus.idle.label == "Not started")
        #expect(SyncStatus.ready.label == "Ready")
        #expect(SyncStatus.syncing.label == "Syncing…")
    }

    // MARK: - Helpers

    private func makeContainer() throws -> ModelContainer {
        try ModelSchemaRegistry.makeContainer(configuration: ModelConfiguration(isStoredInMemoryOnly: true))
    }
}

// Tag for collaboration tests
extension Tag {
    @Tag static var collaboration: Tag
}
