import Foundation
import CryptoKit
import GSAModeledWorld

/// The governed-electronics schema inside the Modeled World (M2.3,
/// complete): type names and the stable-identity rule that maps Volta's
/// existing KiCad-model IDs onto GSA object identities (KERNEL-001).
/// Identity is derived deterministically, so the same Volta
/// project/schematic/component imports to the same `WorldObjectID` across
/// restarts, processes, and re-imports — unlike the app-side
/// `GSAPlatformHost` seed, which minted fresh `WorldObjectID()`s and
/// matched objects by "first live of type".
///
/// ## Schema grounding (Volta sources)
///
/// Every type name below maps onto a concrete type in Volta's KiCad model
/// layer (`macos-app/Sources/Volta/…`):
///
/// - `electronics.project` ← `Project` (SwiftData `@Model`,
///   `Models/Project.swift`): top-level container with a stable `id: UUID`
///   that is never user-visible — that UUID is the legacy identity this
///   schema hashes.
/// - `electronics.schematic` ← `SchematicIR` (`Parsing/SchematicParser.swift`,
///   Phase 221): one parsed `.kicad_sch` (version, symbols, wires, labels).
/// - `electronics.sheet` ← hierarchical sheets of a schematic
///   (`SchematicParser` label/hierarchy handling; `multi_sheet_*` fixtures).
/// - `electronics.symbol` ← `LibSymbol` (`Parsing/SchematicParser.swift`):
///   a `lib_symbols` entry with `LibPin`s carrying electrical types.
/// - `electronics.component` ← `SymbolInstance`
///   (`Parsing/SchematicParser.swift`): a placed component identified by its
///   reference designator (`R1`, `C2`, …) and `libId` (`Device:C`).
/// - `electronics.net` ← `PCBNet` (`Parsing/PCBParser.swift`, Phase 223) and
///   the union-find nets of `TopologyBuilder` (`Parsing/TopologyBuilder.swift`).
/// - `electronics.bus` ← KiCad bus aggregates crossing sheets; Volta's
///   S-expression layer models these alongside labels/wires.
/// - `electronics.pcb` ← `PCBBoard` (`Parsing/PCBParser.swift`): one parsed
///   `.kicad_pcb` (footprints, segments, vias, nets, layers).
/// - `electronics.footprint` ← `PCBFootprint` (`Parsing/PCBParser.swift`):
///   placed footprint with `PCBPad`s and net assignments.
/// - `electronics.bom` ← `BOMLineItem` (`Views/BOM/BOMView.swift`).
/// - `electronics.assembly` ← assembly provider results
///   (`Providers/JLCPCB` `AssemblyAvailability` et al.).
/// - `electronics.verification.artifact` ← `VerificationOutcome`
///   (`Governance/VerificationLoop.swift`) and the ERC/DRC outputs of
///   `Validation/NativeERC.swift` / `Validation/NativeDRC.swift`. The type
///   name matches the one the app-side `GSAPlatformHost` already writes, so
///   the two embeddings converge on one schema.
public enum ElectronicsSchema {
    /// A whole board project as persisted today (SwiftData `Project`).
    public static let projectType = "electronics.project"
    /// One parsed `.kicad_sch` document (`SchematicIR`).
    public static let schematicType = "electronics.schematic"
    /// One hierarchical sheet of a schematic.
    public static let sheetType = "electronics.sheet"
    /// One `lib_symbols` entry (`LibSymbol`).
    public static let symbolType = "electronics.symbol"
    /// One placed component (`SymbolInstance`), identified by reference
    /// designator.
    public static let componentType = "electronics.component"
    /// One electrical net (`PCBNet` / `TopologyBuilder` cluster).
    public static let netType = "electronics.net"
    /// One bus aggregate.
    public static let busType = "electronics.bus"
    /// One parsed `.kicad_pcb` document (`PCBBoard`).
    public static let pcbType = "electronics.pcb"
    /// One placed footprint (`PCBFootprint`).
    public static let footprintType = "electronics.footprint"
    /// One bill of materials (`BOMLineItem` aggregation).
    public static let bomType = "electronics.bom"
    /// One assembly-provider run.
    public static let assemblyType = "electronics.assembly"
    /// One verification output (ERC/DRC/`VerificationOutcome`).
    public static let verificationArtifactType = "electronics.verification.artifact"

    /// All governed-electronics type names, for grant scopes and projections.
    public static let allTypeNames: Set<String> = [
        projectType,
        schematicType,
        sheetType,
        symbolType,
        componentType,
        netType,
        busType,
        pcbType,
        footprintType,
        bomType,
        assemblyType,
        verificationArtifactType,
    ]

    /// Deterministic `WorldObjectID` for a legacy Volta identifier: SHA-256
    /// over "volta:<legacyID>", laid into a UUID with RFC 4122 version-5
    /// bits so it round-trips through `UUID(uuidString:)`. Same legacy ID →
    /// same object identity, forever. The legacy ID is whatever Volta
    /// already uses as its stable key: the `Project.id` UUID, a schematic
    /// file name, or a `<projectID>/component/<reference>` composite.
    public static func stableObjectID(legacyID: String) -> WorldObjectID {
        let digest = SHA256.hash(data: Data("volta:\(legacyID)".utf8))
        var bytes = Array(digest.prefix(16))
        bytes[6] = (bytes[6] & 0x0F) | 0x50 // version 5
        bytes[8] = (bytes[8] & 0x3F) | 0x80 // RFC 4122 variant
        let u = bytes
        let uuid = uuid_t(
            u[0], u[1], u[2], u[3], u[4], u[5], u[6], u[7],
            u[8], u[9], u[10], u[11], u[12], u[13], u[14], u[15]
        )
        return WorldObjectID(value: UUID(uuid: uuid))
    }

    /// Object identity for one schematic of a project. `schematicKey` is
    /// the schematic's stable key inside Volta — by convention the
    /// `.kicad_sch` file name (e.g. `"x64-smart-grid.kicad_sch"`).
    public static func schematicID(projectLegacyID: String, schematicKey: String) -> WorldObjectID {
        stableObjectID(legacyID: "\(projectLegacyID)/schematic/\(schematicKey)")
    }

    /// Object identity for one sheet of a schematic.
    public static func sheetID(projectLegacyID: String, schematicKey: String, sheetName: String) -> WorldObjectID {
        stableObjectID(legacyID: "\(projectLegacyID)/schematic/\(schematicKey)/sheet/\(sheetName)")
    }

    /// Object identity for one component (placed symbol instance) of a
    /// schematic. Reference designators (`R1`, `C2`) are unique per
    /// schematic in KiCad's annotate model, which Volta's `SymbolInstance`
    /// preserves via `reference`.
    public static func componentID(projectLegacyID: String, schematicKey: String, reference: String) -> WorldObjectID {
        stableObjectID(legacyID: "\(projectLegacyID)/schematic/\(schematicKey)/component/\(reference)")
    }

    /// Object identity for one symbol library entry.
    public static func symbolID(projectLegacyID: String, libID: String) -> WorldObjectID {
        stableObjectID(legacyID: "\(projectLegacyID)/symbol/\(libID)")
    }

    /// Object identity for one net of a project. Net names (`GND`,
    /// `+3V3`, `/SDA`) are unique per board in both `PCBNet` and
    /// `TopologyBuilder`'s union-find output.
    public static func netID(projectLegacyID: String, netName: String) -> WorldObjectID {
        stableObjectID(legacyID: "\(projectLegacyID)/net/\(netName)")
    }

    /// Object identity for one bus of a project.
    public static func busID(projectLegacyID: String, busName: String) -> WorldObjectID {
        stableObjectID(legacyID: "\(projectLegacyID)/bus/\(busName)")
    }

    /// Object identity for the board's PCB (`PCBBoard`).
    public static func pcbID(projectLegacyID: String) -> WorldObjectID {
        stableObjectID(legacyID: "\(projectLegacyID)/pcb")
    }

    /// Object identity for one placed footprint.
    public static func footprintID(projectLegacyID: String, reference: String) -> WorldObjectID {
        stableObjectID(legacyID: "\(projectLegacyID)/footprint/\(reference)")
    }

    /// Object identity for a project's BOM.
    public static func bomID(projectLegacyID: String) -> WorldObjectID {
        stableObjectID(legacyID: "\(projectLegacyID)/bom")
    }

    /// Object identity for an assembly run.
    public static func assemblyID(projectLegacyID: String, assemblyKey: String) -> WorldObjectID {
        stableObjectID(legacyID: "\(projectLegacyID)/assembly/\(assemblyKey)")
    }

    /// Object identity for one verification artifact (ERC/DRC run).
    public static func verificationArtifactID(projectLegacyID: String, checkType: String) -> WorldObjectID {
        stableObjectID(legacyID: "\(projectLegacyID)/verification/\(checkType)")
    }
}

/// Principals Volta records on governed changes and capability calls.
/// Raw values follow the platform's `kind:name` convention — matching the
/// app-side `GSAPlatformHost` principals so both embeddings share one
/// authority namespace.
public enum VoltaPrincipals {
    /// The human owner, e.g. `VoltaPrincipals.human("bret")`.
    public static func human(_ name: String) -> Principal {
        Principal(rawValue: "human:\(name)")
    }

    /// The embedding product itself (UI-driven world edits). Matches
    /// `GSAPlatformHost`'s `"system:volta-app"`.
    public static let product = Principal(rawValue: "system:volta-app")

    /// The board agent (capability-only authority, granted via approval).
    public static let boardAgent = Principal(rawValue: "capability:volta.board-agent")

    /// Product bootstrap; grants issued at boot name it as grantor.
    public static let bootstrap = Principal(rawValue: "system:volta-app.bootstrap")
}
