# Gate Repair Workflow Examples

Step-by-step examples of gate failures and how they get resolved
through the repair loop or manual intervention.

## Example 1: Missing Footprint

**Gate:** Schematic intent (pre_pcb_schematic)
**Blocker:** "Footprint not assigned to R3"

```
Gate 'pre_pcb_schematic': FAIL
  BLOCKER: Footprint not assigned to R3
 - Fix the missing footprint assignment and rerun
```

**Resolution:** Add a footprint assignment to R3 in the schematic.

```bash
kicad-agent '{
  "op_type": "assign_footprint",
  "target_file": "board.kicad_sch",
  "reference": "R3",
  "library_id": "Resistor_SMD:R_0603_1608Metric"
}'
```

Rerun the gate:

```bash
kicad-agent gate run pre_pcb_schematic -p /path/to/project
# Gate 'pre_pcb_schematic': PASS
```

## Example 2: DRC Failure During Routing Quality

**Gate:** Routing quality
**Blocker:** "DRC violation: clearance 0.15mm < required 0.2mm on net VCC"

```
Gate 'routing_readiness': FAIL
  BLOCKER: DRC violation: clearance 0.15mm < required 0.2mm on net VCC
 - Fix DRC violations and rerun routing gate
```

**Resolution:** The repair loop detects this as a routing issue and
proposes widening the trace or adjusting clearance constraints.

If the repair loop cannot resolve it automatically, the audit trail
shows the attempt:

```json
[
  {"iteration": 1, "blocker": "DRC violation...", "accepted": false,
   "source": "none", "result": "no_proposal", "rolled_back": false}
]
```

Manual intervention required: adjust the trace width or constraint.

## Example 3: Missing BOM Export

**Gate:** Manufacturing readiness
**Blocker:** "Missing required export: bom"

```
Gate 'manufacturing_readiness': FAIL
  BLOCKER: Missing required export: bom
 - Run manufacturing exports and rerun gate
```

**Resolution:** The repair loop's ManufacturingExportFixProvider proposes
an export operation:

```json
{
  "op_type": "export",
  "export_type": "bom",
  "target_file": "board.kicad_pcb"
}
```

The fix is applied automatically, the gate reruns, and passes:

```
Gate 'manufacturing_readiness': PASS
  Artifacts: manufacturing_manifest.json
```

## Example 4: Multiple Blockers with Partial Fix

**Gate:** Placement readiness
**Blockers:**
- "Component U5 outside board outline"
- "Component C12 overlaps with R8"

```
Gate 'placement_readiness': FAIL
  BLOCKER: Component U5 outside board outline
  BLOCKER: Component C12 overlaps with R8
 - Fix blockers above and retry
```

**Resolution:** The repair loop processes each blocker:

1. **U5 outside outline**: PlacementBoundsFixProvider proposes moving U5
   inside the board outline. Applied successfully.
2. **C12 overlaps R8**: No deterministic fix provider matches. Recorded
   as `no_proposal`.

After iteration 1, the gate reruns. U5 is fixed, but C12 still overlaps.
The audit trail shows:

```json
[
  {"iteration": 1, "blocker": "U5 outside board outline",
   "accepted": true, "source": "deterministic", "result": "applied"},
  {"iteration": 1, "blocker": "C12 overlaps with R8",
   "accepted": false, "source": "none", "result": "no_proposal"}
]
```

Manual intervention: relocate C12 or R8 to resolve the overlap.
