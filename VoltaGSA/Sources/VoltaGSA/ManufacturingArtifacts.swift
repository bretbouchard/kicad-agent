import Foundation
import GSAModeledWorld
import GSAEvidence
import GSAArtifacts
import GSACapabilityKernel

// VO-TRUST-1 (gsa_33/gsa_34): every manufacturing export carries a DAID.
// Exports naming their governing context — the board object and the
// governed change — mint manifests; context-free exports behave as
// before (ArtifactProductionSkipped, platform 0.4.3).

extension ElectronicsExportCapability: ArtifactProducingCapability {

    public func manifest(
        forResult result: CapabilityResult,
        input: WorldValue
    ) async throws -> ArtifactManifest {
        guard case .object(let fields) = input,
              case .string(let boardUUID)? = fields["board"],
              case .string(let changeUUID)? = fields["change"],
              let board = UUID(uuidString: boardUUID),
              let change = UUID(uuidString: changeUUID),
              case .object(let output)? = result.output,
              case .string(let path)? = output["path"],
              case .string(let sha256)? = output["sha256"]
        else {
            throw ArtifactProductionSkipped(
                reason: "electronics.export invocation carries no board/change context"
            )
        }

        let fileName = (path as NSString).lastPathComponent
        var parents: [DAID] = []
        if case .string(let parentRaw)? = fields["parentDAID"] {
            parents.append(DAID(rawValue: parentRaw))
        }

        return ArtifactManifest(
            entityType: "file",
            operation: "export",
            sourceObjects: [WorldObjectID(value: board)],
            parentDAIDs: parents,
            runtimeVersion: "VoltaGSA",
            toolchain: "electronics.export@1 (\(ElectronicsExportCapability.schemaTag))",
            inputs: ["volta board export"],
            outputs: [fileName],
            author: Principal(rawValue: "capability:electronics.export"),
            governingChange: ChangeID(value: change),
            hashes: [fileName: ArtifactHash(sha256Hex: sha256)],
            evidenceReferences: ["evidence:\(result.evidence.id.uuidString)"],
            reproducibility: .deterministic
        )
    }
}

// VO-TRUST-2: the fabricator handoff. A manufacturing package is a signed
// bundle: the manufacturing files (gerbers, BOM, pick-and-place) hashed in
// one manifest whose parent is the export that produced them, signed with
// the fab's key, and written as an ArtifactBundle. The recipient verifies
// with the bundle and a public key alone — no Volta registry required
// (TRUST-T005).

public enum ManufacturingPackageBuilder {

    public enum PackageError: Error, Equatable, Sendable {
        case noSigningKey
        case emptyPackage
    }

    /// Assembles, mints, signs, and writes the manufacturing package.
    /// Returns the package DAID and the bundle directory.
    @discardableResult
    public static func build(
        projectName: String,
        board: WorldObjectID,
        governingChange: ChangeID,
        parentExport: DAID?,
        files: [String: Data],
        registry: ArtifactRegistry,
        signingKey: ArtifactSigningKey,
        to directory: URL
    ) async throws -> (daid: DAID, bundle: URL) {
        guard !files.isEmpty else { throw PackageError.emptyPackage }

        let hashes = files.mapValues { ArtifactHash.sha256($0) }
        var manifest = ArtifactManifest(
            entityType: "file",
            operation: "package",
            sourceObjects: [board],
            parentDAIDs: parentExport.map { [$0] } ?? [],
            runtimeVersion: "VoltaGSA",
            toolchain: "manufacturing package: \(projectName)",
            inputs: ["board export"],
            outputs: files.keys.sorted(),
            author: Principal(rawValue: "human:fabricator-out"),
            governingChange: governingChange,
            hashes: hashes,
            evidenceReferences: [],
            reproducibility: .deterministic
        )

        let daid = try await registry.mint(manifest)
        manifest = try ArtifactSigner.sign(manifest, with: signingKey)
        try await registry.recordSignature(for: daid, manifest)
        try ArtifactBundle.write(manifest: manifest, content: files, to: directory)

        return (daid, directory)
    }
}
