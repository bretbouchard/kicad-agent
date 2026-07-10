# Features — v7.0 Vendor-Neutral Manufacturing Layer

## Feature Categories

### Category 1: Board Metadata Foundation

**Table stakes (must have for v7.0):**
- Parse KiCad `title_block` from `.kicad_pcb` (title, date, rev, company, comments)
- Write/update `title_block` fields (especially `rev` — the board version)
- `BoardSpec` model: surface finish, copper weight, soldermask color, silkscreen color
- `BoardSpec` persistence as sidecar JSON (`.kicad_build_spec.json`) alongside the project

**Differentiators:**
- Controlled impedance spec for fab (which nets, target ohms, reference layer)
- Stackup as fab-facing spec (ordered layer list with materials, dielectric thickness)
- Special process requirements (castellated holes, edge plating, V-scoring, beveling)

**Complexity:** Medium. The parser already handles everything except `title_block` (listed in `_UNSUPPORTED_ELEMENTS`). Extending it follows the existing `NativeStackup`/`NativeSetup` pattern in `pcb_native_types.py`.

### Category 2: Vendor DRC Profiles

**Table stakes:**
- Ship `.kicad_dru` files for PCBWay, JLCPCB, AISLER (verified sources)
- `drc_vendor` operation: run DRC against a vendor profile
- Extend `ManufacturerProfile` (dfm/profiles.py) to reference the `.kicad_dru` file path

**Differentiators:**
- OSH Park + Advanced Circuits profiles authored from published numeric specs
- Multi-stackup selection (AISLER ships 2/4/6/8-layer variants)
- DRC profile validation against vendor's current published capabilities (flag stale rules)

**Complexity:** Low. The files exist; kicad-cli already supports `--custom-rules`. The work is wiring it into the ops system.

### Category 3: Versioned Build System

**Table stakes:**
- `Build` record: version/rev, source file paths, git SHA, timestamp, artifact list
- Manifest serialization to disk (JSON with SHA256-hashed artifacts)
- `build_create` operation: snapshot source + run validation gate + record build
- `build_list` / `build_show` operations: query build history

**Differentiators:**
- Build directory structure (`builds/v{rev}_{timestamp}/`)
- Provenance tracking (which source files + git commit produced this build)
- Build status tracking (draft → validated → exported → handed-off)

**Complexity:** Medium. The `ManufacturingManifest` dataclass already exists with SHA256 hashing — it just needs `to_json()`/`save()` methods and a build record wrapper. The validation flow already exists in `ManufacturingReadinessGate`.

### Category 4: Manufacturer Handoff Package

**Table stakes:**
- Full export orchestration: Gerbers + drill + BOM + P&P + STEP + netlist + schematic PDF + PCB PDF
- Zip bundle with all artifacts + manifest + readme
- Readme/manifest includes: board name, rev, date, layer count, dimensions, finish, colors, designer contact
- `build_handoff_export` operation: the one-call "prepare for manufacturing" command

**Differentiators:**
- Vendor-specific output formatting (JLCPCB BOM column format, naming conventions)
- Handoff page / summary view (what to upload, where, notes per vendor)
- Pre-handoff validation: DRC clean + ERC clean + manifest complete before bundling

**Complexity:** Medium-High. All export wrappers exist individually — the work is orchestration + bundling + readme generation + the validation gate integration.

### Category 5: Crossfile + Integration

**Table stakes:**
- Link builds into `ProjectContext` (builds are a project-scoped artifact)
- Expose all new ops via MCP (auto-generated) and CLI
- Group-edit awareness: builds reference source files, so edits to sources invalidate affected builds

**Differentiators:**
- Build diffing (what changed between build v1.0 and v1.1)
- Integration with existing VerificationLoop (build creation runs through governedCall)

**Complexity:** Low-Medium. MCP auto-exposure is free. CLI needs subcommand wiring. ProjectContext extension is additive.

### Category 6: Vendor API Adapters (DEFERRED)

**Table stakes (when activated):**
- `ManufacturerClient` ABC: `quote()`, `place_order()`, `get_status()` interface
- PCBWay adapter (Partner API)
- MacroFab adapter (Cloud API v2)

**Differentiators:**
- JLCPCB adapter (Online API)
- Quote comparison across multiple vendors
- Order tracking with status notifications

**Complexity:** High. Requires API keys (PCBWay partner-gated, MacroFab account-gated). Endpoint docs for MacroFab are gated behind authenticated portal. No Python libraries exist for any of these — kicad-agent would write the first wrappers.

**Status:** DEFERRED to P6. The handoff package (Category 4) is the universal fallback that works with all vendors, including those with APIs. API adapters are accelerators, not requirements.

## Dependencies Between Categories

```
Category 1 (Metadata) ──┬──→ Category 3 (Builds) ──→ Category 4 (Handoff)
                        │                              ↑
Category 2 (DRC) ───────┘──────────────────────────────┘
                                                        │
                                              Category 5 (Integration)
                                                        │
                                              Category 6 (API Adapters) — DEFERRED
```

Categories 1 and 2 are the foundation. Category 3 builds on 1 (needs version/rev). Category 4 builds on 1+2+3 (needs metadata + DRC + build record). Category 5 integrates everything. Category 6 is optional and deferred.

## Research Notes

- The codebase already has significant primitives: `ManufacturerProfile`, `ManufacturingManifest`, `ManufacturingReadinessGate`, `ManufacturingPackage`, export wrappers for every format. v7.0 is largely about **assembling and completing** these, not building from scratch.
- The `export_jlcpcb_bom` / `enrich_with_lcsc` functions show the vendor-specific output pattern — this should be generalized to a profile-driven formatter rather than hard-coded per vendor.
- No new dependencies are needed. This is pure Python + existing kicad-cli + stdlib.
