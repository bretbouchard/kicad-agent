//
//  MockPreviewRenderer.swift
//  KiCadAgent
//
//  Phase 172 — Inline Rendering
//
//  Test-only mock renderer that produces valid SVG/PNG bytes for the magic-byte
//  verifier. Used by snapshot tests and developer previews. Production wires
//  DaemonPreviewRenderer to MCPClient.call (Phase 175).
//

import Foundation

/// Mock renderer for tests and previews. Writes real bytes so MagicBytes
/// verification passes end-to-end.
///
/// ponytail: NOT a no-op. Writes real file content so the production code path
/// (verify magic bytes → display) is exercised. Anything less wouldn't catch
/// regressions in MagicBytes.verify.
final class MockPreviewRenderer: PreviewRenderer, @unchecked Sendable {
    /// Set this to throw on the next render call. Tests flip it to inject failures.
    var shouldFail: Bool = false

    func renderSchematic(schematicPath: URL) async throws -> RenderArtifact {
        if shouldFail { throw InlineRenderingError.renderFailed(reason: "mock failure") }
        let outURL = makeTempURL(extension: "svg")
        let svg = #"<?xml version="1.0" encoding="UTF-8"?><svg xmlns="http://www.w3.org/2000/svg" width="100" height="60"></svg>"#
        try svg.data(using: .utf8)?.write(to: outURL)
        return RenderArtifact(kind: .schematicSVG, url: outURL)
    }

    func renderPCB(pcbPath: URL, side: PCBSide) async throws -> RenderArtifact {
        if shouldFail { throw InlineRenderingError.renderFailed(reason: "mock failure") }
        let outURL = makeTempURL(extension: "png")
        // Real PNG header + minimal IHDR chunk so magic-byte verifier passes
        // and NSImage can decode a valid (empty) PNG.
        var bytes: [UInt8] = [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]
        // Minimal IHDR + IDAT + IEND
        bytes.append(contentsOf: [
            0x00, 0x00, 0x00, 0x0D,
            0x49, 0x48, 0x44, 0x52,
            0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
            0x08, 0x06, 0x00, 0x00, 0x00, 0x1F, 0x15, 0xC4,
            0x89,
            0x00, 0x00, 0x00, 0x0D,
            0x49, 0x44, 0x41, 0x54,
            0x78, 0x9C, 0x62, 0x00, 0x01, 0x00, 0x00, 0x05, 0x00, 0x01, 0x0D, 0x0A, 0x2D, 0xB4,
            0xFF, 0x00, 0x00, 0x00,
            0x49, 0x45, 0x4E, 0x44,
            0xAE, 0x42, 0x60, 0x82
        ])
        try Data(bytes).write(to: outURL)
        return RenderArtifact(kind: .pcbPNG, url: outURL)
    }

    private func makeTempURL(extension ext: String) -> URL {
        let tempDir = FileManager.default.temporaryDirectory
        return tempDir.appendingPathComponent("mock-\(UUID().uuidString).\(ext)")
    }
}
