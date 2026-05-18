# KiCad Agent -- Operation Reference

This reference documents all operations supported by kicad-agent. Claude uses these schemas to construct valid JSON operations that the Python backend validates and executes against KiCad files.

**Key principle:** The LLM never touches raw S-expressions. It emits structured JSON intents, and the Python tool layer mutates the AST, serializes valid KiCad files, and validates via ERC/DRC gates.

**Supported file types:** `.kicad_sch` (schematic), `.kicad_pcb` (PCB), `.kicad_sym` (symbol library), `.kicad_mod` (footprint library)

**KiCad version:** 10+ only

---

## Available Operations

### Component Operations

#### add_component

Add a component to a schematic or PCB.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"add_component"` |
| `target_file` | string | Relative path to KiCad file (`.kicad_sch` or `.kicad_pcb`) |
| `library_id` | string | Library reference, e.g. `"Device:R_Small_US"` (1-256 chars) |
| `position` | object | Placement coordinates `{x, y}` with optional `angle` (degrees, default 0) |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `reference` | string | `"R?"` | Reference designator (1-64 chars) |
| `value` | string | `""` | Component value (max 256 chars) |

**Example:**

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

---

#### remove_component

Remove a component by reference designator.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"remove_component"` |
| `target_file` | string | Relative path to KiCad file |
| `reference` | string | Reference designator to remove (1-64 chars) |

**Example:**

```json
{
  "root": {
    "op_type": "remove_component",
    "target_file": "motor-driver.kicad_sch",
    "reference": "R1"
  }
}
```

---

#### move_component

Move a component to a new position.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"move_component"` |
| `target_file` | string | Relative path to KiCad file |
| `reference` | string | Reference designator of the component to move (1-64 chars) |
| `position` | object | Target coordinates `{x, y}` with optional `angle` |

**Example:**

```json
{
  "root": {
    "op_type": "move_component",
    "target_file": "motor-driver.kicad_pcb",
    "reference": "U3",
    "position": {"x": 100.0, "y": 50.0, "angle": 180.0}
  }
}
```

---

#### modify_property

Modify a component property (value, footprint, reference, custom field).

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"modify_property"` |
| `target_file` | string | Relative path to KiCad file |
| `reference` | string | Reference designator (1-64 chars) |
| `property_name` | string | Property to modify, e.g. `"Value"`, `"Footprint"` (1-128 chars) |
| `new_value` | string | New property value (max 1024 chars) |

**Example:**

```json
{
  "root": {
    "op_type": "modify_property",
    "target_file": "motor-driver.kicad_sch",
    "reference": "R1",
    "property_name": "Value",
    "new_value": "4.7k"
  }
}
```

---

#### duplicate_component

Duplicate a component with fresh UUID and incremented reference.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"duplicate_component"` |
| `target_file` | string | Relative path to KiCad file |
| `source_reference` | string | Reference designator of the component to duplicate (1-64 chars) |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `offset` | object | `null` | Position offset from source `{x, y}` (angle ignored) |
| `count` | integer | `1` | Number of copies (1-100) |

**Example:**

```json
{
  "root": {
    "op_type": "duplicate_component",
    "target_file": "motor-driver.kicad_sch",
    "source_reference": "R1",
    "offset": {"x": 5.0, "y": 0.0},
    "count": 3
  }
}
```

---

#### array_replicate

Replicate a component in a linear, circular, or matrix array pattern.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"array_replicate"` |
| `target_file` | string | Relative path to KiCad file |
| `source_reference` | string | Reference designator of the component to replicate (1-64 chars) |
| `pattern` | string | Array pattern: `"linear"`, `"circular"`, or `"matrix"` |
| `spacing` | object | Position spacing `{x, y}` with optional `angle` |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `count` | integer | `1` | Number of replications (1-100) |
| `angle_step` | number | `null` | Degrees per step (circular pattern only) |
| `center` | object | `null` | Center point `{x, y}` (circular pattern only) |
| `rows` | integer | `null` | Number of rows (matrix pattern only) |
| `cols` | integer | `null` | Number of columns (matrix pattern only) |

**Example (linear):**

```json
{
  "root": {
    "op_type": "array_replicate",
    "target_file": "motor-driver.kicad_sch",
    "source_reference": "R1",
    "pattern": "linear",
    "count": 4,
    "spacing": {"x": 5.0, "y": 0.0}
  }
}
```

**Example (matrix):**

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

---

### Net Operations

#### add_net

Add a net to a PCB.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"add_net"` |
| `target_file` | string | Relative path to KiCad PCB file (`.kicad_pcb`) |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `net_name` | string | `""` | Net name. Empty triggers auto-generation as `N_<number>` (max 64 chars) |
| `net_number` | integer | `null` | Explicit net number. `null` = auto-assign |

**Example:**

```json
{
  "root": {
    "op_type": "add_net",
    "target_file": "motor-driver.kicad_pcb",
    "net_name": "VCC_3V3"
  }
}
```

---

#### remove_net

Remove a net from a PCB, disconnecting all pads.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"remove_net"` |
| `target_file` | string | Relative path to KiCad PCB file |
| `net_name` | string | Name of the net to remove (1-64 chars) |

**Example:**

```json
{
  "root": {
    "op_type": "remove_net",
    "target_file": "motor-driver.kicad_pcb",
    "net_name": "VCC_3V3"
  }
}
```

---

#### rename_net

Rename a net, propagating to all connected pads.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"rename_net"` |
| `target_file` | string | Relative path to KiCad PCB file |
| `old_name` | string | Current net name (1-64 chars) |
| `new_name` | string | Desired new net name (1-64 chars) |

**Example:**

```json
{
  "root": {
    "op_type": "rename_net",
    "target_file": "motor-driver.kicad_pcb",
    "old_name": "VCC_3V3",
    "new_name": "VCC_3V3_DIGITAL"
  }
}
```

---

### Bus Operations

#### add_bus

Add a bus to a schematic with member nets.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"add_bus"` |
| `target_file` | string | Relative path to KiCad schematic file (`.kicad_sch`) |
| `bus_name` | string | Bus name (1-64 chars) |
| `member_nets` | array | List of net names that belong to this bus (1-32 members, each max 64 chars) |

**Example:**

```json
{
  "root": {
    "op_type": "add_bus",
    "target_file": "motor-driver.kicad_sch",
    "bus_name": "SPI_BUS",
    "member_nets": ["SPI_MOSI", "SPI_MISO", "SPI_SCK", "SPI_CS"]
  }
}
```

---

#### remove_bus

Remove a bus from a schematic.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"remove_bus"` |
| `target_file` | string | Relative path to KiCad schematic file |
| `bus_name` | string | Bus name to remove (1-64 chars) |

**Example:**

```json
{
  "root": {
    "op_type": "remove_bus",
    "target_file": "motor-driver.kicad_sch",
    "bus_name": "SPI_BUS"
  }
}
```

---

### Reference Operations

#### renumber_refs

Renumber component references with configurable prefix and sequencing.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"renumber_refs"` |
| `target_file` | string | Relative path to KiCad schematic file |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `prefix` | string | `""` | Only renumber components with this prefix. Empty = all (max 16 chars) |
| `start_index` | integer | `1` | Starting index for numbering (min 1) |
| `step` | integer | `1` | Step between sequential indices (min 1) |

**Example:**

```json
{
  "root": {
    "op_type": "renumber_refs",
    "target_file": "motor-driver.kicad_sch",
    "prefix": "R",
    "start_index": 1,
    "step": 1
  }
}
```

---

#### validate_refs

Validate that all component references are unique.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"validate_refs"` |
| `target_file` | string | Relative path to KiCad schematic file |

**Example:**

```json
{
  "root": {
    "op_type": "validate_refs",
    "target_file": "motor-driver.kicad_sch"
  }
}
```

---

#### annotate

Auto-assign references to unannotated components (refs ending in `?`).

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"annotate"` |
| `target_file` | string | Relative path to KiCad schematic file |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `prefix_filter` | string | `""` | Only annotate components matching this prefix. Empty = all (max 16 chars) |

**Example:**

```json
{
  "root": {
    "op_type": "annotate",
    "target_file": "motor-driver.kicad_sch",
    "prefix_filter": "R"
  }
}
```

---

#### cross_ref_check

Verify all symbol libIds resolve to entries in the embedded libSymbols.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"cross_ref_check"` |
| `target_file` | string | Relative path to KiCad schematic file |

**Example:**

```json
{
  "root": {
    "op_type": "cross_ref_check",
    "target_file": "motor-driver.kicad_sch"
  }
}
```

---

### Footprint Operations

#### assign_footprint

Assign a footprint to a schematic component.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"assign_footprint"` |
| `target_file` | string | Relative path to KiCad schematic file |
| `reference` | string | Component reference designator, e.g. `"U1"` (1-64 chars) |
| `footprint_lib_id` | string | Footprint library reference, e.g. `"Package_DIP:DIP-8_W7.62mm"` (1-256 chars) |

**Example:**

```json
{
  "root": {
    "op_type": "assign_footprint",
    "target_file": "motor-driver.kicad_sch",
    "reference": "U1",
    "footprint_lib_id": "Package_DIP:DIP-8_W7.62mm"
  }
}
```

---

#### swap_footprint

Swap a PCB footprint while preserving pad-to-net connections.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"swap_footprint"` |
| `target_file` | string | Relative path to KiCad PCB file |
| `reference` | string | Reference designator of the footprint to swap (1-64 chars) |
| `new_footprint_lib_id` | string | New footprint library reference (1-256 chars) |

**Example:**

```json
{
  "root": {
    "op_type": "swap_footprint",
    "target_file": "motor-driver.kicad_pcb",
    "reference": "U3",
    "new_footprint_lib_id": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
  }
}
```

---

#### validate_footprint

Validate that a footprint exists in the available libraries.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"validate_footprint"` |
| `target_file` | string | Relative path to KiCad file |
| `footprint_lib_id` | string | Footprint library reference to validate (1-256 chars) |

**Example:**

```json
{
  "root": {
    "op_type": "validate_footprint",
    "target_file": "motor-driver.kicad_pcb",
    "footprint_lib_id": "Package_DIP:DIP-8_W7.62mm"
  }
}
```

---

#### verify_pin_map

Verify that symbol pin numbers match footprint pad numbers.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"verify_pin_map"` |
| `target_file` | string | Relative path to KiCad file |
| `reference` | string | Component reference designator (1-64 chars) |
| `footprint_lib_id` | string | Footprint library reference to verify against (1-256 chars) |

**Example:**

```json
{
  "root": {
    "op_type": "verify_pin_map",
    "target_file": "motor-driver.kicad_sch",
    "reference": "U1",
    "footprint_lib_id": "Package_DIP:DIP-8_W7.62mm"
  }
}
```

---

## Constraints

All operations must satisfy these constraints. Violations produce clear error messages from the Pydantic validator.

### target_file constraints

- Must be a **relative path** (no leading `/`)
- Must end in `.kicad_sch`, `.kicad_pcb`, `.kicad_sym`, or `.kicad_mod`
- No path traversal (`..` segments)
- No null bytes
- Length: 1-512 characters

### String length limits

| Field | Min | Max |
|-------|-----|-----|
| `reference` | 1 | 64 |
| `library_id` | 1 | 256 |
| `value` | 0 | 256 |
| `property_name` | 1 | 128 |
| `new_value` | 0 | 1024 |
| `net_name` | 0 | 64 |
| `bus_name` | 1 | 64 |
| `member_nets` items | 0 | 64 |
| `footprint_lib_id` | 1 | 256 |
| `prefix` / `prefix_filter` | 0 | 16 |

### Atomic operations

- One mutation per operation (no compound operations)
- One target file per operation
- Operations are wrapped in transactions with automatic rollback on failure

### Count limits

- `duplicate_component.count`: 1-100
- `array_replicate.count`: 1-100
- `add_bus.member_nets`: 1-32 items

---

## Workflow Guidance

### Before editing

1. **Read the target file first** to understand current state. Use `Read` to inspect the KiCad file and understand existing components, nets, and structure.
2. **Use exact reference designators** from the file. References are case-sensitive: `R1` is not the same as `r1`. Power symbols may use `#PWR01` format.
3. **Position coordinates are in millimeters** (mils are not supported).
4. **Check for unannotated components** (references ending in `?`) before operations that require specific designators.

### Constructing operations

1. Wrap the operation object in a `{"root": {...}}` envelope. The `root` key is required by the discriminated union schema.
2. Always include `op_type` as the discriminator field. It determines which operation model validates the rest of the payload.
3. Omit optional fields you do not need -- defaults will be applied.
4. For `position` / `spacing` objects, `x` and `y` are required. `angle` defaults to `0.0` if omitted.

### After editing

1. **Suggest running validation** if ERC/DRC is available for the target file type.
2. **Check round-trip fidelity** by reading the file back to confirm the change was serialized correctly.
3. **Report rollback status** if the operation failed -- the transaction system automatically reverts partial changes.

---

## Error Handling

### target_file validation fails

The error message includes the specific constraint violated:
- `"target_file contains null bytes"` -- null byte injection attempt
- `"target_file must be a relative path"` -- absolute path rejected
- `"target_file must not contain '..' path traversal"` -- path traversal rejected
- `"target_file must be a KiCad file type"` -- wrong extension

### Reference not found

If the specified reference does not exist in the target file, the error suggests listing existing components first. Use `Read` to inspect the file and find valid reference designators.

### Operation execution fails

If execution fails after validation passes, the error includes:
- A description of what went wrong
- A rollback confirmation indicating the file was restored to its pre-operation state
- The operation type and target file for audit traceability

### Net name validation

Net names and bus names reject whitespace-only strings. If a name is `"   "` (spaces only), the validator raises a clear error. Empty string `""` for `add_net.net_name` triggers auto-generation.

---

## Operation Quick Reference

| Operation | File Types | Required Fields |
|-----------|-----------|-----------------|
| `add_component` | sch, pcb | target_file, library_id, position |
| `remove_component` | sch, pcb | target_file, reference |
| `move_component` | sch, pcb | target_file, reference, position |
| `modify_property` | sch, pcb | target_file, reference, property_name, new_value |
| `duplicate_component` | sch, pcb | target_file, source_reference |
| `array_replicate` | sch, pcb | target_file, source_reference, pattern, spacing |
| `add_net` | pcb | target_file |
| `remove_net` | pcb | target_file, net_name |
| `rename_net` | pcb | target_file, old_name, new_name |
| `add_bus` | sch | target_file, bus_name, member_nets |
| `remove_bus` | sch | target_file, bus_name |
| `renumber_refs` | sch | target_file |
| `validate_refs` | sch | target_file |
| `annotate` | sch | target_file |
| `cross_ref_check` | sch | target_file |
| `assign_footprint` | sch | target_file, reference, footprint_lib_id |
| `swap_footprint` | pcb | target_file, reference, new_footprint_lib_id |
| `validate_footprint` | all | target_file, footprint_lib_id |
| `verify_pin_map` | all | target_file, reference, footprint_lib_id |
