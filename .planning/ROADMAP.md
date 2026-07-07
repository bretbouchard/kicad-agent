# ROADMAP — v6.0 KiCad Agent: The Closed Box

**Milestone:** v6.0 KiCad Agent — The Closed Box
**Target Phases:** 161-202 (42 phases)
**Status:** Roadmap defined, ready for phase planning

## Phases

- [ ] **Phase 161: App Shell Foundation** — macOS 27+ SwiftUI app with Liquid Glass visual language
- [ ] **Phase 162: Python Daemon Bundling** — PyInstaller binary, code-signed, app-spawned subprocess
- [ ] **Phase 163: KiCad CLI Integration** — External kicad-cli detection, App Store GPL compliance
- [ ] **Phase 164: LLM Provider Protocol** — FoundationModels, HF Hub, MLX-Swift abstraction
- [ ] **Phase 165: Provider Router** — Task-aware, cost-aware, privacy-aware model routing
- [ ] **Phase 166: BYOK Keychain Storage** — API key management with iCloud sync opt-out default
- [ ] **Phase 167: stdio MCP Client** — Swift subprocess communication with Python daemon
- [ ] **Phase 168: Python MCP Server** — Auto-register 142 ops as MCP tools, zero glue
- [ ] **Phase 169: Obdurate Runtime** — State machine, op journal, verification gates, escalation ladder
- [ ] **Phase 170: Verification Loop Integration** — Python validation_gates.py wrapped for Swift
- [ ] **Phase 171: Liquid Glass UI Shell** — Toolbar, window management, visual language system
- [ ] **Phase 172: Inline Rendering** — SVG schematic preview, PNG PCB renders, live pipeline view
- [ ] **Phase 173: GSD Conversation Engine** — Visual questioning → spec → roadmap → execute → verify
- [ ] **Phase 174: Approval Gates UI** — Human-in-the-loop decision prompts with context
- [ ] **Phase 175: Chat Interface** — Conversational UI with message streaming, image attachments
- [ ] **Phase 176: SwiftData Models** — Project, Conversation, Message, Decision, ValueChange, Snapshot
- [ ] **Phase 177: CloudKit Sync** — Automatic Mac↔iPhone sync, LWW conflict resolution with prompts
- [ ] **Phase 178: Time-Travel Engine** — Event replay, snapshot materialization, diff visualization
- [ ] **Phase 179: Decision Timeline UI** — Visual timeline with chapter segmentation, filters
- [ ] **Phase 180: Event Sourcing** — Complete append-only journal, query optimization, event compaction
- [ ] **Phase 181: SKIDL Compiler** — Conversation state → SKIDL IR (depends on v5.0 Track F)
- [ ] **Phase 182: KiCad Generator** — SKIDL → .kicad_sch/.kicad_pcb files with validation gates
- [ ] **Phase 183: Generative Pipeline** — Full transform orchestration with caching and hash verification
- [ ] **Phase 184: Hash Gold Master Tests** — Deterministic generation verification, 10-run tests
- [ ] **Phase 185: Generative Correctness** — SPICE validation, ERC/DRC enforcement, escalation on failure
- [ ] **Phase 186: Project Genealogy** — Family tree, branches, false starts, snapshot relationships
- [ ] **Phase 187: Group Activities v1** — Live sessions, 4-participant cap, event sync (not files)
- [ ] **Phase 188: CKShare Invitations** — Collaborator invitations with permission management
- [ ] **Phase 189: Collaboration UI** — Activity feed, participant status, permission badges
- [ ] **Phase 190: iCloud Drive Bundle** — .kicadagent document type, atomic writes, conflict resolution
- [ ] **Phase 191: swift-testing Framework** — Unit tests with 100% line+branch coverage enforcement
- [ ] **Phase 192: Snapshot Testing** — 4-variant tests (light/dark/XXXL/high-contrast), frozen time fixtures
- [ ] **Phase 193: Property-Based Testing** — SwiftCheck for invariants, fuzz testing
- [ ] **Phase 194: Mutation Testing** — mull-xcode, >90% score enforced in CI
- [ ] **Phase 195: Accessibility Testing** — VoiceOver, Dynamic Type XXXL, keyboard-only flows
- [ ] **Phase 196: UI Automation** — XCUITest for primary flows, approval gates, time-travel
- [ ] **Phase 197: Performance Testing** — Latency, memory, regression detection
- [ ] **Phase 198: Concurrency Testing** — ThreadSanitizer, no data races allowed
- [ ] **Phase 199: Python Daemon Testing** — pytest, 100% coverage, mutation testing on daemon
- [ ] **Phase 200: CI Coverage Gates** — Build fails if <100% coverage, automated quality enforcement
- [ ] **Phase 201: A11y by Default** — SwiftLint custom rules, a11y audit in CI, block PR if violations
- [ ] **Phase 202: iPhone Companion** — LAN pairing, offline queue, cost tracking, read-only mode
- [ ] **Phase 203: Build & Ship Automation (Fastlane)** — Fastlane lanes for build/test/sign/ship, match code signing, pilot TestFlight, deliver App Store, snapshot screenshots, build_daemon lane for PyInstaller

## Phase Details

### Phase 161: App Shell Foundation

**Goal:** User can launch a native macOS 27+ SwiftUI app with Liquid Glass visual language within 2 seconds

**Depends on:** Nothing (first phase)

**Requirements:** APP-01, APP-02, APP-06, APP-07

**Success Criteria** (what must be TRUE):
1. User can double-click KiCadAgent.app and see the Liquid Glass chat interface within 2 seconds
2. User can open multiple projects in separate windows (CMD+N)
3. App respects system appearance (dark/light mode) and Dynamic Type scaling
4. App installs from Mac App Store without warnings or sandbox violations

**Plans:** 1 plan

**UI hint:** yes

---

### Phase 162: Python Daemon Bundling

**Goal:** App bundles Python daemon (PyInstaller binary) and spawns it as subprocess on launch

**Depends on:** Phase 161

**Requirements:** APP-03, APP-05, DAEM-01, DAEM-05, DAEM-06

**Success Criteria** (what must be TRUE):
1. App spawns bundled Python daemon on launch (subprocess, no LaunchAgent)
2. Daemon survives app sleep/wake cycles (no restart needed)
3. Daemon crashes trigger automatic restart with audit-log entry
4. App gracefully shuts down daemon on quit (no orphan processes)
5. PyInstaller dylibs are code-signed and pass clean-machine test (Pitfall 1 prevention)

**Plans:** 1 plan

---

### Phase 163: KiCad CLI Integration

**Goal:** App detects external KiCad install and guides user to KiCad 10+ (GPL compliance)

**Depends on:** Phase 162

**Requirements:** APP-04, DAEM-07, DAEM-08

**Success Criteria** (what must be TRUE):
1. App detects missing KiCad install on first launch and shows helpful install prompt
2. App auto-detects KiCad after install via `which kicad-cli`
3. App Store submission passes with external kicad-cli requirement (Pitfall 9 prevention)
4. Review notes document KiCad 10+ external install requirement
5. User can opt-in to external HTTP MCP server with auth token (default off)

**Plans:** 1 plan

---

### Phase 164: LLM Provider Protocol

**Goal:** App uses KiCadModelProvider protocol as only model interface (SDK types don't leak)

**Depends on:** Phase 161

**Requirements:** MOD-01, MOD-06, MOD-07

**Success Criteria** (what must be TRUE):
1. FoundationModels is always available as default (free, on-device, no key required)
2. App gracefully degrades to MLX-Swift + HF download on Intel Macs (Pitfall 3 prevention)
3. User can browse MLX models from Hugging Face Hub catalog (zero dev infra)
4. User can drag-drop .mlx model files to import custom fine-tunes
5. FoundationModels availability check runs at app launch (not device model detection)

**Plans:** 1 plan

---

### Phase 165: Provider Router

**Goal:** App routes model calls based on task (privacy, cost, capability awareness)

**Depends on:** Phase 164

**Requirements:** MOD-02, MOD-10, MOD-11, MOD-12

**Success Criteria** (what must be TRUE):
1. Router selects FoundationModels for analysis tasks (free, built-in)
2. Router selects MLX-Swift for circuit generation (local, cost $0)
3. Router selects cloud provider only when user has API keys configured
4. App shows token usage and cost estimate per assistant message
5. Router falls back to FoundationModels when user lacks cloud API keys

**Plans:** 1 plan

---

### Phase 166: BYOK Keychain Storage

**Goal:** App stores API keys in Keychain with iCloud sync (opt-out default, zero dev liability)

**Depends on:** Phase 165

**Requirements:** MOD-03, MOD-04, MOD-05

**Success Criteria** (what must be TRUE):
1. User can configure API keys for Anthropic, OpenAI, Google, Groq, xAI, Together via Settings UI
2. API keys stored in device-local Keychain by default
3. iCloud Keychain sync is opt-out (user must explicitly disable, warned on disable)
4. App never proxies API calls (pure BYOK, developer has zero AI cost liability)
5. Keychain sync disabled shows warning: "You'll lose keys on device swap"

**Plans:** 1 plan

---

### Phase 167: stdio MCP Client

**Goal:** Swift app communicates with Python daemon via stdio MCP (JSON-RPC, no HTTP by default)

**Depends on:** Phase 162

**Requirements:** DAEM-02, DAEM-05

**Success Criteria** (what must be TRUE):
1. Swift app spawns Python daemon subprocess with stdio pipes
2. Communication uses JSON-RPC over stdin/stdout (line-delimited, `\n` protocol)
3. Python stdout forced to line buffering (Pitfall 2 prevention: `PYTHONUNBUFFERED=1` or `-u` flag)
4. App survives daemon restart (no leaked pipes, reconnection transparent)
5. Watchdog timer kills and restarts daemon if no stdout response in 30 seconds

**Plans:** 1 plan

---

### Phase 168: Python MCP Server

**Goal:** Daemon exposes every kicad-agent op (142+) as MCP tool, auto-registered from registry

**Depends on:** Phase 167

**Requirements:** DAEM-03, DAEM-04

**Success Criteria** (what must be TRUE):
1. Adding new op to Python registry auto-exposes as MCP tool (zero glue code)
2. MCP server uses stdio transport (mcp.run with transport="stdio")
3. Tool list published via MCP list_tools (dynamic from ops registry)
4. Pydantic schemas auto-convert to JSON Schema for Tool inputSchema
5. All 142 ops callable via MCP with correct schema validation

**Plans:** 1 plan

---

### Phase 169: Obdurate Runtime

**Goal:** State machine enforces GSD phase transitions, op journal (fsync), escalation ladder

**Depends on:** Phase 168

**Requirements:** GOV-01, GOV-02, GOV-06, GOV-07, GOV-08, GOV-10, GOV-11

**Success Criteria** (what must be TRUE):
1. Every op passes Intent Gate before execution (parse, validate, link to requirement)
2. Workflow State Machine enforces transitions (can't run DRC without PCB)
3. Op Journal logs every op with fsync durability (JSONL per audit.py pattern)
4. Escalation ladder auto-triggers on failures (T1→T2→T3→T4)
5. Drift detection warns on out-of-scope files (requirement_id required)

**Plans:** 1 plan

---

### Phase 170: Verification Loop Integration

**Goal:** Python validation_gates.py wrapped for Swift, ERC/DRC enforcement before commits

**Depends on:** Phase 169

**Requirements:** GOV-03, GOV-04, GOV-05

**Success Criteria** (what must be TRUE):
1. Pre-op verification gate validates intent matches op and will achieve goal
2. Post-op verification gate runs deterministic check + semantic check
3. Auto-rollback on verification failure (PersistentUndoStack checkpoint)
4. ERC/DRC gates must pass before KiCad files marked valid
5. Verification failures surfaced as user decisions (not silent failures)

**Plans:** 1 plan

---

### Phase 171: Liquid Glass UI Shell

**Goal:** SwiftUI app shell with toolbar, window management, Liquid Glass visual language

**Depends on:** Phase 161

**Requirements:** CHAT-05, A11Y-03, A11Y-06

**Success Criteria** (what must be TRUE):
1. App shows toolbar with New Project, Open, Settings, Share actions
2. Window management supports multiple project windows (CMD+N, CMD+W)
3. Liquid Glass visual language applied (consistent spacing, typography, colors)
4. Keyboard navigation works for all UI flows (tab, space, enter)
5. Reduce Motion and Reduce Transparency preferences respected

**Plans:** 1 plan

**Plan List:**
- [x] 171-01-PLAN.md — 01

**UI hint:** yes

---

### Phase 172: Inline Rendering

**Goal:** User sees inline schematic (SVG) and PCB (PNG) renders within chat/pipeline views

**Depends on:** Phase 163

**Requirements:** CHAT-03, CHAT-04, PIPE-01, PIPE-02, PIPE-04

**Success Criteria** (what must be TRUE):
1. Schematic previews render as SVG inline when model generates circuit
2. PCB renders render as PNG inline when routing completes
3. Pipeline view shows horizontal step bar (design → schematic → ERC → PCB → DRC → export)
4. Each pipeline step shows status icon (pending/running/verified/failed) and duration
5. Failed steps show error context and retry option

**Plans:** 1 plan

**Plan List:**
- [x] 172-01-PLAN.md — 01

**UI hint:** yes

---

### Phase 173: GSD Conversation Engine

**Goal:** Visual GSD methodology: questioning → spec → roadmap → execute → verify phases

**Depends on:** Phase 170

**Requirements:** GSD-01, GSD-02, GSD-03, GSD-04, GSD-08

**Success Criteria** (what must be TRUE):
1. When user starts new project, app runs questioning phase (clarifying questions)
2. App generates visual Spec card (expandable, editable) from responses
3. App generates visual Roadmap (timeline of phases) user can approve/refine
4. User can tap any roadmap phase to see detail (goal, requirements, success criteria)
5. User can edit a previous message and re-submit (forks conversation)

**Plans:** 1 plan

**Plan List:**
- [x] 173-01-PLAN.md — 01

**UI hint:** yes

---

### Phase 174: Approval Gates UI

**Goal:** Human-in-the-loop decision prompts with full context at GSD gates

**Depends on:** Phase 173

**Requirements:** GSD-05, GSD-06, GSD-07

**Success Criteria** (what must be TRUE):
1. App pauses execution at approval gates (ERC warnings, op confirmation, phase transitions)
2. User can approve, reject, or "show me" at any gate
3. Approval prompt shows full context (intent, op, verification result, requirement linkage)
4. Obdurate Runtime verification failures surfaced as user decisions
5. Completion summary card shows renders, exports, decisions made when phase ships

**Plans:** 1 plan

**Plan List:**
- [x] 174-01-PLAN.md — 01

**UI hint:** yes

---

### Phase 175: Chat Interface

**Goal:** Conversational UI with message streaming, image attachments, conversation history

**Depends on:** Phase 171

**Requirements:** CHAT-01, CHAT-02, CHAT-05, CHAT-06, CHAT-07, CHAT-08

**Success Criteria** (what must be TRUE):
1. User can type natural-language hardware design intent ("design a distortion pedal")
2. User sees streamed model responses token-by-token (not buffered)
3. User can scroll, search, and copy from full conversation history
4. User can attach images (reference schematics, photos) to messages
5. User sees cost estimate and model badge per assistant message

**Plans:** 1 plan

**Plan List:**
- [x] 175-01-PLAN.md — 01

**UI hint:** yes

---

### Phase 176: SwiftData Models

**Goal:** SwiftData models for Project, Conversation, Message, Decision, ValueChange, Snapshot

**Depends on:** Phase 171

**Requirements:** MEM-01, MEM-03, MEM-04, MEM-05

**Success Criteria** (what must be TRUE):
1. App persists every message, decision, value change, op call as SwiftData models
2. Conversations are append-only (never truncated, never lost)
3. Decisions are first-class objects (UUID, timestamp, key, value, reasoning, status)
4. Values are event-sourced (every change tracked with old/new value and reason)
5. SwiftData schema frozen early (v6.0.0) for CloudKit stability (Pitfall 4 prevention)

**Plans:** 1 plan

---

### Phase 177: CloudKit Sync

**Goal:** Automatic Mac↔iPhone sync, LWW conflict resolution with prompts

**Depends on:** Phase 176

**Requirements:** MEM-02, MEM-09, MEM-10

**Success Criteria** (what must be TRUE):
1. SwiftData syncs automatically to CloudKit (private DB, free tier) across Mac and iPhone
2. User can search across all conversations (per-project and cross-project)
3. Conflict resolution uses LWW with prompts for value changes (both sides asked)
4. Two-device migration test passes (Phone v1.0, Mac v1.1, verify sync, Pitfall 4 prevention)
5. CloudKit sync never auto-migrates schema (explicit VersionedSchema only)

**Plans:** 1 plan

---

### Phase 178: Time-Travel Engine

**Goal:** Event replay, snapshot materialization, diff visualization, restore capability

**Depends on:** Phase 177

**Requirements:** TT-01, TT-02, TT-03, TT-04, TT-06, TT-07

**Success Criteria** (what must be TRUE):
1. User sees Decision Timeline view showing all decisions/values chronologically
2. Each timeline entry links back to originating message (jump to conversation)
3. User can scrub slider to see project state at any point in time
4. User can compare two points (diff view showing values, decisions, conversation changes)
5. User can restore to any snapshot (preserves history, creates restoration event)

**Plans:** 1 plan

**UI hint:** yes

---

### Phase 179: Decision Timeline UI

**Goal:** Visual timeline with chapter segmentation, filters, search

**Depends on:** Phase 178

**Requirements:** TT-05, MEM-06, MEM-08

**Success Criteria** (what must be TRUE):
1. Decision Timeline UI loads chunks (pagination, not entire history)
2. Run-on conversations support chapter segmentation (LLM-suggested, user-editable)
3. Hybrid snapshot capture: auto-snapshot on every decision, manual anytime
4. Timeline loads < 2 seconds with 100K events (Pitfall 8 prevention)
5. User can filter timeline by decision type, date range, participant

**Plans:** 1 plan

**UI hint:** yes

---

### Phase 180: Event Sourcing

**Goal:** Complete append-only journal, query optimization, event compaction

**Depends on:** Phase 179

**Requirements:** MEM-07

**Success Criteria** (what must be TRUE):
1. Op journal logs every op (uuid, timestamp, actor, intent, op, args, result, verification, requirement_id)
2. Events partition by project (separate Event per ProjectID for query pruning)
3. Materialized snapshots maintain current state (don't replay events on every query)
4. Event compaction archives old events to separate store (active events < 100K)
5. SwiftData query tests pass with 100K event dataset (Pitfall 8 prevention)

**Plans:** 1 plan

---

### Phase 181: SKIDL Compiler

**Goal:** Conversation state → SKIDL IR (depends on v5.0 Track F)

**Depends on:** Phase 180, v5.0 Track F completion (BLOCKED until v5.0 lands)

**Requirements:** GENOUT-01, GENOUT-06

**Success Criteria** (what must be TRUE):
1. Conversation state (messages + decisions + values + op journal) IS source of truth
2. SKIDL compiler consumes conversation state and generates SKIDL IR
3. .kicad_sch and .kicad_pcb are derived artifacts (regenerable from journal)
4. SKIDL compiler integration depends on v5.0 Phase 156 (SKIDL Converter) completion
5. Phase BLOCKED until v5.0 Track F completes (hard dependency)

**Plans:** 1 plan

---

### Phase 182: KiCad Generator

**Goal:** SKIDL → .kicad_sch/.kicad_pcb files with validation gates

**Depends on:** Phase 181

**Requirements:** GENOUT-02, GENOUT-07

**Success Criteria** (what must be TRUE):
1. KiCad generator consumes SKIDL IR and emits .kicad_sch and .kicad_pcb files
2. Generated files pass kicad-cli ERC/DRC before being marked valid
3. Generation pipeline uses v5.0 Phase 160 (NL Circuit Generation) outputs
4. Generator failures trigger Obdurate escalation (T1 retry → T2 strategy → T3 human)
5. Generated files are deterministic (same SKIDL produces same KiCad files)

**Plans:** 1 plan

---

### Phase 183: Generative Pipeline

**Goal:** Full transform orchestration with caching and hash verification

**Depends on:** Phase 182

**Requirements:** GENOUT-03, GENOUT-05

**Success Criteria** (what must be TRUE):
1. Pipeline orchestration runs full transform (conversation → SKIDL → KiCad → validation)
2. Generation is deterministic (same journal state produces same hash output, Pitfall 5 prevention)
3. Hash-based gold master tests catch generation drift in CI
4. User can regenerate files from any snapshot (time-travel + generative combined)
5. Pipeline caches derived artifacts (hash → artifact, invalidate on upstream change)

**Plans:** 1 plan

---

### Phase 184: Hash Gold Master Tests

**Goal:** Deterministic generation verification with 10-run tests

**Depends on:** Phase 183

**Requirements:** GENOUT-04, TEST-06

**Success Criteria** (what must be TRUE):
1. Hash gold master tests run 10x with same inputs, assert all hashes identical (Pitfall 5 prevention)
2. Hash includes only deterministic inputs (operation list, component set, net list, conversation intent)
3. Hash excludes timestamps, UUIDs, metadata, ordering-independent fields
4. Collections sorted before hashing (canonical JSON stored in event journal)
5. CI fails if generative output hash drifts from gold master fixture

**Plans:** 1 plan

---

### Phase 185: Generative Correctness

**Goal:** SPICE validation, ERC/DRC enforcement, escalation on generation failure

**Depends on:** Phase 184

**Requirements:** GENOUT-08

**Success Criteria** (what must be TRUE):
1. Generated schematics pass SPICE validation (ngspice integration from v5.0 Phase 158)
2. Generated PCBs pass ERC/DRC before being marked valid
3. Generation failures trigger Obdurate escalation (T1→T2→T3→T4 ladder)
4. Escalation surfaces failures as user decisions (not silent failures)
5. SPICE results used as reward signal for training (v5.0 Phase 159 integration)

**Plans:** 1 plan

---

### Phase 186: Project Genealogy

**Goal:** Family tree, branches, false starts, snapshot relationships

**Depends on:** Phase 178

**Requirements:** GEN-01, GEN-02, GEN-03, GEN-04, GEN-05, GEN-07

**Success Criteria** (what must be TRUE):
1. User sees visual family tree of all projects (parent, children, branches, merges)
2. Branches show status (active, abandoned, merged, archived)
3. Abandoned branches show reason ("too noisy", "user preferred TS sound")
4. User can branch from any project (creates child with parent reference)
5. User can branch from any snapshot (creates child at point in time)

**Plans:** 1 plan

**Plan List:**
- [x] 186-01-PLAN.md — Build project genealogy system (SwiftData models, branch/fork operations, family tree UI with graph visualization)

**UI hint:** yes

---

### Phase 187: Group Activities v1

**Goal:** Live sessions with 4-participant cap, event sync (not files)

**Depends on:** Phase 186

**Requirements:** LIVE-01, LIVE-02, LIVE-06, LIVE-07

**Success Criteria** (what must be TRUE):
1. User can start live session via FaceTime-style interface (Group Activities)
2. Up to 4 participants can join session (cap for v1, raise in v1.x)
3. Session survives network drops (auto-reconnect, replay missed events)
4. Session ends cleanly when initiator leaves (or hands off to participant)
5. Conversation events sync live (messages, decisions, value changes appear instantly)

**Plans:** 1 plan

**Plan List:**
- [x] 187-01-PLAN.md — Build Group Activities v1 (session lifecycle, 4-participant cap, event sync, auto-reconnect, auto-handoff)

**UI hint:** yes

---

### Phase 188: CKShare Invitations

**Goal:** Collaborator invitations with permission management (Owner/Editor/Viewer)

**Depends on:** Phase 187

**Requirements:** COLLAB-01, COLLAB-02, COLLAB-03, COLLAB-04, COLLAB-09

**Success Criteria** (what must be TRUE):
1. User can share project via native macOS Share Sheet (CKShare)
2. User can invite collaborators by email or iMessage
3. Owner sets permission per collaborator (view, edit, fork) — default is view
4. Collaborator accepts invite via universal link, project appears in app
5. Owner can revoke access at any time

**Plans:** 1 plan

**Plan List:**
- [x] 188-01-PLAN.md — Build CKShare invitation system (Share Sheet, permission management, Apple ID sign-in, expired link handling, revocation)

**UI hint:** yes

---

### Phase 189: Collaboration UI

**Goal:** Activity feed, participant status, permission badges, sync visualization

**Depends on:** Phase 188

**Requirements:** COLLAB-05, COLLAB-06, COLLAB-07, COLLAB-08, COLLAB-10, LIVE-03, LIVE-04, LIVE-05

**Success Criteria** (what must be TRUE):
1. Collaborators see full conversation history, decisions, values, renders
2. Collaborator with edit permission can send messages and approve gates
3. Ops execute on collaborator's Mac (their daemon), state syncs via CloudKit
4. User sees activity feed ("Alice added decision X", "Bob approved gate Y")
5. Participants see cursor positions and selections in real-time

**Plans:** 1 plan

**Plan List:**
- [x] 189-01-PLAN.md — Build collaboration UI (shared project view, activity feed, LWW conflict resolution, cursor sync stub)

**UI hint:** yes

---

### Phase 190: iCloud Drive Bundle

**Goal:** .kicadagent document type, atomic writes, conflict resolution

**Depends on:** Phase 189

**Requirements:** FILE-01, FILE-02, FILE-03, FILE-04, FILE-05, FILE-06

**Success Criteria** (what must be TRUE):
1. Each project stored as .kicadagent document bundle (atomic document type)
2. Bundles sync via iCloud Drive (user's account, no dev infra)
3. Bundle contains: conversation.jsonl, decisions.json, values.json, schematic.kicad_sch, pcb.kicad_pcb, renders/
4. Bundle writes atomic via NSFileCoordinator (Pitfall 6 prevention)
5. Simultaneous edit Mac+iPhone test passes (atomic bundle replace, Pitfall 6 prevention)

**Plans:** 1 plan

**Plan List:**
- [x] 190-01-PLAN.md — Build iCloud Drive bundle system (.kicadagent document type, atomic writes, corrupt bundle repair, macOS Versions API, zip export)

**UI hint:** yes

---

## Progress Tracking

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 161. App Shell Foundation | 0/3 | Not started | - |
| 162. Python Daemon Bundling | 0/3 | Not started | - |
| 163. KiCad CLI Integration | 0/3 | Not started | - |
| 164. LLM Provider Protocol | 0/3 | Not started | - |
| 165. Provider Router | 0/3 | Not started | - |
| 166. BYOK Keychain Storage | 0/3 | Not started | - |
| 167. stdio MCP Client | 0/3 | Not started | - |
| 168. Python MCP Server | 0/3 | Not started | - |
| 169. Obdurate Runtime | 0/4 | Not started | - |
| 170. Verification Loop Integration | 0/3 | Not started | - |
| 171. Liquid Glass UI Shell | 1/1 | **Planned** | - |
| 172. Inline Rendering | 1/1 | **Planned** | - |
| 173. GSD Conversation Engine | 1/1 | **Planned** | - |
| 174. Approval Gates UI | 1/1 | **Planned** | - |
| 175. Chat Interface | 1/1 | **Planned** | - |
| 176. SwiftData Models | 0/3 | Not started | - |
| 177. CloudKit Sync | 0/3 | Not started | - |
| 178. Time-Travel Engine | 0/4 | Not started | - |
| 179. Decision Timeline UI | 0/3 | Not started | - |
| 180. Event Sourcing | 0/3 | Not started | - |
| 181. SKIDL Compiler | 0/3 | Blocked (v5.0) | - |
| 182. KiCad Generator | 0/3 | Blocked (v5.0) | - |
| 183. Generative Pipeline | 0/3 | Blocked (v5.0) | - |
| 184. Hash Gold Master Tests | 0/3 | Blocked (v5.0) | - |
| 185. Generative Correctness | 0/3 | Blocked (v5.0) | - |
| 186. Project Genealogy | 0/3 | Not started | - |
| 187. Group Activities v1 | 0/3 | Not started | - |
| 188. CKShare Invitations | 0/3 | Not started | - |
| 189. Collaboration UI | 0/4 | Not started | - |
| 190. iCloud Drive Bundle | 0/3 | Not started | - |
| 191. swift-testing Framework | 0/3 | Not started | - |
| 192. Snapshot Testing | 0/3 | Not started | - |
| 193. Property-Based Testing | 0/3 | Not started | - |
| 194. Mutation Testing | 0/3 | Not started | - |
| 195. Accessibility Testing | 0/3 | Not started | - |
| 196. UI Automation | 0/3 | Not started | - |
| 197. Performance Testing | 0/3 | Not started | - |
| 198. Concurrency Testing | 0/3 | Not started | - |
| 199. Python Daemon Testing | 0/3 | Not started | - |
| 200. CI Coverage Gates | 0/3 | Not started | - |
| 201. A11y by Default | 1/1 | **Planned** | - |
| 202. iPhone Companion | 1/1 | **Planned** | - |

**Total:** 42 phases, 132 requirements mapped, 100% coverage, **7 plans written for phases 171-175, 201-202**

---

## Track Overview

**Track A: Foundation (Phases 161-163)** — App shell, Python daemon bundling, KiCad CLI integration
**Track B: Models (Phases 164-166)** — LLM Provider protocol, Provider Router, BYOK Keychain storage
**Track C: Governance (Phases 167-170)** — stdio MCP client, Python MCP server, Obdurate Runtime, Verification Loop
**Track D: UI Surfaces (Phases 171-175)** — Liquid Glass shell, Inline Rendering, GSD Conversation Engine, Approval Gates, Chat Interface
**Track E: Memory (Phases 176-180)** — SwiftData models, CloudKit sync, Time-Travel, Decision Timeline, Event Sourcing
**Track F: Generative (Phases 181-185)** — SKIDL compiler, KiCad generator, Generative Pipeline, Hash Gold Master Tests, Generative Correctness
**Track G: Collaboration (Phases 186-190)** — Project Genealogy, Group Activities, CKShare invitations, Collaboration UI, iCloud Drive Bundle
**Track H: Quality (Phases 191-202)** — swift-testing, Snapshot tests, Property-based tests, Mutation tests, A11y, UI Automation, Performance, Concurrency, Python daemon tests, CI gates, iPhone Companion

**Critical Path:** A → B → C → D → E → F → G (Quality H runs in parallel)

**Pitfall Addressed by Phase:**
- Phase 162: PyInstaller dylib signing (Pitfall 1)
- Phase 163: App Store GPL compliance (Pitfall 9)
- Phase 164: FoundationModels unavailability (Pitfall 3)
- Phase 167: stdio MCP buffering deadlock (Pitfall 2)
- Phase 177: SwiftData CloudKit migration loss (Pitfall 4)
- Phase 183: Generative hash instability (Pitfall 5)
- Phase 190: iCloud Drive bundle corruption (Pitfall 6)
- Phase 197: MLX-Swift Metal memory pressure (Pitfall 7)

---

## Dependencies

**Hard dependencies:**
- Phase 162 depends on Phase 161 (daemon needs app shell)
- Phase 163 depends on Phase 162 (kicad-cli needs daemon lifecycle)
- Phase 167 depends on Phase 162 (stdio client needs daemon bundling)
- Phase 168 depends on Phase 167 (MCP server needs stdio client)
- Phase 169 depends on Phase 168 (Obdurate needs MCP server)
- Phase 170 depends on Phase 169 (Verification needs Obdurate)
- Phase 173 depends on Phase 170 (GSD needs verification gates)
- Phase 171 depends on Phase 161 (UI shell needs app foundation)
- Phase 172 depends on Phase 163 (inline rendering needs kicad-cli)
- Phase 174 depends on Phase 173 (gates need GSD engine)
- Phase 175 depends on Phase 171 (chat needs UI shell)
- Phase 176 depends on Phase 171 (SwiftData needs UI shell)
- Phase 177 depends on Phase 176 (CloudKit needs models)
- Phase 178 depends on Phase 177 (Time-travel needs CloudKit)
- Phase 181 BLOCKED on v5.0 Track F (SKIDL dependency)
- Phase 186 depends on Phase 178 (Genealogy needs time-travel)
- Phase 187 depends on Phase 186 (Group Activities needs genealogy)
- Phase 188 depends on Phase 187 (CKShare needs Group Activities)
- Phase 189 depends on Phase 188 (Collab UI needs CKShare)
- Phase 190 depends on Phase 189 (iCloud bundle needs collab)

**Parallel tracks:**
- Track H (Quality) runs in parallel with all tracks (continuous testing)
- Track E (Memory) can start in parallel with Track D (UI) after Track C (Governance)
- Track G (Collaboration) can start in parallel with Track F (Generative) after Track E (Memory)

---

**Last updated:** 2026-07-07 — v6.0 roadmap updated, phases 171-175, 201-202 planned with 7 plans total
