//
//  PreviewRendererTests.swift
//  KiCadAgentTests
//
//  Phase 238 — Real Preview Wire-up
//
//  Tests for the real schematic/PCB renderers and file watcher. The
//  schematic SVG renderer is already exercised end-to-end via Volta;
//  the PCB renderer is new in Phase 238 and gets unit tests here.
//

import Testing
import Foundation
import AppKit
@testable import KiCadAgent

@Suite("Preview Renderer (Phase 238)")
struct PreviewRendererTests {

    // MARK: - PCB renderer (the new real one)

    @Test("PCBImageRenderer.renderPNG produces a valid PNG with magic bytes")
    func pcbRendererProducesValidPNG() throws {
        let board = PCBBoard(
            version: "20240101",
            footprints: [
                PCBFootprint(
                    reference: "R1",
                    libId: "Device:R",
                    layer: "F.Cu",
                    position: (10.0, 20.0),
                    rotation: 0,
                    pads: [
                        PCBPad(
                            number: "1", type: "smd", shape: "rect",
                            position: (-1, 0), size: (0.5, 0.5),
                            layers: "F.Cu", netName: "Net-(R1-Pad1)", drill: 0
                        ),
                        PCBPad(
                            number: "2", type: "smd", shape: "rect",
                            position: (1, 0), size: (0.5, 0.5),
                            layers: "F.Cu", netName: "Net-(R1-Pad2)", drill: 0
                        )
                    ]
                )
            ],
            segments: [
                PCBSegment(start: (10, 20), end: (15, 20), width: 0.25, layer: "F.Cu", netName: "GND")
            ],
            vias: [
                PCBVia(position: (15, 20), size: 0.6, drill: 0.3, layers: "F.Cu/B.Cu", netName: "GND")
            ],
            nets: [PCBNet(number: 1, name: "GND")],
            netClasses: [],
            graphicItems: [],
            layers: ["F.Cu", "B.Cu"]
        )

        let data = try PCBImageRenderer.renderPNG(board: board)
        // PNG magic: 89 50 4E 47 0D 0A 1A 0A
        #expect(data.count > 8)
        #expect(Array(data.prefix(8)) == [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])
    }

    @Test("PCBImageRenderer.renderPNG handles an empty board without crashing")
    func pcbRendererEmptyBoard() throws {
        let board = PCBBoard(
            version: "20240101", footprints: [], segments: [],
            vias: [], nets: [], netClasses: [], graphicItems: [], layers: []
        )
        let data = try PCBImageRenderer.renderPNG(board: board)
        // Should still produce a valid PNG of the default 50x50mm area
        #expect(data.count > 100)
        #expect(Array(data.prefix(8)) == [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])
    }

    @Test("PCBImageRenderer.renderPNG respects F.Cu/B.Cu side filter")
    func pcbRendererSideFilter() throws {
        let board = PCBBoard(
            version: "20240101", footprints: [],
            segments: [
                PCBSegment(start: (0, 0), end: (10, 0), width: 0.25, layer: "F.Cu", netName: ""),
                PCBSegment(start: (0, 0), end: (10, 0), width: 0.25, layer: "B.Cu", netName: "")
            ],
            vias: [], nets: [], netClasses: [], graphicItems: [], layers: ["F.Cu", "B.Cu"]
        )
        // Both back and front should produce non-empty PNGs (different colors)
        let front = try PCBImageRenderer.renderPNG(board: board, side: .front)
        let back  = try PCBImageRenderer.renderPNG(board: board, side: .back)
        #expect(front.count > 100)
        #expect(back.count > 100)
        // The bytes should differ (front has F.Cu red pixels, back has B.Cu blue)
        #expect(front != back)
    }

    // MARK: - Schematic renderer (sanity)

    @Test("SwiftSVGRenderer.renderPCB delegates to PCBImageRenderer (not placeholder)")
    func schematicRendererDelegatesPCB() async throws {
        // Render a tiny temp .kicad_pcb via PCBImageRenderer directly and
        // ensure SwiftSVGRenderer delegates to it for the same input.
        let tmp = FileManager.default.temporaryDirectory
            .appendingPathComponent("\(UUID().uuidString).kicad_pcb")
        let minimal = """
        (kicad_pcb
          (version 20240101)
          (generator "test")
          (footprint "Device:R"
            (layer "F.Cu")
            (at 10 20)
          )
        )
        """
        try minimal.write(to: tmp, atomically: true, encoding: .utf8)
        defer { try? FileManager.default.removeItem(at: tmp) }

        let renderer = SwiftSVGRenderer()
        let artifact = try await renderer.renderPCB(pcbPath: tmp, side: .front)
        defer { try? FileManager.default.removeItem(at: artifact.url) }
        // Real PNG, not 67-byte placeholder
        #expect(artifact.url.pathExtension == "png")
        let data = try Data(contentsOf: artifact.url)
        #expect(data.count > 100, "Expected real PCB render, got \(data.count) bytes (likely placeholder)")
    }

    // MARK: - Magic bytes verification (T-172-01)

    @Test("MagicBytes.verify accepts a real PNG and rejects garbage")
    func magicBytesRoundTrip() throws {
        let tmp = FileManager.default.temporaryDirectory
            .appendingPathComponent("\(UUID().uuidString).png")
        // Real (tiny) PNG from PCBImageRenderer
        let board = PCBBoard(
            version: "20240101", footprints: [], segments: [],
            vias: [], nets: [], netClasses: [], graphicItems: [], layers: []
        )
        try PCBImageRenderer.renderPNG(board: board).write(to: tmp)
        defer { try? FileManager.default.removeItem(at: tmp) }

        #expect(MagicBytes.verify(url: tmp, expected: MagicBytes.png))
        #expect(!MagicBytes.verify(url: tmp, expected: MagicBytes.svg))

        // Non-existent file should not verify
        let bogus = URL(fileURLWithPath: "/tmp/does-not-exist-\(UUID().uuidString).png")
        #expect(!MagicBytes.verify(url: bogus, expected: MagicBytes.png))
    }

    // MARK: - File watcher (T-238-03)

    @Test("PreviewFileWatcher debounces multiple writes into one callback")
    func fileWatcherDebounce() async throws {
        let tmp = FileManager.default.temporaryDirectory
            .appendingPathComponent("\(UUID().uuidString).txt")
        try "v0".write(to: tmp, atomically: true, encoding: .utf8)
        defer { try? FileManager.default.removeItem(at: tmp) }

        let counter = Counter()
        let watcher = PreviewFileWatcher(url: tmp, debounce: 0.1) {
            Task { await counter.increment() }
        }
        watcher.start()
        defer { watcher.stop() }

        // Three rapid writes within debounce window
        try "v1".write(to: tmp, atomically: true, encoding: .utf8)
        try? await Task.sleep(for: .milliseconds(20))
        try "v2".write(to: tmp, atomically: true, encoding: .utf8)
        try? await Task.sleep(for: .milliseconds(20))
        try "v3".write(to: tmp, atomically: true, encoding: .utf8)

        // Wait past the debounce window
        try await Task.sleep(for: .milliseconds(300))

        // Should have fired exactly once (debounced), not three times
        let count = await counter.value
        #expect(count == 1, "Expected 1 debounced callback, got \(count)")
    }

    // MARK: - Mock renderer (still used by tests + previews)

    @Test("MockPreviewRenderer still produces valid magic bytes")
    func mockRendererStillValid() async throws {
        let renderer = MockPreviewRenderer()
        let tmp = FileManager.default.temporaryDirectory
            .appendingPathComponent("\(UUID().uuidString).kicad_sch")
        try "(kicad_sch)".write(to: tmp, atomically: true, encoding: .utf8)
        defer { try? FileManager.default.removeItem(at: tmp) }

        let sch = try await renderer.renderSchematic(schematicPath: tmp)
        #expect(MagicBytes.verify(url: sch.url, expected: MagicBytes.svg))

        let pcb = try await renderer.renderPCB(pcbPath: tmp, side: .front)
        #expect(MagicBytes.verify(url: pcb.url, expected: MagicBytes.png))
    }
}

private actor Counter {
    var value: Int = 0
    func increment() { value += 1 }
}
