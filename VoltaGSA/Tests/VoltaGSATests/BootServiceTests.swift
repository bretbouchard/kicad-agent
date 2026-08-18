import Testing
import Foundation
@testable import VoltaGSA

// Boot health: every boot attempt persists a boot-status.json marker next to
// the world change log, so a non-gating failure is inspectable offline.

@Suite struct BootServiceTests {

    static func makeStorage() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("VoltaGSA-\(UUID().uuidString)", isDirectory: true)
    }

    static func readMarker(_ storage: URL) throws -> GSABootService.BootStatus {
        let data = try Data(
            contentsOf: storage.appendingPathComponent("boot-status.json")
        )
        return try JSONDecoder().decode(GSABootService.BootStatus.self, from: data)
    }

    @Test func successfulBootWritesBootedMarker() async throws {
        let storage = Self.makeStorage()
        let service = GSABootService()
        let booted = await service.bootIfNeeded(storageDirectory: storage)
        #expect(booted != nil)

        let marker = try Self.readMarker(storage)
        #expect(marker.outcome == .booted)
        #expect(marker.error == nil)

        // Booted twice returns the same instance and rewrites the marker.
        let again = await service.bootIfNeeded(storageDirectory: storage)
        #expect(again?.storageDirectory == booted?.storageDirectory)
    }

    @Test func failedBootWritesFailedMarkerAndReturnsNil() async throws {
        let storage = Self.makeStorage()
        // Force boot failure: world.jsonl must be a change-log FILE, so an
        // existing DIRECTORY at that path makes the change log unusable.
        try FileManager.default.createDirectory(
            at: storage.appendingPathComponent("world.jsonl"),
            withIntermediateDirectories: true
        )
        defer { try? FileManager.default.removeItem(at: storage) }

        let service = GSABootService()
        let booted = await service.bootIfNeeded(storageDirectory: storage)
        #expect(booted == nil)
        #expect(await service.lastBootError != nil)

        let marker = try Self.readMarker(storage)
        #expect(marker.outcome == .failed)
        #expect(marker.error != nil)
    }
}
