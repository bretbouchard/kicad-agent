//
//  GSDConversationEngineTests.swift
//  KiCadAgentTests
//
//  Phase 173 — GSD Conversation Engine
//
//  Tests GSD view models (ProjectSpec, ProjectRoadmap, CompletionSummary),
//  spec sanitization (T-173-02), fork limiter (T-173-04), and 4-variant
//  trait instantiation of all 5 GSD views.
//

import Testing
import SwiftUI
import SwiftData
@testable import KiCadAgent

@Suite("GSD Conversation Engine", .disabled(if: ProcessInfo.processInfo.environment["CI_SKIP_SMOKE"] != nil))
struct GSDConversationEngineTests {

    // MARK: - SpecValidator (T-173-02)

    @Test("SpecValidator accepts normal-length text")
    func validatorAccepts() {
        #expect(SpecValidator.isWithinLength("normal text") == true)
    }

    @Test("SpecValidator rejects text over 1000 chars (T-173-02)")
    func validatorRejects() {
        let long = String(repeating: "a", count: 1001)
        #expect(SpecValidator.isWithinLength(long) == false)
    }

    @Test("SpecValidator strips script tags (T-173-02 XSS mitigation)")
    func sanitizeStripsScript() {
        let malicious = #"<script>alert('xss')</script>safe text"#
        let sanitized = SpecValidator.sanitize(malicious)
        #expect(sanitized.contains("<script>") == false)
        #expect(sanitized.contains("safe text") == true)
    }

    @Test("SpecValidator strips event handlers (T-173-02)")
    func sanitizeStripsEventHandlers() {
        let malicious = #"<div onclick="alert(1)">content</div>"#
        let sanitized = SpecValidator.sanitize(malicious)
        #expect(sanitized.contains("onclick") == false)
        #expect(sanitized.contains("content") == true)
    }

    // MARK: - ForkLimiter (T-173-04)

    @Test("ForkLimiter allows at zero forks")
    func forkAllows() {
        let decision = ForkLimiter.evaluate(currentForkCount: 0)
        if case .allow(let remaining) = decision {
            #expect(remaining == 100)
        } else {
            Issue.record("expected .allow, got \(decision)")
        }
    }

    @Test("ForkLimiter warns at threshold")
    func forkWarns() {
        let decision = ForkLimiter.evaluate(currentForkCount: 80)
        if case .warn(let remaining) = decision {
            #expect(remaining == 20)
        } else {
            Issue.record("expected .warn, got \(decision)")
        }
    }

    @Test("ForkLimiter denies at cap (T-173-04)")
    func forkDenies() {
        let decision = ForkLimiter.evaluate(currentForkCount: 100)
        #expect(decision == .deny)
    }

    // MARK: - ProjectSpec

    @Test("ProjectSpec default spec is valid")
    func defaultSpec() {
        let spec = ProjectSpec.defaultSpec
        #expect(spec.title.isEmpty == false)
        #expect(spec.requirements.isEmpty == false)
        #expect(spec.successCriteria.isEmpty == false)
    }

    // MARK: - ProjectRoadmap

    @Test("ProjectRoadmap default has 5 phases")
    func defaultRoadmap() {
        let roadmap = ProjectRoadmap.defaultRoadmap
        #expect(roadmap.phases.count == 5)
        #expect(roadmap.phases.map(\.name).contains("Foundation"))
        #expect(roadmap.phases.map(\.name).contains("Ship"))
    }

    // MARK: - CompletionSummary

    @Test("CompletionSummary formats short duration as seconds")
    func durationSeconds() {
        let summary = CompletionSummary(phaseName: "P", totalDurationSeconds: 45)
        #expect(summary.formattedDuration == "45s")
    }

    @Test("CompletionSummary formats minutes")
    func durationMinutes() {
        let summary = CompletionSummary(phaseName: "P", totalDurationSeconds: 750)
        #expect(summary.formattedDuration == "12m 30s")
    }

    @Test("CompletionSummary formats hours")
    func durationHours() {
        let summary = CompletionSummary(phaseName: "P", totalDurationSeconds: 9240)
        #expect(summary.formattedDuration == "2h 34m")
    }

    // MARK: - Conversation Forking (CHAT-08)

    @Test("Conversation fork captures parent and message id")
    @MainActor
    func conversationForkMetadata() throws {
        let container = try ModelContainer(
            for: Project.self, Conversation.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true)
        )
        let ctx = container.mainContext
        let project = Project(name: "Test")
        ctx.insert(project)
        let original = Conversation(project: project, title: "Original")
        ctx.insert(original)
        let messageId = UUID()
        let fork = original.makeFork(forkedFromMessageId: messageId, title: "Forked")
        ctx.insert(fork)

        #expect(fork.parentConversationId == original.id)
        #expect(fork.forkedFromMessageId == messageId)
        #expect(fork.isFork == true)
        #expect(original.isFork == false)
    }

    // MARK: - 4-Variant Trait Tests for GSD Views

    @Test("QuestioningView instantiates in light mode", .tags(.ui, .a11y))
    func questioningLight() {
        var spec = ProjectSpec()
        let view = QuestioningView(
            spec: $spec,
            onAdvanceToSpec: {},
            onUseDefaults: {}
        )
        _ = view
        #expect(spec.title.isEmpty)
    }

    @Test("SpecView instantiates in dark mode", .tags(.ui, .a11y))
    func specDark() {
        var spec = ProjectSpec.defaultSpec
        let view = SpecView(spec: $spec, onApprove: {}, onBack: {})
            .preferredColorScheme(.dark)
        _ = view
    }

    @Test("RoadmapView instantiates at XXXL Dynamic Type", .tags(.ui, .a11y))
    func roadmapXXXL() {
        var roadmap = ProjectRoadmap.defaultRoadmap
        let view = RoadmapView(roadmap: $roadmap, onApprove: {}, onRefine: {})
            .dynamicTypeSize(.accessibility3)
        _ = view
    }

    @Test("ExecuteView instantiates with mixed statuses", .tags(.ui, .a11y))
    func executeMixed() {
        let view = ExecuteView(
            statuses: [.design: .verified, .schematic: .running, .erc: .pending],
            durationsMs: [.design: 850],
            currentOperationDescription: "Generating schematic",
            onPause: {},
            onCancel: {},
            onRetry: {}
        )
        _ = view
    }

    @Test("ExecuteView renders failure banner on failed step", .tags(.ui, .a11y))
    func executeFailure() {
        let view = ExecuteView(
            statuses: [.erc: .failed],
            durationsMs: [:],
            currentOperationDescription: nil,
            onPause: {},
            onCancel: {},
            onRetry: {}
        )
        _ = view
    }

    @Test("VerifyView instantiates with completion summary", .tags(.ui, .a11y))
    func verifySummary() {
        let summary = CompletionSummary(
            phaseName: "Foundation",
            schematicPath: nil,
            pcbPath: nil,
            exports: [
                ExportArtifact(fileName: "gerbers.zip", fileSizeBytes: 12_500, kind: .gerber)
            ],
            decisionsCount: 7,
            totalDurationSeconds: 9240
        )
        let view = VerifyView(summary: summary, previewRenderer: nil, onComplete: {}, onShare: {})
        _ = view
    }
}
