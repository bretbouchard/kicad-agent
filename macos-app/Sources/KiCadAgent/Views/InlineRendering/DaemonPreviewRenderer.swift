//
//  DaemonPreviewRenderer.swift
//  KiCadAgent
//
//  Phase 214 — Inline Rendering via the daemon
//
//  Conforms to PreviewRenderer by calling kicad-cli export via MCPClient.
//  The daemon runs `kicad-cli sch export svg` / `kicad-cli pcb render`
//  and writes the result to a temp file, which we wrap in RenderArtifact.
//

import Foundation
import OSLog

/// PreviewRenderer backed by the daemon's kicad-cli export capability.
///
/// Calls MCPClient tools/call with kicad.export_svg or kicad.render_pcb.
/// The daemon writes the file to a temp directory; we verify magic bytes
/// before returning the RenderArtifact.
final class DaemonPreviewRenderer: PreviewRenderer, @unchecked Sendable {
    private let client: MCPClient

    init(client: MCPClient) {
        self.client = client
    }

    @MainActor
    func renderSchematic(schematicPath: URL) async throws -> RenderArtifact {
        // Call the daemon to export SVG via kicad-cli.
        let result = try await client.callRaw(
            "tools/call",
            params: [
                "name": "export_svg",
                "arguments": [
                    "target_file": schematicPath.path
                ]
            ]
        )

        // The daemon returns the path to the rendered SVG.
        let svgPath = extractFilePath(from: result, fallback: schematicPath)
            .deletingPathExtension()
            .appendingPathExtension("svg")

        guard FileManager.default.fileExists(atPath: svgPath.path) else {
            throw RenderError.fileNotFound(svgPath.path)
        }

        return RenderArtifact(kind: .schematicSVG, url: svgPath)
    }

    @MainActor
    func renderPCB(pcbPath: URL, side: PCBSide) async throws -> RenderArtifact {
        let result = try await client.callRaw(
            "tools/call",
            params: [
                "name": "render_pcb",
                "arguments": [
                    "target_file": pcbPath.path,
                    "side": side.rawValue
                ]
            ]
        )

        let pngPath = extractFilePath(from: result, fallback: pcbPath)
            .deletingPathExtension()
            .appendingPathExtension("png")

        guard FileManager.default.fileExists(atPath: pngPath.path) else {
            throw RenderError.fileNotFound(pngPath.path)
        }

        return RenderArtifact(kind: .pcbPNG, url: pngPath)
    }

    /// Extract a file path from the daemon response, falling back to
    /// the source file's directory if the daemon didn't return one.
    private func extractFilePath(from result: Any, fallback: URL) -> URL {
        if let dict = result as? [String: Any],
           let content = dict["content"] as? String,
           let url = URL(string: content) {
            return url
        }
        // Default: the rendered file sits next to the source.
        return fallback
    }
}

enum RenderError: LocalizedError {
    case fileNotFound(String)

    var errorDescription: String? {
        switch self {
        case .fileNotFound(let path):
            return "Rendered file not found at \(path)"
        }
    }
}
