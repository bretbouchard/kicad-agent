import Foundation
import os

/// App-process integration point for the GSA embedding (M2.3).
///
/// Boots `VoltaPlatform` once per process, off the main actor, and holds
/// the running platform for the app's lifetime. Boot failures are logged
/// and swallowed — the GSA embedding is additive and must never gate app
/// launch, and KiCad workflows must keep working while the platform is
/// down (M2.3 preservation rules).
///
/// Because failures are non-gating by design, every boot attempt also
/// writes a `boot-status.json` marker next to the world change log so boot
/// health is inspectable without reading streamed logs. Same proven shape
/// as WhiteRoomGSA's GSABootService (M2.1 / bd-51au).
public actor GSABootService {
    public static let shared = GSABootService()

    private var platform: VoltaPlatform?
    private var bootError: String?

    public init() {}

    /// The running platform, booting it on first access. Subsequent calls
    /// return the already-booted instance (recovery replays the same world).
    @discardableResult
    public func bootIfNeeded(storageDirectory: URL? = nil) async -> VoltaPlatform? {
        if let platform { return platform }
        do {
            let booted = try await VoltaPlatform.boot(storageDirectory: storageDirectory)
            platform = booted
            Self.logger.info(
                "GSA platform booted (storage: \(booted.storageDirectory.path, privacy: .public))"
            )
            writeStatusMarker(
                in: booted.storageDirectory,
                status: BootStatus(outcome: .booted, error: nil)
            )
            return booted
        } catch {
            bootError = String(describing: error)
            Self.logger.error(
                "GSA platform boot failed (app continues without it): \(String(describing: error), privacy: .public))"
            )
            writeStatusMarker(
                in: storageDirectory ?? Self.defaultStorageDirectory,
                status: BootStatus(outcome: .failed, error: bootError!)
            )
            return nil
        }
    }

    /// The booted platform, if boot already ran.
    public var booted: VoltaPlatform? { platform }

    /// The recorded boot failure, if any (diagnostics only — never fatal).
    public var lastBootError: String? { bootError }

    // MARK: - Boot health marker

    /// Outcome of one boot attempt, persisted as `boot-status.json` in the
    /// platform storage directory (latest attempt wins).
    public struct BootStatus: Codable, Sendable, Equatable {
        public enum Outcome: String, Codable, Sendable {
            case booted
            case failed
        }

        public let outcome: Outcome
        public let at: Date
        public let error: String?

        init(outcome: Outcome, at: Date = Date(), error: String?) {
            self.outcome = outcome
            self.at = at
            self.error = error
        }
    }

    static var defaultStorageDirectory: URL {
        FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        )[0].appendingPathComponent("VoltaGSA", isDirectory: true)
    }

    private func writeStatusMarker(in directory: URL, status: BootStatus) {
        do {
            try FileManager.default.createDirectory(
                at: directory,
                withIntermediateDirectories: true
            )
            let data = try JSONEncoder().encode(status)
            try data.write(
                to: directory.appendingPathComponent("boot-status.json"),
                options: .atomic
            )
        } catch {
            Self.logger.error(
                "GSA boot-status marker write failed: \(String(describing: error), privacy: .public)"
            )
        }
    }

    private static let logger = Logger(subsystem: "com.volta.gsa", category: "GSABoot")
}
