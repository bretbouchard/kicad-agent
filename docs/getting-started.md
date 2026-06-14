# Getting Started

## Installation

### From PyPI (recommended)

```bash
pip install kicad-agent
```

### With optional dependencies

```bash
# Documentation build tools
pip install "kicad-agent[docs]"

# Development tools (pytest, mypy, ruff)
pip install "kicad-agent[dev]"

# LLM integration (Anthropic API)
pip install "kicad-agent[llm]"

# Everything
pip install "kicad-agent[dev,docs,llm]"
```

### From source

```bash
git clone https://github.com/bretbouchard/kicad-agent.git
cd kicad-agent
pip install .
```

### Requirements

- **Python 3.11+**
- **KiCad 10+** -- Required for ERC/DRC validation via kicad-cli. Install from [kicad.org](https://www.kicad.org/).

## Design Stages

kicad-agent enforces a stage-safe PCB flow. Every board progresses through
five design stages, and gates enforce that each stage is complete before
advancing to the next.

```
SCHEMATIC -> PCB_SETUP -> PLACEMENT -> ROUTING -> MANUFACTURING
```

| Stage | What happens | Gate that advances you |
|-------|-------------|----------------------|
| SCHEMATIC | Capture circuit design | Schematic intent gate |
| PCB_SETUP | Define board outline, layers, constraints | Constraint completeness gate |
| PLACEMENT | Place components on board | Placement readiness gate |
| ROUTING | Connect nets with copper traces | Routing quality gate |
| MANUFACTURING | Export Gerbers, BOM, pick-and-place | Manufacturing readiness gate |

### Why gates?

Gates are deterministic checks that always produce the same result for the
same input. They catch structural problems (missing footprints, unresolved
nets, DRC violations, incomplete exports) before those problems propagate
to downstream stages. A board cannot reach manufacturing with unresolved
schematic issues.

## Running Gates

### Check gate status

```bash
kicad-agent gate status -p /path/to/project
```

Shows the current design stage, registered gates, last gate results, and
suggested next actions.

### Run a specific gate

```bash
kicad-agent gate run pre_pcb_schematic -p /path/to/project
```

### Gate result format

```
Gate 'pre_pcb_schematic': PASS
Gate 'placement_readiness': FAIL
  BLOCKER: Component U5 outside board outline
  BLOCKER: Net VCC has no driven source
 - Fix blockers above and retry
```

- **PASS**: All checks passed. Advance to the next stage.
- **FAIL**: One or more blockers found. Fix the issues and rerun the gate.
- **WARNING**: Non-blocking issues (informational).

## Understanding Gate Results

### Blockers

Blockers are hard failures that prevent stage advancement. Common examples:

- Missing footprint assignment on a schematic symbol
- Component placed outside the board outline
- Unrouted nets after routing stage
- DRC violations (clearance, width constraints)
- Missing manufacturing exports (Gerbers, drill files, BOM)

### Warnings

Warnings are advisory. They do not block stage advancement but should
be reviewed:

- Ground plane on inner layer has void near high-speed trace
- Trace length mismatch on differential pair (within tolerance)

### Repair Loop

When a gate fails, kicad-agent can attempt automatic fixes through the
repair loop. The repair loop:

1. Classifies each blocker
2. Proposes a fix via a deterministic fix provider
3. Validates the proposal against the operation registry
4. Applies the fix through a scoped executor
5. Reruns the gate (up to 3 iterations)

```bash
# The repair loop runs automatically when gate run detects a failure
# with registered fix providers. No separate command needed.
```

See [Gate Repair Workflow](examples/gate-repair-workflow.md) for examples.

## First Board Walkthrough

### 1. Create a schematic

```bash
kicad-agent '{
  "op_type": "add_component",
  "target_file": "my_board.kicad_sch",
  "library_id": "Device:R_Small_US",
  "reference": "R1",
  "value": "10k",
  "position": {"x": 50.0, "y": 30.0, "angle": 90.0}
}'
```

### 2. Run schematic intent gate

```bash
kicad-agent gate run pre_pcb_schematic -p /path/to/project
```

### 3. Check status before placement

```bash
kicad-agent gate status -p /path/to/project
```

### 4. Run DRC after routing

```bash
kicad-agent drc my_board.kicad_pcb
```

### 5. Run manufacturing readiness gate

```bash
kicad-agent gate run manufacturing_readiness -p /path/to/project
```

### 6. Export for manufacturing

```bash
kicad-agent export gerber my_board.kicad_pcb -o gerbers/
kicad-agent export bom my_board.kicad_pcb -o gerbers/
kicad-agent export position my_board.kicad_pcb -o gerbers/
```

## Dry-Run Validation

Before executing any operation, validate it without modifying files:

```bash
kicad-agent --dry-run operation.json
```

## Deterministic Checks vs AI Suggestions

kicad-agent distinguishes between deterministic validation (always produces
the same result) and AI-assisted suggestions (may vary between runs).

See [Deterministic Checks vs AI Suggestions](deterministic-checks-vs-ai-suggestions.md)
for the full breakdown.

## Not Manufacturable Until

A quick checklist of what must pass before a board can go to fabrication.

See [Not Manufacturable Until](not-manufacturable-until.md).

## Next Steps

- [CLI Reference](cli.md) -- All command-line flags and usage patterns
- [Basic Operations Examples](examples/basic-operations.md) -- Walkthrough of common operations
- [Gate Repair Workflow](examples/gate-repair-workflow.md) -- Step-by-step gate failure repair
- [Validation Examples](examples/validation.md) -- ERC/DRC validation workflows
- [API Reference](api/index.md) -- Programmatic usage from Python
