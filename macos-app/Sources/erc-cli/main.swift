//
//  main.swift
//  erc-cli — Phase 234B Swift CLI harness for NativeERC
//
//  Reads a KiCad schematic, runs the native Swift ERC engine, prints JSON.
//  Used by the ERC parity test suite (Tests/VoltaTests/ERC/ERCParityTests.swift).
//
//  Build: see Scripts/build_erc_cli.sh
//  Usage: erc-cli <schematic.kicad_sch>
//  Output: { "ok": bool, "violations": [...], "error_count": N, "warning_count": N,
//            "passed": bool, "checks_run": [...], "checks_skipped": [...] }
//  Errors: { "ok": false, "error": "<message>" } printed to stdout
//

import Foundation

// MARK: - JSON output helpers

func jsonOutput(_ dict: [String: Any]) -> String {
    guard let data = try? JSONSerialization.data(
        withJSONObject: dict,
        options: [.prettyPrinted, .sortedKeys]
    ),
    let str = String(data: data, encoding: .utf8) else {
        return "{\"ok\":false,\"error\":\"json_serialization_failed\"}"
    }
    return str
}

// MARK: - SchematicIR → violations normalization

// The Swift ERC parity test suite (Tests/VoltaTests/ERC/ERCParityTests.swift)
// compares this CLI's JSON output against a direct in-process call to
// NativeERC.run(...). The normalization below keeps the load-bearing fields
// (check_id, severity, ref, net) stable across both code paths.
//
// Field mapping (Swift → CLI JSON):
//   checkId  → check_id
//   severity → severity
//   ref      → ref
//   net      → net
//   description → message

func violationToDict(_ v: [String: Any]) -> [String: Any] {
    var d: [String: Any] = [
        "check_id": v["check_id"] ?? "unknown",
        "severity": v["severity"] ?? "error",
    ]
    if let ref = v["ref"] { d["ref"] = ref }
    if let net = v["net"] { d["net"] = net }
    d["message"] = v["description"] ?? v["message"] ?? ""
    return d
}

// MARK: - Main

func main() {
    let args = CommandLine.arguments
    guard args.count == 2 else {
        let err: [String: Any] = [
            "ok": false,
            "error": "usage: erc-cli <schematic.kicad_sch>",
        ]
        print(jsonOutput(err))
        exit(2)
    }

    let path = args[1]
    let url = URL(fileURLWithPath: path)

    guard FileManager.default.fileExists(atPath: path) else {
        let err: [String: Any] = [
            "ok": false,
            "error": "file_not_found: \(path)",
            "violations": [],
            "error_count": 0,
            "warning_count": 0,
            "passed": false,
        ]
        print(jsonOutput(err))
        exit(1)
    }

    let result = NativeERC.run(schematicURL: url)
    let raw = result.toDict()

    // Re-shape to CLI JSON schema (consumed by ERCParityTests).
    let violations = (raw["violations"] as? [[String: Any]] ?? []).map(violationToDict)
    let out: [String: Any] = [
        "ok": true,
        "violations": violations,
        "error_count": raw["error_count"] as? Int ?? 0,
        "warning_count": raw["warning_count"] as? Int ?? 0,
        "passed": raw["clean"] as? Bool ?? false,
        "checks_run": raw["checks_run"] as? [String] ?? [],
        "checks_skipped": raw["checks_skipped"] as? [String] ?? [],
        "engine": "NativeERC.run",
    ]
    print(jsonOutput(out))
}

main()
