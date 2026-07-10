# Milestone v7.0 Requirements — Vendor-Neutral Manufacturing Layer

**Goal:** Send boards to ANY manufacturer — free DRC pre-flight for all vendors, universal versioned handoff package, and (deferred) opt-in quote/order APIs. No vendor lock-in.

## v1.0 Requirements

### Category 1: Board Metadata Foundation (META)

- [ ] **META-01**: User can read board revision, title, date, and company from a `.kicad_pcb` file's `title_block` via the `read_board_metadata` operation
- [ ] **META-02**: User can set board revision (the version number that links to a specific build) via `set_board_revision` operation, which writes the `rev` field in `title_block`
- [ ] **META-03**: User can set full board metadata (title, date, company, comments) via `set_board_metadata` operation
- [ ] **META-04**: User can define manufacturing specs (surface finish, copper weight, soldermask color, silkscreen color) via a `BoardSpec` model persisted as a sidecar JSON file (`.kicad_build_spec.json`)
- [ ] **META-05**: User can specify controlled impedance requirements (which nets, target ohms, reference layer) as part of `BoardSpec`
- [ ] **META-06**: title_block round-trips correctly — parse → modify → serialize produces valid KiCad files with no data loss (follows existing immutability + round-trip fidelity patterns)
- [ ] **META-07**: Parsing handles KiCad 10 quoting variations (quoted and unquoted fields, comments with special characters)

### Category 2: Vendor DRC Profiles (DRC)

- [ ] **DRC-01**: User can run DRC against a specific vendor's manufacturing limits via `drc_vendor` operation (e.g., `drc_vendor(vendor="pcbway")`)
- [ ] **DRC-02**: System ships verified `.kicad_dru` files for PCBWay, JLCPCB, AISLER (2/4/6/8-layer variants)
- [ ] **DRC-03**: User can run DRC against OSH Park and Advanced Circuits profiles (authored from their published numeric specs)
- [ ] **DRC-04**: User can run DRC against a generic conservative profile when vendor is unknown or unspecified
- [ ] **DRC-05**: `ManufacturerProfile` (dfm/profiles.py) is extended with a `drc_rules_path` field linking to the `.kicad_dru` file
- [ ] **DRC-06**: DRC profile files include source attribution (repo URL, license, last-verified date) in header comments
- [ ] **DRC-07**: PCBWay profile updated to current capabilities (annular ring 0.15mm, not the stale 0.25mm from 2023)
- [ ] **DRC-08**: User can list available vendor profiles and their capabilities via a query operation

### Category 3: Versioned Build System (BUILD)

- [ ] **BUILD-01**: User can create a versioned build via `build_create` operation that snapshots source files, records git SHA, and captures board revision
- [ ] **BUILD-02**: Build record includes: build_id (UUID), board_rev, source file paths, git SHA, timestamp, status, artifacts list
- [ ] **BUILD-03**: Build status lifecycle: draft → validated → exported → handed_off (with clear transitions)
- [ ] **BUILD-04**: Build creation runs `ManufacturingReadinessGate` (existing 5-check gate) — build is not created if validation fails
- [ ] **BUILD-05**: Manifest is serialized to disk as `manifest.json` with SHA256-hashed artifacts (promotes existing in-memory `ManufacturingManifest`)
- [ ] **BUILD-06**: Build artifacts stored in structured directory: `builds/v{rev}_{timestamp}/`
- [ ] **BUILD-07**: User can list all builds for a project via `build_list` operation
- [ ] **BUILD-08**: User can view build details (manifest, artifacts, validation status) via `build_show` operation
- [ ] **BUILD-09**: `builds/` directory is added to `.gitignore` (artifacts are not committed)
- [ ] **BUILD-10**: User can diff two builds to see what changed (source diffs, artifact diffs, validation status changes)

### Category 4: Manufacturer Handoff Package (HANDOFF)

- [ ] **HANDOFF-01**: User can generate a complete manufacturing handoff package via `build_handoff_export` operation — one call produces everything
- [ ] **HANDOFF-02**: Handoff package includes all manufacturable artifacts: Gerbers, drill, BOM, pick-and-place, STEP, netlist, schematic PDF, PCB PDF
- [ ] **HANDOFF-03**: Handoff package is bundled into a single zip file (`handoff.zip`) with all artifacts + manifest + readme
- [ ] **HANDOFF-04**: Readme includes all information a manufacturer needs: board name, revision, date, layer count, dimensions, surface finish, copper weight, soldermask/silkscreen color, impedance requirements, designer contact
- [ ] **HANDOFF-05**: Vendor output profiles drive formatting (BOM columns, file naming, zip structure) — replaces hard-coded `export_jlcpcb_bom` with profile-driven formatter
- [ ] **HANDOFF-06**: Pre-handoff validation: DRC clean + ERC clean + manifest complete before bundling — no zip created if validation fails
- [ ] **HANDOFF-07**: STEP file and renders are optional (configurable via BoardSpec or vendor profile — bare-board orders don't need STEP)
- [ ] **HANDOFF-08**: User can generate vendor-specific handoff (e.g., `build_handoff_export(vendor="jlcpcb")` produces JLCPCB-formatted BOM/CPL with correct columns)
- [ ] **HANDOFF-09**: Handoff package includes DRC/ERC validation results in the manifest (proof of manufacturability)

### Category 5: Integration (INTEG)

- [ ] **INTEG-01**: All new operations are exposed via MCP (auto-generated from Operation union — no manual MCP wiring)
- [ ] **INTEG-02**: All new operations are exposed via CLI subcommands (build, handoff, drc-vendor, board-metadata)
- [ ] **INTEG-03**: `ProjectContext` discovers `builds/` directories and `.kicad_build_spec.json` sidecars
- [ ] **INTEG-04**: Builds are project-scoped (each project has its own `builds/` directory)
- [ ] **INTEG-05**: `ManufacturerClient` ABC is defined (interface only — `quote()`, `place_order()`, `get_status()` methods) to enable future API adapters without breaking changes
- [ ] **INTEG-06**: Operations registry count assertion and schema completeness validation pass with all new ops added

---

## Future Requirements (Deferred)

### Category 6: Vendor API Adapters (DEFERRED to v7.1+)

- [ ] **FUTURE-API-01**: PCBWay Partner API adapter (quote, place order, get status) — requires partner API key from anson@pcbway.com
- [ ] **FUTURE-API-02**: MacroFab Cloud API v2 adapter (quote, place order, inventory) — requires account + API key from factory.macrofab.com
- [ ] **FUTURE-API-03**: JLCPCB Online API adapter (quote, order, parts via LCSC) — self-serve application
- [ ] **FUTURE-API-04**: Quote comparison across multiple vendors
- [ ] **FUTURE-API-05**: Order tracking with status notifications

## Out of Scope

- **Auto-routing** — handled by routing-rick agent separately
- **Direct GUI integration** — CLI and MCP interface only
- **KiCad 8.x/9.x backward compatibility** — targeting 10+ only
- **Full API adapter implementation** — deferred to v7.1 (the `ManufacturerClient` ABC is defined in v7.0 as interface-only; adapters are future work)
- **Online Gerber viewer** — web-only tools are not integrated; the handoff package produces standard Gerbers viewable in any tool
- **Component sourcing API** — PCBWay/MacroFab parts sourcing is manual; use LCSC/JLC for programmatic parts (existing `kicad-component-search` covers this)

## Traceability

Maps each REQ-ID to a phase number. 100% coverage — all 40 active requirements map to an active phase (205-209); all 5 future requirements map to deferred Phase 210.

| REQ-ID | Phase | Phase Name |
|--------|-------|------------|
| META-01 | 205 | Board Metadata Foundation |
| META-02 | 205 | Board Metadata Foundation |
| META-03 | 205 | Board Metadata Foundation |
| META-04 | 205 | Board Metadata Foundation |
| META-05 | 205 | Board Metadata Foundation |
| META-06 | 205 | Board Metadata Foundation |
| META-07 | 205 | Board Metadata Foundation |
| DRC-01 | 206 | Vendor DRC Profiles |
| DRC-02 | 206 | Vendor DRC Profiles |
| DRC-03 | 206 | Vendor DRC Profiles |
| DRC-04 | 206 | Vendor DRC Profiles |
| DRC-05 | 206 | Vendor DRC Profiles |
| DRC-06 | 206 | Vendor DRC Profiles |
| DRC-07 | 206 | Vendor DRC Profiles |
| DRC-08 | 206 | Vendor DRC Profiles |
| BUILD-01 | 207 | Versioned Build System |
| BUILD-02 | 207 | Versioned Build System |
| BUILD-03 | 207 | Versioned Build System |
| BUILD-04 | 207 | Versioned Build System |
| BUILD-05 | 207 | Versioned Build System |
| BUILD-06 | 207 | Versioned Build System |
| BUILD-07 | 207 | Versioned Build System |
| BUILD-08 | 207 | Versioned Build System |
| BUILD-09 | 207 | Versioned Build System |
| BUILD-10 | 207 | Versioned Build System |
| HANDOFF-01 | 208 | Manufacturer Handoff Package |
| HANDOFF-02 | 208 | Manufacturer Handoff Package |
| HANDOFF-03 | 208 | Manufacturer Handoff Package |
| HANDOFF-04 | 208 | Manufacturer Handoff Package |
| HANDOFF-05 | 208 | Manufacturer Handoff Package |
| HANDOFF-06 | 208 | Manufacturer Handoff Package |
| HANDOFF-07 | 208 | Manufacturer Handoff Package |
| HANDOFF-08 | 208 | Manufacturer Handoff Package |
| HANDOFF-09 | 208 | Manufacturer Handoff Package |
| INTEG-01 | 209 | Crossfile + MCP Integration |
| INTEG-02 | 209 | Crossfile + MCP Integration |
| INTEG-03 | 209 | Crossfile + MCP Integration |
| INTEG-04 | 209 | Crossfile + MCP Integration |
| INTEG-05 | 209 | Crossfile + MCP Integration |
| INTEG-06 | 209 | Crossfile + MCP Integration |
| FUTURE-API-01 | 210 (DEFERRED) | Vendor API Adapters |
| FUTURE-API-02 | 210 (DEFERRED) | Vendor API Adapters |
| FUTURE-API-03 | 210 (DEFERRED) | Vendor API Adapters |
| FUTURE-API-04 | 210 (DEFERRED) | Vendor API Adapters |
| FUTURE-API-05 | 210 (DEFERRED) | Vendor API Adapters |

**Coverage summary:** 40/40 active requirements mapped (100%). 5/5 future requirements mapped to deferred Phase 210.
