# Plan: Add `update_footprint_from_library` Operation to volta

## Context

KiCad's "Update Footprints from Library" GUI command is the only way to fix `lib_footprint_mismatch` DRC violations. Neither `kicad-cli` nor the existing volta `swap_footprint` op actually reloads footprint geometry from library files — `swap_footprint` only updates the libId string. We need a new operation that:

1. Reads the current footprint from the PCB (preserving position, rotation, net assignments, reference)
2. Loads the fresh footprint from the library `.kicad_mod` file
3. Replaces the geometry in the PCB while preserving all placement state

## Files to Modify

| File | Change |
|------|--------|
| `~/apps/volta/src/volta/ops/schema.py` | Add `UpdateFootprintFromLibraryOp` class + add to `Operation` union |
| `~/apps/volta/src/volta/ir/pcb_ir.py` | Add `update_footprint_from_library()` method |
| `~/apps/volta/src/volta/ops/executor.py` | Add PCB file-type branching + dispatch for new op |
| `~/apps/volta/src/volta/lib_resolver.py` | **New file** — resolve `lib_id` to `.kicad_mod` file path |
| `~/.claude/skills/volta/prompt.md` | Document new operation |

## Implementation

### 1. New: `lib_resolver.py` — Library Path Resolution

Resolve a `lib_id` like `"Package_TO_SOT_SMD:SOT-223-3_TabPin2"` to an actual `.kicad_mod` file path.

Strategy:
1. Parse project-local `fp-lib-table` in same dir as the PCB file (or parent dirs)
2. Look up the library nickname (`Package_TO_SOT_SMD`) in the table
3. Handle library types:
   - `"KiCad"` — direct `.pretty` directory path
   - `"Table"` — nested fp-lib-table (like the global KiCad table), recurse into it
4. Expand `${KIPRJMOD}` → directory of the `.kicad_pro` or `.kicad_pcb` file
5. Expand `${KICAD10_FOOTPRINT_DIR}` → `/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints`
6. Append `<footprint_name>.kicad_mod` to the resolved `.pretty` directory
7. Validate file exists, raise clear error if not

### 2. Schema: `UpdateFootprintFromLibraryOp`

```python
class UpdateFootprintFromLibraryOp(BaseModel):
    op_type: Literal["update_footprint_from_library"] = "update_footprint_from_library"
    target_file: TargetFile  # Must be .kicad_pcb
    reference: str = Field(min_length=1, max_length=64)  # e.g. "U2"

    # Optional: override the lib_id. If omitted, uses the existing libId from PCB.
    footprint_lib_id: Optional[str] = Field(default=None, min_length=1, max_length=256)
```

If `footprint_lib_id` is `None`, use the footprint's existing `libId` — this is the common case (just refresh from library). If provided, it acts like "swap + update from library" in one step.

Add to `Operation.root` union.

### 3. PCB IR: `update_footprint_from_library()`

```python
def update_footprint_from_library(self, reference: str, lib_id_override: Optional[str] = None) -> dict:
    # 1. Find existing footprint in PCB by reference
    fp = self.get_footprint_by_ref(reference)

    # 2. Determine lib_id (override or existing)
    lib_id = lib_id_override or fp.libId

    # 3. Save state to preserve:
    #    - position (X, Y, angle)
    #    - properties["Reference"] and properties["Value"]
    #    - pad net assignments: {pad.number: Net(number, name)}
    #    - board side / layer

    # 4. Resolve lib_id to .kicad_mod file via lib_resolver
    # 5. Load fresh Footprint from library file via kiutils
    # 6. Replace the footprint object in self.board.footprints list:
    #    - Set position to saved position
    #    - Set properties["Reference"] and properties["Value"]
    #    - For each pad in new footprint, restore net from saved mapping (by pad number)
    #    - Preserve the original footprint's UUID via uuid_map

    # 7. Record mutation
```

Key detail: kiutils Footprint objects can be created from file and then modified. We create a fresh one from the library, then transplant position, properties, and net assignments.

### 4. Executor: PCB File-Type Branching

The executor currently only uses `SchematicIR`. Add file-type detection:

```python
def execute(self, op):
    root = op.root
    file_path = self._base_dir / root.target_file

    if file_path.suffix == ".kicad_pcb":
        return self._execute_pcb(op, file_path)
    else:
        return self._execute_schematic(op, file_path)

def _execute_pcb(self, op, file_path):
    parse_result = parse_pcb(file_path)
    uuid_map = extract_uuids(parse_result.raw_content, "pcb")
    ir = PcbIR(_parse_result=parse_result, _uuid_map=uuid_map)

    with Transaction(file_path) as txn:
        details = self._dispatch_pcb(root.op_type, root, ir, file_path)
        serialize_pcb(parse_result, file_path, uuid_map=uuid_map)
        content = file_path.read_text(encoding="utf-8")
        normalized = normalize_kicad_output(content)
        file_path.write_text(normalized, encoding="utf-8")
        txn.commit()
    return {...}
```

Also move `swap_footprint`, `add_net`, `remove_net`, `rename_net` dispatches to the PCB path (they currently route through SchematicIR which doesn't have these methods for PCB files).

### 5. Skill Prompt: Document New Operation

Add `update_footprint_from_library` section to `prompt.md` following existing patterns.

## Verification

1. **Unit test**: Create a small test that resolves a known lib_id to a file path
2. **Integration test**: Run the operation on `tile-rp16/tile-rp16.kicad_pcb` for footprint U2 (the only lib_footprint_mismatch)
3. **DRC check**: Re-run `kicad-cli pcb drc` to verify the mismatch is resolved
4. **Existing ops**: Verify `swap_footprint` still works (now properly routed through PCB executor path)

## Critical Edge Cases

- **UUID preservation**: kiutils drops UUIDs. The PCB serializer uses `uuid_map` to reinject. After replacing the footprint, new pads won't have UUIDs in the map — they'll get auto-generated by KiCad on next load (acceptable).
- **Pad number mismatch**: If the library footprint has different pad numbers than the PCB instance, nets on missing pads are dropped (with a warning in the result).
- **Global libraries**: The project uses a nested `"Table"` type pointing to the global KiCad fp-lib-table, which uses `${KICAD10_FOOTPRINT_DIR}` env var — must resolve this.
