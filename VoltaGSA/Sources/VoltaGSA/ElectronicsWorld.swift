import Foundation
import GSACore
import GSAModeledWorld
import GSAStewardshipRuntime

/// Failures of the electronics-domain layer itself. Refusals from the
/// platform (policy denials, contract violations) surface as
/// `ContractViolation` from `StewardshipRuntime.transact` and are rethrown
/// unchanged.
public enum ElectronicsWorldError: Error, Equatable {
    case projectNotFound(WorldObjectID)
    case schematicNotFound(WorldObjectID)
    case componentNotFound(WorldObjectID)
    /// Deleted identities are never reused (KERNEL-001/003); re-importing a
    /// deleted legacy project is refused rather than silently resurrected.
    case deletedLegacyID(String)
    case malformedState(String)
}

// MARK: - Domain documents (grounded in Volta's KiCad models)

/// A whole board project ready to enter the governed world. Field-by-field
/// this mirrors what Volta already has:
///
/// - `legacyID` ← the SwiftData `Project.id` UUID (`Models/Project.swift`),
///   the stable, never-user-visible key.
/// - `name`/`projectDescription` ← `Project.name`/`Project.projectDescription`.
/// - `schematics` ← the parsed `SchematicIR` documents
///   (`Parsing/SchematicParser.swift`, Phase 221) of the project's
///   `.kicad_sch` files.
///
/// The type is `Codable` so it round-trips losslessly through the Modeled
/// World (stored verbatim on the project object) and can be built directly
/// from Volta's parser output without any intermediate format.
public struct ElectronicsDocument: Codable, Sendable, Equatable {
    public let legacyID: String
    public var name: String
    public var projectDescription: String
    public var schematics: [SchematicDocument]

    public init(
        legacyID: String,
        name: String,
        projectDescription: String = "",
        schematics: [SchematicDocument] = []
    ) {
        self.legacyID = legacyID
        self.name = name
        self.projectDescription = projectDescription
        self.schematics = schematics
    }
}

/// One parsed `.kicad_sch`, mirroring `SchematicIR`
/// (`Parsing/SchematicParser.swift`): the KiCad file version and the placed
/// symbol instances. Wires, labels, and no-connects stay in the raw file —
/// the governed object carries what has identity and consequence.
public struct SchematicDocument: Codable, Sendable, Equatable {
    /// Stable key inside the project: by convention the `.kicad_sch` file
    /// name (e.g. `"x64-smart-grid.kicad_sch"`).
    public let key: String
    /// The `(version …)` field of the KiCad file / `SchematicIR.version`.
    public let kicadVersion: String
    /// Sheet name for the flat single-sheet case (`"Main"`); hierarchical
    /// projects widen to one `SchematicDocument` per sheet.
    public let sheetName: String
    /// Placed symbol instances (`SchematicIR.symbols: [SymbolInstance]`).
    public var components: [ComponentDocument]

    public init(
        key: String,
        kicadVersion: String,
        sheetName: String = "Main",
        components: [ComponentDocument] = []
    ) {
        self.key = key
        self.kicadVersion = kicadVersion
        self.sheetName = sheetName
        self.components = components
    }
}

/// One placed component, mirroring `SymbolInstance`
/// (`Parsing/SchematicParser.swift`): reference designator, library id,
/// position, mirror — plus the value field KiCad carries on symbol
/// properties and the fitted/DNP state Volta's BOM view
/// (`Views/BOM/BOMView.swift`) projects.
public struct ComponentDocument: Codable, Sendable, Equatable {
    /// Reference designator (`R1`, `C2`, `U3`) — unique per schematic.
    public let reference: String
    /// Library id (`Device:C`, `MCU_ST_STM32F1:...`) — `SymbolInstance.libId`.
    public var libId: String
    /// Component value (`10k`, `100nF`) from symbol properties.
    public var value: String
    /// Whether the component is fitted in this build variant (BOM view).
    public var fitted: Bool
    /// Placement (`SymbolInstance.position`).
    public var x: Double
    public var y: Double
    /// `SymbolInstance.mirror`.
    public var mirror: String?

    public init(
        reference: String,
        libId: String,
        value: String = "",
        fitted: Bool = true,
        x: Double = 0,
        y: Double = 0,
        mirror: String? = nil
    ) {
        self.reference = reference
        self.libId = libId
        self.value = value
        self.fitted = fitted
        self.x = x
        self.y = y
        self.mirror = mirror
    }
}

// MARK: - Projections (Modeled World → domain)

/// A live board project as projected from the Modeled World.
public struct ProjectSummary: Sendable, Equatable {
    public let objectID: WorldObjectID
    public let legacyID: String
    public let name: String
    public let schematicCount: Int
    public let componentCount: Int
    public let version: Int
}

/// One governed schematic of a project.
public struct SchematicRecord: Sendable, Equatable {
    public let objectID: WorldObjectID
    public let projectLegacyID: String
    public let key: String
    public let kicadVersion: String
    public let sheetName: String
    public let componentCount: Int
}

/// One governed component with placement and BOM-visible state.
public struct ComponentRecord: Sendable, Equatable {
    public let objectID: WorldObjectID
    public let projectLegacyID: String
    public let schematicKey: String
    public let reference: String
    public let libId: String
    public let value: String
    public let fitted: Bool
    public let x: Double
    public let y: Double
    public let mirror: String?
}

// MARK: - The governed world facade

/// The electronics domain as governed world objects. Every mutation is a
/// `GovernedChange` applied through `StewardshipRuntime.transact` — there is
/// no other write path (KERNEL-002/003), and every read is a projection of
/// the canonical snapshot (KERNEL-001).
///
/// Foundation-wave scope: project + schematic + component (the kinds the
/// M2.3/M2.4 handoff plan prioritizes). Net, sheet, symbol, bus, pcb,
/// footprint, bom, assembly, and verification artifacts follow this exact
/// pattern once the first governed path is proven end to end.
public struct ElectronicsWorld: Sendable {
    public let runtime: StewardshipRuntime

    public init(runtime: StewardshipRuntime) {
        self.runtime = runtime
    }

    // MARK: - Import (Volta models → Modeled World)

    /// Imports (or re-syncs) an `ElectronicsDocument` into the Modeled
    /// World. Project, schematics, and components are created or updated in
    /// ONE atomic transaction. Re-importing an unchanged document is a
    /// no-op (identity is derived from the legacy IDs, state equality is
    /// checked before writing), so migration is idempotent and safe to
    /// re-run — KiCad files stay authoritative until a governed equivalent
    /// replaces them (M2.3 preservation rule).
    @discardableResult
    public func importDocument(
        _ document: ElectronicsDocument,
        as principal: Principal,
        intent: String? = nil
    ) async throws -> WorldObjectID {
        let projectID = ElectronicsSchema.stableObjectID(legacyID: document.legacyID)
        let snapshot = await runtime.snapshot()

        guard snapshot.objects[projectID]?.status != .deleted else {
            throw ElectronicsWorldError.deletedLegacyID(document.legacyID)
        }
        for schematic in document.schematics {
            let schematicID = ElectronicsSchema.schematicID(
                projectLegacyID: document.legacyID,
                schematicKey: schematic.key
            )
            if snapshot.objects[schematicID]?.status == .deleted {
                throw ElectronicsWorldError.deletedLegacyID(
                    "\(document.legacyID)/schematic/\(schematic.key)"
                )
            }
        }

        let desiredProject = try Self.projectState(for: document)
        var changes: [GovernedChange] = []
        let historyNote = intent ?? "import volta project \(document.legacyID)"

        let existingProject = snapshot.objects[projectID]
        if existingProject == nil {
            changes.append(GovernedChange(
                target: projectID,
                operation: .create(
                    typeName: ElectronicsSchema.projectType,
                    initialState: desiredProject
                ),
                authorizedBy: principal,
                intent: historyNote
            ))
        } else if existingProject?.state != desiredProject {
            changes.append(GovernedChange(
                target: projectID,
                operation: .mutate(newState: desiredProject),
                authorizedBy: principal,
                intent: historyNote
            ))
        }

        for schematic in document.schematics {
            let schematicID = ElectronicsSchema.schematicID(
                projectLegacyID: document.legacyID,
                schematicKey: schematic.key
            )
            let desiredSchematic = try Self.schematicState(
                projectLegacyID: document.legacyID,
                schematic: schematic
            )
            let existing = snapshot.objects[schematicID]
            if existing == nil {
                changes.append(GovernedChange(
                    target: schematicID,
                    operation: .create(
                        typeName: ElectronicsSchema.schematicType,
                        initialState: desiredSchematic
                    ),
                    authorizedBy: principal,
                    intent: "\(historyNote): schematic \(schematic.key)"
                ))
            } else if existing?.state != desiredSchematic {
                changes.append(GovernedChange(
                    target: schematicID,
                    operation: .mutate(newState: desiredSchematic),
                    authorizedBy: principal,
                    intent: "\(historyNote): schematic \(schematic.key)"
                ))
            }

            for component in schematic.components {
                let componentID = ElectronicsSchema.componentID(
                    projectLegacyID: document.legacyID,
                    schematicKey: schematic.key,
                    reference: component.reference
                )
                let desiredComponent = Self.componentState(
                    projectLegacyID: document.legacyID,
                    schematicKey: schematic.key,
                    component: component
                )
                let existingComponent = snapshot.objects[componentID]
                if existingComponent == nil {
                    changes.append(GovernedChange(
                        target: componentID,
                        operation: .create(
                            typeName: ElectronicsSchema.componentType,
                            initialState: desiredComponent
                        ),
                        authorizedBy: principal,
                        intent: "\(historyNote): component \(component.reference)"
                    ))
                } else if existingComponent?.state != desiredComponent {
                    changes.append(GovernedChange(
                        target: componentID,
                        operation: .mutate(newState: desiredComponent),
                        authorizedBy: principal,
                        intent: "\(historyNote): component \(component.reference)"
                    ))
                }
            }
        }

        if !changes.isEmpty {
            _ = try await runtime.transact(changes)
        }
        return projectID
    }

    // MARK: - Governed mutations

    /// Renames a project. Every landed rename is a tracked change.
    public func renameProject(
        _ projectID: WorldObjectID,
        to newName: String,
        as principal: Principal,
        intent: String? = nil
    ) async throws -> ProjectSummary {
        let current = try await projectSummary(projectID)
        var document = try await document(projectID: projectID) ?? ElectronicsDocument(
            legacyID: current.legacyID,
            name: current.name
        )
        document.name = newName

        _ = try await runtime.transact([
            GovernedChange(
                target: projectID,
                operation: .mutate(newState: try Self.projectState(for: document)),
                authorizedBy: principal,
                intent: intent ?? "rename project \(current.name) → \(newName)"
            ),
        ])
        return try await projectSummary(projectID)
    }

    /// Updates one component's value/fitted state. `nil` arguments leave
    /// the current value untouched. Component state is governed, so every
    /// BOM-visible change (value swap, DNP toggle) is a tracked change.
    public func setComponentAttributes(
        _ componentID: WorldObjectID,
        value: String? = nil,
        fitted: Bool? = nil,
        as principal: Principal,
        intent: String? = nil
    ) async throws -> ComponentRecord {
        let record = try await component(componentID)
        let updated = ComponentRecord(
            objectID: record.objectID,
            projectLegacyID: record.projectLegacyID,
            schematicKey: record.schematicKey,
            reference: record.reference,
            libId: record.libId,
            value: value ?? record.value,
            fitted: fitted ?? record.fitted,
            x: record.x,
            y: record.y,
            mirror: record.mirror
        )

        _ = try await runtime.transact([
            GovernedChange(
                target: componentID,
                operation: .mutate(newState: Self.componentState(for: updated)),
                authorizedBy: principal,
                intent: intent
                    ?? "component change on \(record.reference) (value \(updated.value), fitted \(updated.fitted))"
            ),
        ])
        return updated
    }

    /// Deletes a project and everything derived from it (schematics,
    /// components) as tombstones in one atomic transaction. Deleted
    /// identities are never reused — history stays complete (KERNEL-003).
    ///
    /// Destructive: the principal needs delete authority over the
    /// electronics types, which for non-founder principals arrives only
    /// through an approval flow
    /// (`ElectronicsApprovals.requestProjectDeletionAuthority`). The raw
    /// KiCad files are NOT touched — only the governed mirror.
    public func deleteProject(
        _ projectID: WorldObjectID,
        as principal: Principal,
        intent: String? = nil
    ) async throws {
        let summary = try await projectSummary(projectID)
        let snapshot = await runtime.snapshot()

        var changes = [GovernedChange(
            target: projectID,
            operation: .delete,
            authorizedBy: principal,
            intent: intent ?? "delete project \(summary.name) (\(summary.legacyID))"
        )]

        for object in snapshot.objects.values where object.status == .live {
            guard let derived = Self.derivedLegacyID(of: object, projectLegacyID: summary.legacyID)
            else { continue }
            changes.append(GovernedChange(
                target: object.id,
                operation: .delete,
                authorizedBy: principal,
                intent: "delete \(object.typeName) \(derived) of project \(summary.legacyID)"
            ))
        }

        _ = try await runtime.transact(changes)
    }

    // MARK: - Projections (Modeled World → domain)

    /// All live projects, ordered by legacy ID for stable presentation.
    public func projects() async -> [ProjectSummary] {
        let snapshot = await runtime.snapshot()
        return snapshot.objects.values
            .filter { $0.typeName == ElectronicsSchema.projectType && $0.status == .live }
            .compactMap { Self.summary(from: $0) }
            .sorted { $0.legacyID < $1.legacyID }
    }

    /// The `ElectronicsDocument` of a governed project, decoded back from
    /// the canonical state. Identity and content survive the round trip —
    /// this is what "no functionality loss" is checked against.
    public func document(projectID: WorldObjectID) async throws -> ElectronicsDocument? {
        let snapshot = await runtime.snapshot()
        guard let object = snapshot.objects[projectID], object.status == .live else { return nil }
        guard case .object(let fields) = object.state,
              let documentValue = fields["document"]
        else {
            throw ElectronicsWorldError.malformedState(
                "project \(projectID) has no document payload"
            )
        }
        return try WorldValueCodec.decode(ElectronicsDocument.self, from: documentValue)
    }

    /// The governed schematics of a project.
    public func schematics(projectID: WorldObjectID) async throws -> [SchematicRecord] {
        let summary = try await projectSummary(projectID)
        let snapshot = await runtime.snapshot()
        return try Self.schematicKeys(in: snapshot, projectID: projectID)
            .map { key in
                ElectronicsSchema.schematicID(
                    projectLegacyID: summary.legacyID,
                    schematicKey: key
                )
            }
            .compactMap { id in
                guard let object = snapshot.objects[id], object.status == .live else {
                    return nil
                }
                return try Self.schematicRecord(from: object)
            }
            .sorted { $0.key < $1.key }
    }

    /// One governed schematic.
    public func schematic(_ schematicID: WorldObjectID) async throws -> SchematicRecord {
        let snapshot = await runtime.snapshot()
        guard let object = snapshot.objects[schematicID], object.status == .live else {
            throw ElectronicsWorldError.schematicNotFound(schematicID)
        }
        return try Self.schematicRecord(from: object)
    }

    /// The governed components of a project, across all schematics.
    public func components(projectID: WorldObjectID) async throws -> [ComponentRecord] {
        let summary = try await projectSummary(projectID)
        let snapshot = await runtime.snapshot()
        return try snapshot.objects.values
            .filter {
                $0.typeName == ElectronicsSchema.componentType
                    && $0.status == .live
                    && Self.fields(of: $0)["projectLegacyID"] == .string(summary.legacyID)
            }
            .compactMap { try Self.componentRecord(from: $0) }
            .sorted { ($0.schematicKey, $0.reference) < ($1.schematicKey, $1.reference) }
    }

    /// One governed component.
    public func component(_ componentID: WorldObjectID) async throws -> ComponentRecord {
        let snapshot = await runtime.snapshot()
        guard let object = snapshot.objects[componentID], object.status == .live else {
            throw ElectronicsWorldError.componentNotFound(componentID)
        }
        return try Self.componentRecord(from: object)
    }

    /// The immutable change history of one object, oldest first.
    public func history(_ objectID: WorldObjectID) async -> [ChangeRecord] {
        let snapshot = await runtime.snapshot()
        return snapshot.histories[objectID] ?? []
    }

    // MARK: - State shapes

    private static func projectState(for document: ElectronicsDocument) throws -> WorldValue {
        .object([
            "legacyID": .string(document.legacyID),
            "name": .string(document.name),
            "projectDescription": .string(document.projectDescription),
            "schematicKeys": .array(document.schematics.map { .string($0.key) }),
            "componentCount": .int(document.schematics.reduce(0) { $0 + $1.components.count }),
            "document": try WorldValueCodec.encode(document),
        ])
    }

    private static func schematicState(
        projectLegacyID: String,
        schematic: SchematicDocument
    ) throws -> WorldValue {
        .object([
            "projectLegacyID": .string(projectLegacyID),
            "key": .string(schematic.key),
            "kicadVersion": .string(schematic.kicadVersion),
            "sheetName": .string(schematic.sheetName),
            "componentReferences": .array(schematic.components.map { .string($0.reference) }),
        ])
    }

    private static func componentState(
        projectLegacyID: String,
        schematicKey: String,
        component: ComponentDocument
    ) -> WorldValue {
        .object([
            "projectLegacyID": .string(projectLegacyID),
            "schematicKey": .string(schematicKey),
            "reference": .string(component.reference),
            "libId": .string(component.libId),
            "value": .string(component.value),
            "fitted": .bool(component.fitted),
            "x": .double(component.x),
            "y": .double(component.y),
            "mirror": component.mirror.map(WorldValue.string) ?? .null,
        ])
    }

    private static func componentState(for record: ComponentRecord) -> WorldValue {
        .object([
            "projectLegacyID": .string(record.projectLegacyID),
            "schematicKey": .string(record.schematicKey),
            "reference": .string(record.reference),
            "libId": .string(record.libId),
            "value": .string(record.value),
            "fitted": .bool(record.fitted),
            "x": .double(record.x),
            "y": .double(record.y),
            "mirror": record.mirror.map(WorldValue.string) ?? .null,
        ])
    }

    // MARK: - Record decoding

    private static func fields(of object: WorldObject) -> [String: WorldValue] {
        if case .object(let fields) = object.state { return fields }
        return [:]
    }

    private func projectSummary(_ projectID: WorldObjectID) async throws -> ProjectSummary {
        let snapshot = await runtime.snapshot()
        guard let object = snapshot.objects[projectID], object.status == .live else {
            throw ElectronicsWorldError.projectNotFound(projectID)
        }
        guard let summary = Self.summary(from: object) else {
            throw ElectronicsWorldError.malformedState(
                "project \(projectID) state is malformed"
            )
        }
        return summary
    }

    private static func schematicKeys(
        in snapshot: WorldSnapshot,
        projectID: WorldObjectID
    ) -> [String] {
        guard let object = snapshot.objects[projectID],
              case .object(let projectFields) = object.state,
              case .array(let keyValues)? = projectFields["schematicKeys"]
        else { return [] }
        return keyValues.compactMap {
            if case .string(let key) = $0 { return key }
            return nil
        }
    }

    /// The `<projectID>/…` composite legacy ID of an object derived from a
    /// project, if it is one of the derived kinds carrying a
    /// `projectLegacyID` field. Used to cascade deletes without guessing
    /// from type names.
    private static func derivedLegacyID(
        of object: WorldObject,
        projectLegacyID: String
    ) -> String? {
        guard object.typeName != ElectronicsSchema.projectType,
              case .object(let f) = object.state,
              case .string(let owner)? = f["projectLegacyID"],
              owner == projectLegacyID
        else { return nil }
        if case .string(let key)? = f["key"] { return key }
        if case .string(let reference)? = f["reference"] { return reference }
        return object.typeName
    }

    private static func summary(from object: WorldObject) -> ProjectSummary? {
        guard case .object(let fields) = object.state,
              case .string(let legacyID)? = fields["legacyID"],
              case .string(let name)? = fields["name"],
              case .array(let keyValues)? = fields["schematicKeys"],
              case .int(let componentCount)? = fields["componentCount"]
        else { return nil }
        return ProjectSummary(
            objectID: object.id,
            legacyID: legacyID,
            name: name,
            schematicCount: keyValues.count,
            componentCount: componentCount,
            version: object.version
        )
    }

    private static func schematicRecord(from object: WorldObject) throws -> SchematicRecord {
        guard case .object(let fields) = object.state,
              case .string(let projectLegacyID)? = fields["projectLegacyID"],
              case .string(let key)? = fields["key"],
              case .string(let kicadVersion)? = fields["kicadVersion"],
              case .string(let sheetName)? = fields["sheetName"],
              case .array(let referenceValues)? = fields["componentReferences"]
        else {
            throw ElectronicsWorldError.malformedState(
                "schematic \(object.id) state is malformed"
            )
        }
        return SchematicRecord(
            objectID: object.id,
            projectLegacyID: projectLegacyID,
            key: key,
            kicadVersion: kicadVersion,
            sheetName: sheetName,
            componentCount: referenceValues.count
        )
    }

    private static func componentRecord(from object: WorldObject) throws -> ComponentRecord {
        guard case .object(let fields) = object.state,
              case .string(let projectLegacyID)? = fields["projectLegacyID"],
              case .string(let schematicKey)? = fields["schematicKey"],
              case .string(let reference)? = fields["reference"],
              case .string(let libId)? = fields["libId"],
              case .string(let value)? = fields["value"],
              case .bool(let fitted)? = fields["fitted"],
              case .double(let x)? = fields["x"],
              case .double(let y)? = fields["y"]
        else {
            throw ElectronicsWorldError.malformedState(
                "component \(object.id) state is malformed"
            )
        }
        var mirror: String?
        if case .string(let rawMirror)? = fields["mirror"] { mirror = rawMirror }
        return ComponentRecord(
            objectID: object.id,
            projectLegacyID: projectLegacyID,
            schematicKey: schematicKey,
            reference: reference,
            libId: libId,
            value: value,
            fitted: fitted,
            x: x,
            y: y,
            mirror: mirror
        )
    }
}
