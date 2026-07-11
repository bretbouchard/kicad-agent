//
//  VoltaEngine.swift
//  Phase 224 — Swift Operation Executor
//
//  Replaces the Python daemon for KiCad file operations.
//  Parses .kicad_sch / .kicad_pcb via SExpr, mutates the tree,
//  serializes back to valid KiCad S-expression text.
//
//  Scoped to 30 critical ops for iOS. The remaining 130 ops stay
//  daemon-backed on Mac until later phases.
//

import Foundation
import OSLog

// MARK: - Operation Protocol

/// A KiCad file operation. Parse params from JSON, execute, return result.
protocol VoltaOperation {
    var opType: String { get }
    var readOnly: Bool { get }
    func execute(params: [String: Any], on fileURL: URL) throws -> [String: Any]
}

// MARK: - VoltaEngine (replaces ProcessManager + DaemonMessenger + MCPClient)

/// The native Swift engine for KiCad file operations.
/// Replaces the 141MB Python daemon for App Store sandbox builds.
///
/// Usage:
/// ```
/// let engine = VoltaEngine()
/// let result = try await engine.execute("add_component", params: [...], on: fileURL)
/// ```
@MainActor
@Observable
final class VoltaEngine {
    private(set) var isReady = true  // Always ready — no daemon to spawn

    /// All registered operations, keyed by op type.
    private let operations: [String: VoltaOperation]

    init() {
        var ops: [String: VoltaOperation] = [:]
        for op in VoltaEngine.builtinOperations {
            ops[op.opType] = op
        }
        self.operations = ops
        Logger.appShell.info("VoltaEngine initialized with \(ops.count) operations")
    }

    /// Execute an operation on a file.
    func execute(_ opType: String, params: [String: Any], on fileURL: URL) throws -> [String: Any] {
        guard let op = operations[opType] else {
            throw VoltaEngineError.unknownOperation(opType)
        }
        return try op.execute(params: params, on: fileURL)
    }

    /// List all registered operation types.
    var availableOperations: [String] {
        Array(operations.keys).sorted()
    }

    // MARK: - Built-in Operations

    static let builtinOperations: [VoltaOperation] = [
        // Query ops (read-only)
        ListComponentsOp(),
        ListNetsOp(),
        ListNetClassesOp(),
        GetComponentOp(),
        GetPropertiesOp(),
        CountComponentsOp(),

        // Component ops
        AddComponentOp(),
        RemoveComponentOp(),
        DuplicateComponentOp(),
        ModifyPropertyOp(),

        // Wire ops
        AddWireOp(),
        RemoveWireOp(),
        AddLabelOp(),
        AddJunctionOp(),
        AddNoConnectOp(),

        // Power ops
        AddPowerOp(),

        // Create ops
        CreateSchematicOp(),
        CreatePCBOp(),

        // Validation ops
        RunNativeERCOp(),
        RunNativeDRCOp(),
        RunStructuralCheckOp(),

        // Reference ops
        AnnotateOp(),
    ]
}

enum VoltaEngineError: Error, LocalizedError {
    case unknownOperation(String)
    case parseError(String)
    case fileError(String)
    case validationError(String)

    var errorDescription: String? {
        switch self {
        case .unknownOperation(let op): return "Unknown operation: \(op)"
        case .parseError(let msg): return "Parse error: \(msg)"
        case .fileError(let msg): return "File error: \(msg)"
        case .validationError(let msg): return "Validation error: \(msg)"
        }
    }
}

// MARK: - SExpr Mutation Helpers

extension SExpr {
    /// Serialize back to KiCad S-expression text.
    func serialize(indent: Int = 0) -> String {
        let pad = String(repeating: "  ", count: indent)
        switch self {
        case .atom(let s):
            return pad + s
        case .string(let s):
            return pad + "\"\(s)\""
        case .list(let head, let children):
            if children.isEmpty {
                return "\(pad)(\(head))"
            }
            // Single-line for short lists, multi-line for nested
            let hasNested = children.contains { $0.head != nil }
            if !hasNested && children.count <= 4 {
                let parts = children.map { $0.serialize() }
                return "\(pad)(\(head) \(parts.joined(separator: " ")))"
            }
            var lines = ["\(pad)(\(head)"]
            for child in children {
                lines.append(child.serialize(indent: indent + 1))
            }
            lines.append("\(pad))")
            return lines.joined(separator: "\n")
        }
    }

    /// Append a child to this list (returns a new SExpr — immutable).
    func appending(_ child: SExpr) -> SExpr {
        guard case .list(let head, var children) = self else { return self }
        children.append(child)
        return .list(head, children)
    }

    /// Replace children matching a predicate.
    func replacingChildren(where predicate: (SExpr) -> Bool, with replacement: (SExpr) -> SExpr) -> SExpr {
        guard case .list(let head, let children) = self else { return self }
        let newChildren = children.map { child in
            predicate(child) ? replacement(child) : child
        }
        return .list(head, newChildren)
    }

    /// Remove children matching a predicate.
    func removingChildren(where predicate: (SExpr) -> Bool) -> SExpr {
        guard case .list(let head, let children) = self else { return self }
        return .list(head, children.filter { !predicate($0) })
    }
}

// MARK: - Query Operations

struct ListComponentsOp: VoltaOperation {
    let opType = "list_components"
    let readOnly = true

    func execute(params: [String: Any], on fileURL: URL) throws -> [String: Any] {
        let ir = try SchematicParser.parse(fileURL)
        let components = ir.symbols.map { sym -> [String: String] in
            ["reference": sym.reference, "lib_id": sym.libId]
        }
        return ["components": components, "count": components.count]
    }
}

struct ListNetsOp: VoltaOperation {
    let opType = "list_nets"
    let readOnly = true

    func execute(params: [String: Any], on fileURL: URL) throws -> [String: Any] {
        let ir = try SchematicParser.parse(fileURL)
        let pins = NativeERC.resolvePinsForListing(ir: ir)
        let pinNets = TopologyBuilder.resolvePinNets(
            pins: pins.map { (ref: $0.ref, number: $0.pinNumber, position: $0.position) },
            wires: ir.wires.map { ($0.start, $0.end) },
            labels: ir.labels.map { ($0.name, $0.position) }
        )
        var nets = Set<String>()
        for netName in pinNets.values {
            nets.insert(netName)
        }
        return ["nets": Array(nets).sorted(), "count": nets.count]
    }
}

struct ListNetClassesOp: VoltaOperation {
    let opType = "list_net_classes"
    let readOnly = true

    func execute(params: [String: Any], on fileURL: URL) throws -> [String: Any] {
        guard fileURL.pathExtension == "kicad_pcb" else {
            return ["net_classes": [], "count": 0]
        }
        let board = try PCBParser.parse(fileURL)
        let classes = board.netClasses.map { nc -> [String: Any] in
            ["name": nc.name, "track_width": nc.trackWidth, "clearance": nc.clearance]
        }
        return ["net_classes": classes, "count": classes.count]
    }
}

struct GetComponentOp: VoltaOperation {
    let opType = "get_component"
    let readOnly = true

    func execute(params: [String: Any], on fileURL: URL) throws -> [String: Any] {
        let ref = params["reference"] as? String ?? ""
        let ir = try SchematicParser.parse(fileURL)
        guard let sym = ir.symbols.first(where: { $0.reference == ref }) else {
            throw VoltaEngineError.validationError("Component \(ref) not found")
        }
        return ["reference": sym.reference, "lib_id": sym.libId,
                "x": sym.position.x, "y": sym.position.y]
    }
}

struct GetPropertiesOp: VoltaOperation {
    let opType = "get_properties"
    let readOnly = true

    func execute(params: [String: Any], on fileURL: URL) throws -> [String: Any] {
        let ref = params["reference"] as? String ?? ""
        let sexpr = try SExpr.parse(fileURL: fileURL)
        // Find symbol node with matching reference
        for symNode in sexpr.findAll("symbol") {
            for child in symNode.children where child.head == "property" {
                if child.childString(0) == "Reference" && child.childString(1) == ref {
                    // Extract all properties
                    var props: [String: String] = [:]
                    for prop in symNode.findAll("property") {
                        let name = prop.childString(0) ?? ""
                        let value = prop.childString(1) ?? ""
                        props[name] = value
                    }
                    return ["reference": ref, "properties": props]
                }
            }
        }
        throw VoltaEngineError.validationError("Component \(ref) not found")
    }
}

struct CountComponentsOp: VoltaOperation {
    let opType = "count_components"
    let readOnly = true

    func execute(params: [String: Any], on fileURL: URL) throws -> [String: Any] {
        let ir = try SchematicParser.parse(fileURL)
        return ["count": ir.symbols.count]
    }
}

// MARK: - Component Operations

struct AddComponentOp: VoltaOperation {
    let opType = "add_component"
    let readOnly = false

    func execute(params: [String: Any], on fileURL: URL) throws -> [String: Any] {
        let libId = params["lib_id"] as? String ?? ""
        let reference = params["reference"] as? String ?? "U?"
        let x = params["x"] as? Double ?? 100.0
        let y = params["y"] as? Double ?? 100.0

        var sexpr = try SExpr.parse(fileURL: fileURL)

        // Create the symbol node
        let symNode = SExpr.list("symbol", [
            .list("at", [.atom(String(x)), .atom(String(y)), .atom("0")]),
            .list("property", [.string("Reference"), .string(reference)]),
            .list("lib_id", [.string(libId)]),
        ])
        sexpr = sexpr.appending(symNode)

        // Write back
        try sexpr.serialize().write(to: fileURL, atomically: true, encoding: .utf8)

        return ["status": "ok", "reference": reference, "lib_id": libId]
    }
}

struct RemoveComponentOp: VoltaOperation {
    let opType = "remove_component"
    let readOnly = false

    func execute(params: [String: Any], on fileURL: URL) throws -> [String: Any] {
        let reference = params["reference"] as? String ?? ""
        var sexpr = try SExpr.parse(fileURL: fileURL)

        sexpr = sexpr.removingChildren { node in
            guard node.head == "symbol" else { return false }
            // Check if this symbol's Reference matches
            for child in node.children where child.head == "property" {
                if child.childString(0) == "Reference" && child.childString(1) == reference {
                    return true
                }
            }
            return false
        }

        try sexpr.serialize().write(to: fileURL, atomically: true, encoding: .utf8)
        return ["status": "ok", "removed": reference]
    }
}

struct DuplicateComponentOp: VoltaOperation {
    let opType = "duplicate_component"
    let readOnly = false

    func execute(params: [String: Any], on fileURL: URL) throws -> [String: Any] {
        let reference = params["reference"] as? String ?? ""
        let newRef = params["new_reference"] as? String ?? reference + "_copy"
        let offsetX = params["offset_x"] as? Double ?? 10.0
        let offsetY = params["offset_y"] as? Double ?? 10.0

        var sexpr = try SExpr.parse(fileURL: fileURL)

        // Find the source component
        var sourceNode: SExpr?
        for child in sexpr.children where child.head == "symbol" {
            for prop in child.children where prop.head == "property" {
                if prop.childString(0) == "Reference" && prop.childString(1) == reference {
                    sourceNode = child
                    break
                }
            }
        }

        guard let source = sourceNode else {
            throw VoltaEngineError.validationError("Component \(reference) not found")
        }

        // Clone with offset position and new reference
        let dup = source.replacingChildren(where: { $0.head == "property" && $0.childString(0) == "Reference" }) { _ in
            .list("property", [.string("Reference"), .string(newRef)])
        }.replacingChildren(where: { $0.head == "at" }) { atNode in
            let x = (atNode.childDouble(0) ?? 0) + offsetX
            let y = (atNode.childDouble(1) ?? 0) + offsetY
            return .list("at", [.atom(String(x)), .atom(String(y)), .atom("0")])
        }

        sexpr = sexpr.appending(dup)
        try sexpr.serialize().write(to: fileURL, atomically: true, encoding: .utf8)
        return ["status": "ok", "new_reference": newRef]
    }
}

struct ModifyPropertyOp: VoltaOperation {
    let opType = "modify_property"
    let readOnly = false

    func execute(params: [String: Any], on fileURL: URL) throws -> [String: Any] {
        let reference = params["reference"] as? String ?? ""
        let propName = params["property_name"] as? String ?? ""
        let propValue = params["property_value"] as? String ?? ""

        var sexpr = try SExpr.parse(fileURL: fileURL)

        sexpr = sexpr.replacingChildren(where: { node in
            guard node.head == "symbol" else { return false }
            return node.children.contains { child in
                child.head == "property" && child.childString(0) == "Reference" && child.childString(1) == reference
            }
        }) { symNode in
            symNode.replacingChildren(where: { $0.head == "property" && $0.childString(0) == propName }) { _ in
                .list("property", [.string(propName), .string(propValue)])
            }
        }

        try sexpr.serialize().write(to: fileURL, atomically: true, encoding: .utf8)
        return ["status": "ok", "\(reference).\(propName)": propValue]
    }
}

// MARK: - Wire Operations

struct AddWireOp: VoltaOperation {
    let opType = "add_wire"
    let readOnly = false

    func execute(params: [String: Any], on fileURL: URL) throws -> [String: Any] {
        let x1 = params["x1"] as? Double ?? 0
        let y1 = params["y1"] as? Double ?? 0
        let x2 = params["x2"] as? Double ?? 0
        let y2 = params["y2"] as? Double ?? 0

        var sexpr = try SExpr.parse(fileURL: fileURL)
        let wire = SExpr.list("wire", [
            .list("pts", [
                .list("xy", [.atom(String(x1)), .atom(String(y1))]),
                .list("xy", [.atom(String(x2)), .atom(String(y2))]),
            ])
        ])
        sexpr = sexpr.appending(wire)
        try sexpr.serialize().write(to: fileURL, atomically: true, encoding: .utf8)
        return ["status": "ok"]
    }
}

struct RemoveWireOp: VoltaOperation {
    let opType = "remove_wire"
    let readOnly = false

    func execute(params: [String: Any], on fileURL: URL) throws -> [String: Any] {
        let x1 = params["x1"] as? Double ?? 0
        let y1 = params["y1"] as? Double ?? 0
        let x2 = params["x2"] as? Double ?? 0
        let y2 = params["y2"] as? Double ?? 0

        var sexpr = try SExpr.parse(fileURL: fileURL)
        sexpr = sexpr.removingChildren { node in
            guard node.head == "wire" else { return false }
            guard let pts = node.find("pts") else { return false }
            let xyNodes = pts.findAll("xy")
            guard xyNodes.count >= 2 else { return false }
            let sx = xyNodes[0].childDouble(0) ?? 999
            let sy = xyNodes[0].childDouble(1) ?? 999
            let ex = xyNodes[1].childDouble(0) ?? 999
            let ey = xyNodes[1].childDouble(1) ?? 999
            // Match start or end (wire direction doesn't matter)
            return (abs(sx-x1)<0.01 && abs(sy-y1)<0.01 && abs(ex-x2)<0.01 && abs(ey-y2)<0.01) ||
                   (abs(sx-x2)<0.01 && abs(sy-y2)<0.01 && abs(ex-x1)<0.01 && abs(ey-y1)<0.01)
        }
        try sexpr.serialize().write(to: fileURL, atomically: true, encoding: .utf8)
        return ["status": "ok"]
    }
}

struct AddLabelOp: VoltaOperation {
    let opType = "add_label"
    let readOnly = false

    func execute(params: [String: Any], on fileURL: URL) throws -> [String: Any] {
        let name = params["name"] as? String ?? ""
        let x = params["x"] as? Double ?? 0
        let y = params["y"] as? Double ?? 0

        var sexpr = try SExpr.parse(fileURL: fileURL)
        let label = SExpr.list("label", [
            .string(name),
            .list("at", [.atom(String(x)), .atom(String(y)), .atom("0")]),
        ])
        sexpr = sexpr.appending(label)
        try sexpr.serialize().write(to: fileURL, atomically: true, encoding: .utf8)
        return ["status": "ok", "label": name]
    }
}

struct AddJunctionOp: VoltaOperation {
    let opType = "add_junction"
    let readOnly = false

    func execute(params: [String: Any], on fileURL: URL) throws -> [String: Any] {
        let x = params["x"] as? Double ?? 0
        let y = params["y"] as? Double ?? 0

        var sexpr = try SExpr.parse(fileURL: fileURL)
        let junction = SExpr.list("junction", [
            .list("at", [.atom(String(x)), .atom(String(y))]),
        ])
        sexpr = sexpr.appending(junction)
        try sexpr.serialize().write(to: fileURL, atomically: true, encoding: .utf8)
        return ["status": "ok"]
    }
}

struct AddNoConnectOp: VoltaOperation {
    let opType = "add_no_connect"
    let readOnly = false

    func execute(params: [String: Any], on fileURL: URL) throws -> [String: Any] {
        let x = params["x"] as? Double ?? 0
        let y = params["y"] as? Double ?? 0

        var sexpr = try SExpr.parse(fileURL: fileURL)
        let nc = SExpr.list("no_connect", [
            .list("at", [.atom(String(x)), .atom(String(y))]),
        ])
        sexpr = sexpr.appending(nc)
        try sexpr.serialize().write(to: fileURL, atomically: true, encoding: .utf8)
        return ["status": "ok"]
    }
}

struct AddPowerOp: VoltaOperation {
    let opType = "add_power"
    let readOnly = false

    func execute(params: [String: Any], on fileURL: URL) throws -> [String: Any] {
        let netName = params["net_name"] as? String ?? "VCC"
        let x = params["x"] as? Double ?? 0
        let y = params["y"] as? Double ?? 0

        var sexpr = try SExpr.parse(fileURL: fileURL)
        // Power symbols use #PWR references
        let powerSym = SExpr.list("symbol", [
            .list("at", [.atom(String(x)), .atom(String(y)), .atom("0")]),
            .list("property", [.string("Reference"), .string("#PWR?")]),
            .list("property", [.string("Value"), .string(netName)]),
            .list("lib_id", [.string("power:\(netName)")]),
        ])
        sexpr = sexpr.appending(powerSym)
        try sexpr.serialize().write(to: fileURL, atomically: true, encoding: .utf8)
        return ["status": "ok", "net": netName]
    }
}

// MARK: - Create Operations

struct CreateSchematicOp: VoltaOperation {
    let opType = "create_schematic"
    let readOnly = false

    func execute(params: [String: Any], on fileURL: URL) throws -> [String: Any] {
        let template = """
        (kicad_sch (version 20241129) (generator "volta-pcb")
          (paper "A4")
          (lib_symbols)
          (symbols)
          (sheets)
          (instances)
        )
        """
        try template.write(to: fileURL, atomically: true, encoding: .utf8)
        return ["status": "ok", "path": fileURL.path]
    }
}

struct CreatePCBOp: VoltaOperation {
    let opType = "create_pcb"
    let readOnly = false

    func execute(params: [String: Any], on fileURL: URL) throws -> [String: Any] {
        let template = """
        (kicad_pcb (version 20241129) (generator "volta-pcb")
          (general (thickness 1.6))
          (paper "A4")
          (layers
            (0 "F.Cu" signal)
            (31 "B.Cu" signal)
            (32 "B.Adhes" user)
            (33 "F.Adhes" user)
            (34 "B.Paste" user)
            (35 "F.Paste" user)
            (36 "B.SilkS" user)
            (37 "F.SilkS" user)
            (38 "B.Mask" user)
            (39 "F.Mask" user)
            (44 "Edge.Cuts" user)
          )
          (setup
            (pad_to_mask_clearance 0.05)
          )
          (net 0 "")
        )
        """
        try template.write(to: fileURL, atomically: true, encoding: .utf8)
        return ["status": "ok", "path": fileURL.path]
    }
}

// MARK: - Validation Operations

struct RunNativeERCOp: VoltaOperation {
    let opType = "run_native_erc"
    let readOnly = true

    func execute(params: [String: Any], on fileURL: URL) throws -> [String: Any] {
        let result = NativeERC.run(schematicURL: fileURL)
        return result.toDict()
    }
}

struct RunNativeDRCOp: VoltaOperation {
    let opType = "run_native_drc"
    let readOnly = true

    func execute(params: [String: Any], on fileURL: URL) throws -> [String: Any] {
        // DRC needs a PCB file — parse and run checks
        let board = try PCBParser.parse(fileURL)
        var violations: [DRCViolation] = []

        // Check track widths
        let segments = board.segments.map { seg in
            (start: CGPoint(seg.start.x, seg.start.y),
             end: CGPoint(seg.end.x, seg.end.y),
             width: seg.width, net: seg.netName, layer: seg.layer)
        }
        violations.append(contentsOf: NativeDRC.checkTrackWidths(segments: segments))

        return ["clean": violations.filter { $0.severity == "error" }.isEmpty,
                "error_count": violations.filter { $0.severity == "error" }.count,
                "violations": violations.map { $0.toDict() }]
    }
}

struct RunStructuralCheckOp: VoltaOperation {
    let opType = "run_structural_check"
    let readOnly = true

    func execute(params: [String: Any], on fileURL: URL) throws -> [String: Any] {
        // Structural validation: parse the file and check for issues
        _ = try SExpr.parse(fileURL: fileURL)  // Will throw on malformed files
        return ["status": "ok", "format": "valid"]
    }
}

// MARK: - Reference Operations

struct AnnotateOp: VoltaOperation {
    let opType = "annotate"
    let readOnly = false

    func execute(params: [String: Any], on fileURL: URL) throws -> [String: Any] {
        let ir = try SchematicParser.parse(fileURL)

        // Group by prefix and assign sequential numbers
        var prefixCounters: [String: Int] = [:]
        var annotations: [[String: String]] = []

        for sym in ir.symbols {
            let ref = sym.reference
            // Extract prefix (letters before the number)
            let prefix = String(ref.prefix { $0.isLetter })
            prefixCounters[String(prefix), default: 0] += 1
            let newRef = "(prefix)(prefixCounters[prefix] ?? 0)"
            annotations.append(["old": ref, "new": newRef])
        }

        return ["annotations": annotations, "count": annotations.count]
    }
}

// MARK: - Helper Extensions

extension NativeERC {
    /// Expose pin resolution for query ops.
    static func resolvePinsForListing(ir: SchematicIR) -> [PinInfo] {
        // Same as resolvePins but accessible from query ops
        var libIndex: [String: LibSymbol] = [:]
        for ls in ir.libSymbols {
            libIndex[ls.libId] = ls
        }

        var pins: [PinInfo] = []
        for sym in ir.symbols {
            guard let libSym = libIndex[sym.libId] else { continue }
            for libPin in libSym.pins {
                let absX = sym.position.x + libPin.position.x
                let absY = sym.position.y + libPin.position.y
                pins.append(PinInfo(
                    ref: sym.reference, pinNumber: libPin.number,
                    pinName: libPin.name, position: (absX, absY),
                    electricalType: libPin.electricalType
                ))
            }
        }
        return pins
    }
}
