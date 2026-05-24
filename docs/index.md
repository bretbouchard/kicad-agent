# kicad-agent

AI-safe structural editing of KiCad schematic, PCB, symbol library, and footprint files.

**LLM -> JSON intent -> AST mutation -> valid KiCad file. Zero corruption, every time.**

## Key Features

- **Zero-corruption editing** -- Every mutation goes through validation gates before commit
- **19 operations** -- Add, remove, move, modify components, nets, buses, references, and footprints
- **ERC/DRC gates** -- Validation runs via kicad-cli after every edit with automatic rollback
- **4 file types** -- Schematic (.kicad_sch), PCB (.kicad_pcb), Symbol Library (.kicad_sym), Footprint (.kicad_mod)
- **CLI interface** -- Schema export, dry-run validation, verbose output
- **AI generation** -- Template board generation with LLM-driven design critique
- **LTspice integration** -- Parse .asc files, inject simulation commands, analyze waveforms
- **GRPO training** -- Reinforcement learning pipeline with neural reward model

## Quick Install

```bash
pip install kicad-agent
```

Requires Python 3.11+ and KiCad 10+ (for ERC/DRC validation).

## Quick Start

```bash
# Print the operation JSON Schema
kicad-agent --schema

# Add a component
kicad-agent '{"root": {"op_type": "add_component", "target_file": "board.kicad_sch", "library_id": "Device:R_Small_US", "position": {"x": 50.0, "y": 30.0}}}'

# Validate without executing
kicad-agent --dry-run operation.json
```

## Documentation

- [Getting Started](getting-started.md) -- Installation and first operation
- [CLI Reference](cli.md) -- Complete command-line documentation
- [API Reference](api/index.md) -- Auto-generated API docs from source
- [Examples](examples/basic-operations.md) -- Walkthroughs with complete JSON operations

## Links

- [GitHub Repository](https://github.com/bretbouchard/kicad-agent)
- [PyPI Package](https://pypi.org/project/kicad-agent/)
- [Issue Tracker](https://github.com/bretbouchard/kicad-agent/issues)
