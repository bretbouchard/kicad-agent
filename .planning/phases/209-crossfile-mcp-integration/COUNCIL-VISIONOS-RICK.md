# Council Review — VisionOS Rick

**Phase:** 209 (reviewing the v7.0 manufacturing layer end-to-end)
**Review Date:** 2026-07-10
**Reviewer:** VisionOS Rick (spatial computing specialist, visionOS 26+)
**Perspective:** Could the manufacturing workflow benefit from spatial computing?
**Verdict:** YES — with one honest caveat. The generation layer stays on macOS. The review/inspection layer is a legitimate spatial computing target, and there is one killer use case.

---

## Executive Summary

I am the first to reject an iPad app floating in space. Most "visionOS port" proposals I see are crimes against the medium — flat forms pasted into 3D with no spatial reasoning. I expected to reject this one too. I did not.

The v7.0 manufacturing layer produces data that is **inherently spatial**: DRC violations happen at physical coordinates, boards are 3D objects with layer stackups, and the handoff package already emits a STEP 3D model. This is not a text workflow dressed up as 3D — it is a physical-object workflow that is currently being forced through 2D text reports and JSON. The spatial computing fit is genuine.

There is one killer use case: **a spatial DRC review volume** — the board as a real 3D object you walk around, with violations floating as spatial annotations at their actual coordinates. And there is one blocking data gap that must be closed first: the `Violation` records drop the coordinates that the evaluator already computes.

**What does NOT belong in visionOS:** The generation layer (LLM, intent JSON, AST mutation, MCP, operations registry, daemon). That is a text/code/data workflow. It stays on macOS. visionOS is a review and inspection client, not an editing environment.

**My recommendation:** Do not build a visionOS app now (v7.0 is not the time). But close the coordinate-enrichment gap in the `Violation` records during v7.1, because it costs almost nothing and unlocks the spatial path. Then evaluate a visionOS manufacturing review companion app as a real v8.0 candidate.

---

## The Spatial Data Inventory

I read the data models before forming opinions. Here is what the manufacturing layer actually carries, mapped to spatial dimensions:

### NativeBoard Geometry (fully spatial)

File: `src/volta/parser/pcb_native_types.py`

| Data Model | Spatial Fields | Spatial Mapping |
|---|---|---|
| `NativeSegment` | `start` (X,Y), `end` (X,Y), `width`, `layer` | 2D line on a named Z-layer |
| `NativeVia` | `position` (X,Y), `drill`, `diameter`, `layers` (start,end) | Z-spanning cylinder between layers |
| `NativeFootprint` | `position` (X,Y,angle), `layer` | Placed component with rotation |
| `NativePad` | `position` (X,Y), `drill`, `layers` | Pad with Z-span |
| `NativeStackup` | `layers` with `name`, `type`, `thickness` | The Z-axis itself |
| `NativeGeneral` | `thickness` (board, default 1.6mm) | Board Z-dimension |
| `NativeBoardOutline` | `items` on Edge.Cuts layer | The board silhouette |

This is a complete 3D-representable geometry graph. Every track, via, pad, and component has X,Y coordinates plus layer (Z-stratum). The stackup provides layer-to-Z mapping with physical thicknesses. This is enough to reconstruct the board in 3D — and KiCad already does exactly this for its 3D viewer.

### STEP Export (the spatial ace in the hole)

File: `src/volta/export/general.py:176` — `export_step()`

The handoff package already produces a `.step` 3D model via `kicad-cli pcb export step`. STEP is directly convertible to USDZ (Apple's tooling does this). USDZ loads natively into RealityKit via `Entity(named:in:)`. This means the spatial 3D model of the board is **already being generated** — it just lands in a zip file instead of a visionOS volume.

This is the single most important fact for my review. The 3D asset pipeline already exists. The manufacturing layer is already a 3D-asset-producing system.

### BoardSpec (physical properties)

File: `src/volta/manufacturing/board_spec.py`

`SurfaceFinish`, `SoldermaskColor`, `SilkscreenColor`, copper weights, `ImpedanceRequirement` (net_name, target_ohms, reference_layer). These are physical manufacturing properties. They are not coordinates — but they describe a physical object. In a spatial context, they become visual attributes of the 3D board model (the soldermask color literally colors the model; the impedance requirements annotate specific traces).

### Build Records + Handoff Packages

File: `src/volta/manufacturing/build.py`, `handoff.py`

`Build` (versioned record with artifacts, git_sha, status lifecycle), `HandoffResult` (zip with Gerbers, BOM, STEP, renders, readme, manifest). These are document/data artifacts — metadata about the manufacturing process. Flat data, not spatial, but they accompany the spatial STEP asset.

---

## THE Blocking Data Gap (must close before spatial works)

This is the one finding I want the council to act on. It is small, cheap, and unlocks everything.

### Violation records drop the coordinates the evaluator already computes

File: `src/volta/manufacturing/vendor_drc.py`

The vendor DRC evaluator iterates over real geometry with real coordinates, then throws the coordinates away when constructing `Violation` records.

**Track width check** (`_check_track_width`, line 173): The loop reads each `seg` which has `.start` and `.end` (X,Y coordinates). But the emitted `Violation.items` dict contains only `{net, layer, actual_mm, required_mm}`. The coordinates of the offending track are gone.

**Clearance check** (`_check_clearance`, line 369): This is the most painful one. The loop has `sx1, sy1, ex1, ey1` and `sx2, sy2, ex2, ey2` — the full coordinates of BOTH violating segments. It computes the exact gap. Then the `Violation.items` records `{layer, actual_gap_mm, required_mm, net_a, net_b}`. The midpoint of the violation (the ideal annotation anchor) is trivially computable from these coords — but it is not persisted.

**Drill / annular ring checks**: Same pattern. The `via` has `.position` (X,Y), the `pad` has `.position` (X,Y). The Violation records the dimension but not where on the board the problem is.

**Why this matters for spatial computing:** Every spatial annotation use case depends on knowing WHERE a violation is. The data exists at computation time. It is dropped at serialization time. This is not a hard problem — it is a 4-field addition to each `items` dict: `x_mm`, `y_mm`, `layer`, and for pair-violations `x2_mm`, `y2_mm`.

**Cost to fix:** Trivial. Each check function already has the coordinates in local variables. Add them to the items dict. No new parsing, no new geometry computation, no architectural change. This is a v7.1 task that takes an hour and unlocks the entire spatial path.

**Recommendation:** Add `ENRICH-1` requirement to v7.1: "All DRC/vendor-DRC violations must persist the (x_mm, y_mm, layer) coordinates of the offending feature(s) in the items dict." This is useful even on macOS (a 2D board view can jump to violations), but it is MANDATORY for spatial.

---

## Question-by-Question Review

### Q1: Could DRC violations be displayed as spatial annotations on a 3D board model in visionOS?

**YES. This is the killer use case.** This is the one that justifies the entire spatial computing exercise.

Here is why this is spatial-native and not iPad-in-3D:

A DRC violation is not a row in a table. It is a physical location on a physical object where a manufacturing constraint is violated. The clearance between two tracks is too small AT a specific point on the board. The drill is too small AT a specific via. These are spatial facts about a spatial object. Forcing them into a scrolling text list is a representation problem, not a data problem — the data is spatial, the representation is not.

**The spatial vision:** Load the handoff STEP model as USDZ into a `RealityView` volumetric window. The board floats at table height, scaled up to ~30cm (real boards are ~10cm — too small to inspect; spatial computing lets you choose the comfortable scale). For each violation, place a spatial annotation — a small glass pill with a red severity dot — at the violation's mapped (X,Y,layer) coordinate on the board model. Gaze at an annotation to focus it; pinch to expand the full violation detail (actual vs required, net names, layer) as a glass detail panel that orients toward the user.

The annotations live IN the 3D space of the board, not on a 2D overlay. You walk around the board and see violations from the back. You lean in to see a cluster. You look at the bottom layer to see the violations there. This is depth as architecture — the thing my entire philosophy demands.

**Blocking dependency:** ENRICH-1 (coordinate persistence in Violations). Without it, you cannot place annotations. With it, this use case is immediately buildable.

**Implementation sketch (visionOS 26+):**
```swift
// VolumetricWindow with the board + violation annotations
RealityView { content in
    // STEP -> USDZ, loaded async
    let board = try await Entity(named: "board.usdz", in: bundle)
    content.add(board)
    // For each violation, spawn an annotation entity at mapped coords
    for v in violations {
        let anchor = ViolationAnnotationEntity(violation: v, boardBounds: boardBounds)
        board.addChild(anchor)
    }
}
```
The annotation entities use `spatialPosition` within the board's local frame. Gaze + pinch for detail expansion. No 2D overlays — pure spatial.

### Q2: Would a spatial handoff package preview be useful?

**YES. Strong fit, and it maps cleanly to spatial layout principles.**

The handoff package (`handoff.py`) bundles heterogeneous artifacts: a 3D model (STEP), a text report (readme.md), structured data (manifest.json), manufacturing files (Gerbers), a parts list (BOM CSV). On macOS these are files in a folder. In visionOS, these are naturally spatial objects at different depths.

**Spatial layout (this is where I reject the flat approach):**
- **Primary (z = -1.5m, arm's length):** The 3D board model (STEP → USDZ), floating and slowly rotating. This is the physical artifact the package represents. It is the hero.
- **Secondary left (x = -1.0m, z = -2.0m, scale 0.8):** The readme as a glass document panel — title, revision, specs, validation results. This is the "what is this" context.
- **Secondary right (x = +1.0m, z = -2.0m, scale 0.8):** The manifest as a structured glass panel — build_id, git_sha, status, artifact list with sizes and hashes. This is the "provenance" data.
- **Tertiary (z = -3.0m, scale 0.6, reduced opacity):** The Gerbers and BOM as smaller glass chips — gaze to summon, pinch to open as a detail sheet.

This is depth-as-hierarchy: the physical board is most important (closest), the human-readable report and machine-readable manifest are context (mid-depth), the raw files are reference (far). The user can look around the layout naturally.

**The validation results** from `HandoffValidation` (DRC/ERC/vendor-DRC pass/fail + violation counts) become a spatial status banner — green glass if all passed, red glass with counts if any failed. This is glanceable, not buried in JSON.

This is a legitimate spatial experience, not an iPad port. The artifacts have natural depth relationships that a flat file listing cannot express.

### Q3: Could vendor DRC clearance results be visualized as a 3D heat map?

**YES, and this is where the spatial advantage over 2D is most dramatic.**

The clearance check (`_check_clearance`) computes the gap between every same-layer track pair. The result is a gap value per pair. On a 2D board view, you can color violating segments red — but you lose the magnitude information (how close to the limit is each non-violating pair?).

**The spatial heat map:** Color every track segment by its clearance headroom — the ratio of actual gap to required gap. Green (safe, >2x margin) → yellow (approaching, 1.0-2.0x) → orange (tight, 1.0-1.1x) → red (violation, <1.0x). Each segment is a colored line in (X,Y,layer) space. The layer stackup provides Z-separation, so you see the heat map per layer — F.Cu on top, In1.Cu below, etc., stacked in Z like a real board.

**Why 3D beats 2D here:** On a 2D view, multi-layer boards collapse all layers onto one plane, making it impossible to see which layer a tight clearance is on. In 3D, the layers separate in Z — you literally see the clearance situation per physical layer, the way the copper actually exists. Dense violation clusters in a corner of one layer become immediately visible as a red hot-spot floating at that layer's Z-height.

This is depth communicating information (layer identity) that 2D fundamentally cannot. That is my definition of spatial-native.

**Implementation note:** This requires the ENRICH-1 coordinates PLUS the gap value (which is already in the violation items as `actual_gap_mm`). The heat map colors non-violating segments too, which means you'd want to expose the full pairwise gap data, not just violations — a small extension to emit a clearance report alongside violations.

### Q4: Is there value in a visionOS manufacturing review app?

**YES — this is the product thesis, and I will defend it.**

PCB manufacturing review is a 3D-native problem wearing a 2D disguise. Boards are physical objects. Violations are spatial. The review process — "will this manufacture correctly?" — is fundamentally a visual inspection of a physical artifact. Currently that inspection happens by reading text reports and scrolling violation lists. That is a lossy compression of a spatial reality.

**The product:** A visionOS companion app ("KiCad Manufacturing Review") that opens a handoff package and presents it as a spatial manufacturing review volume:
- The board as a walkable 3D model
- DRC violations as spatial annotations (Q1)
- Clearance heat map toggleable on/off (Q3)
- BoardSpec as visual attributes + floating annotations (soldermask color applied to the model, impedance requirements annotated on their nets)
- Validation status as ambient glass banners
- Build provenance (git_sha, rev, timestamp) as a glanceable sidecar

**The workflow win:** An engineer reviewing a board for manufacturing readiness can physically walk around the board, lean into dense areas, flip it over to inspect the bottom layer, and see all violations in their true spatial relationship. A cluster of clearance violations in one corner is immediately visible as a spatial pattern, not a list of coordinates you have to mentally map onto the board. This is the inspection speedup that justifies the platform.

**The collaboration angle (mixed immersion):** Multiple engineers (via Personas) can review the same floating board simultaneously, each pointing at violations. This is the ".mixed" immersion use case — collaborative 3D review with spatial awareness. This is where visionOS earns its existence over a desktop 3D viewer.

**Honest scope:** This is a review/inspection client only. It does NOT edit the board. It does NOT run the LLM. It does NOT mutate files. It reads handoff packages and presents them spatially. The editing stays on macOS. This boundary is what makes it a legitimate spatial app rather than a bloated port.

### Q5: How would the BoardSpec editor work in a spatial UI?

**Mostly: it wouldn't, and shouldn't. With one exception.**

The `BoardSpec` model (`board_spec.py`) is form data: enum pickers (SurfaceFinish, SoldermaskColor, SilkscreenColor) and numeric fields (copper weights). A spatial form with pickers and steppers is iPad-in-3D. I reject it. BoardSpec editing belongs in a glass sidecar panel — a flat 2D form, honestly, because it IS flat data.

**The one exception — impedance requirements are spatial-native:**

`ImpedanceRequirement` has `net_name`, `target_ohms`, `reference_layer`. Editing these in a table is clunky. In a spatial context, you gaze at a specific trace on the 3D board model, pinch to select it, and assign an impedance target. The target appears as a spatial annotation floating above that trace ("50Ω to GND"). You can see all impedance-controlled nets at a glance because they're annotated in space on the board itself.

This is spatial-native: the data (impedance) is a property of a spatial object (a physical trace), and the assignment happens by interacting with the object in space, not by typing a net name into a field.

**So the BoardSpec editor in visionOS is:** A flat glass form panel for the enums and weights (honestly, maybe just reuse the macOS form in a window), PLUS a spatial impedance-assignment mode where you tag traces directly on the 3D model. The first part is a concession to flat data. The second part is the spatial win.

---

## What Does NOT Belong in visionOS

I would be dishonest if I did not draw this boundary clearly.

**The generation layer is not spatial.** The core value proposition (LLM → intent JSON → AST mutation → valid KiCad file) is a text/code/data workflow. Intent JSON is structured text. AST mutation is tree editing. The MCP daemon, operations registry, verification loop, governance layer, rollback snapshots — all of this is backend logic with no spatial representation. Putting any of this in visionOS is iPad-in-3D. I veto it.

**Schematic editing is 2D.** Schematics are 2D graph layouts (components + wires). They are not 3D. A visionOS schematic editor would be a flat canvas floating in space — which is just a big monitor. No spatial value.

**BOM generation is tabular.** It is a CSV. Tables are flat. A floating table is not spatial computing.

**The visionOS boundary:** Manufacturing REVIEW and INSPECTION (the handoff package, the DRC results, the board as a physical object). Not manufacturing GENERATION or EDITING.

---

## Concrete Recommendations

### For v7.1 (cheap, unlocks the spatial path)

1. **ENRICH-1 (HIGH):** Persist `(x_mm, y_mm, layer)` coordinates in every vendor-DRC `Violation.items` dict. The data already exists in the evaluator loops — it is a 4-field addition per check. This is useful on macOS (2D board view can locate violations) and MANDATORY for any spatial annotation.
2. **ENRICH-2 (MEDIUM):** Emit a clearance report (all pairwise gaps, not just violations) alongside the `VendorDrcResult` to enable heat-map visualization. Currently only violations are reported; the heat map needs the full gap distribution.

### For v8.0 (the spatial candidate)

3. **Investigate a visionOS manufacturing review companion app** as a real product candidate. It is a read-only spatial client over handoff packages. The data models already support it (modulo ENRICH-1/2). The 3D asset pipeline (STEP export) already exists.
4. **Start with a spike:** Load a real handoff STEP as USDZ into a `VolumetricWindow`, place 3-4 hardcoded violation annotations at mapped coordinates, validate the spatial layout feels native. If the spike feels like iPad-in-3D, kill it. If it feels like the board is a real object you're inspecting, greenlight the full app.

### What I explicitly do NOT recommend

- Do NOT build a visionOS app in v7.0 or v7.1. The manufacturing layer needs to ship on macOS first.
- Do NOT spatial-ize the BoardSpec form (except the impedance-assignment interaction).
- Do NOT port the schematic editor or the generation pipeline to visionOS.
- Do NOT make the spatial app an editor. Read-only review and inspection only.

---

## Verdict

**Does the manufacturing workflow benefit from spatial computing?** Yes, specifically and narrowly: the review and inspection of DRC results and handoff packages on a 3D board model. The spatial data already exists in the geometry models. The 3D asset (STEP) is already being generated. The one missing piece is coordinate persistence in violation records (ENRICH-1), which is a trivial fix that also benefits the macOS app.

**Is there a killer spatial computing use case?** Yes: the spatial DRC review volume — a board you walk around with violations floating at their true coordinates. This is depth-as-architecture, gaze-driven inspection, and physical-object reasoning. It is the opposite of iPad-in-3D.

**Is now the time?** No. Close ENRICH-1 in v7.1. Evaluate the visionOS companion as a v8.0 candidate after the macOS manufacturing layer is battle-tested. The spatial path is real, but it is not urgent, and rushing it would produce a port instead of a native spatial experience.

**SLC Compliance:** N/A (no visionOS code in v7.0 to review). This is a forward-looking architectural assessment. When visionOS code is written, it must be spatial-native (volumetric, depth-layered, gaze-driven) or I will veto it.

---

*VisionOS Rick — Tier 2 (Stack-Aware Specialist), spatial computing domain*
*"visionOS is not iPad in 3D. The manufacturing review layer is not iPad data. The fit is genuine."*
