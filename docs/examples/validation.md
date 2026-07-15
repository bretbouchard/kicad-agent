# Validation Examples

Walk through dry-run validation, ERC/DRC checks, and structural validation.

## Dry-Run Validation

Validate an operation without executing it. This checks schema compliance, file existence, and structural constraints.

```bash
# Validate an inline operation
volta --dry-run '{"root": {"op_type": "add_component", "target_file": "board.kicad_sch", "library_id": "Device:R_Small_US", "position": {"x": 50.0, "y": 30.0}}}'

# Validate from a file
volta --dry-run operation.json
```

Dry-run catches:

- Schema violations (missing required fields, invalid values)
- Target file does not exist
- Component reference not found (for move/remove/modify operations)
- Library ID not found in available libraries
- Position out of board bounds

## ERC/DRC Validation

ERC (Electrical Rule Check) and DRC (Design Rule Check) are available through
explicit validation commands and gate operations. Run them before promoting work
to the next PCB design stage.

### When validation runs

1. Run `volta pre-pcb-gate <root.kicad_sch>` before transferring to PCB.
2. Run `volta erc <root.kicad_sch>` after schematic edits.
3. Run `volta drc <board.kicad_pcb>` after PCB/layout edits.
4. Mutation operations use transaction rollback for execution failures.

### Pre-PCB schematic gate

The pre-PCB gate is stricter than basic schematic validation. By default it
requires KiCad 10 format validity, clean ERC, resolved symbols, annotated
references, connected power pins, footprint assignments, grid alignment, symbol
copy consistency, and hierarchical sheet-pin consistency.

```bash
volta pre-pcb-gate path/to/root.kicad_sch
volta pre-pcb-gate path/to/root.kicad_sch --json
```

## Gate-based validation workflow

Gates replace ad-hoc validation with a structured pipeline. Instead of
remembering which checks to run, run the appropriate gate for your
current stage.

### Running gates via CLI

```bash
# Check what stage you're at and what gates are available
volta gate status -p /path/to/project

# Run the schematic intent gate before PCB layout
volta gate run pre_pcb_schematic -p /path/to/project

# Run manufacturing readiness before sending to fab
volta gate run manufacturing_readiness -p /path/to/project
```

### Gate results

Gates return structured results with blockers, warnings, and artifacts:

```
Gate 'placement_readiness': FAIL
  BLOCKER: Component U5 outside board outline
  WARNING: Ground plane coverage below 80% on F.Cu
 - Fix blockers above and retry
```

Only blockers prevent advancement. Warnings are advisory.

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
from volta.handler import validate_operation

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
volta --schema > operation-schema.json
```

The schema is a valid JSON Schema draft-07 document defining all 19 operation types with their fields, constraints, and validation rules.
