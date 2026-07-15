//
//  NativeERC.swift
//  Phase 222 — Swift Native ERC Engine
//
//  Pure Swift port of native_erc.py. No kicad-cli, no Python daemon.
//  Uses SchematicParser + TopologyBuilder from Phase 221.
//
//  Checks:
//    1. Pin-type conflict detection (11×11 compatibility matrix)
//    2. Power net validation (unconnected power pins)
//    3. No-connect validation (missing/incorrect NC flags)
//    4. Dangling wire detection
//

import Foundation
import OSLog

// MARK: - Result Types

enum ERCSeverity: String, Sendable {
    case error, warning, info
}

struct ERCViolation: Identifiable, Sendable {
    let id = UUID()
    let severity: ERCSeverity
    let checkId: String
    let description: String
    var ref: String = ""
    var pin: String = ""
    var net: String = ""
    var position: (Double, Double)?

    func toDict() -> [String: Any] {
        var d: [String: Any] = [
            "severity": severity.rawValue,
            "check_id": checkId,
            "description": description,
        ]
        if !ref.isEmpty { d["ref"] = ref }
        if !pin.isEmpty { d["pin"] = pin }
        if !net.isEmpty { d["net"] = net }
        if let pos = position { d["position"] = [pos.0, pos.1] }
        return d
    }
}

struct NativeErcResult: Sendable {
    let violations: [ERCViolation]
    let checksRun: [String]
    let checksSkipped: [String]

    var errorCount: Int { violations.filter { $0.severity == .error }.count }
    var warningCount: Int { violations.filter { $0.severity == .warning }.count }
    var passed: Bool { errorCount == 0 }

    func toDict() -> [String: Any] {
        [
            "clean": passed,
            "error_count": errorCount,
            "warning_count": warningCount,
            "violations": violations.map { $0.toDict() },
            "checks_run": checksRun,
            "checks_skipped": checksSkipped,
        ]
    }
}

// MARK: - Pin-Type Compatibility Matrix

/// KiCad's 11×11 pin electrical type compatibility matrix.
/// Values: "ok" = compatible, "err" = error, "warn" = warning.
/// Transcribed from KiCad's publicly documented ERC matrix.
private let pinCompatMatrix: [String: [String: String]] = [
    "input":          ["input": "ok", "output": "ok", "bidirectional": "ok", "tri_state": "ok", "passive": "ok", "unspecified": "warn", "power_input": "ok", "power_output": "ok", "open_collector": "ok", "open_emitter": "ok", "free": "warn"],
    "output":         ["input": "ok", "output": "err", "bidirectional": "warn", "tri_state": "err", "passive": "ok", "unspecified": "warn", "power_input": "err", "power_output": "err", "open_collector": "warn", "open_emitter": "warn", "free": "warn"],
    "bidirectional":  ["input": "ok", "output": "warn", "bidirectional": "warn", "tri_state": "warn", "passive": "ok", "unspecified": "warn", "power_input": "warn", "power_output": "warn", "open_collector": "warn", "open_emitter": "warn", "free": "warn"],
    "tri_state":      ["input": "ok", "output": "err", "bidirectional": "warn", "tri_state": "err", "passive": "ok", "unspecified": "warn", "power_input": "err", "power_output": "err", "open_collector": "warn", "open_emitter": "warn", "free": "warn"],
    "passive":        ["input": "ok", "output": "ok", "bidirectional": "ok", "tri_state": "ok", "passive": "ok", "unspecified": "warn", "power_input": "ok", "power_output": "ok", "open_collector": "ok", "open_emitter": "ok", "free": "warn"],
    "unspecified":    ["input": "warn", "output": "warn", "bidirectional": "warn", "tri_state": "warn", "passive": "warn", "unspecified": "warn", "power_input": "warn", "power_output": "warn", "open_collector": "warn", "open_emitter": "warn", "free": "warn"],
    "power_input":    ["input": "ok", "output": "err", "bidirectional": "warn", "tri_state": "err", "passive": "ok", "unspecified": "warn", "power_input": "ok", "power_output": "err", "open_collector": "ok", "open_emitter": "ok", "free": "warn"],
    "power_output":   ["input": "ok", "output": "err", "bidirectional": "warn", "tri_state": "err", "passive": "ok", "unspecified": "warn", "power_input": "err", "power_output": "warn", "open_collector": "ok", "open_emitter": "ok", "free": "warn"],
    "open_collector": ["input": "ok", "output": "warn", "bidirectional": "warn", "tri_state": "warn", "passive": "ok", "unspecified": "warn", "power_input": "ok", "power_output": "ok", "open_collector": "warn", "open_emitter": "warn", "free": "warn"],
    "open_emitter":   ["input": "ok", "output": "warn", "bidirectional": "warn", "tri_state": "warn", "passive": "ok", "unspecified": "warn", "power_input": "ok", "power_output": "ok", "open_collector": "warn", "open_emitter": "warn", "free": "warn"],
    "free":           ["input": "warn", "output": "warn", "bidirectional": "warn", "tri_state": "warn", "passive": "warn", "unspecified": "warn", "power_input": "warn", "power_output": "warn", "open_collector": "warn", "open_emitter": "warn", "free": "warn"],
]

private func normalizePinType(_ raw: String) -> String {
    let t = raw.lowercased().trimmingCharacters(in: .whitespaces)
    let aliases: [String: String] = [
        "power_in": "power_input",
        "power_out": "power_output",
        "opencollector": "open_collector",
        "openemitter": "open_emitter",
        "tristate": "tri_state",
        "no_connect": "passive",
    ]
    return aliases[t] ?? t
}

// MARK: - Power Net Detection

private let powerNames: Set<String> = ["VCC", "GND", "VDD", "VSS", "VEE", "AGND", "DGND", "PGND"]
private let voltagePattern = try? NSRegularExpression(
    pattern: #"^[+V]\d|[-+]\d+\s*V|_?\d+[Vv]\d?"#, options: .caseInsensitive
)

private func isPowerNet(_ name: String) -> Bool {
    let upper = name.uppercased()
    if powerNames.contains(upper) { return true }
    for prefix in ["+", "V", "PWR"] {
        if upper.hasPrefix(prefix) {
            let range = NSRange(upper.startIndex..., in: upper)
            if voltagePattern?.firstMatch(in: upper, range: range) != nil {
                return true
            }
        }
    }
    return false
}

// MARK: - ERC Checks

/// Resolved pin info for ERC checks — combines lib symbol pins with
/// instance positions and resolved net names.
struct ResolvedPin {
    let ref: String
    let number: String
    let name: String
    let electricalType: String
    let position: (Double, Double)
    let netName: String?
}

struct NativeERC {

    // MARK: - Check 1: Pin-Type Conflicts

    static func checkPinTypeConflicts(_ pins: [ResolvedPin]) -> [ERCViolation] {
        var violations: [ERCViolation] = []
        var nets: [String: [ResolvedPin]] = [:]

        for pin in pins {
            guard let net = pin.netName else { continue }
            nets[net, default: []].append(pin)
        }

        for (net, pinsOnNet) in nets {
            guard pinsOnNet.count >= 2 else { continue }
            for i in 0..<pinsOnNet.count {
                for j in (i+1)..<pinsOnNet.count {
                    let pa = pinsOnNet[i]
                    let pb = pinsOnNet[j]
                    let ta = normalizePinType(pa.electricalType)
                    let tb = normalizePinType(pb.electricalType)
                    let compat = pinCompatMatrix[ta]?[tb] ?? "warn"
                    if compat == "ok" { continue }

                    let sev: ERCSeverity = compat == "err" ? .error : .warning
                    violations.append(ERCViolation(
                        severity: sev, checkId: "ERC_PIN_CONFLICT",
                        description: "Pin type conflict: \(pa.ref).\(pa.number) (\(ta)) connected to \(pb.ref).\(pb.number) (\(tb)) on net '\(net)'",
                        ref: "\(pa.ref)/\(pb.ref)",
                        pin: "\(pa.number)/\(pb.number)",
                        net: net,
                        position: pa.position
                    ))
                }
            }
        }
        return violations
    }

    // MARK: - Check 2: Power Net Validation

    static func checkPowerNets(_ pins: [ResolvedPin]) -> [ERCViolation] {
        var violations: [ERCViolation] = []
        var nets: [String: [ResolvedPin]] = [:]

        for pin in pins {
            guard let net = pin.netName else { continue }
            nets[net, default: []].append(pin)
        }

        for (net, pinsOnNet) in nets {
            guard isPowerNet(net) else { continue }
            let hasDriver = pinsOnNet.contains {
                normalizePinType($0.electricalType) == "power_output"
            }
            let hasPowerInput = pinsOnNet.contains {
                normalizePinType($0.electricalType) == "power_input"
            }
            if hasPowerInput && !hasDriver {
                violations.append(ERCViolation(
                    severity: .warning, checkId: "ERC_POWER_NOT_DRIVEN",
                    description: "Power net '\(net)' has power_input pins but no power_output driver.",
                    net: net
                ))
            }
        }
        return violations
    }

    // MARK: - Check 3: No-Connect Validation

    static func checkNoConnects(
        pins: [ResolvedPin],
        noConnectPositions: Set<PositionKey>
    ) -> [ERCViolation] {
        var violations: [ERCViolation] = []

        for pin in pins {
            if pin.ref.hasPrefix("#") { continue }
            let posKey = roundPos(pin.position.0, pin.position.1)
            let isConnected = pin.netName != nil
            let hasNC = noConnectPositions.contains(posKey)

            if isConnected && hasNC {
                violations.append(ERCViolation(
                    severity: .warning, checkId: "ERC_NC_CONNECTED",
                    description: "Pin \(pin.ref).\(pin.number) has NC flag but is connected",
                    ref: pin.ref, pin: pin.number, position: pin.position
                ))
            } else if !isConnected && !hasNC {
                let ptype = normalizePinType(pin.electricalType)
                if ["passive", "free", "unspecified"].contains(ptype) { continue }
                violations.append(ERCViolation(
                    severity: .error, checkId: "ERC_UNCONNECTED_PIN",
                    description: "Pin \(pin.ref).\(pin.number) (\(ptype)) is not connected.",
                    ref: pin.ref, pin: pin.number, position: pin.position
                ))
            }
        }
        return violations
    }

    // MARK: - Check 4: Dangling Wires

    static func checkDanglingWires(
        wires: [(start: (Double, Double), end: (Double, Double))],
        connectionPoints: Set<PositionKey>
    ) -> [ERCViolation] {
        var violations: [ERCViolation] = []
        var wireEndpoints: [PositionKey: Int] = [:]

        for wire in wires {
            let s = roundPos(wire.start.0, wire.start.1)
            let e = roundPos(wire.end.0, wire.end.1)
            wireEndpoints[s, default: 0] += 1
            wireEndpoints[e, default: 0] += 1
        }

        for wire in wires {
            for endpoint in [wire.start, wire.end] {
                let pos = roundPos(endpoint.0, endpoint.1)
                if connectionPoints.contains(pos) { continue }
                if (wireEndpoints[pos] ?? 0) >= 2 { continue }
                violations.append(ERCViolation(
                    severity: .warning, checkId: "ERC_WIRE_DANGLING",
                    description: String(format: "Wire endpoint at (%.2f, %.2f) not connected", pos.x100/100, pos.y100/100),
                    position: endpoint
                ))
            }
        }
        return violations
    }

    // MARK: - Main Entry Point

    static func run(schematicURL: URL) -> NativeErcResult {
        var checksRun: [String] = []
        var checksSkipped: [String] = []
        var allViolations: [ERCViolation] = []

        // Parse schematic
        let ir: SchematicIR
        do {
            ir = try SchematicParser.parse(schematicURL)
            checksRun.append("schematic_parse")
        } catch {
            return NativeErcResult(
                violations: [ERCViolation(
                    severity: .error, checkId: "ERC_PARSE_ERROR",
                    description: "Failed to parse schematic: \(error)"
                )],
                checksRun: [], checksSkipped: ["all"]
            )
        }

        // Resolve pins: match symbol instances to lib symbol pins
        let pins = resolvePins(ir: ir)
        checksRun.append("pin_resolution")

        // Build pin position list for topology
        let pinPositions = pins.map { (ref: $0.ref, number: $0.pinNumber, position: $0.position) }

        // Resolve net connectivity
        let pinNets = TopologyBuilder.resolvePinNets(
            pins: pinPositions,
            wires: ir.wires.map { ($0.start, $0.end) },
            labels: ir.labels.map { ($0.name, $0.position) }
        )
        checksRun.append("topology_resolution")

        // Attach net names to pins
        let resolvedPins = pins.map { pin -> ResolvedPin in
            let netKey = "\(pin.ref).\(pin.pinNumber)"
            return ResolvedPin(
                ref: pin.ref, number: pin.pinNumber, name: pin.pinName,
                electricalType: pin.electricalType,
                position: pin.position,
                netName: pinNets[netKey]
            )
        }

        // Build NC position set
        let ncPositions = Set(ir.noConnects.map { roundPos($0.x, $0.y) })

        // Build connection points
        var connPoints = Set<PositionKey>()
        for pin in resolvedPins {
            connPoints.insert(roundPos(pin.position.0, pin.position.1))
        }
        for label in ir.labels {
            connPoints.insert(roundPos(label.position.0, label.position.1))
        }

        // Run checks
        allViolations.append(contentsOf: checkPinTypeConflicts(resolvedPins))
        checksRun.append("pin_type_conflicts")

        allViolations.append(contentsOf: checkPowerNets(resolvedPins))
        checksRun.append("power_net_validation")

        allViolations.append(contentsOf: checkNoConnects(pins: resolvedPins, noConnectPositions: ncPositions))
        checksRun.append("no_connect_validation")

        allViolations.append(contentsOf: checkDanglingWires(
            wires: ir.wires.map { ($0.start, $0.end) },
            connectionPoints: connPoints
        ))
        checksRun.append("dangling_wires")

        return NativeErcResult(
            violations: allViolations,
            checksRun: checksRun,
            checksSkipped: checksSkipped
        )
    }

    // MARK: - Pin Resolution

    /// Match symbol instances to their lib symbol definitions and compute
    /// absolute pin positions.
    private static func resolvePins(ir: SchematicIR) -> [PinInfo] {
        var libIndex: [String: LibSymbol] = [:]
        for ls in ir.libSymbols {
            libIndex[ls.libId] = ls
        }

        var pins: [PinInfo] = []

        for sym in ir.symbols {
            guard let libSym = libIndex[sym.libId] else { continue }
            for libPin in libSym.pins {
                // Compute absolute pin position (symbol position + pin offset)
                // Note: KiCad pins are relative to the lib symbol origin.
                // For simple schematics without rotation, we add the symbol position.
                // TODO: handle rotation/mirror for full accuracy.
                let absX = sym.position.x + libPin.position.x
                let absY = sym.position.y + libPin.position.y

                pins.append(PinInfo(
                    ref: sym.reference,
                    pinNumber: libPin.number,
                    pinName: libPin.name,
                    position: (absX, absY),
                    electricalType: libPin.electricalType
                ))
            }
        }
        return pins
    }
}

// MARK: - WireInfo/LabelInfo tuple conversion helpers

extension WireInfo {
    var startTuple: (Double, Double) { (start.x, start.y) }
    var endTuple: (Double, Double) { (end.x, end.y) }
}
