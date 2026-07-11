//
//  ValidationPanel.swift
//  KiCadAgent
//
//  Phase 216 — ERC/DRC Integration
//
//  Toolbar buttons + results panel for running ERC/DRC via the daemon.
//

import SwiftUI
import OSLog

/// Results of an ERC/DRC check.
struct ValidationResult: Identifiable {
    let id = UUID()
    let checkType: String  // "ERC" or "DRC"
    let decision: String   // "passed", "failed", "indeterminate"
    let errorCount: Int
    let warningCount: Int
    let failures: [String]
}

/// View model for running ERC/DRC checks via the daemon.
@MainActor
@Observable
final class ValidationManager {
    var results: [ValidationResult] = []
    var isRunning: Bool = false

    /// Run ERC on a .kicad_sch file.
    func runERC(filePath: String, client: MCPClient?) async {
        guard let client else {
            results.append(ValidationResult(
                checkType: "ERC", decision: "indeterminate",
                errorCount: 0, warningCount: 0,
                failures: ["Daemon not connected"]
            ))
            return
        }
        isRunning = true
        defer { isRunning = false }

        do {
            let result = try await client.callRaw(
                "kicad.post_check",
                params: [
                    "op_type": "erc",
                    "files": [filePath],
                    "require_erc": true,
                    "require_drc": false
                ]
            )

            let parsed = parseResult(result, checkType: "ERC")
            results.insert(parsed, at: 0)
        } catch {
            results.insert(ValidationResult(
                checkType: "ERC", decision: "indeterminate",
                errorCount: 0, warningCount: 0,
                failures: [error.localizedDescription]
            ), at: 0)
        }
    }

    /// Run DRC on a .kicad_pcb file.
    func runDRC(filePath: String, client: MCPClient?) async {
        guard let client else {
            results.append(ValidationResult(
                checkType: "DRC", decision: "indeterminate",
                errorCount: 0, warningCount: 0,
                failures: ["Daemon not connected"]
            ))
            return
        }
        isRunning = true
        defer { isRunning = false }

        do {
            let result = try await client.callRaw(
                "kicad.post_check",
                params: [
                    "op_type": "drc",
                    "files": [filePath],
                    "require_erc": false,
                    "require_drc": true
                ]
            )

            let parsed = parseResult(result, checkType: "DRC")
            results.insert(parsed, at: 0)
        } catch {
            results.insert(ValidationResult(
                checkType: "DRC", decision: "indeterminate",
                errorCount: 0, warningCount: 0,
                failures: [error.localizedDescription]
            ), at: 0)
        }
    }

    /// Check if kicad-cli is installed.
    func checkKiCadCLI(client: MCPClient?) async -> String {
        guard let client else { return "Daemon not connected" }
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
            return "Check failed: \(error.localizedDescription)"
        }
        return "Unknown"
    }

    private func parseResult(_ raw: Any, checkType: String) -> ValidationResult {
        guard let dict = raw as? [String: Any] else {
            return ValidationResult(checkType: checkType, decision: "indeterminate",
                                    errorCount: 0, warningCount: 0, failures: ["Unparseable result"])
        }

        let decision = dict["decision"] as? String ?? "indeterminate"
        let failures = dict["failures"] as? [String] ?? []

        var errorCount = 0
        var warningCount = 0

        if let erc = dict["erc"] as? [String: Any] {
            errorCount = erc["error_count"] as? Int ?? 0
            warningCount = erc["warning_count"] as? Int ?? 0
        }
        if let drc = dict["drc"] as? [String: Any] {
            errorCount = drc["error_count"] as? Int ?? 0
        }

        return ValidationResult(checkType: checkType, decision: decision,
                                errorCount: errorCount, warningCount: warningCount,
                                failures: failures)
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
