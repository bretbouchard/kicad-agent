# Not Manufacturable Until...

A board is not ready for fabrication until every item on this checklist
passes. Each item maps to a specific gate check.

## Schematic Completeness

- [ ] ERC passes with zero errors
- [ ] Every symbol has a footprint assigned
- [ ] All power pins are connected
- [ ] No unresolved symbols or library references

*Gate: schematic intent (pre_pcb_schematic)*

## Placement

- [ ] All components are inside the board outline
- [ ] No component overlaps
- [ ] Courtyard clearances maintained

*Gate: placement readiness*

## Routing

- [ ] DRC passes with zero violations
- [ ] All nets are routed (or explicitly marked as manual)
- [ ] Ground plane exists for power return paths
- [ ] Differential pairs have matched lengths (within tolerance)

*Gate: routing quality*

## Manufacturing Exports

- [ ] Gerber files generated for all copper layers
- [ ] Drill file generated (through-hole and blind/buried if applicable)
- [ ] BOM generated with MPN and vendor for each component
- [ ] Pick-and-place (centroid) file generated
- [ ] STEP 3D model generated (required for 4-layer boards with mechanical constraints)

*Gate: manufacturing readiness*

## Layer Completeness

- [ ] 2-layer boards: F.Cu, B.Cu, F.Mask, B.Mask, F.SilkS, B.SilkS, Edge.Cuts (7 layers)
- [ ] 4-layer boards: above + In1.Cu, In2.Cu (9 layers)

*Gate: manufacturing readiness (layer check)*

## DFM (Design for Manufacturing)

- [ ] Zero CRITICAL severity DFM findings
- [ ] Minimum trace width meets fab capability
- [ ] Minimum drill size meets fab capability
- [ ] Solder mask slivers within tolerance

*Gate: manufacturing readiness (DFM check)*
