//
//  InlineRenderingTypes.swift
//  KiCadAgent
//
//  Phase 172 — Inline Rendering
//
//  Shared types for inline preview rendering: pipeline steps, statuses,
//  progress events, and the preview renderer protocol that the daemon
//  client conforms to. UI depends on the protocol so tests can inject
//  a mock renderer without touching the daemon.
//
//  T-172-01: file magic byte verification (SVG: <?xml, PNG: \\x89PNG)
//  T-172-02: strict progress event schema (steps restricted to enum)
//  T-172-03: bounded render cache (cap 100, LRU eviction)
//

import Foundation
import SwiftUI

/// Canonical pipeline steps in fixed execution order.
///
/// T-172-02: enum-restricted step names prevent injection via daemon stdout.
enum PipelineStep: String, CaseIterable, Codable, Sendable, Identifiable {
    case design
    case schematic
    case erc
    case pcb
    case drc
    case export

    var id: String { rawValue }

    /// Human-readable label (capitalized, preserved as source of truth).
    var label: String {
        switch self {
        case .design: return "Design"
        case .schematic: return "Schematic"
        case .erc: return "ERC"
        case .pcb: return "PCB"
        case .drc: return "DRC"
        case .export: return "Export"
        }
    }

    /// SF Symbol per step (for drill-down UI).
    var systemImage: String {
        switch self {
        case .design: return "rectangle.and.pencil.and.ellipsis"
        case .schematic: return "doc.text"
        case .erc: return "checkmark.shield"
        case .pcb: return "rectangle.split.3x1"
        case .drc: return "checkmark.shield.fill"
        case .export: return "square.and.arrow.up"
        }
    }
}

/// Step status — what state a step is currently in.
enum StepStatus: String, Codable, Sendable, Equatable {
    case pending
    case running
    case verified
    case failed

    var color: Color {
        switch self {
        case .pending: return ColorTokens.tertiaryText
        case .running: return Color.accentColor
        case .verified: return ColorTokens.success
        case .failed: return ColorTokens.destructive
        }
    }

    var systemImage: String {
        switch self {
        case .pending: return "circle"
        case .running: return "arrow.triangle.2.circlepath"
        case .verified: return "checkmark.circle.fill"
        case .failed: return "xmark.circle.fill"
        }
    }
}

/// Pipeline progress event — what the daemon emits.
///
/// T-172-02: strict schema. `step` must match PipelineStep raw values.
struct PipelineProgressEvent: Codable, Sendable, Equatable {
    let step: PipelineStep
    let status: StepStatus
    let durationMs: Int
    let timestamp: Date
    /// Optional error message for `.failed` status. Sanitized — no secrets.
    let errorMessage: String?

    enum CodingKeys: String, CodingKey {
        case step
        case status
        case durationMs = "duration_ms"
        case timestamp
        case errorMessage = "error_message"
    }

    init(
        step: PipelineStep,
        status: StepStatus,
        durationMs: Int,
        timestamp: Date = .now,
        errorMessage: String? = nil
    ) {
        self.step = step
        self.status = status
        self.durationMs = durationMs
        self.timestamp = timestamp
        self.errorMessage = errorMessage
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.step = try c.decode(PipelineStep.self, forKey: .step)
        self.status = try c.decode(StepStatus.self, forKey: .status)
        self.durationMs = try c.decode(Int.self, forKey: .durationMs)
        // Timestamp may arrive as ISO 8601 string or epoch Double. Support both.
        if let str = try? c.decode(String.self, forKey: .timestamp),
           let parsed = ISO8601DateFormatter().date(from: str) {
            self.timestamp = parsed
        } else {
            self.timestamp = try c.decode(Date.self, forKey: .timestamp)
        }
        self.errorMessage = try c.decodeIfPresent(String.self, forKey: .errorMessage)
    }
}

/// Render kind for `RenderArtifact` — what was produced.
enum RenderKind: String, Codable, Sendable {
    case schematicSVG
    case pcbPNG
}

/// A rendered artifact on disk.
struct RenderArtifact: Identifiable, Sendable, Equatable {
    let id: UUID
    let kind: RenderKind
    let url: URL
    let createdAt: Date

    init(id: UUID = UUID(), kind: RenderKind, url: URL, createdAt: Date = .now) {
        self.id = id
        self.kind = kind
        self.url = url
        self.createdAt = createdAt
    }
}

/// Preview renderer protocol — UI depends on this, not the daemon.
///
/// ponytail: protocol, not concrete class. Tests inject mock.
/// Phase 172 ships MockPreviewRenderer for tests; Phase 175 wires
/// DaemonPreviewRenderer to MCPClient.call.
protocol PreviewRenderer: Sendable {
    /// Render a schematic SVG. Returns the rendered artifact or throws.
    func renderSchematic(schematicPath: URL) async throws -> RenderArtifact
    /// Render a PCB PNG. Returns the rendered artifact or throws.
    func renderPCB(pcbPath: URL, side: PCBSide) async throws -> RenderArtifact
}

/// PCB render side (kicad-cli --side flag).
enum PCBSide: String, CaseIterable, Codable, Sendable {
    case front
    case back
}

/// Errors specific to inline rendering.
enum InlineRenderingError: LocalizedError, Sendable {
    case fileNotRenderable(URL)
    case invalidMagicBytes(expected: String, actual: String)
    case renderFailed(reason: String)
    case daemonUnavailable

    var errorDescription: String? {
        switch self {
        case .fileNotRenderable(let url):
            return "File not renderable: \(url.lastPathComponent)"
        case .invalidMagicBytes(let expected, let actual):
            return "File failed magic-byte verification (expected \(expected), got \(actual))"
        case .renderFailed(let reason):
            return "Render failed: \(reason)"
        case .daemonUnavailable:
            return "Daemon unavailable — cannot render"
        }
    }
}

/// Magic byte verification (T-172-01 mitigation).
///
/// Verifies a file starts with the expected magic bytes before rendering.
/// Prevents malicious daemon from substituting non-image content.
enum MagicBytes {
    /// SVG files start with `<?xml` (possibly with leading BOM/whitespace).
    static let svg: [UInt8] = Array("<?xml".utf8)
    /// PNG files start with the 8-byte PNG signature.
    static let png: [UInt8] = [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]

    /// Verify a file at the given URL starts with the expected magic bytes.
    /// Returns true if verified, false otherwise. File-read errors return false.
    static func verify(url: URL, expected: [UInt8]) -> Bool {
        guard let fileHandle = try? FileHandle(forReadingFrom: url) else { return false }
        defer { try? fileHandle.close() }
        guard let data = try? fileHandle.read(upToCount: expected.count) else { return false }
        guard data.count == expected.count else { return false }
        return Array(data) == expected
    }
}
