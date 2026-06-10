# kicad-agent — Agent Context

AI-safe structural editing of KiCad 10+ schematic, PCB, symbol, and footprint files.

## Tool Inventory

### KiCad CLI (kicad-cli 10.0.1)

**Schematic Operations:**
```bash
kicad-cli sch erc <file.kicad_sch>                    # Run ERC, generate report
kicad-cli sch export pdf <file.kicad_sch> -o out.pdf  # Export schematic to PDF
kicad-cli sch export svg <file.kicad_sch> -o out.svg  # Export schematic to SVG
kicad-cli sch export netlist <file.kicad_sch> -o out.net  # Export netlist
kicad-cli sch export bom <file.kicad_sch> -o bom.xml  # Export BOM
kicad-cli sch upgrade <file.kicad_sch>                 # Upgrade format version
```

**PCB Operations:**
```bash
kicad-cli pcb drc <file.kicad_pcb>                     # Run DRC, generate report
kicad-cli pcb export gerbers <file.kicad_pcb> -o dir/  # Export Gerber files
kicad-cli pcb export drill <file.kicad_pcb> -o dir/    # Export drill files
kicad-cli pcb export pos <file.kicad_pcb> -o dir/      # Export position files
kicad-cli pcb export step <file.kicad_pcb> -o out.step # Export STEP 3D model
kicad-cli pcb export svg <file.kicad_pcb> -o out.svg   # Export SVG
kicad-cli pcb export pdf <file.kicad_pcb> -o out.pdf   # Export PDF
kicad-cli pcb export stats <file.kicad_pcb>            # Board statistics
kicad-cli pcb render <file.kicad_pcb> -o render.png    # 3D render to PNG/JPEG
kicad-cli pcb render <file.kicad_pcb> -o out.png --side bottom --rotate "-45,0,45"  # Isometric view
kicad-cli pcb upgrade <file.kicad_pcb>                  # Upgrade format version
```

**Library Operations:**
```bash
kicad-cli sym export svg <file.kicad_sym> -o out.svg   # Export symbol SVG
kicad-cli sym upgrade <file.kicad_sym>                   # Upgrade symbol lib
kicad-cli fp export svg <file.kicad_mod> -o out.svg     # Export footprint SVG
kicad-cli fp upgrade <file.kicad_mod>                    # Upgrade footprint lib
```

### Python Automation (installed packages)

| Package | Version | Purpose |
|---------|---------|---------|
| `kicad-agent` | 0.0.1 | Core library — AST mutation, operation executor, validation gates |
| `kicad-python` | 0.4.0 | KiCad file I/O bindings |
| `kiutils` | 1.4.8 | S-expression parser/writer for KiCad files |
| `sexpdata` | 1.0.0 | Low-level S-expression parsing |
| `skidl` | 2.0.1 | Script-based circuit design (Python → netlist) |
| `spicelib` | 1.5.1 | SPICE simulation integration |

**kicad-agent operations (via `/kicad-agent` skill or direct Python):**
```bash
cd ~/apps/kicad-agent && python3 -c "
from kicad_agent.ops.executor import execute
result = execute(operation_json)
"
```

98 operation types. Operation metadata (category, file types, read-only, dependencies) available via `kicad_agent.ops.registry`.

### Analysis & Inference
```bash
cd ~/apps/kicad-agent && python3 -c "
from kicad_agent.inference import generate_analysis
result = generate_analysis('path/to/file.kicad_pcb')
"
```

### Training Scripts (scripts/)
```bash
python3 scripts/train_sft.py          # SFT fine-tuning
python3 scripts/train_grpo_mlx.py     # GRPO RL training (Apple MLX)
python3 scripts/evaluate_models.py    # Model evaluation
python3 scripts/collect_training_data.py  # Data collection
python3 scripts/prepare_sft_data.py   # SFT data preparation
python3 scripts/discover_100k.py      # Large-scale schematic discovery
```

## Workflow Stages

The PCB design pipeline runs in this order. Each stage has CLI automation — never ask a human to do these manually.

### 1. Circuit Design (SPICE/skidl)
```bash
# skidl-based circuit synthesis
python3 -c "import skidl; ..."
# SPICE simulation via spicelib
python3 -c "from spicelib import ..."
```

### 2. Schematic Capture
```bash
# Edit via kicad-agent operations (JSON → AST mutation)
/kicad-agent '{"op": "add_component", ...}'

# Validate schematic
kicad-cli sch erc <project.kicad_sch>
```

### 3. ERC (Electrical Rules Check)
```bash
kicad-cli sch erc <project.kicad_sch>    # Always run ERC after schematic edits
```

### 4. PCB Layout
```bash
# Operations via kicad-agent
/kicad-agent '{"op": "pcb_ops", ...}'

# 3D visualization
kicad-cli pcb render <project.kicad_pcb> -o render.png --rotate "-45,0,45"
```

### 5. DRC (Design Rules Check)
```bash
kicad-cli pcb drc <project.kicad_pcb>    # Always run DRC after layout edits
```

### 6. Manufacturing Export
```bash
kicad-cli pcb export gerbers <project.kicad_pcb> -o gerbers/
kicad-cli pcb export drill <project.kicad_pcb> -o gerbers/
kicad-cli pcb export pos <project.kicad_pcb> -o gerbers/
kicad-cli pcb export step <project.kicad_pcb> -o assembly/
```

### 7. Review
```bash
# Render for review
kicad-cli pcb render <project.kicad_pcb> -o review.png --quality high
kicad-cli sch export pdf <project.kicad_sch> -o schematic.pdf
```

## Known Bugs & Workarounds (Phase 26)

These bugs have workarounds that MUST be applied in any build script using kicad-agent. See KNOWN_LIMITATIONS.md P26-1 through P26-5 for full details.

| Bug | Issue | Workaround |
|-----|-------|-----------|
| `add_power` creates 0-pin symbols | #49 | Don't use. Change pin types to `passive` in embedded lib_symbol. |
| `add_component` missing rotation | #48 | Post-process regex: append ` 0` to `(at X Y)` |
| kiutils `Board.to_file()` drops nets | Unfiled | Use raw S-expression for PCBs, not kiutils serialization |
| Device:R/C 3.81mm off-grid | #48 | Accept false-positive `wire_dangling`, use no-connects for optional parts |

## KiCad Coordinate System (Critical for Agents)

When building schematics programmatically, these rules prevent the most common agent failures:

1. **Pin (at X Y) = wire connection point**, not pin graphic tip. Wires terminate at the `(at)` coordinate.
2. **Schematic Y is INVERTED:** `abs_Y = comp_Y - pin_rel_Y` (subtract, not add).
3. **Multi-pin connectors have non-sequential layouts.** Card_Edge_64P pins 33-64 ALL on right side, reuse Y positions from pins 1-32. Use lookup tables, never calculate.
4. **Device:R/C have 3.81mm pin offsets** (not 2.54mm), placing connection points off-grid.

## Planning (MANDATORY)

All implementation planning MUST go through GSD. Never use native plan mode for kicad-agent work.

| I want to... | Command | Plans land at |
|---|---|---|
| Plan a phase | `/gsd-plan-phase N` | `.planning/phases/N/PLAN.md` |
| Execute a phase | `/gsd-execute-phase N` | Source files + `.planning/phases/N/SUMMARY.md` |
| Check progress | `/gsd-progress` | `.planning/STATE.md` |

**Forbidden:** Writing plans to `~/.claude/plans/` for kicad-agent work.

## Agent Rules

- **Automate first.** Before asking a human to run something manually, check the tool inventory above. If a CLI command exists, use it. kicad-cli runs ERC, DRC, exports, renders, and upgrades without opening the GUI.
- **Track in Beads.** Use `mcp__beads__beads_create` for every issue found or task started. Use `mcp__beads__beads_update` to track progress.
- **Never skip validation.** Always run ERC after schematic edits. Always run DRC after layout edits. Always run both before manufacturing export.
- **Out-of-scope findings must be tracked.** If you find an issue but it's not in the current task, create a Bead with labels "out-of-scope" before continuing.
- **Use kicad-agent operations, not raw file edits.** Never directly edit .kicad_sch or .kicad_pcb files with text tools. Use the operation executor for safe AST mutations.
- **3D renders for visual review.** Use `kicad-cli pcb render` to generate PNG/JPEG images for visual inspection instead of asking the user to open KiCad.

## Project Structure

```
src/kicad_agent/
  cli.py           — CLI entry point
  context.py       — Project context loading
  handler.py       — Operation dispatch
  ops/             — 98 operation implementations
    executor.py    — Core operation executor
    schema*.py     — Pydantic operation schemas
    validation_gates.py — Pre/post validation
  parser/          — S-expression parsing
  serializer/      — File serialization
  validation/      — ERC/DRC, format, spatial, structural checks
  mcp/             — MCP server for tool integration
  inference/       — AI model inference (spatial reasoning)
  analysis/        — Board/schematic analysis
  training/        — Model training pipeline (SFT, GRPO)
  crawler/         — Schematic/board discovery
  ltspice/         — LTSpice import support
  project/         — Project management, ADI library
  llm/             — LLM integration layer
  ir/              — Intermediate representation
  spatial/         — Spatial reasoning utilities
  generation/      — Auto-generation tools
  placement/       — Component placement
  routing/         — Auto-routing
  export/          — Export utilities
  crossfile/       — Cross-file reference tracking

scripts/           — Training, evaluation, data collection scripts
skills/            — Claude Code skill definitions
```

## Key Commands

| I want to... | Command |
|-------------|---------|
| Edit a KiCad file | `/kicad-agent '<json operation>'` |
| Run ERC | `kicad-cli sch erc <file.kicad_sch>` |
| Run DRC | `kicad-cli pcb drc <file.kicad_pcb>` |
| Export Gerbers | `kicad-cli pcb export gerbers <file.kicad_pcb> -o gerbers/` |
| 3D render | `kicad-cli pcb render <file.kicad_pcb> -o render.png --rotate "-45,0,45"` |
| Export schematic PDF | `kicad-cli sch export pdf <file.kicad_sch> -o sch.pdf` |
| Analyze with AI model | `/kicad-agent analyze <file.kicad_pcb>` |
| Check project status | `/kicad-agent status` |
| Get project context | `/kicad-agent context` |
| View operations help | `/kicad-agent help` |
