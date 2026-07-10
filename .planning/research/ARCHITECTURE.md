# Architecture — v7.0 Vendor-Neutral Manufacturing Layer

## Existing Architecture

The codebase has a mature operation pipeline:

```
CLI/MCP → OperationExecutor → Operation (Pydantic union) → Handler → kicad-cli / AST mutation → Result
                                                    ↓
                                            validation_gates (pre/post)
                                                    ↓
                                            VerificationLoop (checkpoint → execute → post-check → rollback-on-fail)
```

Key existing modules relevant to v7.0:

| Module | Purpose | v7.0 Relationship |
|--------|---------|-------------------|
| `parser/pcb_native_parser.py` | Parses `.kicad_pcb` S-expressions into typed dataclasses | EXTEND: add `NativeTitleBlock` (currently in `_UNSUPPORTED_ELEMENTS`) |
| `parser/pcb_native_types.py` | Frozen dataclasses for parsed PCB elements | EXTEND: add `NativeTitleBlock` dataclass |
| `dfm/profiles.py` | `ManufacturerProfile` — fab capability constraints | EXTEND: add `drc_rules_path` field linking to `.kicad_dru` |
| `dfm/checker.py` | DFM checker orchestrator | CONSUME: existing DFM checks run before build export |
| `validation/gates/manufacturing_manifest.py` | `ManufacturingArtifact`/`ManufacturingManifest` (in-memory) | PROMOTE: add serialization (`to_json()`, `save()`) |
| `validation/gates/manufacturing_gate.py` | `ManufacturingReadinessGate` (5 checks) | REUSE: validation flow before build export |
| `export/gerber.py` | Gerber/drill export + `ManufacturingPackage` | EXTEND: `ManufacturingPackage` → full bundle |
| `export/bom.py` | BOM export + JLCPCB-specific formatting + LCSC enrichment | GENERALIZE: vendor profile-driven formatting |
| `export/general.py` | pos, step, netlist, pdf, stats exports | CONSUME: orchestrated by handoff package |
| `ops/registry.py` | 142 ops with OpMeta | EXTEND: add ~8 manufacturing ops |
| `ops/schema.py` | Pydantic discriminated union | EXTEND: add new op schemas |
| `ops/handlers/` | Domain-specific handler registries | EXTEND: new `manufacturing.py` handler module |
| `ops/execution.py` | Dispatch routing (CROSS_FILE_OP_TYPES, CREATE_OP_TYPES) | EXTEND: add new multi-file op types |
| `crossfile/project_context.py` | `ProjectContext` — project file discovery | EXTEND: include build artifacts |
| `mcp/edit_server.py` | MCP server with auto-generated op tools | AUTO: new ops auto-exposed via `_generate_operation_tools()` |

## New Components

### 1. DRC Profiles Directory

```
src/kicad_agent/manufacturing/
├── __init__.py
├── drc_profiles/                    # Static .kicad_dru files (data, not code)
│   ├── pcbway.kicad_dru             # from pcbway/PCBWay-Design-Rules
│   ├── jlcpcb.kicad_dru             # from Cimos/KiCad-DesignRules (MIT)
│   ├── aisler_2layer.kicad_dru      # from AislerHQ/aisler-support
│   ├── aisler_4layer.kicad_dru
│   ├── aisler_6layer.kicad_dru
│   ├── aisler_8layer.kicad_dru
│   ├── oshpark.kicad_dru            # authored from published specs
│   └── generic.kicad_dru            # conservative defaults
└── board_spec.py                    # BoardSpec model (finish, color, stackup, impedance)
```

### 2. Build Record + Manifest

```
src/kicad_agent/manufacturing/
├── build.py                         # Build record (version, source SHA, artifacts, status)
├── manifest.py                      # Extends ManufacturingManifest with serialization
└── handoff.py                       # Orchestrator: exports → validation → zip → readme
```

**Build record data model:**
```python
@dataclass(frozen=True)
class Build:
    build_id: str                    # UUID
    board_rev: str                   # from title_block (e.g. "1.0", "2.1")
    source_files: tuple[str, ...]    # absolute paths to .kicad_sch/.kicad_pcb/.kicad_pro
    git_sha: str | None              # HEAD commit when build created
    created_at: datetime
    status: BuildStatus              # draft → validated → exported → handed_off
    artifacts: tuple[Artifact, ...]  # generated files with SHA256
    manifest_path: Path | None       # path to serialized manifest
    build_dir: Path                  # builds/v{rev}_{timestamp}/
```

### 3. New Operations

| Op Type | Scope | Category | Description |
|---------|-------|----------|-------------|
| `read_board_metadata` | single_file | query | Read title_block + BoardSpec from PCB |
| `set_board_metadata` | single_file | pcb | Write title_block fields (rev, title, date, company) |
| `set_board_revision` | single_file | pcb | Convenience op: just update the `rev` field |
| `drc_vendor` | single_file | validation | Run DRC with a specific vendor profile |
| `build_create` | multi_file | manufacturing | Snapshot source + validate + create build record |
| `build_list` | single_file | query | List builds for a project |
| `build_show` | single_file | query | Show build details + manifest |
| `build_handoff_export` | multi_file | manufacturing | Full export → validation → zip bundle + readme |

**Handler registry pattern:** New `ops/handlers/manufacturing.py` with `_MANUFACTURING_HANDLERS` dict + `register_manufacturing()` decorator, merged in `handlers/__init__.py` (mirroring the existing `_BOM_HANDLERS` → `_PCB_HANDLERS` pattern).

### 4. BoardSpec Sidecar

The `BoardSpec` (finish, color, stackup, impedance) lives in a sidecar JSON file:
```
my_project/
├── my_project.kicad_pro
├── my_project.kicad_sch
├── my_project.kicad_pcb
├── my_project.kicad_build_spec.json    ← NEW: BoardSpec sidecar
└── builds/                             ← NEW: build artifacts
    └── v1.0_20260710/
        ├── manifest.json
        ├── readme.md
        ├── gerbers/
        ├── drill/
        ├── bom.csv
        ├── positions.pos
        ├── board.step
        └── handoff.zip
```

## Data Flow

### DRC Vendor Flow
```
drc_vendor(vendor="pcbway", file="board.kicad_pcb")
  → resolve profile path (manufacturing/drc_profiles/pcbway.kicad_dru)
  → kicad-cli pcb drc board.kicad_pcb --custom-rules pcbway.kicad_dru
  → parse report → return DrcResult (existing type)
```

### Build + Handoff Flow
```
build_handoff_export(file="board.kicad_pcb", vendor="pcbway")
  → 1. Read BoardSpec + title_block (board rev, finish, etc.)
  → 2. Run ManufacturingReadinessGate (existing 5 checks)
     → FAIL? return error, no build created
  → 3. Run vendor DRC (drc_vendor flow above)
     → FAIL? return DRC violations, no build created
  → 4. Create build directory: builds/v{rev}_{timestamp}/
  → 5. Run all exports: gerbers, drill, bom, pos, step, netlist, pdf
  → 6. Build manifest with SHA256 hashes (existing ManufacturingArtifact pattern)
  → 7. Generate readme.md from BoardSpec + board stats + DRC/ERC results
  → 8. Zip everything into handoff.zip
  → 9. Serialize manifest.json
  → 10. Return Build record with all artifact paths
```

## Integration Points

1. **Ops system** — all 8 new ops follow the existing pattern: schema class → registry entry → handler → auto-MCP-exposed
2. **Validation gates** — `build_create` and `build_handoff_export` run through the existing `ManufacturingReadinessGate`
3. **VerificationLoop** — build creation can run through governedCall for checkpoint/rollback safety
4. **MCP auto-generation** — `_generate_operation_tools()` in edit_server.py introspects the Operation union; new ops appear automatically
5. **ProjectContext** — extended to discover `builds/` directories and `.kicad_build_spec.json` sidecars

## Suggested Build Order

1. **Phase 1 (Metadata Foundation)** — unblocks everything. title_block parsing + BoardSpec model.
2. **Phase 2 (DRC Profiles)** — independent of P1, but P1's BoardSpec is needed for full DRC context. Can partially overlap.
3. **Phase 3 (Versioned Builds)** — depends on P1 (needs rev field). Extends ManufacturingManifest.
4. **Phase 4 (Handoff Package)** — depends on P1+P2+P3. The capstone of the vendor-neutral layer.
5. **Phase 5 (Crossfile + MCP)** — depends on P3+P4. Integration layer.
6. **Phase 6 (API Adapters)** — DEFERRED. Depends on P4 conceptually but not technically required to start.

## What is NOT Changing

- The core parse → mutate → serialize pipeline is untouched
- The 142 existing operations are untouched
- The VerificationLoop / governedCall governance is untouched
- No new dependencies
- No changes to MCP protocol or daemon
