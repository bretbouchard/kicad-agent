// swift-tools-version: 6.0
// VoltaGSA — Volta's embedding of the GSA Platform (M2.3 foundation wave).
//
// Owns everything product-specific about Volta's GSA integration: boot
// configuration, principals, the governed-electronics schema in the Modeled
// World, and the electronics capabilities registered behind the Execution
// Broker.
//
// gsa-platform is pinned from GitHub (tag 0.1.0+). For local development
// against a checkout in ~/apps/gsa-platform, use:
//   swift package edit gsa-platform --path ~/apps/gsa-platform   (then `swift package unedit`)

import PackageDescription

let package = Package(
    name: "VoltaGSA",
    platforms: [
        .macOS(.v14),
        .iOS(.v17),
    ],
    products: [
        .library(name: "VoltaGSA", targets: ["VoltaGSA"]),
    ],
    dependencies: [
        .package(url: "https://github.com/bretbouchard/gsa-platform.git", from: "0.1.0"),
    ],
    targets: [
        .target(
            name: "VoltaGSA",
            dependencies: [
                .product(name: "GSAPlatform", package: "gsa-platform"),
                .product(name: "GSACore", package: "gsa-platform"),
                .product(name: "GSAModeledWorld", package: "gsa-platform"),
                .product(name: "GSAObdurate", package: "gsa-platform"),
                .product(name: "GSAEvidence", package: "gsa-platform"),
                .product(name: "GSACapabilityKernel", package: "gsa-platform"),
                .product(name: "GSAArtifacts", package: "gsa-platform"),
                .product(name: "GSAStewardshipRuntime", package: "gsa-platform"),
            ],
            path: "Sources/VoltaGSA",
            swiftSettings: [
                .enableExperimentalFeature("StrictConcurrency"),
                .enableUpcomingFeature("InferIsolatedConformances"),
            ]
        ),
        .testTarget(
            name: "VoltaGSATests",
            dependencies: [
                "VoltaGSA",
                .product(name: "GSAPlatform", package: "gsa-platform"),
            ],
            path: "Tests/VoltaGSATests",
            swiftSettings: [
                .enableExperimentalFeature("StrictConcurrency"),
            ]
        ),
    ]
)
