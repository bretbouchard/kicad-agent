import Testing
import Foundation
@testable import Volta

@MainActor
@Suite("Validation Panel")
struct ValidationPanelTests {
    private let governedContext = GSAPlatformHost.GovernedProjectContext(
        projectID: UUID(uuidString: "CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC")!,
        projectName: "Validation Fixture",
        conversationID: UUID(uuidString: "DDDDDDDD-DDDD-DDDD-DDDD-DDDDDDDDDDDD")!,
        revision: 3
    )

    private static func locateBoardFixture() -> URL? {
        let candidates = [
            "Tests/VoltaTests/Routing/Fixtures/simple_2layer_led.kicad_pcb",
            "../Tests/VoltaTests/Routing/Fixtures/simple_2layer_led.kicad_pcb",
            "macos-app/Tests/VoltaTests/Routing/Fixtures/simple_2layer_led.kicad_pcb",
            "../macos-app/Tests/VoltaTests/Routing/Fixtures/simple_2layer_led.kicad_pcb",
        ]
        for path in candidates {
            let url = URL(fileURLWithPath: path)
            if FileManager.default.fileExists(atPath: url.path) {
                return url
            }
        }
        return nil
    }

    @Test("ValidationManager records governed DRC evidence for a real board fixture")
    func validationManagerRecordsGovernedDRC() async throws {
        guard let fixture = Self.locateBoardFixture() else {
            Issue.record("Board fixture missing")
            return
        }

        let storageDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("volta-validation-governed-\(UUID().uuidString)", isDirectory: true)
        let artifactRoot = storageDirectory.appendingPathComponent("artifacts", isDirectory: true)
        let host = GSAPlatformHost(configuration: GSAPlatformHostConfiguration(
            storageDirectory: storageDirectory,
            artifactRoot: artifactRoot,
            allowedFileRoots: [storageDirectory, artifactRoot, fixture.deletingLastPathComponent()],
            allowedExecutables: []
        ))
        defer { try? FileManager.default.removeItem(at: storageDirectory) }

        host.boot()
        let deadline = ContinuousClock.now.advanced(by: .seconds(3))
        while host.state == .booting, ContinuousClock.now < deadline {
            try await Task.sleep(for: .milliseconds(25))
        }

        let manager = ValidationManager()
        await manager.runDRC(
            filePath: fixture.path,
            client: nil,
            gsaPlatformHost: host,
            governedContext: governedContext
        )

        #expect(manager.results.isEmpty == false)
        let result = try #require(manager.results.first)
        #expect(result.checkType == "DRC")
        #expect(result.governed != nil)
        #expect(result.governed?.projectReference.hasPrefix("project:") == true)
        #expect(result.governed?.revisionReference.hasPrefix("revision:") == true)
        #expect(result.governed?.schematicReference.hasPrefix("schematic:") == true)
        #expect(result.governed?.sheetReference.hasPrefix("sheet:") == true)
        #expect(result.governed?.componentReference.hasPrefix("component:") == true)
        #expect(result.governed?.netReference.hasPrefix("net:") == true)
        #expect(result.governed?.bomReference.hasPrefix("bom:") == true)
        #expect(result.governed?.pcbReference.hasPrefix("pcb:") == true)
        #expect(result.governed?.footprintReference.hasPrefix("footprint:") == true)
        #expect(result.governed?.verificationArtifactReference.hasPrefix("verification-artifact:") == true)
        #expect(result.governed?.objectReference.hasPrefix("object:") == true)
        #expect(result.governed?.claim.contains("volta.drc.verification:") == true)
        #expect(result.governed?.gateSatisfied == true)
        #expect(result.governed?.liveEvidenceCount ?? 0 > 0)
        #expect(result.governed?.historianChainCount ?? 0 > 0)
    }
}
