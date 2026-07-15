# Feature Request: Contextual Placement Constraints

**Created:** 2026-07-04
**Bead:** volta-24
**Priority:** P1
**Status:** Proposed

## The Problem

PCB schematics capture electrical connectivity but NOT physical placement intent. Experienced designers carry implicit knowledge in their heads that causes board respins when it isn't captured:

> "The switching regulator can't be near the sensitive analog section — EMI coupling will destroy the SNR."

> "J1 is an edge connector — it MUST be on the board edge, oriented so pins face outward."

> "C4 is a decoupling cap for U3 — it needs to be within 5mm of U3's VCC pin or the inductance kills the bypass."

> "LED1 needs to face up — users need to see it from above."

> "The crystal Y1 can't be near the switching node of the buck converter — noise coupling."

> "Mounting holes need to be in specific corners for the enclosure."

These are the "stupid requirements" — the ones experienced designers carry in their head, the ones that cause respins, and the ones that are **completely invisible to the schematic**.

## Current State: Zero Infrastructure

A codebase audit confirmed volta has no model for contextual placement rules:

| Requirement | Exists? | What we have |
|---|---|---|
| Per-component edge/region affinity | **No** | Hardcoded 5mm connector-edge check only |
| Relational avoid (A must not be near B) | **No** | — |
| Relational approach (A must be near B) | **Partial** | `DecouplingConstraint` (IC↔cap only) |
| Orientation/facing | **No** | Rotation is an SA optimization variable |
| Named-region assignment | **Partial** | `zone_partition.py` (static rectangles) |
| Thermal clearance | **Partial** | `ThermalProfile` (power→keepout boxes only) |
| Electrical rules (impedance, current) | **Yes** | Full `ElectricalConstraints` model |
| Fab minimums | **Yes** | `FabProfileConstraints` presets |

## Proposed Architecture

### 1. `PlacementRule` Constraint Model

A new constraint type alongside the existing `ElectricalConstraints` / `MechanicalConstraints`:

```python
@dataclass(frozen=True)
class PlacementRule:
    subject_ref: str          # "J1", "U3", "C4" — component the rule applies to
    rule_type: str            # edge_affinity | avoid | approach | orientation | region
    target: str               # "edge" | "corner:TL" | "U1" | "analog_zone"
    min_mm: float | None      # minimum distance (for avoid)
    max_mm: float | None      # maximum distance (for approach)
    orientation_deg: float | None  # required rotation (for orientation)
    edge_sides: list[str]     # ["top","bottom","left","right"] (for edge_affinity)
    rationale: str            # WHY — "EMI from switching regulator"
    priority: str             # "hard" (gate-enforced) | "soft" (SA penalty)
```

### 2. Rule Types

| Rule type | Example | Enforcement |
|---|---|---|
| **edge_affinity** | "J1 must be within 5mm of board edge on bottom side" | Hard — placement gate fails |
| **avoid** | "U3 at least 25mm from U1" (EMI) | Soft (SA penalty) with hard option |
| **approach** | "C4 within 5mm of U3" (decoupling) | Soft (SA reward) — generalizes DecouplingConstraint |
| **orientation** | "LED1 faces 0° (up)" | Hard — placement gate fails |
| **region** | "U3,U4,U5 in analog_zone" | Soft (SA zone penalty) — generalizes zone_partition |
| **alignment** | "J1,J2,J3 in same row" | Soft (SA penalty) |

### 3. How Requirements Get Captured (the key question)

The "stupid requirements" come from four sources:

**Explicit** — User provides rules:
```python
# Via set_constraints op
{"op_type": "set_constraints", "placement_rules": [
    {"subject_ref": "J1", "rule_type": "edge_affinity", "target": "edge",
     "edge_sides": ["bottom"], "max_mm": 3.0, "priority": "hard",
     "rationale": "USB connector must be accessible from enclosure bottom"},
    {"subject_ref": "U3", "rule_type": "avoid", "target": "U1",
     "min_mm": 25.0, "priority": "soft",
     "rationale": "EMI from switching regulator coupling to analog front-end"},
]}
```

**Inferred** — System infers from component type/function:
- Switching regulator → `avoid` rule for analog section (EMI)
- Connector (J*) → `edge_affinity` rule (must be on edge)
- Decoupling cap → `approach` rule for nearest IC (inductance)
- Crystal → `avoid` rule for switching nodes (noise)
- LED → `orientation` rule (face up)
- Mounting hole (MH*) → `region` rule (corners)

**Learned** — Trained model suggests rules from board topology:
- The SKIDL/SchGen training data angle: convert real boards to Python code, learn the patterns of where components go relative to each other
- This is where the model earns its keep — it's seen 71K boards and knows the implicit rules

**Imported** — From existing design artifacts:
- KiCad text fields (`comment` properties on components)
- Mechanical constraints file (enclosure dimensions)
- Design review notes (free text → parsed by model)
- Datasheet proximity requirements (e.g., "place within 10mm of load")

### 4. Enforcement Pipeline

```
set_constraints (placement_rules)
       ↓
[constraint_gate] — validate rules are well-formed
       ↓
[placement SA] — soft rules → objective penalties/rewards
       ↓
[placement_gate] — hard rules → fail-closed if violated
       ↓
[routing graph] — avoid rules → keepout zones for router
       ↓
[negotiation loop] — placement-aware blocker diagnosis uses rules
       ↓
[AI context] — rules feed model as structured input
```

### 5. Persistence

- Extends `.volta/constraints.json` sidecar (already stores `DesignConstraints`)
- Each rule carries `rationale` — this is the **"why"** that becomes training data for the model
- The sidecar is the bridge between "stupid requirements" and the AI

## Connection to SKIDL + Training Data

This feature connects to the SKIDL research (Bead volta-24 / Phase 107 proposal):

1. **SKIDL code** describes circuits as Python — includes component relationships
2. **Placement rules** capture the spatial intent — not in the schematic, but in constraints
3. **Training pairs**: `(SKIDL circuit code + placement rules) → (placed PCB)` = training data for the model
4. The model learns: "given this circuit and these rules, where do components go?"

This is the pipeline SchGen (Microsoft 2026) and PCBSchemaGen (2026) demonstrated — we have the infrastructure to go further because we have routing + DRC + the full volta pipeline.

## Files That Would Be Affected

| File | Change |
|---|---|
| `validation/gates/constraint_schema.py` | Add `PlacementRule` model |
| `validation/gates/constraint_gate.py` | Enforce placement rules |
| `validation/gates/placement_gate.py` | Check hard rules (fail-closed) |
| `placement/layout_aware.py` | Add rules to SA objective function |
| `placement/zone_partition.py` | Generalize zone assignment from region rules |
| `ops/handlers/constraint_handlers.py` | Accept PlacementRule in `set_constraints` |
| `ops/_schema_constraint.py` | Pydantic schema for the op |

## Why This Matters

Without capturing these requirements, volta produces boards that **route but respin** — they pass DRC but fail in the real world because the implicit knowledge wasn't enforced. This is the gap between "auto-placement that kinda works" and "auto-placement that experienced engineers trust."

The `rationale` field is the key to the AI angle — every rule carries the reason it exists, and those reasons become the training corpus that lets the model eventually infer rules autonomously. The "stupid requirements" aren't stupid — they're the expertise that's currently locked in designers' heads.
