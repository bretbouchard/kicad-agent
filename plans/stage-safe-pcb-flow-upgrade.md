# Stage-Safe PCB Flow Upgrade

Date: 2026-06-11

## Purpose

This plan captures the recommended upgrades from the kicad-agent review so another agent can expand them into the existing GSD workflow, write detailed phase plans, and run review gates.

The core shift is from "file-safe KiCad editing" to "stage-safe PCB design." Every major design transition should have a deterministic gate:

- Schematic to PCB
- PCB setup to placement
- Placement to routing
- Routing to manufacturing

LLM output should propose intent and repairs. Deterministic tool gates should decide whether a design can move forward.

## Needed Areas

1. Stage gates

   Current pre-PCB gate is a good start, but the flow needs gates for PCB setup, placement readiness, routing readiness, and manufacturing readiness.

2. Real schematic-to-PCB transfer

   Nets and footprints are still over-simplified. The tool needs a verified path from schematic symbols and pins to PCB footprints, pads, net IDs, net classes, and ratsnest.

3. Component and library truth

   The tool needs to resolve actual symbols, footprints, pin maps, package variants, MPN/LCSC/vendor data, lifecycle, and stock. Stub symbols and placeholder pads should be disallowed outside demos.

4. Constraint capture

   Before layout, the tool needs explicit design intent: current, voltage, impedance, differential pairs, creepage, thermal constraints, connector/mechanical constraints, keepouts, layer count, stackup, and fab capabilities.

5. Manufacturing package completeness

   Gerbers alone are not enough. Need drill, IPC/netlist checks where available, fab notes, stackup, BOM, CPL/position files, DFM profile, assembly exclusions, fiducials/tooling holes, and review artifacts.

6. AI boundary enforcement

   Claude/LLM should propose intent and repairs. Deterministic validation and gates should decide whether proposals can mutate files or advance stages.

## GSD Plan: v4.x Stage-Safe PCB Flow

### Objective

Make `kicad-agent` enforce a credible schematic-to-manufacturing PCB workflow where each stage has deterministic readiness gates, explicit constraints, and verified artifacts.

### Success Criteria

- A design cannot progress from schematic to PCB unless the pre-PCB gate passes.
- A generated PCB contains real footprints, pad-net assignments, and net classes derived from schematic intent.
- Routing only runs after placement and constraints are validated.
- Manufacturing export fails closed unless DRC, DFM, BOM, CPL, drill, Gerbers, and required review artifacts are complete.
- LLM output is advisory unless accepted by schema validation and deterministic gates.

## Phase 85: Gate Architecture

Goal: Define a unified gate model for design stage transitions.

Plans:

1. Add `DesignStage` enum: `schematic`, `pcb_setup`, `placement`, `routing`, `manufacturing`.
2. Add `GateResult` model with `pass`, `blockers`, `warnings`, `artifacts`, `next_actions`.
3. Refactor `pre_pcb_schematic_gate` to use `GateResult`.
4. Add CLI and MCP exposure for `gate status`, `gate run`, and `gate explain`.
5. Add tests proving gates fail closed.

Verification:

- Unit tests for each gate result shape.
- CLI tests for non-zero exit on failed gates.
- MCP schema includes gate operations.

## Phase 86: Schematic Intent Completeness

Goal: Ensure schematic has enough information to produce a meaningful PCB.

Plans:

1. Add footprint assignment completeness check with package variant validation.
2. Add pin-map validation against symbol pins and footprint pads.
3. Add component metadata checks: MPN, value, footprint, datasheet, DNP/exclude flags.
4. Add net intent extraction: power, signal, high-current, differential pair, clock, analog, digital.
5. Add warnings for generic symbols, stubs, missing units, hidden power pins, and ambiguous connectors.

Verification:

- Fixtures for pass/fail schematics.
- Tests for missing footprint, wrong pin map, missing MPN, ambiguous package.
- Pre-PCB gate reports actionable blockers.

## Phase 87: Schematic-to-PCB Transfer Contract

Goal: Replace placeholder PCB generation with verified schematic-derived PCB state.

Plans:

1. Define transfer contract: symbols to footprints to pads to nets to net classes.
2. Implement pad-net assignment from schematic netlist.
3. Verify PCB net IDs match schematic net names.
4. Ensure update-from-schematic runs pre-PCB gate first.
5. Block transfer if stubs or placeholder pads are present.

Verification:

- Golden test: simple resistor LED circuit transfers with correct pad nets.
- Golden test: MCU connector board transfers all pin nets.
- Regression test: no placeholder one-pad footprints in production path.

## Phase 88: Constraint Capture and Propagation

Goal: Capture design constraints before layout.

Plans:

1. Add schema for electrical constraints: current, voltage, impedance, differential pair, length match.
2. Add mechanical constraints: board outline, mounting holes, keepouts, connector lock zones.
3. Add fab profile constraints: min trace, min drill, clearance, layer count, copper weight.
4. Propagate constraints into `.kicad_dru`, net classes, and routing config.
5. Gate PCB setup on complete constraint coverage for nontrivial nets.

Verification:

- Tests for net class creation from constraints.
- Tests for fab profile rejecting impossible rules.
- Gate blocks routing when critical nets lack constraints.

## Phase 89: Placement Readiness Gate

Goal: Ensure placement is electrically and mechanically plausible before routing.

Plans:

1. Validate footprints are inside board outline.
2. Validate courtyard and keepout clearances.
3. Check connector/mechanical positions.
4. Check decoupling proximity, thermal spacing, analog/digital grouping.
5. Check routability heuristics: density, ratsnest length, blocked channels.

Verification:

- Fixture boards with known placement failures.
- Gate reports blocker categories.
- Routing command refuses to run unless placement gate passes or override is explicit.

## Phase 90: Routing Readiness and Quality Gate

Goal: Prevent pathfinding from pretending to be production routing.

Plans:

1. Require board outline, stackup, net classes, constraints, and placement gate pass.
2. Add route quality metrics: completion, vias, clearance, length mismatch, return path risk.
3. Add post-route DRC and unconnected-item check.
4. Add differential-pair and impedance rule checks.
5. Mark A* router as prototype unless route quality gate passes.

Verification:

- Tests for unrouted nets blocking manufacturing.
- Tests for differential-pair mismatch blockers.
- DRC failure prevents manufacturing gate.

## Phase 91: Manufacturing Readiness Gate

Goal: Treat manufacturing as a package, not a Gerber export.

Plans:

1. Require clean DRC and DFM profile pass.
2. Export Gerbers, drill, IPC/netlist where available, BOM, CPL/position, STEP.
3. Validate required layers exist for selected fab profile.
4. Validate BOM rows have MPN/vendor fields unless DNP/excluded.
5. Generate manufacturing manifest with hashes and command provenance.

Verification:

- Fixture board produces complete package.
- Missing drill/BOM/CPL fails gate.
- Manifest includes all generated files and validation results.

## Phase 92: AI Boundary and Repair Loop

Goal: Make the LLM propose, not silently decide.

Plans:

1. Add `Proposal` model for LLM-suggested changes.
2. Require deterministic validation before applying proposals.
3. Add repair workflow: gate failure to classify blockers to propose operations to apply to rerun gate.
4. Track whether each fix was deterministic, local AI, or external LLM.
5. Add audit trail to operation results.

Verification:

- Tests prove failed proposals do not mutate files.
- Gate repair loop stops after max attempts.
- Audit trail identifies AI involvement.

## Phase 93: Golden End-to-End Boards

Goal: Prove the full flow on representative designs.

Fixtures:

1. LED resistor board.
2. Buck regulator.
3. MCU breakout.
4. Op-amp analog front end.
5. Connector-heavy board.
6. Four-layer controlled impedance example.

Verification:

- Each fixture must pass all stage gates.
- Each has expected artifacts.
- CI runs at least the lightweight deterministic checks.

## Phase 94: Docs and UX

Goal: Make the stage-safe workflow obvious.

Plans:

1. Rewrite getting-started around stage gates.
2. Add `kicad-agent status` showing current stage and blockers.
3. Add examples for failing gates and repair workflow.
4. Document what the tool guarantees versus what AI suggests.
5. Add "not manufacturable until" checklist.

## Recommended Priority

Start with Phases 85-87. Those address the biggest current weakness: the gap between a safe KiCad file and a real schematic-to-PCB transfer. Manufacturing and AI repair should come after the transfer contract is reliable.

