# Deterministic Checks vs AI Suggestions

**Disclaimer:** The term "deterministic checks" below refers to the gate
enforcement model -- validation rules that always produce the same result
for the same input. This is not a legal warranty of PCB correctness.

## What volta Guarantees (Deterministic)

These checks always produce the same result for the same input. No AI
model is involved.

| Check | What it verifies | Gate |
|-------|-----------------|------|
| ERC clean | No pin conflicts, unconnected pins, unconnected wires | Schematic intent |
| Footprint assigned | Every schematic symbol has a footprint | Schematic intent |
| File format valid | KiCad 10 S-expression format integrity | All gates |
| DRC clean | Copper clearance, pad spacing, track width | Routing quality |
| Components in bounds | All components inside board outline | Placement readiness |
| Net completeness | All nets routed (or flagged as manual) | Routing quality |
| Required exports | Gerbers, drill files, BOM, pick-and-place | Manufacturing readiness |
| BOM completeness | All components have MPN and vendor | Manufacturing readiness |
| Layer match | Export layers match fab profile (2-layer or 4-layer) | Manufacturing readiness |
| Ground planes | Return path exists for power nets | Routing quality |
| Round-trip fidelity | Parse -> modify -> serialize preserves file integrity | Operation executor |
| Transaction safety | Failed operations roll back to pre-operation state | Operation executor |

## What AI Suggests (Non-Deterministic)

These features use AI models and may produce different suggestions
between runs.

| Feature | What it does | Why it's AI |
|---------|-------------|-------------|
| Auto-routing | Suggests trace paths | Path optimization is heuristic |
| Component selection | Suggests MPN alternatives | Requires catalog knowledge |
| Constraint values | Suggests trace widths, spacing | Depends on signal requirements |
| Board analysis | Generates analysis text | Natural language generation |
| Schematic review | Reviews readability | Visual quality assessment |

## How to Tell Which is Which

1. **Gates are always deterministic.** If a check runs through the gate
   system (`volta gate run ...`), it is deterministic.
2. **Operations may use AI.** Operations like `auto_route` or `analyze`
   may invoke AI models. Check the operation documentation.
3. **The audit trail is always truthful.** Gate results include an
   audit trail JSON that shows exactly what was checked and what happened.

## Audit Trail

Every gate run produces an audit trail:

```bash
volta gate run manufacturing_readiness -p /path/to/project --json
```

The `artifacts` array contains a JSON-encoded audit trail with
iteration, blocker, proposal, acceptance, source, and result for each
repair attempt. If no repair was needed, the trail is empty.
