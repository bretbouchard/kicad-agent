# Technology Stack — v6.0 Mac+iPhone App

**Domain:** Native SwiftUI macOS 26+ / iOS 26+ app for KiCad automation
**Researched:** 2026-07-07
**Overall confidence:** HIGH

## Executive Summary

The v6.0 stack is **Apple-native first** — SwiftUI + FoundationModels + MLX-Swift + Swift AI SDK for a closed-box experience with zero infrastructure. Python daemon bundled via PyInstaller, stdio MCP transport for in-app communication, SwiftData + CloudKit for event-sourced memory with auto-sync. Key differentiator: **pure BYOK with direct provider connections** (no proxying, no developer AI bill liability).

**Critical constraint:** macOS 27.0+ required (FoundationModels dependency). This is intentional — clean break from legacy APIs, access to built-in on-device AI.

## Recommended Stack

### Core Frameworks (Apple-built, no installation)

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| **SwiftUI** | macOS 26+ / iOS 26+ | Native UI framework | Liquid Glass visual language requires SwiftUI state machines. Declarative, type-safe, cross-platform (Mac+iPhone from single codebase). |
| **FoundationModels** | macOS 27.0+ / iOS 27.0+ | On-device LLM with tool calling | **Default AI provider** (free, built-in, no API keys). Tool calling via `GenerationOptions.ToolCallingMode.allowed/required`. Structured output via `@Generable` macro. Zero cost per request. |
| **SwiftData** | macOS 14+ / iOS 17+ | Persistence layer for event-sourced memory | Replaces Core Data with Swift-first API. `@Model` macro, auto CloudKit sync via `ModelConfiguration.CloudKitDatabase.automatic`. Type-safe, async/await native. |
| **CloudKit** | Built-in iCloud | Cross-device sync + collaboration | Auto-sync Mac↔iPhone via private database. CKShare for project sharing. CKGroupSession for live collaboration (Group Activities framework). |
| **Network framework** | Built-in macOS 10+ / iOS 12+ | Bonjour LAN auto-pairing | `NWBrowser`/`NWListener` for zero-configuration IP discovery. Replaces deprecated `NSNetService`. TCP connections between Mac+iPhone. |
| **Group Activities** | Built-in iOS 15+ / macOS 12+ | Live collaboration sessions | `CKGroupSession` for real-time shared state. 4-participant cap in v1 (raise later if needed). |

### Swift Packages (via Swift Package Manager)

| Package | Version | Purpose | Why |
|--------|---------|---------|-----|
| **Swift AI SDK** | v0.18.2 | Unified provider abstraction + BYOK | 37+ provider modules (OpenAI, Anthropic, Google, etc.) via one API. Swap providers without changing call sites. Middleware hooks for auth/observability. **Pure BYOK** — API keys stored in Keychain, direct provider connections. |
| **MLX Swift** | 0.31.6 | In-process Metal-accelerated ML | Loads fine-tuned LoRA adapters from Hugging Face (zero dev infra). `mlx-swift-lm` package for LLM/VLM implementations. **No mlx-server** — runs in-process, Metal-accelerated. |
| **swift-testing** | swift-6.3.2-RELEASE | Modern testing framework | Expressive APIs, `@Test` macros, parameterized tests, parallel execution. Replaces XCTest for greenfield projects. |
| **SnapshotTesting** | 1.19.2 (PointFree) | 4-variant snapshot testing | Assert UI across light/dark/XXXL/high-contrast. `withSnapshotTesting(record:diffTool:)` for scoped configuration. Critical for Liquid Glass visual regression. |
| **SwiftCheck** | 0.12.0 | Property-based testing | Randomized test generation for invariants. Shrinks counterexamples to minimal cases. Use for state machine transitions, tool calling logic, decision journal validation. |
| **MCP Swift SDK** | modelcontextprotocol/swift-sdk | Stdio MCP client | Official Swift implementation of Model Context Protocol. `StdioClientTransport(process.inputStream, process.outputStream)` for daemon communication. |

### Python Packages (bundled with daemon)

| Package | Version | Purpose | Why |
|---------|---------|---------|-----|
| **mcp** | 1.28.1 | MCP server implementation | `mcp.run(transport="stdio")` exposes 142+ kicad-agent operations as MCP tools. Line-delimited JSON-RPC over stdin/stdout. |
| **PyInstaller** | v6.21.0 | Python → .app bundling | Generates standalone `MyApp.app` with Python daemon + kicad-cli inside `MacOS/`. `--codesign-identity` + `--osx-entitlements-file` for code signing. |
| **kicad-agent** | Local Python library | Core KiCad automation | Existing 142 operations, AST mutation, validation gates. Bundled as daemon subprocess (not LaunchAgent). |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| **SwiftLint** | Style enforcement + a11y rules | Custom rules via `custom_rules:` YAML. Enforce `accessibilityLabel` on all interactive elements. 0.65.0 verified. |
| **mull-xcode** | Mutation testing | >90% mutation score enforced in CI. Requires separate Mull installation. Catches logic gaps coverage misses. |
| **xcrun notarytool** | Notarization for distribution | Required for macOS 26+ apps outside Mac App Store. `xcrun notarytool submit MyApp.app` after code signing. |
| **codesign** | Code signing | `codesign -s "Developer ID Application"` for production. Ad-hoc signing for development (`-` identity). |

## Integration Patterns

### Pattern 1: Swift AI SDK BYOK Flow

```swift
import SwiftAISDK
import OpenAIProvider
import Foundation

// 1. Store API key in Keychain (opt-out iCloud sync)
let keychainItem = KeychainItem(
  service: "com.kicadagent.apikeys",
  account: "openai"
)
try keychainItem.setValue(apiKey)

// 2. Provider reads from Keychain or environment
let openaiProvider = OpenAIProvider(
  apiKey: ProcessInfo.processInfo.environment["OPENAI_API_KEY"] 
    ?? KeychainItem(service: "...", account: "openai").getValue()
)

// 3. Use unified API (same signature for all providers)
let result = try await generateText(
  model: openaiProvider.languageModel(modelId: "gpt-4"),
  prompt: "Design a 555 timer circuit"
)
```

**Why this pattern:** Pure BYOK. No proxying. Direct provider connections. Keychain sync optional (opt-out by default). App never sees the key.

### Pattern 2: MLX Swift LoRA Loading

```swift
import MLX
import MLXNN
import MLXLM

// 1. Load base model from Hugging Face (in-process, Metal)
let model = loadLM(modelName: "mlx-community/KiCadGPT-4B")

// 2. Load fine-tuned LoRA adapter
let adapter = loadAdapter(
  model: model,
  adapterPath: URL.documentsDirectory.appendingPathComponent("adapters/pcb-routing-v1.safetensors")
)

// 3. Generate with fine-tuned model
let output = try await adapter.generate(prompt: "Route this PCB: ...")
```

**Why this pattern:** Zero infrastructure. HF Hub model downloads. In-process Metal acceleration (no mlx-server subprocess). LoRA adapters for domain-specific tasks (routing, placement, legibility).

### Pattern 3: FoundationModels Tool Calling

```swift
import FoundationModels

// 1. Define tool (KiCad operation)
struct AddComponentTool: Codable {
  @Generable
  static func toolDefinition() -> ToolDefinition {
    ToolDefinition(
      name: "add_component",
      description: "Add a component to the schematic",
      inputSchema: ComponentSpec.self
    )
  }
  
  func execute(input: ComponentSpec) async throws -> ComponentResult {
    // Call Python daemon via MCP stdio
  }
}

// 2. Configure model with tool calling
let options = GenerationOptions(
  toolCallingMode: .allowed,  // or .required
  tools: [AddComponentTool.toolDefinition()]
)

// 3. Generate with tool calls
let response = try await generation.generate(
  prompt: "Add a 10k resistor to the schematic",
  generationOptions: options
)

// 4. Execute tool calls
for try await toolCall in response.toolCalls {
  let result = try await executeTool(toolCall)
}
```

**Why this pattern:** Built-in to macOS 27+. Free. No API keys. On-device privacy. Structured output via `@Generable`.

### Pattern 4: SwiftData + CloudKit Event-Sourced Memory

```swift
import SwiftData

// 1. Define event-sourced model
@Model
final class DesignDecision {
  var timestamp: Date
  var projectId: String
  var decisionId: String
  var type: DecisionType  // enum: component, placement, routing
  var inputValue: String
  var outputValue: String
  var provenance: Provenance  // which model, which operation
  var confidence: Double
}

// 2. Configure CloudKit auto-sync
let config = ModelConfiguration(
  cloudKitDatabase: .automatic,  // Uses primary ubiquity container from Entitlements.plist
  cloudKitContainerIdentifier: "iCloud.com.kicadagent.projects"
)
let container = try ModelContainer(for: DesignDecision.self, configurations: config)

// 3. Query for time-travel
let context = container.mainContext
let decisions = try context.fetch(
  FetchDescriptor<DesignDecision>(
    predicate: #Predicate { $0.projectId == projectId && $0.timestamp < snapshotDate }
  )
)

// 4. Rebuild KiCad file from decision journal
let schematic = rebuildSchematic(from: decisions)
```

**Why this pattern:** Event-sourced memory enables time-travel (snapshot any point, diff, restore). CloudKit auto-sync Mac↔iPhone. LWW conflict resolution with prompts.

### Pattern 5: MCP Stdio Transport (Swift ↔ Python)

```swift
import MCP

// 1. Spawn Python daemon
let process = Process()
process.executableURL = URL(fileURLWithPath: "/App/MacOS/daemon")
process.arguments = ["--mcp-stdio"]
try process.run()

// 2. Connect via stdio
let transport = StdioClientTransport(
  input: process.fileHandleForReading,
  output: process.fileHandleForWriting
)

// 3. Initialize MCP client
let mcpClient = McpClient.sync(transport).build()
try mcpClient.initialize()

// 4. List kicad-agent tools (142 operations)
let tools = try mcpClient.listTools()

// 5. Call tool
let result = try mcpClient.callTool(
  CallToolRequest(
    name: "add_component",
    arguments: [
      "target_file": "board.kicad_sch",
      "lib_id": "Device:R",
      "reference": "R1",
      "value": "10k"
    ]
  )
)
```

**Why this pattern:** No HTTP by default (cleaner security model). Stdio is dead simple (line-delimited JSON). Python daemon lifecycle controlled by app (not LaunchAgent). 142+ operations exposed as tools.

### Pattern 6: PyInstaller Bundling + Code Signing

```python
# spec file for PyInstaller
app = BUNDLE(
    coll,
    name='KiCadAgent.app',
    icon=None,
    bundle_identifier='com.kicadagent.app',
    version='1.0.0',
    info_plist={
        'NSPrincipalClass': 'NSApplication',
        'NSAppleScriptEnabled': False,
        'CFBundleDocumentTypes': [
            {
                'CFBundleTypeName': 'KiCad Project',
                'CFBundleTypeIconFile': 'kicad.icns',
                'LSItemContentTypes': ['com.kicad.kicad_sch'],
                'LSHandlerRank': 'Owner'
            }
        ]
    },
)

# EXE class for code signing
exe = EXE(
    pyz,
    target_script,
    target_name='daemon',
    codesign_identity='Developer ID Application: Your Name (TEAM_ID)',
    entitlements_file='entitlements.plist',
    osx_hardened_runtime=True
)
```

**Why this pattern:** Single `.app` bundle containing Swift UI + Python daemon + kicad-cli. `--osx-hardened-runtime` for security. `entitlements.plist` for file/system access. Ad-hoc signing for dev (`-` identity), production cert for distribution.

## Installation

### Swift Packages

```swift
// Package.swift
dependencies: [
  // AI layer
  .package(url: "https://github.com/teunlao/swift-ai-sdk.git", from: "0.18.2"),
  .package(url: "https://github.com/ml-explore/mlx-swift", from: "0.31.6"),
  .package(url: "https://github.com/modelcontextprotocol/swift-sdk", from: "1.0.0"),
  
  // Testing
  .package(url: "https://github.com/swiftlang/swift-testing", from: "0.10.0"),
  .package(url: "https://github.com/pointfreeco/swift-snapshot-testing", from: "1.19.2"),
  .package(url: "https://github.com/typelift/SwiftCheck", from: "0.12.0"),
]

targets: [
  .target(
    name: "KiCadAgentApp",
    dependencies: [
      .product(name: "SwiftAISDK", package: "swift-ai-sdk"),
      .product(name: "OpenAIProvider", package: "swift-ai-sdk"),
      .product(name: "AnthropicProvider", package: "swift-ai-sdk"),
      .product(name: "MLX", package: "mlx-swift"),
      .product(name: "MLXNN", package: "mlx-swift"),
      .product(name: "MLXLM", package: "mlx-swift"),
      .product(name: "MCP", package: "swift-sdk"),
    ]
  )
]
```

### Python Bundling

```bash
# Build Python daemon with PyInstaller
pyinstaller \
  --onefile \
  --name daemon \
  --codesign-identity "Developer ID Application: Your Team" \
  --osx-entitlements-file entitlements.plist \
  --osx-hardened-runtime \
  --add-data "/usr/local/bin/kicad-cli:kicad-cli" \
  --hidden-import kicad_agent.ops.executor \
  src/kicad_agent/ops/mcp_server.py

# Copy into macOS app bundle
cp dist/daemon KiCadAgent.app/Contents/MacOS/
cp /usr/local/bin/kicad-cli KiCadAgent.app/Contents/MacOS/

# Sign the entire app
codesign --force --deep --sign "Developer ID Application: Your Team" KiCadAgent.app

# Notarize (required for distribution)
xcrun notarytool submit KiCadAgent.app --apple-id "your@email.com" --password "app-specific-password" --team-id "TEAM_ID" --wait
```

### Development Tools

```bash
# SwiftLint (via Mint or SwiftPM)
mint install realm/swiftlint

# Custom a11y rules in .swiftlint.yml
custom_rules:
  accessibility_label:
    regex: "\\.(button|toggle|picker)\\("
    match_kinds: identifier
    message: "Interactive elements must have accessibilityLabel"
    severity: error

# mull-xcode (mutation testing)
brew install mull

# Run mutation tests
mull-cxx -test-framework=SwiftTesting --coverage-info=coverage.info
```

## Alternatives Considered

| Recommended | Alternative | Why Not |
|-------------|-------------|---------|
| **FoundationModels (built-in)** | OpenAI API only | FoundationModels is free + on-device + no API keys. Use OpenAI as cloud provider via Swift AI SDK for heavy tasks, FoundationModels for default. |
| **MLX Swift (in-process)** | mlx-server subprocess | mlx-server adds HTTP overhead. MLX Swift runs in-process with Metal acceleration. Cleaner architecture. |
| **stdio MCP transport** | HTTP MCP server | Stdio is simpler (no HTTP server needed). Daemon lifecycle controlled by app. Better security model (no network surface). |
| **SwiftData** | Core Data | SwiftData is Swift-first (no `@objc`, no `NSManagedObject`). Type-safe with `@Model` macro. Async/await native. Core Data is legacy. |
| **Network framework** | NSNetService / Bonjour C API | NSNetService deprecated. Network framework is Swift-native, async/await, cleaner API. |
| **PyInstaller bundled daemon** | PyPy standalone interpreter | PyInstaller generates single `.app` bundle. PyPy requires embedding build, more complex. |
| **Swift AI SDK** | Direct Anthropic/OpenAI SDKs | Swift AI SDK unifies 37+ providers via one API. Swap providers without changing code. Middleware hooks for auth/logging. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| **mlx-server** | Adds HTTP server subprocess. MLX Swift runs in-process with Metal acceleration. | MLX Swift direct imports (`MLX`, `MLXNN`, `MLXLM`). |
| **Custom HTTP MCP server** | Adds network surface. Stdio is simpler (no HTTP parsing). | MCP stdio transport (`StdioClientTransport`). |
| **Core Data** | Legacy ObjC runtime. SwiftData is Swift-first, type-safe, async/await native. | SwiftData with `@Model` macro. |
| **NSNetService** | Deprecated since macOS 12. | Network framework (`NWBrowser`/`NWListener`). |
| **Proxy-based AI SDKs** | Violates pure BYOK. Developer becomes liable for user AI bills. | Swift AI SDK with direct provider connections + Keychain storage. |
| **LaunchAgent for Python daemon** | App loses control over daemon lifecycle. Harder to debug. | Spawn subprocess from app (controlled lifecycle). |
| **Raw XCTest** | Legacy API. swift-testing has modern `@Test` macros, parameterized tests. | swift-testing framework (`@Test`, `@Suite`). |

## Stack Patterns by Variant

**If user enables cloud AI providers:**
- Use Swift AI SDK provider modules (OpenAI, Anthropic, etc.)
- API keys stored in Keychain with iCloud sync opt-out default
- Direct provider connections (no proxying)
- FoundationModels remains default for on-device tasks

**If user wants offline-only mode:**
- FoundationModels primary (built-in, free)
- MLX Swift with fine-tuned LoRA adapters (downloaded from HF Hub once)
- No external API calls

**If Mac+iPhone collaboration:**
- Bonjour (Network framework) for LAN auto-pairing
- CloudKit for iCloud sync (SwiftData auto-sync)
- CKShare for project sharing invitations
- Group Activities for live sessions (4-participant v1 cap)

**If testing generative transforms:**
- SwiftCheck for property-based testing (state machine invariants)
- SnapshotTesting for 4-variant UI regression (light/dark/XXXL/high-contrast)
- Hash-based gold master tests on KiCad file outputs
- mull-xcode for >90% mutation score

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| Swift AI SDK v0.18.2 | Swift 5.10+ | Requires Swift concurrency (async/await). |
| MLX Swift 0.31.6 | macOS 12+ (Metal 2) | Metal shaders required. Command-line SwiftPM cannot build shaders — use Xcode. |
| FoundationModels | macOS 27.0+ / iOS 27.0+ | **Hard requirement**. Clean break from legacy macOS versions. |
| SwiftData | macOS 14+ / iOS 17+ | Requires `@Model` macro support (Xcode 15+). |
| MCP Swift SDK | Swift 5.9+ | Uses `Sendable` concurrency. |
| PyInstaller v6.21.0 | Python 3.11+ | Tested with kicad-agent Python 3.11.11 runtime. |
| swift-testing swift-6.3.2-RELEASE | Swift 6.0+ | Swift 6 language mode required for full feature set. |

## Key Decision Rationale

**1. Why macOS 27.0+ required?**
FoundationModels framework requires macOS 27.0+ (iOS 27.0+). This is intentional — clean break from legacy APIs, access to built-in on-device AI. Users on older macOS versions must upgrade or use the Python CLI version.

**2. Why stdio MCP not HTTP?**
Simpler security model. No HTTP server to maintain. Daemon lifecycle controlled by app. Line-delimited JSON over stdin/stdout is trivial to debug. HTTP MCP available as opt-in for external clients (Claude Code, Cursor).

**3. Why MLX Swift not mlx-server?**
In-process Metal acceleration. No subprocess overhead. Direct Swift API access (no HTTP calls). Cleaner architecture for iOS (no background server complications).

**4. Why SwiftData over Core Data?**
Swift-first type safety. `@Model` macro eliminates `NSManagedObject` boilerplate. Async/await native. Auto CloudKit sync without `NSPersistentCloudKitContainer` complexity.

**5. Why pure BYOK?**
Developer has zero liability for user AI bills. Direct provider connections (no proxy costs). Keychain storage with optional iCloud sync. User owns their API keys.

**6. Why bundled daemon not LaunchAgent?**
App controls daemon lifecycle. Easier debugging (stdout/stderr visible in Xcode). No root permissions needed. Simpler installation (single `.app` bundle).

## Sources

### HIGH Confidence (Verified via Context7 + Official Docs)
- **Swift AI SDK v0.18.2** — `/teunlao/swift-ai-sdk`, docs: provider management, BYOK patterns, 37+ provider modules
- **MLX Swift 0.31.6** — `/ml-explore/mlx-swift`, README: LoRA adapter loading, Metal shaders, HF Hub integration
- **FoundationModels** — `/websites/developer_apple_foundationmodels`, docs: tool calling modes, @Generable macro, macOS 27.0+ requirement
- **SwiftData + CloudKit** — `/websites/developer_apple_swiftdata`, docs: `ModelConfiguration.CloudKitDatabase.automatic`, custom container, auto-sync
- **MCP stdio transport** — `/websites/modelcontextprotocol`, spec: JSON-RPC over stdin/stdout, line-delimited messages
- **PyInstaller v6.21.0** — `/pyinstaller/pyinstaller`, wiki: code signing, entitlements, Info.plist customization
- **swift-testing swift-6.3.2-RELEASE** — `/swiftlang/swift-testing`, docs: `@Test` macros, parameterized tests, parallel execution
- **SnapshotTesting 1.19.2** — `/pointfreeco/swift-snapshot-testing`, docs: `withSnapshotTesting`, 4-variant snapshots
- **SwiftCheck 0.12.0** — `/typelift/swiftcheck`, README: property-based testing, shrinking
- **SwiftLint 0.65.0** — `/realm/swiftlint`, docs: custom rules, a11y enforcement patterns
- **Python mcp 1.28.1** — PyPI verified via `pip show mcp`
- **Network framework** — `/websites/developer_apple_network`, docs: `NWBrowser`/`NWListener` for Bonjour

### MEDIUM Confidence (Official docs + web verification)
- **CKShare + Group Activities** — Apple CloudKit docs (verified pattern: CKShare for sharing, CKGroupSession for live sessions)
- **PyInstaller macOS hardening** — PyInstaller wiki + Apple notarization docs (verified: `--osx-hardened-runtime`, `xcrun notarytool`)
- **Code signing for App Store** — Apple developer docs (verified: `codesign`, `entitlements.plist`)

### LOW Confidence (Requires phase-specific research)
- **mull-xcode** — Mutation testing integration pattern (needs research during Track H execution)
- **HF Hub model download UX** — In-app download flow for LoRA adapters (needs UX research)

---
*Stack research for: v6.0 Mac+iPhone App*
*Researched: 2026-07-07*
