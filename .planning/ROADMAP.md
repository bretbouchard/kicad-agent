# ROADMAP — v7.0 Vendor-Neutral Manufacturing Layer

**Milestone:** v7.0 Vendor-Neutral Manufacturing Layer
**Target Phases:** 205-210 (6 phases; 205-209 active, 210 DEFERRED)
**Status:** Planning — 0/5 active phases shipped

## Goal

Send boards to ANY manufacturer — free DRC pre-flight for all vendors, universal versioned handoff package, and (deferred) opt-in quote/order APIs where available. No vendor lock-in.

The handoff package is the universal fallback — it works with every fab (3 with APIs, 10+ without). API adapters are accelerators on top, not requirements.

## Phases

- [x] **Phase 205: Board Metadata Foundation** — Parse/write KiCad `title_block`, `BoardSpec` model, sidecar JSON persistence (completed 2026-07-10)
- [x] **Phase 206: Vendor DRC Profiles** — Wire up `.kicad_dru` files (PCBWay, JLCPCB, AISLER, OSH Park, Advanced Circuits, generic), `drc_vendor` op (completed 2026-07-10)
- [x] **Phase 207: Versioned Build System** — Build record, manifest serialization, `build_create`/`build_list`/`build_show` ops, build diffing (completed 2026-07-11)
- [x] **Phase 208: Manufacturer Handoff Package** — Full export orchestration, zip bundle + readme, vendor output profiles, pre-handoff validation gate (completed 2026-07-11)
- [x] **Phase 209: Crossfile + MCP Integration** — MCP auto-exposure, CLI subcommands, `ProjectContext` discovery, `ManufacturerClient` ABC (completed 2026-07-11)
- [ ] **Phase 210: Vendor API Adapters** — DEFERRED (PCBWay, MacroFab, JLCPCB quote/order adapters) — placeholder, activated in v7.1

## Phase Details

### Phase 205: Board Metadata Foundation

**Goal:** User can read and write board metadata (revision, title, date, company) and persist manufacturing specs (surface finish, copper weight, mask/silk color, impedance) alongside a `.kicad_pcb` file

**Depends on:** Nothing (first phase — foundation for versioning)

**Requirements:** META-01, META-02, META-03, META-04, META-05, META-06, META-07

**Key work:**
- Extend `parser/pcb_native_parser.py` to parse `title_block` (currently in `_UNSUPPORTED_ELEMENTS`) — follow the existing `NativeStackup` pattern
- Add `NativeTitleBlock` frozen dataclass to `parser/pcb_native_types.py` (fields: title, date, rev, company, comments)
- Build `BoardSpec` model in `manufacturing/board_spec.py` (surface finish, copper weight, soldermask color, silkscreen color, controlled impedance requirements, stackup-as-fab-spec)
- Sidecar JSON persistence: `.kicad_build_spec.json` alongside the project
- Operations: `read_board_metadata`, `set_board_metadata`, `set_board_revision`
- Handle KiCad 10 quoting variations (quoted and unquoted fields, comments with special characters) — Pitfall 2 prevention

**Success Criteria** (what must be TRUE):
1. User runs `read_board_metadata` on a `.kicad_pcb` and gets the rev, title, date, and company from the `title_block`
2. User runs `set_board_revision(rev="2.1")` and the `.kicad_pcb` `title_block` round-trips with zero data loss (parse → modify → serialize produces a valid file)
3. User defines a `BoardSpec` (surface finish, copper weight, mask/silk color, impedance nets) and it persists to `.kicad_build_spec.json`; reloading the project restores it
4. Parsing handles KiCad 10 quoting variations — boards with empty fields, numbered comments, and special characters in title/company round-trip without corruption

**Plans:** 1/1 plans complete

---

### Phase 206: Vendor DRC Profiles

**Goal:** User can run DRC against a specific vendor's manufacturing limits as a pre-flight gate, and the system ships verified `.kicad_dru` files for 5+ vendors

**Depends on:** Nothing (independent of Phase 205; can partially overlap)

**Requirements:** DRC-01, DRC-02, DRC-03, DRC-04, DRC-05, DRC-06, DRC-07, DRC-08

**Key work:**
- Create `src/kicad_agent/manufacturing/drc_profiles/` with static `.kicad_dru` files:
  - `pcbway.kicad_dru` — from PCBWay official repo, updated to current capabilities (annular ring 0.15mm, not stale 0.25mm from 2023) — Pitfall 1 + DRC-07
  - `jlcpcb.kicad_dru` — from Cimos/KiCad-DesignRules (MIT) — Pitfall 6 cleanest source
  - `aisler_2layer.kicad_dru`, `aisler_4layer.kicad_dru`, `aisler_6layer.kicad_dru`, `aisler_8layer.kicad_dru` — from AislerHQ/aisler-support
  - `oshpark.kicad_dru` — authored from published numeric specs
  - `advanced_circuits.kicad_dru` — authored from published numeric specs
  - `generic.kicad_dru` — conservative defaults for unknown vendors
- Add source attribution header comments to each profile (repo URL, license, last-verified date) — DRC-06, Pitfall 6
- Extend `dfm/profiles.py` `ManufacturerProfile` with `drc_rules_path: Path | None` field — DRC-05
- `drc_vendor` operation: resolve profile path → `kicad-cli pcb drc --custom-rules <profile>` → parse report → return `DrcResult`
- List vendor profiles query operation (capabilities + profile path) — DRC-08

**Success Criteria** (what must be TRUE):
1. User runs `drc_vendor(vendor="pcbway", file="board.kicad_pcb")` and gets vendor-specific DRC violations (annular ring, track width, clearance) against PCBWay's current published limits
2. System ships 5+ verified vendor profiles (PCBWay, JLCPCB, AISLER 2/4/6/8L, OSH Park, Advanced Circuits, generic) — each with source attribution in header comments
3. User runs `drc_vendor(vendor="generic")` against an unknown vendor and gets conservative DRC results
4. User can list available vendor profiles and see each profile's capabilities (layer count, min track, min clearance, source)

**Plans:** 1/1 plans complete

---

### Phase 207: Versioned Build System

**Goal:** User can create a versioned build that snapshots source files, records git SHA + board revision, and serializes a manifest with SHA256-hashed artifacts to disk

**Depends on:** Phase 205 (needs `title_block` rev field for `board_rev`)

**Requirements:** BUILD-01, BUILD-02, BUILD-03, BUILD-04, BUILD-05, BUILD-06, BUILD-07, BUILD-08, BUILD-09, BUILD-10

**Key work:**
- `Build` record dataclass in `manufacturing/build.py` (frozen; fields: `build_id` UUID, `board_rev`, `source_files` tuple, `git_sha`, `created_at`, `status: BuildStatus`, `artifacts` tuple, `manifest_path`, `build_dir`) — BUILD-02
- `BuildStatus` lifecycle: `draft → validated → exported → handed_off` with clear transitions — BUILD-03
- Promote `validation/gates/manufacturing_manifest.py` `ManufacturingManifest`/`ManufacturingArtifact` with serialization (`to_json()`, `save()`) — BUILD-05
- `build_create` operation: snapshot source files → run existing `ManufacturingReadinessGate` (5 checks) → record git SHA + board rev → create build dir. Build is NOT created if validation fails — BUILD-01, BUILD-04
- Build directory structure: `builds/v{rev}_{timestamp}/` — BUILD-06
- `.gitignore` entry for `builds/` — BUILD-09, Pitfall 4
- `build_list` operation: list all builds for a project — BUILD-07
- `build_show` operation: view build details (manifest, artifacts, validation status) — BUILD-08
- Build diffing: diff two builds (source diffs, artifact diffs, validation status changes) — BUILD-10
- Add `build_create` and `build_handoff_export` to `CROSS_FILE_OP_TYPES` in `ops/execution.py` — Integration Pitfall IP-4

**Success Criteria** (what must be TRUE):
1. User runs `build_create` on a clean board and gets a build record with `build_id`, `board_rev` (from `title_block`), `git_sha` (HEAD), and timestamp; the build directory `builds/v{rev}_{timestamp}/` is created
2. User runs `build_create` on a board that fails `ManufacturingReadinessGate` and gets a clear validation error — NO build is created (no partial state)
3. `manifest.json` is serialized to disk in the build directory with SHA256 hashes for each artifact; reloading it via `build_show` reproduces the build record exactly
4. User runs `build_list` and sees all builds for the project with status (draft/validated/exported/handed_off)
5. `builds/` directory is in `.gitignore` — build artifacts do not appear in `git status`

**Plans:** 1/1 plans complete

---

### Phase 208: Manufacturer Handoff Package

**Goal:** One call (`build_handoff_export`) produces a complete zip bundle with all manufacturing artifacts + readme + manifest, with pre-handoff validation preventing incomplete bundles

**Depends on:** Phase 205 (BoardSpec + title_block), Phase 206 (vendor DRC profiles), Phase 207 (build record + manifest)

**Requirements:** HANDOFF-01, HANDOFF-02, HANDOFF-03, HANDOFF-04, HANDOFF-05, HANDOFF-06, HANDOFF-07, HANDOFF-08, HANDOFF-09

**Key work:**
- `manufacturing/handoff.py` orchestrator — the one-call "prepare for manufacturing" command:
  1. Read `BoardSpec` + `title_block` (board rev, finish, colors)
  2. Run existing `ManufacturingReadinessGate` (5 checks) — FAIL → no build, error returned
  3. Run vendor DRC (Phase 206 `drc_vendor` flow) — FAIL → DRC violations returned, no build
  4. Run ERC clean check — FAIL → no build
  5. Create build directory: `builds/v{rev}_{timestamp}/`
  6. Run all exports via existing `export/` wrappers: Gerbers (`export/gerber.py`), drill, BOM (`export/bom.py`), pick-and-place (`export/general.py`), STEP, netlist, schematic PDF, PCB PDF
  7. Build manifest with SHA256 hashes (existing `ManufacturingArtifact` pattern)
  8. Generate `readme.md` from `BoardSpec` + board stats + DRC/ERC results
  9. Zip everything into `handoff.zip` (streaming zip creation for large STEP files — Pitfall 7)
  10. Serialize `manifest.json`
  11. Return `Build` record with all artifact paths
- Generalize `export_jlcpcb_bom` into profile-driven formatter — `export_bom(profile=...)` with JLCPCB as one profile, NOT direct hard-coded calls (Pitfall 3, HANDOFF-05)
- Vendor output profiles: `ManufacturerProfile` extension includes output format spec (BOM columns, file naming, zip structure) — default to generic format when no vendor specified
- Pre-handoff validation gate: DRC clean + ERC clean + manifest complete before bundling — no zip created if validation fails (HANDOFF-06, Pitfall 5)
- STEP/render inclusion optional via `BoardSpec` or vendor profile (bare-board orders skip STEP) — HANDOFF-07
- Vendor-specific handoff: `build_handoff_export(vendor="jlcpcb")` produces JLCPCB-formatted BOM/CPL with correct columns (HANDOFF-08)
- DRC/ERC validation results included in manifest as proof of manufacturability (HANDOFF-09)

**Success Criteria** (what must be TRUE):
1. User runs `build_handoff_export(file="board.kicad_pcb")` and gets a single `handoff.zip` containing Gerbers, drill, BOM, pick-and-place, STEP (if configured), netlist, schematic PDF, PCB PDF, `manifest.json`, and `readme.md`
2. `readme.md` includes everything a manufacturer needs: board name, revision, date, layer count, dimensions, surface finish, copper weight, soldermask/silkscreen color, impedance requirements, designer contact
3. Pre-handoff validation gate blocks incomplete bundles — if DRC, ERC, or manifest validation fails, NO zip is created and the user gets a clear error listing what failed
4. `build_handoff_export(vendor="jlcpcb")` produces a JLCPCB-formatted bundle (BOM columns, CPL file naming) via the profile-driven formatter — no hard-coded `export_jlcpcb_bom` calls in the handoff path
5. Bare-board orders (`BoardSpec` or vendor profile marks STEP as optional) produce a bundle without the STEP file

**Plans:** 1/1 plans complete

---

### Phase 209: Crossfile + MCP Integration

**Goal:** All new operations are callable via MCP and CLI; builds are project-scoped; `ManufacturerClient` ABC is defined for future API adapters

**Depends on:** Phase 207 (builds), Phase 208 (handoff). Phase 206 (DRC) is consumed but not a hard dependency for the integration wiring.

**Requirements:** INTEG-01, INTEG-02, INTEG-03, INTEG-04, INTEG-05, INTEG-06

**Key work:**
- MCP auto-exposure: new ops appear automatically via `_generate_operation_tools()` in `mcp/edit_server.py` (free — no manual MCP wiring) — INTEG-01
- CLI subcommands: `build`, `handoff`, `drc-vendor`, `board-metadata` — INTEG-02
- Extend `crossfile/project_context.py` `ProjectContext` to discover `builds/` directories and `.kicad_build_spec.json` sidecars — INTEG-03
- Builds are project-scoped: each project has its own `builds/` directory under the project root — INTEG-04
- `ManufacturerClient` ABC in `manufacturing/` (interface only — `quote()`, `place_order()`, `get_status()` abstract methods). NO adapter implementations — INTEG-05, Pitfall 8 scope-creep prevention
- Update `tests/test_registry.py:26` count assertion (currently `== 142`) for new ops — Integration Pitfall IP-1
- `validate_registry_completeness()` passes with all new ops added (registry + schema union in sync) — INTEG-06, Integration Pitfall IP-2
- Merge `_MANUFACTURING_HANDLERS` in `ops/handlers/__init__.py` (follow `_BOM_HANDLERS` pattern) — Integration Pitfall IP-3

**Success Criteria** (what must be TRUE):
1. All new operations (`read_board_metadata`, `set_board_metadata`, `set_board_revision`, `drc_vendor`, `build_create`, `build_list`, `build_show`, `build_handoff_export`, vendor profile list) are callable via MCP tools and CLI subcommands
2. `ProjectContext` discovers a project's `builds/` directory and `.kicad_build_spec.json` sidecar; build operations resolve to the correct project scope
3. `ManufacturerClient` ABC is defined with `quote()`, `place_order()`, `get_status()` abstract methods — importing it does not require any network libraries or credentials
4. Operations registry count assertion and `validate_registry_completeness()` pass with all new ops added (registry, schema union, and handlers in sync)

**Plans:** 1/1 plans complete

---

### Phase 210: Vendor API Adapters (DEFERRED)

**Status:** **DEFERRED** — Placeholder phase. Activated in v7.1+ when API credentials are obtained. Do NOT plan implementation details in v7.0.

**Goal (when activated):** Implement `ManufacturerClient` adapters for vendors with APIs (quote/order/status), enabling programmatic quote comparison and order placement

**Depends on:** Phase 209 (needs `ManufacturerClient` ABC). Standalone for v7.0 (no implementation work).

**Requirements:** FUTURE-API-01, FUTURE-API-02, FUTURE-API-03, FUTURE-API-04, FUTURE-API-05

**Deferred rationale:** API keys are partner-gated (PCBWay: anson@pcbway.com) or account-gated (MacroFab: factory.macrofab.com). Endpoint docs for MacroFab are behind an authenticated portal. No Python libraries exist for any of these — kicad-agent would write the first wrappers. The handoff package (Phase 208) is the universal fallback that works with all vendors, including those with APIs. API adapters are accelerators, not requirements.

**Scope guard (Pitfall 8):** If this phase is ever activated, scope it to QUOTE ONLY first (no order placement) — quoting is read-only and safe; ordering has financial consequences.

**Success Criteria:** N/A (deferred — no implementation in v7.0)

**Plans:** 0 plans (deferred)

---

## Dependency Graph

```
Phase 205 (Metadata) ──┬──→ Phase 207 (Builds) ──→ Phase 208 (Handoff) ──→ Phase 209 (Integration)
                        │                                 ↑
Phase 206 (DRC) ────────┴─────────────────────────────────┘
                                                                                  │
                                                                         Phase 210 (API) — DEFERRED
```

**Hard dependencies:**
- Phase 207 depends on Phase 205 (needs `title_block` rev field for `board_rev`)
- Phase 208 depends on Phase 205 (BoardSpec + title_block), Phase 206 (vendor DRC), Phase 207 (build record + manifest)
- Phase 209 depends on Phase 207 + Phase 208 (integration layer over builds + handoff)
- Phase 206 feeds Phase 208 (vendor DRC profiles consumed by handoff validation gate)

**Parallel tracks:**
- Phase 205 (Metadata) and Phase 206 (DRC) are independent — can be worked in parallel
- Phase 210 is standalone (DEFERRED — no implementation work in v7.0)

## Track Overview

**Phase 205: Board Metadata Foundation** — `title_block` parse/write + `BoardSpec` model + sidecar JSON. Foundation for versioning.
**Phase 206: Vendor DRC Profiles** — `.kicad_dru` files for 5+ vendors + `drc_vendor` op. Pre-flight DRC gate.
**Phase 207: Versioned Build System** — `Build` record + serialized manifest + build ops + diffing. Provenance tracking.
**Phase 208: Manufacturer Handoff Package** — Full export orchestration → zip + readme + manifest. Universal vendor-neutral path.
**Phase 209: Crossfile + MCP Integration** — MCP/CLI exposure + `ProjectContext` + `ManufacturerClient` ABC.
**Phase 210: Vendor API Adapters (DEFERRED)** — PCBWay/MacroFab/JLCPCB adapters. Placeholder only in v7.0.

**Critical Path:** 205 → 207 → 208 → 209 (206 feeds 208 in parallel)

## Pitfall Addressed by Phase

- Phase 205: title_block parsing fragility (Pitfall 2)
- Phase 206: Stale DRC values (Pitfall 1) + profile licensing/attribution (Pitfall 6)
- Phase 207: Build dir git pollution (Pitfall 4) + manifest false confidence (Pitfall 5, build side)
- Phase 208: Vendor lock-in via hard-coded formatting (Pitfall 3) + manifest false confidence (Pitfall 5, handoff side) + large file handling in zips (Pitfall 7)
- Phase 209: Integration pitfalls IP-1 (registry count), IP-2 (schema union drift), IP-3 (handler merge), IP-4 (CROSS_FILE_OP_TYPES)
- Phase 210: API adapter scope creep (Pitfall 8) — guarded by DEFERRED status + quote-only scope rule

## Requirement Coverage

| Category | REQ-IDs | Phase | Count |
|----------|---------|-------|-------|
| Board Metadata | META-01..07 | 205 | 7 |
| Vendor DRC Profiles | DRC-01..08 | 206 | 8 |
| Versioned Build System | BUILD-01..10 | 207 | 10 |
| Manufacturer Handoff | HANDOFF-01..09 | 208 | 9 |
| Integration | INTEG-01..06 | 209 | 6 |
| Vendor API Adapters (DEFERRED) | FUTURE-API-01..05 | 210 | 5 |
| **Active Total** | | | **40** |
| **Deferred Total** | | | **5** |
| **Grand Total** | | | **45** |

**Coverage:** 100% — all 40 active requirements (META-01..07, DRC-01..08, BUILD-01..10, HANDOFF-01..09, INTEG-01..06) map to an active phase (205-209). All 5 future requirements (FUTURE-API-01..05) map to deferred Phase 210.

## Progress Tracking

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 205. Board Metadata Foundation | 1/1 | Complete    | 2026-07-10 |
| 206. Vendor DRC Profiles | 1/1 | Complete    | 2026-07-10 |
| 207. Versioned Build System | 1/1 | Complete    | 2026-07-11 |
| 208. Manufacturer Handoff Package | 1/1 | Complete    | 2026-07-11 |
| 209. Crossfile + MCP Integration | 1/1 | Complete    | 2026-07-11 |
| 210. Vendor API Adapters (DEFERRED) | 0/0 | Deferred | - |
| 230. Train Both Models | 0/? | In Progress | (Vast.ai training, bead kicad-agent-h7q) |
| 231. Wire Swift ERC as Primary Validation | 1/1 | Complete    | 2026-07-14 |
| 232. Spatial Index for DRC Performance | 1/1 | Complete    | 2026-07-14 |
| 233. Swift Schematic SVG Renderer | 1/1 | Complete    | 2026-07-14 |
| 234A. Corpus Acquisition + Parity Driver | 0/1 | Pending | - |
| 234B. Parity Execution + Report + Fix | 0/1 | Pending | - |
| 235. Complex Op Implementations | 1/1 | Complete    | 2026-07-14 |
| 236. Vision Input (Camera → Schematic) | 0/? | Pending | - |

**Total:** 5 active phases (205-209), 40 active requirements mapped, 100% coverage. v11.0 audit 2026-07-14: 231, 232, 233 already shipped (rolled into native-engine effort); 230 in flight; 234/235/236 still pending.

---

# v11.0 — Better, Faster, Stronger

7 Epics (Phase 230-236). See `.planning/ROADMAP-v11.md` for full scope.

### Phase 230: Train Both Models
- Re-train 12B adapter on full 108K corpus (Vast.ai, ~$3)
- Train 4B iOS adapter (Vast.ai, ~$2)
- Upload both to HuggingFace
- Update ModelDownloader to select model by device capability

### Phase 231: Wire Swift ERC as Primary Validation
- ValidationPanel calls `NativeERC.run()` directly (no IPC)
- Python `native_check` stays as macOS-only fallback
- ValidationManager updated to call Swift engine first
- Goal: close the daemon round-trip for validation; lower latency; remove IPC failure mode
- Dependency: Phase 218 (Native ERC engine) — COMPLETE

### Phase 232: Spatial Index for DRC Performance
- Wire `SpatialHash` into `NativeDRC.checkCopperSpacing()`
- Replace O(n²) pairwise with O(n log n) spatial query
- Benchmark on large boards (1000+ segments)

### Phase 233: Swift Schematic SVG Renderer
- New `SwiftSVGRenderer` conforming to `PreviewRenderer`
- Render wires, pins, labels, symbols as SVG from `SchematicIR`
- Works on iOS (no daemon needed)
- Wire into `LiquidGlassShell.previewRenderer`

### Phase 234A: Corpus Acquisition + Parity Driver
- Stage 1000-schematic corpus via `CorpusCurator` (accept what it returns, target ≥100)
- Implement Python parity driver (`scripts/batch_erc_parity.py`)
- Smoke test on 3 schematics, write handoff artifacts for 234B
- See: `.planning/phases/234a-corpus-and-driver/`

### Phase 234B: Parity Execution + Report + Fix
- Run full batch on corpus from 234A
- Generate parity report (pass rate, FP/FN counts, per-check breakdown)
- Fix root-cause discrepancies (≥5-schematic drift threshold, 2-iteration cap)
- See: `.planning/phases/234b-execution-and-fix/`

### Phase 235: Complex Op Implementations
- Fully implement the 78 scaffold ops in `VoltaEngineRemaining.swift`
- Priority: `safe_sync_pcb_from_schematic`, `auto_route`, `fill_zones`, `match_lengths`, `place_components_sch`
- Each op gets real algorithm implementation
- **Status re-opened 2026-07-14:** Marked Complete but the priority ops remain stubs. `safe_sync_pcb_from_schematic` (line 933-942), `fix_net_short` (line 862-868), `fix_pin_type_mismatches` (line 870-876) all return placeholder messages. Re-opened and split into dedicated phases:
  - Phase 237: `safe_sync_pcb_from_schematic` real impl
  - Phase 243: fix ops (fix_net_short, fix_pin_type_mismatches, fix_shorted_nets, strip_shorts) real impl
- Remaining 74 ops in VoltaEngineRemaining.swift verified real and unchanged

### Phase 236: Vision Input (Camera → Schematic)
- Photo picker for schematic/breadboard images
- Wire `KCAttachment` images into MLX vision pipeline
- "Snap photo → generate SKiDL" feature
- The adapter was trained multimodal — this activates that capability

---

## v11.0 — Gap-Closure Phases (237-244)

Created 2026-07-14 to close the 8 high-priority gaps identified in `docs/GAP-ANALYSIS-CURRENT.md` that the v11.0 phases (230-236) and v7.0 phases (205-210) did not address. Ordered roughly by user-impact priority.

### Phase 237: Real safe_sync_pcb_from_schematic
- Replace the stub return-message with a real diff-and-replay algorithm
- `SchematicPcbDiffer` (matches components by ref, emits add/remove/move/update ops)
- `SchematicPcbSync` (journals sync as a single transaction; one-shot undo)
- Closes gap A2 — the iterate loop is currently broken
- Plan: `.planning/phases/237-safe-sync-pcb-from-schematic/237-01-PLAN.md`

### Phase 238: Real preview wire-up
- SchematicPreviewView and PCBPreviewView currently render mock data
- Wire to real `SchematicIR` / `PCBIR` via `SwiftSVGRenderer`
- PCB option: extend renderer with PCB → SVG path (preferred) OR shell out to `kicad-cli pcb render`
- Add 250ms debounced file watcher for live updates
- Closes gaps A4 + B8 — App Store inline-preview claim becomes true
- Plan: `.planning/phases/238-real-preview-wire-up/238-01-PLAN.md`

### Phase 239: Image attachment UI wiring
- Chat compose bar gets paperclip button + drop target + paste handler
- `RouterStreamProvider.buildKCPrompt` reads `ImageAttachment.url` bytes, constructs `KCAttachment`
- 10MB size limit, 2048px auto-compression, EXIF strip
- Closes gaps A5 + E1 — vision-capable model gets the input
- Plan: `.planning/phases/239-image-attachment-ui/239-01-PLAN.md`

### Phase 240: Volta op registry tests
- Coverage test: iterate `VoltaOpRegistry.allOpTypes`, assert every op has a test
- 20+ `.kicad_sch` fixtures covering common topologies
- Property tests for read-only ops; round-trip tests for write ops
- CI gate blocks merge if coverage < 80%
- Closes gap A1 — the 268-op registry currently has zero tests
- Plan: `.planning/phases/240-volta-op-registry-tests/240-01-PLAN.md`

### Phase 241: Streaming chat pipeline E2E test
- NoopChatStream → RouterStreamProvider → ContentChunker → MessageBubbleView, end-to-end
- Canned fixtures: echo response (regression for the echo bug), clean response, loop response
- Verify echo stripping, boundary chunking, loop collapse, cost callback
- Closes gap A8 — exactly the gap that allowed the echo bug this session fixed
- Plan: `.planning/phases/241-streaming-chat-e2e-test/241-01-PLAN.md`

### Phase 242: First-run onboarding
- 3-step guided tour: pick starter (LED blinker / ESP32 / op-amp), run a chat, view result
- SwiftData-persisted state (dismissed, completed, currentStep)
- Skip button always visible; returning user with project skips the tour
- Delete orphaned `KiCadInstallView.swift` (Phase 220 already removed the install path)
- Closes gap F3 — first-time users currently land on a blank sidebar
- Plan: `.planning/phases/242-first-run-onboarding/242-01-PLAN.md`

### Phase 243: Real fix op implementations
- Replace `fix_net_short` and `fix_pin_type_mismatches` stub return-messages
- New `SchematicNets.swift` utility: findShorts, findPinTypeMismatches, findShortedNets, isInPinTypeMatrix
- Verify + harden `fix_shorted_nets` and `strip_shorts` (currently delegate to `BreakWireShortsGenOp`)
- All four ops journaled as transactions (one-shot undo)
- Closes gap A3 — same paper-completion as Phase 235
- Plan: `.planning/phases/243-fix-ops-real-implementations/243-01-PLAN.md`

### Phase 244: Fastlane notarization execute
- Phase 203 (203-01-PLAN.md, 2026-07-07) shipped a comprehensive plan but was never executed
- Execute the plan: match, Appfile, Fastfile, snapshot, build_daemon, CI wiring
- One command: `fastlane mac beta` → build, sign, notarize, upload to TestFlight
- PyInstaller daemon hardened-runtime signed alongside the app
- Closes gap F2 — no notarized build artifact exists for v6
- Plan: `.planning/phases/244-fastlane-notarization-execute/244-01-PLAN.md`

### Phase 245: Wire Volta v2 LoRA adapter into macOS app + publish to HF
- Replace `MLXLocalProvider` placeholder with real PEFT inference on `google/gemma-4-12b-it`
- Adapter: rank=64, alpha=128, dropout=0.05, 7 target modules, peft 0.19.1
- Trained 3000 steps on 48.5M tokens (loss 0.0288, accuracy 98.66%)
- Source adapter at `/Volumes/Storage/models/kicad-agent/adapters/volta-12b-v2/` (5.0 GB, SHA256 cbc121cc… verified)
- **Publish to HF**: create `bretbouchard/volta-pcb-adapter-v2` repo + upload the 5.0 GB so the app's `ModelDownloader.adapterRepo` can fetch it
- **Flip the swap gate**: change `ModelDownloader.swift:65` from `volta-pcb-adapter-v1` → `volta-pcb-adapter-v2`. Remove the v1 smoke-test path entirely (no value keeping it)
- Load via `PeftModel.from_pretrained(base, adapter_path)` in Python daemon; bridge to Swift via existing `LocalProvider` protocol
- `ProviderRegistry` resolves `volta-pcb-v2` as the local provider, served through `KiCadModelRouter`
- Preserve the streaming + multi-turn contract that Phase 175/241 built (no regressions to the E2E test)
- **Failure guard**: if HF repo is down or 404s, download sheet must show a clear "v2 not yet available — check status" state, not silently fall back to v1 (which no longer exists)
- Plan: `.planning/phases/245-wire-volta-v2-adapter/245-01-PLAN.md`
- **Status:** Complete (2026-07-15) — 2 commits (942dcf0, ca6ddb1), 8/8 must-haves passed, 0 P0/P1 Council findings

### Phase 246: Python eval harness for Volta v2 adapter
- Load `bretbouchard/volta-pcb-adapter-v2` directly via `peft + transformers` (Python) to measure PCB generation quality against a held-out test set
- Test set: ≥50 NL circuit intents → SKiDL or schematic output, scored on:
  - ERC pass rate (skidl 2.2.3 ERC, zero errors)
  - Syntactic correctness (parses as valid SKiDL or netlist)
  - Schema completeness (has all required components for the intent)
  - Reference fidelity vs hand-crafted gold answers (BLEU/ROUGE + semantic)
- Use the same test set as Phase 234A corpus (or carve out a 50-sample holdout)
- Output: `output/volta-v2-eval-report.json` + `output/volta-v2-eval-summary.md` with pass/fail per sample + aggregate score
- CI gate: score must be ≥ baseline (TBD — current Phase 230 v2 metrics set the floor)
- Plan: `.planning/phases/246-volta-v2-eval-harness/246-01-PLAN.md`

### Phase 247: Gap closure against docs/GAP-ANALYSIS-CURRENT.md
- Read `docs/GAP-ANALYSIS-CURRENT.md` and triage all open gaps
- Apply the four-state resolution taxonomy (IMPLEMENTED / ADDED-AS-PHASE / SUPERSEDED-BY-ALTERNATIVE / DEFERRED-TO-NAMED-TARGET) to each gap
- Includes: MLXLLM `TODO(245)` LoRA-load API gap (the only intentional degradation left in Phase 245)
- P0/P1 gaps must be IMPLEMENTED in this phase or ADDED-AS-PHASE; defer only with named trigger
- Verifier re-runs after closure; updated gap file goes to `docs/GAP-ANALYSIS-CURRENT.md` with status column
- Plan: `.planning/phases/247-gap-closure-vol11/247-01-PLAN.md`

---

## v11.0 Execution Order

User's instruction: "move to phase 234a and all other phases." Suggested order:

1. **Phase 230** (Train Both Models) — in flight, ~1h 26m to step 3000
2. **Phase 234A** (Corpus Acquisition + Parity Driver) — plan ready, next concrete deliverable
3. **Phase 234B** (Parity Execution + Report + Fix) — depends on 234A
4. **Phase 237** (safe_sync_pcb_from_schematic) — P0 gap, restores iterate loop
5. **Phase 238** (real preview wire-up) — P0, App Store claim becomes true
6. **Phase 239** (image attachment UI) — P1, vision input path
7. **Phase 241** (streaming chat E2E) — P0, regression guard for the bug just fixed
8. **Phase 240** (op registry tests) — P0, prevents silent regressions
9. **Phase 243** (fix ops real impl) — P1, paired with 237
10. **Phase 242** (onboarding) — P1, first-impressions
11. **Phase 244** (fastlane notarization) — P0, ships v6 to App Store
12. **Phase 245** (wire Volta v2 LoRA adapter) — ✅ DONE 2026-07-15 — enables real local PCB inference, prerequisite for eval harness
13. **Phase 246** (Python eval harness) — ✅ DONE 2026-07-15 — 32/32 tests, Council APPROVED, 10/10 must-haves. E2E inference pending vast.ai GPU.
14. **Phase 247** (gap closure) — after eval, addresses remaining gaps + MLXLLM TODO
15. **Phase 236** (Vision Input camera) — L effort, do last
16. **Phase 235** (Complex Op Implementations) — already partially shipped, audit + close the 4 known stubs via 237/243

---

**Last updated:** 2026-07-14 — v7.0 roadmap created. Phase numbering continues from v6.0's last phase (204).
v11.0 phases (230-236) appended 2026-07-14 to seed Phase 231 planning.
Gap-closure phases (237-244) added 2026-07-14 to track the 8 high-priority gaps from docs/GAP-ANALYSIS-CURRENT.md. Phase 235 re-opened as partial.
Phase 245 (wire Volta v2 LoRA adapter) added 2026-07-14 after training completed: step 3000, loss 0.0288, accuracy 98.66%. Adapter downloaded and SHA256-verified; instance 44774137 destroyed. Phase 245 marked complete 2026-07-15: 2 commits (942dcf0, ca6ddb1), HF repo live at bretbouchard/volta-pcb-adapter-v2, 8/8 must-haves passed.
Phases 246 (Python eval harness) + 247 (gap closure) added 2026-07-15 per user instruction "eval first, then gaps". Eval harness measures v2 quality on held-out test set; gap closure addresses remaining docs/GAP-ANALYSIS-CURRENT.md items including MLXLLM TODO(245).

