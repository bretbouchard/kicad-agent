# Basic Operations

Walk through the most common component operations with complete JSON examples.

## Add Component

Add a new component to a schematic or PCB file.

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

Execute:

```bash
volta add-resistor.json
```

### Key fields

| Field | Required | Description |
|-------|----------|-------------|
| `library_id` | Yes | Symbol library reference (e.g., `Device:R_Small_US`) |
| `target_file` | Yes | Target KiCad file (relative to project directory) |
| `reference` | No | Component reference designator (auto-assigned if omitted) |
| `value` | No | Component value (e.g., "10k", "100nF") |
| `position` | No | Placement coordinates and rotation angle |

## Move Component

Move an existing component to new coordinates.

```json
{
  "root": {
    "op_type": "move_component",
    "target_file": "motor-driver.kicad_pcb",
    "reference": "R1",
    "position": {"x": 75.0, "y": 40.0, "angle": 180.0}
  }
}
```

### Key fields

| Field | Required | Description |
|-------|----------|-------------|
| `reference` | Yes | Component reference to move (e.g., "R1") |
| `position` | Yes | New coordinates and rotation |

## Modify Property

Change a component property (value, footprint, reference, or custom property).

```json
{
  "root": {
    "op_type": "modify_property",
    "target_file": "motor-driver.kicad_sch",
    "reference": "R1",
    "property_name": "value",
    "property_value": "4.7k"
  }
}
```

### Common property names

| Property | Description |
|----------|-------------|
| `value` | Component value |
| `footprint` | Footprint library reference |
| `reference` | Reference designator |
| Any custom name | User-defined property |

## Remove Component

Remove a component and clean up any orphaned net stubs.

```json
{
  "root": {
    "op_type": "remove_component",
    "target_file": "motor-driver.kicad_sch",
    "reference": "R1"
  }
}
```

Removal automatically cleans up:

- Disconnected net wires
- Orphaned net labels
- Unused library symbol entries

## Array Replicate

Replicate a component in a linear, circular, or matrix pattern.

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

### Pattern types

| Pattern | Required fields | Description |
|---------|----------------|-------------|
| `linear` | `count`, `spacing` | Linear array along one axis |
| `circular` | `count`, `center`, `radius` | Circular array around a center point |
| `matrix` | `rows`, `cols`, `spacing` | 2D grid pattern |
