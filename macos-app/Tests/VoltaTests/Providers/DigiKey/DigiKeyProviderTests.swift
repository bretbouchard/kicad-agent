//
//  DigiKeyProviderTests.swift
//  VoltaTests
//
//  Phase 1 / Task 2 — Digi-Key V4 Provider
//
//  Tests V4 response decoding and UnifiedComponent mapping.
//  Uses the recorded V4 response schema as fixture data.
//  Live API tests require DIGIKEY_CLIENT_ID + DIGIKEY_CLIENT_SECRET env vars.
//

import XCTest
@testable import Volta
@testable import VoltaPCBCore

final class DigiKeyProviderTests: XCTestCase {

    /// Minimal V4 product JSON matching the schema.
    private let sampleProductJSON: [String: Any] = [
        "ManufacturerProductNumber": "STM32F411RET6",
        "Description": [
            "ProductDescription": "IC MCU 32BIT 512KB FLASH 64LQFP",
            "DetailedDescription": "ARM Cortex-M4 STM32F4 Microcontroller IC 32-Bit 100MHz 512KB FLASH 64-LQFP"
        ],
        "Manufacturer": ["Id": 497, "Name": "STMicroelectronics"],
        "UnitPrice": 7.46,
        "QuantityAvailable": 3181,
        "ProductUrl": "https://www.digikey.com/en/products/detail/stmicroelectronics/STM32F411RET6/4935722",
        "DatasheetUrl": "https://www.st.com/content/ccc/resource/technical/document/datasheet/DM00115249.pdf",
        "PhotoUrl": "https://mm.digikey.com/Volume0/opasdata/d220001/medias/images/4832/MCU.JPG",
        "ProductStatus": ["Id": 0, "Status": "Active"],
        "Category": ["Id": 4, "Name": "Integrated Circuits"],
        "Parameters": [
            ["ParameterId": 506, "ParameterText": "Core Processor", "ValueText": "ARM Cortex-M4"],
            ["ParameterId": 85, "ParameterText": "Speed", "ValueText": "100MHz"]
        ],
        "ProductVariations": [
            [
                "DigiKeyProductNumber": "497-14909-ND",
                "QuantityAvailableforPackageType": 3181,
                "MinimumOrderQuantity": 1,
                "StandardPricing": [
                    ["BreakQuantity": 1, "UnitPrice": 7.46],
                    ["BreakQuantity": 10, "UnitPrice": 5.757],
                    ["BreakQuantity": 100, "UnitPrice": 4.74]
                ]
            ]
        ]
    ]

    func test_decodeV4SearchResponse() throws {
        let responseJSON: [String: Any] = [
            "Products": [sampleProductJSON],
            "ProductsCount": 1
        ]
        let data = try JSONSerialization.data(withJSONObject: responseJSON)
        let decoded = try JSONDecoder().decode(DigiKeySearchResponse.self, from: data)

        XCTAssertEqual(decoded.products.count, 1)
        XCTAssertEqual(decoded.productsCount, 1)

        let product = decoded.products[0]
        XCTAssertEqual(product.manufacturerProductNumber, "STM32F411RET6")
        XCTAssertEqual(product.manufacturer.name, "STMicroelectronics")
        XCTAssertEqual(product.unitPrice, 7.46)
        XCTAssertEqual(product.quantityAvailable, 3181)
        XCTAssertEqual(product.description.productDescription, "IC MCU 32BIT 512KB FLASH 64LQFP")
        XCTAssertEqual(product.productStatus?.status, "Active")
        XCTAssertEqual(product.category?.name, "Integrated Circuits")
        XCTAssertEqual(product.parameters?.count, 2)
    }

    func test_decodeProductWithMissingFields() throws {
        // Many fields are optional — verify graceful decode with minimal JSON.
        let minimalJSON: [String: Any] = [
            "ManufacturerProductNumber": "RC0805FR-0710KL",
            "Description": ["ProductDescription": "RES SMD 10K OHM 1% 1/8W 0805"],
            "Manufacturer": ["Name": "Yageo"],
            "UnitPrice": 0.10,
            "QuantityAvailable": 500000
        ]
        let responseJSON: [String: Any] = [
            "Products": [minimalJSON],
            "ProductsCount": 1
        ]
        let data = try JSONSerialization.data(withJSONObject: responseJSON)
        let decoded = try JSONDecoder().decode(DigiKeySearchResponse.self, from: data)

        let product = decoded.products[0]
        XCTAssertNil(product.datasheetUrl)
        XCTAssertNil(product.parameters)
        XCTAssertNil(product.productVariations)
        XCTAssertEqual(product.manufacturerProductNumber, "RC0805FR-0710KL")
    }

    func test_credentialsLoadFromEnv() {
        // Set env vars temporarily
        setenv("DIGIKEY_CLIENT_ID", "test-client-id", 1)
        setenv("DIGIKEY_CLIENT_SECRET", "test-secret", 1)

        let keychain = KeychainManager(service: "com.bretbouchard.volta.tests.digikey")
        let creds = DigiKeyCredentials.load(from: keychain)

        XCTAssertEqual(creds?.clientID, "test-client-id")
        XCTAssertEqual(creds?.clientSecret, "test-secret")

        unsetenv("DIGIKEY_CLIENT_ID")
        unsetenv("DIGIKEY_CLIENT_SECRET")
    }

    func test_credentialsMissingReturnsNil() {
        unsetenv("DIGIKEY_CLIENT_ID")
        unsetenv("DIGIKEY_CLIENT_SECRET")

        let keychain = KeychainManager(service: "com.bretbouchard.volta.tests.digikey")
        let creds = DigiKeyCredentials.load(from: keychain)

        XCTAssertNil(creds)
    }
}
