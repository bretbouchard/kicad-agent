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
- [ ] **Phase 208: Manufacturer Handoff Package** — Full export orchestration, zip bundle + readme, vendor output profiles, pre-handoff validation gate
- [ ] **Phase 209: Crossfile + MCP Integration** — MCP auto-exposure, CLI subcommands, `ProjectContext` discovery, `ManufacturerClient` ABC
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

**Plans:** 1 plan

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

**Plans:** 1 plan

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
| 208. Manufacturer Handoff Package | 0/1 | Not started | - |
| 209. Crossfile + MCP Integration | 0/1 | Not started | - |
| 210. Vendor API Adapters (DEFERRED) | 0/0 | Deferred | - |

**Total:** 5 active phases (205-209), 40 active requirements mapped, 100% coverage, **0 plans written**

---

**Last updated:** 2026-07-10 — v7.0 roadmap created. Phase numbering continues from v6.0's last phase (204).
