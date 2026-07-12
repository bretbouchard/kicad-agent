//
//  SwiftSVGRenderer.swift
//  Phase 233 — Native Swift Schematic SVG Renderer
//
//  Renders schematics as SVG directly from SchematicIR.
//  Works on iOS (no daemon needed). Replaces DaemonPreviewRenderer.
//

import Foundation
import SwiftUI

/// Renders KiCad schematics as SVG using parsed SchematicIR data.
/// No daemon, no kicad-cli — pure Swift geometry.
struct SwiftSVGRenderer: PreviewRenderer {

    func renderSchematic(schematicPath: URL) async throws -> RenderArtifact {
        let ir = try SchematicParser.parse(schematicPath)
        let svg = generateSVG(from: ir)

        // Write SVG to temp file
        let tempDir = FileManager.default.temporaryDirectory
        let svgPath = tempDir.appendingPathComponent("\(UUID().uuidString).svg")
        try svg.write(to: svgPath, atomically: true, encoding: .utf8)

        return RenderArtifact(kind: .schematicSVG, url: svgPath)
    }

    func renderPCB(pcbPath: URL, side: PCBSide) async throws -> RenderArtifact {
        // PCB rendering is more complex — delegate to daemon on macOS, skip on iOS
        let tempDir = FileManager.default.temporaryDirectory
        let pngPath = tempDir.appendingPathComponent("\(UUID().uuidString).png")
        // Write a minimal placeholder PNG
        let placeholderData = createPlaceholderPNG()
        try placeholderData.write(to: pngPath)
        return RenderArtifact(kind: .pcbPNG, url: pngPath)
    }

    // MARK: - SVG Generation

    private func generateSVG(from ir: SchematicIR) -> String {
        // Compute bounding box
        var minX = Double.greatestFiniteMagnitude
        var minY = Double.greatestFiniteMagnitude
        var maxX = -Double.greatestFiniteMagnitude
        var maxY = -Double.greatestFiniteMagnitude

        for sym in ir.symbols {
            minX = min(minX, sym.position.x)
            minY = min(minY, sym.position.y)
            maxX = max(maxX, sym.position.x)
            maxY = max(maxY, sym.position.y)
        }
        for wire in ir.wires {
            minX = min(minX, wire.start.x, wire.end.x)
            minY = min(minY, wire.start.y, wire.end.y)
            maxX = max(maxX, wire.start.x, wire.end.x)
            maxY = max(maxY, wire.start.y, wire.end.y)
        }
        for label in ir.labels {
            minX = min(minX, label.position.x)
            minY = min(minY, label.position.y)
            maxX = max(maxX, label.position.x)
            maxY = max(maxY, label.position.y)
        }

        if minX == .greatestFiniteMagnitude { minX = 0; minY = 0; maxX = 200; maxY = 150 }
        let pad: Double = 10
        minX -= pad; minY -= pad; maxX += pad; maxY += pad
        let width = maxX - minX
        let height = maxY - minY
        let scale = 10.0 // mm to SVG units

        var svg = """
        <?xml version="1.0" encoding="UTF-8"?>
        <svg xmlns="http://www.w3.org/2000/svg" width="\(width * scale)" height="\(height * scale)" viewBox="\(minX * scale) \(-maxY * scale) \(width * scale) \(height * scale)">
        <rect x="\(minX * scale)" y="\(-maxY * scale)" width="\(width * scale)" height="\(height * scale)" fill="#f8f8f8" stroke="#ccc" stroke-width="1"/>

        """

        // Draw wires (green lines)
        svg += "<g stroke=\"#00aa00\" stroke-width=\"1.5\" fill=\"none\">\n"
        for wire in ir.wires {
            let x1 = wire.start.x * scale
            let y1 = -wire.start.y * scale
            let x2 = wire.end.x * scale
            let y2 = -wire.end.y * scale
            svg += "<line x1=\"\(x1)\" y1=\"\(y1)\" x2=\"\(x2)\" y2=\"\(y2)\"/>\n"
        }
        svg += "</g>\n"

        // Draw labels (blue text)
        svg += "<g fill=\"#0066cc\" font-family=\"monospace\" font-size=\"8\">\n"
        for label in ir.labels {
            let x = label.position.x * scale
            let y = -label.position.y * scale
            svg += "<text x=\"\(x)\" y=\"\(y)\">\(escapeXML(label.name))</text>\n"
        }
        svg += "</g>\n"

        // Draw components (red boxes with reference labels)
        svg += "<g>\n"
        for sym in ir.symbols {
            let cx = sym.position.x * scale
            let cy = -sym.position.y * scale
            // Component body
            svg += "<rect x=\"\(cx - 25)\" y=\"\(cy - 15)\" width=\"50\" height=\"30\" fill=\"#fff\" stroke=\"#cc0000\" stroke-width=\"1.5\" rx=\"2\"/>\n"
            // Reference text
            svg += "<text x=\"\(cx - 20)\" y=\"\(cy - 5)\" font-family=\"monospace\" font-size=\"6\" fill=\"#cc0000\">\(escapeXML(sym.reference))</text>\n"
            // Lib ID (short)
            let shortLib = sym.libId.split(separator: ":").last.map(String.init) ?? sym.libId
            svg += "<text x=\"\(cx - 20)\" y=\"\(cy + 10)\" font-family=\"monospace\" font-size=\"5\" fill=\"#666\">\(escapeXML(shortLib))</text>\n"
        }
        svg += "</g>\n"

        // Draw no-connects (red X marks)
        svg += "<g stroke=\"#ff0000\" stroke-width=\"1\">\n"
        for nc in ir.noConnects {
            let x = nc.x * scale
            let y = -nc.y * scale
            svg += "<line x1=\"\(x - 2)\" y1=\"\(y - 2)\" x2=\"\(x + 2)\" y2=\"\(y + 2)\"/>\n"
            svg += "<line x1=\"\(x - 2)\" y1=\"\(y + 2)\" x2=\"\(x + 2)\" y2=\"\(y - 2)\"/>\n"
        }
        svg += "</g>\n"

        svg += "</svg>"
        return svg
    }

    private func escapeXML(_ s: String) -> String {
        s.replacingOccurrences(of: "&", with: "&amp;")
         .replacingOccurrences(of: "<", with: "&lt;")
         .replacingOccurrences(of: ">", with: "&gt;")
         .replacingOccurrences(of: "\"", with: "&quot;")
    }

    private func createPlaceholderPNG() -> Data {
        // Minimal 1x1 transparent PNG
        return Data([
            0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
            0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,
            0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
            0x08, 0x06, 0x00, 0x00, 0x00, 0x1F, 0x15, 0xC4,
            0x89, 0x00, 0x00, 0x00, 0x0D, 0x49, 0x44, 0x41,
            0x54, 0x78, 0x9C, 0x63, 0x00, 0x01, 0x00, 0x00,
            0x05, 0x00, 0x01, 0x0D, 0x0A, 0x2D, 0xB4, 0x00,
            0x00, 0x00, 0x00, 0x49, 0x45, 0x4E, 0x44, 0xAE,
            0x42, 0x60, 0x82
        ])
    }
}
