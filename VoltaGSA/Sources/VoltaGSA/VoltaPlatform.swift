import Foundation
import GSAModeledWorld
import GSAObdurate
import GSAPlatform

/// Volta's embedding of the GSA Platform — the composition root for
/// everything product-specific (M2.3 foundation wave). `boot` calls
/// `Platform.boot`, then registers Volta's electronics capabilities and
/// exposes the domain facade.
///
/// The platform boots with an EMPTY grant set (default-deny, KERNEL-004):
/// nothing may change the world or invoke a capability until authority
/// exists — either directly issued via `issueFounderAuthority` at a human's
/// behest, or minted from an approval flow (`ElectronicsApprovals`).
///
/// KiCad workflows are untouched: the app's `.kicad_sch`/`.kicad_pcb`
/// read/write paths and validation gates keep running exactly as before;
/// this embedding is the governed mirror of that state, and migration into
/// it is idempotent, so syncing is safe to re-run at any cadence.
public struct VoltaPlatform: Sendable {
    /// The underlying GSA platform (`runtime`, `broker`, `policy`,
    /// `approvals`, `evidence`, `historian`).
    public let platform: Platform
    /// Governed electronics domain: projects, schematics, components.
    public let electronics: ElectronicsWorld
    /// Approval flows for consequential operations.
    public let approvals: ElectronicsApprovals
    /// Where the world change log (and default artifact root) live.
    public let storageDirectory: URL
    /// Default artifact output root (inside the broker's allowed roots).
    public let artifactRoot: URL

    /// Boots Volta's GSA embedding.
    ///
    /// - Parameters:
    ///   - storageDirectory: platform storage (world change log). Defaults
    ///     to `~/Library/Application Support/VoltaGSA` (created).
    ///   - allowedFileRoots: broker sandbox for artifact-writing
    ///     capabilities. Defaults to `<storageDirectory>/artifacts` (created).
    ///
    /// Recovery is part of boot: an existing change log is replayed and the
    /// recovered world must validate, or boot refuses to run (KERNEL-009).
    @discardableResult
    public static func boot(
        storageDirectory: URL? = nil,
        allowedFileRoots: [URL]? = nil
    ) async throws -> VoltaPlatform {
        let support = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        )[0]
        let storage = storageDirectory
            ?? support.appendingPathComponent("VoltaGSA", isDirectory: true)
        let artifacts = storage.appendingPathComponent("artifacts", isDirectory: true)
        try FileManager.default.createDirectory(
            at: artifacts,
            withIntermediateDirectories: true
        )
        let roots = allowedFileRoots ?? [artifacts]

        let platform = try await Platform.boot(
            storageDirectory: storage,
            allowedFileRoots: roots
        )

        // Electronics capabilities behind the broker (KERNEL-005).
        // Platform.boot already registered the standard fs/process
        // capabilities for the roots given above.
        await platform.broker.register(ElectronicsExportCapability(allowedRoots: roots))
        await platform.broker.register(
            ElectronicsManufacturingQuoteCapability(allowedRoots: roots)
        )
        await platform.broker.register(
            ElectronicsManufacturingUploadCapability(allowedRoots: roots)
        )
        await platform.broker.register(
            ElectronicsComplianceCheckCapability(allowedRoots: roots)
        )

        return VoltaPlatform(
            platform: platform,
            electronics: ElectronicsWorld(runtime: platform.runtime),
            approvals: ElectronicsApprovals(ledger: platform.approvals),
            storageDirectory: storage,
            artifactRoot: artifacts
        )
    }

    /// Full electronics-domain authority for one principal: create/mutate/
    /// delete governed electronics objects and invoke Volta's capabilities.
    /// Call this only for the human founder's own session; agent principals
    /// get authority exclusively through approval flows.
    public func issueFounderAuthority(to principal: Principal) async {
        await platform.policy.issue(AuthorityGrant(
            principal: principal,
            scope: GrantScope(
                kinds: [.create, .mutate, .delete],
                typeNames: ElectronicsSchema.allTypeNames,
                capabilities: [
                    "electronics.export",
                    "electronics.manufacturing.quote",
                    "fs.write",
                    "fs.read",
                ]
            ),
            grantedBy: VoltaPrincipals.bootstrap
        ))
    }
}
