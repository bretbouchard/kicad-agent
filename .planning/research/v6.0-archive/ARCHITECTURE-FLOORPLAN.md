# Floor Planning / Placement Specification — Architecture Research

**Milestone:** v5.0 (floor planning & placement specification system)
**Status:** Research — answers the 5 design questions, proposes the spec format, and defines the integration sequence.
**Date:** 2026-07-03

---

## Executive Summary

volta already possesses the four primitives a floor planner needs —
**zones** (`ZoneDefinition`), **constraints** (`PCBConstraint` hierarchy),
**signal-flow grouping** (`SignalFlowGrouper`), and **position + keepout
vectors** consumed by `HybridPlacementEngine`/`LayoutAwarePlacer`. What is
missing is a single, format-agnostic **source document** that captures design
intent (functional zones, locked anchors, keepouts, decoupling pairs, power
isolation, ground-pour prep, multi-strip replication) and a **lowering pass**
that compiles it into the engine's existing `fixed_positions` +
`keepout_zones` + `constraints` inputs.

**Recommendation: a declarative YAML floor-plan spec** (`.floorplan.yaml`),
compiled by a new `FloorPlan` loader into the existing engine vectors, and
applied as a **post-populate, pre-Quilter stage** via
`PcbRawWriter.modify_footprint_position`. YAML is chosen over raw Python
dicts and over JSON for three reasons: (1) it supports comments and
`anchors/aliases`, which are essential for the multi-strip replication
(`CH{n}_`) pattern; (2) it round-trips cleanly to/from the existing
`export_positions`/`import_positions` JSON op for position-locking; (3) it
decouples design intent from generator code so the same floor plan scales
across `build_base_board.py`'s 4–16 channel sweep without editing Python.

The remainder of this document answers the five explicit research questions,
surveys how commercial EDA tools handle floor planning, and gives concrete
encoding recipes for each of the eight listed concerns.

---

## Q1 — Placement Specification Format

### Options considered

| Format | Pros | Cons | Verdict |
|---|---|---|---|
| **Python dict in build script** | Zero parsing; full expression power; reuse `build_*.py` vars directly | Design intent entangled with code; can't scale across `channels=4..16` without code edits; no diff-friendly review | ✗ |
| **JSON file** | Native round-trip with `export_positions`/`import_positions`; Pydantic-validation friendly | No comments; no anchors → multi-strip replication means hand-listing 16× identical blocks or a separate generator | △ |
| **YAML file (`.floorplan.yaml`)** | Comments, anchors/aliases for replication, Pydantic-loadable, human-reviewable diffs, industry-standard for "design intent" configs (cf. Altium snippets, KiCad design rules) | Needs a YAML dep (already in tree via `pyyaml`); indentation-sensitive | **✓ Recommended** |
| **`.kicad_dru` rules** | KiCad-native; consumed by DRC | Rules are *clearance* constraints, not placement/zoning — cannot express "stage 3 goes left of stage 4" | ✗ (orthogonal) |

### Recommended schema (YAML, validated by a new Pydantic `FloorPlanSpec`)

The spec is a **thin extension** of the two existing schemas
(`ZoneDefinition` from `_schema_placement.py`, `PCBConstraint` subclasses from
`constraints/types.py`). It adds only what those lack: a board-level header,
a `pre_placed` anchor list, a `replicate` directive for multi-strip patterns,
and a `ground_pour` section.

```yaml
# analog-board.floorplan.yaml
schema_version: 1
board:
  width_mm: 200.0
  height_mm: 190.0
  layers: [F.Cu, In1.Cu, In2.Cu, B.Cu]   # mirror gen_pcb.py stack

# --- Functional zones (reuses ZoneDefinition vocabulary) ---
zones:
  - name: power
    x_range: [0, 60]
    y_range: [0, 190]
    fill_order: top-to-bottom
    priority_refs: [U_PWR_BUCK, U_INV, U_5V, U_3V3]   # WAVE 1
  - name: digital
    x_range: [60, 120]
    y_range: [0, 190]
    fill_order: left-to-right
    priority_refs: [U_XMOS, U_CODEC, U_MCU, U_ETH, J_USB]
  - name: connectors
    x_range: [120, 200]
    y_range: [0, 190]
    fill_order: left-to-right
    priority_refs: []   # filled by replicate, below

# --- Pre-placed / locked anchors (reuses fixed_positions dict) ---
pre_placed:
  H1: [5.0, 5.0, 0.0]      # mounting holes — corner anchors
  H2: [195.0, 5.0, 0.0]
  H3: [5.0, 185.0, 0.0]
  H4: [195.0, 185.0, 0.0]
  J_PWR: [10.0, 95.0, 90.0]

# --- Keepout zones (reuses keepout_zones tuple list) ---
keepout_zones:
  - [0, 0, 60, 190, "power_only"]          # power corridor isolation
  - [188, 188, 200, 190, "edge_keepout"]   # board edge clearance

# --- Constraints (reuses PCBConstraint hierarchy, JSON-encoded) ---
constraints:
  - type: DECOUPLING
    ic_ref: U_XMOS
    cap_ref: C_XMOS_100N
    max_distance_mm: 5.0
    priority: critical
  - type: THERMAL
    component_refs: [U_PWR_BUCK, U_INV]
    heat_dissipation_w: 2.5
    max_junction_temp_c: 125
  - type: CLEARANCE
    min_clearance_mm: 1.5
    net_class_name: "mains"

# --- Multi-strip replication (NEW — the one genuinely new construct) ---
replicate:
  template: ch_strip        # anchor name (YAML alias) defined below
  count: 16                  # build_base_board.py channels=16
  net_prefix: "CH{n}_"       # CH1_ADC_HOT, CH2_ADC_HOT, ...
  pitch_mm: 9.0              # vertical strip pitch
  origin: [125.0, 10.0]      # first strip top-left

# --- Ground-pour preparation (NEW) ---
ground_pour:
  layers: [F.Cu, B.Cu]
  net: GND
  exclude_zones: [power]     # don't pour over the noisy switcher area
  thermals: true
  star_point: [30.0, 95.0]   # ferrite bead FB_0R reference
```

The `replicate.template` would expand via a YAML anchor (`&ch_strip`) or, if
the strip is too large to inline, a small `strips:` section that the loader
parameterizes with `{n}` and the net prefix. This single directive replaces
hand-listing 16×(ADC_HOT, DAC_HOT, GPIO_0..6, CV_*, EQ_*) in
`build_base_board.py`.

---

## Q2 — How Other EDA Tools Handle Floor Planning

| Tool | Mechanism | What volta can borrow |
|---|---|---|
| **Altium Designer** | **Rooms** — rectangular regions on the PCB; sheet→room auto-assignment by hierarchical sheet; components dragged *into* a room are member-bound; rooms can be moved/locked as a unit. Room definitions live in the `.SchDoc`/`.PcbDoc`. | The `ZoneDefinition` + `priority_refs` model is a direct analog of Altium rooms. The YAML `zones:` section is our "room table." |
| **Cadence Allegro / OrCAD** | **Constraint Manager** — a spreadsheet-driven matrix of net-class rules (clearance, impedance, differential pair, max length) plus **Placement Regions** (keep-in/keep-out polygons). | The `PCBConstraint` Pydantic hierarchy is our Constraint Manager. `keepout_zones` are our keep-out polygons. |
| **KiCad (native)** | **No room/floor-plan concept.** Has `.kicad_dru` design rules (clearance, min track width, courtyards) and sheet-based hierarchical grouping, but no first-class "place this group in this region" primitive. Users resort to area fills + locked footprints. | **This is the gap volta fills.** The floor-plan spec is a *custom* construct — it must not assume KiCad-native persistence. It lowers into `(locked)` tokens + keepout polygons that *are* KiCad-native. |
| **Quilter (AI autorouter/placer)** | **Pre-placed components** (anything inside the board outline at upload is treated as locked) + **Placement Regions** (user polygons on F.Cu/B.Cu that constrain which components may sit inside). Constraint-maturity is explicit: "if your constraints are vague, any tool will struggle." | **This is the downstream consumer.** The floor-plan spec must emit (a) fixed positions for anchors → Quilter locks them; (b) keepout polygons → Quilter respects them as Placement Regions; (c) numeric net IDs → already handled by `gen_pcb.py`. |
| **Open-source (coriolis, OpenROAD)** | Hierarchical floorplanning with hard/soft macros, simulated annealing, cut-minimization. | Our `LayoutAwarePlacer` already does SA via `scipy.optimize.dual_annealing` with constraint-aware penalties — we don't need to import a floorplanner, just feed it better zones. |

**Key takeaway:** KiCad's lack of native rooms means our floor-plan spec is the
*only* place this intent lives. We must own the source-of-truth and lower it
into KiCad-native artifacts (`(locked)` tokens, keepout `gr_poly`/`keepout`
objects) at build time. See Q3 for the lowering sequence.

---

## Q3 — Integration with `gen_pcb.py`

### Current pipeline (no floor plan)

```
skidl .net ──parse──► XML netlist ──► populate_pcb_from_netlist()
                                              │
                                              │ internally calls auto_place_grid()
                                              │ (grid packing, NOT zone-aware)
                                              ▼
                                     raw .kicad_pcb (grid-placed)
                                              │
                              ┌───────────────┼───────────────┐
                              ▼               ▼               ▼
                    _inject_net_table  _rewrite_pad_nets  _assign_ground_pads
                                              │
                                              ▼
                                    Quilter upload (placement + routing)
```

### Critical constraint: `populate_pcb_from_netlist` does NOT accept a floor plan

Inspection of `src/volta/crossfile/pcb_populate.py:526` shows the
signature is:

```python
def populate_pcb_from_netlist(
    pcb_raw, netlist_path, base_dir, library_paths=None,
    board_width=200.0, board_height=150.0,
    placement_clearance=5.0, assign_nets=True, side="F",
) -> tuple[str, dict]:
```

There is **no** `fixed_positions` or `keepout_zones` parameter. Internally it
calls `auto_place_grid(components, board_width, board_height,
placement_clearance)` — a pure grid packer. Therefore the floor plan **cannot
be injected into the populate call**; it must be applied **after**.

### Recommended integration: a new `apply_floor_plan` stage

```
... populate_pcb_from_netlist() ──► raw PCB (grid-placed, nets assigned)
                                              │
                              ┌───────────────┼───────────────┐
                              ▼               ▼               ▼
                    _inject_net_table  _rewrite_pad_nets  _assign_ground_pads
                                              │
                                              ▼
                              ┌───────────────────────────────────┐
                              │  NEW: apply_floor_plan(spec_yaml) │
                              │                                   │
                              │  1. Load FloorPlanSpec (Pydantic) │
                              │  2. Expand replicate → channels    │
                              │  3. Run LayoutAwarePlacer with     │
                              │     fixed_positions + keepout_zones│
                              │     + constraints from the spec    │
                              │  4. For each ref in output:        │
                              │     PcbRawWriter.modify_footprint_ │
                              │       position(raw, ref, x, y, ang)│
                              │  5. Inject (locked) tokens on      │
                              │     pre_placed refs (so Quilter    │
                              │     treats them as anchors)        │
                              │  6. Emit keepout gr_poly objects   │
                              │     for Quilter Placement Regions  │
                              └───────────────────────────────────┘
                                              │
                                              ▼
                                    Quilter upload (constrained)
```

**Why after populate, before Quilter — and not before populate?**
1. `populate_pcb_from_netlist` needs to *exist* in the PCB to be repositioned —
   it instantiates footprint blocks. The floor plan only *moves* already-
   instantiated footprints.
2. The three net post-processing passes (`_inject_net_table`,
   `_rewrite_pad_nets_to_numeric`, `_assign_ground_to_unconnected_pads`) are
   **idempotent under repositioning** — moving a footprint does not change
   its pad net assignments. So the floor-plan stage can sit either before or
   after them; placing it *after* keeps all net bookkeeping together and lets
   the floor planner reason about already-numeric nets.
3. Quilter is the terminal consumer. By the time the board reaches Quilter,
   anchors must be `(locked)`, keepouts must be polygons, and nets must be
   numeric — all three are satisfied by `apply_floor_plan` running last.

### Concrete `gen_pcb.py` edit (illustrative)

```python
# After the three net post-processing passes, before OUT_PCB.write_text():
floorplan_path = BASE_DIR / f"{stem}.floorplan.yaml"
if floorplan_path.exists():
    from volta.placement.floorplan import apply_floor_plan
    new_pcb, fp_result = apply_floor_plan(
        pcb_raw=new_pcb,
        spec_path=floorplan_path,
        components=components,
        nets=nets,
    )
    print(f"  Floor plan: {fp_result['placed']} moved, "
          f"{fp_result['locked']} locked, "
          f"{fp_result['violations']} violations")
```

The new module `volta/placement/floorplan.py` would:
1. Define `FloorPlanSpec` (Pydantic, extending `ZoneDefinition` +
   `PCBConstraint`).
2. Lower `spec.zones` → `LayoutAwarePlacer` zone assignment.
3. Lower `spec.pre_placed` → `PlacementRequest.fixed_positions`.
4. Lower `spec.keepout_zones` → `PlacementRequest.keepout_zones` (and emit
   `gr_poly` keepout objects into the raw PCB for Quilter).
5. Lower `spec.constraints` → `LayoutAwarePlacer` constraint injection.
6. Expand `spec.replicate` → parameterized channel strips.
7. Call `PcbRawWriter.modify_footprint_position` for each moved ref and
   `PcbRawWriter._inject_locked_token` for each `pre_placed` ref.

---

## Q4 — Quilter Constraints

Quilter is the **terminal consumer** of the floor-planned board. Its two
constraint mechanisms (per official docs) are:

1. **Pre-placed components** — *"Locking the position and rotation of a
   component is easy: just pre-place it within the board outline and upload
   your input file to Quilter."* Quilter treats **any** footprint with a
   position inside the board boundary as locked and will not move it.

2. **Placement Regions** — user-drawn polygons on F.Cu/B.Cu that constrain
   *which* components may be placed inside. Components are associated to a
   region; Quilter keeps them within its boundary during auto-placement.

### What this means for the floor-plan spec

| Floor-plan concept | Quilter mechanism | How volta satisfies it |
|---|---|---|
| `pre_placed` anchors | Pre-placed (locked) components | `apply_floor_plan` sets the position via `modify_footprint_position` AND injects `(locked)` via `_inject_locked_token` — belt-and-suspenders, since Quilter keys off "inside board boundary" but the token makes intent explicit for KiCad too. |
| `zones` (functional regions) | Placement Regions (polygons) | `apply_floor_plan` emits `gr_poly` keepout-for-other-zones objects (using the existing `build_keepouts_from_zone` from `zone_partition.py`). Quilter sees these as region boundaries. |
| `keepout_zones` | Placement Regions / board keepouts | Emitted directly as `gr_poly` on `F.Cu`/`B.Cu`. |
| Locked footprints (KiCad `(locked)`) | Respected — Quilter reads the token | `PcbRawWriter._inject_locked_token` already exists for segments/vias; extend it for footprints (`(footprint ... (locked) ...)`). |
| Pin-count mismatches | **Blocking error** in Quilter | Already handled by `gen_pcb.py`'s `_assign_ground_to_unconnected_pads`. The floor planner must not disturb this — it only moves footprints, never adds/removes pads. |
| Numeric net IDs | **Required** by Quilter | Already handled by `_inject_net_table` + `_rewrite_pad_nets_to_numeric`. Floor planner operates on already-numeric nets. |

**Net effect:** the floor-plan spec's job is to (a) put anchors where Quilter
will lock them, (b) draw keepout polygons Quilter will respect, and (c) place
the *remaining* components well enough that Quilter's AI has a good starting
configuration. Quilter does the final routing; our floor plan governs
placement.

### Security/safety note

The existing `_MAX_COMPONENTS = 500` cap in `HybridPlacementEngine` and the
`max_length=500` on `component_refs`/`fixed_refs` in `AutoPlaceOp` must be
respected by `FloorPlanSpec`. The `replicate` directive is the danger zone:
16 channels × ~30 parts/strip = 480 — under the cap, but a 20-channel sweep
would exceed it. `apply_floor_plan` must validate
`len(expanded_refs) <= 500` and fail closed.

---

## Q5 — Encoding the Eight Concerns

Each concern maps onto existing primitives. Recipes below use the YAML
schema from Q1.

### 5.1 Signal flow zones

**Existing primitive:** `SignalFlowGrouper` (`placement/signal_flow.py`) +
`LayoutAwarePlacer` zone assignment. The grouper builds a BFS adjacency graph
from shared `boundary_nets`, finds connected components, and orders zones
entry→exit (left→right on the board).

**Encoding:** The mono-blade's linear chain
(`INPUT_JACK → DG413 impedance → DG413 HPF → DG413 pad → DG413 invert →
THAT340 preamp → DG413 routing → THAT4301 VCA → NE5532 makeup → 3-band EQ →
NE5532 output → LINE_OUT`) is the canonical signal flow. Two ways to encode:

- **Declarative (explicit zone order):** list zones in `zones:` with
  `priority_refs` named per stage. The `fill_order: left-to-right` enforces
  the chain direction.
- **Derived (let the grouper infer):** omit explicit zones, instead supply
  `SubcircuitIntent` input/output nets and let `SignalFlowGrouper.group()`
  produce `SignalFlowGroup.ordered_zones`. This is what `LayoutAwarePlacer`
  already does — the floor-plan spec can *opt into* auto-derivation with a
  top-level `zones: auto` flag.

**Recommendation:** explicit for the base board (power/digital/connector
macro-zones), derived for the blade (per-stage micro-zones), since the blade's
chain is well-defined and the grouper's `_TYPE_PRIORITY` already ranks
PREAMP/EQ/FILTER ahead of OUTPUT_STAGE.

### 5.2 Decoupling proximity

**Existing primitive:** `DecouplingConstraint` (`constraints/types.py:125`)
with `ic_ref`, `cap_ref`, `max_distance_mm`, `priority` (critical/high/normal).
Consumed by `LayoutAwarePlacer.constraint_aware_sa_objective` with
`_DECOUPLING_PENALTY_WEIGHT=1.0` and `_MAX_DECOUPLING_DISTANCE_MM=10.0`.

**Encoding:**
```yaml
constraints:
  - type: DECOUPLING
    ic_ref: THAT340
    cap_ref: C_PRE_100N
    max_distance_mm: 5.0
    priority: critical
```
Each active stage in the blade (DG413 ×5, THAT340, THAT4301, NE5532 ×5) gets
one such entry. The `replicate` directive expands `CH{n}_` prefixes so all 16
copies get decoupling constraints automatically.

### 5.3 Power isolation

**Existing primitives:** (a) `keepout_zones` tuples for hard isolation;
(b) `ThermalProfile` + `apply_thermal_constraints` (`placement/thermal.py`)
for heat-driven exclusion; (c) `ThermalConstraint` for declarative profiles.

**Encoding:** The base board's switcher corridor (TPS54202 buck + LT3580
inverting + MP1584EN + AMS1117) is both electrically noisy and thermally hot.
Three layers of isolation:

```yaml
keepout_zones:
  - [0, 0, 60, 190, "power_only"]     # no non-power parts in this corridor

constraints:
  - type: THERMAL
    component_refs: [U_BUCK, U_INV]
    heat_dissipation_w: 2.5
    max_junction_temp_c: 125
    thermal_resistance_c_per_w: 40

# ThermalProfile is derived from ThermalConstraint at load time:
# apply_thermal_constraints() emits extra keepout rectangles sized by
# required_clearance_mm + _POWER_SCALING_FACTOR * watts
```

The star-ground ferrite (`FB_0R`) and the ±15V rail ferrites (`fb_v15`,
`fb_n15` creating `+15V_FILT`/`-15V_FILT`) are placed at the `power`→`digital`
zone boundary so filtered rails cross the keepout at a single choke point.

### 5.4 Mounting holes

**Existing primitive:** the `H`-prefix convention in `auto_place_zoned`
(`ops/handlers/pcb.py`) — H-prefixed refs are auto-added to exclusion zones via
`PcbRawWriter.build_exclusion_zones`.

**Encoding:**
```yaml
pre_placed:
  H1: [5.0, 5.0, 0.0]
  H2: [195.0, 5.0, 0.0]
  H3: [5.0, 185.0, 0.0]
  H4: [195.0, 185.0, 0.0]
```
The loader auto-derives 4 corner keepouts (mounting-hole keepout = hole
diameter + bit clearance) and passes H1–H4 as `fixed_positions` so neither
the placer nor Quilter moves them. The existing `build_exclusion_zones`
function already handles margin expansion.

### 5.5 Keepout zones

**Existing primitive:** `(x1, y1, x2, y2)` tuples throughout
(`AutoPlaceOp.keepout_zones`, `PlacementRequest.keepout_zones`,
`LayoutAwarePlacer`). Consumed by `constraint_aware_sa_objective` as hard
penalty boxes.

**Encoding:** two flavors in the YAML:

```yaml
keepout_zones:
  # 4-tuple = axis-aligned rectangle (existing engine format)
  - [0, 0, 60, 190, "power_only"]
  # Optional 5th element = semantic label for debugging/Quilter naming
  - [188, 0, 200, 190, "edge_keepout"]
```

For **non-rectangular** keepouts (e.g., around a circular connector), the
loader approximates with multiple rectangles OR emits a `gr_poly` directly
into the raw PCB (KiCad-native keepout). The `(x1,y1,x2,y2)` form is the
engine-facing representation; `gr_poly` is the Quilter-facing representation.
`apply_floor_plan` does the conversion.

### 5.6 Ground-pour preparation

**No existing primitive** — this is genuinely new. KiCad pours are
`zone` objects with `(net ...)`, layer list, and fill rules. The floor-plan
spec must declare *intent* (which layers, which net, where to exclude), and
`apply_floor_plan` lowers it into KiCad `zone` blocks.

**Encoding:**
```yaml
ground_pour:
  layers: [F.Cu, B.Cu]
  net: GND
  exclude_zones: [power]      # don't pour over the switcher — separate pour
  thermals: true
  star_point: [30.0, 95.0]    # FB_0R — single ground reference
  isolated_pours:
    - net: GNDA               # analog ground, star-tied at FB_0R
      layers: [F.Cu]
      within: [60, 0, 200, 190]
```

The `exclude_zones` key cross-references the `zones:` names, so changing a
zone boundary automatically updates the pour exclusion. The `isolated_pours`
section handles the `GNDA` (analog ground) case where the blade's analog
section gets its own pour tied to digital GND only at the ferrite bead — the
classic star-ground topology in `build_base_board.py`.

**Lowering:** `apply_floor_plan` emits `(zone (net N "GND") (layer "F.Cu")
(hatch ...) (connect_pads ...) ...)` blocks. KiCad fills these on load; no
explicit polygon geometry needed — the zone is bounded by keepouts and the
board edge.

### 5.7 Multi-strip patterns (16 identical channels)

**No existing primitive** — this is the second genuinely new construct and
the strongest argument for YAML (anchors) over JSON. The pattern: 16 blades,
each with ~30 nets named `CH{n}_ADC_HOT`, `CH{n}_DAC_HOT`, etc.

**Encoding:** two supported forms.

**Form A — YAML anchor/alias (explicit):**
```yaml
replicate:
  count: 16
  net_prefix: "CH{n}_"
  pitch_mm: 9.0
  origin: [125.0, 10.0]
  template: &ch_strip
    zones:
      - name: "input_{n}"
        x_range: [0, 10]
        y_range: [0, 9]
        priority_refs: ["J_IN_{n}", "U_IMP_{n}"]
    constraints:
      - type: DECOUPLING
        ic_ref: "U_PRE_{n}"
        cap_ref: "C_PRE_{n}_100N"
        max_distance_mm: 5.0
```
The loader expands `{n}` → 1..16 and offsets each strip by `pitch_mm`.

**Form B — derive from netlist (implicit):**
```yaml
replicate:
  detect_prefix: "CH"          # scan nets for CH1_*, CH2_*, ...
  pitch_mm: 9.0
  origin: [125.0, 10.0]
  template: ch_strip_template  # refs use CH{n}_wildcards
```
The loader reads the netlist, finds all distinct `CH\d+_` prefixes, and
instantiates one strip per prefix. This auto-scales 4→8→16 channels with zero
spec edits — matching `build_base_board.py`'s `build_board(channels=N)`.

**Recommendation:** Form B for production (netlist-driven, DRY); Form A for
one-off/prototyping where the netlist isn't canonical.

---

## Validation & Failure Modes

The floor-plan loader must validate:

1. **Zone coverage:** every `priority_ref` falls inside some zone's bounds,
   else fail closed ("U_XMOS not in any zone").
2. **Pre-placed inside board:** every `pre_placed` coordinate within
   `[0,width]×[0,height]` + edge margin.
3. **Keepout non-annihilation:** no keepout fully covers a zone (would make
   it unplaceable).
4. **Replicate count vs. component cap:** `sum(strip_parts) × count ≤ 500`.
5. **Net-prefix existence:** `replicate.net_prefix` matches at least one net
   in the netlist (catches typos like `CHN_` vs `CH{n}_`).
6. **Constraint ref existence:** every `ic_ref`/`cap_ref` resolves to a real
   component.

On failure, `apply_floor_plan` returns the raw PCB unmodified + a violations
list (mirroring `PlacementOutput.violations`), so `gen_pcb.py` can fall back
to grid placement rather than producing a malformed board.

---

## Migration Path

1. **Phase 1 — Spec + loader (no behavior change):** implement
   `FloorPlanSpec` Pydantic model + YAML loader. Validate only; do not apply.
   Ship a sample `analog-board.floorplan.yaml` mirroring the current grid
   placement so the output is byte-identical.
2. **Phase 2 — Apply positions:** wire `apply_floor_plan` into `gen_pcb.py`
   behind a `--floorplan` flag. Compare Quilter routing scores
   (HPWL/congestion from `PlacementScorer`) before/after.
3. **Phase 3 — Keepouts + locks:** emit `gr_poly` keepouts and `(locked)`
   tokens; verify Quilter respects them.
4. **Phase 4 — Replication:** enable the `replicate` directive for
   `build_base_board.py`'s 16-channel sweep.
5. **Phase 5 — Ground pours:** lower `ground_pour` into KiCad `zone` blocks.

Each phase is independently shippable and reversible (delete the YAML →
original grid placement).

---

## Open Questions (for implementation, not blocking this research)

- Should `FloorPlanSpec` live in `placement/floorplan.py` or in
  `ops/_schema_placement.py` alongside `ZoneDefinition`? (Leaning: new module,
  re-importing `ZoneDefinition` to avoid bloating the ops schema file.)
- Does Quilter's Placement Region require a *named* association
  (component→region map) or just polygon geometry? The docs suggest polygon +
  component membership; needs a live upload test.
- For the `gr_poly` keepout emission, should we use `Dwgs.User` (non-electrical)
  or the dedicated `keepout` property on `(zone ...)`? KiCad 10 supports
  `(zone ... (keepout ...))` with flags — preferred for Quilter interop.

---

## Sources

- **Altium Rooms** — https://www.altium.com/documentation/altium-designer/pcb/rooms
- **Quilter Pre-placed Components** — https://docs.quilter.ai/design-parameters/pre-placed-components
- **Quilter Placement Regions** — https://docs.quilter.ai/design-parameters/placement-regions
- **Quilter vs Altium vs KiCad (2026)** — https://www.quilter.ai/blog/a-data-driven-look-at-pcb-layout-efficiency-in-2026-quilter-ai-vs-altium-vs-kicad
- **Cadence Constraint Manager** — (general reference; Allegro/OrCAD documentation)
- **KiCad design rules (.kicad_dru)** — KiCad documentation (no native rooms confirmed)
- **In-tree:** `gen_pcb.py`, `build_base_board.py`, `build_mono_blade.py`,
  `placement/{engine,layout_aware,zone_partition,signal_flow,scoring,thermal}.py`,
  `constraints/types.py`, `ops/_schema_placement.py`, `ops/handlers/pcb.py`,
  `crossfile/pcb_populate.py`, `ops/pcb_raw_writer.py`
