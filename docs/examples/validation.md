# Validation Examples

Walk through dry-run validation, ERC/DRC checks, and structural validation.

## Dry-Run Validation

Validate an operation without executing it. This checks schema compliance, file existence, and structural constraints.

```bash
# Validate an inline operation
kicad-agent --dry-run '{"root": {"op_type": "add_component", "target_file": "board.kicad_sch", "library_id": "Device:R_Small_US", "position": {"x": 50.0, "y": 30.0}}}'

# Validate from a file
kicad-agent --dry-run operation.json
```

Dry-run catches:

- Schema violations (missing required fields, invalid values)
- Target file does not exist
- Component reference not found (for move/remove/modify operations)
- Library ID not found in available libraries
- Position out of board bounds

## ERC/DRC Validation

ERC (Electrical Rule Check) and DRC (Design Rule Check) run automatically after every operation via kicad-cli. If validation fails, the operation is rolled back.

### When validation runs

1. After every component/net operation on a schematic (ERC)
2. After every component/net operation on a PCB (DRC)
3. Files that fail are restored to their pre-operation state

### What ERC checks

- Pin conflicts (output-to-output, power-to-ground)
- Unconnected pins
- Unconnected wires
- Symbol library reference integrity

### What DRC checks

- Copper clearance violations
- Pad-to-pad spacing
- Track width constraints
- Unrouted nets

## Structural Validation

Structural validation checks file integrity independent of electrical rules.

### Round-trip fidelity

Every operation is verified to maintain round-trip fidelity: parse -> modify -> serialize produces byte-identical or semantically equivalent output.

### UUID integrity

UUIDs are extracted before parsing and re-injected after serialization to preserve cross-file references.

## Validation via Handler API

```python
from kicad_agent.handler import validate_operation

# Validate without executing
json_str = '{"root": {"op_type": "add_component", "target_file": "board.kicad_sch", "library_id": "Device:R_Small_US", "position": {"x": 50.0, "y": 30.0}}}'

valid, errors = validate_operation(json_str)

if valid:
    print("Operation is valid")
else:
    print(f"Validation errors: {errors}")
```

## Schema Export

Export the complete operation schema for LLM tool definitions or documentation:

```bash
kicad-agent --schema > operation-schema.json
```

The schema is a valid JSON Schema draft-07 document defining all 19 operation types with their fields, constraints, and validation rules.
