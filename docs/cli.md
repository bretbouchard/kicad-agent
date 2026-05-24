# CLI Reference

The `kicad-agent` command-line interface provides schema export, dry-run validation, and operation execution.

## Synopsis

```
kicad-agent [OPTIONS] [OPERATION]
```

## Arguments

| Argument | Description |
|----------|-------------|
| `OPERATION` | JSON operation string or path to a `.json` file containing the operation |

The operation argument can be either an inline JSON string or a path to a JSON file. When the argument ends with `.json`, it is treated as a file path; otherwise, it is parsed as inline JSON.

## Options

### `--schema`

Print the complete operation JSON Schema and exit. The schema defines all 19 operation types, their required and optional fields, value constraints, and validation rules.

```bash
kicad-agent --schema
```

Use this output to configure LLM tool definitions or generate documentation. The schema is a valid JSON Schema draft-07 document.

### `--dry-run`

Validate the operation without executing it. Checks schema compliance, file existence, and structural constraints without modifying any files.

```bash
kicad-agent --dry-run operation.json
```

### `--project-dir`, `-p`

Set the project directory for resolving relative file paths in operations. Default is the current working directory.

```bash
kicad-agent --project-dir /path/to/kicad-project operation.json
```

### `--verbose`, `-v`

Enable verbose output with detailed operation information including validation results, mutation details, and execution timing.

```bash
kicad-agent --verbose operation.json
```

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success -- operation executed and validated without errors |
| `1` | Failure -- operation failed validation or execution |

## Usage Examples

### Print schema for LLM tool definition

```bash
kicad-agent --schema > kicad-operation-schema.json
```

### Execute an inline operation

```bash
kicad-agent '{"root": {"op_type": "add_component", "target_file": "board.kicad_sch", "library_id": "Device:R_Small_US", "position": {"x": 50.0, "y": 30.0}}}'
```

### Execute from a file

```bash
kicad-agent my-operation.json
```

### Validate before executing

```bash
kicad-agent --dry-run --verbose operation.json
```

### Specify project directory

```bash
kicad-agent -p ~/projects/motor-driver add-resistor.json
```

## Programmatic Usage

For Python usage, see the [Handler API Reference](api/handler.md). The CLI is a thin wrapper around `kicad_agent.handler`:

```python
from kicad_agent.handler import handle_operation, format_result

result = handle_operation(json_str, project_dir="/path/to/project")
print(format_result(result))
```
