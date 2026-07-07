# Architecture Research: v6.0 KiCad Agent — The Closed Box

**Domain:** Native Mac+iPhone app with conversational hardware design
**Researched:** 2026-07-07
**Confidence:** HIGH

## Executive Summary

The v6.0 architecture wraps the existing Python kicad-agent library (142 ops, validation gates, routing stack) in a native Swift/macOS+iPhone app that delivers closed-box conversational hardware design. The architecture follows a **compiler model** where conversation state is the source of truth and KiCad files (.kicad_sch, .kicad_pcb) are derived artifacts regenerated from an event-sourced journal.

**Key architectural principles:**
1. **Daemon-spawned stdio MCP** — Swift app spawns Python daemon subprocess, communicates via JSON-RPC over stdio (no HTTP by default)
2. **Event-sourced memory** — All decisions/value changes stored as events, enabling time-travel and project genealogy
3. **Generative transform pipeline** — Conversation state → SKIDL IR → KiCad files (hash-based gold master tests)
4. **Obdurate Runtime** — State machine, op journal, verification gates, escalation ladder (extends routing/audit.py patterns)
5. **Apple-native collaboration** — SwiftData + CloudKit sync, Group Activities for live sessions, CKShare for invitations
6. **Zero infrastructure** — BYOK with Keychain sync, HF Hub for models (no developer AI bill), iCloud Drive for files

## Standard Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│  SwiftUI UI Surfaces (Track D)                                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐               │
│  │ Liquid Glass │  │ Inline Render│  │ GSD Conv Eng │               │
│  │   App Shell  │  │ SVG/PNG View │  │ questioning   │               │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘               │
│         │                 │                    │                       │
├─────────┼─────────────────┼────────────────────┼─────────────────────┤
│         │         SwiftData + CloudKit (Track E) │                     │
│  ┌──────▼──────┐  ┌───────┴──────┐  ┌───────────▼─────────┐         │
│  │  Project    │  │  Conversation│  │ Decision Timeline   │         │
│  │  Model      │  │  Model        │  │ Time-Travel UI      │         │
│  └─────────────┘  └──────────────┘  └─────────────────────┘         │
├──────────────────────────────────────────────────────────────────────┤
│  Provider Router (Track B)                                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐               │
│  │ Foundation   │  │ HF Hub       │  │ MLX-Swift    │               │
│  │ Models (BYOK)│  │ Custom       │  │ Local        │               │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘               │
│         │                 │                    │                       │
├─────────┼─────────────────┼────────────────────┼─────────────────────┤
│         │         DaemonMCPClient (Track C)      │                     │
│  ┌──────▼──────────────────▼─────────────────────▼──────────┐        │
│  │  stdio MCP Bridge (Swift) ↔ Python Daemon (Process)      │        │
│  └───────────────────────────────────────────────────────────┘        │
├──────────────────────────────────────────────────────────────────────┤
│  Python Daemon (bundled, app-spawned subprocess)                       │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  MCP Server (142 ops as tools)                                │    │
│  │  Obdurate Runtime (state machine, op journal, gates)          │    │
│  │  Verification Loop (validation_gates.py integration)          │    │
│  │  Generative Transform (SKIDL compiler)                        │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────────┐
│  Collaboration Layer (Track G)                                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐               │
│  │ Project      │  │ Group        │  │ CKShare      │               │
│  │ Genealogy    │  │ Activities   │  │ Invitations  │               │
│  └─────────────┘  └──────────────┘  └──────────────┘               │
└─────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|------------|----------------|------------------------|
| **Liquid Glass App Shell** | macOS 26+ SwiftUI app container, window management, toolbar | SwiftUI App, WindowGroup, ScenePhase lifecycle |
| **Inline Rendering** | SVG schematic preview, PNG PCB render, live pipeline view | QuickLook (SVG), Image (PNG), AsyncImage + cache |
| **GSD Conversation Engine** | Visual questioning → spec → roadmap → execute → verify | TabView with @State phase navigation, Observable Conversation |
| **SwiftData Models** | Project, Conversation, Message, Decision, ValueChange, ProjectSnapshot | @Model macro, @Attribute, @Relationship |
| **CloudKit Sync** | Automatic Mac↔iPhone sync, conflict resolution (LWW), private DB | CloudKit container, CKRecord, syncSKSubscription |
| **Provider Router** | Task-aware model routing (circuit gen vs routing vs analysis), cost tracking | LLMProvider Protocol, Anthropic/Ollama/HFHub adapters |
| **DaemonMCPClient** | stdio JSON-RPC client, Process lifecycle, tool auto-registration | Process(), Pipe JSON streaming, MCP protocol codec |
| **Python MCP Server** | Expose 142 ops as MCP tools, validation gates, routing stack | mcp.Server, stdio transport, Pydantic schema → Tool schemas |
| **Obdurate Runtime** | State machine, op journal (JSONL), verification gates, escalation | State enum, Transition guard, Journal (fsync), GateRunner |
| **Generative Transform** | Conversation → SKIDL IR → KiCad files, hash-based gold master | SKIDL compiler (v5.0 work), Pipeline, Hash test fixtures |
| **Project Genealogy** | Family tree, branches, snapshots, false starts | Graph models, parent/child relationships, versioning |
| **Group Activities** | Live session events (conversation state, not files), 4-participant cap | GroupActivities framework, MessengerSessionDelegate |
| **CKShare Invitations** | Collaborator invitations, permission management | CKShare, UICloudSharingController, permission tiers |
| **Quality Gate** | swift-testing, SwiftCheck, mutation testing, 100% coverage | XCTest, swift-testing, mull-xcode, CI coverage enforcement |

## Recommended Project Structure

```
KiCadAgent/
├── KiCadAgentApp.swift                  # App entry point
├── Models/                              # SwiftData models (Track E)
│   ├── Project.swift                    # @Model project container
│   ├── Conversation.swift               # @Model conversation state
│   ├── Message.swift                    # @Model message entities
│   ├── Decision.swift                   # @Model decision events
│   ├── ValueChange.swift                # @Model value change events
│   ├── ProjectSnapshot.swift            # @Model time-travel snapshots
│   └── Genealogy/                       # Project genealogy (Track G)
│       ├── ProjectBranch.swift          # Branch/fork relationships
│       └── FamilyTree.swift             # Visual family tree
├── Providers/                           # AI model layer (Track B)
│   ├── LLMProvider.swift                # Protocol for all providers
│   ├── FoundationModelsProvider.swift   # Built-in models (BYOK)
│   ├── HFHubProvider.swift              # Hugging Face models
│   ├── MLXSwiftProvider.swift           # Local MLX models
│   ├── ProviderRouter.swift             # Task-aware routing
│   └── KeychainManager.swift            # BYOK storage + sync
├── Daemon/                              # Python daemon bridge (Track C)
│   ├── DaemonMCPClient.swift            # stdio MCP client
│   ├── ProcessManager.swift             # Process lifecycle (spawn/kill)
│   ├── ToolRegistry.swift               # Auto-registered MCP tools
│   ├── JSONRPCCoder.swift               # JSON-RPC codec
│   └── MCPToolBridge.swift              # Swift → MCP tool call adapter
├── Governance/                          # Obdurate Runtime (Track C)
│   ├── StateMachine.swift                # GSD phase state machine
│   ├── OpJournal.swift                   # JSONL audit trail (fsync)
│   ├── VerificationGates.swift           # Python validation_gates.py wrapper
│   ├── GateRunner.swift                 # Gate execution orchestrator
│   └── EscalationLadder.swift           # Rick escalation (T1→T2→T3→T4)
├── Generative/                          # Transform pipeline (Track F)
│   ├── SKIDLCompiler.swift               # Conversation → SKIDL IR
│   ├── KiCadGenerator.swift             # SKIDL → .kicad_sch/.kicad_pcb
│   ├── PipelineOrchestrator.swift       # Full pipeline orchestration
│   ├── HashGoldMaster.swift             # Hash-based test fixtures
│   └── GenerativeCache.swift            # Cached derived artifacts
├── Collaboration/                       # Collaboration layer (Track G)
│   ├── CloudKitSync.swift               # SwiftData + CloudKit bridge
│   ├── GroupActivitiesSession.swift     # Live session events
│   ├── CKShareManager.swift             # Collaborator invitations
│   ├── ProjectBundle.swift              # .kicadagent iCloud Drive bundle
│   └── EventSync.swift                  # Conversation event payloads
├── UI/                                  # SwiftUI views (Track D)
│   ├── AppRootView.swift                # Main app container
│   ├── LiquidGlassShell.swift           # App shell with toolbar
│   ├── InlineRendering/
│   │   ├── SchematicPreviewView.swift   # SVG inline preview
│   │   ├── PCBPreviewView.swift         # PNG inline preview
│   │   └── PipelineStatusView.swift    # Live pipeline progress
│   ├── GSDConversationEngine/
│   │   ├── QuestioningView.swift        # Questioning phase UI
│   │   ├── SpecView.swift               # Spec phase UI
│   │   ├── RoadmapView.swift            # Roadmap phase UI
│   │   ├── ExecuteView.swift            # Execute phase UI
│   │   ├── VerifyView.swift            # Verify phase UI
│   │   └── ApprovalGatesView.swift      # Human approval gates UI
│   └── Memory/
│       ├── DecisionTimelineView.swift   # Decision timeline UI
│       ├── TimeTravelView.swift         # Time-travel scrub UI
│       └── ProjectGenealogyView.swift  # Family tree visualizer
├── Resources/                           # Bundled resources
│   ├── kicad-cli                        # Bundled KiCad 10 CLI
│   ├── python-stdlib/                   # Minimal Python stdlib
│   ├── daemon/                          # Bundled Python daemon
│   └── models/                          # HF Hub model cache
└── Tests/                               # Test suite (Track H)
    ├── UnitTests/                        # swift-testing unit tests
    ├── IntegrationTests/                 # Daemon integration tests
    ├── SnapshotTests/                   # 4-variant snapshot tests
    ├── PropertyTests/                   # SwiftCheck property tests
    └── MutationTests/                    # mull-xcode mutation tests

PythonDaemon/ (bundled as app resource)
├── kicad_agent/
│   ├── daemon/
│   │   ├── mcp_server.py                # stdio MCP server (142 ops)
│   │   ├── obdurate_runtime.py         # State machine + journal + gates
│   │   └── generative_transform.py     # SKIDL compiler pipeline
│   ├── ops/                             # Existing 142 ops (unchanged)
│   ├── routing/                         # Existing routing stack (unchanged)
│   └── validation/                      # Existing validation gates (unchanged)
└── daemon_entry.py                      # Python entry point
```

### Structure Rationale

- **Models/**: SwiftData models are the core — everything depends on event-sourced state
- **Providers/**: Clean separation between AI providers and app logic (BYOK, privacy)
- **Daemon/**: Swift ↔ Python IPC is the critical bridge — isolate for testing
- **Governance/**: Obdurate Runtime extends Python routing/audit.py patterns app-wide
- **Generative/**: SKIDL compiler is the differentiator — isolate for hash-based testing
- **Collaboration/**: Apple-native collaboration — CloudKit, Group Activities, CKShare
- **UI/**: SwiftUI views are thin — state lives in SwiftData models
- **Resources/**: Bundled daemon, kicad-cli, minimal dependencies (zero infrastructure)

## Architectural Patterns

### Pattern 1: Swift ↔ Python IPC via stdio MCP

**What:** Swift app spawns Python daemon as subprocess, communicates via JSON-RPC over stdio pipes. No HTTP by default (opt-in for external clients like Claude Code).

**When to use:** All in-app Python daemon communication. Required for zero-infrastructure local architecture.

**Trade-offs:**
- **Pros:** Zero network overhead, no HTTP server needed, simple subprocess lifecycle, works with sandboxed macOS apps
- **Cons:** Process spawning overhead (~100ms), stdio buffering requires explicit flush, need robust process crash recovery

**Example:**
```swift
// DaemonMCPClient.swift
import Foundation

final class DaemonMCPClient: Sendable {
    private let process: Process()
    private let stdinPipe: Pipe
    private let stdoutPipe: Pipe
    private let jsonEncoder: JSONEncoder = .init()
    private let jsonDecoder: JSONDecoder = .init()
    
    func spawn() async throws {
        process.executableURL = Bundle.main.url(forResource: "python_daemon", withExtension: nil)
        process.arguments = ["-m", "kicad_agent.daemon.mcp_server"]
        
        // stdio pipes for JSON-RPC
        process.standardInput = stdinPipe
        process.standardOutput = stdoutPipe
        
        try process.run()
        
        // Spawn background task to read stdout
        Task {
            await readOutputContinuously()
        }
    }
    
    func callTool(_ name: String, arguments: [String: Any]) async throws -> MCPResponse {
        let request = MCPRequest(
            jsonrpc: "2.0",
            id: UUID().uuidString,
            method: "tools/call",
            params: [
                "name": name,
                "arguments": arguments
            ]
        )
        
        let encoded = try jsonEncoder.encode(request)
        stdinPipe.fileHandleForWriting.write(encoded)
        
        // Wait for response with matching ID
        return try await waitForResponse(id: request.id)
    }
    
    private func readOutputContinuously() async {
        for await line in stdoutPipe.fileHandleForReading.bytes.lines {
            guard let data = line.data(using: .utf8) else { continue }
            
            if let response = try? jsonDecoder.decode(MCPResponse.self, from: data) {
                await handleResponse(response)
            }
        }
    }
}
```

**Python daemon side:**
```python
# daemon/mcp_server.py
from mcp.server import Server
from mcp.server.stdio import stdio_server
from kicad_agent.ops.registry import get_all_operations

app = Server("kicad-agent-daemon", version="6.0.0")

@app.list_tools()
async def list_tools() -> list[Tool]:
    """Auto-register all 142 ops as MCP tools."""
    ops = get_all_operations()
    return [
        Tool(
            name=op.op_type,
            description=op.description,
            inputSchema=op.input_schema
        )
        for op in ops
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Route to existing OperationExecutor."""
    from kicad_agent.ops.executor import OperationExecutor
    from kicad_agent.ops.schema import Operation
    
    executor = OperationExecutor(base_dir=Path.cwd())
    op = Operation.model_validate({"op_type": name, **arguments})
    result = executor.execute(op)
    
    return [TextContent(type="text", text=json.dumps(result))]

async def main():
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
```

### Pattern 2: Generative Transform Pipeline (Compiler Model)

**What:** Conversation state is source of truth. KiCad files (.kicad_sch, .kicad_pcb) are derived artifacts regenerated from event-sourced journal. Follows compiler model: source code → compiler → binary.

**When to use:** All circuit generation. Conversation → SKIDL → KiCad files.

**Trade-offs:**
- **Pros:** Single source of truth, reproducible builds, time-travel by replaying events, diff-friendly
- **Cons:** Initial compilation time (~1-5s), must cache derived files for performance

**Example:**
```swift
// Generative/PipelineOrchestrator.swift
import Foundation

struct PipelineOrchestrator {
    let daemonClient: DaemonMCPClient
    let cache: GenerativeCache
    
    func regenerateKiCadFiles(from conversation: Conversation) async throws -> KiCadArtifact {
        // Check cache first
        let stateHash = conversation.computeStateHash()
        if let cached = cache.getArtifact(forHash: stateHash) {
            return cached
        }
        
        // 1. Conversation → SKIDL IR (via LLM)
        let skidlCode = try await generateSKIDL(from: conversation)
        
        // 2. SKIDL → KiCad files (via daemon)
        let schematicResult = try await daemonClient.callTool(
            "skidl_to_kicad_sch",
            arguments: ["skidl_code": skidlCode]
        )
        
        // 3. Validation gates (ERC/DRC)
        let ercResult = try await daemonClient.callTool(
            "validate_erc",
            arguments: ["schematic_path": schematicResult["schematic_path"]]
        )
        
        guard ercResult["valid"] == true else {
            throw GenerationError.ercFailed(ercResult["errors"])
        }
        
        // 4. Cache and return
        let artifact = KiCadArtifact(
            schematic: schematicResult["schematic_path"],
            pcb: schematicResult["pcb_path"],
            state_hash: stateHash,
            generated_at: Date()
        )
        
        cache.setArtifact(artifact, forHash: stateHash)
        return artifact
    }
}
```

**Hash-based gold master testing:**
```swift
// Tests/HashGoldMasterTests.swift
import Testing

struct HashGoldMasterTests {
    @Test func conversationGeneratesExpectedSchematic() async throws {
        let conversation = try loadFixtureConversation("simple_led")
        let orchestrator = PipelineOrchestrator(...)
        let artifact = try await orchestrator.regenerateKiCadFiles(from: conversation)
        
        let schematicData = try Data(contentsOf: URL(fileURLWithPath: artifact.schematic))
        let schematicHash = schematicData.sha256()
        
        // Expected hash from gold master fixture
        let expectedHash = "a1b2c3d4..."  // Pre-computed from known-good output
        
        #expect(schematicHash == expectedHash)
    }
}
```

### Pattern 3: Event-Sourced Memory + Time-Travel

**What:** All decisions and value changes stored as events in SwiftData. Time-travel by replaying events from any point. Snapshot materialization creates full project state at any event index.

**When to use:** All state changes. Decision timeline, project genealogy, undo/redo, "what if" exploration.

**Trade-offs:**
- **Pros:** Complete audit trail, reproducible states, efficient event storage, diff-friendly
- **Cons:** Event replay cost (mitigated by snapshots), must compact event log periodically

**Example:**
```swift
// Models/Decision.swift
import SwiftData

@Model
final class Decision {
    var id: UUID
    var conversationId: UUID
    var eventType: DecisionEventType
    var timestamp: Date
    var eventData: Data  // Codable decision payload
    
    enum DecisionEventType {
        case componentAdded
        case netRouted
        case footprintChanged
        case constraintAdded
        // ... all decision types
    }
}

// Models/ProjectSnapshot.swift
@Model
final class ProjectSnapshot {
    var id: UUID
    var conversationId: UUID
    var eventIndex: Int  // Materialized at this point in event stream
    var stateHash: String
    var schematicData: Data
    var pcbData: Data
    var createdAt: Date
    var isAutoSnapshot: Bool  // True = auto on decisions, False = manual
    var metadata: [String: String]  // Freeform tags
}

// Memory/TimeTravelEngine.swift
struct TimeTravelEngine {
    let context: ModelContext
    let daemonClient: DaemonMCPClient
    
    func createSnapshot(at eventIndex: Int, for conversation: Conversation) async throws -> ProjectSnapshot {
        // 1. Replay events up to eventIndex
        let replayedState = try await replayEvents(upTo: eventIndex, from: conversation)
        
        // 2. Regenerate KiCad files from replayed state
        let artifact = try await regenerateKiCadFiles(from: replayedState)
        
        // 3. Create snapshot
        let schematicData = try Data(contentsOf: URL(fileURLWithPath: artifact.schematic))
        let pcbData = try Data(contentsOf: URL(fileURLWithPath: artifact.pcb))
        
        let snapshot = ProjectSnapshot(
            id: UUID(),
            conversationId: conversation.id,
            eventIndex: eventIndex,
            stateHash: artifact.stateHash,
            schematicData: schematicData,
            pcbData: pcbData,
            createdAt: Date(),
            isAutoSnapshot: false,
            metadata: [:]
        )
        
        context.insert(snapshot)
        try context.save()
        
        return snapshot
    }
    
    func diff(snapshotA: ProjectSnapshot, snapshotB: ProjectSnapshot) -> ProjectDiff {
        // Line-by-line diff of schematic/pcb data
        let schematicDiff = DiffUtil.unidiff(
            snapshotA.schematicData,
            snapshotB.schematicData
        )
        
        let pcbDiff = DiffUtil.unidiff(
            snapshotA.pcbData,
            snapshotB.pcbData
        )
        
        return ProjectDiff(schematic: schematicDiff, pcb: pcbDiff)
    }
    
    private func replayEvents(upTo eventIndex: Int, from conversation: Conversation) async throws -> Conversation {
        // Deep copy conversation
        var replayed = conversation.copy()
        
        // Fetch events up to target index
        let descriptor = FetchDescriptor<Decision>()
        descriptor.predicate = #Predicate { $0.conversationId == conversation.id }
        let events = try context.fetch(descriptor).filter { $0.eventIndex <= eventIndex }
        
        // Apply events in order
        for event in events.sorted(by: { $0.eventIndex < $1.eventIndex }) {
            replayed = try await applyEvent(event, to: replayed)
        }
        
        return replayed
    }
}
```

### Pattern 4: SwiftData + CloudKit Sync

**What:** SwiftData models automatically sync via CloudKit private database. Conflict resolution uses Last-Writer-Wins (LWW) with prompts for value changes. .kicadagent bundle stored in iCloud Drive.

**When to use:** All SwiftData models that sync across Mac+iPhone. Project, Conversation, Message, Decision, ValueChange, ProjectSnapshot.

**Trade-offs:**
- **Pros:** Zero-infrastructure sync, automatic merge propagation, native iOS/macOS support
- **Cons:** CloudKit latency (~1-5s), conflict resolution complexity (LWW with prompts), private DB only (no sharing)

**Example:**
```swift
// Collaboration/CloudKitSync.swift
import SwiftData
import CloudKit

@Model
final class Project {
    var id: UUID
    var title: String
    var createdAt: Date
    var updatedAt: Date  // For LWW conflict resolution
    var conversations: [Conversation]?
    
    // CloudKit sync metadata
    var ckRecordID: String?
    var ckRecordChangeTag: String?
}

// App entry point
@main
struct KiCadAgentApp: App {
    let modelContainer: ModelContainer
    
    init() {
        let schema = Schema([
            Project.self,
            Conversation.self,
            Message.self,
            Decision.self,
            ValueChange.self,
            ProjectSnapshot.self,
            ProjectBranch.self
        ])
        
        let cloudKitConfiguration = CloudKitSchemaConfiguration(
            schema: schema,
            cloudKitDatabase: .private(.automated)
        )
        
        do {
            modelContainer = try ModelContainer(
                for: schema,
                cloudKitDatabase: .automatic()
            )
        } catch {
            fatalError("Failed to create ModelContainer: \(error)")
        }
    }
    
    var body: some Scene {
        WindowGroup {
            AppRootView()
        }
        .modelContainer(modelContainer)
    }
}

// Conflict resolution (LWW with prompts)
struct ConflictResolver {
    func resolveValueChange(_ local: ValueChange, _ remote: ValueChange) -> ValueChange {
        // Last-Writer-Wins based on timestamp
        if remote.timestamp > local.timestamp {
            // Prompt user about incoming change
            promptUserAboutChange(remote)
            return remote
        } else {
            return local
        }
    }
    
    private func promptUserAboutChange(_ change: ValueChange) {
        // Show alert/banner: "Collaborator updated resistor R1 value: 1kΩ → 10kΩ"
    }
}
```

### Pattern 5: Provider Router with Task-Aware Routing

**What:** Central router selects AI provider based on task type, cost awareness, privacy awareness. Circuit generation uses MLX-Swift local models, routing uses Gemma 4 12B V2 vision, analysis uses FoundationModels.

**When to use:** All LLM calls. Centralizes provider selection logic.

**Trade-offs:**
- **Pros:** Cost optimization, privacy awareness, task-specific model selection, easy provider swapping
- **Cons:** Routing complexity, must track cost/latency/quality per provider

**Example:**
```swift
// Providers/ProviderRouter.swift
enum TaskType {
    case circuitGeneration      // Use MLX-Swift local (cost: $0)
    case pcbRouting            // Use Gemma 4 12B V2 vision (cost: $0, local)
    case boardAnalysis         // Use FoundationModels (cost: $0.001/1K tokens)
    case conversationHistory   // Use FoundationModels (cost: $0.0005/1K tokens)
}

struct ProviderRouter {
    let foundationModelsProvider: FoundationModelsProvider
    let hfHubProvider: HFHubProvider
    let mlxSwiftProvider: MLXSwiftProvider
    
    func selectProvider(for task: TaskType) -> LLMProvider {
        switch task {
        case .circuitGeneration:
            // Use MLX-Swift for free local generation
            return mlxSwiftProvider
            
        case .pcbRouting:
            // Use Gemma 4 12B V2 vision (local via MLX-Swift)
            return mlxSwiftProvider
            
        case .boardAnalysis:
            // Use FoundationModels (built-in, free)
            return foundationModelsProvider
            
        case .conversationHistory:
            // Use FoundationModels for history analysis
            return foundationModelsProvider
        }
    }
    
    func estimateCost(for task: TaskType, inputTokens: Int, outputTokens: Int) -> Decimal {
        let provider = selectProvider(for: task)
        return provider.estimateCost(input: inputTokens, output: outputTokens)
    }
}
```

**BYOK with Keychain storage:**
```swift
// Providers/KeychainManager.swift
import Security
import Foundation

struct KeychainManager {
    func storeAPIKey(_ key: String, for provider: String) throws {
        let data = key.data(using: .utf8)!
        
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: provider,
            kSecValueData as String: data,
            kSecAttrSynchronizable as String: true  // iCloud Keychain sync
        ]
        
        let status = SecItemAdd(query as CFDictionary, nil)
        
        if status == errSecDuplicateItem {
            // Update existing
            let updateQuery: [String: Any] = [
                kSecClass as String: kSecClassGenericPassword,
                kSecAttrAccount as String: provider
            ]
            let updateAttributes: [String: Any] = [
                kSecValueData as String: data
            ]
            SecItemUpdate(updateQuery as CFDictionary, updateAttributes as CFDictionary)
        } else if status != errSecSuccess {
            throw KeychainError.unhandledError(status: status)
        }
    }
    
    func getAPIKey(for provider: String) throws -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: provider,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        
        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        
        guard status == errSecSuccess,
              let data = result as? Data,
              let key = String(data: data, encoding: .utf8) else {
            return nil
        }
        
        return key
    }
}
```

### Pattern 6: Group Activities Event Sync

**What:** Group Activities v1 for live collaboration sessions (4-participant cap). Syncs conversation events (decisions, value changes), not KiCad files (files synced via iCloud Drive separately). Event payloads contain minimal state changes (delta sync).

**When to use:** Live collaboration sessions. Real-time design review, pair programming, team decisions.

**Trade-offs:**
- **Pros:** Native iOS/macOS support, FaceTime integration, zero infrastructure
- **Cons:** 4-participant cap (v1 limitation), event ordering complexity, must handle offline gracefully

**Example:**
```swift
// Collaboration/GroupActivitiesSession.swift
import GroupActivities

struct KiCadDesignSession: GroupActivity {
    var metadata: GroupActivityMetadata {
        var metadata = GroupActivityMetadata()
        metadata.title = "KiCad Design Session"
        metadata.type = .generic
        return metadata
    }
    
    // Event payload (minimal delta sync)
    struct DecisionEvent: Codable {
        var conversationId: UUID
        var eventId: UUID
        var eventType: String
        var payload: Data
        var timestamp: Date
        var author: String  // Participant name
    }
    
    var decisionEvents: [DecisionEvent] = []
}

struct GroupActivitiesManager {
    var session: KiCadDesignSession?
    var messenger: GroupSessionMessenger?
    
    func startSession() async throws {
        let newSession = KiCadDesignSession()
        
        try await newSession.join()
        
        self.session = newSession
        self.messenger = .init(for: newSession)
        
        // Subscribe to incoming events
        Task {
            await subscribeToEvents()
        }
    }
    
    private func subscribeToEvents() async {
        guard let messenger else { return }
        
        for await event in messenger.events {
            switch event {
            case .message(let message):
                await handleIncomingEvent(message)
            case .participantStateChanged(let state):
                await handleParticipantChange(state)
            }
        }
    }
    
    func broadcastDecision(_ decision: Decision) async throws {
        guard let messenger else { return }
        
        let event = KiCadDesignSession.DecisionEvent(
            conversationId: decision.conversationId,
            eventId: decision.id,
            eventType: String(describing: decision.eventType),
            payload: decision.eventData,
            timestamp: decision.timestamp,
            author: currentUser
        )
        
        let message = GroupSessionMessage(
            payload: event
        )
        
        try await messenger.send(message)
    }
    
    private func handleIncomingEvent(_ message: GroupSessionMessage) async {
        let event = message.payload
        
        // Apply remote event to local SwiftData
        let context = modelContext
        let localDecision = Decision(
            id: event.eventId,
            conversationId: event.conversationId,
            eventType: ..., // decode event.eventType
            timestamp: event.timestamp,
            eventData: event.payload
        )
        
        context.insert(localDecision)
        try context.save()
        
        // Trigger UI update
        await notifyUIOfIncomingDecision(localDecision)
    }
}
```

### Pattern 7: Verification Loop with Obdurate Runtime

**What:** Extends existing Python routing/audit.py patterns app-wide. State machine enforces GSD phase transitions (questioning → research → planning → review → execute → verify). Op journal (JSONL) records every operation with fsync durability. Verification gates (ERC/DRC, validation_gates.py) run before commits. Escalation ladder auto-triggers on failures (T1→T2→T3→T4).

**When to use:** All state transitions, operation execution, verification. App-wide governance.

**Trade-offs:**
- **Pros:** Deterministic state machine, complete audit trail, auto-escalation on failures, reusable routing/audit.py patterns
- **Cons:** State machine complexity, escalation tuning (false positives), journal compaction overhead

**Example:**
```swift
// Governance/StateMachine.swift
enum GSDPhase: String, Codable {
    case questioning
    case research
    case planning
    case review
    case execute
    case verification
    case complete
}

enum GSDStateTransition {
    case questioningToResearch
    case researchToPlanning
    case planningToReview
    case reviewToExecute      // Requires APPROVED plan
    case executeToVerification
    case verificationToComplete
    case reviewToRejected     // Plan rejected, back to planning
    case executeToBlocked     // Verification failed
}

struct GSDStateMachine {
    var currentPhase: GSDPhase = .questioning
    
    mutating func transition(_ transition: GSDStateTransition, planApproved: Bool = false) throws {
        let (nextPhase, guardCondition) = try validateTransition(transition, planApproved: planApproved)
        
        guard guardCondition else {
            throw StateMachineError.transitionGuardFailed(transition)
        }
        
        currentPhase = nextPhase
    }
    
    private func validateTransition(_ transition: GSDStateTransition, planApproved: Bool) throws -> (GSDPhase, Bool) {
        switch transition {
        case .questioningToResearch:
            return (.research, true)  // Always allowed
            
        case .planningToReview:
            return (.review, true)  // Always allowed
            
        case .reviewToExecute:
            // Hard guard: plan must be APPROVED
            return (.execute, planApproved)
            
        case .executeToVerification:
            return (.verification, true)  // Always allowed
            
        case .verificationToComplete:
            // Hard guard: verification must pass
            return (.complete, planApproved)  // planApproved reused as verificationPassed
            
        default:
            throw StateMachineError.invalidTransition(transition)
        }
    }
}

// Governance/OpJournal.swift
import Foundation

struct OpJournalEntry: Codable {
    var timestamp: ISO8601Date
    var operationType: String
    var operationId: UUID
    var parameters: [String: AnyCodable]
    var result: [String: AnyCodable]
    var executionTimeMs: Int64
    var phase: GSDPhase
}

struct OpJournal {
    let fileURL: URL
    let queue: DispatchQueue
    
    func append(_ entry: OpJournalEntry) throws {
        let encoded = try JSONEncoder().encode(entry)
        let line = String(data: encoded, encoding: .utf8)! + "\n"
        
        queue.async {
            guard let handle = try? FileHandle(forWritingTo: self.fileURL) else { return }
            defer { try? handle.close() }
            
            handle.seekToEndOfFile()
            handle.write(line.data(using: .utf8)!)
            handle.synchronizeFile()  // fsync durability (H5)
        }
    }
    
    func queryByOperation(_ operationId: UUID) throws -> [OpJournalEntry] {
        let content = try String(contentsOf: fileURL, encoding: .utf8)
        let lines = content.split(separator: "\n")
        
        return try lines.compactMap { line in
            guard let data = line.data(using: .utf8) else { return nil }
            let entry = try JSONDecoder().decode(OpJournalEntry.self, from: data)
            return entry.operationId == operationId ? entry : nil
        }
    }
}

// Governance/GateRunner.swift
struct GateRunner {
    let daemonClient: DaemonMCPClient
    let journal: OpJournal
    let escalationLadder: EscalationLadder
    
    func runVerificationGates(for plan: Plan) async throws -> GateResult {
        // Pre-gate: ERC check
        let ercResult = try await daemonClient.callTool(
            "validate_erc",
            arguments: ["schematic_path": plan.schematicPath]
        )
        
        guard ercResult["valid"] == true else {
            // Trigger escalation on failure
            await escalationLadder.recordFailure(
                task: "ERC validation",
                severity: .critical,
                details: ercResult["errors"]
            )
            
            return GateResult(
                passed: false,
                failures: ["ERC failed: \(ercResult["errors"])"],
                escalationTier: escalationLadder.currentTier
            )
        }
        
        // DRC check
        let drcResult = try await daemonClient.callTool(
            "validate_drc",
            arguments: ["pcb_path": plan.pcbPath]
        )
        
        guard drcResult["valid"] == true else {
            await escalationLadder.recordFailure(
                task: "DRC validation",
                severity: .critical,
                details: drcResult["errors"]
            )
            
            return GateResult(
                passed: false,
                failures: ["DRC failed: \(drcResult["errors"])"],
                escalationTier: escalationLadder.currentTier
            )
        }
        
        return GateResult(passed: true, failures: [], escalationTier: .none)
    }
}

// Governance/EscalationLadder.swift
enum EscalationTier: Int {
    case none = 0
    case T1  // Single Rick review
    case T2  // Council (4 specialists)
    case T3  // Full Council (all-hands)
    case T4  // Grand Council (23) + pause for human
}

struct EscalationLadder {
    var currentTier: EscalationTier = .none
    var failureCounts: [String: Int] = [:]
    
    mutating func recordFailure(task: String, severity: Severity, details: [String]) async {
        let count = (failureCounts[task] ?? 0) + 1
        failureCounts[task] = count
        
        // Auto-escalate based on failure count
        switch count {
        case 1:
            currentTier = .T1
            await triggerSingleRickReview(task: task, details: details)
            
        case 2:
            currentTier = .T2
            await triggerCouncilReview(task: task, details: details)
            
        case 3:
            currentTier = .T3
            await triggerFullCouncil(task: task, details: details)
            
        case 5:
            currentTier = .T4
            await triggerGrandCouncil(task: task, details: details)
            // Pause for human input
            await pauseForHumanIntervention()
            
        default:
            break
        }
    }
    
    private func triggerSingleRickReview(task: String, details: [String]) async {
        // Delegate to specialist agent
    }
    
    private func triggerCouncilReview(task: String, details: [String]) async {
        // Delegate to 4 specialists
    }
    
    private func triggerFullCouncil(task: String, details: [String]) async {
        // Delegate to all-hands
    }
    
    private func triggerGrandCouncil(task: String, details: [String]) async {
        // Delegate to all 23 specialists
    }
    
    private func pauseForHumanIntervention() async {
        // Show UI: "Escalation T4: Manual intervention required"
    }
}
```

### Pattern 8: MCP Auto-Registration (Zero Glue)

**What:** Every Python operation (142 ops) auto-registers as MCP tool. Zero glue code. Pydantic schemas → Tool schemas. OperationExecutor unchanged.

**When to use:** All 142 ops exposed as MCP tools. No custom tool registration needed.

**Trade-offs:**
- **Pros:** Zero glue, automatic tool discovery, schema consistency, ops registry as single source
- **Cons:** Large tool list (142 tools), must filter/sort for UI presentation

**Example:**
```python
# daemon/mcp_server.py
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from kicad_agent.ops.registry import get_all_operations
from kicad_agent.ops.executor import OperationExecutor
from kicad_agent.ops.schema import Operation

app = Server("kicad-agent-daemon", version="6.0.0")

@app.list_tools()
async def list_tools() -> list[Tool]:
    """Auto-register all 142 ops as MCP tools."""
    ops = get_all_operations()
    
    tools = []
    for op in ops:
        # Convert Pydantic schema to JSON Schema for Tool inputSchema
        input_schema = _pydantic_to_json_schema(op.schema_class)
        
        tools.append(Tool(
            name=op.op_type,
            description=op.description,
            inputSchema=input_schema
        ))
    
    return tools

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Route to existing OperationExecutor (unchanged)."""
    executor = OperationExecutor(base_dir=Path.cwd())
    
    # Construct operation from tool name + arguments
    op = Operation.model_validate({
        "op_type": name,
        **arguments
    })
    
    # Execute via existing executor (unchanged)
    result = executor.execute(op)
    
    return [TextContent(
        type="text",
        text=json.dumps(result, indent=2)
    )]

def _pydantic_to_json_schema(pydantic_class: type[BaseModel]) -> dict:
    """Convert Pydantic model to JSON Schema for MCP Tool."""
    return pydantic_class.model_json_schema()

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())
```

## Data Flow

### Request Flow

```
[User Action: "Add a 10kΩ resistor to the input"]
    ↓
[SwiftUI UI]
    ↓ (update SwiftData)
[Conversation Model] ← [Message: "Add a 10kΩ resistor"]
    ↓ (Provider Router)
[LLMProvider] → [FoundationModels / MLX-Swift / HFHub]
    ↓ (returns: operation JSON)
[DaemonMCPClient]
    ↓ (stdio JSON-RPC)
[Python MCP Server] → [OperationExecutor] → [SchematicIR mutation]
    ↓ (serialize)
[.kicad_sch file] → [Validation Gate (ERC)]
    ↓ (pass)
[SwiftData] ← [Decision event stored]
    ↓ (trigger)
[Inline Rendering] → [SVG preview updated]
```

### State Management

```
[SwiftData Persistent Store]
    ↓ (CloudKit sync)
[iCloud Drive]
    ↓ (subscribe)
[Mac+iPhone apps]
    ↓ (query)
[SwiftUI Views]
    ↓ (user action)
[SwiftData insert/update]
    ↓ (trigger)
[DaemonMCPClient] → [Python ops]
    ↓ (result)
[SwiftData update] → [UI refresh]
```

### Key Data Flows

1. **Conversation → KiCad Files:** User types intent → LLM generates SKIDL → Python daemon compiles to .kicad_sch/.kicad_pcb → validation gates → SwiftData Decision event → UI update
2. **Time-Travel:** User scrubs timeline → TimeTravelEngine replays events → regenerates KiCad files from snapshot → UI shows diff → user restores → current conversation updated
3. **Collaboration:** Participant A makes decision → GroupActivities broadcasts event → Participant B receives → SwiftData updated → KiCad files regenerated → UI syncs
4. **Verification Loop:** Plan execution → GateRunner runs ERC/DRC → failure → EscalationLadder triggers T1 review → fix → retry → pass → complete phase

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 0-1K users | Single macOS app instance, local Python daemon, iCloud Drive storage |
| 1K-10K users | Same architecture (Apple handles CloudKit scale), daemon multiprocessing |
| 10K+ users | Consider server-side daemon pool (external HTTP MCP), CloudKit private DB scales automatically |

### Scaling Priorities

1. **First bottleneck:** Python daemon subprocess spawn time (~100ms) — mitigate with daemon process pooling
2. **Second bottleneck:** iCloud Drive sync latency (~1-5s) — mitigate with optimistic UI updates (show decisions immediately, sync in background)
3. **Third bottleneck:** Group Activities 4-participant cap — mitigate with session sharding (multiple sessions per project)

## Anti-Patterns

### Anti-Pattern 1: Direct File Mutation Without Events

**What people do:** Modify .kicad_sch/.kicad_pcb directly without storing Decision events

**Why it's wrong:** Breaks time-travel, loses audit trail, can't replay conversation state

**Do this instead:** Always store Decision event first, then regenerate KiCad files from conversation state

### Anti-Pattern 2: HTTP MCP Server by Default

**What people do:** Expose HTTP MCP server for in-app communication

**Why it's wrong:** Unnecessary infrastructure, network overhead, security risk (local HTTP attack surface)

**Do this instead:** Use stdio MCP by default (in-app), HTTP MCP opt-in only for external clients (Claude Code, Cursor)

### Anti-Pattern 3: Hardcoded Provider Selection

**What people do:** Hardcode FoundationModels for all LLM calls

**Why it's wrong:** Loses cost optimization, can't use task-specific models, no privacy awareness

**Do this instead:** Use ProviderRouter with task-aware routing (circuit gen → MLX-Swift, analysis → FoundationModels)

### Anti-Pattern 4: Manual Tool Registration

**What people do:** Manually register each MCP tool in Swift code

**Why it's wrong:** Code duplication, drift from ops registry, maintenance burden

**Do this instead:** Auto-register from ops registry (142 ops → 142 MCP tools, zero glue)

### Anti-Pattern 5: Skipping Verification Gates

**What people do:** Apply operations without running ERC/DRC validation

**Why it's wrong:** Corrupts files silently, violates "safe editing" principle, accumulates technical debt

**Do this instead:** Always run validation gates before commit (Obdurate Runtime enforces this)

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| **FoundationModels** | Swift AI SDK (built-in) | BYOK with Keychain, free tier, macOS 26+ only |
| **Hugging Face Hub** | HFHubProvider (custom) | Model downloads, zero dev infra, cache in ~/Library |
| **CloudKit** | SwiftData + CKRecord | Auto-sync Mac↔iPhone, private DB, LWW conflict resolution |
| **iCloud Drive** | .kicadagent bundle | Project files storage, document type, CKShare for invitations |
| **Group Activities** | GroupActivities framework | Live sessions, 4-participant cap, event sync (not files) |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|--------|
| **Swift ↔ Python** | stdio MCP (JSON-RPC) | Daemon subprocess, Process spawning, pipe lifecycle |
| **SwiftData ↔ CloudKit** | CloudKit automatic sync | Private DB, conflict resolution (LWW with prompts) |
| **Provider Router ↔ LLMs** | Protocol-based (LLMProvider) | FoundationModels, HFHub, MLX-Swift implementations |
| **UI ↔ SwiftData** | @Query + @ModelContext | SwiftUI observes SwiftData, automatic UI updates |
| **Obdurate Runtime ↔ Python** | MCP tools (state_machine, gates) | Python executor, Swift orchestration |
| **Generative ↔ Daemon** | MCP tools (skidl_to_kicad, validate_erc) | SKIDL compiler, validation gates |

## Build Order and Dependencies

### Track Dependencies

```
Track A (Foundation) ──────────────────────────────────────┐
    ↓                                                       │
Track B (Models) ←────────────────────────────────────────┤
    ↓                                                       │
Track C (Governance) ←────────────────────────────────────┤
    ↓                                                       │
Track D (UI Surfaces) ──────┐                             │
    ↓                       │                             │
Track E (Memory) ←─────────┘                             │
    ↓                       ┐                             │
Track F (Generative) ←─────┼─────┐                       │
    ↓                       │     │                       │
Track G (Collaboration) ←──┘     │                       │
    ↓                             │                       │
Track H (Quality) ◄────────────────┴───────────────────────┘
```

### Build Order (Respecting Dependencies)

1. **Track A — Foundation** (Phases 161-163): App shell, Python daemon bundling, kicad-cli integration
   - **Unblocks:** Track B (needs app shell), Track C (needs daemon)
   
2. **Track B — Models** (Phases 164-166): LLMProvider protocol, Provider Router, BYOK Keychain storage
   - **Unblocks:** Track C (needs providers for LLM calls), Track F (needs generative models)
   
3. **Track C — Governance** (Phases 167-170): stdio MCP client, Obdurate Runtime, Verification Loop
   - **Unblocks:** Track D (needs governance for UI gates), Track E (needs journal for events)
   
4. **Track D — UI Surfaces** (Phases 171-175): Liquid Glass shell, Inline Rendering, GSD Conversation Engine
   - **Unblocks:** Track E (needs UI for timeline), Track G (needs UI for collaboration)
   
5. **Track E — Memory** (Phases 176-180): SwiftData models, CloudKit sync, Time-Travel, Decision Timeline
   - **Unblocks:** Track F (needs conversation state for generation), Track G (needs events for sync)
   
6. **Track F — Generative** (Phases 181-185): SKIDL compiler, Generative Transform, Pipeline, Hash Gold Master
   - **Unblocks:** Track G (needs derived files for sharing), v6.0 completion
   
7. **Track G — Collaboration** (Phases 186-190): Project Genealogy, Group Activities, CKShare, iCloud Drive bundle
   - **Unblocks:** v6.0 completion
   
8. **Track H — Quality** (Phases 191-202): swift-testing, Snapshot tests, SwiftCheck, Mutation testing, Coverage enforcement
   - **Runs in parallel:** All tracks (quality is continuous, not gated)

### Component Breakdown per Track

#### Track A — Foundation (Phases 161-163)
- **A1:** macOS 26+ SwiftUI app shell (Liquid Glass)
- **A2:** Python daemon bundling (PyInstaller, app-spawned subprocess)
- **A3:** kicad-cli bundling + minimal Python stdlib
- **Responsibilities:** App container, daemon lifecycle, bundled resources

#### Track B — Models (Phases 164-166)
- **B1:** LLMProvider protocol (FoundationModels, HFHub, MLX-Swift)
- **B2:** Provider Router (task-aware, cost-aware, privacy-aware)
- **B3:** BYOK Keychain storage + iCloud sync
- **Responsibilities:** AI abstraction, provider selection, API key management

#### Track C — Governance (Phases 167-170)
- **C1:** stdio MCP client (Process, Pipe, JSON-RPC)
- **C2:** Python MCP server (142 ops auto-registered)
- **C3:** Obdurate Runtime (state machine, op journal, gates, escalation)
- **C4:** Verification Loop (validation_gates.py integration)
- **Responsibilities:** Daemon communication, state enforcement, audit trail

#### Track D — UI Surfaces (Phases 171-175)
- **D1:** Liquid Glass shell (toolbar, window management)
- **D2:** Inline Rendering (SVG schematic, PNG PCB, pipeline status)
- **D3:** GSD Conversation Engine (questioning → spec → roadmap → execute → verify)
- **D4:** Approval Gates UI (human approval prompts)
- **Responsibilities:** User interface, visualization, conversation flow

#### Track E — Memory (Phases 176-180)
- **E1:** SwiftData models (Project, Conversation, Message, Decision, ValueChange, ProjectSnapshot)
- **E2:** CloudKit sync (auto-sync Mac↔iPhone, LWW conflict resolution)
- **E3:** Time-Travel (replay, snapshot, diff, restore)
- **E4:** Decision Timeline UI
- **Responsibilities:** Event-sourced memory, cross-device sync, time-travel UX

#### Track F — Generative (Phases 181-185)
- **F1:** SKIDL compiler (Conversation → SKIDL IR)
- **F2:** KiCad generator (SKIDL → .kicad_sch/.kicad_pcb)
- **F3:** Pipeline orchestration (full transform pipeline)
- **F4:** Hash-based gold master tests (fixture hashing)
- **Responsibilities:** Generative transform, pipeline correctness, test coverage

#### Track G — Collaboration (Phases 186-190)
- **G1:** Project Genealogy (family tree, branches, snapshots)
- **G2:** Group Activities (live sessions, event sync, 4-participant cap)
- **G3:** CKShare invitations (permission management)
- **G4:** iCloud Drive .kicadagent bundle
- **Responsibilities:** Collaboration UX, real-time sync, project sharing

#### Track H — Quality (Phases 191-202)
- **H1:** swift-testing framework (unit tests, 100% line+branch coverage)
- **H2:** Snapshot tests (4 variants: light/dark/XXXL/high-contrast)
- **H3:** SwiftCheck (property-based testing)
- **H4:** mull-xcode (mutation testing, >90% score)
- **H5:** a11y by default (SwiftLint custom rules)
- **H6:** CI coverage enforcement (gate on <100% coverage)
- **Responsibilities:** Test infrastructure, coverage enforcement, a11y compliance

## Sources

- [Model Context Protocol — Official Specification](https://modelcontextprotocol.io/) — HIGH confidence (MCP stdio transport)
- [SwiftData + CloudKit — Apple Documentation](https://developer.apple.com/documentation/swiftdata) — HIGH confidence (official Apple docs)
- [FoundationModels — Apple Documentation](https://developer.apple.com/machine-learning/foundation-models/) — HIGH confidence (official Apple docs)
- [Group Activities — Apple Documentation](https://developer.apple.com/documentation/groupactivities) — HIGH confidence (official Apple docs)
- [CloudKit — Apple Documentation](https://developer.apple.com/documentation/cloudkit) — HIGH confidence (official Apple docs)
- [KiCad 10 File Format — KiCad Documentation](https://docs.kicad.org/) — HIGH confidence (KiCad 10 S-expression format)
- [SKIDL — SKIDL Documentation](https://skidl.readthedocs.io/) — MEDIUM confidence (SKIDL IR patterns)
- [MLX-Swift — MLX Community](https://github.com/ml-explore/mlx-swift) — MEDIUM confidence (MLX-Swift integration)
- [Python multiprocessing — Python Documentation](https://docs.python.org/3/library/multiprocessing.html) — HIGH confidence (subprocess patterns)
- [Pydantic — Pydantic Documentation](https://docs.pydantic.dev/) — HIGH confidence (schema validation)

---

*Architecture research for: v6.0 KiCad Agent — The Closed Box*
*Researched: 2026-07-07*
