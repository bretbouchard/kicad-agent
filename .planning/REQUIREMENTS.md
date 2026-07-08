# Milestone v6.0 Requirements — KiCad Agent: The Closed Box

**Status:** Defining (2026-07-07)
**Milestone:** v6.0 KiCad Agent — The Closed Box
**Target Phases:** 161-202 (continues from v5.0 phase 160)

## Requirements

### APP — App Shell & Platform

- [x] **APP-01**: User can launch the app on macOS 27+ and see a Liquid Glass chat interface within 2 seconds. *If daemon fails to spawn within 5s, app shows recovery UI with retry/quit options (no silent hang).* ✅ Phase 161
- [x] **APP-02**: User can install the app from the Mac App Store without warnings or sandbox violations. *If App Store submission is rejected, fallback distribution path is notarized direct download from website.* ✅ Phase 161 (source ready; signing in Phase 203)
- [x] **APP-03**: App bundles the Python daemon (PyInstaller binary) inside the .app package and spawns it as a subprocess on launch. *Daemon binary checksum verified on launch; corrupt binary triggers re-download prompt.* ✅ Phase 162
- [ ] **APP-04**: App detects missing external KiCad install and guides user to install KiCad 10+ (one-time setup). *App cannot start main workflow without KiCad; shows dedicated onboarding screen with one-tap install link.*
- [x] **APP-05**: App gracefully shuts down daemon on app quit (no orphan processes). *Daemon shutdown has 5-second timeout; hung daemon is force-killed with audit-log entry.* ✅ Phase 162
- [x] **APP-06**: User can have multiple projects open in separate windows ✅ Phase 161
- [x] **APP-07**: App respects system appearance (dark/light) and Dynamic Type ✅ Phase 161

### CHAT — Conversational Interface

- [ ] **CHAT-01**: User can type natural-language hardware design intent ("design a distortion pedal for bass"). *Empty or invalid input shows inline placeholder hint, never submits empty messages.*
- [ ] **CHAT-02**: User sees streamed model responses (token-by-token, not buffered). *Stream failures show partial response + retry button; user can ESC to cancel stream.*
- [ ] **CHAT-03**: User sees inline schematic previews (SVG) within chat when relevant. *SVG render failures show fallback placeholder with 'regenerate' button.*
- [ ] **CHAT-04**: User sees inline PCB renders (PNG) within chat when relevant. *PNG render failures show fallback placeholder with 'regenerate' button.*
- [ ] **CHAT-05**: User can scroll, search, and copy from full conversation history. *Conversation list uses lazy virtualization; 10K messages scroll without lag.*
- [ ] **CHAT-06**: User can attach images (reference schematics, photos) to messages. *Images >10MB auto-compressed; unsupported formats show inline error.*
- [ ] **CHAT-07**: User sees cost estimate and model badge per assistant message
- [ ] **CHAT-08**: User can edit a previous message and re-submit (forks conversation)

### GSD — Conversation Engine

- [ ] **GSD-01**: When user starts a new project, app runs questioning phase (asks clarifying questions until requirements are clear). *User can skip questioning with 'Use defaults' button; bad input returns inline clarification.*
- [ ] **GSD-02**: App generates a visual Spec card (expandable, editable) from questioning responses
- [ ] **GSD-03**: App generates a visual Roadmap (timeline of phases) user can approve or refine. *Roadmap generation failures (e.g., impossible requirements) show inline error with 'Regenerate' button.*
- [ ] **GSD-04**: User can tap any roadmap phase to see detail (goal, requirements, success criteria)
- [ ] **GSD-05**: App pauses execution at approval gates (ERC warnings, op confirmation, phase transitions)
- [ ] **GSD-06**: User can approve, reject, or "show me" at any gate
- [ ] **GSD-07**: App surfaces Obdurate Runtime verification failures as user decisions (not silent failures)
- [ ] **GSD-08**: App shows a completion summary card (renders, exports, decisions made) when project phase ships. *Completion summary accessible from project menu after dismissal.*

### PIPELINE — Live Pipeline View

- [ ] **PIPE-01**: User sees a horizontal step bar showing current workflow stage (design → schematic → ERC → PCB → DRC → export)
- [ ] **PIPE-02**: Each step shows status icon (pending, running, verified, failed) and duration. *Steps with no progress for >2 minutes marked stale with warning indicator.*
- [ ] **PIPE-03**: User can tap any step to drill into detail (intent, ops called, verification results)
- [ ] **PIPE-04**: Pipeline updates live as ops execute (no manual refresh). *Daemon disconnect shows 'Reconnecting' state in pipeline; auto-restores without losing step state.*
- [ ] **PIPE-05**: Failed steps show error context and retry option. *Retry failure 3x triggers Obdurate escalation; user sees 'Request human input' option.*

### MODELS — Provider Layer

- [x] **MOD-01**: App uses `KiCadModelProvider` Swift protocol as the only model interface (no SDK types leak) ✅ Phase 164
- [x] **MOD-02**: App routes model calls based on task (privacy mode → local, vision needed → cloud/MLX, complex reasoning → user's preferred). *Unavailable preferred model falls back to FoundationModels with one-time notification.* ✅ Phase 165
- [ ] **MOD-03**: User can configure API keys for Anthropic, OpenAI, Google, Groq, xAI, Together via Provider Settings UI. *Invalid API keys detected via test call on save; revoked keys (401) trigger re-entry prompt.*
- [ ] **MOD-04**: API keys are stored in Keychain with **iCloud Keychain sync ON by default** (user can opt-out via Settings). Aligns with PROJECT.md locked decision 2026-07-07.
- [ ] **MOD-05**: App never proxies API calls through developer infrastructure (pure BYOK, zero dev liability)
- [x] **MOD-06**: FoundationModels is always available as default (free, on-device, no key required). *Devices without Apple Intelligence see banner explaining local-only mode + link to add API key.* ✅ Phase 164
- [ ] **MOD-07**: User can browse and download MLX models from Hugging Face Hub catalog (zero dev infra). *Failed downloads resume on app relaunch; incompatible models (.safetensors without MLX metadata) rejected with explanation.*
- [ ] **MOD-08**: User can drag-drop `.mlx` model files to import custom fine-tunes. *Drag-drop validates .mlx format; rejected files show inline error with format requirements.*
- [ ] **MOD-09**: App shows download progress for MLX models and notifies on completion
- [x] **MOD-10**: User can pick preferred model per task type (quick replies, complex reasoning, vision). *Unavailable preferred model falls back to FoundationModels with one-time notification.* ✅ Phase 165
- [x] **MOD-11**: App falls back to FoundationModels when user lacks cloud API keys ✅ Phase 165
- [x] **MOD-12**: App shows token usage and cost estimate per message ✅ Phase 165

### DAEMON — Python Daemon & stdio MCP

- [x] **DAEM-01**: App spawns bundled Python daemon as subprocess on launch. *On app wake, daemon health checked; if dead, silent restart with audit-log entry.* ✅ Phase 162
- [x] **DAEM-02**: Swift app communicates with daemon via stdio MCP transport (no HTTP, no ports). *Daemon stdout forced unbuffered (PYTHONUNBUFFERED=1); 30s watchdog kills hung daemon.* ✅ Phase 162 (env + watchdog) + Phase 167 (MCPClient + StdioWatchdog + initialize/tools-list/tools-call lifecycle + DAEM-02 audit-before-kill)
- [ ] **DAEM-03**: Daemon exposes every kicad-agent op (142+) as an MCP tool, auto-registered from ops registry
- [ ] **DAEM-04**: Adding a new op to the Python registry automatically exposes it as an MCP tool (zero glue)
- [x] **DAEM-05**: Daemon survives app sleep/wake cycles (no daemon restart needed). *On app wake, daemon health checked; silent restart if dead.* ✅ Phase 162
- [x] **DAEM-06**: Daemon crashes trigger automatic restart with audit-log entry. *Crash loop detection (5 crashes in 60s) halts auto-restart and shows recovery UI.* ✅ Phase 162
- [ ] **DAEM-07**: User can opt-in to external HTTP MCP server (for Claude Code/Cursor/scripts) via Settings toggle (default off)
- [ ] **DAEM-08**: External HTTP MCP requires auth token (regenerable, shown via QR for pairing). *Suspicious usage patterns (10x failed auth) auto-revoke token + notify user.*

### MEMORY — Event-Sourced Storage

- [ ] **MEM-01**: App persists every conversation message, decision, value change, and op call as SwiftData models
- [ ] **MEM-02**: SwiftData syncs automatically to CloudKit (private DB, free tier) across user's Mac and iPhone. *CloudKit sync failures show banner after 3 retries; user can retry or work offline.*
- [ ] **MEM-03**: Conversations are append-only (never truncated, never lost)
- [ ] **MEM-04**: Decisions are first-class objects (UUID, timestamp, key, value, reasoning, status)
- [ ] **MEM-05**: Values are event-sourced (every change tracked with old/new value and reason)
- [ ] **MEM-06**: Op journal logs every daemon op (intent, args, result, verification, requirement linkage)
- [ ] **MEM-07**: Hybrid snapshot capture: auto-snapshot on every decision, manual snapshot anytime
- [ ] **MEM-08**: Run-on conversations support chapter segmentation (LLM-suggested, user-editable). *Chapters capped at 10 per project; LLM-suggested chapters user-editable in timeline.*
- [ ] **MEM-09**: User can search across all conversations (per-project and cross-project). *Empty search results show 'recently viewed' fallback; >500 results paginated.*
- [ ] **MEM-10**: Conflict resolution uses LWW with prompts for value changes (both sides asked). *Prompt UI shows both versions side-by-side with 'keep mine / keep theirs / merge' options.*

### TIMETRAVEL — Time-Travel & Diff

- [ ] **TT-01**: User sees a Decision Timeline view showing all decisions and value changes chronologically
- [ ] **TT-02**: Each timeline entry links back to originating message (jump to conversation context)
- [ ] **TT-03**: User can scrub a slider to see project state at any point in time. *Scrub slider debounced (100ms); 1M+ event timelines virtualized.*
- [ ] **TT-04**: User can compare two points in time (diff view showing values, decisions, conversation changes)
- [ ] **TT-05**: User can fork from any snapshot (creates new branch with full history)
- [ ] **TT-06**: User can restore to any snapshot (preserves history, creates restoration event)
- [ ] **TT-07**: Snapshots are immutable (captured state never changes)

### GENEALOGY — Project Family Tree

- [ ] **GEN-01**: User sees a visual family tree of all projects (parent, children, branches, merges). *Family tree supports 1000+ projects with search/filter; cycle prevention on merge.*
- [ ] **GEN-02**: Branches show status (active, abandoned, merged, archived)
- [ ] **GEN-03**: Abandoned branches show reason ("too noisy", "user preferred TS sound"). *Abandon branch prompts for reason (optional, skippable); 'Decided later' default.*
- [ ] **GEN-04**: User can branch from any project (creates child with parent reference)
- [ ] **GEN-05**: User can branch from any snapshot (creates child at point in time)
- [ ] **GEN-06**: User can merge work from one branch into another (creates merge event). *Merge conflicts trigger three-way merge UI; user picks which side wins per conflict.*
- [ ] **GEN-07**: User can view diff between any two projects or snapshots

### GENERATIVE — Conversation-Coupled Generation

- [ ] **GENOUT-01**: Conversation state (messages + decisions + values + op journal) IS the source of truth
- [ ] **GENOUT-02**: `.kicad_sch` and `.kicad_pcb` files are derived artifacts, regenerable from journal
- [ ] **GENOUT-03**: Generation is deterministic (same journal state produces same hash output). *Generation uses fixed-precision math + sandboxed execution; no timestamps in generated content.*
- [ ] **GENOUT-04**: Hash-based gold master tests catch any generation drift in CI
- [ ] **GENOUT-05**: User can regenerate files from any snapshot (time-travel + generative combined)
- [ ] **GENOUT-06**: Generation pipeline consumes v5.0 SKIDL IR + SPICE validation (Track F dependency)
- [ ] **GENOUT-07**: Generated files pass kicad-cli ERC/DRC before being marked valid
- [ ] **GENOUT-08**: Generation failures trigger Obdurate escalation (T1 retry → T2 strategy switch → T3 human)

### COLLAB — Collaboration & Sharing

- [ ] **COLLAB-01**: User can share a project via native macOS Share Sheet (CKShare)
- [ ] **COLLAB-02**: User can invite collaborators by email or iMessage. *Invitees without Apple ID see 'Sign in with Apple ID' on first open.*
- [ ] **COLLAB-03**: Owner sets permission per collaborator (view, edit, fork) — default is view
- [ ] **COLLAB-04**: Collaborator accepts invite via universal link, project appears in their app. *Expired invite links show 'Request new invite' flow.*
- [ ] **COLLAB-05**: Collaborators see full conversation history, decisions, values, renders
- [ ] **COLLAB-06**: Collaborator with edit permission can send messages and approve gates
- [ ] **COLLAB-07**: Ops execute on collaborator's Mac (their daemon), state syncs via CloudKit. *Collaborator's offline ops queued in CloudKit; sync on next online session.*
- [ ] **COLLAB-08**: User sees activity feed ("Alice added decision X", "Bob approved gate Y"). *Activity feed filterable by collaborator + time range; >100 entries paginated.*
- [ ] **COLLAB-09**: Owner can revoke access at any time. *Revoked collaborators' local cache invalidated on next CloudKit sync; they see 'Access revoked' state.*
- [ ] **COLLAB-10**: LWW conflict resolution with prompt when both sides edit same value

### LIVE — Real-Time Collaboration (Group Activities)

- [ ] **LIVE-01**: User can start a live session via FaceTime-style interface (Group Activities). *If FaceTime/Group Activities unavailable, live session disabled with explanation.*
- [ ] **LIVE-02**: Up to 4 participants can join a session (cap for v1, raise in v1.x). *5th participant sees 'Session full (4/4)' with 'Notify when slot opens' option.*
- [ ] **LIVE-03**: Participants see cursor positions and selections in real-time
- [ ] **LIVE-04**: Conversation events sync live (messages, decisions, value changes appear instantly)
- [ ] **LIVE-05**: Each participant's Mac regenerates derived files locally (no file conflicts)
- [ ] **LIVE-06**: Session survives network drops (auto-reconnect, replay missed events)
- [ ] **LIVE-07**: Session ends cleanly when initiator leaves (or hands off to another participant). *Initiator abrupt leave auto-hands-off to longest-present participant; if all leave, session ends.*

### FILES — File Sync & Bundle

- [ ] **FILE-01**: Each project is stored as a `.kicadagent` document bundle
- [ ] **FILE-02**: Bundles sync via iCloud Drive (user's account, no dev infra). *iCloud Drive quota warnings at 90% full; user prompted to clean up or use local-only mode.*
- [ ] **FILE-03**: Bundle contains: conversation.jsonl, decisions.json, values.json, schematic.kicad_sch, pcb.kicad_pcb, renders/
- [ ] **FILE-04**: User can open bundles from Finder via standard document double-click. *Corrupt bundle shows 'Repair' option that attempts event-sourced regeneration.*
- [ ] **FILE-05**: Bundle has version history via macOS Versions API
- [ ] **FILE-06**: User can export bundle to zip for sharing outside iCloud. *Large bundles (>100MB) warn before zip export with size estimate.*

### IPHONE — iPhone Companion

- [ ] **IPH-01**: iPhone app shows same conversation as Mac (CloudKit sync)
- [ ] **IPH-02**: iPhone pairs with user's Mac automatically via iCloud Keychain (zero-config). *Different Apple ID on iPhone falls back to QR code pairing.*
- [ ] **IPH-03**: iPhone discovers Mac on LAN via Bonjour (`_kicadagent._tcp`). *Bonjour discovery failure shows 'Check Mac firewall' help screen.*
- [ ] **IPH-04**: iPhone sends messages to Mac daemon over encrypted TCP
- [ ] **IPH-05**: iPhone renders schematics (SVG) and PCBs (PNG) streamed from Mac. *Large renders compressed + progressive; slow networks show progressive load indicator.*
- [ ] **IPH-06**: iPhone can approve gates from anywhere (when Mac reachable on LAN). *Pending gates trigger push notification on iPhone (if user opted in).*
- [ ] **IPH-07**: iPhone queues messages when Mac not reachable ("will send when Mac available"). *Offline queue capped at 100 messages; queue expires after 7 days with user warning.*
- [ ] **IPH-08**: iPhone shows banner when Mac disconnected (read-only mode)
- [ ] **IPH-09**: iPhone can use FoundationModels for trivial offline questions
- [ ] **IPH-10**: iPhone shows cost tracking (read-only)

### A11Y — Accessibility by Default

- [ ] **A11Y-01**: Every interactive UI element has `.accessibilityLabel`
- [ ] **A11Y-02**: Every meaningful action has `.accessibilityHint`
- [ ] **A11Y-03**: Every UI flow is completable via keyboard only (tab navigation, space/enter activate)
- [ ] **A11Y-04**: VoiceOver reads every element correctly (verified via XCUITest)
- [ ] **A11Y-05**: Dynamic Type works up to `.accessibilityExtraExtraExtraLarge` without clipping
- [ ] **A11Y-06**: Reduce Motion and Reduce Transparency preferences respected
- [ ] **A11Y-07**: High contrast variant of every view (4-variant snapshot test)
- [ ] **A11Y-08**: Color contrast meets WCAG AA (4.5:1 minimum)
- [ ] **A11Y-09**: SwiftLint custom rules block PR if Button lacks accessibilityLabel

### TESTING — Militant Test Infrastructure

- [ ] **TEST-01**: All new code uses `swift-testing` framework (XCTest only for legacy XCUITest)
- [ ] **TEST-02**: 100% line + branch coverage enforced in CI (build fails if below)
- [ ] **TEST-03**: Every SwiftUI view has 4 snapshot variants (light, dark, Dynamic Type XXXL, high contrast)
- [ ] **TEST-04**: Property-based testing via SwiftCheck for invariants (fuzz inputs)
- [ ] **TEST-05**: Mutation testing via mull-xcode, score >90% required to merge
- [ ] **TEST-06**: Gold master hash tests on every generative output (drift fails CI)
- [ ] **TEST-07**: UI automation tests via XCUITest for every primary flow
- [ ] **TEST-08**: Accessibility audit runs in CI (VoiceOver simulation, keyboard-only flows)
- [ ] **TEST-09**: Performance tests with regression detection (latency, memory)
- [ ] **TEST-10**: Concurrency tests with ThreadSanitizer (no data races)
- [ ] **TEST-11**: Python daemon has same standard: pytest + 100% + mutation testing
- [ ] **TEST-12**: Nightly stress tests (10-hour daemon run, multi-account CloudKit, multi-session Group Activities)
- [ ] **TEST-13**: All build/archive/sign/test/ship automation goes through **Fastlane** (no manual Xcode clicks, no bespoke shell scripts wrapping xcodebuild)
- [ ] **TEST-14**: Code signing managed by **Fastlane match** (certs + profiles in a private git repo, synced across all developer devices and CI)
- [ ] **TEST-15**: TestFlight beta distribution via **Fastlane pilot** (every merge to main ships a TestFlight build, internal testers notified automatically)
- [ ] **TEST-16**: App Store submission via **Fastlane deliver** (metadata in Fastlane metadata repo, screenshots from `snapshot`, submission is one command)
- [ ] **TEST-17**: Pre-submission validation via **Fastlane precheck** (catches App Store rejection risks in CI before merge, never at submission time)
- [ ] **TEST-18**: PyInstaller binary build orchestrated by Fastlane lane `build_daemon` (Python + Swift builds unified in one `fastlane build_all` lane)

### GOV — Obdurate Runtime

- [ ] **GOV-01**: Every op passes through Intent Gate (parse, validate, link to requirement) before execution
- [ ] **GOV-02**: Workflow State Machine enforces phase transitions (can't run DRC without PCB)
- [ ] **GOV-03**: Pre-op verification gate (intent matches op, will achieve goal)
- [ ] **GOV-04**: Post-op verification gate (deterministic check + semantic check)
- [ ] **GOV-05**: Auto-rollback on verification failure (PersistentUndoStack checkpoint)
- [ ] **GOV-06**: Op Journal logs every op (uuid, timestamp, actor, intent, op, args, result, verification, requirement_id)
- [ ] **GOV-07**: Drift detection (out-of-scope files trigger warning, requirement_id required)
- [ ] **GOV-08**: Escalation ladder (T1 retry → T2 strategy switch → T3 external AI → T4 halt)
- [ ] **GOV-09**: Four-state resolution taxonomy (IMPLEMENTED, ADDED-AS-PHASE, SUPERSEDED-BY-ALTERNATIVE, DEFERRED-TO-NAMED-TARGET) — no silent deferrals
- [ ] **GOV-10**: Auto-learning (success → pattern store, failure → error_message store)
- [ ] **GOV-11**: Requirement coverage report (every op linked to requirement, every requirement has ops)

## Future Requirements (Deferred to v1.x / v2+)

- [ ] **FUTURE-01**: Windows support (native via Tauri or PWA)
- [ ] **FUTURE-02**: iPad-native layout (currently scales iPhone app)
- [ ] **FUTURE-03**: Web app for non-Apple users
- [ ] **FUTURE-04**: Cloud daemon for iPhone-only users (subscription)
- [ ] **FUTURE-05**: Group Activities participant cap >4 (raise based on usage)
- [ ] **FUTURE-06**: Plugin SDK for third-party ops
- [ ] **FUTURE-07**: Multi-language UI (i18n)
- [ ] **FUTURE-08**: Live co-editing with concurrent cursor on same schematic (advanced)
- [ ] **FUTURE-09**: AI auto-tagging of decisions (currently hybrid LLM-proposed + user-confirmed)
- [ ] **FUTURE-10**: Branch merging with conflict resolution UI (currently fork-only)

## Out of Scope (Locked Exclusions)

- **Cloud execution backend** — User's Mac (or collaborator's Mac) always does the work. No dev-hosted daemon. Pure BYOK.
- **AI bill proxying** — User pays provider directly with their API key. Developer has zero AI cost liability.
- **Windows v1** — Apple-native SLC focus. Windows/web is v7+.
- **Bundled kicad-cli** — GPLv3 blocks App Store. Require external KiCad install (one-time setup).
- **Native plan mode (in-app)** — GSD Conversation Engine handles planning visually. No raw plan files exposed to user.
- **Custom model training UI** — Training stays in Python scripts. App loads resulting fine-tunes via MLX-Swift.
- **Direct KiCad GUI integration** — App is the GUI. KiCad GUI not required (only kicad-cli).
- **Web-based admin/settings** — All settings native in macOS System app pattern.

## Traceability

(Filled by roadmapper — every REQ-ID maps to exactly one phase)

| Requirement | Phase | Plan |
|-------------|-------|------|
| (to be filled by ROADMAP.md) | | |

---

**Requirement count:** 138 requirements across 17 categories (all stupid-proof audited 2026-07-07 — see `.planning/research/v6/STUPID-PROOF-AUDIT.md`)

**Categories:** APP (7), CHAT (8), GSD (8), PIPE (5), MOD (12), DAEM (8), MEM (10), TT (7), GEN (7), GENOUT (8), COLLAB (10), LIVE (7), FILE (6), IPH (10), A11Y (9), TEST (18), GOV (11)

**Stupid-Proof Audit (2026-07-07):** 86 PASS, 46 AUGMENTED (clauses added inline above), 0 FAIL. Every requirement now answers both questions: (1) how does it prevent user-stupid harm? (2) how does it achieve magic-stupid flow?
