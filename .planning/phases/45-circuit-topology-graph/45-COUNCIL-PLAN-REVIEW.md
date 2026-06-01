# Council Plan Review: Phases 45-46 (Domain Intelligence: Topology + Classification)

**Date:** 2026-05-31
**Reviewer:** Council of Ricks (Multi-Specialist, Deep Re-Review)
**Verdict:** CONDITIONAL

## Stack Assessment

**Detected Project Stack:**
- **Project Type:** Python (kicad-agent)
- **Domain:** EDA / KiCad automation / circuit analysis / ML training data
- **Build System:** pip install -e .
- **Testing:** pytest (135+ test files, 1392+ tests)
- **Key Dependencies:** dataclasses (frozen), networkx, kiutils, re (regex)
- **Pattern Reference:** violation_classifier.py (ordered-rule first-match-wins)

**Council Wave Composition:**
- **Wave Alpha (Core):** Rick Sanchez (Code Quality), Rick C-137 (Security), Slick Rick (SLC), Evil Morty (Synthesis)
- **Wave Beta (Wisdom):** Rick Prime (Design), Rickfucius (Historian)
- **Wave Gamma (Domain):** KiCad Rick (PCB/EDA specialist, circuit topology), Embedded Firmware Rick (MCU pin classification)
- **Wave Delta (Pipeline):** GSD Plan Checker (plan review specialist)
- **Wave Epsilon (Fresh Eyes):** Spectral Rick (frequency domain on signal classification), Component Rick (IC part number accuracy)
- **Total reviewers this session:** 10/84

---

## Executive Summary

Phases 45-46 introduce domain intelligence to kicad-agent by building a directed circuit topology graph with signal flow inference (Phase 45) and rule-based subcircuit detection with ML-ready feature extraction (Phase 46). The plans are well-structured with proper TDD phases, frozen dataclass schemas, correct dependency chains, and thorough test coverage (97+ test behaviors across 4 sub-plans). However, there are 3 CRITICAL issues (circular import risk, schema drift, stub method ambiguity), 6 HIGH issues (identical field computation, missing SchematicIR method, wrong rule ordering, overly generic pin patterns, pin numbering error in test text, Teensy typo), 8 MEDIUM issues, and 4 LOW issues. The architecture is sound but requires structural fixes before execution.

- **Total Issues:** 21
- **Critical (SLC/Architecture):** 3
- **High (Correctness/Security):** 6
- **Medium (Functional):** 8
- **Low (Style/Completeness):** 4

---

## Findings

### CRITICAL (must fix before execution)

| ID | Phase | Finding | Evidence | Recommendation |
|----|-------|---------|----------|----------------|
| C-1 | 45-01/45-02 | **Circular import between topology_graph.py and net_classifier.py.** topology_graph.py imports NetClassifier (45-01-PLAN line 692). net_classifier.py imports NetClassification and PinRole from topology_graph.py (45-01-PLAN line 705). This creates A -> B -> A at module level. Python may handle same-direction circular imports at runtime, but enums should not live in topology_graph.py if net_classifier.py needs them -- the import could fail depending on import order. | 45-01-PLAN Task 3 step 3: `from kicad_agent.analysis.net_classifier import NetClassifier` in topology_graph.py. Same plan Task 3 step 3: `from kicad_agent.analysis.topology_graph import NetClassification, PinRole` in net_classifier.py. Two modules importing from each other at module level. | Move NetClassification and PinRole enums to a separate `src/kicad_agent/analysis/types.py` module that both files import from. Or move the enums into net_classifier.py (since it is the classification authority) and have topology_graph.py import from there. Either approach breaks the cycle cleanly. |
| C-2 | 45-PLAN vs 45-01 | **Schema type mismatch between overview and sub-plan.** 45-PLAN.md defines TopologyNode.power_pins: list[str] and CircuitTopology.nodes: list[TopologyNode], but 45-01-PLAN.md correctly uses tuple[str, ...] and tuple[TopologyNode, ...] for frozen dataclass immutability. The overview is what reviewers and downstream consumers read first. | 45-PLAN.md lines 48-69: list[str], list[TopologyNode], list[list[str]]. 45-01-PLAN.md lines 320-345: tuple[str, ...], tuple[TopologyNode, ...], tuple[tuple[str, ...], ...]. The overview does not mark the dataclass as frozen. | Update 45-PLAN.md schemas to match 45-01-PLAN.md: use tuple[...] for all collection fields and add @dataclass(frozen=True). This matches the established pattern from BoardGraphResult, SchematicGraphResult, and ErcViolation. |
| C-3 | 45-01, 46-01 | **Stub methods in plan code without explicit GREEN-phase replacement instructions.** Three methods contain `pass  # Implementation follows TDD GREEN phase`. The GREEN-phase action steps describe the algorithm but do not show replacing these stubs. The executor could leave `pass` in place. | 45-01-PLAN lines 405, 416, 421-432: `from_schematic_graph`, `_classify_pin_role`, `_build_nodes`, `_build_edges`, `_detect_feedback`, `_trace_signal_paths` all have `pass` bodies. 46-01-PLAN line 299: `SubcircuitDetector.detect` has `pass` body. | Either (a) provide actual method implementations in GREEN phase steps, or (b) add explicit instructions: "Replace the pass stub in from_schematic_graph with the complete pipeline from Task 4 step 5." Option (b) is recommended -- the current form reads as "skip this" rather than "implement during GREEN." |

### HIGH (should fix before execution)

| ID | Phase | Finding | Evidence | Recommendation |
|----|-------|---------|----------|----------------|
| H-1 | 46-02 | **input_net_count and output_net_count computed identically.** Both are set to `net_by_class.get(NetClassification.SIGNAL, 0)` in extract_features(), making them always equal and meaningless as features. | 46-02-PLAN Task 1 step 3 code: `input_net_count=net_by_class.get(NetClassification.SIGNAL, 0)` and `output_net_count=net_by_class.get(NetClassification.SIGNAL, 0)` -- exact same source on consecutive lines. | Fix input_net_count to count boundary nets entering the subcircuit (from topology.input_nets intersecting sc_net_names), and output_net_count to count boundary nets leaving (from topology.output_nets intersecting sc_net_names). These are direction features, not classification counts. |
| H-2 | 45-PLAN | **Overview claims SchematicIR input but sub-plan only implements SchematicGraph input.** 45-PLAN.md says "from SchematicIR or SchematicGraph" and 45-01 must_haves truth 7 says "TopologyBuilder builds from SchematicGraph or SchematicIR interchangeably." But no task creates from_schematic_ir(). | 45-PLAN.md line 29: "from SchematicIR or SchematicGraph". 45-01-PLAN must_haves: "TopologyBuilder builds from SchematicGraph or SchematicIR interchangeably." Only `from_schematic_graph()` method is implemented. | Either add `from_schematic_ir()` with SchematicIR-to-SchematicGraph conversion, or remove the SchematicIR claim from overview and must_haves. SchematicIR has different access patterns (no wire/label position data) requiring a substantially different approach. Recommend removal for this phase -- SchematicIR support can be Phase 45-03. |
| H-3 | 45-02 | **SignalIntegrity rule ordering wrong: CONTROL patterns matched before POWER by topology.** A net named "SCL" connecting only to power pins would be classified HIGH_SPEED (from CONTROL match) instead of POWER_INTEGRITY (from topology rule). Power-by-topology is a stronger signal. | 45-02-PLAN _SIGNAL_INTEGRITY_RULES order: Clock -> CONTROL patterns -> Power by name -> Ground by name -> Power by topology -> Audio -> DC. The _is_power_by_topology rule is position 5. | Move _is_power_by_topology before the CONTROL patterns rule. In violation_classifier, more-specific context rules come first. Power-by-topology (all pins are power pins) is more specific than name-based control pattern matching. |
| H-4 | 45-01 | **_INPUT_PIN_PATTERNS includes "A", "B", "D" which cause false positives.** Single-letter pin names match unrelated pins: "A" matches "ADJ", "B" matches "BIAS", "D" matches dozens of pin names. These are analog switch signal pins but the fallback applies to ALL unknown ICs. | 45-01-PLAN line 581: `_INPUT_PIN_PATTERNS = ["IN", "INPUT", "IN+", "IN-", "A", "B", "D"]`. The _classify_pin_role fallback at line 601-610 uses `pin_name_upper.startswith(pattern)` -- "A" matches "ADJ", "BIAS" starts with "B". | Remove "A", "B", "D" from _INPUT_PIN_PATTERNS. These are too generic for a fallback. The IC-specific _IC_PIN_RULES already handle known ICs correctly; the fallback should be conservative with only unambiguous patterns. |
| H-5 | 45-01 | **Op-amp pin number error in test behavior text.** Test Task 2 Test 1 says "pin 8 (OUT) classified as OUTPUT" but NE5532 OUT is on pin 1 (first amp) and pin 7 (second amp). Pin 8 is V+. The mock data correctly uses pin 1 for OUT, but the prose contradicts the mock. | 45-01-PLAN Task 2 behavior line 456: "pin 8 (OUT) classified as OUTPUT". Mock data line 485: `PinPosition(ref="U1", pin_number="1", pin_name="OUT", ...)`. NE5532 datasheet: pin 1=OUT(A), pin 7=OUT(B), pin 8=V+. | Fix test behavior text to: "pin 1 (OUT) classified as OUTPUT, pin 8 (V+) classified as POWER." The mock data is correct; only the prose needs updating. |
| H-6 | 46-01 | **Typo in _is_digital_control: lowercase " teensy" with leading space will never match.** The substring match `any(mcu in lib_id for mcu in ...)` will fail because the leading space prevents matching "TEENSY" in any lib_id. | 46-01-PLAN line 562: `" teensy"` has a leading space. All other MCU names in the list are uppercase without spaces. | Change to `"TEENSY"` (uppercase, no leading space) to match the pattern used for all other IC families. |

### MEDIUM (fix during execution)

| ID | Phase | Finding | Evidence | Recommendation |
|----|-------|---------|----------|----------------|
| M-1 | 45-01 | **Net resolution reimplemented instead of using existing trace_endpoint_to_net().** The plan says "Use label positions and wire connectivity" but the existing SchematicGraph.trace_endpoint_to_net() (schematic_graph.py lines 153-181) does BFS wire tracing through junctions with proximity matching. Reimplementing risks edge cases. | 45-01-PLAN Task 2 step 5: "Use label positions and wire connectivity to determine which pins share a net" -- describes reimplementing net resolution. schematic_graph.py line 153: `trace_endpoint_to_net()` does exactly this with BFS. | In Task 2 step 5 (_build_edges), explicitly call graph.trace_endpoint_to_net() for each pin position to determine net membership. Reuse existing BFS wire tracing that handles junctions, multi-hop wires, and proximity matching. |
| M-2 | 45-01 | **No test for multi-sheet/hierarchical schematics.** All test mocks are single-sheet SchematicGraph objects. Real schematics in analog-ecosystem use hierarchical sheets with global labels connecting across sheets. | All mock SchematicGraph objects in 45-01-PLAN have no hierarchical labels or multi-sheet references. The analog-ecosystem project has 15-sheet schematics. | Add at least one test with global labels on separate components with no wire between them (connected via global label). This tests the label-based connectivity path that is critical for multi-sheet designs. |
| M-3 | 45-02 | **NetStats.is_stub detection relies on "dead-end" component types but none are defined.** The plan says "net connects to exactly one component that is a dead-end (test point, LED, etc.)" but TopologyNode.component_type has no "test_point" or "led" type -- only "ic", "resistor", "capacitor", "inductor", "diode", "transistor", "connector", "misc". | 45-02-PLAN Task 2 step 4: "is_stub = net connects to exactly one component that is a dead-end (test point, LED, etc.)". The _LIBID_TYPE_MAP in 45-01 does not map Device:Test_Point or Device:LED_Small. | Add "test_point" to _LIBID_TYPE_MAP with pattern "Device:Test_Point" -> "test_point". LEDs fall under "diode" but the stub detection should check lib_id for LED variants explicitly, not just component_type. |
| M-4 | 46-01 | **Subcircuit clustering hop count not specified.** The plan says "collect all components within 1-2 hops" but does not specify when to use 1 vs 2 hops. The compressor (THAT4301 + NE5532) requires 2 hops. | 46-PLAN line 68: "For each IC, collect all components within 1-2 hops on signal nets." 46-01-PLAN: no explicit hop count in detect algorithm. | Define explicitly: use 2 hops for initial clustering, then prune components on power-only nets. Or define as "all components reachable via SIGNAL-classified edges from the center IC, up to 2 hops." |
| M-5 | 46-01 | **Subcircuit.features is bare dict -- should be typed.** The Subcircuit schema has features: dict which loses type safety. | 46-01-PLAN line 270: `features: dict  # Extracted features`. | Acceptable for 46-01 as transitional since 46-02 replaces with SubcircuitFeatures. Add comment: `# Replaced by SubcircuitFeatures in 46-02`. |
| M-6 | 46-01 | **Feature keys used by CircuitClassifier not formally specified.** The classifier checks has_sidechain, has_vca_input, has_multiple_inputs, coupling_capacitor_count, has_crystal but these are never listed as required keys. Missing keys silently default to False/0 causing misclassification. | 46-01-PLAN: _is_compressor checks features.get("has_sidechain", False), _is_mixer checks features.get("has_multiple_inputs", False). No SubcircuitFeatureKeys spec. | Document ALL feature keys expected by ANY classifier rule. The _extract_features method in 46-01 Task 3 must produce every key used by any rule. |
| M-7 | 45-01 | **Threat model T-45-01 mentions max_paths=100 but no task implements this limit.** The _trace_signal_paths method does not include this parameter. | 45-01-PLAN threat model: "signal path trace limited to max_paths=100". Task 4 _trace_signal_paths signature has no max_paths parameter. | Add max_paths: int = 100 parameter to _trace_signal_paths and from_schematic_graph. Log warning when limit is hit. This is a DoS mitigation that must be implemented, not just documented. |
| M-8 | 46-01 | **_LIBID_TYPE_MAP prefix matching is order-dependent.** Device:LED must appear before Device:L or LED gets classified as inductor. Current code has LED before L (works), but this is fragile. | 45-01-PLAN lines 350-360: `Device:LED: "diode"` then `Device:L: "inductor"`. The startswith check means order matters. | Document that the mapping must be ordered longest-prefix-first. Or use exact match for ambiguous prefixes. |

### LOW (suggestions)

| ID | Phase | Finding | Evidence | Recommendation |
|----|-------|---------|----------|----------------|
| L-1 | 45-01 | **No RP2040 pin role rules despite being in IC type mapping.** RP2040 is recognized as "ic" type but has no _IC_PIN_RULES entry, falling through to generic patterns. | 45-01-PLAN: ic_patterns list includes "RP2040" but _IC_PIN_RULES has no RP2040 entry. The analog-ecosystem project uses RP2040 extensively. | Add RP2040 pin rules: GPIO (BIDIRECTIONAL), power pins (POWER), debug/SWD (CONTROL), USB pins (BIDIRECTIONAL). |
| L-2 | 46-01 | **No EQ subcircuit type rule despite EQ being in the enum.** SubcircuitType.EQ is defined but no classification rule detects it. | 46-PLAN line 41: `EQ = "EQ"`. 46-01-PLAN _CLASSIFICATION_RULES has no EQ rule. | Add EQ rule or remove EQ from enum if not planned for this phase. EQ detection requires identifying frequency-selective feedback networks. |
| L-3 | 46-02 | **to_jsonl uses str path instead of Path.** The rest of the codebase uses pathlib.Path consistently. | 46-02-PLAN Task 3: `to_jsonl(self, subcircuits, output_path: str)`. graph_builder.py and schematic_graph_builder.py use Path. | Change to output_path: Path for consistency. |
| L-4 | 46-02 | **to_numeric_vector() field order not documented.** The method builds a fixed-order list but the order is implicit and not part of the schema contract. | 46-02-PLAN: method builds list in fixed order but no _NUMERIC_FIELDS constant or documentation. | Add _NUMERIC_FIELDS tuple documenting the field order for ML pipeline consumers. |

---

## Positive Observations

1. **Excellent dependency chain.** Phase 45 depends on Phase 39 (net extraction, conflict detection) which are both completed with summaries. Phase 46 depends on Phase 45 with correct wave ordering (45-01 -> 45-02 -> 46-01 -> 46-02).

2. **Consistent frozen dataclass pattern.** All schemas in detail plans use @dataclass(frozen=True) with tuple[T, ...] for collections, matching BoardGraphResult, SchematicGraphResult, and ErcViolation.

3. **No LLM dependency.** All classification is deterministic, rule-based, first-match-wins ordered rules matching violation_classifier.py. Zero mentions of model inference in execution code.

4. **Thorough TDD structure.** Every task has explicit RED/GREEN/REFACTOR phases with specific test descriptions and mock data builders. Total: 97+ test behaviors across 8 tasks.

5. **Complete interface references.** All referenced existing code (SchematicGraph, PinPosition, Wire, Label, NetGraph, BoardGraphResult, SchematicGraphResult, ViolationCategory, RuleTuple) verified against actual codebase and match exactly.

6. **Threat models present and appropriate.** Each plan includes STRIDE threat analysis focused on actual attack surface (DoS from large topologies, audit trail for classification decisions).

7. **IC pin heuristics are comprehensive.** _IC_PIN_RULES covers all ICs from analog-ecosystem project (NE5532, TL072, THAT4301, THAT2181, CD4066, CD4060, LM7805/LM317) plus fallback patterns.

8. **ML-ready feature design is forward-looking.** SubcircuitFeatures with to_dict(), to_json(), to_numeric_vector() provides sklearn/pytorch compatibility without framework coupling.

---

## Detailed Analysis by Review Dimension

### SLC Compliance (Slick Rick)

**Status: CONDITIONAL PASS**

No NotImplementedError stubs in production code specifications. No TODO/FIXME without tickets. No workarounds. No "it works but..." patterns. The pass-stubs in plan code blocks (C-3) are plan-level scaffolding, not production code -- but need explicit replacement instructions. The identical field computation (H-1) is a functional correctness issue producing meaningless features.

### Dependency Correctness (Rickfucius)

**Status: PASS**

- Phase 39-01 (net extraction): COMPLETED (39-01-SUMMARY.md exists)
- Phase 39-02 (conflict detection): COMPLETED (39-02-SUMMARY.md exists)
- Phase 45-01 -> 45-02: Correct wave ordering
- Phase 46-01 -> 46-02: Correct wave ordering
- Cross-phase: 46-01 depends on 45-01 only; 45-02 is not a prerequisite for 46-01

### Schema Completeness (Rick Prime)

**Status: CONDITIONAL**

Frozen dataclass schemas well-defined in detail plans. Two bare dict fields need typing (M-5, M-6). Overview/detail schema drift (C-2) must be resolved. Feature key contract between detector and classifier (M-6) must be formalized.

### TDD Coverage (Rick Sanchez)

**Status: PASS**

All 8 tasks across 4 plans have explicit TDD phases:
- 45-01: 3 tasks, 9+10+8 = 27 test behaviors
- 45-02: 2 tasks, 13+7 = 20 test behaviors
- 46-01: 3 tasks, 10+12+7 = 29 test behaviors
- 46-02: 3 tasks, 10+9+5 = 24 test behaviors
- **Total: 100+ test behaviors specified**

Mock data builders provided for SchematicGraph, CircuitTopology, and subcircuit features. Verify commands use --timeout=60 per task and full regression suite with --timeout=120.

### Security (Rick C-137)

**Status: PASS**

Threat models cover actual attack surface:
- DoS: Large topology processing bounded by hop limits and fanout warnings
- Repudiation: Classification decisions traced via matched_rule and feature_vector
- Info Disclosure: Circuit topology data is internal IP, no PII
- Circular import risk (C-1) could cause ImportError at runtime but is not a security vulnerability

No path traversal risk. No external network access. No credential handling.

### No LLM Dependency (Sentinel Rick)

**Status: PASS**

Zero LLM calls. All classification deterministic rule-based. Feature extraction is pure computation. Confidence scoring is rule-derived. ML-ready features in 46-02 are for future training data generation, not runtime inference.

---

## Council Consensus

**Wave Alpha (Core):**
- Rick Sanchez (Code): CONDITIONAL -- fix C-1 (circular import), C-3 (stubs), H-4 (pin patterns), H-5 (pin numbering)
- Rick C-137 (Security): PASS
- Slick Rick (SLC): CONDITIONAL -- fix H-1 (identical features)

**Wave Beta (Wisdom):**
- Rick Prime (Design): CONDITIONAL -- fix C-2 (schema drift), H-3 (rule ordering)
- Rickfucius (Historian): PASS -- dependency chain correct, follows established patterns

**Wave Gamma (Domain):**
- KiCad Rick (PCB/EDA): CONDITIONAL -- fix M-6 (feature key contract), L-1 (RP2040 pins), L-2 (EQ rule)
- Embedded Firmware Rick (MCU): CONDITIONAL -- fix L-1 (RP2040 pin rules), H-6 (Teensy typo)

**Wave Delta (Pipeline):**
- GSD Plan Checker: CONDITIONAL -- fix C-1, C-2, C-3 before execution

**Wave Epsilon (Fresh Eyes):**
- Spectral Rick: NOTE -- SDA/SCL classified as HIGH_SPEED in signal integrity rules. I2C is 100kHz-3.4MHz, not truly "high speed" in SI terms. Acceptable for heuristic classification but should be documented.
- Component Rick: CONDITIONAL -- fix H-6 (Teensy typo), add RP2040 pin rules (L-1)

**Final:**
- **Evil Morty:** CONDITIONAL -- fix C-1 through C-3 and H-1 through H-6, then proceed.

---

## Recommendation

**CONDITIONAL** -- Fix the 3 CRITICAL and 6 HIGH issues before execution. The architecture is sound and the plans follow established patterns. The issues are structural/correctness problems that are straightforward to fix but would cause bugs or confusion during execution.

### Required Fixes Before Execution

1. **C-1** (45-01/45-02): Break circular import -- move NetClassification/PinRole enums to types.py or into net_classifier.py
2. **C-2** (45-PLAN): Update overview schema from list[T] to tuple[T, ...]
3. **C-3** (45-01, 46-01): Add explicit "Replace pass stub with implementation" instructions in GREEN phases
4. **H-1** (46-02): Fix input_net_count / output_net_count to use boundary net direction
5. **H-2** (45-PLAN): Remove SchematicIR claim or add from_schematic_ir method
6. **H-3** (45-02): Reorder SignalIntegrity rules -- power-by-topology before CONTROL patterns
7. **H-4** (45-01): Remove "A", "B", "D" from _INPUT_PIN_PATTERNS
8. **H-5** (45-01): Fix "pin 8 (OUT)" to "pin 1 (OUT)" in test behavior text
9. **H-6** (46-01): Fix " teensy" typo to "TEENSY"

### Track During Execution (MEDIUM)

10. **M-1:** Use existing trace_endpoint_to_net() for net resolution
11. **M-2:** Add global label connectivity test
12. **M-3:** Define dead-end component types for stub detection
13. **M-4:** Define hop count for subcircuit clustering (recommend 2 hops)
14. **M-5:** Type Subcircuit.features as dict[str, Any]
15. **M-6:** Document all feature keys expected by classifier rules
16. **M-7:** Add max_paths=100 parameter to _trace_signal_paths
17. **M-8:** Document longest-prefix-first ordering for _LIBID_TYPE_MAP

### Execution Order

```
45-01 -> 45-02 -> 46-01 -> 46-02
  |         |         |         |
  v         v         v         v
Fix C-1   Fix C-1   Fix C-3   Fix H-1
Fix C-2   Fix H-3   Fix H-6
Fix C-3             Fix M-6
Fix H-2
Fix H-4
Fix H-5
```

---

**Council Motto**: "84 specialists. 6 waves. Zero compromises. Every agent reviews. Every finding is fixed. Evil Morty makes the final call. No appeals."

**Review Completed**: 2026-05-31
**Review Duration**: ~25 minutes (deep analysis across 6 plans + 7 codebase files)
