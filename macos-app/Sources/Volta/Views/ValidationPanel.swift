//
//  ValidationPanel.swift
//  Phase 216 + 231 — ERC/DRC via native Swift engine (no IPC)
//
//  Phase 231: ValidationManager now calls NativeERC.run() directly in Swift.
//  No daemon round-trip needed. Daemon path stays as macOS-only fallback.
//

import SwiftUI
import OSLog

/// Results of an ERC/DRC check.
struct ValidationResult: Identifiable {
    let id = UUID()
    let checkType: String
    let decision: String
    let errorCount: Int
    let warningCount: Int
    let failures: [String]
}

/// View model for running ERC/DRC checks.
/// Phase 231: Calls Swift NativeERC/NativeDRC directly — instant, no IPC.
@MainActor
@Observable
final class ValidationManager {
    var results: [ValidationResult] = []
    var isRunning: Bool = false

    /// Run ERC on a .kicad_sch file using Swift native engine.
    func runERC(filePath: String, client: MCPClient?) async {
        isRunning = true
        defer { isRunning = false }

        // Phase 231: Try Swift native ERC first (instant, no daemon)
        let fileURL = URL(fileURLWithPath: filePath)
        let result = NativeERC.run(schematicURL: fileURL)

        let failures = result.violations
            .filter { $0.severity == .error }
            .map { $0.description }

        results.insert(ValidationResult(
            checkType: "ERC",
            decision: result.passed ? "passed" : "failed",
            errorCount: result.errorCount,
            warningCount: result.warningCount,
            failures: failures
        ), at: 0)
    }

    /// Run DRC on a .kicad_pcb file using Swift native engine.
    func runDRC(filePath: String, client: MCPClient?) async {
        isRunning = true
        defer { isRunning = false }

        let fileURL = URL(fileURLWithPath: filePath)

        do {
            let board = try PCBParser.parse(fileURL)

            // Run Swift DRC checks
            var violations: [DRCViolation] = []

            // Check track widths
            let segments = board.segments.map { seg in
                (start: CGPoint(seg.start.x, seg.start.y),
                 end: CGPoint(seg.end.x, seg.end.y),
                 width: seg.width, net: seg.netName, layer: seg.layer)
            }
            violations.append(contentsOf: NativeDRC.checkTrackWidths(segments: segments))

            // Check annular rings
            let vias = board.vias.map { via in
                (pos: CGPoint(via.position.x, via.position.y),
                 size: via.size, drill: via.drill)
            }
            let pads = board.footprints.flatMap { fp in
                fp.pads.map { pad in
                    (pos: CGPoint(fp.position.x + pad.position.x, fp.position.y + pad.position.y),
                     size: [pad.size.w, pad.size.h], drill: pad.drill,
                     ref: "\(fp.reference).\(pad.number)")
                }
            }
            violations.append(contentsOf: NativeDRC.checkAnnularRing(vias: vias, pads: pads))

            // Check hole clearances
            var holes: [(pos: CGPoint, drill: Double, ref: String, fpRef: String)] = []
            for via in board.vias {
                holes.append((pos: CGPoint(via.position.x, via.position.y),
                             drill: via.drill, ref: "via", fpRef: ""))
            }
            for fp in board.footprints {
                for pad in fp.pads where pad.drill > 0 {
                    holes.append((pos: CGPoint(fp.position.x + pad.position.x, fp.position.y + pad.position.y),
                                 drill: pad.drill, ref: "\(fp.reference).\(pad.number)",
                                 fpRef: fp.reference))
                }
            }
            violations.append(contentsOf: NativeDRC.checkHoleClearance(holes: holes))

            let errors = violations.filter { $0.severity == "error" }
            let failures = errors.map { $0.description }

            results.insert(ValidationResult(
                checkType: "DRC",
                decision: errors.isEmpty ? "passed" : "failed",
                errorCount: errors.count,
                warningCount: violations.filter { $0.severity == "warning" }.count,
                failures: failures
            ), at: 0)
        } catch {
            results.insert(ValidationResult(
                checkType: "DRC", decision: "indeterminate",
                errorCount: 0, warningCount: 0,
                failures: ["Parse error: \(error.localizedDescription)"]
            ), at: 0)
        }
    }

    /// Check if kicad-cli is installed (macOS only — informational).
    func checkKiCadCLI(client: MCPClient?) async -> String {
        #if os(macOS)
        guard let client else { return "Daemon not connected (using native engine)" }
        do {
            let result = try await client.callRaw("kicad_cli_check", params: [:])
            if let dict = result as? [String: Any] {
                let status = dict["status"] as? String ?? "unknown"
                if status == "ready" {
                    return "KiCad \(dict["version"] ?? "?") ✓"
                }
                return "KiCad CLI: \(status)"
            }
        } catch {
            return "Using native engine (kicad-cli check failed)"
        }
        return "Using native engine"
        #else
        return "Native engine (iOS)"
        #endif
    }
}

/// Panel showing ERC/DRC results.
struct ValidationResultsPanel: View {
    let results: [ValidationResult]
    let isRunning: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if isRunning {
                ProgressView("Running checks...")
            }

            ForEach(results) { result in
                resultRow(result)
            }

            if results.isEmpty && !isRunning {
                Text("No validation run yet")
                    .foregroundStyle(.secondary)
                    .font(.caption)
            }
        }
        .padding(8)
    }

    private func resultRow(_ result: ValidationResult) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Image(systemName: result.decision == "passed" ? "checkmark.circle.fill" : "xmark.circle.fill")
                    .foregroundStyle(result.decision == "passed" ? .green : .red)
                Text(result.checkType)
                    .font(.headline)
                Spacer()
                Text("\(result.errorCount) errors, \(result.warningCount) warnings")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            if !result.failures.isEmpty {
                ForEach(result.failures.prefix(5), id: \.self) { failure in
                    Text("• \(failure)")
                        .font(.caption)
                        .foregroundStyle(.red)
                }
                if result.failures.count > 5 {
                    Text("... and \(result.failures.count - 5) more")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding(.vertical, 4)
    }
}
