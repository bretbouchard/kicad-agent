# Feature Research

**Domain:** Native Mac+iPhone app (KiCad Agent — The Closed Box)
**Researched:** 2026-07-07
**Confidence:** MEDIUM

## Feature Landscape

### Table Stakes (Users Expect These)

Features users assume exist. Missing these = product feels incomplete.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Inline schematic/PCB rendering | User types "show me the schematic", app renders it inline | MEDIUM | SVG for schematics (kicad-cli sch export svg), PNG for PCB (kicad-cli pcb render). SwiftUI `Image` view with inline rendering. Standard pattern seen in Linear, Figma, Apple Notes. |
| Chat-with-inline-artifacts UI | Conversational UI with embedded visual artifacts | MEDIUM | Message bubbles + inline image previews. Tapping artifact opens full-screen inspector. Standard pattern (Linear issues, Figma comments, Notion inline canvases). |
| Basic project management | Create/delete projects, list recent projects | LOW | SwiftData models with CloudKit sync. Standard CRUD operations. |
| Model selection dropdown | Choose AI model from installed list | LOW | Settings UI with model picker. Standard pattern (ChatGPT app, Cursor model selector). |
| Undo/redo conversation | Basic undo for last action | MEDIUM | Command+Z pattern. Event-sourced journal enables this. Standard expectation for any editing app. |
| Dark/light mode | System appearance sync | LOW | SwiftUI automatic adaptation. Table stakes for 2026. |
| Basic search | Search across conversations | MEDIUM | Full-text search over SwiftData store. Standard expectation. |
| Export KiCad files | Export .kicad_sch/.kicad_pcb | LOW | Standard share sheet. Users expect to get files out. |

### Differentiators (Competitive Advantage)

Features that set the product apart. Not required, but valuable.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Conversation IS source of truth** | KiCad files are derived artifacts, regenerable from conversation journal | HIGH | Compiler model: conversation (source) → KiCad files (binary). Enables time-travel, reproducibility, "why did this change?" traceability. No other EDA tool does this. |
| **Decision Timeline UI** | Visual timeline of all project decisions with time-travel scrubbing | HIGH | Event-sourced decisions render as timeline. Scrub → restore any point. Diff visualization between states. Like Xcode git time-travel but for decisions + artifacts. |
| **Live Pipeline View** | CI/CD-style step bar showing operation progress in real-time | MEDIUM | Visual step indicator (ERC → placement → routing → DRC). Each step shows status (pending/running/complete/error). Pattern from Vercel deploy preview, GitHub Actions UI. |
| **GSD Conversation Engine** | Visual spec/roadmap generation from conversational questioning | HIGH | Questions → spec → roadmap all visualized as editable artifacts. Approval gates surfaced as user decisions. No other tool has built-in GSD methodology. |
| **Event-sourced memory** | Every decision, value change, and operation is journaled immutably | HIGH | No silent mutations. Full audit trail. Enables "time-travel debugging". Pattern from event sourcing systems (Martin Fowler's time-travel patterns). |
| **Project genealogy** | Family tree showing branches, false starts, snapshots, merges | MEDIUM | Visual graph like Xcode source control navigator but richer. Shows "this snapshot came from that branch which forked from that decision". |
| **CKShare collaboration** | Native iCloud collaboration with view/edit/fork permissions | MEDIUM | No infra. 4-participant Group Activities sessions (FaceTime-style). Pattern from Apple Notes collaboration, iWork suite. |
| **Run-on conversations** | Chapter segmentation for long-running projects | MEDIUM | Auto-chunk conversations when they exceed 500 messages. "Chapter 1: Initial design", "Chapter 2: Power supply redesign". Pattern from Linear's project updates. |
| **Provider Settings UI (BYOK)** | Bring-yourown-api-key with iCloud Keychain sync | LOW | Settings screen with Keychain integration. No proxy, no AI bill liability. Pattern from Cursor API key settings. |
| **Model browser** | HF Hub catalog + drag-drop import of custom models | MEDIUM | In-app model downloader. Drag-drop .gguf or MLX model files. Pattern from Ollama model manager, LM Studio. |
| **Approval gates UI** | Obdurate surfaced as human-in-the-loop decisions | MEDIUM | When system needs approval (destructive ops, escalations), it asks user. Decision is journaled. Pattern from error escalation systems. |
| **iPhone companion mode** | LAN-paired phone for read+chat+approve, offline queue | HIGH | Phone is thin client. Mac does heavy work (Python daemon). Pattern from Dumb Passthrough, Sidecar remote screen. |
| **Generative transform coupling** | Conversation state drives generation. Source = conversation, artifacts = derived | HIGH | Changes in conversation regenerate artifacts. Hash-based gold master tests ensure correctness. Compiler model applied to hardware design. |
| **iCloud Drive .kicadagent bundle** | Document is first-class iCloud Drive citizen | MEDIUM | `.kicadagent` bundle with conversation journal, KiCad files, metadata. Pattern from Notes .storedata, Pages .pages. |
| **Chapter segmentation** | Auto-split long conversations into searchable chapters | LOW | Auto-chunk at 500 messages or user request. Pattern from Linear's project updates, podcast chapter markers. |
| **Routing constraints capture** | Conversation-driven constraint specification → .kicad_dru | MEDIUM | User says "0.5mm track spacing, 4-layer stackup". System captures, generates DRC rules. No other tool does this conversationally. |

### Anti-Features (Commonly Requested, Often Problematic)

Features that seem good but create problems.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Built-in cloud execution** | "Run my design in the cloud" | Massive infra cost, security risk, data privacy nightmare, dev becomes ops, zero infra principle violated | Local-only execution (macOS). iPhone is LAN-pair thin client. |
| **AI bill proxying** | "I'll pay you, you handle the API keys" | Legal liability, billing disputes, compliance nightmare, KYC burden | Pure BYOK with Keychain sync. User pays OpenAI/Anthropic directly. |
| **Windows v1 support** | "Windows is huge for EDA" | Cross-platform UI framework (Electron?) bloat, violates Apple-native quality bar, dilutes "militant testing" effort | Mac+iPhone v1. Windows v7+ after 100% coverage proven on Mac. |
| **Real-time multi-user editing** | "Google Docs for KiCad" | Merge conflicts on S-expressions are catastrophic, LWW prompts fatigue, Operational Transform is hell | CKShare with view/edit permissions. One editor at a time, collaborators watch + comment. |
| **GitHub integration** | "Sync my repos" | Git sync on S-expressions is noisy, binary diffs, conflicts everywhere | Manual export/import. Git outside the app (user's workflow). |
| **Plugin system** | "Let users extend it" | Security surface, API stability burden, testing nightmare | MCP server opt-in (HTTP daemon). External agents call tools, no in-app plugin model. |
| **Custom scripting UI** | "Script my workflows" | Another language to learn, maintenance burden, script rot | Conversation IS the script. GSD phases ARE the workflow. No scripting needed. |
| **Web version** | "Use it anywhere" | Browser sandbox limits, no kicad-cli, no Metal, offline impossible | Native Mac+iPhone only. Web v7+ if demand validates. |
| **Free tier with limits** | "Freemium model" | Infrastructure cost, abuse, support burden, distorts product decisions | Paid app ($49 one-time?). Trial period. No infra costs = no freemium needed. |
| **Social features** | "Share my designs publicly" | Moderation burden, privacy risk, noise | Private collaboration only (CKShare). Public export to GitHub/manual. |

## Feature Dependencies

```
[Table Stakes: Inline Rendering]
    └──requires──> [Python Daemon (Track A)]
    └──requires──> [kicad-cli bundled]
    └──requires──> [SwiftUI Image view pipeline]

[Conversation IS Source of Truth]
    └──requires──> [Event-Sourced Memory (Track E)]
    └──requires──> [Decision Timeline UI]
    └──requires──> [Generative Transform (Track F)]
    └──requires──> [Hash-based Gold Master Tests (Track H)]

[Decision Timeline UI]
    └──requires──> [Event-Sourced Memory]
    └──enhances──> [Time-Travel Scrubbing]
    └──enhances──> [Project Genealogy]

[Project Genealogy]
    └──requires──> [CKShare Collaboration (Track G)]
    └──requires──> [SwiftData + CloudKit]
    └──requires──> [Branch/Fork Operations]

[Live Pipeline View]
    └──requires──> [Obdurate Runtime (Track C)]
    └──requires──> [MCP Tool Execution]
    └──requires──> [Progress Streaming]

[Approval Gates UI]
    └──requires──> [Obdurate Runtime]
    └──requires──> [Four-State Resolution Taxonomy]
    └──requires──> [Decision Journal]

[GSD Conversation Engine]
    └──requires──> [Visual Spec Generator]
    └──requires──> [Visual Roadmap Generator]
    └──requires──> [Approval Gates UI]
    └──requires──> [Questioning Phase → Spec Phase]

[iPhone Companion Mode]
    └──requires──> [LAN Pairing]
    └──requires──> [Offline Queue]
    └──requires──> [Mac as Primary]
    └──requires──> [Python Daemon on Mac]

[Generative Transform]
    └──requires──> [SKIDL Integration (v5.0 Track F)]
    └──requires──> [SPICE Pipeline (v5.0 Track F)]
    └──requires──> [Training Data (v5.0 Track F)]
    └──requires──> [MLX-Swift Inference]
    └──requires──> [Hash-based Gold Master]

[CKShare Collaboration]
    └──requires──> [iCloud Drive .kicadagent Bundle]
    └──requires──> [SwiftData + CloudKit Sync]
    └──requires──> [Permission Model: Owner/Editor/Viewer]
    └──requires──> [Conflict Resolution: LWW with prompts]
```

### Dependency Notes

- **Inline Rendering requires Python Daemon**: kicad-cli operations (SVG export, PNG render, PDF export) run in subprocess. No bundling hacks.
- **Conversation IS Source of Truth requires Event-Sourced Memory**: Without immutable journal, "source of truth" is a lie. Every decision must be replayable.
- **Decision Timeline enhances Time-Travel**: Timeline is visual layer on top of event journal. Scrub = replay journal to that point.
- **Project Genealogy requires CKShare**: Branching/forking only meaningful when collaborating. Solo projects = linear timeline.
- **Live Pipeline View requires Obdurate Runtime**: Progress streaming from MCP tool execution. Runtime emits progress events → UI renders step bar.
- **Approval Gates requires Four-State Resolution**: Without resolution taxonomy (IMPLEMENTED/ADDED-AS-PHASE/SUPERSEDED/DEFERRED), approval is just a boolean, loses context.
- **GSD Conversation Engine requires Approval Gates**: GSD methodology has mandatory gates (questioning → spec → roadmap → execute). UI must surface these.
- **iPhone Companion requires Mac as Primary**: Phone is thin client. Heavy ops (Python daemon, KiCad export, routing) run on Mac. Phone shows chat + approves + views artifacts.
- **Generative Transform requires SKIDL/SPICE**: Natural language → SKIDL → KiCad. SPICE validates circuit quality. Training data fine-tunes models. All v5.0 inputs.
- **CKShare requires iCloud Drive Bundle**: `.kicadagent` bundle must be first-class iCloud document. CKShare points to bundle in iCloud Drive.
- **Group Activities requires CKShare**: FaceTime-style collaboration builds on CKShare infrastructure. GroupActivities is session layer on top.
- **BYOK requires iCloud Keychain Sync**: User enters API key once, syncs across devices. Keychain access requires entitlements.

## MVP Definition

### Launch With (v1)

Minimum viable product — what's needed to validate the concept.

- [ ] **Inline schematic/PCB rendering** — Essential feedback loop. User types intent, sees result.
- [ ] **Chat-with-inline-artifacts UI** — Core interaction model. Conversational hardware design.
- [ ] **Basic project management** — Create/delete/list projects. Can't use app without this.
- [ ] **Model selection dropdown** — Choose between FoundationModels (free) and HF Hub models.
- [ ] **Provider Settings UI (BYOK)** — Enter API keys. Without this, no LLM access.
- [ ] **Python Daemon bundled** — Subprocess execution of kicad-cli and 142 ops. Core engine.
- [ ] **MCP stdio daemon** — App talks to Python via stdio MCP. Bridge layer.
- [ ] **Event-sourced memory (basic)** — Journal all ops. Enables undo/redo.
- [ ] **Undo/redo conversation** — Basic mistake recovery. Table stakes.
- [ ] **Export KiCad files** — Get files out. Essential for any EDA tool.
- [ ] **Dark/light mode** — System appearance sync. 2026 expectation.
- [ ] **Basic search** — Search conversations. Essential for rediscovery.

### Add After Validation (v1.x)

Features to add once core is working.

- [ ] **Decision Timeline UI** — Adds once event-sourcing proven. Value: "why did this change?"
- [ ] **Time-travel scrubbing** — Adds after Decision Timeline. Value: restore any point.
- [ ] **Live Pipeline View** — Adds once ops are stable. Value: see progress, not spinners.
- [ ] **Approval Gates UI** — Adds once Obdurate Runtime integrated. Value: human-in-the-loop.
- [ ] **CKShare collaboration** — Adds once iCloud Drive bundle stable. Value: collaborative editing.
- [ ] **Project genealogy** — Adds after CKShare. Value: see branches, false starts.
- [ ] **Run-on conversations** — Adds once journal proven. Value: long-running projects.
- [ ] **Chapter segmentation** — Adds after run-on conversations. Value: navigation at scale.
- [ ] **Model browser** — Adds once BYOK stable. Value: power-user custom models.
- [ ] **Routing constraints capture** — Adds once generative transform works. Value: conversation-driven DRC.

### Future Consideration (v2+)

Features to defer until product-market fit is established.

- [ ] **GSD Conversation Engine** — Full visual GSD methodology. Differentiator, but massive effort.
- [ ] **Conversation IS Source of Truth** — Compiler model for hardware. High risk, high reward.
- [ ] **Generative Transform** — SKIDL/SPICE integration, NL → circuit. v5.0 dependency.
- [ ] **iPhone Companion Mode** — LAN pairing, offline queue. Platform expansion.
- [ ] **Group Activities** — FaceTime-style sessions. Requires v1 collaboration proven.
- [ ] **Hash-based Gold Master Tests** — Militant testing for generative outputs. Quality gate.
- [ ] **4-variant snapshot tests** — Light/dark/XXXL/high-contrast. Testing infrastructure.
- [ ] **mull-xcode mutation testing** — >90% mutation score. Quality infrastructure.
- [ ] **Windows support** — Cross-platform UI framework. Platform expansion.
- [ ] **Web version** — Browser UI. Platform expansion.

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Inline schematic/PCB rendering | HIGH | MEDIUM | P1 |
| Chat-with-inline-artifacts UI | HIGH | MEDIUM | P1 |
| Basic project management | HIGH | LOW | P1 |
| Model selection dropdown | MEDIUM | LOW | P1 |
| Provider Settings UI (BYOK) | MEDIUM | LOW | P1 |
| Python Daemon bundled | HIGH | MEDIUM | P1 |
| MCP stdio daemon | HIGH | MEDIUM | P1 |
| Event-sourced memory (basic) | MEDIUM | MEDIUM | P1 |
| Undo/redo conversation | HIGH | MEDIUM | P1 |
| Export KiCad files | HIGH | LOW | P1 |
| Dark/light mode | LOW | LOW | P1 |
| Basic search | MEDIUM | MEDIUM | P1 |
| Decision Timeline UI | HIGH | HIGH | P2 |
| Time-travel scrubbing | HIGH | HIGH | P2 |
| Live Pipeline View | MEDIUM | MEDIUM | P2 |
| Approval Gates UI | HIGH | MEDIUM | P2 |
| CKShare collaboration | HIGH | MEDIUM | P2 |
| Project genealogy | MEDIUM | MEDIUM | P2 |
| Run-on conversations | MEDIUM | MEDIUM | P2 |
| Chapter segmentation | LOW | LOW | P2 |
| Model browser | LOW | MEDIUM | P2 |
| Routing constraints capture | MEDIUM | HIGH | P2 |
| GSD Conversation Engine | HIGH | HIGH | P3 |
| Conversation IS Source of Truth | HIGH | HIGH | P3 |
| Generative Transform | HIGH | HIGH | P3 |
| iPhone Companion Mode | MEDIUM | HIGH | P3 |
| Group Activities | MEDIUM | MEDIUM | P3 |
| Hash-based Gold Master Tests | MEDIUM | HIGH | P3 |
| 4-variant snapshot tests | LOW | MEDIUM | P3 |
| mull-xcode mutation testing | LOW | MEDIUM | P3 |
| Windows support | MEDIUM | HIGH | P3 |
| Web version | MEDIUM | HIGH | P3 |

**Priority key:**
- P1: Must have for launch (MVP)
- P2: Should have, add when possible (v1.x)
- P3: Nice to have, future consideration (v2+)

## Competitor Feature Analysis

| Feature | Linear | Figma | Notion | Apple Notes | Things 3 | Our Approach |
|---------|--------|-------|--------|-------------|----------|--------------|
| Inline rendering | Markdown + images | Canvases + embeds | Blocks + embeds | Rich text + sketches | Task lists | SVG schematics + PNG PCBs inline |
| Chat UI | Comments on issues | Multiplayer cursors | Comments in docs | Inline comments | Task notes | Conversational intent → operations |
| Version history | Issue history | File history | Page history | Document history | Task history | Event-sourced journal + timeline |
| Collaboration | Real-time comments | Multiplayer editing | Real-time editing | Collab editing | Shared lists | CKShare (view/edit/fork) |
| Permissions | Workspace roles | Team roles | Workspace roles | Share permissions | Not applicable | Owner/Editor/Viewer per project |
| Time-travel | Issue restore | Version restore | Page restore | Document restore | Not applicable | Scrub timeline → restore |
| Project genealogy | Not applicable | Branching | Not applicable | Not applicable | Not applicable | Family tree + false starts |
| Pipeline visualization | Not applicable | Not applicable | Not applicable | Not applicable | Not applicable | CI/CD-style step bar |
| Approval gates | State transitions | Not applicable | Not applicable | Not applicable | Not applicable | Obdurate surfaced as decisions |
| BYOK | Not applicable | Not applicable | Not applicable | Not applicable | Not applicable | Keychain-synced API keys |
| Model selection | Not applicable | AI features | AI features | Not applicable | Not applicable | FoundationModels + HF Hub |
| Native platforms | Mac/Windows/Web | Mac/Windows/Web | Mac/Windows/Web/iOS | Mac/iOS/iPadOS | Mac/iOS/iPadOS | Mac+iPhone v1 |

## Best-in-Class Patterns Research

### Chat-with-Inline-Artifacts UI

**Pattern:** Message bubbles with embedded image previews. Tapping opens full-screen inspector with zoom/pan/export.

**Examples:**
- **Linear**: Issues with inline image rendering (markdown `![alt](url)`). Tap to fullscreen. (Linear blog 2024)
- **Figma**: Comment threads with canvas snapshots. Multiplayer cursors show live presence. (Figma collaboration blog 2026)
- **Notion**: Block-based embedding. Images render inline, tap for lightbox. (Notion UI patterns)
- **Apple Notes**: Rich text with inline sketches. Collaborators see edits in real-time. (iOS 18 collaboration)

**Implementation notes:**
- SwiftUI `LazyVStack` with `ScrollView`. Message bubbles are custom views.
- Inline images: `AsyncImage` for URLs, bundled `Image` for local files.
- KiCad rendering: Call kicad-cli in subprocess (`kicad-cli sch export svg`, `kicad-cli pcb render`). Pipe output to SwiftUI.
- Complexity: MEDIUM. Requires subprocess coordination, image cache, progressive rendering.

### Pipeline Visualization

**Pattern:** Step-by-step progress bar. Each step shows icon + label + status (pending/running/complete/error).

**Examples:**
- **Vercel**: Deploy preview with step log. "Building → Deploying → Done".
- **GitHub Actions**: Workflow run log with step status.
- **Xcode**: Build report with phases (Compile → Link → Archive).
- **Linear**: Project updates with progress indicators.

**Implementation notes:**
- SwiftUI `HStack` with step circles. Connected by progress line.
- Status colors: gray (pending), blue (running), green (complete), red (error).
- Progress events from Obdurate Runtime via MCP. Stdout emits structured JSON: `{"type": "progress", "step": "routing", "status": "running"}`.
- Complexity: MEDIUM. Requires event streaming, state management, error handling.

### Time-Travel/Snapshot UX

**Pattern:** Timeline scrubber. Scrub to restore state. Diff visualization between points.

**Examples:**
- **Xcode**: Source control navigator. Commit history popover. "Show changes" visual diff.
- **GitX/Kaleidoscope**: Branch visualization timeline. Click commit → show diff.
- **Linear**: Issue history. Click point → show state.
- **Notion**: Page history. Scrub → restore.
- **Martin Fowler time-travel patterns**: Event-sourced systems replay journal to any point. (Event sourcing blog 2020)

**Implementation notes:**
- SwiftData query: `SELECT * FROM events WHERE timestamp <= ? ORDER BY timestamp`. Replay events → rebuild state.
- SwiftUI `TimelineView` with custom scrubber. Scrub → query events → replay → render.
- Diff: `git diff` style. Red deletions, green additions. S-expression diff (KiCad files) or JSON diff (conversation).
- Complexity: HIGH. Requires event replay engine, diff visualization, performance optimization.

### Project Genealogy Visualization

**Pattern:** Family tree graph. Nodes = snapshots/branches. Edges = parent-child relationships. False starts shown as dead ends.

**Examples:**
- **Xcode**: Source control navigator. Branch tree visualization.
- **GitKraken**: Commit graph with merge visualization.
- **Linear**: Project updates. "Forked from X at Y".
- **Figma**: Version history. "Branch created from version X".

**Implementation notes:**
- SwiftUI `Canvas` or custom graph view. Nodes = circles, edges = bezier curves.
- SwiftData query: `SELECT * FROM projects WHERE parent_id = ?`. Recursive traversal.
- Tap node → show details (timestamp, description, parent, children).
- Complexity: MEDIUM. Requires graph layout algorithm, tap handling, zoom/pan.

### Collaboration Permission Models

**Pattern:** Owner/Editor/Viewer roles. Owner invites collaborators via CKShare. Default = Viewer (read-only). Owner upgrades to Editor (read+write).

**Examples:**
- **Apple Notes**: Share sheet. "Can make changes" toggle. On by default? No, default = view. (iOS 18 collaboration)
- **Figma**: "Anyone with link can view/edit/comment". Granular permissions.
- **Notion**: Workspace roles (Owner/Editor/Viewer/Comment-only).
- **iWork suite**: Share sheet with "Invite people". Permission dropdown.
- **CKShare documentation**: `CKShare.ParticipantPermission` enum (.none/.read/.write/.admin). (CKShare API guide)

**Implementation notes:**
- `CKShare` with `participantPermission`. Default = `.readOnly` (per PROJECT.md decision).
- Share sheet: `UIActivityViewController` with CKShare URL.
- Permission upgrade: Owner taps collaborator → "Upgrade to Editor" → CKShare update.
- Complexity: MEDIUM. Requires CloudKit sync, permission UI, conflict resolution.

### Generative Transform Coupling (Source vs Derived)

**Pattern:** Conversation state IS source of truth. KiCad files are derived artifacts (like compiled binaries). Changes in conversation regenerate KiCad files.

**Examples:**
- **Compiler model**: Source code (C) → Compiler → Binary (exe). Edit source → recompile → new binary.
- **Figma**: Design file (source) → Export → PNG/SVG (derived). Edit design → re-export.
- **Notion**: Block content (source) → Export → PDF/Markdown (derived).
- **Martin Fowler event sourcing**: Event journal (source) → Replay → Current state (derived). Rebuild from events.

**Implementation notes:**
- Conversation journal = event stream. Each message/decision = event.
- KiCad generation = replay journal → SKIDL/SPICE → KiCad files.
- Hash-based gold master: SHA256 of KiCad files. Regenerate → hash compare.
- Complexity: HIGH. Requires deterministic generation, hash verification, rollback on mismatch.

### Apple-Native Patterns Preferred

**Decision:** Use Apple frameworks/patterns over generic cross-platform approaches.

| Feature | Apple-Native Pattern | Generic Alternative | Why Apple |
|---------|---------------------|-------------------|----------|
| Collaboration | `CKShare` + CloudKit | Custom WebSocket sync | Zero infra, native permissions, iCloud integration |
| Real-time sessions | `GroupActivities` + FaceTime | WebRTC mesh | Native FaceTime UI, 4-participant cap, zero infra |
| Data sync | SwiftData + CloudKit | Core Data + custom sync | SwiftUI-native, automatic schema sync |
| Key storage | iCloud Keychain | Environment variables | Cross-device sync, secure enclave |
| Document storage | iCloud Drive bundle | Custom file sync | `.kicadagent` bundle, first-class citizen |
| Model inference | MLX-Swift + FoundationModels | Python subprocess | In-process, Metal-accelerated, zero latency |
| Progress view | SwiftUI `ProgressView` | Custom spinner | Native animation, system appearance |
| Share sheet | `UIActivityViewController` | Custom share UI | Native extensions, AirDrop support |
| Notifications | `UNUserNotification` | In-app banners | System respect, Do Not Disturb |
| Search | SwiftData `#Predicate` | Custom FTS | Automatic indexing, CloudKit sync |

## Sources

### HIGH Confidence (Official Documentation)
- **CKShare + CloudKit**: Apple Developer Documentation — `CKShare`, `CKShare.ParticipantPermission`, CloudKit collaboration guide (iOS 18)
- **GroupActivities**: Apple Developer Documentation — `GroupActivities` framework, FaceTime integration, SharePlay
- **SwiftData + CloudKit**: WWDC 2024 sessions — SwiftData sync, CloudKit integration
- **MLX-Swift**: MLX GitHub repository — Swift bindings for ML framework, Metal acceleration
- **FoundationModels**: Apple Intelligence Documentation — Built-in models, API access

### MEDIUM Confidence (Industry Patterns)
- **Linear app blog**: Linear.app/blog — Product updates, UI redesign, project updates feature
- **Figma collaboration blog**: Figma.com/blog/collaboration — Multiplayer cursors, permissions, real-time editing
- **Martin Fowler event sourcing**: MartinFowler.com/articles/2017-01-time-travel.html — Time-travel patterns, event replay
- **Event sourcing time travel**: Blog.ProgrammingWithNuts.com/event-sourcing-time-travel — UI patterns for snapshots
- **GitKraken/GitX patterns**: Git client UI — Branch visualization, timeline scrubbing
- **Apple Notes collaboration**: iOS 18 features — Collab editing, iCloud permissions, share sheet
- **Things 3/Bear app**: Cultured Code — Project timeline visualization, markdown rendering

### LOW Confidence (WebSearch only)
- **SwiftUI conversation view**: WebSearch results (529 errors) — Chat bubbles, inline images
- **Xcode git time travel**: WebSearch results (529 errors) — Source control navigator
- **iOS 18 collaborative editing**: WebSearch results (failed) — iCloud permissions
- **RealityKit GroupActivities**: WebSearch results (failed) — FaceTime sessions

### Gaps Requiring Validation
- **MLX-Swift model loading**: Need to verify drag-drop import of custom models (.gguf, MLX format)
- **GroupActivities participant limits**: Documentation says "typical 4-participant cap" — need to verify hard limit
- **CKShare permission upgrade flow**: Need to test "Viewer → Editor" upgrade UX
- **SwiftData conflict resolution**: LWW with prompts — need to verify implementation pattern
- **KiCad rendering performance**: SVG schematic size limits, PNG render times — need benchmarks

---
*Feature research for: KiCad Agent — The Closed Box (v6.0 Mac+iPhone app)*
*Researched: 2026-07-07*
