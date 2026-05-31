# Phase 39: Schematic Intelligence — Net Extraction, Topology Inference, Smart Labeling

**Status:** PLANNING
**Requirements:** SCH-INTEL-01, SCH-INTEL-02, SCH-INTEL-03
**Depends on:** Phase 38 (pin resolution, connect_pins)

## Goal

Make kicad-agent understand existing schematic topology — extract nets from wires/labels, infer circuit function, and intelligently manage net names. Today, defining a net topology requires manual analysis of every pin connection. After this phase, the agent can extract existing topology, detect naming conflicts, and suggest corrections.

## Context

After regenerating compressor-stage wiring, I encountered several classes of net naming problems:
- Local label "comp_in" conflicts with global label "COMP_IN" at the same position → `multiple_net_names`
- Power symbol creates net "+9V" but label was "pwr_u21_vdd" → `power_pin_not_driven`
- Net labels at overlapping pin positions create unintended shorts
- No way to verify that a netlist definition matches the actual circuit

## Plans

### Plan 39-01: Net Extraction (SCH-INTEL-01)

**Goal:** Extract the complete net topology from an existing schematic — wires, labels, implied connections.

**Schema:**
```python
class ExtractNetsOp(OpBase):
    op_type: Literal["extract_nets"] = "extract_nets"
    target_file: TargetFile
    include_power: bool = True
    include_unconnected: bool = False
```

**Returns:**
```python
{
    "nets": [
        {
            "name": "COMP_IN",
            "pins": [{"ref": "TP8", "pin": 1, "position": [30.48, 30.48]}, ...],
            "wire_count": 2,
            "label_count": 3,
            "is_global": true
        }
    ],
    "power_nets": ["+9V", "GNDA", "GND", "-9V"],
    "unconnected_pins": [{"ref": "U21", "pin": 3, "position": [...]}],
    "total_nets": 45,
    "total_connections": 120
}
```

**Algorithm:**
1. Parse all wires → build connection graph (wire endpoints connect to pins at same position)
2. Parse all labels → join nets by name (local labels within sheet, global labels across sheets)
3. Parse all power symbols → add power net connections
4. Group connected pins into nets
5. For each net: resolve pin positions, count wires/labels

**Tests:**
- Extract nets from compressor-stage (should find ~45 nets)
- Verify net names match global label names
- Verify power nets are correctly identified

---

### Plan 39-02: Net Name Conflict Detection (SCH-INTEL-02)

**Goal:** Detect and suggest fixes for net naming problems before running ERC.

**Schema:**
```python
class DetectNetConflictsOp(OpBase):
    op_type: Literal["detect_net_conflicts"] = "detect_net_conflicts"
    target_file: TargetFile
```

**Returns:**
```python
{
    "multiple_net_names": [
        {
            "position": [59.69, 78.74],
            "names": ["to_switch", "COMP_BYPASS_SIG"],
            "pins": [{"ref": "R55", "pin": 2}, {"ref": "R56", "pin": 1}],
            "suggested_fix": "R55 pin2 and R56 pin1 overlap at same position — move R56 or merge nets"
        }
    ],
    "local_global_mismatch": [
        {
            "position": [85.09, 59.69],
            "local_name": "+9V",
            "global_name": "+9V",
            "severity": "info"  # same_local_global_label — benign
        }
    ],
    "power_net_mismatch": [
        {
            "power_symbol": "#PWR076",
            "power_net": "+9V",
            "connected_pins": [{"ref": "U21", "pin": 14}],
            "label_at_pin": "+9V",
            "match": true
        }
    ],
    "total_conflicts": 1,
    "total_warnings": 9
}
```

**Checks performed:**
1. Multiple net names at same position (different local labels at same point)
2. Local/global label name mismatches at same position
3. Power symbol net name vs label at connected pins
4. Case-only differences in net names (COMP_IN vs comp_in)
5. Global labels that appear only once (possible orphan)

**Tests:**
- Detect R55/R56 overlap in compressor-stage
- Detect power net name mismatches
- Detect case-only differences

---

### Plan 39-03: Auto-Name Nets from Topology (SCH-INTEL-03)

**Goal:** Given a netlist definition with internal net names, suggest canonical names based on global labels and circuit topology.

**Schema:**
```python
class SuggestNetNamesOp(OpBase):
    op_type: Literal["suggest_net_names"] = "suggest_net_names"
    target_file: TargetFile
    nets: list[NetDefinition]  # Current net definitions with internal names
```

**Returns:**
```python
{
    "renames": [
        {
            "current": "from_switch",
            "suggested": "COMP_BYPASS_SIG",
            "reason": "Global label COMP_BYPASS_SIG exists at pin U21.2 position",
            "pins_affected": ["U21.2", "R56.1"]
        }
    ],
    "power_net_fixes": [
        {
            "current": "pwr_u21_vdd",
            "suggested": "+9V",
            "reason": "Power symbol #PWR076 creates +9V net"
        }
    ]
}
```

**Naming rules:**
1. If a global label exists at any pin position → use that name
2. If a power symbol is connected → use the power net name
3. If net connects to an IC input pin with a recognized function → name by signal (VCA_IN, SC_FILTER)
4. Otherwise → keep the internal name

**Tests:**
- Suggest COMP_BYPASS_SIG for "from_switch"
- Suggest +9V for "pwr_u21_vdd"
- Keep internal names for nets without global labels

---

## Success Criteria

1. `extract_nets` correctly identifies all 45 nets in compressor-stage with pin membership
2. `detect_net_conflicts` finds the R55/R56 pin overlap and all case-mismatch conflicts
3. `suggest_net_names` correctly maps internal names to global label names
4. No regression in existing operations
