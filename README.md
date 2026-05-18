# kicad-agent

AI-safe structural editing of KiCad schematic, PCB, symbol library, and footprint files. The LLM never touches raw S-expressions — it emits structured JSON intents, and the Python backend mutates the AST, serializes valid KiCad files, and validates via ERC/DRC gates.

**LLM → JSON intent → AST mutation → valid KiCad file. Zero corruption, every time.**

## Why This Exists

KiCad files are deeply nested S-expressions with strict ordering constraints, fragile UUID/symbol references, and implicit electrical relationships. Generic LLMs fail on KiCad files because:

- Parentheses nesting is deep and ordering matters
- UUIDs and symbol references are fragile — one typo corrupts the file
- Tiny syntax mistakes break the entire design
- Semantic relationships (nets, pins, connectivity) are implicit

kicad-agent solves this with **constrained structural editing** — the AI emits operations, never raw text. Every mutation goes through validation gates before commit.

## Supported File Types

| File | Extension | Description |
|------|-----------|-------------|
| Schematic | `.kicad_sch` | Circuit schematics |
| PCB Layout | `.kicad_pcb` | Board layouts |
| Symbol Library | `.kicad_sym` | Component symbol definitions |
| Footprint Library | `.kicad_mod` | Footprint definitions |

**KiCad 10+ only.**

## Install

```bash
# Clone and install
git clone https://github.com/bretbouchard/kicad-agent.git
cd kicad-agent
pip install .

# Or install with dev dependencies
pip install ".[dev]"
```

**Requirements:** Python 3.11+, [KiCad 10+](https://www.kicad.org/) (for ERC/DRC validation)

**Dependencies:** [kiutils](https://github.com/mvnmgr/kiutils) (KiCad AST), [sexpdata](https://github.com/tkf/sexpdata) (S-expression parsing), [networkx](https://networkx.org/) (connectivity graphs)

## CLI Usage

```bash
# Print the operation JSON Schema (useful for LLM tool definitions)
kicad-agent --schema

# Run an operation from inline JSON
kicad-agent '{"root": {"op_type": "add_component", "target_file": "board.kicad_sch", "library_id": "Device:R_Small_US", "position": {"x": 50.0, "y": 30.0}}}'

# Run an operation from a file
kicad-agent operation.json

# Validate without executing (dry-run)
kicad-agent --dry-run operation.json

# Specify project directory
kicad-agent -p /path/to/kicad-project operation.json

# Verbose output with operation details
kicad-agent -v operation.json
```

## Claude Code Skill

kicad-agent ships as a Claude Code skill for AI-assisted KiCad editing. Install it by copying the skill definition:

```bash
# Copy skill files to your Claude Code skills directory
mkdir -p ~/.claude/skills/kicad-agent
cp skills/SKILL.md ~/.claude/skills/kicad-agent/
cp skills/prompt.md ~/.claude/skills/kicad-agent/
```

Then invoke from any KiCad project:

```
/kicad-agent add a 10k resistor at position 50,30
/kicad-agent status
/kicad-agent context
/kicad-agent help
```

The skill routes natural language requests through the Python backend — Claude constructs valid JSON operations, the backend validates and executes them, and results are returned as formatted text.

## Operations Reference

19 operations across 5 categories:

### Component Operations

| Operation | Files | Description |
|-----------|-------|-------------|
| `add_component` | sch, pcb | Add a component with library reference, position, value |
| `remove_component` | sch, pcb | Remove a component and clean up net stubs |
| `move_component` | sch, pcb | Move a component to new coordinates |
| `modify_property` | sch, pcb | Change a component property (value, footprint, reference, custom) |
| `duplicate_component` | sch, pcb | Duplicate with fresh UUID and incremented reference |
| `array_replicate` | sch, pcb | Replicate in linear, circular, or matrix pattern |

### Net Operations

| Operation | Files | Description |
|-----------|-------|-------------|
| `add_net` | pcb | Add a named or auto-named net |
| `remove_net` | pcb | Remove a net and disconnect all pads |
| `rename_net` | pcb | Rename a net across all connected pads |

### Bus Operations

| Operation | Files | Description |
|-----------|-------|-------------|
| `add_bus` | sch | Add a bus with member nets |
| `remove_bus` | sch | Remove a bus from the schematic |

### Reference Operations

| Operation | Files | Description |
|-----------|-------|-------------|
| `renumber_refs` | sch | Renumber references with configurable prefix and sequence |
| `validate_refs` | sch | Check all references are unique |
| `annotate` | sch | Auto-assign references to unannotated components (R? → R1) |
| `cross_ref_check` | sch | Verify all symbol libIds resolve to embedded libSymbols |

### Footprint Operations

| Operation | Files | Description |
|-----------|-------|-------------|
| `assign_footprint` | sch | Assign a footprint to a schematic component |
| `swap_footprint` | pcb | Swap a PCB footprint preserving pad-to-net connections |
| `validate_footprint` | all | Verify a footprint exists in available libraries |
| `verify_pin_map` | all | Check symbol pin numbers match footprint pad numbers |

### Example: Add a Component

```json
{
  "root": {
    "op_type": "add_component",
    "target_file": "motor-driver.kicad_sch",
    "library_id": "Device:R_Small_US",
    "reference": "R1",
    "value": "10k",
    "position": {"x": 50.0, "y": 30.0, "angle": 90.0}
  }
}
```

### Example: Array Replicate

```json
{
  "root": {
    "op_type": "array_replicate",
    "target_file": "motor-driver.kicad_pcb",
    "source_reference": "LED1",
    "pattern": "matrix",
    "spacing": {"x": 3.0, "y": 3.0},
    "rows": 3,
    "cols": 4
  }
}
```

See the [full operation reference](skills/prompt.md) for all field descriptions, constraints, and examples.

## Architecture

```
LLM / CLI
    │
    ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Parser     │────▶│     IR      │────▶│   Ops       │────▶│  Serializer │
│              │     │             │     │             │     │             │
│ S-expression │     │ Intermediate│     │ 19 atomic   │     │ Valid KiCad │
│ → AST        │     │ representation│   │ operations  │     │ S-expression│
│              │     │ + mutation  │     │ + executor  │     │ + normalize │
│ 4 file types │     │ tracking    │     │             │     │             │
└─────────────┘     └─────────────┘     └──────┬──────┘     └─────────────┘
                                                │
                                    ┌───────────▼───────────┐
                                    │      Validation       │
                                    │                       │
                                    │ ERC/DRC via kicad-cli │
                                    │ Structural checks     │
                                    │ Round-trip fidelity   │
                                    │ Auto-rollback         │
                                    └───────────────────────┘
```

### Module Structure

| Module | Purpose |
|--------|---------|
| `src/kicad_agent/parser/` | Parse KiCad files into structured AST (schematic, PCB, symbol, footprint) |
| `src/kicad_agent/ir/` | Intermediate representation with mutation tracking and transactions |
| `src/kicad_agent/ops/` | 19 operation handlers, Pydantic schema, operation executor |
| `src/kicad_agent/serializer/` | Write valid KiCad files with UUID re-injection and normalization |
| `src/kicad_agent/validation/` | ERC/DRC gates via kicad-cli, structural validation, round-trip checks |
| `src/kicad_agent/crossfile/` | Atomic cross-file operations, library propagation, structural diffs |
| `src/kicad_agent/analysis/` | Net connectivity graph analysis via networkx |
| `src/kicad_agent/handler.py` | Operation validation and result formatting |
| `src/kicad_agent/cli.py` | Terminal interface |

### Key Design Decisions

- **JSON operation schema** — The LLM emits structured intents, never raw S-expressions. Pydantic validates every operation before execution.
- **Transaction safety** — Every mutation is wrapped in a transaction with automatic rollback on failure.
- **ERC/DRC gates** — Validation runs via `kicad-cli` after every edit. Files that fail validation are rolled back.
- **Round-trip fidelity** — Parse → modify → serialize produces byte-identical or semantically equivalent output.
- **UUID integrity** — UUIDs are extracted before parsing and re-injected after serialization to preserve references.
- **Atomic operations** — One mutation per operation, one target file per operation. No compound operations.

## Development

```bash
# Install with dev dependencies
pip install ".[dev]"

# Run tests (459 tests)
pytest

# Run with coverage
pytest --cov=kicad_agent --cov-report=term-missing

# Lint
ruff check src/ tests/

# Type check
mypy src/
```

## Project Status

All 7 phases complete. 459 tests passing.

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Parse, serialize, round-trip all 4 file types | Complete |
| 2 | Operation schema and IR layer | Complete |
| 3 | Validation pipeline (ERC/DRC, structural, rollback) | Complete |
| 4 | Component operations (add, remove, duplicate, move, modify) | Complete |
| 5 | Net, reference, and footprint operations | Complete |
| 6 | Cross-file operations and analysis | Complete |
| 7 | GSD Skill integration and CLI | Complete |

## License

MIT
