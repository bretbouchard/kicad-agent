# Implement Feature Requests #19 and #22

## Context

Two feature requests on GitHub:
- **#19**: `remove_labels` — batch remove labels by type/name
- **#22**: `snap_components_to_grid` — move all components to grid-aligned positions

Both schemas and handlers already exist. The remaining work is fixing a corrupted file and wiring everything together.

---

## Current State (verified by reading files)

| Component | #19 remove_labels | #22 snap_components_to_grid |
|-----------|-------------------|----------------------------|
| Schema class | Exists in `_schema_remove.py` (corrupted body) | Exists in `_schema_component.py:107-138` |
| Handler | Exists in `handlers/schematic.py:283-330` | Exists in `handlers/schematic.py:58-118` |
| schema.py import | MISSING | MISSING |
| schema.py union | MISSING | MISSING |
| schema.py __all__ | MISSING | MISSING |
| registry.py | MISSING | MISSING |
| Test count | 90 (needs 92) | 90 (needs 92) |

---

## Steps

### 1. Fix `_schema_remove.py` (corrupted RemoveJunctionOp)

Lines 92-98 have the RemoveJunctionOp docstring injected into RemoveLabelsOp's body. RemoveJunctionOp is missing its `class RemoveJunctionOp(BaseModel):` declaration.

Replace lines 91-100 with clean RemoveLabelsOp closing + proper RemoveJunctionOp class:

```python
    remove_all: bool = Field(
        default=False,
        description="Must be True when removing without a names filter.",
    )


class RemoveJunctionOp(BaseModel):
    """Remove a junction dot by UUID.

    Attributes:
        op_type: Discriminator literal ``"remove_junction"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        uuid: UUID of the Junction object to remove.
    """

    op_type: Literal["remove_junction"] = "remove_junction"
```

### 2. Wire into `schema.py`

**Imports** — Add `RemoveLabelsOp` to existing `_schema_remove` import (line 208-213), add `SnapComponentsToGridOp` to existing `_schema_component` import (line 173-181).

**Union** — Add `| RemoveLabelsOp` and `| SnapComponentsToGridOp` to `Operation.root` union.

**__all__** — Add both to exports list.

### 3. Add to `registry.py` `_RAW_CATALOG`

```python
"remove_labels": {
    "category": "remove",
    "description": "Batch remove labels by type and/or name filter",
    "file_types": [".kicad_sch"],
    "is_readonly": False,
    "scope": "single_file",
    "requires": [],
    "conflicts": [],
},
"snap_components_to_grid": {
    "category": "component",
    "description": "Snap all component positions to the nearest grid point",
    "file_types": [".kicad_sch"],
    "is_readonly": False,
    "scope": "single_file",
    "requires": [],
    "conflicts": [],
},
```

### 4. Update counts 90→92

- `tests/test_registry.py:23` — `test_registry_has_90_operations` → `test_registry_has_92_operations`, assert 92
- `tests/test_registry.py:183` — Add `"remove_labels"` to destructive_operations expected set
- `tests/test_registry.py:166` — Add `"snap_components_to_grid"` to component category expected list
- `README.md` — Update operation count
- `skills/SKILL.md` — Update operation count
- `src/kicad_agent/ops/registry.py:3` — Update docstring count
- `src/kicad_agent/ops/schema.py` — Update docstring if it has a count

---

## Files to modify

| File | Change |
|------|--------|
| `src/kicad_agent/ops/_schema_remove.py` | Fix corrupted RemoveJunctionOp class declaration |
| `src/kicad_agent/ops/schema.py` | Import + union + __all__ for both ops |
| `src/kicad_agent/ops/registry.py` | Add both catalog entries |
| `tests/test_registry.py` | Count 90→92, update expected sets |
| `README.md` | Count 90→92 |
| `skills/SKILL.md` | Count 90→92 |

---

## Verification

1. `python3 -m pytest tests/test_registry.py -x -q` — registry completeness passes
2. `python3 -c "from kicad_agent.ops.schema import Operation; print('OK')"` — imports work
3. Full test suite: `python3 -m pytest tests/ -x -q`
4. Close GitHub issues #19 and #22
