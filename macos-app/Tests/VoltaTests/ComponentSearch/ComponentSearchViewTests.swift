import Testing
import Foundation
import SwiftUI
@testable import Volta
@testable import VoltaPCBCore

@MainActor
@Suite("Component Search")
struct ComponentSearchViewTests {
    @Test("ComponentSearchView instantiates with merge engine", .tags(.ui, .a11y))
    func componentSearchInstantiates() {
        let componentRegistry = ComponentProviderRegistry()
        let cadRegistry = CADModelProviderRegistry()
        let engine = MergeEngine(componentRegistry: componentRegistry, cadRegistry: cadRegistry)

        let view = ComponentSearchView(mergeEngine: engine)
            .frame(width: 600, height: 480)
        _ = view
    }

    @Test("ComponentDetailView instantiates with governed provider workflow", .tags(.ui, .a11y))
    func componentDetailInstantiates() {
        let component = UnifiedComponent(
            partNumber: "STM32F411RET6",
            manufacturer: "STMicroelectronics",
            description: "Mainstream ARM Cortex-M4 MCU",
            sources: [
                ComponentSource(
                    provider: "jlcpcb",
                    providerPartId: "C2040",
                    lastUpdated: Date(timeIntervalSince1970: 1750000000),
                    confidence: 0.95
                )
            ],
            pricing: [
                PricingData(
                    unitPrice: 4.63,
                    minOrderQty: 1,
                    currency: "USD",
                    distributor: "LCSC",
                    lastUpdated: Date(timeIntervalSince1970: 1750000000)
                )
            ],
            stock: [
                StockData(
                    quantityAvailable: 1200,
                    distributor: "LCSC",
                    leadTime: "immediate",
                    lastUpdated: Date(timeIntervalSince1970: 1750000000)
                )
            ],
            specs: [
                "Package": "LQFP-64",
                "Assembly": "basic"
            ],
            datasheetURL: URL(string: "https://example.com/stm32f411.pdf"),
            lcscPartNumber: "C2040",
            category: "MCU"
        )

        let storageDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("volta-component-search-\(UUID().uuidString)", isDirectory: true)
        let artifactRoot = storageDirectory.appendingPathComponent("artifacts", isDirectory: true)
        let host = GSAPlatformHost(configuration: GSAPlatformHostConfiguration(
            storageDirectory: storageDirectory,
            artifactRoot: artifactRoot,
            allowedFileRoots: [storageDirectory, artifactRoot],
            allowedExecutables: []
        ))

        let view = ComponentDetailView(component: component, onRefresh: {})
            .environment(host)
            .preferredColorScheme(.dark)
        _ = view

        try? FileManager.default.removeItem(at: storageDirectory)
    }
}
