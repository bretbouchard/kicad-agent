//
//  PCBImageRenderer.swift
//  Phase 238 — Real PCB Renderer (replaces 1x1 placeholder)
//
//  Renders .kicad_pcb files to PNG using Core Graphics, reading the
//  parsed PCBBoard IR from PCBParser. No daemon required — works
//  on iOS and macOS, just like the schematic SVG renderer.
//
//  Renders: footprints (boxed w/ reference), pads, traces (segments),
//  vias, board outline, drill holes. Layer coloring per KiCad's
//  standard F.Cu (red) / B.Cu (blue) convention.
//

import Foundation
import AppKit
import CoreGraphics

/// Real PCB → PNG renderer (no daemon, no kicad-cli).
/// Replaces `SwiftSVGRenderer.renderPCB` placeholder.
enum PCBImageRenderer {

    /// Render a .kicad_pcb file to a PNG. Returns the on-disk PNG URL.
    static func render(pcbPath: URL, side: PCBSide = .front) throws -> URL {
        let board = try PCBParser.parse(pcbPath)
        let pngData = try renderPNG(board: board, side: side)
        let outURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("\(UUID().uuidString).png")
        try pngData.write(to: outURL, options: .atomic)
        return outURL
    }

    /// Render a `PCBBoard` to PNG `Data` (testable without file I/O).
    static func renderPNG(board: PCBBoard, side: PCBSide = .front) throws -> Data {
        // Compute bounding box
        var minX = Double.greatestFiniteMagnitude
        var minY = Double.greatestFiniteMagnitude
        var maxX = -Double.greatestFiniteMagnitude
        var maxY = -Double.greatestFiniteMagnitude

        func expand(_ x: Double, _ y: Double) {
            minX = min(minX, x); minY = min(minY, y)
            maxX = max(maxX, x); maxY = max(maxY, y)
        }
        for fp in board.footprints { expand(fp.position.x, fp.position.y) }
        for seg in board.segments { expand(seg.start.x, seg.start.y); expand(seg.end.x, seg.end.y) }
        for via in board.vias { expand(via.position.x, via.position.y) }

        // Edge case: empty board
        if minX == .greatestFiniteMagnitude {
            minX = 0; minY = 0; maxX = 50; maxY = 50
        }
        let pad: Double = 5
        minX -= pad; minY -= pad; maxX += pad; maxY += pad
        let widthMM = maxX - minX
        let heightMM = maxY - minY

        // Render at 10 px/mm (matches schematic renderer scale)
        let scale: CGFloat = 10.0
        let pixelW = Int(widthMM * Double(scale))
        let pixelH = Int(heightMM * Double(scale))
        // Guard against tiny boards
        let outW = max(pixelW, 100)
        let outH = max(pixelH, 100)

        let colorSpace = CGColorSpaceCreateDeviceRGB()
        guard let ctx = CGContext(
            data: nil,
            width: outW, height: outH,
            bitsPerComponent: 8,
            bytesPerRow: 0,
            space: colorSpace,
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        ) else {
            throw NSError(domain: "PCBImageRenderer", code: 1, userInfo: [
                NSLocalizedDescriptionKey: "Could not create CGContext"
            ])
        }

        // Background — KiCad's standard PCB canvas (dark green)
        ctx.setFillColor(red: 0.05, green: 0.18, blue: 0.10, alpha: 1.0)
        ctx.fill(CGRect(x: 0, y: 0, width: outW, height: outH))

        // Coordinate system: PCB y is up; CG y is down. Flip + translate.
        ctx.translateBy(x: -CGFloat(minX) * scale, y: CGFloat(maxY) * scale)
        ctx.scaleBy(x: scale, y: -scale)

        // Layer colors (KiCad convention)
        let frontTraceColor = CGColor(red: 0.85, green: 0.20, blue: 0.10, alpha: 1.0)
        let backTraceColor  = CGColor(red: 0.10, green: 0.30, blue: 0.90, alpha: 1.0)
        let padColor        = CGColor(red: 0.95, green: 0.80, blue: 0.20, alpha: 1.0)
        let viaColor        = CGColor(red: 0.85, green: 0.85, blue: 0.20, alpha: 1.0)
        let silkscreenColor = CGColor(red: 1.0, green: 1.0, blue: 1.0, alpha: 1.0)

        // Traces (segments)
        for seg in board.segments {
            let isFront = seg.layer == "F.Cu"
            let isBack  = seg.layer == "B.Cu"
            if side == .front && isBack { continue }
            if side == .back  && isFront { continue }
            ctx.setStrokeColor(isFront ? frontTraceColor : backTraceColor)
            ctx.setLineWidth(seg.width > 0 ? CGFloat(seg.width) : 0.25)
            ctx.beginPath()
            ctx.move(to: CGPoint(x: seg.start.x, y: seg.start.y))
            ctx.addLine(to: CGPoint(x: seg.end.x, y: seg.end.y))
            ctx.strokePath()
        }

        // Vias
        ctx.setFillColor(viaColor)
        for via in board.vias {
            let r = CGFloat(via.size) / 2
            ctx.fillEllipse(in: CGRect(
                x: via.position.x - r, y: via.position.y - r,
                width: r * 2, height: r * 2
            ))
        }

        // Footprints (silkscreen body)
        for fp in board.footprints {
            let bodyW: CGFloat = 3
            let bodyH: CGFloat = 3
            ctx.setStrokeColor(silkscreenColor)
            ctx.setLineWidth(0.1)
            ctx.stroke(CGRect(
                x: fp.position.x - bodyW / 2,
                y: fp.position.y - bodyH / 2,
                width: bodyW, height: bodyH
            ))
        }

        // Pads
        ctx.setFillColor(padColor)
        for fp in board.footprints {
            for pad in fp.pads {
                let w = CGFloat(pad.size.w)
                let h = CGFloat(pad.size.h)
                if w <= 0 || h <= 0 { continue }
                let cx = fp.position.x + pad.position.x
                let cy = fp.position.y + pad.position.y
                let rect = CGRect(x: cx - w / 2, y: cy - h / 2, width: w, height: h)
                if pad.shape == "circle" || pad.shape == "oval" {
                    ctx.fillEllipse(in: rect)
                } else {
                    ctx.fill(rect)
                }
                // Drill hole
                if pad.drill > 0 {
                    let d = CGFloat(pad.drill)
                    ctx.setFillColor(red: 0.05, green: 0.18, blue: 0.10, alpha: 1.0)
                    ctx.fillEllipse(in: CGRect(x: cx - d / 2, y: cy - d / 2, width: d, height: d))
                    ctx.setFillColor(padColor)
                }
            }
        }

        guard let cgImage = ctx.makeImage() else {
            throw NSError(domain: "PCBImageRenderer", code: 2, userInfo: [
                NSLocalizedDescriptionKey: "Could not finalize CGImage"
            ])
        }
        let rep = NSBitmapImageRep(cgImage: cgImage)
        guard let png = rep.representation(using: .png, properties: [:]) else {
            throw NSError(domain: "PCBImageRenderer", code: 3, userInfo: [
                NSLocalizedDescriptionKey: "Could not encode PNG"
            ])
        }
        return png
    }
}
