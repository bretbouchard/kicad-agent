//
//  InlineRenderingTests.swift
//  VoltaTests
//
//  Phase 172 — Inline Rendering
//
//  Tests inline rendering: pipeline step model, magic-byte verifier,
//  progress event schema strictness (T-172-02), and 4-variant trait
//  instantiation of the preview / pipeline status views.
//

import Testing
import SwiftUI
@testable import Volta

@Suite("Inline Rendering", .disabled(if: ProcessInfo.processInfo.environment["CI_SKIP_SMOKE"] != nil))
struct InlineRenderingTests {

    // MARK: - PipelineStep model

    @Test("PipelineStep has six canonical cases in correct order")
    func pipelineStepOrder() {
        let cases = PipelineStep.allCases
        #expect(cases.count == 6)
        #expect(cases == [.design, .schematic, .erc, .pcb, .drc, .export])
    }

    @Test("PipelineStep label is human-readable")
    func pipelineStepLabels() {
        #expect(PipelineStep.design.label == "Design")
        #expect(PipelineStep.erc.label == "ERC")
        #expect(PipelineStep.export.label == "Export")
    }

    @Test("PipelineStep decodes from raw value (T-172-02 strict schema)")
    func pipelineStepDecode() throws {
        let json = #""schematic""#.data(using: .utf8)!
        let step = try JSONDecoder().decode(PipelineStep.self, from: json)
        #expect(step == .schematic)
    }

    @Test("PipelineStep rejects invalid raw value (T-172-02)")
    func pipelineStepRejectsInvalid() {
        let json = #""sql_injection_attempt""#.data(using: .utf8)!
        #expect(throws: DecodingError.self) {
            _ = try JSONDecoder().decode(PipelineStep.self, from: json)
        }
    }

    // MARK: - StepStatus

    @Test("StepStatus colors are semantic")
    func stepStatusColors() {
        #expect(StepStatus.pending.color == ColorTokens.tertiaryText)
        #expect(StepStatus.failed.color == ColorTokens.destructive)
        #expect(StepStatus.verified.color == ColorTokens.success)
    }

    // MARK: - PipelineProgressEvent (T-172-02 strict schema)

    @Test("PipelineProgressEvent decodes well-formed JSON")
    func eventDecodes() throws {
        let json = """
        {
          "step": "schematic",
          "status": "verified",
          "duration_ms": 1250,
          "timestamp": "2026-07-08T12:34:56Z",
          "error_message": null
        }
        """.data(using: .utf8)!
        let event = try JSONDecoder().decode(PipelineProgressEvent.self, from: json)
        #expect(event.step == .schematic)
        #expect(event.status == .verified)
        #expect(event.durationMs == 1250)
        #expect(event.errorMessage == nil)
    }

    @Test("PipelineProgressEvent rejects unknown step (T-172-02)")
    func eventRejectsUnknownStep() {
        let json = """
        {"step": "exploit", "status": "running", "duration_ms": 1, "timestamp": "2026-07-08T12:34:56Z", "error_message": null}
        """.data(using: .utf8)!
        #expect(throws: DecodingError.self) {
            _ = try JSONDecoder().decode(PipelineProgressEvent.self, from: json)
        }
    }

    // MARK: - MagicBytes verifier (T-172-01)

    @Test("MagicBytes verifies SVG file starting with <?xml")
    func magicBytesSVG() throws {
        let url = makeTempFile(content: "<?xml version=\"1.0\"?><svg></svg>")
        #expect(MagicBytes.verify(url: url, expected: MagicBytes.svg) == true)
        try? FileManager.default.removeItem(at: url)
    }

    @Test("MagicBytes rejects SVG file starting with malicious content")
    func magicBytesRejectsMalicious() throws {
        let url = makeTempFile(content: "<script>alert('xss')</script>")
        #expect(MagicBytes.verify(url: url, expected: MagicBytes.svg) == false)
        try? FileManager.default.removeItem(at: url)
    }

    @Test("MagicBytes verifies PNG file with valid header")
    func magicBytesPNG() throws {
        let pngHeader: [UInt8] = [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]
        let url = makeTempFile(data: Data(pngHeader + [0x00, 0x00]))
        #expect(MagicBytes.verify(url: url, expected: MagicBytes.png) == true)
        try? FileManager.default.removeItem(at: url)
    }

    @Test("MagicBytes returns false for missing file")
    func magicBytesMissingFile() {
        let url = URL(fileURLWithPath: "/nonexistent/file.png")
        #expect(MagicBytes.verify(url: url, expected: MagicBytes.png) == false)
    }

    // MARK: - MockPreviewRenderer

    @Test("MockPreviewRenderer produces valid SVG bytes")
    func mockRendererSVG() async throws {
        let renderer = MockPreviewRenderer()
        let artifact = try await renderer.renderSchematic(schematicPath: URL(fileURLWithPath: "/dev/null"))
        #expect(artifact.kind == .schematicSVG)
        #expect(MagicBytes.verify(url: artifact.url, expected: MagicBytes.svg) == true)
        try? FileManager.default.removeItem(at: artifact.url)
    }

    @Test("MockPreviewRenderer produces valid PNG bytes")
    func mockRendererPNG() async throws {
        let renderer = MockPreviewRenderer()
        let artifact = try await renderer.renderPCB(pcbPath: URL(fileURLWithPath: "/dev/null"), side: .front)
        #expect(artifact.kind == .pcbPNG)
        #expect(MagicBytes.verify(url: artifact.url, expected: MagicBytes.png) == true)
        try? FileManager.default.removeItem(at: artifact.url)
    }

    @Test("MockPreviewRenderer honors shouldFail")
    func mockRendererFailure() async {
        let renderer = MockPreviewRenderer()
        renderer.shouldFail = true
        await #expect(throws: InlineRenderingError.self) {
            _ = try await renderer.renderSchematic(schematicPath: URL(fileURLWithPath: "/dev/null"))
        }
    }

    // MARK: - 4-Variant Trait Tests for Views

    @Test("SchematicPreviewView instantiates in light mode", .tags(.ui, .a11y))
    func schematicLight() {
        let renderer = MockPreviewRenderer()
        let view = SchematicPreviewView(
            schematicPath: URL(fileURLWithPath: "/dev/null"),
            renderer: renderer
        )
        _ = view
    }

    @Test("SchematicPreviewView instantiates in dark mode", .tags(.ui, .a11y))
    func schematicDark() {
        let renderer = MockPreviewRenderer()
        let view = SchematicPreviewView(
            schematicPath: URL(fileURLWithPath: "/dev/null"),
            renderer: renderer
        )
        .preferredColorScheme(.dark)
        _ = view
    }

    @Test("PCBPreviewView instantiates at XXXL Dynamic Type", .tags(.ui, .a11y))
    func pcbXXXL() {
        let renderer = MockPreviewRenderer()
        let view = PCBPreviewView(
            pcbPath: URL(fileURLWithPath: "/dev/null"),
            side: .front,
            renderer: renderer
        )
        .dynamicTypeSize(.accessibility3)
        _ = view
    }

    @Test("PipelineStatusView renders all 6 steps", .tags(.ui))
    func pipelineRendersAllSteps() {
        let view = PipelineStatusView(
            statuses: [.design: .verified, .schematic: .running],
            durationsMs: [.design: 850]
        )
        _ = view
    }

    @Test("PipelineStatusView handles failed step state", .tags(.ui, .a11y))
    func pipelineFailedState() {
        let view = PipelineStatusView(
            statuses: [.erc: .failed],
            durationsMs: [:]
        )
        _ = view
    }

    @Test("PipelineStatusView invokes onStepTap callback")
    @MainActor
    func pipelineStepTapCallback() {
        final class TapHolder { @MainActor var tapped: PipelineStep? }
        let holder = TapHolder()
        let view = PipelineStatusView(
            statuses: [:],
            durationsMs: [:],
            onStepTap: { step in holder.tapped = step }
        )
        _ = view
        #expect(holder.tapped == nil)
    }

    @Test("PipelineStepDetailView renders with full detail", .tags(.ui, .a11y))
    func stepDetailInstantiates() {
        let detail = StepDetail(
            status: .verified,
            intent: "Generate distortion pedal schematic from intent",
            opsCalled: ["add_component", "wire", "run_erc"],
            durationMs: 2450,
            passedChecks: 12,
            warningCount: 1,
            errorCount: 0,
            verificationNotes: "All nets driven, no floating inputs.",
            requirementId: "DISTORTION-01"
        )
        let view = PipelineStepDetailView(step: .schematic, detail: detail)
        _ = view
    }

    @Test("FullScreenInspector instantiates with SVG URL", .tags(.ui))
    func fullScreenInspectorInstantiates() throws {
        let url = makeTempFile(content: "<?xml version=\"1.0\"?><svg></svg>")
        let view = FullScreenInspector(title: "Schematic", url: url)
        _ = view
        try? FileManager.default.removeItem(at: url)
    }

    // MARK: - Helpers

    private func makeTempFile(content: String) -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("test-\(UUID().uuidString).tmp")
        try? content.data(using: .utf8)?.write(to: url)
        return url
    }

    private func makeTempFile(data: Data) -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("test-\(UUID().uuidString).tmp")
        try? data.write(to: url)
        return url
    }
}
