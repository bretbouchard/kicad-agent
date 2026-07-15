# API Reference

volta exposes a Python API organized into subpackages by responsibility. Each module has a specific role in the pipeline:

```
Parser -> IR -> Ops -> Serializer
                 |
                 v
            Validation
```

## Modules

| Module | Responsibility |
|--------|---------------|
| [parser](parser.md) | Parse KiCad files into structured AST (schematic, PCB, symbol, footprint) |
| [ops](ops.md) | 19 operation handlers, Pydantic schema, operation executor |
| [validation](validation.md) | ERC/DRC gates via kicad-cli, structural validation, round-trip checks |
| [serializer](serializer.md) | Write valid KiCad files with UUID re-injection and normalization |
| [handler](handler.md) | Operation validation, execution, and result formatting |
| [analysis](analysis.md) | Net connectivity graph analysis via networkx |
| [crossfile](crossfile.md) | Atomic cross-file operations, library propagation, structural diffs |
| [spatial](spatial.md) | Spatial query engine with Shapely STRtree for clearance and congestion |
| [export](export.md) | Manufacturing export: Gerber generation, BOM output, kicad-cli integration |
| [generation](generation.md) | AI-driven PCB generation with template instantiation and refinement |
| [ltspice](ltspice.md) | LTspice .asc parsing, simulation command injection, waveform analysis |
| [training](training.md) | GRPO reinforcement learning pipeline with neural reward model |
| [project](project.md) | Project-level operations and Analog Devices footprint library |

## Entry Points

The top-level package exposes:

```python
import volta

volta.__version__  # Package version string
```

The two main entry points for programmatic usage are:

- **`volta.handler`** -- Validate and execute operations
- **`volta.cli`** -- Command-line interface

## Usage Pattern

```python
from volta.handler import validate_operation, handle_operation, format_result

# Validate an operation
valid, errors = validate_operation(json_str)

# Execute an operation
result = handle_operation(json_str, project_dir="/path/to/project")

# Format the result
print(format_result(result))
```
