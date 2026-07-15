// swift-tools-version: 6.2
//
// Volta — macOS 27+ Liquid Glass app shell.
// ponytail: SPM over .xcodeproj — simpler, fully macOS 27+ compatible, no PBX hell.
import PackageDescription

// DEVNOTE Phase 161: SPM's macOS platform enum currently tops out at `.v26`
// (SDK 26.5 ships with Xcode 26.5). The `.v27` symbol arrives with the
// macOS 27 SDK in Xcode 27. To target macOS 27 at the ABI level today
// without waiting, we declare `.v26` (highest available) and then force
// `-target arm64-apple-macosx27.0` via `unsafeFlags`. When Xcode 27 ships,
// remove the unsafeFlags and change `.v26` → `.v27`. Tracked in SUMMARY.
let package = Package(
    name: "Volta",
    platforms: [
        // macOS 27+ for Liquid Glass + FoundationModels.
        // iOS 18+ for iPhone/iPad companion (Phase 226).
        .macOS(.v26),
        .iOS(.v18)
    ],
    products: [
        .executable(
            name: "Volta",
            targets: ["Volta"]
        ),
        // Phase 226: Shared library for iOS + macOS targets.
        .library(
            name: "VoltaPCBCore",
            targets: ["VoltaPCBCore"]
        )
    ],
    dependencies: [
        // Phase 164: MLX-Swift for in-process Metal-accelerated LLM inference.
        .package(
            url: "https://github.com/ml-explore/mlx-swift",
            from: "0.31.6"
        ),
        // Phase 210: MLX LM for the autoregressive generation loop + LoRA
        // adapter loading. Provides MLXLMCommon (pipeline, generate, tokenizer).
        .package(
            url: "https://github.com/ml-explore/mlx-swift-lm",
            from: "3.31.4"
        ),
        // Phase 210.1: HuggingFace Hub client + tokenizers (required by MLXHuggingFace macros).
        .package(
            url: "https://github.com/huggingface/swift-huggingface",
            from: "0.1.0"
        ),
        .package(
            url: "https://github.com/huggingface/swift-transformers",
            from: "1.3.3"
        )
    ],
    targets: [
        // Phase 226: Cross-platform core library (iOS + macOS).
        // Contains parser, ERC/DRC, VoltaEngine, models — no daemon deps.
        .target(
            name: "VoltaPCBCore",
            path: "Sources/VoltaPCBCore"
        ),
        .executableTarget(
            name: "Volta",
            dependencies: [
                "VoltaPCBCore",
                .product(name: "MLX", package: "mlx-swift"),
                .product(name: "MLXNN", package: "mlx-swift"),
                .product(name: "MLXLLM", package: "mlx-swift-lm"),
                .product(name: "MLXLMCommon", package: "mlx-swift-lm"),
                .product(name: "MLXHuggingFace", package: "mlx-swift-lm"),
                .product(name: "HuggingFace", package: "swift-huggingface"),
                .product(name: "Tokenizers", package: "swift-transformers")
            ],
            swiftSettings: [
                .unsafeFlags(["-target", "arm64-apple-macosx27.0"]),
            ],
            linkerSettings: [
                .unsafeFlags(["-target", "arm64-apple-macosx27.0"]),
            ]
        ),
        .testTarget(
            name: "VoltaTests",
            dependencies: ["Volta"],
            swiftSettings: [
                .unsafeFlags(["-target", "arm64-apple-macosx27.0"]),
            ],
            linkerSettings: [
                .unsafeFlags(["-target", "arm64-apple-macosx27.0"]),
            ]
        )
    ]
)
