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

/// Executes KiCad operations parsed from LLM output via the daemon.
///
/// Scans assistant messages for JSON code blocks containing operation
/// specs ({"op_type": "...", "target_file": "...", ...}), sends them
/// to the daemon via MCPClient tools/call, and returns formatted results.
struct OperationExecutor {

    /// Execute any operations found in an LLM response.
    /// Returns the result text to append as a system message, or nil
    /// if no operations were found.
    @MainActor
    static func execute(from responseText: String, client: MCPClient?) async -> OperationResult {
        guard let client else {
            return .noOperation
        }

        // Parse JSON code blocks from the response
        let operations = parseOperations(from: responseText)
        guard !operations.isEmpty else {
            return .noOperation
        }

        var results: [String] = []
        for op in operations {
            do {
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
