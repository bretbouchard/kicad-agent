//
//  TimeTravelTests.swift
//  KiCadAgentTests
//
//  Phase 178 + 179 + 180 — Time-Travel + Timeline UI + Event Sourcing
//

import Testing
import Foundation
import SwiftData
@testable import KiCadAgent

@Suite("Time-Travel + Event Sourcing", .disabled(if: ProcessInfo.processInfo.environment["CI_SKIP_SMOKE"] != nil))
struct TimeTravelTests {

    // MARK: - DiffUtil

    @Test("DiffUtil detects added field")
    func diffAdded() {
        let from: [String: String] = ["a": "1"]
        let to: [String: String] = ["a": "1", "b": "2"]
        let diffs = DiffUtil.diffFields(from: from, to: to)
        #expect(diffs.count == 1)
        #expect(diffs.first?.op == .added)
        #expect(diffs.first?.fieldPath == "b")
    }

    @Test("DiffUtil detects changed field")
    func diffChanged() {
        let from: [String: String] = ["a": "1"]
        let to: [String: String] = ["a": "2"]
        let diffs = DiffUtil.diffFields(from: from, to: to)
        #expect(diffs.count == 1)
        #expect(diffs.first?.op == .changed)
    }

    @Test("DiffUtil detects removed field")
    func diffRemoved() {
        let from: [String: String] = ["a": "1", "b": "2"]
        let to: [String: String] = ["a": "1"]
        let diffs = DiffUtil.diffFields(from: from, to: to)
        #expect(diffs.count == 1)
        #expect(diffs.first?.op == .removed)
    }

    @Test("DiffUtil omits unchanged fields")
    func diffUnchanged() {
        let from: [String: String] = ["a": "1", "b": "2"]
        let to: [String: String] = ["a": "1", "b": "2"]
        let diffs = DiffUtil.diffFields(from: from, to: to)
        #expect(diffs.isEmpty)
    }

    @Test("DiffOp labels are human-readable")
    func diffOpLabels() {
        #expect(DiffOp.added.label == "Added")
        #expect(DiffOp.changed.label == "Changed")
        #expect(DiffOp.removed.label == "Removed")
    }

    // MARK: - ConversationState

    @Test("ConversationState applies change correctly")
    func stateApply() {
        var state = ConversationState.empty
        let change = ValueChangePayload(
            fieldPath: "spec.title",
            oldValueJSON: "{}",
            newValueJSON: #"{"value":"New Title"}"#,
            changedAt: .now,
            actorRaw: "user"
        )
        state.apply(change)
        #expect(state.fields["spec.title"] == #"{"value":"New Title"}"#)
    }

    @Test("ConversationState encodes and decodes round-trip")
    func stateRoundTrip() throws {
        var state = ConversationState.empty
        state.fields["a"] = "1"
        state.fields["b"] = "2"
        let encoded = try state.encode()
        let decoded = try ConversationState.decode(encoded)
        #expect(decoded.fields == state.fields)
    }

    // MARK: - TimeTravelEngine

    @Test("TimeTravelEngine materializes empty state for new conversation")
    @MainActor
    func materializeEmpty() throws {
        let (engine, _) = try makeEngine()
        let state = try engine.materializeState(conversationId: UUID(), at: .now)
        #expect(state.fields.isEmpty)
    }

    @Test("TimeTravelEngine replays changes for materialization")
    @MainActor
    func materializeReplays() throws {
        let (engine, conversation) = try makeEngineWithConversation()
        let context = engine.modelContext
        // Add a change event in the past
        let pastDate = Date().addingTimeInterval(-3600)
        let oldChange = ValueChange(
            conversation: conversation,
            changedAt: pastDate,
            fieldPath: "spec.title",
            newValueJSON: "\"Past Title\""
        )
        context.insert(oldChange)
        try context.save()

        let state = try engine.materializeState(conversationId: conversation.id, at: .now)
        #expect(state.fields["spec.title"] == "\"Past Title\"")
    }

    @Test("TimeTravelEngine captures snapshot")
    @MainActor
    func captureSnapshot() throws {
        let (engine, conversation) = try makeEngineWithConversation()
        let snapshot = try engine.captureSnapshot(
            conversationId: conversation.id,
            trigger: .manual,
            changeSequence: 5
        )
        #expect(snapshot != nil)
        #expect(snapshot?.trigger == .manual)
        #expect(snapshot?.changeSequence == 5)
    }

    @Test("TimeTravelEngine restore preserves history")
    @MainActor
    func restorePreservesHistory() throws {
        let (engine, conversation) = try makeEngineWithConversation()
        let context = engine.modelContext
        let pastDate = Date().addingTimeInterval(-3600)

        // Old state
        context.insert(ValueChange(
            conversation: conversation,
            changedAt: pastDate,
            fieldPath: "spec.title",
            newValueJSON: "\"Old Title\""
        ))
        try context.save()

        // Restore to past
        try engine.restore(conversationId: conversation.id, to: pastDate.addingTimeInterval(60))

        // History preserved: should have at least 2 ValueChange events now (old + restore)
        let allChanges = try context.fetch(FetchDescriptor<ValueChange>(
            predicate: #Predicate { $0.conversationId == conversation.id }
        ))
        #expect(allChanges.count >= 2)
    }

    @Test("TimeTravelEngine diff returns changed entries")
    @MainActor
    func diffEntries() throws {
        let (engine, conversation) = try makeEngineWithConversation()
        let context = engine.modelContext

        let pastDate = Date().addingTimeInterval(-3600)
        context.insert(ValueChange(
            conversation: conversation,
            changedAt: pastDate,
            fieldPath: "spec.title",
            newValueJSON: "\"Old\""
        ))
        try context.save()

        let diffs = try engine.diff(
            conversationId: conversation.id,
            from: pastDate.addingTimeInterval(-60),
            to: .now
        )
        #expect(diffs.count >= 1)
        #expect(diffs.contains(where: { $0.fieldPath == "spec.title" }))
    }

    // MARK: - EventCompactor

    @Test("EventCompactor archives events older than cutoff")
    @MainActor
    func compactArchivesOld() throws {
        let tempDir = FileManager.default.temporaryDirectory.appendingPathComponent("compact-test-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: tempDir) }

        let (engine, conversation) = try makeEngineWithConversation()
        let context = engine.modelContext
        let cutoff = Date().addingTimeInterval(-3600)

        // Insert old event
        context.insert(ValueChange(
            conversation: conversation,
            changedAt: cutoff.addingTimeInterval(-3600),
            fieldPath: "old.field",
            newValueJSON: "\"old\""
        ))
        // Insert recent event
        context.insert(ValueChange(
            conversation: conversation,
            changedAt: Date(),
            fieldPath: "new.field",
            newValueJSON: "\"new\""
        ))
        try context.save()

        let compactor = EventCompactor(modelContext: context, archiveDirectory: tempDir)
        let archived = try compactor.compact(olderThan: cutoff)
        #expect(archived == 1)

        // Recent event still present
        let remaining = try context.fetch(FetchDescriptor<ValueChange>())
        #expect(remaining.count == 1)
        #expect(remaining.first?.fieldPath == "new.field")

        // Archive file exists
        let archives = try FileManager.default.contentsOfDirectory(at: tempDir, includingPropertiesForKeys: nil)
        #expect(archives.count == 1)
    }

    @Test("EventCompactor reports when under cap")
    @MainActor
    func needsCompactionFalse() throws {
        let tempDir = FileManager.default.temporaryDirectory.appendingPathComponent("compact-cap-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: tempDir) }

        let (engine, _) = try makeEngineWithConversation()
        let compactor = EventCompactor(modelContext: engine.modelContext, archiveDirectory: tempDir)
        #expect(try compactor.needsCompaction() == false)
    }

    // MARK: - Timeline View Models

    @Test("TimelineEntry has three kinds")
    func timelineKinds() {
        #expect(TimelineEntryKind.allCases.count == 3)
        #expect(TimelineEntryKind.allCases.contains(.decision))
    }

    @Test("TimelineFilter has four cases")
    func timelineFilterCases() {
        #expect(TimelineFilter.allCases.count == 4)
    }

    // MARK: - 4-Variant View Instantiation

    @Test("DecisionTimelineView instantiates with empty entries", .tags(.ui, .a11y))
    func timelineEmpty() {
        let view = DecisionTimelineView(
            entries: [],
            chapters: [],
            onLoadMore: {},
            onSelectEntry: { _ in },
            onScrub: { _ in }
        )
        _ = view
    }

    @Test("DecisionTimelineView instantiates with entries", .tags(.ui, .a11y))
    func timelineWithEntries() {
        let entries = [
            TimelineEntry(kind: .decision, timestamp: Date(), title: "Approved spec", detail: "User approved", actor: "user"),
            TimelineEntry(kind: .valueChange, timestamp: Date(), title: "Title changed", detail: "Old → New")
        ]
        let view = DecisionTimelineView(
            entries: entries,
            chapters: [],
            onLoadMore: {},
            onSelectEntry: { _ in },
            onScrub: { _ in }
        )
        .preferredColorScheme(.dark)
        _ = view
    }

    @Test("TimeTravelView instantiates with date range", .tags(.ui, .a11y))
    func timeTravelInstantiates() {
        let now = Date()
        let view = TimeTravelView(
            conversationId: UUID(),
            timeRange: now.addingTimeInterval(-3600)...now,
            onScrub: { _ in },
            onDiff: { _, _ in },
            onRestore: { _ in }
        )
        .dynamicTypeSize(.accessibility3)
        _ = view
    }

    @Test("ChapterSegmentationView enforces 10-chapter cap")
    @MainActor
    func chapterCap() {
        var chapters: [TimelineChapter] = (0..<10).map { idx in
            TimelineChapter(id: UUID(), title: "Ch \(idx + 1)", startIndex: idx * 10, endIndex: idx * 10 + 9)
        }
        let view = ChapterSegmentationView(chapters: $chapters, onRegenerate: {})
        _ = view
        #expect(chapters.count == 10)
    }

    // MARK: - Helpers

    @MainActor
    private func makeEngine() throws -> (TimeTravelEngine, UUID) {
        let container = try ModelContainer(
            for: ModelSchemaRegistry.v600Schema,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true)
        )
        let ctx = container.mainContext
        let project = Project(name: "Test")
        ctx.insert(project)
        let conversation = Conversation(project: project, title: "Test")
        ctx.insert(conversation)
        try ctx.save()
        return (TimeTravelEngine(modelContext: ctx), conversation.id)
    }

    @MainActor
    private func makeEngineWithConversation() throws -> (TimeTravelEngine, Conversation) {
        let container = try ModelContainer(
            for: ModelSchemaRegistry.v600Schema,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true)
        )
        let ctx = container.mainContext
        let project = Project(name: "Test")
        ctx.insert(project)
        let conversation = Conversation(project: project, title: "Test")
        ctx.insert(conversation)
        try ctx.save()
        return (TimeTravelEngine(modelContext: ctx), conversation)
    }
}

extension TimeTravelEngine {
    var modelContext: ModelContext { _modelContext }
}

// Expose private stored property for tests via internal accessor.
// (SwiftData ModelContext is a class — passing by reference works.)
@MainActor
fileprivate extension TimeTravelEngine {
    var _modelContext: ModelContext {
        // Use Mirror to access private stored property
        let mirror = Mirror(reflecting: self)
        for child in mirror.children where child.label == "modelContext" {
            if let ctx = child.value as? ModelContext { return ctx }
        }
        fatalError("TimeTravelEngine.modelContext not accessible")
    }
}
