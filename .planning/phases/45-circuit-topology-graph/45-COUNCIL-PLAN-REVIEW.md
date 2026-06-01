# Council Plan Review: Phases 45-46 (Domain Intelligence: Topology + Classification)

**Date:** 2026-05-31
**Reviewer:** Council of Ricks (Multi-Specialist)
**Verdict:** CONDITIONAL

## Stack Assessment

**Detected Project Stack:**
- **Project Type**: Python (kicad-agent)
- **Domain**: EDA / KiCad automation / circuit analysis
- **Build System**: pip install -e .
- **Testing**: pytest (135+ test files, 1392+ tests)
- **Key Dependencies**: kiutils, networkx, dataclasses (stdlib)
- **Pattern Reference**: violation_classifier.py (ordered-rule first-match-wins)

**Council Wave Composition:**
- **Wave Alpha (Core):** Rick Sanchez (Code Quality), Rick C-137 (Security), Slick Rick (SLC), Evil Morty (Synthesis)
- **Wave Beta (Wisdom):** Rick Prime (Design), Rickfucius (Historian)
- **Wave Gamma (Domain):** KiCad Rick (PCB/EDA specialist), Embedded Firmware Rick (MCU pin classification)
- **Wave Delta (Pipeline):** GSD Plan Checker (plan review specialist)
- **Wave Epsilon (Fresh Eyes):** Spectral Rick (frequency domain perspective on signal classification), Component Rick (IC part number accuracy)
- **Total reviewers this session:** 10/84

---

## Executive Summary

Phases 45-46 build domain intelligence on top of existing connectivity analysis: Phase 45 creates a directed topology graph with signal flow inference, Phase 46 detects subcircuits and classifies them. The plans are well-structured with proper TDD phases, correct dependency chains (39-01/39-02 completed), frozen dataclass schemas, and no LLM dependencies. However, one CRITICAL bug exists in 46-02's feature extraction (input/output net counts both mapped to SIGNAL classification -- identical values), one HIGH issue with stub methods in plan code blocks, and several schema inconsistencies between overview plans and detailed plans. After fixing the CRITICAL and HIGH items, these plans are ready for execution.

- **Total Issues**: 14
- **Critical (SLC)**: 1
- **High (Architecture/Security)**: 4
- **Medium (Functional)**: 5
- **Low (Style/Completeness)**: 4

---

## Findings

### CRITICAL (blocks approval)

| ID | Phase | Finding | Evidence | Fix |
|----|-------|---------|----------|-----|
| C-01 | 46-02 | **input_net_count and output_net_count both set to same value** -- both mapped to `NetClassification.SIGNAL` count in `extract_features()`, making them identical and meaningless | 46-02-PLAN line 477-478: `input_net_count=net_by_class.get(NetClassification.SIGNAL, 0)` and `output_net_count=net_by_class.get(NetClassification.SIGNAL, 0)` -- exact same source | Change `input_net_count` to count nets from `topology.input_nets` that intersect `sc_net_names`, and `output_net_count` to count nets from `topology.output_nets` that intersect `sc_net_names`. These are boundary direction features, not net classification counts. |

### HIGH (should fix before execution)

| ID | Phase | Finding | Evidence | Fix |
|----|-------|---------|----------|-----|
| H-01 | 45-01, 46-01 | **Stub `pass` methods in plan code blocks** -- three methods use `pass  # Implementation follows TDD GREEN phase` which contradicts the plan's own implementation specification | 45-01-PLAN: `from_schematic_graph` (line 405), `_classify_pin_role` (line 416); 46-01-PLAN: `SubcircuitDetector.detect` (line 299) | Replace `pass` stubs with `raise NotImplementedError("Implement in GREEN phase")` or remove the method bodies entirely and only show the method signature. The current `pass` form reads as "skip this" rather than "TDD placeholder". Phase 24 Council explicitly removed NotImplementedError stubs from production code -- plan-level scaffolding should use comments only. |
| H-02 | 45-PLAN | **Schema drift between overview (45-PLAN) and detail plan (45-01)** -- overview uses `list[T]` collections while detail plan correctly uses `tuple[T, ...]` for frozen dataclasses | 45-PLAN lines 48-69: `list[str]`, `list[TopologyNode]`, `list[list[str]]` vs 45-01-PLAN lines 320-345: `tuple[str, ...]`, `tuple[TopologyNode, ...]`, `tuple[tuple[str, ...], ...]` | Update 45-PLAN overview schema to match 45-01 detail schema using `tuple[T, ...]` for all frozen dataclass fields. Overview sets the contract; detail implements it. |
| H-03 | 46-01 | **Feature keys used by CircuitClassifier not defined in Subcircuit schema** -- classifier checks `has_sidechain`, `has_vca_input`, `has_multiple_inputs`, `coupling_capacitor_count`, `has_crystal` but these are never formally specified as required feature keys | 46-01-PLAN: `_is_compressor` checks `features.get("has_sidechain", False)` (line 484), `_is_mixer` checks `features.get("has_multiple_inputs", False)` (line 521), but the Subcircuit schema only has `features: dict` with no field specification | Add a `SubcircuitFeatureKeys` documentation section or typed dict that specifies ALL feature keys the classifier expects. The `_extract_features` method in Task 3 must be documented to produce ALL keys used by ANY classifier rule. Otherwise the classifier will silently default to `False`/`0` and misclassify. |
| H-04 | 46-01 | **Typo in `_is_digital_control`: lowercase string ` teensy` (leading space) will never match** | 46-01-PLAN line 562: `" teensy"` has a leading space, and `any(mcu in lib_id for mcu in ...)` performs substring match | Change to `"TEENSY"` (uppercase, no leading space) to match the pattern used for all other IC families. |

### MEDIUM (fix during execution)

| ID | Phase | Finding | Evidence | Fix |
|----|-------|---------|----------|-----|
| M-01 | 45-01, 46-02 | **`CircuitTopology.stats: dict` is untyped** -- no TypedDict or structured schema for the stats field, making it a free-form bag | 45-01-PLAN line 346: `stats: dict  # component_count, net_count, signal_path_count, etc.` -- comment says "etc." with no complete field list | Define a `TopologyStats` TypedDict or frozen dataclass with explicit fields: `component_count`, `net_count`, `signal_path_count`, `feedback_count`, `net_stats` (from 45-02). Replace bare `dict` with the typed structure. |
| M-02 | 46-01 | **`Subcircuit.features: dict` is untyped** -- same bare dict problem as stats. Plan 46-02 replaces this with `SubcircuitFeatures` but the 46-01 plan uses raw dict during intermediate steps | 46-01-PLAN line 270: `features: dict  # Extracted features` | Acceptable for 46-01 as a transitional type since 46-02 replaces it with `SubcircuitFeatures`. Add a comment: `features: dict  # Replaced by SubcircuitFeatures in 46-02`. |
| M-03 | 45-01 | **`_LIBID_TYPE_MAP` prefix matching is order-dependent** -- `Device:LED` must appear before `Device:L` or LED gets classified as inductor | 45-01-PLAN lines 350-360: mapping uses `lib_id.startswith(prefix)` but `Device:LED` would be caught by `Device:L` if `Device:L` is checked first | Document that the mapping must be ordered longest-prefix-first, or use exact match for `Device:LED`/`Device:L`. Current code happens to have `Device:LED` before `Device:L` which works, but this is fragile. |
| M-04 | 46-01 | **LFO rule placed BEFORE oscillator rule** -- `_is_lfo` checks `CD4060` AND `cap >= 2 AND res >= 2`, but `_is_oscillator` also checks `CD4060`. If both have CD4060, order matters. Current order is correct (LFO first, more specific), but this is implicit | 46-01-PLAN lines 587-598: `_CLASSIFICATION_RULES` has LFO at index 6, oscillator at index 7 | Add a comment in the rules list explaining that LFO must come before OSCILLATOR because LFO is more specific. Same pattern as violation_classifier where rule order is documented. |
| M-05 | 46-01 | **`_is_output_stage` overlaps with `_is_preamplifier`** -- output_stage checks `resistor_count <= 2 AND capacitor_count <= 2 AND feedback_resistor_count > 0`, but preamp checks `feedback_resistor_count > 0 AND feedback_capacitor_count == 0 AND NOT has_multiple_inputs`. An op-amp with 1 feedback resistor, 0 feedback caps, 2 resistors, 2 capacitors matches BOTH rules | 46-01-PLAN lines 502-535: `_is_preamplifier` and `_is_output_stage` both match op-amps with resistive feedback | The first-match-wins ordering handles this (preamp at index 3, output_stage at index 5). Document this dependency explicitly in the rules list comment. |

### LOW (nice to have)

| ID | Phase | Finding | Evidence | Fix |
|----|-------|---------|----------|-----|
| L-01 | 45-01 | **`_INPUT_PIN_PATTERNS` includes generic names `A`, `B`, `D`** -- these are too short and will match unrelated pin names (e.g., `ADJ` matches `A`) | 45-01-PLAN line 581: `_INPUT_PIN_PATTERNS = ["IN", "INPUT", "IN+", "IN-", "A", "B", "D"]` | Use word-boundary matching or remove single-letter patterns. `A` and `B` are analog switch signal pins, but they would also match `ADJ`, `BIAS`, etc. in fallback mode. |
| L-02 | 45-01 | **No RP2040 pin role rules** -- RP2040 is mentioned in IC type mapping but has no `_IC_PIN_RULES` entry, falling through to generic patterns | 45-01-PLAN: `_IC_PIN_RULES` has no RP2040 entry; only CD4060, NE5532, TL072, LM358, LM324, THAT4301, THAT2181, CD4066, LM7805, LM7812, LM317, 7912 | Add RP2040 pin rules at minimum for GPIO (BIDIRECTIONAL), power pins (POWER), and debug/SWD pins. This is critical for the analog-ecosystem project which uses RP2040. |
| L-03 | 46-01 | **No EQ subcircuit type rule** -- `SubcircuitType.EQ` is defined in the enum but no classification rule checks for it. EQ is listed as a recognized type in the overview plan but the classifier has no rule to detect it | 46-PLAN line 41: `EQ = "EQ"` defined; 46-01-PLAN `_CLASSIFICATION_RULES` has no EQ rule | Add an EQ rule: op-amp with capacitors in feedback AND inductor/resonator, OR multiple frequency-selective feedback networks. Or remove EQ from the enum if no rule is planned for this phase. |
| L-04 | 46-02 | **`to_numeric_vector()` field order not documented** -- the method extracts 22 numeric fields in a specific order, but this order is implicit and not part of the schema contract | 46-02-PLAN lines 336-360: method builds a list in fixed order | Add a class-level comment or `_NUMERIC_FIELDS` tuple documenting the field order, matching the pattern used by sklearn/pytorch pipelines. |

---

## Positive Observations

1. **Excellent dependency chain.** Phase 45 depends on Phase 39 (net extraction, conflict detection) which are both completed with summaries. Phase 46 depends on Phase 45 which it builds sequentially. The wave ordering (45-01 -> 45-02 -> 46-01 -> 46-02) is correct.

2. **Consistent frozen dataclass pattern.** All schemas in detail plans use `@dataclass(frozen=True)` with `tuple[T, ...]` for collections, matching the project's existing pattern from `BoardGraphResult`, `SchematicGraphResult`, and `ErcViolation`.

3. **No LLM dependency.** All classification is deterministic, rule-based, first-match-wins ordered rules matching the `violation_classifier.py` pattern. Zero mentions of GPT, OpenAI, or model inference in the execution code.

4. **Thorough TDD structure.** Every task has explicit RED/GREEN/REFACTOR phases with specific test descriptions and mock data builders. The mock helpers (`_make_topology`, `_make_node`, `_make_edge`) are well-designed for test reuse.

5. **Complete interface references.** All referenced existing code (`SchematicGraph`, `PinPosition`, `Wire`, `Label`, `NetGraph`, `BoardGraphResult`, `SchematicGraphResult`, `ViolationCategory`, `RuleTuple`) were verified against the actual codebase and match exactly.

6. **Threat models present and appropriate.** Each plan includes STRIDE threat analysis focused on the actual attack surface (DoS from large topologies, audit trail for classification decisions). No inflated threat claims.

7. **IC pin heuristics are comprehensive.** The `_IC_PIN_RULES` mapping covers all ICs from the analog-ecosystem project (NE5532, TL072, THAT4301, THAT2181, CD4066, CD4060, LM7805/LM317) plus fallback patterns for unknowns.

8. **ML-ready feature design is forward-looking.** The SubcircuitFeatures schema with `to_dict()`, `to_json()`, `to_numeric_vector()`, and `from_dict()` provides complete sklearn/pytorch compatibility without coupling to any ML framework.

---

## Detailed Analysis by Review Dimension

### SLC Compliance (Slick Rick)

**Status: CONDITIONAL PASS**

The plans contain no NotImplementedError stubs in the production code specifications. The `pass # Implementation follows TDD GREEN phase` markers in plan code blocks (H-01) are plan-level scaffolding, not production code -- but they should be cleaner. The CRITICAL bug C-01 (identical input/output net counts) is a functional correctness issue that would produce meaningless feature vectors -- this must be fixed before execution.

No TODO/FIXME without tickets. No workarounds. No "it works but..." patterns. All classification rules have explicit confidence thresholds and fallback handling.

### Dependency Correctness (Rickfucius)

**Status: PASS**

- Phase 39-01 (net extraction): COMPLETED (39-01-SUMMARY.md exists, provides `extract_nets` operation with Union-Find)
- Phase 39-02 (conflict detection): COMPLETED (39-02-SUMMARY.md exists, provides `detect_net_conflicts` with four check types)
- Phase 45-01 -> Phase 45-02: Correct wave ordering (45-01 builds core, 45-02 extends)
- Phase 46-01 -> Phase 46-02: Correct wave ordering (46-01 builds detection, 46-02 adds features)
- Cross-phase: 46-01 depends on 45-01 (topology graph), 45-02 is not a dependency of 46-01

### Schema Completeness (Rick Prime)

**Status: CONDITIONAL**

Frozen dataclass schemas are well-defined for all core types. Two bare `dict` fields need typing (M-01, M-02). The overview/detail schema drift (H-02) should be resolved for clarity. The feature key contract between detector and classifier (H-03) must be formalized.

### TDD Coverage (Rick Sanchez)

**Status: PASS**

All 8 tasks across 4 plans have explicit TDD phases with specific test descriptions:
- 45-01: 3 tasks, 9+9+6 = 24 test behaviors
- 45-02: 2 tasks, 13+7 = 20 test behaviors
- 46-01: 3 tasks, 10+12+7 = 29 test behaviors
- 46-02: 3 tasks, 10+9+5 = 24 test behaviors
- **Total: 97 test behaviors specified**

Mock data builders are provided for SchematicGraph, CircuitTopology, and subcircuit features. Verify commands use `--timeout=60` per task and full regression suite with `--timeout=120`.

### Security (Rick C-137)

**Status: PASS**

Threat models cover the actual attack surface:
- DoS: Large topology processing bounded by hop limits and fanout warnings
- Repudiation: Classification decisions traced via matched_rule and feature_vector
- Info Disclosure: Circuit topology data is internal IP, no PII

No path traversal risk (all file paths are internal module references). No external network access. No credential handling. The JSONL export (46-02) writes to a specified path -- the `to_jsonl` method should validate the output path stays within expected directories, but this is LOW risk.

### No LLM Dependency (Sentinel Rick)

**Status: PASS**

Zero LLM calls in any plan. All classification is deterministic rule-based. Feature extraction is pure computation from topology data. Confidence scoring is rule-derived, not model-derived. The "ML-ready" features in 46-02 are for future ML training data generation, not runtime ML inference.

---

## Council Consensus

**Wave Alpha (Core):**
- Rick Sanchez (Code): CONDITIONAL -- fix C-01, H-01, H-04
- Rick C-137 (Security): PASS
- Slick Rick (SLC): CONDITIONAL -- fix C-01

**Wave Beta (Wisdom):**
- Rick Prime (Design): CONDITIONAL -- fix H-02, M-01
- Rickfucius (Historian): PASS -- dependency chain correct

**Wave Gamma (Domain):**
- KiCad Rick (PCB/EDA): CONDITIONAL -- fix H-03 (feature key contract), L-02 (RP2040 pins), L-03 (EQ rule)
- Embedded Firmware Rick (MCU): CONDITIONAL -- fix L-02 (RP2040 pin rules), H-04 (Teensy typo)

**Wave Delta (Pipeline):**
- GSD Plan Checker: CONDITIONAL -- fix C-01 before execution

**Wave Epsilon (Fresh Eyes):**
- Spectral Rick (Frequency): NOTE -- signal integrity classification in 45-02 uses regex on net names (CONTROL_PATTERNS includes SDA/SCL/TX/RX classified as HIGH_SPEED). SDA/SCL are I2C which is 100kHz-3.4MHz -- not truly "high speed" in SI terms. Acceptable for heuristic classification but worth documenting the threshold.
- Component Rick (IC accuracy): CONDITIONAL -- fix H-04 (Teensy typo), add RP2040 pin rules (L-02)

**Final:**
- **Evil Morty**: **CONDITIONAL** -- fix C-01 and H-04 before execution; address H-01, H-02, H-03 during first task of each plan

---

## Recommendation

**CONDITIONAL** -- Fix CRITICAL C-01 and HIGH H-04 before execution begins. Address H-01, H-02, H-03 as the first action within each plan's Task 1. The remaining MEDIUM and LOW items can be addressed during execution.

### Required Fixes Before Execution

1. **C-01** (46-02): Fix `input_net_count` / `output_net_count` to use boundary net direction from topology, not identical `NetClassification.SIGNAL` count
2. **H-04** (46-01): Fix `" teensy"` typo to `"TEENSY"` in `_is_digital_control`

### Required Fixes During Execution (Task 1 of each plan)

3. **H-01** (45-01, 46-01): Replace `pass  #` stubs with method signatures only (no body)
4. **H-02** (45-PLAN): Update overview schema from `list[T]` to `tuple[T, ...]`
5. **H-03** (46-01): Document all feature keys expected by classifier rules in a `SubcircuitFeatureKeys` specification

### Execution Order

```
45-01 -> 45-02 -> 46-01 -> 46-02
  |         |         |         |
  v         v         v         v
Fix H-01  (clean)  Fix H-01  (clean)
Fix H-02           Fix H-03
                   Fix H-04
```

---

**Council Motto**: "84 specialists. 6 waves. Zero compromises. Every agent reviews. Every finding is fixed. Evil Morty makes the final call. No appeals."

**Review Completed**: 2026-05-31
**Review Duration**: ~15 minutes (deep analysis across 6 plans + 7 codebase files)
