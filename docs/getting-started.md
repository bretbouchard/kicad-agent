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

## First Operation

### 1. Print the operation schema

The operation schema defines all valid operations and their fields. It is useful for LLM tool definitions and understanding available operations.

```bash
kicad-agent --schema
```

### 2. Add a component

Create a JSON operation file or pass inline JSON:

```bash
kicad-agent '{
  "root": {
    "op_type": "add_component",
    "target_file": "my_board.kicad_sch",
    "library_id": "Device:R_Small_US",
    "reference": "R1",
    "value": "10k",
    "position": {"x": 50.0, "y": 30.0, "angle": 90.0}
  }
}'
```

This adds a 10k resistor at position (50, 30) with 90-degree rotation in the schematic file `my_board.kicad_sch`.

### 3. Validate with dry-run

Before executing an operation, you can validate it without modifying any files:

```bash
kicad-agent --dry-run operation.json
```

Dry-run validates the operation against the schema, checks file existence, and verifies structural constraints without writing to disk.

### 4. Specify a project directory

If your KiCad files are in a different directory:

```bash
kicad-agent --project-dir /path/to/kicad-project operation.json
```

### 5. Verbose output

For detailed operation output including validation results:

```bash
kicad-agent --verbose operation.json
```

## Next Steps

- [CLI Reference](cli.md) -- All command-line flags and usage patterns
- [Basic Operations Examples](examples/basic-operations.md) -- Walkthrough of common operations
- [Validation Examples](examples/validation.md) -- ERC/DRC validation workflows
- [API Reference](api/index.md) -- Programmatic usage from Python
