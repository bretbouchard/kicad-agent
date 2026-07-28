//
//  ProcessRunner.swift
//  Volta
//
//  ProcessRunner — abstraction over Foundation.Process for tests.
//
//  Extracted from the deleted KiCadCLIDetector (Phase 4 Task 6a sandbox
//  cleanup). Used by EasyEdaProvider (CLI subprocess invocation) and
//  FreeroutingProvider (Java/JAR invocation). Tests inject mock
//  implementations to avoid spawning real processes.
//
//  ponytail: three small types. No factory, no DI container.
//

import Foundation

/// Abstraction over `Process` so tests can mock subprocess results.
///
/// Real impl: `RealProcessRunner` — uses Foundation.Process.
/// Test impls: return canned `ProcessResult` values.
protocol ProcessRunner: Sendable {
    func run(executable: String, arguments: [String]) async throws -> ProcessResult
}

/// Result of one subprocess invocation.
struct ProcessResult: Equatable, Sendable {
    let stdout: String
    let stderr: String
    let exitCode: Int32
}

/// Real subprocess runner backed by Foundation.Process.
struct RealProcessRunner: ProcessRunner {
    func run(executable: String, arguments: [String]) async throws -> ProcessResult {
        try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global().async {
                let process = Process()
                process.executableURL = URL(fileURLWithPath: executable)
                process.arguments = arguments

                let stdoutPipe = Pipe()
                let stderrPipe = Pipe()
                process.standardOutput = stdoutPipe
                process.standardError = stderrPipe

                do {
                    try process.run()
                } catch {
                    continuation.resume(throwing: error)
                    return
                }

                // Wait synchronously on this background thread.
                process.waitUntilExit()

                let stdoutData = stdoutPipe.fileHandleForReading.readDataToEndOfFile()
                let stderrData = stderrPipe.fileHandleForReading.readDataToEndOfFile()

                let stdout = String(data: stdoutData, encoding: .utf8) ?? ""
                let stderr = String(data: stderrData, encoding: .utf8) ?? ""

                continuation.resume(returning: ProcessResult(
                    stdout: stdout,
                    stderr: stderr,
                    exitCode: process.terminationStatus
                ))
            }
        }
    }
}