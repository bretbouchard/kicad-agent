# volta — Agent Context

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
| `volta` | 0.0.1 | Core library — AST mutation, operation executor, validation gates |
| `kicad-python` | 0.4.0 | KiCad file I/O bindings |
| `kiutils` | 1.4.8 | S-expression parser/writer for KiCad files |
| `sexpdata` | 1.0.0 | Low-level S-expression parsing |
| `skidl` | 2.0.1 | Script-based circuit design (Python → netlist) |
| `spicelib` | 1.5.1 | SPICE simulation integration |

**volta operations (via `/volta` skill or direct Python):**
```bash
cd ~/apps/volta && python3 -c "
from volta.ops.executor import execute
result = execute(operation_json)
"
```

98 operation types. Operation metadata (category, file types, read-only, dependencies) available via `volta.ops.registry`.

### Analysis & Inference
```bash
cd ~/apps/volta && python3 -c "
from volta.inference import generate_analysis
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
# Edit via volta operations (JSON → AST mutation)
/volta '{"op": "add_component", ...}'

# Validate schematic
kicad-cli sch erc <project.kicad_sch>
```

### 3. ERC (Electrical Rules Check)
```bash
kicad-cli sch erc <project.kicad_sch>    # Always run ERC after schematic edits
```

### 4. PCB Layout
```bash
# Operations via volta
/volta '{"op": "pcb_ops", ...}'

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

These bugs have workarounds that MUST be applied in any build script using volta. See KNOWN_LIMITATIONS.md P26-1 through P26-5 for full details.

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

## Agent Rules

- **Automate first.** Before asking a human to run something manually, check the tool inventory above. If a CLI command exists, use it. kicad-cli runs ERC, DRC, exports, renders, and upgrades without opening the GUI.
- **Track in Beads.** Use `mcp__beads__beads_create` for every issue found or task started. Use `mcp__beads__beads_update` to track progress.
- **Never skip validation.** Always run ERC after schematic edits. Always run DRC after layout edits. Always run both before manufacturing export.
- **Native ERC/DRC (Phase 218):** The app now has a pure-Python ERC/DRC engine (`native_erc.py`, `native_drc.py`) that replaces kicad-cli for App Store sandboxed builds. 18 checks + 50 DFM checks. Batch tested against 50 real schematics: 100% pass rate vs kicad-cli. kicad-cli remains as a dev backstop for comparison.
- **Out-of-scope findings must be tracked.** If you find an issue but it's not in the current task, create a Bead with labels "out-of-scope" before continuing.
- **Use volta operations, not raw file edits.** Never directly edit .kicad_sch or .kicad_pcb files with text tools. Use the operation executor for safe AST mutations.
- **3D renders for visual review.** Use `kicad-cli pcb render` to generate PNG/JPEG images for visual inspection instead of asking the user to open KiCad.

## Project Structure

```
src/volta/
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
skills/            — Codex skill definitions
```

## Key Commands

| I want to... | Command |
|-------------|---------|
| Edit a KiCad file | `/volta '<json operation>'` |
| Run ERC | `kicad-cli sch erc <file.kicad_sch>` |
| Run DRC | `kicad-cli pcb drc <file.kicad_pcb>` |
| Export Gerbers | `kicad-cli pcb export gerbers <file.kicad_pcb> -o gerbers/` |
| 3D render | `kicad-cli pcb render <file.kicad_pcb> -o render.png --rotate "-45,0,45"` |
| Export schematic PDF | `kicad-cli sch export pdf <file.kicad_sch> -o sch.pdf` |
| Analyze with AI model | `/volta analyze <file.kicad_pcb>` |
| Check project status | `/volta status` |
| Get project context | `/volta context` |
| View operations help | `/volta help` |

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:970c3bf2 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   bd dolt push
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->

<!-- BEGIN BEADS CODEX SETUP: generated by bd setup codex -->
## Beads Issue Tracker

Use Beads (`bd`) for durable task tracking in repositories that include it. Use the `beads` skill at `.agents/skills/beads/SKILL.md` (project install) or `~/.agents/skills/beads/SKILL.md` (global install) for Beads workflow guidance, then use the `bd` CLI for issue operations.

### Quick Reference

```bash
bd ready                # Find available work
bd show <id>            # View issue details
bd update <id> --claim  # Claim work
bd close <id>           # Complete work
bd prime                # Refresh Beads context
```

### Rules

- Use `bd` for all task tracking; do not create markdown TODO lists.
- Run `bd prime` when Beads context is missing or stale. Codex 0.129.0+ can load Beads context automatically through native hooks; use `/hooks` to inspect or toggle them.
- Keep persistent project memory in Beads via `bd remember`; do not create ad hoc memory files.

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.
<!-- END BEADS CODEX SETUP -->
