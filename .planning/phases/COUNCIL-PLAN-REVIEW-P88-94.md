# Council of Ricks -- All-Hands Plan Review: Phases 88-94

**Review Date**: 2026-06-14
**Milestone**: v4.1 Stage-Safe PCB Flow (Final 7 Phases)
**Review Type**: Plan Review (Pre-Execution Gate)
**Council Composition**: All-Hands (Wave Alpha + Beta + Gamma + Delta + Epsilon)

---

## Stack Assessment

- **Project Type**: Python (volta -- structural KiCad editing)
- **Core Framework**: Pydantic models, S-expression parsing, KiCad 10+ CLI
- **Gate Infrastructure**: Established (Phase 85) -- GateResult, GateDefinition, GateRunner, register_gate()
- **Existing Gates**: pre_pcb_schematic, schematic_intent (Phase 86), transfer_contract (Phase 87)
- **Component Classification**: `_classify_component_type()` exists in topology_graph.py (line 110)
- **DFM Infrastructure**: `DfmChecker`, `DfmReport`, `DfmFinding` exist in dfm/checker.py
- **DRC Infrastructure**: `DrcResult` exists in validation/erc_drc.py with `passed`, `violations`, `unconnected_items`
- **Routing Infrastructure**: A* router, diff pair routing, routing graph all exist in routing/
- **Operation Registry**: `add_net_class` and `add_design_rule` operations exist (registry.py:334, 343)

---

## Executive Summary

| Phase | Verdict | Critical | High | Medium | Low |
|-------|---------|----------|------|--------|-----|
| 88-01 | APPROVE WITH CONDITIONS | 0 | 2 | 3 | 2 |
| 88-02 | APPROVE WITH CONDITIONS | 0 | 1 | 2 | 1 |
| 89 | REJECT -- REVISE REQUIRED | 1 | 3 | 2 | 1 |
| 90 | APPROVE WITH CONDITIONS | 0 | 2 | 3 | 1 |
| 91 | APPROVE WITH CONDITIONS | 0 | 2 | 2 | 1 |
| 92 | REJECT -- REVISE REQUIRED | 2 | 3 | 2 | 1 |
| 93 | APPROVE WITH CONDITIONS | 0 | 2 | 3 | 1 |
| 94 | APPROVE WITH CONDITIONS | 0 | 1 | 2 | 1 |

**Overall Verdict**: 2 REJECTS (Phase 89, Phase 92), 6 APPROVES WITH CONDITIONS. All issues must be addressed before execution begins.

**Phase dependency chain**: 88 -> 89 -> 90 -> 91 -> 92 -> 93 -> 94. Phase 89 and 92 rejections block execution of their downstream phases until fixed.

---

## Cross-Phase Consistency Findings

### CPC-1 (HIGH): Type Name Mismatch -- DfmResult vs DfmReport

**Severity**: HIGH
**Location**: Phase 91-01-PLAN.md, step 2, line 62; must_haves line 16

Phase 91 references `DfmResult` (lines 16, 62) but the codebase has `DfmReport` (dfm/checker.py:55). The plan must use the existing type name or explicitly state it creates a new `DfmResult` adapter.

**Fix**: Update all references from `DfmResult` to `DfmReport` in the plan, or add a step to create an adapter class.

### CPC-2 (MEDIUM): Gate Registration Pattern Not Consistently Specified

**Severity**: MEDIUM
**Location**: All plans (88-01, 88-02, 89, 90, 91, 92)

The existing gate pattern (schematic_intent_gate.py:447-458) uses module-level registration:
```python
_gate = SchematicIntentGate()
register_gate(
    GateDefinition(name=..., from_stage=..., to_stage=..., check_fn_name=...),
    check_fn=_gate.run,
)
```

Plans 88-92 mention "Registers as `constraint_completeness`" but do not specify this module-level registration pattern. Plans should explicitly call out the `register_gate()` call at module scope matching the established pattern.

**Fix**: Add explicit `register_gate(GateDefinition(...), check_fn=...)` to each gate plan's steps.

### CPC-3 (MEDIUM): PCB IR Interface Assumptions Unverified

**Severity**: MEDIUM
**Location**: Phase 89 (check_footprint_bounds, check_courtyard_clearance, etc.), Phase 90 (PostRouteQualityGate)

Plans 89 and 90 assume `pcb_ir` provides methods like footprint bounds lookup, courtyard geometry, board outline polygon, and ratsnest length. The existing `PcbIR` (ir/pcb_ir.py:60) needs verification that these methods exist. Plans should list the specific PcbIR methods they depend on and note any that need to be added.

**Fix**: Add a "Prerequisites" section to each plan listing the specific PcbIR methods/SchematicIR methods required, flagging any that do not yet exist.

### CPC-4 (LOW): Test File Naming Convention Inconsistency

**Severity**: LOW
**Location**: Phase 93-01-PLAN.md (tests/test_golden_e2e.py)

Phase 93 uses `tests/test_golden_e2e.py` but the existing test directory convention separates gate tests into individual files (`test_schematic_intent_gate.py`, `test_transfer_contract.py`). The golden E2E tests are integration tests so a single file is acceptable, but the plan should note this is intentional.

### CPC-5 (HIGH): Constraint Completeness Gate Stage Registration Ambiguity

**Severity**: HIGH
**Location**: Phase 88-01 line 80 ("pcb_setup -> placement"), Phase 88-02 line 49

The plan states the constraint completeness gate registers as `pcb_setup -> placement`. But Phase 89's PlacementReadinessGate also registers as `placement -> routing`. There is no gate explicitly bridging `pcb_setup -> placement` yet. The constraint completeness gate fills this gap, which is correct. However, the plans need to clarify: does pcb_setup -> placement require BOTH the constraint gate AND something else, or is constraint completeness the sole gate for that transition?

**Fix**: Explicitly state in Phase 88-01 that `constraint_completeness` is the sole gate for `PCB_SETUP -> PLACEMENT` transition.

---

## Phase 88-01: Constraint Schemas, Propagator, Completeness Gate

**Verdict**: APPROVE WITH CONDITIONS
**Requirement Coverage**: CONST-01 through CONST-04 -- FULLY COVERED

### Findings

#### 88-01-H1 (HIGH): ConstraintPropagator .kicad_dru Writer Path Unspecified

**File**: Plan step 2, `ConstraintPropagator.propagate()`
**Location**: 88-01-PLAN.md:72

The plan says "Uses existing sexpdata-based .kicad_dru writer" but no .kicad_dru writer was found in the codebase (grep for `kicad_dru` in handlers/validation returns nothing). The registry confirms `add_net_class` and `add_design_rule` operations target `.kicad_dru` files (registry.py:337, 345), but the actual handler implementations need verification.

**Risk**: If the writer does not exist, the plan's 15-test target is unrealistic. If it exists but is incomplete, the propagator may need to fill gaps.

**Fix**: Add a prerequisite step to verify the existing `add_net_class` / `add_design_rule` handlers can write to `.kicad_dru` files. If they cannot, add a sub-step to extend them. The `must_haves` truth on line 22 claims "uses existing add_net_class and add_design_rule operations (not direct file writes)" -- this must be validated against actual handler code before execution.

#### 88-01-H2 (HIGH): Fab Profile Validation Against Known Minimums Lacks Specification

**File**: Plan step 1, `validate_achievable() -> list[str]`
**Location**: 88-01-PLAN.md:67

The method `validate_achievable()` is described as returning warnings "when constraints exceed known fab minimums" but the plan does not specify what "known minimums" means. Where does the reference data come from? The presets (`jlcpcb()`, `pcbway()`, `oshpark()`) have specific values, but `validate_achievable()` needs a reference point.

**Fix**: Specify that `validate_achievable()` checks the fab profile's own constraints (e.g., 0.1mm trace on a profile with `min_trace_width_mm = 0.15` is impossible) and cross-references electrical constraints against fab capability (e.g., 50-ohm impedance on 2-layer FR4 may be geometrically impossible).

#### 88-01-M1 (MEDIUM): ElectricalConstraints Missing Frequency/Signal Integrity Fields

**File**: Plan step 1, ElectricalConstraints model
**Location**: 88-01-PLAN.md:47-53

ROADMAP requirement CONST-01 mentions "impedance, diff pair" which is covered. But for a complete constraint model that Phase 90's routing quality gate will need, the schema is missing:
- `frequency_hz: Optional[float]` -- needed for signal integrity analysis
- `max_length_mm: Optional[float]` -- needed for length-matched groups
- `min_length_mm: Optional[float]` -- needed for length-matched groups

The `length_match` spec has `target_mm` and `tolerance_mm` which partially covers this, but a standalone net may need a max length constraint without a group.

**Fix**: Add `frequency_hz` and standalone length constraints to ElectricalConstraints, or document explicitly that these are deferred to Phase 90.

#### 88-01-M2 (MEDIUM): MechanicalConstraints Board Outline Type Should Be Polygon, Not List of Tuples

**File**: Plan step 1, MechanicalConstraints.board_outline
**Location**: 88-01-PLAN.md:55

`board_outline: Optional[list[tuple[float,float]]]` should be a proper Pydantic model or use `list[tuple[float, float]]` with a validator ensuring the polygon is closed (first point == last point). Raw tuples provide no validation.

**Fix**: Add a `@field_validator` for board_outline ensuring polygon closure, or create a `BoardOutline` model with validation.

#### 88-01-M3 (MEDIUM): Missing DesignConstraints.validate() Method

**File**: Plan step 1, DesignConstraints aggregate
**Location**: 88-01-PLAN.md:68

The aggregate model combines electrical, mechanical, and fab constraints but lacks a cross-field validation method. For example: electrical constraints specifying 100-ohm diff pairs with 0.1mm gap may be impossible for a 2-layer FR4 fab profile. The `validate_achievable()` is on FabProfileConstraints alone -- there needs to be a cross-constraint validation on DesignConstraints.

**Fix**: Add `DesignConstraints.validate_cross_constraints() -> list[str]` that checks electrical constraints against fab profile capabilities.

#### 88-01-L1 (LOW): Named Preset Names Should Match Existing Fab Profile Naming

**File**: Plan step 1, `jlcpcb()`, `pcbway()`, `oshpark()`
**Location**: 88-01-PLAN.md:66

Check if the existing `dfm/` module already has fab profile definitions with different naming. If DFM profiles exist with different names (e.g., `jlcpcb_standard` vs `jlcpcb`), align the preset names.

#### 88-01-L2 (LOW): ConstraintCompletenessGate "Nontrivial Nets" Definition Unspecified

**File**: Plan step 2, ConstraintCompletenessGate
**Location**: 88-01-PLAN.md:78

The gate checks "nontrivial nets (power, differential pairs, clocks) have constraints" but does not define "nontrivial" programmatically. The plan should reference the net intent classification from Phase 86 (`NetClassification`) and specify which intent types trigger the completeness check.

**Fix**: Specify that nets with intent classification `power`, `high_current`, `differential_pair`, `clock`, or `high_speed` must have electrical constraints.

---

## Phase 88-02: SetConstraintsOp/GetConstraintsOp Handler

**Verdict**: APPROVE WITH CONDITIONS
**Requirement Coverage**: CONST-05 -- COVERED

### Findings

#### 88-02-H1 (HIGH): SetConstraintsOp Missing Path Validation Pattern

**File**: Plan step 1, SetConstraintsOp schema
**Location**: 88-02-PLAN.md:42

The existing `UpdateFromSchematicOp` (pcb_transfer.py:73-85) has field validators rejecting path traversal (`..` in paths, null bytes, absolute paths). The `SetConstraintsOp` and `GetConstraintsOp` schemas do not mention this security pattern. The `project_dir: Optional[str]` field is a path input that must be validated.

**Fix**: Add `@field_validator("project_dir")` to both operations matching the pattern in pcb_transfer.py:73-85 (reject null bytes, reject absolute paths, reject `..` traversal).

#### 88-02-M1 (MEDIUM): Gate Wiring Into Chain Lacks Concrete Registration Code

**File**: Plan step 3
**Location**: 88-02-PLAN.md:49

Step 3 says "Wire ConstraintCompletenessGate into the GateRunner stage chain" but does not specify the registration code. The existing pattern is module-level `register_gate()` calls. The plan should show the concrete registration:

```python
register_gate(
    GateDefinition(
        name="constraint_completeness",
        from_stage=DesignStage.PCB_SETUP,
        to_stage=DesignStage.PLACEMENT,
        check_fn_name="constraint_completeness_gate",
    ),
    check_fn=_gate.run,
)
```

#### 88-02-M2 (MEDIUM): GetConstraintsOp Read Path for .kicad_dru Unspecified

**File**: Plan step 1, handle_get_constraints
**Location**: 88-02-PLAN.md:45

"reads .kicad_dru, returns DesignConstraints" -- but reading a .kicad_dru file and reverse-engineering DesignConstraints is non-trivial. The .kicad_dru contains net classes and design rules, not the original constraint schema. The plan should specify the reverse mapping or note that GetConstraintsOp returns the last-set constraints from a sidecar file (e.g., `.volta/constraints.json`).

**Fix**: Specify whether GetConstraintsOp reads from `.kicad_dru` (requires reverse mapping) or from a persisted constraint file. Recommend the latter for reliability.

#### 88-02-L1 (LOW): Test Count of "5+" Is Low for 2 Operations

**File**: must_haves line 22
**Location**: 88-02-PLAN.md:22

The plan specifies "5+ tests" but covers 2 operations plus gate integration. Minimum should be: set propagates correctly (1), get reads correctly (1), dry_run validates without writing (1), gate blocks without constraints (1), invalid constraints rejected (1), path traversal rejected (1) = 6 minimum.

---

## Phase 89: Placement Readiness Gate

**Verdict**: REJECT -- REVISE REQUIRED
**Requirement Coverage**: PLACE-01 through PLACE-05 -- COVERED but with critical gaps

### Findings

#### 89-C1 (CRITICAL): ComponentTypeClassifier Does Not Exist -- Plan References It as Existing

**File**: must_haves line 16, objective
**Location**: 89-01-PLAN.md:16

The plan states: "ComponentTypeClassifier extracts component role (IC, decoupling_cap, bulk_cap, connector, power_regulator, etc.) from footprint library_id and schematic net intent (Phase 86)"

This class does not exist. The codebase has `_classify_component_type(lib_id: str) -> str` in topology_graph.py:110 which returns simple types ("ic", "resistor", "capacitor", "inductor", "diode", "transistor", "connector", "misc"). The plan references `ComponentTypeClassifier` as if it exists with rich categories like "decoupling_cap", "bulk_cap", "power_regulator" -- these do not exist in the current classifier.

**Risk**: The decoupling proximity check (PLACE-04) and thermal spacing check (PLACE-05) both depend on this classification. Without it, the checks cannot identify which caps are decoupling or which components are thermal.

**Fix**: The plan must either:
1. Add a step to create `ComponentTypeClassifier` extending `_classify_component_type()` with net-intent-aware classification (cap connected to power net + small package = decoupling_cap), OR
2. Reframe the checks to work with the existing simple classification plus net intent data

This is a critical scope gap that makes the plan non-executable as written.

#### 89-H1 (HIGH): Decoupling Proximity Check Depends on Net Intent Data Not Available in PCB IR

**File**: must_haves line 17, check_decoupling_proximity
**Location**: 89-01-PLAN.md:17, 56

The check "Decoupling caps identified by: connected to power net + small package (0402/0603/0805) + near IC" requires:
1. Net-to-power-net classification (available from Phase 86 net intent)
2. Package size information (footprint library_id contains package size)
3. IC power pin locations (requires pin-level data from PCB)

The plan passes `pcb_ir` and `constraints` to `check_decoupling_proximity()` but does not specify how net intent data from the schematic phase reaches the placement gate. The gate context dict needs a `schematic_ir` or `net_intent` key.

**Fix**: Add `net_intent` or `schematic_ir` to the gate context dict specification. Specify how the gate accesses net-to-component power connections.

#### 89-H2 (HIGH): Courtyard Clearance Check Requires Courtyard Geometry from PCB

**File**: check_courtyard_clearance
**Location**: 89-01-PLAN.md:55

Courtyard data comes from the footprint's `*.Courtyard` layers in the .kicad_pcb file. The plan does not specify whether `PcbIR` exposes courtyard geometry. This is a fundamental prerequisite -- if PcbIR does not parse courtyard lines, the check cannot work.

**Fix**: Add a prerequisite step to verify PcbIR exposes courtyard geometry. If not, add a step to extend PcbIR with courtyard layer parsing.

#### 89-H3 (HIGH): Fixture Board Count Insufficient for 6 Sub-Checks

**File**: Plan step 2
**Location**: 89-01-PLAN.md:62-67

The plan creates 4 fixture boards (good, out_of_bounds, overlap, poor_decoupling) but has 6 sub-checks. Missing fixtures:
- No fixture for thermal spacing failure
- No fixture for mechanical/connector position failure
- No fixture for routability/density failure

**Fix**: Add fixtures: `placement_thermal_violation.kicad_pcb`, `placement_connector_wrong.kicad_pcb`, `placement_dense_blocked.kicad_pcb` -- minimum 7 fixtures.

#### 89-M1 (MEDIUM): Routability Heuristics Algorithm Unspecified

**File**: check_routability, objective line 43
**Location**: 89-01-PLAN.md:58, 43

"density score, ratsnest length estimate, blocked channel detection" -- these are complex algorithms with no specification. What formula computes density? How is ratsnest length estimated? What constitutes a "blocked channel"?

**Fix**: Define each heuristic:
- Density: component area / board area ratio, threshold > 0.7 = warning
- Ratsnest: Manhattan distance sum for unrouted nets, threshold TBD
- Blocked channel: corridor between components < 2mm wide

#### 89-M2 (MEDIUM): Analog/Digital Grouping Check Lacks Algorithm

**File**: must_haves line 24
**Location**: 89-01-PLAN.md:24

"Analog/digital grouping check: analog and digital sections separated" -- how is this determined? This requires net intent classification (analog vs digital) from Phase 86 and spatial clustering analysis. The plan does not specify the algorithm.

**Fix**: Define: components connected to analog-intent nets form the "analog group". Compute centroid of each group. If groups overlap (centroid distance < threshold), warn.

#### 89-L1 (LOW): Test Count "15+" May Be Insufficient

With 6 sub-checks, 7 fixture boards, and integration tests, 15 is tight. Recommend 20+ tests (3 per sub-check minimum + integration).

---

## Phase 90: Routing Readiness & Quality Gate

**Verdict**: APPROVE WITH CONDITIONS
**Requirement Coverage**: ROUTE-GATE-01 through ROUTE-GATE-05 -- COVERED

### Findings

#### 90-H1 (HIGH): PostRouteQualityGate kicad-cli Dependency Handling Needs More Detail

**File**: must_haves line 22
**Location**: 90-01-PLAN.md:22

The plan correctly handles kicad-cli unavailability (line 22: "returns GateResult(pass=False) with clear blocker"). However, the plan does not specify whether the PostRouteQualityGate can work WITHOUT kicad-cli for partial checks. The route quality metrics (completion %, via count) do not require kicad-cli -- they can be computed from PcbIR directly.

**Fix**: Separate the gate into:
1. kicad-cli-dependent checks (DRC, unconnected items) -- fail if unavailable
2. PcbIR-based checks (completion %, via count, diff pair gap) -- always run

This partial evaluation provides value even without kicad-cli.

#### 90-H2 (HIGH): A* Router Prototype Marking Mechanism Unspecified

**File**: must_haves line 23, ROUTE-GATE-05
**Location**: 90-01-PLAN.md:23

"A* router marked as prototype unless route quality gate passes" -- what does "marked as prototype" mean concretely? Is this a flag on the routing result? A warning in the GateResult? A metadata field on the PCB?

**Fix**: Specify: when PostRouteQualityGate has not run (or failed), routing results include `quality_status: "prototype"` in their metadata. After passing, `quality_status: "verified"`.

#### 90-M1 (MEDIUM): RouteQualityMetrics Quality Score Formula Unspecified

**File**: route_quality.py, quality_score field
**Location**: 90-01-PLAN.md:56

The `quality_score: float` composite (0.0-1.0) needs a formula. How are completion_pct, via_count, clearance_violations, and length_mismatch_pct combined?

**Fix**: Specify a formula, e.g.:
```
quality_score = (completion_pct/100) * 0.4
              + (1 - min(via_count/max_expected_vias, 1)) * 0.2
              + (1 - min(clearance_violations/max_allowed, 1)) * 0.2
              + (1 - length_mismatch_pct/100) * 0.2
```

#### 90-M2 (MEDIUM): Differential Pair Rule Check Scope Unclear

**File**: PostRouteQualityGate, "Validates differential pair rules (gap, length match)"
**Location**: 90-01-PLAN.md:65

The plan does not specify where differential pair definitions come from. These should come from DesignConstraints.electrical constraints (Phase 88). The plan should state this dependency explicitly.

**Fix**: "Reads diff_pair specs from DesignConstraints in gate context. For each pair, verifies routed gap matches spec, length mismatch within tolerance."

#### 90-M3 (MEDIUM): Return Path Risk Detection Algorithm Unspecified

**File**: RouteQualityMetrics.return_path_risk
**Location**: 90-01-PLAN.md:54

"return_path_risk: list[str] -- nets without return path" -- how is this detected? Return path analysis requires checking that each signal layer has an adjacent ground reference plane or ground pour.

**Fix**: Define: for each signal net, check if the layer below (or above) the primary trace layer has a ground plane zone. If not, add to return_path_risk list.

#### 90-L1 (LOW): Pre-Route Gate Check List Should Reference Constraint Gate Dependency

**File**: RoutingReadinessGate checks
**Location**: 90-01-PLAN.md:60

"placement gate passed" is listed as a prerequisite. The gate should verify this by checking for a passed PlacementReadinessGate result in the context dict, not just checking file existence.

---

## Phase 91: Manufacturing Readiness Gate

**Verdict**: APPROVE WITH CONDITIONS
**Requirement Coverage**: MFG-01 through MFG-05 -- COVERED

### Findings

#### 91-H1 (HIGH): DfmResult Type Does Not Exist -- Must Use DfmReport

**File**: must_haves line 16, step 1
**Location**: 91-01-PLAN.md:16

The plan references `DfmResult` in ManufacturingManifest (line 53: `dfm_result: Optional[DfmResult]`). The codebase has `DfmReport` (dfm/checker.py:55), not `DfmResult`. Using the wrong type name will cause an import error.

**Fix**: Change all references from `DfmResult` to `DfmReport`. The existing type has `findings: tuple[DfmFinding, ...]`, `checks_passed`, `checks_failed`, and a `summary` dict.

#### 91-H2 (HIGH): DFM Profile Pass Check Lacks Integration Specification

**File**: check_dfm_pass(context)
**Location**: 91-01-PLAN.md:62

"requires DFM profile pass" -- the existing `DfmChecker` (dfm/checker.py:133) produces a `DfmReport`. The plan must specify what constitutes a "pass": zero CRITICAL findings? Zero CRITICAL + zero HIGH? All checks passed?

**Fix**: Define: DFM pass = `DfmReport` has zero findings with severity CRITICAL or HIGH. Findings with MEDIUM or LOW severity are warnings, not blockers.

#### 91-M1 (MEDIUM): ManufacturingManifest SHA256 Computation Method Unspecified

**File**: ManufacturingArtifact.sha256
**Location**: 91-01-PLAN.md:46

The manifest includes SHA256 hashes for artifacts, but the plan does not specify the hashing method. SHA256 of file contents? Of normalized contents? Of the file path? The provenance field "generated_by (command)" also needs specification -- is this the kicad-cli command string?

**Fix**: Specify: `sha256 = hashlib.sha256(open(path, 'rb').read()).hexdigest()` and `generated_by = "kicad-cli pcb export gerbers ..."` (the actual command string).

#### 91-M2 (MEDIUM): Layer Completeness Check -- What Layers Are Required?

**File**: check_layer_completeness(context, fab_profile)
**Location**: 91-01-PLAN.md:64

"required layers exist for selected fab profile" -- which layers are required? This depends on the fab profile (2-layer vs 4-layer). The plan should list the minimum required layers per profile type.

**Fix**: Define: required layers for 2-layer = F.Cu, B.Cu, F.Mask, B.Mask, F.SilkS, B.SilkS, Edge.Cuts. For 4-layer = above + In1.Cu, In2.Cu.

#### 91-L1 (LOW): STEP Export May Not Be Required for All Boards

**File**: check_required_exports
**Location**: 91-01-PLAN.md:63

STEP export is listed as required. For simple 2-layer boards without complex mechanical constraints, STEP may be optional. Consider making STEP required only for boards with mechanical constraints.

---

## Phase 92: AI Boundary & Repair Loop

**Verdict**: REJECT -- REVISE REQUIRED
**Requirement Coverage**: AI-01 through AI-05 -- COVERED but with critical security gaps

### Findings

#### 92-C1 (CRITICAL): RepairLoop File Scope Enforcement Not Specified Mechanically

**File**: must_haves line 19, step 2
**Location**: 92-01-PLAN.md:19, 60

The plan states: "RepairLoop.executor is scoped to only permit operations targeting the same files the gate checked -- proposals targeting files outside gate context are rejected"

This is the most security-critical component in the entire milestone. The plan describes WHAT it does but not HOW. The existing `OperationExecutor` (executor.py:83) has path confinement (rejects paths outside `base_dir`) but NO per-gate-scope file restriction. The executor executes any valid operation -- it does not have a concept of "scoped to files the gate checked."

**Risk**: Without a concrete scoping mechanism, a malicious or hallucinated LLM proposal could target any file within the project directory, not just the files relevant to the current gate. This is an AI safety violation.

**Fix**: Add concrete implementation specification:
1. Gate context includes a `scope_files: list[Path]` key
2. RepairLoop creates a `ScopedExecutor` wrapper that intercepts `execute()` calls and rejects operations where `target_file not in scope_files`
3. `ScopedExecutor` raises `ScopeViolationError` on out-of-scope attempts
4. The scope check is BEFORE the operation is parsed, not after

#### 92-C2 (CRITICAL): Proposal Application Path Mutates Files Without Rollback Safety

**File**: step 2, RepairLoop.run()
**Location**: 92-01-PLAN.md:63-71

Step 5 says "Apply accepted proposals" then step 6 says "Rerun gate". If the rerun fails (gate still does not pass after the proposed fix), the files have already been mutated. The plan does not specify:
1. Whether proposals are applied in a Transaction (the existing executor uses Transactions)
2. Whether mutations are rolled back if the gate still fails after the repair
3. Whether there is a dry_run option for the entire repair loop

**Risk**: A repair attempt that makes things worse (proposes a fix that introduces a new violation) leaves the design in a WORSE state than before the repair loop ran.

**Fix**: Specify:
1. Each proposal application is wrapped in a Transaction
2. After all proposals in an iteration are applied, the gate reruns
3. If the gate still fails after max_iterations, all repair mutations in the final iteration are rolled back
4. The audit trail records what was attempted and what was rolled back

#### 92-H1 (HIGH): Fix Provider Registration Interface Unspecified

**File**: step 2, fix_providers
**Location**: 92-01-PLAN.md:73

`fix_providers: list[Callable]` -- what is the Callable signature? The plan does not define the interface that fix providers must implement. How does a fix provider receive blockers and generate proposals?

**Fix**: Define the fix provider protocol:
```python
class FixProvider(Protocol):
    def classify_blocker(self, blocker: str) -> str: ...
    def propose_fix(self, blocker: str, context: dict) -> Proposal | None: ...
```

#### 92-H2 (HIGH): No Fix Providers Defined for Any Gate

**File**: Entire plan
**Location**: 92-01-PLAN.md

The plan builds the RepairLoop infrastructure but defines zero fix providers. When the repair loop runs, `fix_providers` will be empty, meaning no proposals will ever be generated, and the loop will iterate 3 times doing nothing.

**Risk**: The RepairLoop is an empty shell without fix providers. Phase 93's golden E2E tests require "repair loop integration tested: gate failure -> propose -> fix -> rerun" -- this cannot work without fix providers.

**Fix**: Add at minimum one deterministic fix provider per gate type:
- Schematic intent: "add missing footprint" fix provider
- Placement: "move component inside outline" fix provider
- Routing: "mark unrouted net as manual" fix provider
- Manufacturing: "export missing artifacts" fix provider

These can be simple deterministic fixes, not LLM-generated.

#### 92-H3 (HIGH): Audit Trail Serialization Format Unspecified

**File**: step 2, RepairAuditEntry
**Location**: 92-01-PLAN.md:62

`RepairAuditEntry` has fields `iteration, blocker, proposal, accepted, source, result` but the plan does not specify how this is serialized. The plan says "Audit trail attached to GateResult.artifacts" -- but `GateResult.artifacts` is `list[str]` (gate_types.py:43), not a structured data field.

**Fix**: Either:
1. Serialize the audit trail to JSON and add the JSON string to artifacts, OR
2. Extend GateResult to include an `audit_trail: list[dict]` field (breaking change to frozen model)

Recommend option 1 for backward compatibility. Specify the JSON format.

#### 92-M1 (MEDIUM): Confidence Threshold for Proposal Acceptance Unspecified

**File**: Proposal.confidence
**Location**: 92-01-PLAN.md:52

The Proposal model has `confidence: float` (0.0-1.0) but the plan does not specify a threshold for acceptance. Should all validated proposals be applied regardless of confidence? Or is there a minimum confidence (e.g., 0.7)?

**Fix**: Specify acceptance criteria: proposals from `deterministic` source are always applied if valid. Proposals from `local_ai` require confidence >= 0.7. Proposals from `external_llm` require confidence >= 0.8 and human review flag.

#### 92-M2 (MEDIUM): Repair Loop Does Not Detect Infinite Loops Within Iterations

**File**: RepairLoop.run()
**Location**: 92-01-PLAN.md:63-71

The plan limits to max 3 iterations, but within a single iteration, a fix provider could propose a fix that causes a different blocker, which gets fixed in a way that causes the original blocker. The loop should detect when the same blocker appears across iterations.

**Fix**: Add: "Track blocker hashes across iterations. If the same blocker set appears in 2 consecutive iterations, stop the loop -- the fix providers cannot resolve this."

#### 92-L1 (LOW): ProposalValidator Uses "registry" Parameter -- Which Registry?

**File**: step 1, ProposalValidator.validate
**Location**: 92-01-PLAN.md:56

`validate(proposal: Proposal, registry) -> tuple[bool, str]` -- the `registry` parameter is ambiguous. Is this the operation registry (`ops/registry.py`) or a new proposal registry?

**Fix**: Clarify: `registry` is the existing operation registry (`OPERATION_REGISTRY` from ops/registry.py). The validator checks that `proposal.proposed_op.op_type` is a registered operation type.

---

## Phase 93: Golden E2E Boards

**Verdict**: APPROVE WITH CONDITIONS
**Requirement Coverage**: E2E-01 -- COVERED

### Findings

#### 93-H1 (HIGH): Fixture Board Creation Complexity Underestimated

**File**: Plan step 1, 6 board sets
**Location**: 93-01-PLAN.md:47-84

Creating 6 valid KiCad fixture boards (each with .kicad_sch + .kicad_pcb + expected_artifacts.json) is a massive effort. Each board needs:
- Valid S-expression syntax
- Valid symbol/footprint references
- Valid net connections
- Valid component placement (for placement gate)
- Valid routing (for routing gate)
- Valid DRC pass (for manufacturing gate)

The plan estimates this as a single phase with "20+ integration tests" but does not acknowledge the complexity of creating these fixtures.

**Fix**: Add a note that fixture boards may be created using the volta operation pipeline (building schematics programmatically via operations) rather than hand-authoring S-expressions. Add a step to verify fixtures pass ERC/DRC before integration tests run.

#### 93-H2 (HIGH): Repair Loop Integration Test Cannot Work Without Fix Providers

**File**: must_haves line 18
**Location**: 93-01-PLAN.md:18

"Repair loop integration tested: gate failure -> propose -> fix -> rerun" -- this depends on Phase 92 having fix providers (see 92-H2). If Phase 92 ships without fix providers, this test cannot pass.

**Fix**: Add cross-phase dependency note: "Phase 93 repair loop tests require Phase 92 fix providers for at least one gate type. If fix providers are deferred, repair loop tests should be marked as expected failures."

#### 93-M1 (MEDIUM): Total Test Time "<30 Seconds" May Be Unrealistic

**File**: verification
**Location**: 93-01-PLAN.md:104

Running 6 boards through all stage gates (including ERC, DRC via kicad-cli, DFM checks) in under 30 seconds is optimistic. kicad-cli DRC alone can take 5-10 seconds per board.

**Fix**: Change to "<120 seconds" or note that tests should use lightweight fixture boards with minimal component counts to stay fast.

#### 93-M2 (MEDIUM): Expected Artifacts List Not Specified Per Board

**File**: must_haves line 24, step 2
**Location**: 93-01-PLAN.md:24, 88

Each fixture has "expected_artifacts.json" but the plan does not specify what goes in each board's expected list. The LED board needs Gerbers + drill + BOM + CPL. The 4-layer board needs all of that + STEP. The plan should enumerate this.

**Fix**: Add a table mapping each board to its expected artifacts:
| Board | Gerbers | Drill | BOM | CPL | STEP |
|-------|---------|-------|-----|-----|------|
| LED | Yes | Yes | Yes | Yes | No |
| Buck | Yes | Yes | Yes | Yes | No |
| MCU | Yes | Yes | Yes | Yes | Yes |
| OpAmp | Yes | Yes | Yes | Yes | No |
| Connector | Yes | Yes | Yes | Yes | No |
| 4-layer | Yes | Yes | Yes | Yes | Yes |

#### 93-M3 (MEDIUM): Missing Negative Test Cases

**File**: test_golden_e2e.py
**Location**: 93-01-PLAN.md:90-97

All tests are positive ("passes all gates"). The plan should include at least one negative test: a deliberately broken board that fails a specific gate, proving the gates actually catch problems.

**Fix**: Add a 7th fixture: `deliberately_broken/` -- LED board with missing footprint. Test that schematic intent gate blocks it. Test that manufacturing gate never runs.

#### 93-L1 (LOW): Parametrized Test Naming Convention

**File**: step 3
**Location**: 93-01-PLAN.md:97

The parametrized test pattern `@pytest.mark.parametrize("board", ALL_BOARDS)` is good, but each test function should generate a clear test ID. Use `ids=lambda b: b` or a named ID function so test failures show which board failed.

---

## Phase 94: Docs & UX

**Verdict**: APPROVE WITH CONDITIONS
**Requirement Coverage**: DOCS-01 through DOCS-05 -- COVERED

### Findings

#### 94-H1 (HIGH): CLI Status Enhancement Scope Underestimated

**File**: Plan step 2, Enhance `volta status`
**Location**: 94-01-PLAN.md:49-54

The existing `handle_gate_status` (gate_handlers.py:69-99) already returns current stage and registered gates. The plan says "Enhance" but the existing code already does much of what the plan describes. The plan should specify exactly what changes are needed beyond what exists.

**Fix**: Add a gap analysis step comparing existing `handle_gate_status` output to desired output. Likely changes: (1) show last gate result per stage, (2) show blockers from most recent failed gate, (3) format as readable text instead of dict.

#### 94-M1 (MEDIUM): Getting-Started Rewrite May Break Existing Documentation References

**File**: Plan step 0, step 1
**Location**: 94-01-PLAN.md:41-43

The plan wisely says "Preserve non-gate-related content" and "Add gate sections rather than full rewrite." However, the existing docs may reference workflows that the gates now block. The plan should audit existing docs for workflow references that are now invalid.

**Fix**: Add a step: "Audit existing docs/getting-started.md for references to operations that now require gate passes. Update those references to include gate checks."

#### 94-M2 (MEDIUM): No Test for CLI Status Output

**File**: Verification
**Location**: 94-01-PLAN.md:77

The plan enhances CLI output but specifies no test for the new status format. All code changes should have tests.

**Fix**: Add: Create or extend `tests/test_gate_cli.py` to verify status output includes design stage, gate results, and blockers when applicable.

#### 94-L1 (LOW): Guarantees vs Suggestions Document Needs Legal-Safe Language

**File**: docs/guarantees-vs-suggestions.md
**Location**: 94-01-PLAN.md:63-66

"Guarantees" is a strong word in software. Consider "Deterministic Checks vs AI Suggestions" as the title, with a disclaimer that "guarantees" refers to the gate enforcement model, not a legal warranty of PCB correctness.

---

## Security Review Summary (Sentinel Rick + Rick C-137)

### Agent Autonomy Risks

| Phase | Risk | Severity | Status |
|-------|------|----------|--------|
| 92-C1 | RepairLoop scope not mechanically enforced | CRITICAL | MUST FIX |
| 92-C2 | Repair mutations not rolled back on failure | CRITICAL | MUST FIX |
| 92-H1 | Fix provider interface undefined | HIGH | MUST FIX |
| 88-02-H1 | SetConstraintsOp missing path validation | HIGH | MUST FIX |
| 92-M1 | No confidence threshold for AI proposals | MEDIUM | SHOULD FIX |

### File Mutation Risks

| Phase | Risk | Severity | Status |
|-------|------|----------|--------|
| 91 | Manufacturing gate generates files but plan does not specify cleanup on failure | MEDIUM | SHOULD ADD |
| 90 | Post-route gate runs kicad-cli DRC which may modify .kicad_pcb | LOW | VERIFY |

### Credential/Scope Boundary

| Phase | Risk | Severity | Status |
|-------|------|----------|--------|
| 92 | External LLM proposals need rate limiting and token tracking | MEDIUM | SHOULD ADD |

---

## SLC Validation (Slick Rick)

**Status**: PASS (on plan quality, not implementation)

### SLC Anti-Pattern Scan Results
- **TODOs in plans**: 0 found
- **FIXMEs in plans**: 0 found
- **Workaround language**: 0 found
- **"Good enough" language**: 0 found
- **Stub method references**: 0 found (Phase 87 stub detection is a feature, not anti-pattern)

### SLC Criteria Assessment

- [x] **Simple**: Plans build on established patterns (GateDefinition, register_gate, Pydantic models). Gate context dict is straightforward.
- [x] **Lovable**: Stage-safe flow is a compelling UX improvement. Status CLI will make gates discoverable.
- [ ] **Complete**: Phase 89 missing ComponentTypeClassifier. Phase 92 missing fix providers. These gaps make the plans non-executable as written.

**SLC Decision**: CONDITIONAL PASS -- plans are SLC-compliant in intent but have completeness gaps that must be filled.

---

## Historical Context (Rickfucius)

### Relevant Patterns from Codebase

1. **Gate Registration Pattern** (schematic_intent_gate.py:447-458): Module-level `register_gate()` with GateDefinition + check_fn. All new gates MUST follow this pattern. Phase 88-92 plans reference it but do not consistently specify the concrete registration code.

2. **Operation Handler Pattern** (gate_handlers.py, pcb_transfer.py): Handlers receive `(op, ir, file_path)` and return dict. Pydantic operation schemas with `@field_validator` for path safety. Phase 88-02's SetConstraintsOp/GetConstraintsOp must follow this pattern.

3. **Frozen Pydantic Models** (GateResult, TransferContract): All data models use `model_config = {"frozen": True}`. Phase 88's DesignConstraints and Phase 92's Proposal should follow this immutability pattern.

4. **Stub Detection Pattern** (pcb_transfer.py:93-135): `detect_stub_footprints()` and `detect_placeholder_pads()` are the existing stub detection mechanisms. Phase 87's UpdateFromSchematicOp already integrates these. Phase 92's RepairLoop should be aware of this existing infrastructure.

### Anti-Patterns to Avoid

1. **DO NOT** create new gate registration mechanisms. Use `register_gate()` from gate_runner.py.
2. **DO NOT** bypass the OperationExecutor for file mutations. All file changes go through `execute()`.
3. **DO NOT** add `force` or `bypass` fields to operation schemas (T-87-06, T-87-07 security pattern).
4. **DO NOT** create new DRC/DFM result types. Use existing `DrcResult` and `DfmReport`.

---

## Final Council Decision

### Phase-by-Phase Verdicts

| Phase | Verdict | Blocking Issues |
|-------|---------|-----------------|
| 88-01 | APPROVE WITH CONDITIONS | 88-01-H1, 88-01-H2 must be addressed |
| 88-02 | APPROVE WITH CONDITIONS | 88-02-H1 must be addressed |
| 89 | REJECT | 89-C1 (ComponentTypeClassifier does not exist) -- must revise plan |
| 90 | APPROVE WITH CONDITIONS | 90-H1, 90-H2 must be addressed |
| 91 | APPROVE WITH CONDITIONS | 91-H1 (DfmResult type name) must be addressed |
| 92 | REJECT | 92-C1 (scope enforcement), 92-C2 (rollback safety) -- must revise plan |
| 93 | APPROVE WITH CONDITIONS | 93-H1 (fixture complexity), 93-H2 (fix provider dependency) |
| 94 | APPROVE WITH CONDITIONS | 94-H1 (CLI status gap analysis) must be addressed |

### Execution Order After Fixes

1. **Fix Phase 89 plan** -- Add ComponentTypeClassifier creation step or reframe checks
2. **Fix Phase 92 plan** -- Add ScopedExecutor spec, rollback safety, fix provider definitions
3. **Address all HIGH findings** in approved phases (incorporate into revised plans)
4. **Address all MEDIUM findings** in approved phases (incorporate into revised plans)
5. **Address all LOW findings** (incorporate into revised plans)
6. Re-review revised plans for 89 and 92
7. Begin execution: Phase 88 -> 89 -> 90 -> 91 -> 92 -> 93 -> 94

### Mandatory Actions Before Execution

**ALL findings at ALL severities must be incorporated into revised plans before execution begins.**

1. [ ] Fix Phase 89 plan: Add ComponentTypeClassifier or reframe checks to use existing `_classify_component_type()`
2. [ ] Fix Phase 92 plan: Add ScopedExecutor specification, rollback safety, fix provider definitions
3. [ ] Phase 88-01: Validate `add_net_class`/`add_design_rule` handlers can write .kicad_dru
4. [ ] Phase 88-01: Specify `validate_achievable()` reference data
5. [ ] Phase 88-02: Add path validation to SetConstraintsOp/GetConstraintsOp schemas
6. [ ] Phase 90: Separate kicad-cli-dependent and independent gate checks
7. [ ] Phase 91: Change `DfmResult` to `DfmReport` throughout
8. [ ] Phase 91: Define DFM pass criteria (zero CRITICAL/HIGH findings)
9. [ ] Phase 93: Add deliberate-broken fixture for negative testing
10. [ ] Phase 94: Add CLI status output test
11. [ ] ALL phases: Add concrete `register_gate()` code to gate creation steps
12. [ ] ALL phases: List PcbIR/SchematicIR method dependencies in prerequisites

---

**Council Motto**: "84 specialists. 6 waves. Zero compromises. Every agent reviews. Every finding is fixed. Evil Morty makes the final call. No appeals."

**Review Completed**: 2026-06-14
**Review Duration**: Comprehensive all-hands review
**Next Action**: Revise Phase 89 and 92 plans, address all HIGH findings, re-review
