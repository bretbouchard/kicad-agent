import Foundation
import CryptoKit
import GSAModeledWorld
import GSAEvidence
import GSACapabilityKernel

// MARK: - Shared artifact plumbing
// Same proven shape as WhiteRoomGSA's ArtifactSupport (M2.1).

enum ArtifactSupport {
    static func sha256Hex(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    /// Resolves `dir/file` and enforces the allowed-roots sandbox. Matches
    /// the platform's standard fs capabilities (gsa-platform 0.1.2): paths
    /// are physically resolved — symlinks are resolved on BOTH the target
    /// and the roots, via longest-existing-ancestor resolution because
    /// URL.resolvingSymlinksInPath() skips non-existent tails — and the
    /// containment check requires a whole path component, so a root of
    /// "/a/artifacts" does not authorize "/a/artifacts-evil".
    static func resolveURL(
        directory: String,
        file: String,
        allowedRoots: [URL]
    ) throws -> URL {
        let url = physicallyResolvedURL(
            URL(fileURLWithPath: directory, isDirectory: true)
                .appendingPathComponent(file)
        )
        let roots = allowedRoots.map(physicallyResolvedURL)
        guard roots.contains(where: { root in
            url.path == root.path || url.path.hasPrefix(root.path + "/")
        }) else {
            throw CapabilityInputError.outsideSandbox(url.path)
        }
        return url
    }

    /// Longest-existing-ancestor symlink resolution (mirrors gsa-platform's
    /// physicallyResolvedURL).
    private static func physicallyResolvedURL(_ url: URL) -> URL {
        let fileManager = FileManager.default
        var ancestor = url.standardizedFileURL
        var tail: [String] = []
        while ancestor.path != "/" && !fileManager.fileExists(atPath: ancestor.path) {
            tail.insert(ancestor.lastPathComponent, at: 0)
            ancestor = ancestor.deletingLastPathComponent()
        }
        let resolved = ancestor.resolvingSymlinksInPath()
        return tail.reduce(resolved) { $0.appendingPathComponent($1) }
    }

    /// Writes `data` atomically and returns it with its digest.
    static func write(
        _ data: Data,
        to url: URL
    ) throws -> (bytes: Int, sha256: String) {
        try FileManager.default.createDirectory(
            at: url.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try data.write(to: url, options: .atomic)
        return (data.count, sha256Hex(data))
    }

    /// Extracts `path` and `sha256` from an evidence payload.
    static func artifactReference(
        in payload: WorldValue?
    ) -> (path: String, sha256: String)? {
        guard case .object(let fields)? = payload,
              case .string(let path)? = fields["path"],
              case .string(let sha256)? = fields["sha256"]
        else { return nil }
        return (path, sha256)
    }

    /// Strong artifact verification (KERNEL-006): the file must exist and
    /// its current digest must still match the claimed one. A capability
    /// that lied about writing — or wrote something that has since changed
    /// underneath the claim — fails at the broker boundary.
    static func verifyArtifact(_ result: CapabilityResult) -> Bool {
        guard let reference = artifactReference(in: result.evidence.payload) else {
            return false
        }
        guard let data = try? Data(contentsOf: URL(fileURLWithPath: reference.path)) else {
            return false
        }
        return sha256Hex(data) == reference.sha256
    }
}

// MARK: - electronics.export

/// Publishes a governed electronics project as a canonical, reproducible
/// release artifact: a manifest with sorted keys and a stable schema tag,
/// whose digest is computed over the exported payload. Outward-facing by
/// design — this is the seed of the M2.4 manufacturing-export path (Gerber/
/// BOM packaging starts here), and the authority to invoke it is meant to
/// arrive through an approval flow, never ambiently.
public struct ElectronicsExportCapability: Capability {
    public static let schemaTag = "volta.export/1"

    public let id = CapabilityID(name: "electronics.export", version: 1)
    public let effect =
        "Writes a canonical export manifest (sorted-key JSON, schema \(ElectronicsExportCapability.schemaTag)) for a governed electronics project inside the allowed roots. Seed of the governed manufacturing-export path (M2.4)."

    private let allowedRoots: [URL]

    public init(allowedRoots: [URL]) {
        self.allowedRoots = allowedRoots
    }

    public func invoke(_ input: WorldValue) async throws -> CapabilityResult {
        guard case .object(let fields) = input,
              case .string(let projectName)? = fields["projectName"],
              let project = fields["project"]
        else {
            throw CapabilityInputError.missingField(
                "projectName (string) and project (object) required"
            )
        }
        guard case .string(let outputDir)? = fields["outputDir"] else {
            throw CapabilityInputError.missingField("outputDir (string) required")
        }

        let manifest = try JSONSerialization.data(
            withJSONObject: [
                "schema": Self.schemaTag,
                "projectName": projectName,
                "project": try WorldValueCodec.toJSON(project),
            ],
            options: [.sortedKeys, .withoutEscapingSlashes]
        )

        let file = "export-\(projectName.replacingOccurrences(of: "/", with: "-"))-\(UUID().uuidString.prefix(8)).json"
        let url = try ArtifactSupport.resolveURL(
            directory: outputDir,
            file: file,
            allowedRoots: allowedRoots
        )
        let written = try ArtifactSupport.write(manifest, to: url)

        return CapabilityResult(
            output: .object([
                "path": .string(url.path),
                "bytes": .int(written.bytes),
                "sha256": .string(written.sha256),
            ]),
            evidence: Evidence(
                kind: .artifact,
                claim: "electronics.export wrote \(written.bytes) bytes to \(url.path) (sha256 \(written.sha256))",
                producer: Principal(rawValue: "capability:electronics.export"),
                payload: .object([
                    "path": .string(url.path),
                    "sha256": .string(written.sha256),
                    "bytes": .int(written.bytes),
                ])
            )
        )
    }

    public func verify(_ result: CapabilityResult) -> Bool {
        ArtifactSupport.verifyArtifact(result)
    }
}
