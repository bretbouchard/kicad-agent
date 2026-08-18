// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "VoltaGSAPlatformProof",
    platforms: [
        .macOS(.v14),
    ],
    dependencies: [
        .package(path: "../../../gsa-platform"),
    ],
    targets: [
        .testTarget(
            name: "VoltaGSAPlatformProofTests",
            dependencies: [
                .product(name: "GSAPlatform", package: "gsa-platform"),
                .product(name: "GSAModeledWorld", package: "gsa-platform"),
            ]
        ),
    ]
)
