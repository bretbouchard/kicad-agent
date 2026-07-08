// swift-tools-version: 6.2
//
// KiCadAgent — macOS 27+ Liquid Glass app shell.
// ponytail: SPM over .xcodeproj — simpler, fully macOS 27+ compatible, no PBX hell.
import PackageDescription

// DEVNOTE Phase 161: SPM's macOS platform enum currently tops out at `.v26`
// (SDK 26.5 ships with Xcode 26.5). The `.v27` symbol arrives with the
// macOS 27 SDK in Xcode 27. To target macOS 27 at the ABI level today
// without waiting, we declare `.v26` (highest available) and then force
// `-target arm64-apple-macosx27.0` via `unsafeFlags`. When Xcode 27 ships,
// remove the unsafeFlags and change `.v26` → `.v27`. Tracked in SUMMARY.
let package = Package(
    name: "KiCadAgent",
    platforms: [
        // Forward-declared deployment target. Real target is macOS 27.0
        // per PROJECT.md decision 2026-07-07 (FoundationModels, Liquid Glass).
        .macOS(.v26)
    ],
    products: [
        .executable(
            name: "KiCadAgent",
            targets: ["KiCadAgent"]
        )
    ],
    dependencies: [
        // Phase 164: MLX-Swift for in-process Metal-accelerated LLM inference.
        // Used by MLXLocalProvider for loading .mlx fine-tuned models.
        // STACK.md decision: in-process MLX (not mlx-server subprocess).
        // MLXLM (LLM helpers) lives in mlx-swift-extras; we model .mlx
        // loading with MLX+MLXNN primitives here. Phase 165+ Router may
        // add mlx-swift-extras when shipping inference to end users.
        .package(
            url: "https://github.com/ml-explore/mlx-swift",
            from: "0.31.6"
        )
    ],
    targets: [
        .executableTarget(
            name: "KiCadAgent",
            dependencies: [
                // Phase 164: real MLX integration for VRAM probing and
                // model format validation. MLXLM (LLM loop) ships in
                // Phase 165 once Router lands.
                .product(name: "MLX", package: "mlx-swift"),
                .product(name: "MLXNN", package: "mlx-swift")
            ],
            // Force macOS 27 deployment target at the ABI level.
            // sdk 26.5 toolchain accepts this — produces binary that
            // refuses to launch on macOS 26 (which is what we want).
            swiftSettings: [
                .unsafeFlags(["-target", "arm64-apple-macosx27.0"]),
            ],
            linkerSettings: [
                .unsafeFlags(["-target", "arm64-apple-macosx27.0"]),
            ]
        ),
        .testTarget(
            name: "KiCadAgentTests",
            dependencies: ["KiCadAgent"],
            swiftSettings: [
                .unsafeFlags(["-target", "arm64-apple-macosx27.0"]),
            ],
            linkerSettings: [
                .unsafeFlags(["-target", "arm64-apple-macosx27.0"]),
            ]
        )
    ]
)
