# Research Summary: v6.0 KiCad Agent — The Closed Box

**Project:** KiCad Agent v6.0 (Mac+iPhone App)
**Domain:** Native macOS 27+ / iOS 27+ app with conversational hardware design
**Researched:** 2026-07-07
**Confidence:** HIGH

## Executive Summary

The v6.0 KiCad Agent is a **native SwiftUI app** that wraps the existing Python volta library (142 operations, validation gates, routing stack) in a closed-box conversational interface. The architecture follows a **compiler model**: conversation state is the source of truth, KiCad files (.kicad_sch, .kicad_pcb) are derived artifacts regenerated from an event-sourced journal. Key differentiator: **pure BYOK (Bring Your Own API Key)** with direct provider connections — the developer has zero liability for user AI bills.

**Recommended approach:** Apple-native first. SwiftUI + FoundationModels (built-in, free, macOS 27+) + MLX-Swift (local Metal-accelerated models) + SwiftData + CloudKit (zero infra sync). Python daemon bundled via PyInstaller, communicates via stdio MCP (line-delimited JSON-RPC, no HTTP by default). Collaboration via CKShare + Group Activities (4-participant cap, FaceTime-style sessions). No server infrastructure — Apple handles CloudKit scale, HF Hub handles models, users pay providers directly.

**Key risks and mitigation:**
1. **GPL licensing (P0):** Do NOT bundle kicad-cli — require external KiCad install or face App Store rejection
2. **FoundationModels unavailability (P0):** Graceful degradation to MLX-Swift + HF download on Intel Macs
3. **PyInstaller code signing corruption (P0):** Sign every embedded dylib individually before packaging
4. **stdio MCP buffering deadlock (P0):** Force line buffering with `PYTHONUNBUFFERED=1` or `-u` flag
5. **SwiftData CloudKit migration data loss (P0):** NEVER auto-migrate — use explicit `VersionedSchema` with two-device testing
6. **Generative transform hash instability (P0):** Hash only deterministic inputs, exclude timestamps/UUIDs, run 10-run determinism tests

## Key Findings

### Recommended Stack

**Core runtime (Apple-built, zero installation):**
- **SwiftUI** (macOS 26+ / iOS 26+) — Native UI framework, declarative, type-safe, cross-platform (Mac+iPhone from single codebase)
- **FoundationModels** (macOS 27.0+ / iOS 27.0+) — Built-in on-device LLM with tool calling, free, no API keys, structured output via `@Generable` macro
- **SwiftData** (macOS 14+ / iOS 17+) — Event-sourced persistence, `@Model` macro, auto CloudKit sync via `ModelConfiguration.CloudKitDatabase.automatic`
- **CloudKit** — Zero-infrastructure Mac↔iPhone sync, CKShare for invitations, GroupActivities for live sessions
- **Network framework** — Bonjour LAN auto-pairing for Mac+iPhone collaboration, `NWBrowser`/`NWListener` (replaces deprecated `NSNetService`)

**Swift packages:**
- **Swift AI SDK v0.18.2** — 37+ provider modules (OpenAI, Anthropic, Google) unified via one API, pure BYOK with Keychain storage
- **MLX Swift 0.31.6** — In-process Metal-accelerated ML, loads LoRA adapters from HF Hub, no mlx-server subprocess needed
- **MCP Swift SDK** — Stdio MCP client for Python daemon communication, line-delimited JSON-RPC over stdin/stdout

**Python daemon (bundled):**
- **mcp 1.28.1** — MCP server exposing 142 volta operations as tools, `mcp.run(transport="stdio")`
- **PyInstaller v6.21.0** — Python → .app bundling, code signing with `--osx-hardened-runtime`, entitlements for file/system access
- **volta** — Existing 142 operations, AST mutation, validation gates (unchanged)

**Critical constraint:** macOS 27.0+ required (FoundationModels dependency). This is intentional — clean break from legacy APIs, access to built-in on-device AI.

### Expected Features

**Must have (table stakes) — users expect these:**
- Inline schematic/PCB rendering — SVG for schematics (kicad-cli), PNG for PCBs, SwiftUI `Image` view with inline rendering
- Chat-with-inline-artifacts UI — Conversational intent → operations, message bubbles + embedded image previews
- Basic project management — Create/delete/list projects, SwiftData with CloudKit sync
- Model selection dropdown — Choose between FoundationModels (free) and HF Hub models
- Provider Settings UI (BYOK) — Enter API keys, Keychain integration, iCloud sync opt-out default
- Python Daemon bundled — Subprocess execution of kicad-cli and 142 ops, core engine
- MCP stdio daemon — App ↔ Python via stdio MCP, bridge layer
- Event-sourced memory (basic) — Journal all ops, enables undo/redo
- Undo/redo conversation — Basic mistake recovery, Command+Z pattern
- Export KiCad files — Standard share sheet, get files out
- Dark/light mode — System appearance sync, 2026 expectation
- Basic search — Full-text search over SwiftData store

**Should have (differentiators) — add after validation:**
- Conversation IS source of truth — Compiler model: conversation (source) → KiCad files (binary), enables time-travel, reproducibility
- Decision Timeline UI — Visual timeline of all project decisions with time-travel scrubbing
- Live Pipeline View — CI/CD-style step bar showing operation progress (ERC → placement → routing → DRC)
- GSD Conversation Engine — Visual spec/roadmap generation from conversational questioning
- Event-sourced memory — Every decision journaled immutably, full audit trail
- Project genealogy — Family tree showing branches, false starts, snapshots, merges
- CKShare collaboration — Native iCloud collaboration with view/edit/fork permissions
- Run-on conversations — Chapter segmentation for long-running projects
- Generative transform coupling — Conversation state drives generation, source = conversation, artifacts = derived
- Routing constraints capture — Conversation-driven constraint specification → .kicad_dru

**Defer to v2+ (not essential for launch):**
- GSD Conversation Engine — Full visual GSD methodology, massive effort, validate core first
- Conversation IS Source of Truth — Compiler model for hardware, high risk high reward, prove event sourcing first
- Generative Transform — SKIDL/SPICE integration, depends on v5.0 landing first
- iPhone Companion Mode — LAN pairing, offline queue, platform expansion
- Group Activities — FaceTime-style sessions, requires v1 collaboration proven
- Windows support — Cross-platform UI framework, dilute Apple-native quality bar
- Web version — Browser UI, sandbox limits, no kicad-cli

### Architecture Approach

The architecture wraps the existing Python volta library in a native Swift app with **compiler-model semantics**: conversation state is source of truth, KiCad files are derived artifacts regenerated from event-sourced journal.

**Major components:**
1. **SwiftUI UI Surfaces** — Liquid Glass app shell, inline rendering (SVG/PNG), GSD Conversation Engine, Approval Gates UI
2. **SwiftData + CloudKit** — Event-sourced models (Project, Conversation, Message, Decision, ValueChange, ProjectSnapshot), auto-sync Mac↔iPhone, LWW conflict resolution
3. **Provider Router** — Task-aware model routing (circuit gen → MLX-Swift, routing → Gemma 4 12B V2, analysis → FoundationModels), cost tracking, BYOK with Keychain
4. **DaemonMCPClient** — stdio JSON-RPC client, Process lifecycle, tool auto-registration (142 ops → 142 MCP tools)
5. **Python MCP Server** — stdio MCP server, Obdurate Runtime (state machine, op journal, gates), Verification Loop, Generative Transform
6. **Generative Transform Pipeline** — Conversation → SKIDL IR → KiCad files, hash-based gold master tests, pipeline orchestration
7. **Collaboration Layer** — Project Genealogy, Group Activities (4-participant cap), CKShare invitations, iCloud Drive .kicadagent bundle
8. **Quality Gate** — swift-testing, SwiftCheck property tests, mull-xcode mutation testing (>90% score), 100% coverage enforcement

**Key architectural patterns:**
- **stdio MCP Bridge** — Swift app spawns Python daemon, communicates via JSON-RPC over stdio (no HTTP by default)
- **Event-Sourced Memory** — All decisions stored as events, time-travel by replaying events, snapshot materialization
- **Generative Transform Pipeline** — Compiler model: conversation state → SKIDL → KiCad files, hash-based verification
- **SwiftData + CloudKit Sync** — Automatic Mac↔iPhone sync, conflict resolution via LWW with prompts
- **Provider Router** — Task-aware model selection, cost optimization, privacy awareness
- **Obdurate Runtime** — State machine enforcement, op journal (JSONL with fsync), verification gates, escalation ladder

### Critical Pitfalls

**6 P0 ship-blockers identified — MUST address before launch:**

1. **PyInstaller Code Signing Corruption (P0)** — App builds locally but crashes on launch for users with `killed: 9` or code signature invalid. Dylibs embedded by PyInstaller lose signatures during `--onefile` pack. **Avoid:** Sign EVERY embedded dylib individually before packaging, use `--onedir` for dylibs, verify with `codesign -dv`, test on clean machine. **Address in:** Track A Phase 161.

2. **stdio MCP Buffering Deadlock (P0)** — App hangs indefinitely waiting for Python response. Python stdout block-buffered when not TTY, Swift waits for stdout, Python waits for stdin. **Avoid:** Force line buffering with `PYTHONUNBUFFERED=1` or `-u` flag, use `\n` delimited protocol, add 30-second watchdog timer. **Address in:** Track C Phase 169.

3. **FoundationModels Unavailability Hard Failure (P0)** — App crashes or shows unavailable on Intel Macs or devices without Apple Intelligence. FoundationModels only on Apple Silicon Macs with 8+ GB RAM. **Avoid:** Check `FoundationModelsAvailability` at launch, graceful degradation to MLX-Swift + HF download, pre-flight check during onboarding, unit tests with availability stub. **Address in:** Track B Phase 163.

4. **SwiftData CloudKit Schema Migration Data Loss (P0)** — App updates with new schema, ALL project history vanishes. CloudKit requires exact schema match, may wipe local data on drift. **Avoid:** NEVER auto-migrate — use `VersionedSchema` with explicit migration plans, test two-device migration (Phone v1.0, Mac v1.1), freeze schema early. **Address in:** Track E Phase 173.

5. **Generative Transform Hash Instability (P0)** — Same conversation produces different KiCad files each generation, breaks event sourcing. Python dict ordering, JSON timestamps, floating point rounding cause drift. **Avoid:** Hash ONLY deterministic inputs (operation list, component set, net list, conversation intent), exclude timestamps/UUIDs, sort collections before hashing, store canonical JSON, run 10-run determinism tests. **Address in:** Track F Phase 183.

6. **App Store Review GPL Licensing Rejection (P0)** — Submission rejected for GPL violation because app bundles kicad-cli (GPLv3). Bundling GPL tool makes entire app GPLv3. **Avoid:** Do NOT bundle kicad-cli, require external KiCad install (detect via `which kicad-cli`), show helpful install prompt, document in App Store review notes. **Address in:** Track A Phase 162.

**Additional risks (P1-P2):**
- **iCloud Drive .kicadagent Bundle Corruption (P1)** — Simultaneous Mac+iPhone edit creates mixed state. Use `NSFileCoordinator` for atomic writes, detect conflicts via `NSFileVersion`, never auto-merge KiCad files. **Address in:** Track G Phase 190.
- **MLX-Swift Metal Memory Pressure (P1)** — 8GB Macs OOM when loading 4B model. Detect VRAM at startup, dynamic model selection (4B on 16GB+, 2B on 8GB), release context when idle. **Address in:** Track B Phase 165.
- **SwiftData Query Performance (P1)** — Decision Timeline slows to 10+ seconds after millions of events. Add indexes on query predicates, materialize snapshots, paginate, partition events by project, compact old events. **Address in:** Track E Phase 175.
- **CKShare Participant Permission Edge Cases (P2)** — Collaborator edits offline then syncs, permission mismatch fails silently. Check `userRole` before allowing edits, force app reload on permission change, queue offline edits. **Address in:** Track G Phase 192.

## Implications for Roadmap

Based on research, suggested **42-phase roadmap** organized into **8 tracks** (A-H) with clear dependency ordering:

### Track A: Foundation (Phases 161-163)
**Rationale:** Foundation unblocks all other tracks. App shell, daemon bundling, and kicad-cli integration must land first before any UI or governance can be built.

**Delivers:**
- macOS 27+ SwiftUI app shell (Liquid Glass visual language)
- Python daemon bundling (PyInstaller, code-signed, app-spawned subprocess)
- kicad-cli integration (external install requirement to avoid App Store GPL rejection)

**Addresses:** MVP features (inline rendering, basic project management, Python daemon bundled)

**Avoids:** Pitfall 1 (PyInstaller signing), Pitfall 6 (App Store GPL rejection)

**Research flags:** Phase 162 needs App Store review guidelines research — GPL bundling is a well-documented rejection pattern but verify current policy.

### Track B: Models (Phases 164-166)
**Rationale:** Provider abstraction and Keychain storage unblock governance (needs LLM calls) and generative (needs models for SKIDL generation). Task-aware routing requires provider diversity.

**Delivers:**
- LLMProvider protocol (FoundationModels, HFHub, MLX-Swift implementations)
- Provider Router (task-aware, cost-aware, privacy-aware routing)
- BYOK Keychain storage with iCloud sync opt-out default

**Addresses:** MVP features (model selection dropdown, Provider Settings UI)

**Uses:** Swift AI SDK v0.18.2, MLX Swift 0.31.6, FoundationModels (macOS 27+)

**Avoids:** Pitfall 3 (FoundationModels unavailability), Pitfall 7 (MLX-Swift OOM)

**Research flags:** Phase 165 needs MLX-Swift VRAM detection patterns — documented but needs real-device testing on 8GB M1 MacBook Air.

### Track C: Governance (Phases 167-170)
**Rationale:** stdio MCP bridge and Obdurate Runtime unblock UI (needs gates for approval) and memory (needs journal for events). State machine and verification gates enforce app-wide quality.

**Delivers:**
- stdio MCP client (Process, Pipe, JSON-RPC codec)
- Python MCP server (142 ops auto-registered as tools, zero glue)
- Obdurate Runtime (state machine, op journal with fsync, verification gates, escalation ladder)
- Verification Loop (validation_gates.py integration, ERC/DRC enforcement)

**Addresses:** MVP features (MCP stdio daemon, event-sourced memory basic, undo/redo)

**Uses:** MCP Swift SDK, Python mcp 1.28.1, existing ops registry

**Avoids:** Pitfall 2 (stdio buffering deadlock)

**Implements:** Architecture Pattern 1 (stdio MCP Bridge), Pattern 7 (Verification Loop)

**Research flags:** Phase 169 needs stdio buffering stress testing — well-documented pattern but needs 100-RPC stress test.

### Track D: UI Surfaces (Phases 171-175)
**Rationale:** UI unblocks memory (needs timeline visualization) and collaboration (needs approval gates for invites). Thin SwiftUI views depend on SwiftData models from Track E.

**Delivers:**
- Liquid Glass app shell (toolbar, window management, Liquid Glass visual language)
- Inline Rendering (SVG schematic preview, PNG PCB render, live pipeline status)
- GSD Conversation Engine (questioning → spec → roadmap → execute → verify phases)
- Approval Gates UI (human-in-the-loop decisions surfaced)

**Addresses:** MVP features (chat-with-inline-artifacts UI, inline rendering, undo/redo, dark/light mode, basic search)

**Uses:** SwiftUI, QuickLook (SVG), AsyncImage (PNG), FoundationModels for conversation

**Implements:** Architecture Pattern 8 (MCP Auto-Registration) — UI presents 142 tools filtered by category

**Research flags:** Phase 171 needs Liquid Glass visual language specification — new visual language, requires design system definition.

### Track E: Memory (Phases 176-180)
**Rationale:** Event-sourced memory unblocks generative (needs conversation state for generation) and collaboration (needs events for sync). SwiftData + CloudKit is the backbone for cross-device sync.

**Delivers:**
- SwiftData models (Project, Conversation, Message, Decision, ValueChange, ProjectSnapshot)
- CloudKit sync (auto-sync Mac↔iPhone, LWW conflict resolution with prompts)
- Time-Travel (replay events, snapshot materialization, diff visualization, restore)
- Decision Timeline UI (visual timeline, chapter segmentation, filter by type)

**Addresses:** MVP features (event-sourced memory basic, decision timeline UI), should-have features (time-travel, project genealogy)

**Uses:** SwiftData `@Model` macro, CloudKit private DB, `ModelConfiguration.CloudKitDatabase.automatic`

**Avoids:** Pitfall 4 (SwiftData migration loss), Pitfall 8 (query performance)

**Implements:** Architecture Pattern 3 (Event-Sourced Memory), Pattern 4 (SwiftData + CloudKit)

**Research flags:** Phase 173 needs two-device migration testing — critical but risky, requires physical iPhone + Mac.

### Track F: Generative (Phases 181-185)
**Rationale:** Generative transform is the differentiator but depends on v5.0 SKIDL/SPICE work landing first. Hash-based gold master tests ensure correctness.

**Delivers:**
- SKIDL compiler (Conversation → SKIDL IR, depends on v5.0 Track F)
- KiCad generator (SKIDL → .kicad_sch/.kicad_pcb files)
- Pipeline orchestration (full transform pipeline, caching)
- Hash-based gold master tests (fixture hashing, 10-run determinism tests)

**Addresses:** Should-have features (Generative Transform coupling), differentiator (conversation IS source of truth)

**Depends on:** v5.0 Track F (SKIDL integration, SPICE pipeline, training data)

**Uses:** SKIDL compiler (v5.0 work), Provider Router (MLX-Swift for local generation), DaemonMCPClient

**Avoids:** Pitfall 5 (hash instability)

**Implements:** Architecture Pattern 2 (Generative Transform Pipeline)

**Research flags:** Phase 183 is BLOCKED until v5.0 Track F completes — SKIDL/SPICE dependency is hard gate.

### Track G: Collaboration (Phases 186-190)
**Rationale:** Collaboration features require SwiftData models (from Track E) and derived KiCad files (from Track F). CKShare + Group Activities deliver Apple-native collaboration.

**Delivers:**
- Project Genealogy (family tree, branches, snapshots, false starts)
- Group Activities (live sessions, 4-participant cap, event sync NOT files)
- CKShare invitations (permission management: Owner/Editor/Viewer)
- iCloud Drive .kicadagent bundle (atomic bundle writes, conflict resolution)

**Addresses:** Should-have features (CKShare collaboration, project genealogy, routing constraints capture)

**Uses:** CloudKit, CKShare, GroupActivities framework, `NSFileCoordinator` for atomic writes

**Avoids:** Pitfall 6 (iCloud bundle corruption), Pitfall 10 (CKShare permission edge cases)

**Implements:** Architecture Pattern 6 (Group Activities Event Sync)

**Research flags:** Phase 190 needs simultaneous edit testing — Mac + iPhone editing same project, stress test atomic bundle replace.

### Track H: Quality (Phases 191-202)
**Rationale:** Quality runs continuously alongside all tracks. swift-testing, Snapshot tests, SwiftCheck, mutation testing enforce coverage and correctness.

**Delivers:**
- swift-testing framework (unit tests, 100% line+branch coverage)
- Snapshot tests (4 variants: light/dark/XXXL/high-contrast, frozen time fixtures)
- SwiftCheck (property-based testing, state machine invariants)
- mull-xcode (mutation testing, >90% score enforced in CI)
- a11y by default (SwiftLint custom rules, VoiceOver testing)
- CI coverage enforcement (gate on <100% coverage)

**Addresses:** Quality infrastructure, militant testing culture

**Runs in parallel:** All tracks (quality is continuous, not gated)

**Uses:** swift-testing, SnapshotTesting, SwiftCheck, mull-xcode, SwiftLint

**Research flags:** Phase 199 needs snapshot test fixture management — frozen time, 4-variant testing, anti-flake patterns.

### Phase Ordering Rationale

**Dependency-driven ordering:**
1. **Track A (Foundation) first** — App shell and daemon bundling are prerequisites for all other work
2. **Track B (Models) second** — Provider abstraction enables LLM calls in governance and generative
3. **Track C (Governance) third** — stdio MCP bridge enables all Python communication, Obdurate Runtime enforces quality
4. **Track D (UI) fourth** — UI depends on governance for approval gates, needs SwiftData models from Track E
5. **Track E (Memory) fifth** — SwiftData backbone enables generative (conversation state) and collaboration (event sync)
6. **Track F (Generative) sixth** — Depends on v5.0 SKIDL/SPICE work, blocked until v5.0 Track F completes
7. **Track G (Collaboration) seventh** — Needs SwiftData models (E) and derived KiCad files (F) for sharing
8. **Track H (Quality) continuous** — Runs in parallel with all tracks, quality is continuous not gated

**Grouping rationale:**
- **Foundation → Models → Governance** form the core engine (app → LLM → state machine)
- **UI → Memory** form the user experience (views → data)
- **Generative → Collaboration** form the differentiators (compiler model → sharing)

**Pitfall avoidance:**
- Each track has specific pitfall prevention phases (A161 for PyInstaller signing, B163 for FoundationModels availability, etc.)
- Critical P0 pitfalls addressed in early phases (foundation, models, governance)
- P1/P2 pitfalls addressed in later phases (memory, collaboration)

### Research Flags

**Phases requiring deeper research during planning:**
- **Phase 162 (kicad-cli integration):** App Store GPL licensing policy — verify current rejection patterns for bundled GPLv3 tools
- **Phase 163 (FoundationModels):** FoundationModels availability checks on Intel Macs — need availability stub or real device testing
- **Phase 165 (MLX-Swift models):** VRAM detection patterns on 8GB M1 MacBook Air — documented but needs real-device verification
- **Phase 171 (Liquid Glass shell):** Visual language specification — new design system, requires design system definition
- **Phase 173 (SwiftData + CloudKit):** Two-device migration testing — critical but risky, requires physical iPhone + Mac
- **Phase 183 (Generative Transform):** BLOCKED until v5.0 Track F completes — SKIDL/SPICE dependency is hard gate
- **Phase 190 (iCloud Drive bundle):** Simultaneous edit testing — Mac + iPhone editing same project, stress atomic writes
- **Phase 199 (Snapshot tests):** Fixture management patterns — frozen time, 4-variant testing, anti-flake

**Phases with standard patterns (skip research-phase):**
- **Phase 161 (PyInstaller bundling):** Well-documented PyInstaller patterns, code signing is standard Apple tooling
- **Phase 164 (LLMProvider protocol):** Protocol-based abstraction is standard Swift pattern, provider-specific SDKs are documented
- **Phase 167 (stdio MCP client):** MCP stdio transport is specified, JSON-RPC is standard protocol
- **Phase 168 (Python MCP server):** Auto-registration pattern is straightforward, ops registry exists
- **Phase 176 (SwiftData models):** `@Model` macro is standard SwiftData pattern, CloudKit auto-sync is documented
- **Phase 177 (CloudKit sync):** CloudKit private DB is standard, LWW conflict resolution is documented pattern
- **Phase 186 (Project Genealogy):** Graph visualization is standard UI pattern, parent/child relationships are trivial
- **Phase 191 (swift-testing):** swift-testing framework is standard, coverage enforcement is well-documented

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| **Stack** | HIGH | All core technologies verified via official documentation (Apple docs, PyPI, GitHub). FoundationModels availability constraint is well-documented. |
| **Features** | MEDIUM | Table stakes features are industry-standard (chat UI, inline rendering). Differentiators (GSD Conversation Engine, generative transform) are unproven in this domain — higher execution risk. |
| **Architecture** | HIGH | stdio MCP bridge and compiler model are well-researched patterns. Event sourcing and time-travel are established patterns (Martin Fowler). SwiftData + CloudKit integration is documented. |
| **Pitfalls** | HIGH | All 6 P0 pitfalls are documented with clear prevention strategies. PyInstaller signing and FoundationModels availability are well-known failure modes. |
| **Integration** | MEDIUM | Apple-first integration (CloudKit, GroupActivities, CKShare) is documented but complex. stdio MCP buffering is straightforward but needs stress testing. |

**Overall confidence:** HIGH

The stack is proven, architecture patterns are established, pitfalls are well-documented with clear mitigation. Main risks are execution complexity (GSD Conversation Engine, generative transform) and Apple-specific integration (CloudKit migration, Group Activities session management).

### Gaps to Address

**v5.0 Dependency (hard gate):**
- **Gap:** Generative Transform (Track F Phase 183) depends on v5.0 Track F (SKIDL integration, SPICE pipeline, training data). v5.0 work must complete before v6.0 generative can begin.
- **Handle during planning:** Mark Phase 183 as BLOCKED until v5.0 Track F completion. Plan v6.0 phases assuming v5.0 lands on time.

**FoundationModels on Intel Macs:**
- **Gap:** FoundationModels unavailability on Intel Macs is documented but graceful degradation pattern needs validation. MLX-Swift fallback requires HF Hub model download UX.
- **Handle during planning:** Phase 163 (FoundationModels integration) will include availability stub testing. Fallback UX (HF download prompt, progress bar) is MEDIUM complexity.

**CloudKit Schema Migration:**
- **Gap:** SwiftData `VersionedSchema` migration with two-device testing is documented but complex. LWW conflict resolution with prompts needs UX validation.
- **Handle during planning:** Phase 173 (SwiftData + CloudKit) will freeze schema early (v6.0.0), require two-device test (Phone v1.0, Mac v1.1) before complete.

**Group Activities Simulator Limitation:**
- **Gap:** Group Activities framework does not support simulator testing — requires physical devices (Mac + iPhone). Session management and event ordering complexity needs real-device validation.
- **Handle during planning:** Phase 191 (Group Activities) will require physical device testing. Plan for device lab time or remote testing via TestFlight.

**GSD Conversation Engine Complexity:**
- **Gap:** GSD Conversation Engine (visual questioning → spec → roadmap → execute → verify) is HIGH complexity. No reference implementation exists for visual GSD methodology.
- **Handle during planning:** Phase 172 (GSD Conversation Engine) should be deferred to v1.x or v2.0. Validate MVP features first (chat UI, inline rendering) before adding visual methodology.

**KiCad External Install Friction:**
- **Gap:** Requiring external KiCad install (to avoid App Store GPL rejection) adds onboarding friction. Users download app but can't use it without KiCad.
- **Handle during planning:** Phase 162 (kicad-cli integration) will include onboarding UX (helpful install link, auto-detect after install, retry button). Document in App Store review notes.

## Sources

### Primary (HIGH confidence)
- **Apple Developer Documentation** — FoundationModels (macOS 27.0+ requirement), SwiftData (`@Model` macro, CloudKit auto-sync), CloudKit (private DB, CKShare), GroupActivities (4-participant cap), Network framework (`NWBrowser`/`NWListener`)
- **PyInstaller Documentation** — Code signing (`--osx-hardened-runtime`, `--codesign-identity`), dylib signing patterns, entitlements
- **MCP Specification** — stdio transport (JSON-RPC over stdin/stdout, line-delimited messages), tool registration
- **Swift AI SDK Repository** — `/teunlao/swift-ai-sdk`, provider management, BYOK patterns, 37+ provider modules
- **MLX Swift Repository** — `/ml-explore/mlx-swift`, LoRA adapter loading, Metal shaders, HF Hub integration
- **Python Documentation** — subprocess module, stdio buffering (`PYTHONUNBUFFERED=1`, `-u` flag)

### Secondary (MEDIUM confidence)
- **KiCad Documentation** — KiCad 10 file format (S-expression), kicad-cli usage (ERC, DRC, export commands), GPLv3 license
- **SKIDL Documentation** — SKIDL IR patterns, Python → netlist compilation, KiCad file generation
- **Martin Fowler Event Sourcing** — Time-travel patterns, event replay, snapshot materialization
- **Swift Forums** — SwiftData CloudKit migration patterns, `VersionedSchema` explicit migration
- **Apple Developer Forums** — FoundationModels availability checks, CloudKit conflict resolution, GroupActivities session management

### Tertiary (LOW confidence)
- **GitHub Issues / StackOverflow** — PyInstaller code signing corruption failures, stdio buffering deadlock patterns, FoundationModels unavailability on Intel Macs
- **Reddit / HN Threads** — App Store GPL rejection patterns, KiCad bundling in commercial apps
- **WebSearch results (failed queries)** — SwiftUI conversation view patterns, Xcode git time travel, iOS 18 collaborative editing (529 errors, needs validation)

**Research completed:** 2026-07-07
**Ready for roadmap:** Yes
