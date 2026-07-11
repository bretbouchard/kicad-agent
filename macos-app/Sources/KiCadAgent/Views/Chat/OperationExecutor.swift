//
//  OperationExecutor.swift
//  KiCadAgent
//
//  Phase 212 — Daemon Operations from Chat
//
//  Parses LLM responses for KiCad operation JSON, executes them via
//  the daemon MCPClient, and returns results for the chat UI.
//

import Foundation
import OSLog

/// Result of executing an operation from chat.
enum OperationResult: Sendable {
    case success(String)
    case failure(String)
    case noOperation

    var displayText: String {
        switch self {
        case .success(let text): return text
        case .failure(let error): return "⚠️ \(error)"
        case .noOperation: return ""
        }
    }
}

/// Executes KiCad operations parsed from LLM output.
///
/// Phase 225: Uses the native Swift VoltaEngine first (no daemon needed).
/// Falls back to the daemon MCPClient if the op isn't in the Swift engine.
///
/// Scans assistant messages for JSON code blocks containing operation
/// specs ({"op_type": "...", "target_file": "...", ...}), executes them,
/// and returns formatted results.
struct OperationExecutor {

    /// Execute any operations found in an LLM response.
    /// Tries Swift VoltaEngine first, falls back to daemon.
    @MainActor
    static func execute(from responseText: String, client: MCPClient?) async -> OperationResult {
        // Parse JSON code blocks from the response
        let operations = parseOperations(from: responseText)
        guard !operations.isEmpty else {
            return .noOperation
        }

        let voltaEngine = VoltaEngine()
        var results: [String] = []

        for op in operations {
            do {
                // Try Swift VoltaEngine first
                if voltaEngine.availableOperations.contains(op.opType),
                   let targetPath = op.arguments["target_file"] as? String {
                    let fileURL = URL(fileURLWithPath: targetPath)
                    let result = try voltaEngine.execute(op.opType, params: op.arguments, on: fileURL)
                    let summary = result["status"] as? String ?? "completed"
                    results.append("✅ \(op.opType): \(summary)")
                    continue
                }

                // Fall back to daemon MCPClient
                guard let client else {
                    results.append("⚠️ \(op.opType): no engine available")
                    continue
                }

                let result = try await client.callRaw(
                    "tools/call",
                    params: ["name": "kicad.\(op.opType)", "arguments": op.arguments]
                )
                if let resultDict = result as? [String: Any],
                   let content = resultDict["content"] as? String {
                    results.append("✅ \(op.opType): \(content.prefix(200))")
                } else {
                    results.append("✅ \(op.opType): completed")
                }
            } catch {
                results.append("⚠️ \(op.opType): \(error.localizedDescription)")
            }
        }

        return results.isEmpty ? .noOperation : .success(results.joined(separator: "\n\n"))
    }

    /// Parse ```json blocks from LLM output that look like operation specs.
    private static func parseOperations(from text: String) -> [ParsedOp] {
        var ops: [ParsedOp] = []

        // Find all ```json ... ``` blocks
        let pattern = #"```json\s*\n([\s\S]*?)```"#
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return [] }

        let nsText = text as NSString
        let matches = regex.matches(in: text, range: NSRange(location: 0, length: nsText.length))

        for match in matches {
            guard match.numberOfRanges > 1 else { continue }
            let jsonStr = nsText.substring(with: match.range(at: 1))
            guard let data = jsonStr.data(using: .utf8),
                  let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let opType = dict["op_type"] as? String else { continue }

            ops.append(ParsedOp(opType: opType, arguments: dict))
        }

        return ops
    }
}

private struct ParsedOp {
    let opType: String
    let arguments: [String: Any]
}
