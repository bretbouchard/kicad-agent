//
//  DigiKeySearchResponse.swift
//  Volta
//
//  Phase 1 / Task 2 — Digi-Key V4 Provider
//
//  Codable structs for Digi-Key V4 keyword search response.
//  Field names match DIGIKEY_V4_RESPONSE_SCHEMA.json exactly.
//
//  Only fields we use are decoded — the full V4 schema is much larger.
//

import Foundation

/// Top-level V4 keyword search response.
struct DigiKeySearchResponse: Decodable, Sendable {
    let products: [DigiKeyProduct]
    let productsCount: Int
    let exactMatches: [DigiKeyProduct]?

    enum CodingKeys: String, CodingKey {
        case products = "Products"
        case productsCount = "ProductsCount"
        case exactMatches = "ExactMatches"
    }
}

/// Single product from Digi-Key V4.
struct DigiKeyProduct: Decodable, Sendable {
    let manufacturerProductNumber: String
    let description: DigiKeyDescription
    let manufacturer: DigiKeyManufacturer
    let unitPrice: Double
    let quantityAvailable: Int
    let productUrl: String?
    let datasheetUrl: String?
    let photoUrl: String?
    let productStatus: DigiKeyProductStatus?
    let category: DigiKeyCategory?
    let parameters: [DigiKeyParameter]?
    let productVariations: [DigiKeyProductVariation]?

    enum CodingKeys: String, CodingKey {
        case manufacturerProductNumber = "ManufacturerProductNumber"
        case description = "Description"
        case manufacturer = "Manufacturer"
        case unitPrice = "UnitPrice"
        case quantityAvailable = "QuantityAvailable"
        case productUrl = "ProductUrl"
        case datasheetUrl = "DatasheetUrl"
        case photoUrl = "PhotoUrl"
        case productStatus = "ProductStatus"
        case category = "Category"
        case parameters = "Parameters"
        case productVariations = "ProductVariations"
    }
}

struct DigiKeyDescription: Decodable, Sendable {
    let productDescription: String
    let detailedDescription: String?

    enum CodingKeys: String, CodingKey {
        case productDescription = "ProductDescription"
        case detailedDescription = "DetailedDescription"
    }
}

struct DigiKeyManufacturer: Decodable, Sendable {
    let id: Int?
    let name: String

    enum CodingKeys: String, CodingKey {
        case id = "Id"
        case name = "Name"
    }
}

struct DigiKeyProductStatus: Decodable, Sendable {
    let id: Int
    let status: String

    enum CodingKeys: String, CodingKey {
        case id = "Id"
        case status = "Status"
    }
}

struct DigiKeyCategory: Decodable, Sendable {
    let id: Int?
    let name: String

    enum CodingKeys: String, CodingKey {
        case id = "Id"
        case name = "Name"
    }
}

struct DigiKeyParameter: Decodable, Sendable {
    let parameterId: Int
    let parameterText: String
    let valueText: String

    enum CodingKeys: String, CodingKey {
        case parameterId = "ParameterId"
        case parameterText = "ParameterText"
        case valueText = "ValueText"
    }
}

struct DigiKeyProductVariation: Decodable, Sendable {
    let digiKeyProductNumber: String
    let quantityAvailableforPackageType: Int?
    let minimumOrderQuantity: Int?
    let standardPricing: [DigiKeyStandardPricing]?

    enum CodingKeys: String, CodingKey {
        case digiKeyProductNumber = "DigiKeyProductNumber"
        case quantityAvailableforPackageType = "QuantityAvailableforPackageType"
        case minimumOrderQuantity = "MinimumOrderQuantity"
        case standardPricing = "StandardPricing"
    }
}

struct DigiKeyStandardPricing: Decodable, Sendable {
    let breakQuantity: Int
    let unitPrice: Double

    enum CodingKeys: String, CodingKey {
        case breakQuantity = "BreakQuantity"
        case unitPrice = "UnitPrice"
    }
}
