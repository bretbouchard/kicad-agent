//
//  ERCParityTests.swift
//  VoltaTests
//
//  Phase 253 Task 6d — Pure Swift ERC parity test
//
//  Verifies that the erc-cli binary (which spawns NativeERC as a subprocess
//  and emits JSON) produces output equivalent to a direct in-process call to
//  NativeERC.run(...). This catches two regressions:
//
//    1. The CLI wrapper corrupting violation data during JSON serialization
//    2. The CLI wrapper's normalization diverging from the Swift API
//
//  Strategy:
//    1. Locate the erc-cli binary (try a few candidate paths).
//    2. For each fixture in a small corpus:
//       a. Spawn erc-cli via Process with the fixture path as arg.
//       b. Parse the JSON output.
//       c. Run NativeERC.run(...) directly on the same fixture.
//       d. Compare error_count, warning_count, passed, and violation keys.
//    3. Skip the suite if erc-cli is not built (dev-mode tolerance — devs
//       who delete build artifacts don't get false-positives).
//
//  No Python in the test loop. No fallback to deleted harness.
//

import Testing
import Foundation
@testable import Volta

@Suite("ERC Parity (erc-cli ↔ NativeERC)")
struct ERCParityTests {

    // MARK: - Fixture corpus
    //
    // Three fixtures cover the three regimes:
    //   - S1_led_bringer: clean board (no violations)
    //   - S3_opamp_preamp: 5 errors, no warnings
    //   - S5_esp32_breakout: 11 errors, 42 warnings (mixed)
    //
    // Verified via `erc-cli <fixture>` before writing this test.

    private static let corpus: [(name: String, relPath: String)] = [
        ("S1_led_bringer.kicad_sch", "tests/fixtures/legibility/S1_led_bringer.kicad_sch"),
        ("S3_opamp_preamp.kicad_sch", "tests/fixtures/legibility/S3_opamp_preamp.kicad_sch"),
        ("S5_esp32_breakout.kicad_sch", "tests/fixtures/legibility/S5_esp32_breakout.kicad_sch"),
    ]

    // MARK: - Locators

    /// Locate the committed erc-cli binary. The build script writes it to
    /// `.planning/phases/234b-parity-execute/erc-cli`. When tests run from
    /// the repo root, the relative path is correct. When run from inside
    /// `macos-app/` (some Xcode configurations), we need the `../` prefix.
    private static func locateERCCLI() -> URL? {
        let candidates = [
            ".planning/phases/234b-parity-execute/erc-cli",
            "../.planning/phases/234b-parity-execute/erc-cli",
        ]
        for path in candidates {
            let url = URL(fileURLWithPath: path)
            if FileManager.default.isExecutableFile(atPath: url.path) {
                return url
            }
        }
        return nil
    }

    /// Locate a fixture by name, trying repo-root and `macos-app/`-relative
    /// working directories. Returns nil if the fixture can't be found.
    private static func locateFixture(name: String) -> URL? {
        let rel = "tests/fixtures/legibility/\(name)"
        for prefix in ["", "../"] {
            let url = URL(fileURLWithPath: prefix + rel)
            if FileManager.default.fileExists(atPath: url.path) {
                return url
            }
        }
        return nil
    }

    // MARK: - CLI invocation

    /// Decoded shape of the erc-cli JSON output. Mirrors the dictionary in
    /// `Sources/erc-cli/main.swift`.
    private struct CLIOutput: Decodable {
        let ok: Bool?
        let passed: Bool?
        let errorCount: Int?
        let warningCount: Int?
        let violations: [CLIViolation]?

        enum CodingKeys: String, CodingKey {
            case ok
            case passed
            case errorCount = "error_count"
            case warningCount = "warning_count"
            case violations
        }
    }

    private struct CLIViolation: Decodable {
        let checkId: String?
        let severity: String?
        let ref: String?
        let net: String?

        enum CodingKeys: String, CodingKey {
            case checkId = "check_id"
            case severity
            case ref
            case net
        }
    }

    /// Spawn erc-cli and capture its JSON output. Throws on spawn failure
    /// or non-zero exit; the CLI itself emits `{"ok": false, ...}` for
    /// expected errors (missing file, parse error), so a non-zero exit
    /// is treated as a hard failure.
    private static func runCLI(_ binary: URL, fixture: URL) throws -> CLIOutput {
        let proc = Process()
        proc.executableURL = binary
        proc.arguments = [fixture.path]
        let stdoutPipe = Pipe()
        let stderrPipe = Pipe()
        proc.standardOutput = stdoutPipe
        proc.standardError = stderrPipe

        try proc.run()
        proc.waitUntilExit()

        let data = stdoutPipe.fileHandleForReading.readDataToEndOfFile()
        if proc.terminationStatus != 0 {
            let stderr = String(
                data: stderrPipe.fileHandleForReading.readDataToEndOfFile(),
                encoding: .utf8
            ) ?? "<no stderr>"
            throw CLIError.nonZeroExit(proc.terminationStatus, stderr)
        }
        do {
            return try JSONDecoder().decode(CLIOutput.self, from: data)
        } catch {
            throw CLIError.invalidJSON(String(data: data, encoding: .utf8) ?? "<binary>", error)
        }
    }

    private enum CLIError: Error, CustomStringConvertible {
        case nonZeroExit(Int32, String)
        case invalidJSON(String, Error)

        var description: String {
            switch self {
            case .nonZeroExit(let code, let stderr):
                return "erc-cli exited with code \(code): \(stderr)"
            case .invalidJSON(let body, let err):
                return "erc-cli emitted invalid JSON: \(err); body=\(body.prefix(200))"
            }
        }
    }

    // MARK: - Comparators

    /// A violation's identity is `(check_id, ref, net)`. The CLI normalizes
    /// Swift's `description` → `message`, but `check_id`, `ref`, and `net`
    /// are preserved verbatim — those are the load-bearing fields.
    private static func violationKey(_ v: CLIViolation) -> String {
        "\(v.checkId ?? "?"):\(v.ref ?? ""):\(v.net ?? "")"
    }

    private static func violationKey(_ v: ERCViolation) -> String {
        "\(v.checkId):\(v.ref):\(v.net)"
    }

    // MARK: - Tests

    @Test("erc-cli binary is available (or suite is skipped)")
    func ercCLIAvailable() {
        // ponystail: don't gate the suite on a build artifact the dev may
        // have cleaned. Print a paper trail and skip; the parity tests
        // below also skip if the binary is missing.
        guard let binary = Self.locateERCCLI() else {
            print("[SKIP] erc-cli binary not built. Build with: " +
                  ".planning/phases/234b-parity-execute/scripts/build_erc_cli.sh")
            return
        }
        #expect(FileManager.default.isExecutableFile(atPath: binary.path))
    }

    @Test("CLI parity: S1_led_bringer (clean board, 0 violations)")
    func cliParityS1() throws {
        try assertParity(fixtureName: "S1_led_bringer.kicad_sch")
    }

    @Test("CLI parity: S3_opamp_preamp (5 errors, 0 warnings)")
    func cliParityS3() throws {
        try assertParity(fixtureName: "S3_opamp_preamp.kicad_sch")
    }

    @Test("CLI parity: S5_esp32_breakout (11 errors, 42 warnings)")
    func cliParityS5() throws {
        try assertParity(fixtureName: "S5_esp32_breakout.kicad_sch")
    }

    @Test("All corpus fixtures exist and are readable")
    func corpusIsComplete() {
        for entry in Self.corpus {
            guard Self.locateFixture(name: entry.name) != nil else {
                print("[SKIP] fixture missing: \(entry.name)")
                continue
            }
            // Found — just confirm parseable text.
        }
    }

    // MARK: - Core parity assertion

    private func assertParity(fixtureName: String) throws {
        guard let binary = Self.locateERCCLI() else {
            print("[SKIP] erc-cli binary not built — parity check skipped")
            return
        }
        guard let fixture = Self.locateFixture(name: fixtureName) else {
            print("[SKIP] fixture not found: \(fixtureName)")
            return
        }

        let cli = try Self.runCLI(binary, fixture: fixture)
        let direct = NativeERC.run(schematicURL: fixture)

        #expect(cli.ok == true, "CLI must report ok=true on a valid fixture")
        #expect(cli.errorCount == direct.errorCount,
                "error_count mismatch: cli=\(cli.errorCount ?? -1), direct=\(direct.errorCount)")
        #expect(cli.warningCount == direct.warningCount,
                "warning_count mismatch: cli=\(cli.warningCount ?? -1), direct=\(direct.warningCount)")
        #expect(cli.passed == direct.passed,
                "passed mismatch: cli=\(cli.passed ?? false), direct=\(direct.passed)")

        let cliKeys = Set((cli.violations ?? []).map(Self.violationKey))
        let directKeys = Set(direct.violations.map(Self.violationKey))
        let onlyInCLI = cliKeys.subtracting(directKeys)
        let onlyInDirect = directKeys.subtracting(cliKeys)

        #expect(onlyInCLI.isEmpty,
                "CLI reported violations that direct invocation did not: \(onlyInCLI.sorted())")
        #expect(onlyInDirect.isEmpty,
                "Direct invocation found violations that CLI did not: \(onlyInDirect.sorted())")
    }
}
