# Phase 157 — Floor Planner

**Goal:** A declarative YAML floor-plan spec (`.floorplan.yaml`) that captures design intent — functional zones, locked anchors, keepouts, decoupling pairs, power isolation, ground-pour prep, multi-strip replication — and a lowering pass that compiles it into the existing `LayoutAwarePlacer` vectors. Applied as a **post-populate, pre-Quilter stage** so Quilter starts from an engineering-aware configuration instead of blind grid packing.

**Depends on:** Phase 156 (SKIDL Circuit provides module-aware hierarchy metadata for zone-aware placement)
**Requirements:** FLOOR-01, FLOOR-02, FLOOR-03, FLOOR-04, FLOOR-05, FLOOR-06, FLOOR-07, FLOOR-08, FLOOR-09
**Research basis:** `.planning/research/ARCHITECTURE-FLOORPLAN.md`
**Integration target:** `analog-ecosystem/.../mono-arch/gen_pcb.py`

---

## Design Principles

1. **Reuse, don't rebuild.** kicad-agent already has the four primitives a floor planner needs — `ZoneDefinition` (ops/_schema_placement.py:111), the `PCBConstraint` hierarchy (constraints/types.py), `SignalFlowGrouper` (placement/signal_flow.py), and `LayoutAwarePlacer` (placement/layout_aware.py:156). The floor planner is a **source-of-truth spec + a lowering pass** into those vectors — not a parallel engine.
2. **Own the source-of-truth; emit KiCad-native artifacts.** KiCad has no native "rooms/floor-plan" concept (confirmed in research Q2). The YAML spec is the *only* place this intent lives. It lowers into `(locked)` tokens + keepout `gr_poly`/`zone` objects that *are* KiCad-native.
3. **Fail closed.** On any validation error, `apply_floor_plan` returns the raw PCB unmodified + a violations list, so `gen_pcb.py` falls back to grid placement rather than producing a malformed board.
4. **Each wave is independently shippable and reversible.** Delete the `.floorplan.yaml` → original grid placement (zero behavior change).
5. **Contextual placement rules capture implicit knowledge (Bead kicad-agent-24).** The `placement_rules` section captures the "stupid requirements" — edge affinity, EMI avoidance, decoupling proximity, orientation, region membership. Each rule carries a `rationale` field (the "why") that becomes training data for Phase 159. Rules lower into SA objective penalties (soft) or placement-gate failures (hard), and into routing keepouts for the negotiation loop (Phase 105).

### Critical constraint from research (Q3)

`populate_pcb_from_netlist` (`crossfile/pcb_populate.py`) does **not** accept a floor plan — its signature has no `fixed_positions`/`keepout_zones` parameter, and internally it calls `auto_place_grid()` (a pure grid packer). Therefore the floor plan **cannot be injected into the populate call; it must be applied after.** This is the defining architectural decision: floor planning is a *post-populate repositioning* stage, not a populate-time input.

---

## New Module: `src/kicad_agent/floorplan/`

```
src/kicad_agent/floorplan/
├── __init__.py      # public exports: FloorPlanSpec, load_floor_plan, apply_floor_plan
├── spec.py          # FloorPlanSpec Pydantic models (board, zones, pre_placed, keepout, constraints, replicate, ground_pour)
├── parser.py        # load_floor_plan(path) -> FloorPlanSpec  (YAML → Pydantic + validation)
├── lower.py         # lowering: FloorPlanSpec → LayoutAwarePlacer vectors (fixed_positions, keepout_zones, constraints)
├── replicate.py     # expand replicate directive ({n} templates, netlist-driven prefix detection)
├── emission.py      # PCB emission: (locked) tokens, gr_poly keepouts, zone blocks (ground pour)
└── applier.py       # apply_floor_plan(pcb_raw, spec, components, nets) -> (pcb_raw, result)  — orchestrator
```

**Why a top-level `floorplan/` subpackage (not `placement/floorplan.py`)?** The task specifies this location. It is a cohesive subsystem with 6 concerns (parse, lower, replicate, emit, apply, spec) that would bloat a single file. It re-imports from `placement/`, `constraints/`, and `ops/pcb_raw_writer.py` rather than duplicating logic.

### Reused primitives (no duplication)

| Floor-plan concept | Existing primitive | Location |
|---|---|---|
| Zones | `ZoneDefinition` | `ops/_schema_placement.py:111` |
| Zone → keepout conversion | `build_keepouts_from_zone` | `placement/zone_partition.py:87` |
| Ref → zone assignment | `assign_to_zone` | `placement/zone_partition.py:11` |
| Decoupling / thermal / clearance | `DecouplingConstraint`, `ThermalConstraint`, `ClearanceConstraint` | `constraints/types.py:125,142,93` |
| Placement engine | `LayoutAwarePlacer` / `LayoutAwareRequest` | `placement/layout_aware.py:156,82` |
| Move footprint | `PcbRawWriter.modify_footprint_position` | `ops/pcb_raw_writer.py:423` |
| Lock token | `PcbRawWriter._inject_locked_token` | `ops/pcb_raw_writer.py:801` |
| Footprint block finder | `PcbRawWriter._find_footprint_block` | `ops/pcb_raw_writer.py:978` |
| Mounting-hole exclusion | `PcbRawWriter.build_exclusion_zones` | `ops/pcb_raw_writer.py:1069` |
| Ground-pour zone S-expr | `PcbRawWriter.build_zone_sexp` | `ops/pcb_raw_writer.py:81` |
| Placement scoring (test) | `PlacementScorer` | `placement/scoring.py:229` |

---

## YAML Schema Definition (`.floorplan.yaml`)

Validated by `FloorPlanSpec` Pydantic model in `floorplan/spec.py`. The schema is a **thin extension** of `ZoneDefinition` + `PCBConstraint` — it adds only what those lack: a board header, a `pre_placed` anchor list, a `replicate` directive, and a `ground_pour` section.

```yaml
# mono-blade.floorplan.yaml
schema_version: 1

board:
  width_mm: 40.0          # must match gen_pcb.py --width
  height_mm: 200.0        # must match gen_pcb.py --height
  layers: [F.Cu, In1.Cu, In2.Cu, B.Cu]
  edge_clearance_mm: 3.0  # auto-keepout band inside board edge

# --- Functional zones (reuses ZoneDefinition vocabulary) ---
# zones: auto           # ← opt into SignalFlowGrouper derivation instead of explicit list
zones:
  - name: power
    x_range: [0, 8]
    y_range: [0, 200]
    fill_order: top-to-bottom
    priority_refs: [J1]                  # blade power connector
  - name: input
    x_range: [8, 16]
    y_range: [0, 200]
    fill_order: top-to-bottom
    priority_refs: []                    # filled by signal-flow + assign_to_zone
  - name: preamp
    x_range: [16, 24]
    y_range: [0, 200]
    fill_order: top-to-bottom
    priority_refs: [U_PRE]               # THAT340
  - name: vca
    x_range: [24, 30]
    y_range: [0, 200]
    fill_order: top-to-bottom
    priority_refs: [U_VCA]               # THAT4301
  - name: output
    x_range: [30, 40]
    y_range: [0, 200]
    fill_order: top-to-bottom
    priority_refs: [U_OUT]               # NE5532 output buffer

# --- Pre-placed / locked anchors (reuses fixed_positions dict) ---
# Format: ref: [x, y, angle_degrees]
pre_placed:
  H1: [3.0, 3.0, 0.0]        # mounting holes — corner anchors
  H2: [37.0, 3.0, 0.0]
  H3: [3.0, 197.0, 0.0]
  H4: [37.0, 197.0, 0.0]
  J1: [4.0, 100.0, 90.0]     # blade connector at left edge

# --- Keepout zones (reuses keepout_zones tuple list) ---
# 4-tuple = axis-aligned rectangle; optional 5th element = semantic label
keepout_zones:
  - [0, 0, 40, 3, "edge_top"]
  - [0, 197, 40, 200, "edge_bottom"]
  - [0, 0, 3, 200, "edge_left"]
  - [37, 0, 40, 200, "edge_right"]

# --- Constraints (reuses PCBConstraint hierarchy, JSON-encoded) ---
constraints:
  - type: DECOUPLING
    ic_ref: U_PRE
    cap_ref: C_PRE_100N
    max_distance_mm: 5.0
    priority: critical
    confidence: 0.95
    source_rule: floorplan_yaml
  - type: DECOUPLING
    ic_ref: U_VCA
    cap_ref: C_VCA_100N
    max_distance_mm: 5.0
    priority: critical
    confidence: 0.95
    source_rule: floorplan_yaml
  - type: THERMAL
    component_refs: [U_PRE, U_VCA]
    heat_dissipation_w: 1.5
    max_junction_temp_c: 125
    thermal_resistance_c_per_w: 40
    confidence: 0.8
    source_rule: floorplan_yaml
  - type: CLEARANCE
    min_clearance_mm: 1.5
    net_class_name: "mains"
    confidence: 0.9
    source_rule: floorplan_yaml

# --- Contextual placement rules (Bead kicad-agent-24) ---
# Capture the "stupid requirements" — implicit design knowledge not in the schematic.
# Each rule carries a rationale (the "why") — this becomes training data for AI (Phase 159).
placement_rules:
  # Edge affinity: component must be on/near the board edge
  - subject_ref: J1
    rule_type: edge_affinity
    target: edge
    edge_sides: [bottom]         # must be on bottom edge
    max_mm: 3.0                  # within 3mm of the edge
    priority: hard               # gate-enforced (fail-closed)
    rationale: "Blade connector must be accessible from enclosure slot"

  # Avoid: two components must not be near each other (EMI, noise coupling)
  - subject_ref: U_PRE          # preamp (sensitive analog)
    rule_type: avoid
    target: U_REG               # switching regulator
    min_mm: 25.0
    priority: hard
    rationale: "EMI from switching regulator coupling to analog front-end degrades SNR"

  # Approach: two components must be near each other (decoupling, signal integrity)
  - subject_ref: C_PRE_100N     # decoupling cap
    rule_type: approach
    target: U_PRE               # the IC it decouples
    max_mm: 5.0
    priority: hard
    rationale: "Decoupling inductance — cap must be close to IC power pin"

  # Orientation: component must face a specific direction
  - subject_ref: LED_PWR
    rule_type: orientation
    target: fixed
    orientation_deg: 0          # faces up (visible from top)
    priority: hard
    rationale: "Power LED must be visible from above the enclosure"

  # Region: component must be in a named zone (generalizes zone_partition)
  - subject_ref: U_VCA
    rule_type: region
    target: preamp              # must be in the preamp zone (defined above)
    priority: soft              # SA penalty
    rationale: "VCA belongs in the analog signal chain"

  # Alignment: group of components must be aligned
  - subject_ref: [CH1_OUT, CH2_OUT, CH3_OUT]
    rule_type: alignment
    target: row                 # same Y coordinate
    priority: soft
    rationale: "Channel output connectors should be visually aligned"

# --- Multi-strip replication (NEW construct) ---
# Two supported forms — see Wave 5. Form B (netlist-driven) is production default.
replicate:
  detect_prefix: "CH"        # scan nets for CH1_*, CH2_*, ... (Form B)
  # count: 16                # explicit count (Form A, overrides detection)
  net_prefix: "CH{n}_"
  pitch_mm: 9.0
  origin: [10.0, 10.0]
  template: ch_strip         # refs use CH{n}_ wildcards

# --- Ground-pour preparation (NEW construct) ---
ground_pour:
  layers: [F.Cu, B.Cu]
  net: GND
  exclude_zones: [power]     # cross-references zones[].name — don't pour over switcher
  thermals: true
  star_point: [4.0, 100.0]   # single ground reference (ferrite bead / FB_0R)
  clearance_mm: 0.5
  isolated_pours:
    - net: GNDA              # analog ground, star-tied at star_point
      layers: [F.Cu]
      within: [8, 0, 40, 200]
```

### FloorPlanSpec model outline (`floorplan/spec.py`)

```python
class BoardSpec(BaseModel):
    width_mm: float = Field(gt=0)
    height_mm: float = Field(gt=0)
    layers: list[str] = Field(default=["F.Cu", "B.Cu"])
    edge_clearance_mm: float = Field(default=3.0, ge=0)

class ZoneSpec(BaseModel):           # mirrors ZoneDefinition + optional
    name: str
    x_range: tuple[float, float]
    y_range: tuple[float, float]
    fill_order: Literal["left-to-right","right-to-left","top-to-bottom","bottom-to-top"] = "left-to-right"
    priority_refs: list[str] = []

class KeepoutSpec(BaseModel):
    rect: tuple[float, float, float, float]   # (x1,y1,x2,y2)
    label: str = ""

class ConstraintSpec(BaseModel):     # discriminated union by `type`
    type: Literal["DECOUPLING","THERMAL","CLEARANCE","IMPEDANCE","DIFFERENTIAL_PAIR"]
    # ...type-specific optional fields, lowered to PCBConstraint subclasses in lower.py

class ReplicateSpec(BaseModel):
    count: int | None = None
    detect_prefix: str | None = None
    net_prefix: str                   # "CH{n}_"
    pitch_mm: float
    origin: tuple[float, float]
    template: str | dict | None = None

class GroundPourSpec(BaseModel):
    layers: list[str]
    net: str
    exclude_zones: list[str] = []
    thermals: bool = True
    star_point: tuple[float, float] | None = None
    clearance_mm: float = 0.5
    isolated_pours: list[IsolatedPourSpec] = []

class FloorPlanSpec(BaseModel):
    schema_version: Literal[1] = 1
    board: BoardSpec
    zones: list[ZoneSpec] | Literal["auto"] = []
    pre_placed: dict[str, tuple[float, float, float]] = {}
    keepout_zones: list[KeepoutSpec | list] = []   # accepts inline lists or objects
    constraints: list[ConstraintSpec] = []
    replicate: ReplicateSpec | None = None
    ground_pour: GroundPourSpec | None = None
```

### Validators (fail closed — research §"Validation & Failure Modes")

1. **Zone coverage** — every `priority_ref` falls inside some zone's bounds.
2. **Pre-placed inside board** — every `pre_placed` coordinate within `[0,width]×[0,height]` minus edge margin.
3. **Keepout non-annihilation** — no keepout fully covers a zone (would make it unplaceable).
4. **Replicate count vs 500-component cap** — `sum(strip_parts) × count ≤ 500` (the `_MAX_COMPONENTS` cap in `HybridPlacementEngine` and `max_length=500` on `AutoPlaceOp.component_refs`).
5. **Net-prefix existence** — `replicate.net_prefix`/`detect_prefix` matches ≥1 net in the netlist.
6. **Constraint ref existence** — every `ic_ref`/`cap_ref`/`component_refs` entry resolves to a real component.

---

## Wave-Based Task Breakdown

Each wave is independently shippable. Later waves depend only on the *interface* of earlier waves (not internal implementation), so Waves 2–6 can be parallelized once Wave 1's `FloorPlanSpec` model is frozen.

### Wave 1 — Spec & Loader (FLOOR-01)
**Goal:** `FloorPlanSpec` Pydantic model + YAML loader with full validation. No behavior change — validate only, do not apply. Ship a sample `mono-blade.floorplan.yaml`.

**Files:**
- `src/kicad_agent/floorplan/__init__.py` (new)
- `src/kicad_agent/floorplan/spec.py` (new) — all Pydantic models above
- `src/kicad_agent/floorplan/parser.py` (new) — `load_floor_plan(path: Path) -> FloorPlanSpec`
- `tests/floorplan/test_spec.py` (new) — model + validator unit tests
- `tests/floorplan/test_parser.py` (new) — YAML round-trip + error cases
- `tests/fixtures/floorplan/mono-blade.floorplan.yaml` (new) — canonical sample
- `tests/fixtures/floorplan/invalid-*.yaml` (new) — one per validator (6 negative fixtures)

**Tasks:**
- [ ] W1-1: Define `BoardSpec`, `ZoneSpec`, `KeepoutSpec`, `ConstraintSpec`, `ReplicateSpec`, `GroundPourSpec`, `IsolatedPourSpec`, `FloorPlanSpec` in `spec.py`. Re-import `ZoneDefinition` fields to avoid drift.
- [ ] W1-2: Implement 6 validators as Pydantic `@model_validator(mode="after")` methods on `FloorPlanSpec` (zone coverage, board bounds, keepout non-annihilation, replicate cap, net-prefix existence, constraint-ref existence). Validators 5 & 6 require the component/net list → accept optional `components`/`nets` args via a `validate_against_netlist()` method (Pydantic validators run at parse time without netlist; the cross-check is a second pass).
- [ ] W1-3: Implement `load_floor_plan(path)` in `parser.py`: read YAML via `pyyaml` (already a dep, `PyYAML>=6.0`, confirmed 6.0.2), parse into `FloorPlanSpec`. Accept inline-list keepouts `[[x1,y1,x2,y2,"label"], ...]` by normalizing to `KeepoutSpec`.
- [ ] W1-4: Write `tests/fixtures/floorplan/mono-blade.floorplan.yaml` mirroring the mono blade (40×200mm, 5 zones, 4 mounting holes, decoupling pairs for U_PRE/U_VCA/U_OUT).
- [ ] W1-5: Write 6 negative fixtures (`invalid-zone-coverage.yaml`, `invalid-board-bounds.yaml`, etc.) + tests asserting each raises with a specific message.
- [ ] W1-6: `__init__.py` exports: `FloorPlanSpec`, `load_floor_plan`, and (forward-declared) `apply_floor_plan`.

**Acceptance:** `load_floor_plan` parses the sample YAML into a valid `FloorPlanSpec`; all 6 negative fixtures fail validation with clear messages. Zero changes to `gen_pcb.py`. Coverage ≥90% on `floorplan/spec.py` + `floorplan/parser.py`.

---

### Wave 2 — Position Applier & gen_pcb.py Integration (FLOOR-02, FLOOR-03, FLOOR-04, FLOOR-07)
**Goal:** `apply_floor_plan` lowers the spec into `LayoutAwarePlacer` vectors, runs placement, and repositions footprints via `modify_footprint_position`. Wire into `gen_pcb.py` behind a `--floorplan` flag. Edge connectors pre-placed + locked; corner mounting holes pre-placed + locked; decoupling caps within max distance of their IC.

**Files:**
- `src/kicad_agent/floorplan/lower.py` (new) — spec → engine vectors
- `src/kicad_agent/floorplan/applier.py` (new) — orchestrator
- `src/kicad_agent/floorplan/__init__.py` (edit) — wire `apply_floor_plan`
- `tests/floorplan/test_lower.py` (new)
- `tests/floorplan/test_applier.py` (new)
- `analog-ecosystem/.../mono-arch/gen_pcb.py` (edit) — add `--floorplan` arg + post-populate call

**Tasks:**
- [ ] W2-1 (`lower.py`): `lower_zones(spec) -> list[ZoneDefinition]` — convert `ZoneSpec` → `ZoneDefinition` (ops/_schema_placement.py:111). Handle `zones: "auto"` by returning `[]` and letting `LayoutAwarePlacer` derive via `SignalFlowGrouper`.
- [ ] W2-2 (`lower.py`): `lower_pre_placed(spec) -> dict[str, tuple[float,float,float]]` — pass `pre_placed` straight through as `fixed_positions` (same shape `LayoutAwareRequest.fixed_positions` expects).
- [ ] W2-3 (`lower.py`): `lower_keepouts(spec) -> list[tuple[float,float,float,float]]` — flatten `KeepoutSpec`/inline-lists to the 4-tuple list `LayoutAwareRequest.keepout_zones` expects. Auto-derive edge keepouts from `board.edge_clearance_mm` and mounting-hole keepouts from H-prefixed `pre_placed` refs (via `build_exclusion_zones`).
- [ ] W2-4 (`lower.py`): `lower_constraints(spec) -> list[PCBConstraint]` — convert `ConstraintSpec` discriminated union → typed `PCBConstraint` subclasses (`DecouplingConstraint`, `ThermalConstraint`, `ClearanceConstraint`, etc.). Map YAML fields to constructor args; supply required `confidence`/`source_rule` defaults.
- [ ] W2-5 (`applier.py`): `apply_floor_plan(pcb_raw, spec, components, nets) -> tuple[str, dict]`. Pipeline:
  1. Run `spec.validate_against_netlist(components, nets)` (Wave 1 cross-checks). On failure → return `(pcb_raw, {"applied": False, "violations": [...]})`.
  2. Lower spec → zones, fixed_positions, keepout_zones, constraints (W2-1..4).
  3. Expand `replicate` (Wave 5; stub returns identity until then).
  4. Build `LayoutAwareRequest` from lowered vectors + components/nets/board dims.
  5. Call `LayoutAwarePlacer.place_layout_aware(request)` → `PlacementOutput`.
  6. For each ref in `output.positions`: call `PcbRawWriter.modify_footprint_position(pcb_raw, ref, x, y, angle)`.
  7. Inject `(locked)` on `pre_placed` refs (Wave 3; stub until then).
  8. Return `(new_pcb, {"applied": True, "placed": N, "locked": M, "violations": [...], "score": output.score})`.
- [ ] W2-6 (`gen_pcb.py`): Add `--floorplan <path>` arg. After the three net post-processing passes (`_inject_net_table`, `_rewrite_pad_nets_to_numeric`, `_assign_ground_to_unconnected_pads`) and **before** `OUT_PCB.write_text()`, if `--floorplan` given and file exists, call `apply_floor_plan`. Print result summary. If `applied=False`, warn and proceed with grid placement (fail-closed). This is exactly the integration point specified in research Q3 — the net passes are idempotent under repositioning, so floor planning runs last.

```python
# gen_pcb.py edit (illustrative, after _assign_ground_to_unconnected_pads, before write_text):
floorplan_path = args.floorplan or (BASE_DIR / f"{stem}.floorplan.yaml")
if floorplan_path and Path(floorplan_path).exists():
    from kicad_agent.floorplan import apply_floor_plan, load_floor_plan
    spec = load_floor_plan(Path(floorplan_path))
    new_pcb, fp_result = apply_floor_plan(
        pcb_raw=new_pcb, spec=spec, components=components, nets=nets,
    )
    if fp_result["applied"]:
        print(f"  Floor plan: {fp_result['placed']} moved, "
              f"{fp_result['locked']} locked, score={fp_result['score']:.4f}")
    else:
        print(f"  Floor plan NOT applied ({len(fp_result['violations'])} violations) "
              f"— falling back to grid placement")
```

- [ ] W2-7: Test `lower.py` — assert each lower function produces correctly-shaped vectors; assert `zones: "auto"` → `[]`.
- [ ] W2-8: Test `applier.py` end-to-end on a tiny synthetic PCB (5 comps, 2 zones, 1 pre_placed) — assert footprint positions change, `pre_placed` refs land at their exact coords, decoupling cap within max_distance of IC.
- [ ] W2-9: Test `gen_pcb.py` with `--floorplan` on the mono blade netlist — assert it produces a valid `.kicad_pcb` (round-trip parseable) with `H1`–`H4` and `J1` at their spec coords.

**Acceptance:** `gen_pcb.py --floorplan mono-blade.floorplan.yaml` produces a board where mounting holes are at the 4 corners and the blade connector is at the left edge, all within board bounds. Decoupling caps for U_PRE/U_VCA are within 5mm of their IC. Without `--floorplan`, output is byte-identical to today.

---

### Wave 3 — Keepouts & Locks for Quilter (FLOOR-05)
**Goal:** Emit `gr_poly` keepout objects that Quilter respects as Placement Regions, and inject `(locked)` tokens on `pre_placed` refs so Quilter (and KiCad) treat them as anchors. Belt-and-suspenders: Quilter keys off "inside board boundary" but the token makes intent explicit.

**Files:**
- `src/kicad_agent/floorplan/emission.py` (new)
- `src/kicad_agent/floorplan/applier.py` (edit) — call emission fns (replace W2-5 step 7 stub)
- `tests/floorplan/test_emission.py` (new)

**Tasks:**
- [ ] W3-1 (`emission.py`): `inject_locked_tokens(pcb_raw, refs) -> str` — for each ref, find its footprint block via `PcbRawWriter._find_footprint_block` (pcb_raw_writer.py:978), then call `PcbRawWriter._inject_locked_token(content, start, end)` (pcb_raw_writer.py:801) to insert `(locked)` as the first property inside `(footprint ...)`. Idempotent (skip if already locked). This extends the existing segment/via lock path to footprints.
- [ ] W3-2 (`emission.py`): `emit_keepout_polys(pcb_raw, keepouts, layer="F.Cu") -> str` — for each keepout 4-tuple `(x1,y1,x2,y2)`, emit a KiCad `gr_poly` on the given layer representing the keepout boundary. Quilter reads these as Placement Regions. Research open question (Dwgs.User vs `(zone ... (keepout ...))`): prefer KiCad 10 `(zone ... (keepout ...))` flags where supported; fall back to `gr_poly` on `Dwgs.User` + `F.Cu`/`B.Cu`. Inject before the closing `)` of `(kicad_pcb ...)`.
- [ ] W3-3 (`emission.py`): `emit_zone_region_polys(pcb_raw, zones) -> str` — for each functional zone, emit its boundary as a Placement-Region polygon so Quilter constrains zone-assigned components. Uses `build_keepouts_from_zone` (zone_partition.py:87) to derive per-zone keepouts for *other* zones.
- [ ] W3-4 (`applier.py`): Replace the W2-5 step-7 stub: after repositioning, call `inject_locked_tokens(pcb_raw, list(spec.pre_placed.keys()))`, then `emit_keepout_polys(pcb_raw, lowered_keepouts)`, then `emit_zone_region_polys(pcb_raw, lowered_zones)`. Increment `result["locked"]`.
- [ ] W3-5: Test — after `apply_floor_plan`, assert every `pre_placed` ref's footprint block contains `(locked)` exactly once. Assert `gr_poly`/`zone` count matches keepout count. Assert output round-trips through the parser.
- [ ] W3-6: Regression — re-run W2-9 mono blade test; assert locks + keepouts present and board still valid.

**Acceptance:** The floor-planned board's pre_placed footprints carry `(locked)`; keepouts appear as KiCad-native polygons; Quilter (per its docs) will lock anchors and respect Placement Regions. No pin-count or net-ID regressions (floor planner only moves/adds graphics, never touches pads).

---

### Wave 4 — Ground-Pour Preparation (FLOOR-06)
**Goal:** Lower the `ground_pour` section into KiCad `zone` blocks (F.Cu/B.Cu, GND, excluded over the noisy zones) using the existing `PcbRawWriter.build_zone_sexp` (pcb_raw_writer.py:81). KiCad fills these on load — no explicit polygon geometry needed; the zone is bounded by keepouts and the board edge.

**Files:**
- `src/kicad_agent/floorplan/emission.py` (edit) — add ground-pour emission
- `src/kicad_agent/floorplan/applier.py` (edit) — call it
- `tests/floorplan/test_ground_pour.py` (new)

**Tasks:**
- [ ] W4-1 (`emission.py`): `emit_ground_pour(pcb_raw, ground_pour_spec, board_spec, zones) -> str`. For each layer in `ground_pour.layers`, emit a `(zone (net "GND") (layer "F.Cu") ...)` block via `PcbRawWriter.build_zone_sexp`. The polygon is the board outline minus `exclude_zones` rectangles (compute the bounding polygon; if exclude makes it non-convex, emit one zone per remaining rectangle). Wire `clearance_mm` → `build_zone_sexp(clearance=...)`. Emit `thermals` flag.
- [ ] W4-2 (`emission.py`): Handle `isolated_pours` (e.g., GNDA analog ground) — emit a separate `(zone (net "GNDA") ...)` bounded by its `within` rectangle, star-tied conceptually at `star_point` (the actual star tie is a routed connection, not a pour property — document this).
- [ ] W4-3 (`applier.py`): If `spec.ground_pour` present, call `emit_ground_pour` after keepout emission. Record `result["pours_emitted"]`.
- [ ] W4-4: Test — assert GND zone blocks present on F.Cu and B.Cu; assert GNDA isolated pour present and bounded by its `within` rect; assert excluded zone rectangle does not appear in the GND pour polygon. Validate the board still parses (KiCad fills on load, so we don't simulate the fill).
- [ ] W4-5: Cross-reference check — `exclude_zones` names must exist in `zones[].name`; fail closed with a clear error if not.

**Acceptance:** A board with a `ground_pour` section produces KiCad `zone` blocks for GND on both copper layers, excludes the power zone, and emits a separate GNDA pour. Opening in KiCad shows the pour fills (verified manually or via `kicad-cli pcb drc` accepting the zones).

---

### Wave 5 — Multi-Strip Replication (FLOOR-08)
**Goal:** Expand a single `replicate` directive across N channels. Two forms: **Form A** (explicit count + YAML anchor template) and **Form B** (netlist-driven prefix detection, production default). A single directive replaces hand-listing 16× identical blocks — the strongest argument for YAML anchors over JSON.

**Files:**
- `src/kicad_agent/floorplan/replicate.py` (new)
- `src/kicad_agent/floorplan/applier.py` (edit) — call expand (replace W2-5 step 3 stub)
- `tests/floorplan/test_replicate.py` (new)
- `tests/fixtures/floorplan/multi-strip.floorplan.yaml` (new) — Form A + Form B variants

**Tasks:**
- [ ] W5-1 (`replicate.py`): `detect_channel_prefixes(nets) -> list[int]` — scan net names for `{prefix}\d+_` patterns (e.g., `CH1_ADC_HOT`, `CH2_DAC_HOT`), return sorted distinct channel numbers. Form B driver.
- [ ] W5-2 (`replicate.py`): `expand_template(replicate_spec, channels) -> tuple[list[ZoneSpec], list[ConstraintSpec], dict]`. For each channel `n` in 1..count: substitute `{n}` in template refs (`U_PRE_{n}`, `C_PRE_{n}_100N`), offset zone `y_range`/`x_range` by `pitch_mm × (n-1)` from `origin`. Returns expanded zones + constraints + expanded pre_placed entries.
- [ ] W5-3: **Component-cap enforcement** — after expansion, assert `len(all_refs) ≤ 500` (`_MAX_COMPONENTS` cap in `HybridPlacementEngine`). Fail closed with `"replicate expands to {N} components, exceeds 500 cap"` if exceeded (16×30=480 OK; 20×30=600 fails — matches research Q4 safety note).
- [ ] W5-4: Form A — `count` given: use it directly. Form B — `detect_prefix` given: run `detect_channel_prefixes(nets)`, derive count. If both, `count` wins (explicit override).
- [ ] W5-5 (`applier.py`): Replace W2-5 step-3 stub: if `spec.replicate`, call expand and merge expanded zones/constraints/pre_placed into the lowered vectors before placement.
- [ ] W5-6: Test Form A — 4-channel template expands to 4× zones with correct offsets and `{n}` substitution in refs. Test Form B — feed a netlist with `CH1_*`..`CH3_*` nets, assert count=3 detected. Test cap — 20-channel expansion raises.
- [ ] W5-7: Integration — run `gen_pcb.py` on `build_base_board.py`'s multi-channel netlist (4 channels) with a multi-strip floor plan; assert all channel components land in their offset strips.

**Acceptance:** A single `replicate` block produces N correctly-offset channel strips with `{n}`-substituted refs and per-channel decoupling constraints. Auto-scales 4→8→16 channels with zero spec edits.

---

### Wave 6 — Validation, Scoring & Mono-Blade Comparison (FLOOR-09)
**Goal:** Prove the floor plan improves Quilter routing quality. The canonical test: mono blade routed WITH a floor plan scores higher placement quality (HPWL/congestion) than WITHOUT. Capture both Quilter-ready boards for the live routing comparison.

**Files:**
- `scripts/validate_floorplan_mono_blade.py` (new) — comparison harness
- `tests/floorplan/test_mono_blade_comparison.py` (new) — automated score assertion
- `tests/fixtures/floorplan/mono-blade.floorplan.yaml` (finalize from W1-4)

**Tasks:**
- [ ] W6-1 (`scripts/validate_floorplan_mono_blade.py`): Generate the mono blade PCB two ways:
  - **Baseline (no floor plan):** `gen_pcb.py --netlist mono-blade.net` → `mono-blade-baseline.kicad_pcb`
  - **With floor plan:** `gen_pcb.py --netlist mono-blade.net --floorplan mono-blade.floorplan.yaml` → `mono-blade-floorplanned.kicad_pcb`
- [ ] W6-2: Extract positions from both boards (reuse `ExportPositionsOp` logic or parse `(at X Y angle)` per footprint). Build a `PlacementGraph` from the netlist.
- [ ] W6-3: Score both with `PlacementScorer` (scoring.py:229) — composite of HPWL (30%), congestion (20%), clearance (30%), edge (20%). Print a comparison table.
- [ ] W6-4 (`test_mono_blade_comparison.py`): Assert the floor-planned board scores **strictly higher** `total_score` than baseline. Assert decoupling constraints satisfied (caps within max_distance). Assert zero overlaps in both (clearance_score=1.0). Assert `pre_placed` refs at exact spec coords.
- [ ] W6-5: Emit both boards as Quilter-upload-ready artifacts. Document the manual Quilter routing comparison (HPWL/congestion from Quilter's own metrics) as the live validation step — the automated `PlacementScorer` delta is the proxy gate.
- [ ] W6-6: Regression suite — add the mono-blade floor-plan generation to CI (fast: ~116 parts, sub-second placement). Assert no flakiness across 5 runs (SA seed fixed at 42 in `LayoutAwarePlacer`).

**Acceptance (FLOOR-09 + Roadmap criterion 5):** The mono blade routed WITH a floor plan scores higher placement quality than WITHOUT. The improvement is measurable on HPWL (wirelength) and congestion, and decoupling caps are verifiably closer to their ICs. Both boards are Quilter-upload-ready for the live routing-quality confirmation.

---

## Test Strategy

### Mono blade with vs without floor plan (the FLOOR-09 canonical test)

The mono blade (`build_mono_blade.py`, ~116 parts, 40×200mm) is the test vehicle because its linear signal chain (input → impedance → HPF → pad → phase → THAT340 preamp → THAT4301 VCA → EQ → NE5532 output) is the canonical signal flow, and it's small enough for fast CI (~sub-second placement) yet real enough to exercise all floor-plan features.

| Aspect | Without floor plan (baseline) | With floor plan |
|---|---|---|
| Placement | `auto_place_grid` (grid packing, blind) | `LayoutAwarePlacer` (zone-aware, constraint-driven SA) |
| Mounting holes | Wherever grid puts them | 4 corners, locked |
| Connector | Mid-board | Left edge, locked, rotated 90° |
| Decoupling caps | Random | Within 5mm of each IC (critical priority) |
| Power/analog isolation | None | Keepout corridor + GNDA star pour |
| Expected HPWL | Higher (long signal paths) | **Lower** (signal flow respects L→R chain) |
| Expected congestion | Higher (clumped) | **Lower** (spread across zones) |

**Automated gate:** `PlacementScorer.total_score(floorplanned) > PlacementScorer.total_score(baseline)`, plus structural assertions (locks present, keepouts present, decoupling distances met, zero overlaps).

**Live gate (manual):** Upload both boards to Quilter; compare Quilter's routing completion rate / via count / HPWL. Documented in the validation script's output, not enforced in CI (Quilter is external).

### Test pyramid

| Layer | What | Count |
|---|---|---|
| Unit (W1) | `FloorPlanSpec` validators, `load_floor_plan` round-trip, 6 negative fixtures | ~25 |
| Unit (W2) | `lower_*` vector shapes, `apply_floor_plan` on synthetic 5-comp board | ~15 |
| Unit (W3) | `inject_locked_tokens` idempotency, `emit_keepout_polys` count + validity | ~10 |
| Unit (W4) | `emit_ground_pour` zone blocks, exclude-zone cross-ref, GNDA isolated pour | ~10 |
| Unit (W5) | `detect_channel_prefixes`, `expand_template` Form A/B, 500-cap enforcement | ~12 |
| Integration (W2/W6) | `gen_pcb.py --floorplan` on mono blade netlist, round-trip parse | ~6 |
| Comparison (W6) | Mono blade with vs without: `PlacementScorer` delta + structural asserts | ~5 |
| **Total** | | **~83 tests** |

### Fixtures
- `tests/fixtures/floorplan/mono-blade.floorplan.yaml` — canonical sample (W1-4, finalized W6)
- `tests/fixtures/floorplan/multi-strip.floorplan.yaml` — Form A + B (W5)
- `tests/fixtures/floorplan/invalid-*.yaml` — 6 negative cases (W1-5)
- Existing: `mono-arch/mono-blade.net`, `mono-arch/gen_pcb.py` (the SUT)

---

## Requirement → Wave Coverage

| Req | Description | Wave |
|---|---|---|
| FLOOR-01 | YAML schema (zones, edges, mounting, keepout, power, decoupling) | **W1** |
| FLOOR-02 | gen_pcb.py reads spec → places in functional zones | **W2** |
| FLOOR-03 | Pre-place connectors at board edges (locked) | **W2** (+lock in W3) |
| FLOOR-04 | Mounting holes at corners + structural points | **W2** (+lock in W3) |
| FLOOR-05 | Keepout zones (edge clearance, connector clearance) | **W3** |
| FLOOR-06 | Ground pour prep (copper zone definitions) | **W4** |
| FLOOR-07 | Decoupling proximity (caps near ICs) | **W2** |
| FLOOR-08 | Multi-strip replication (N channels, evenly spaced) | **W5** |
| FLOOR-09 | Test: mono blade with vs without floor plan | **W6** |

## Roadmap Success Criteria → Wave Coverage

1. `FloorPlanSpec` + loader validates + fails closed → **W1**
2. `gen_pcb.py` reads spec, places via `apply_floor_plan` into `LayoutAwarePlacer` → **W2**
3. Connectors/mounting holes locked, keepouts as `gr_poly` → **W3**
4. Ground-pour `zone` blocks, decoupling within max distance, multi-strip → **W4 + W5**
5. Mono blade WITH floor plan scores higher than WITHOUT → **W6**

---

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| `LayoutAwarePlacer` SA is non-deterministic → flaky comparison test | SA seed fixed at 42 (already set in `layout_aware.py:294`); W6-6 asserts stability across 5 runs |
| `replicate` exceeds 500-component cap silently | W5-3 hard check, fail closed (research Q4) |
| `(locked)` token format wrong for footprints (only segments/vias proven) | W3-1 extends existing `_inject_locked_token` path; W3-5 round-trip parse validates; manual KiCad open check |
| Ground pour polygon geometry incorrect → KiCad fill fails | Use `build_zone_sexp` (proven in Phase 10); W4-4 validates parse; `kicad-cli pcb drc` accepts zones |
| Floor plan disturbs net bookkeeping | Floor planner only *moves* footprints + adds graphics; never adds/removes pads. Net passes run before and are idempotent under repositioning (research Q3). W2-9 asserts net table intact. |
| `gen_pcb.py` is in `analog-ecosystem` repo, not `kicad-agent` | The `--floorplan` integration is a thin ~15-line edit; the `floorplan/` module lives in `kicad-agent` and is imported via `sys.path` (gen_pcb.py already does this for `populate_pcb_from_netlist`). Test the integration against the real gen_pcb.py. |

---

## Definition of Done

- [ ] All 9 FLOOR requirements checked off in REQUIREMENTS.md
- [ ] All 5 Roadmap success criteria TRUE
- [ ] `src/kicad_agent/floorplan/` ships with parser + applier + lowering + replicate + emission
- [ ] `gen_pcb.py` supports `--floorplan <path>`; mono blade generates with and without
- [ ] Mono blade WITH floor plan scores higher than WITHOUT (automated + documented live Quilter comparison)
- [ ] ~83 tests green, coverage ≥90% on `floorplan/`
- [ ] Sample `mono-blade.floorplan.yaml` + `multi-strip.floorplan.yaml` checked in
- [ ] Deleting the `.floorplan.yaml` → original grid placement (reversibility verified)
