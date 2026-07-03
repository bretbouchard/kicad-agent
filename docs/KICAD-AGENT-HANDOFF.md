# kicad-agent — Team Handoff Document

**AI-safe structural editing of KiCad 10+ schematic, PCB, symbol, and footprint files.**

> **Quick start:** `pip install -e .` then `kicad-agent '{"op_type":"query","file_path":"my.kicad_pcb"}'`

---

## What Is kicad-agent?

kicad-agent is a Python library and CLI tool for programmatically editing KiCad design files with zero corruption. It provides:

- **98 operation types** covering schematic editing, PCB layout, routing, cross-file sync, validation, and manufacturing export
- **Structural safety** — every edit goes through AST mutation or raw S-expression surgery, never text-level find/replace
- **Validation gates** — ERC, DRC, spatial checks, and stage-transition gates that fail closed
- **Auto-routing** — in-house A* pathfinder + Freerouting integration + placement-aware negotiation loop
- **AI integration** — Gemma 4 12B vision model for spatial reasoning, blocker diagnosis, and routing strategy
- **MCP server** — exposes all operations as tools for Claude Code or other MCP-compatible AI agents

**KiCad version:** 10+ only. `kicad-cli` must be on PATH for ERC/DRC/export operations.

---

## Table of Contents

1. [Installation](#installation)
2. [CLI Quick Reference](#cli-quick-reference)
3. [Operations (98 types)](#operations-98-types)
4. [Schematic Operations](#schematic-operations)
5. [PCB Operations](#pcb-operations)
6. [Routing Capabilities](#routing-capabilities)
7. [Validation & Gates](#validation--gates)
8. [Cross-File Sync](#cross-file-sync)
9. [MCP Server](#mcp-server)
10. [Analysis Tools](#analysis-tools)
11. [AI/ML Integration](#aiml-integration)
12. [Manufacturing Export](#manufacturing-export)
13. [Known Limitations](#known-limitations)
14. [Architecture](#architecture)
15. [Phase 103-106: Routing Overhaul](#phase-103-106-routing-overhaul)

---

## Installation

```bash
git clone <repo-url>
cd kicad-agent
pip install -e .
```

**Dependencies:** Python 3.11+, KiCad 10+ (`kicad-cli` on PATH).

**Verify:**
```bash
kicad-cli --version
kicad-agent --schema | python3 -m json.tool | head -20
```

---

## CLI Quick Reference

| Command | What it does |
|---|---|
| `kicad-agent '<json>'` | Run any operation from inline JSON |
| `kicad-agent ops.json` | Run operations from a JSON file |
| `kicad-agent --dry-run '<json>'` | Validate without executing |
| `kicad-agent --schema` | Print the full operation JSON Schema |
| `kicad-agent erc <schematic>` | Run ERC on a schematic |
| `kicad-agent drc <pcb>` | Run DRC on a PCB |
| `kicad-agent export gerber <pcb> -o gerbers/` | Export Gerbers |
| `kicad-agent export bom <pcb> -o bom.csv` | Export BOM |
| `kicad-agent export step <pcb> -o board.step` | Export STEP 3D model |
| `kicad-agent route <pcb>` | Auto-route a PCB |
| `kicad-agent context [project_dir]` | Show project summary |
| `kicad-agent analyze <file>` | AI-powered board analysis |
| `kicad-agent pre-pcb-gate <schematic>` | Schematic readiness gate |
| `kicad-agent review-schematic <sch>` | Schematic quality review |
| `kicad-agent undo [file]` / `redo [file]` | Persistent undo/redo |
| `kicad-agent workflow route-and-fill <pcb>` | Multi-step workflow |
| `kicad-agent playground` | Interactive web UI |
| `kicad-agent demo --list` | Template-based schematic generation |

---

## Operations (98 types)

All operations are JSON-driven and go through the same executor pipeline:

```
JSON input → Pydantic schema validation → Pre-analysis gate → Handler → Post-validation → Atomic write
```

**Invocation patterns:**
```bash
# Inline JSON
kicad-agent '{"op_type":"add_component","file_path":"my.kicad_sch","reference":"R1","lib_id":"Device:R","x":100,"y":50}'

# From file
kicad-agent ops.json

# Dry run (validate only)
kicad-agent --dry-run '{"op_type":"auto_route","file_path":"my.kicad_pcb"}'

# Programmatic
from kicad_agent.ops.executor import execute
result = execute(operation_json)
```

**Categories (25):** component, net, reference, footprint, wire, remove, query, library, pcb, erc, gap, create, repair, sheet, crossfile, routing, schematic_intel, erc_smart, readability, gate, constraint, manufacturing, placement, drc, zone.

**Registry queries:** Use `kicad_agent.ops.registry` to discover operations:
```python
from kicad_agent.ops.registry import get_operations_for_file_type, get_readonly_operations
pcb_ops = get_operations_for_file_type("pcb")  # All PCB operations
read_only = get_readonly_operations()          # Safe query operations
```

---

## Schematic Operations

File type: `.kicad_sch`

### Components
| Operation | Description |
|---|---|
| `add_component` | Add a component with reference, lib_id, position |
| `remove_component` | Remove a component by reference |
| `move_component` | Move a component to new coordinates |
| `modify_property` | Add/modify a component property |
| `duplicate_component` | Duplicate an existing component |
| `array_replicate` | Linear/circular/matrix array of a component |
| `swap_symbol` | In-place symbol library swap |
| `snap_components_to_grid` | Snap all components to grid |
| `place_missing_units` | Place missing units of multi-unit symbols |

### Wiring & Connectivity
| Operation | Description |
|---|---|
| `add_wire` | Add a wire between two points |
| `add_label` | Add local/global/hierarchical label |
| `add_power` | Add power port symbol |
| `add_no_connect` | Add no-connect marker |
| `add_junction` | Add junction at wire intersection |
| `add_power_flag` | Add PWR_FLAG at ERC violations |
| `connect_pins` | Wire two pins together |
| `batch_connect` | Wire multiple pin pairs |
| `regenerate_wiring` | Strip and rebuild wiring from netlist |

### Annotation
| Operation | Description |
|---|---|
| `safe_annotate` | Non-destructive reference renumbering (raw S-expr) |
| `renumber_refs` | Renumber reference designators |
| `validate_refs` | Check for duplicate/missing references |

### Repair
| Operation | Description |
|---|---|
| `repair_schematic` | Multi-issue schematic repair |
| `remove_dangling_wires` | Remove unconnected wire stubs |
| `break_wire_shorts` | Break nets that are shorted |
| `resolve_shorted_nets` | Resolve net short conflicts |
| `fix_pin_type_mismatches` | Fix ERC pin type errors |

### Schematic Intelligence (read-only)
| Operation | Description |
|---|---|
| `extract_nets` | Extract all nets from schematic |
| `infer_connectivity` | Infer net connectivity with confidence scoring |
| `detect_net_conflicts` | Detect conflicting net assignments |
| `suggest_net_names` | Suggest net names from context |
| `detect_net_shorts` | Detect shorted nets (union-find) |
| `analyze_ground_topology` | Analyze GND topology (mixed-signal) |

---

## PCB Operations

File type: `.kicad_pcb`

### Placement
| Operation | Description |
|---|---|
| `move_footprint` | Move a footprint to new coordinates |
| `auto_place` | Automatic overlap-free placement |
| `auto_place_zoned` | Zone-aware placement |
| `place_component` | Parametric component placement |
| `batch_expand_footprints` | Load full geometry from libraries |
| `export_positions` / `import_positions` | Save/restore placement as JSON |

### Routing
| Operation | Description |
|---|---|
| `auto_route` | A* auto-routing with DRC-aware obstacles |
| `auto_route_manhattan` | L-shaped Manhattan routing |
| `auto_route_freerouting` | Full Freerouting pipeline (DSN→SES) |
| `route_diff_pair` | Differential pair routing |
| `match_lengths` | Sawtooth length matching |
| `import_ses` | Import Freerouting SES result |

### Tracks & Vias
| Operation | Description |
|---|---|
| `add_track` / `add_arc_track` | Add track segments |
| `add_via` | Add a via |
| `delete_track` / `delete_via` | Delete tracks/vias |
| `move_track_endpoint` | Move a track endpoint |
| `lock_track` / `lock_via` | Lock tracks/vias |
| `add_stitching_via_pattern` | Add via stitching pattern |
| `stitch_power_nets` | DRC-aware power net via stitching |

### Zones
| Operation | Description |
|---|---|
| `add_copper_zone` | Add copper zone (pour) |
| `modify_copper_zone` | Modify zone properties |
| `remove_copper_zone` | Remove a zone |
| `refill_copper_zone` / `fill_zones` | Fill zones (via pcbnew API) |
| `add_keepout_area` | Add keepout zone |

### Cleanup
| Operation | Description |
|---|---|
| `strip_shorts` | Remove tracks causing DRC shorts |
| `remove_dangling_tracks` | Remove orphaned track segments |
| `fix_silkscreen_over_copper` | Fix silkscreen over copper violations |

---

## Routing Capabilities

kicad-agent has a multi-layered routing system under `src/kicad_agent/routing/`:

### Routing Backends
- **A\* Pathfinder** — in-house grid-based A* with DRC-aware edge weights, Euclidean heuristic, nearest-neighbor Steiner tree for multi-pin nets
- **Freerouting** — external Java autorouter via DSN export → subprocess → SES import. 30+ years of classical routing engineering
- **Strategy dispatch** — `DeterministicStrategy` routes diff pairs/power to A*, dense nets to Freerouting. `AiRoutingStrategy` (Gemma 4 vision) provides model-based dispatch

### Phase 103-106: Placement-Aware Routing Overhaul

The most recent work adds a **closed-loop negotiation system** with AI-powered blocker diagnosis:

**Phase 103 — Foundation (Signal Capture)**
- `RouteFailure` dataclass captures the true router dead-end point (not just "it failed")
- `route_net()` returns `RouteResult | RouteFailure` with `dead_end_point`, `failure_type`, `reachable_count`
- Audit trail enriched with failure location data

**Phase 104 — Diagnosis (Reverse-Perspective Classifier)**
- `BlockerDiagnostician` — when routing hits a dead end, looks from the dead end's perspective, finds what's blocking the path
- Shadow-cast corridor query → causality test (remove obstacle, does path open?) → classify blocker
- Blocker classifications: `SOFT_OTHER` (rip & reroute), `SOFT_OWN` (reroute self), `HARD_COMPONENT` (nudge component), `HARD_FIXED` (escalate), `CONTESTED` (raise priority)

**Phase 105 — Negotiation (Closed Loop)**
- `NegotiationLoop` — PathFinder-style rip-up-and-reroute with monotonic congestion cost for guaranteed convergence
- Diagnoses failures → rips up SOFT_OTHER blockers → re-routes with escalating priority
- DSN `(type fix)` locking for Freerouting-as-executor (empirically verified)
- Terminates on convergence, stall (2 rounds no improvement), or max_rounds

**Phase 106 — Model Repoint (AI Diagnostician)**
- `BlockerDiagnosticianModel` — Gemma 4 12B vision model trained on diagnostic traces
- Renders board → prompts model → parses blocker classifications
- Graceful degradation: falls back to deterministic on any failure
- Opt-in only: `NegotiationLoop(diagnostician=model_diag)`

```python
# Use the negotiation loop with AI diagnosis
from kicad_agent.routing import negotiate_route, BlockerDiagnosticianModel

result = negotiate_route(
    board_bounds=bounds,
    obstacles=obstacles,
    netlist=netlist,
    max_rounds=8,
    # diagnostician=model_diag,  # opt-in AI (default: deterministic)
)
print(f"Routed: {len(result.routed_nets)}, Failed: {len(result.failed_nets)}")
```

---

## Validation & Gates

### KiCad-CLI Checks
```bash
kicad-agent erc my.kicad_sch     # Electrical Rules Check
kicad-agent drc my.kicad_pcb     # Design Rules Check
```

### Stage Gates
kicad-agent enforces a stage-gate pipeline:

```
SCHEMATIC → PCB_SETUP → PLACEMENT → ROUTING → MANUFACTURING
```

Each transition has a deterministic gate that fails closed:
```bash
kicad-agent pre-pcb-gate my.kicad_sch    # Schematic readiness before PCB
kicad-agent gate run placement_gate       # Placement readiness
kicad-agent gate status                    # Show all gate results
```

### Spatial & Structural Validators
- DRC with spatial enrichment (`SpatialViolation` with coordinates)
- Silkscreen clearance checks
- Split-plane detection
- Grid alignment verification
- Structural integrity (parse → serialize → parse stability)
- Symbol mismatch / resolution checks

---

## Cross-File Sync

kicad-agent provides non-destructive schematic↔PCB synchronization:

| Operation | Description |
|---|---|
| `safe_sync_pcb_from_schematic` | **Recommended.** Updates pad nets + lib_ids while preserving routing, zones, placement |
| `update_pcb_from_schematic` | Full PCB sync via kicad-cli netlist |
| `repopulate_pcb_from_schematic` | Re-populate PCB from netlist with auto-placement |
| `rebuild_pcb_nets` | Rebuild PCB net table from netlist |
| `propagate_symbol_change` | Atomic symbol/footprint change across all files |

**Key principle:** `safe_sync_pcb_from_schematic` NEVER touches `(at X Y)` — your placement and routing always survive sync.

---

## MCP Server

kicad-agent exposes two MCP servers for AI agent integration:

### Edit Server (operation execution)
```bash
KICAD_PROJECT_DIR=/path/to/project kicad-agent-edit
```

Exposes **one MCP tool per operation** (all 98), plus meta-tools:
- `erc_check`, `drc_check` — validation
- `undo`, `redo` — persistent undo
- `render_pcb`, `export_schematic_svg`, `export_pcb_svg` — visualization
- `get_project_context` — project summary
- `list_workflows`, `get_workflow` — workflow discovery

Tool annotations (`readOnlyHint`/`destructiveHint`) are auto-derived from the operation registry.

### Component Search Server
```bash
kicad-agent component-search
```

Searches JLCPCB/EasyEDA for components:
- `search_components` — keyword search
- `get_component_details` — full part info (pins, pads, package, stock, price)
- `get_component_suggestions` — application-based suggestions

---

## Analysis Tools

| Tool | Description |
|---|---|
| `analyze_gaps` | Post-routing gap analysis (unrouted nets, DRC violations, incomplete nets) |
| `fill_gaps` | AI-powered gap filling |
| `review_schematic` | Schematic readability + spatial quality review |
| `analyze` | Local model board/schematic reasoning (best-of-N chains) |
| Gap report | Unrouted nets, incomplete nets, DRC violations, net naming issues |
| Readability scoring | Component spacing, label clarity, wire routing quality |
| Subcircuit detection | Identify functional blocks (power, analog, digital) |

---

## AI/ML Integration

### Gemma 4 12B Vision Model
- **Purpose:** Spatial reasoning, routing strategy, blocker diagnosis
- **Format:** MLX LoRA adapter (rank 64, 326MB)
- **Adapters:**
  - `kicad-vision-v2-mlx` — spatial Q&A + maze reasoning (prior, on storage drive)
  - `phase106-mlx` — blocker diagnosis (latest, includes diagnostic training)
- **Inference:** `KiCadVisionPipeline` via mlx-vlm
- **Graceful degradation:** ALL model outputs are validated; on failure, falls back to deterministic

### Training Pipeline
- **SFT** — supervised fine-tuning on maze reasoning chains + PCB spatial Q&A
- **GRPO** — advantage-weighted REINFORCE (reward model + rule-based blend)
- **Data generation** — synthetic maze boards, real GitHub KiCad repos (71K discovered)
- **Vast.ai training** — `scripts/vast_train_kicad.py` for cloud GPU training
- **Local eval** — `scripts/evaluate_gemma_adapter.py`, `scripts/phase106_eval.py`

### Inference Wrapper
```python
from kicad_agent.inference import generate_analysis
result = generate_analysis("my.kicad_pcb", n_best=3)
```

---

## Manufacturing Export

All exports go through kicad-cli:

```bash
kicad-agent export gerber my.kicad_pcb -o gerbers/      # Gerber files
kicad-agent export bom my.kicad_pcb -o bom.csv           # BOM with LCSC numbers
kicad-agent export position my.kicad_pcb -o pos.csv      # Pick-and-place
kicad-agent export step my.kicad_pcb -o board.step       # 3D STEP model
```

**DFM analysis:**
```bash
kicad-agent dfm my.kicad_pcb --profile jlcpcb --output dfm_report.md
```

---

## Known Limitations

| Limitation | Status | Workaround |
|---|---|---|
| Via optimization for complex multi-layer designs | Not implemented | Use Freerouting for complex boards |
| Built-in A* router is for simple boards only | By design | Negotiation loop + Freerouting for production |
| Native PCB parser edge cases (custom thermal pads, complex keepouts) | Some fall back to kiutils | Raw S-expression preserved; structural edits still safe |
| `erc_auto_fix` / `erc_auto_fix_hierarchical` | **Deprecated** (data-loss bug) | Use `repair_schematic` instead |
| `annotate` | **Superseded** by `safe_annotate` (P0-006 corruption fix) | Always use `safe_annotate` |
| GRPO is advantage-weighted REINFORCE, not PPO | Mislabeled | Labels corrected; algorithm is sound |
| KiCad version | 10+ only | KiCad 9 and below not supported |

---

## Architecture

```
src/kicad_agent/
  cli.py              — CLI entry point (19 subcommands)
  handler.py          — Operation dispatch
  ops/
    executor.py       — Core operation executor
    schema.py         — Pydantic operation schemas (98 types)
    registry.py       — Operation metadata registry
    validation_gates.py — Pre/post validation
    handlers/         — Operation implementations
      schematic.py    — Schematic operations
      pcb.py          — PCB operations (routing, placement, tracks)
      crossfile.py    — Cross-file sync
      pcb_cleanup.py  — Post-route cleanup
      pcb_stitch.py   — Power net via stitching
      ...
  routing/
    pathfinder.py     — A* pathfinding with RouteFailure
    diagnostician.py  — Deterministic blocker diagnosis
    diagnostician_model.py — AI blocker diagnosis (Phase 106)
    negotiation.py    — Closed-loop negotiation (Phase 105)
    graph.py          — DRC-aware routing graph
    freerouting.py    — Freerouting integration
    dsn_generator.py  — Specctra DSN generation
    orchestrator.py   — Strategy-based dispatch
    ...
  parser/             — S-expression parsing (native + kiutils)
  serializer/         — File serialization
  validation/         — ERC, DRC, spatial, structural checks
  crossfile/          — Schematic↔PCB synchronization
  inference/          — AI model inference (Gemma 4 vision)
  analysis/           — Gap analysis, spatial benchmarks
  training/           — Model training (SFT, GRPO)
  mcp/                — MCP servers (edit + component search)
  export/             — Manufacturing export utilities
  spatial/            — Shapely-based spatial queries
  placement/          — Component placement engine
  dfm/                — Design for Manufacturing
  ltspice/            — LTspice import support
```

---

## Phase 103-106: Routing Overhaul Summary

The most recent work was a comprehensive placement-aware routing overhaul. See `plans/routing-overhaul-phases-103-106.md` for the full plan and `.planning/COUNCIL-PLAN-REVIEW.md` for the council review.

| Phase | Deliverable | Status |
|---|---|---|
| **103 Foundation** | `RouteFailure` with dead-end recovery, enriched audit trail | ✅ Complete |
| **104 Diagnosis** | `BlockerDiagnostician` — reverse-perspective classifier | ✅ Complete |
| **105 Negotiation** | `NegotiationLoop` — PathFinder rip-up-and-reroute, DSN `(type fix)` locking | ✅ Complete |
| **106 Model Repoint** | `BlockerDiagnosticianModel` — trained Gemma 4 adapter, graceful fallback | ✅ Complete |

**Training:** 2000 steps on A100-SXM4-40GB, loss 0.089, 142K dataset (including 110 blocker-diagnosis examples).

**Verification:** 178 routing tests pass, zero regressions. R-1 empirically verified (Freerouting honors `(type fix)`).

---

## Getting Help

- **Operation schema:** `kicad-agent --schema`
- **Available operations:** `python3 -c "from kicad_agent.ops.registry import OPERATIONS; print(len(OPERATIONS))"`
- **Project context:** `kicad-agent context /path/to/project`
- **Gate status:** `kicad-agent gate status`
- **Test suite:** `pytest tests/ -m "not slow"`
- **Playground:** `kicad-agent playground` → http://localhost:8000

---

*Document generated 2026-07-03. kicad-agent v0.0.1, KiCad 10+.*
