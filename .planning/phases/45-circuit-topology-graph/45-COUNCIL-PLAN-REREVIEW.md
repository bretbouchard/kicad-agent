# Council Plan Re-Review: Phases 45-46 (Wave 1)

**Date:** 2026-05-31
**Reviewer:** Council of Ricks (Re-Review Wave 1)
**Previous Verdict:** CONDITIONAL
**Re-Review Verdict:** CONDITIONAL

---

## Finding Status Table

| ID | Severity | Original Finding | Status | Evidence |
|----|----------|-----------------|--------|----------|
| C-01 | CRITICAL | input_net_count/output_net_count identical (SIGNAL) | **FIXED** | 46-02 line 477: `len(topology.input_nets & sc_net_names)`, line 478: `len(topology.output_nets & sc_net_names)` -- uses boundary net intersection |
| H-01 | HIGH | `pass # Implementation follows TDD GREEN phase` stubs | **PARTIALLY FIXED** | 45-01/46-01: stubs now have `# GREEN: Replace this stub with...` + `# Do NOT leave this as a stub.` instructions per task step. Body is still comment-only (no code). Improved from silent pass to explicit replacement instructions, but method bodies remain empty in RED-phase code blocks. |
| H-02 | HIGH | `list[T]` in overview schema | **FIXED** | 45-PLAN lines 48-69: all collections now use `tuple[str, ...]`, `tuple[TopologyNode, ...]`, `tuple[tuple[str, ...], ...]`. All three dataclasses have `@dataclass(frozen=True)`. Zero `list[` occurrences. |
| H-03 | HIGH | Feature keys not formally specified | **FIXED** | 46-01 lines 758-775: explicit `Required feature keys (consumed by CircuitClassifier rules):` block listing all 16 keys with types and descriptions -- has_sidechain, has_vca_input, has_multiple_inputs, has_crystal, coupling_capacitor_count, feedback_capacitor_count, feedback_resistor_count, resistor_count, capacitor_count, inductor_count, diode_count, transistor_count, has_feedback_loop, has_power_connection, lib_id, component_type. |
| H-04 | HIGH | `" teensy"` typo (lowercase with space) | **FIXED** | 46-01 line 578: `"TEENSY"` -- uppercase, no leading space, consistent with all other MCU names in the list. |

---

## Outstanding Issues from Previous Review (Not in Fix Scope)

The following findings from the original review were NOT included in the fix scope but remain present. They are tracked here for execution-time awareness.

### Still Present (Original CRITICAL)

| ID | Severity | Finding | Status | Evidence |
|----|----------|---------|--------|----------|
| Orig C-1 | CRITICAL | Circular import between topology_graph.py and net_classifier.py | **FIXED** (independent of user's scope) | types.py module created. Both modules import from `kicad_agent.analysis.types`. Lines 330, 754 in 45-01. key_links in 45-02 confirm "no circular import." |
| Orig C-2 | CRITICAL | Schema type mismatch between overview and sub-plan | **FIXED** (by H-02 fix) | Overview now uses tuple[T, ...] matching sub-plans. |
| Orig C-3 | CRITICAL | Stub methods without explicit replacement instructions | **PARTIALLY FIXED** (by H-01 fix) | See H-01 above. Instructions added but bodies still empty. |

### Still Present (Original HIGH)

| ID | Severity | Finding | Status | Evidence |
|----|----------|---------|--------|----------|
| Orig H-2 | HIGH | SchematicIR claim without implementation | **NOT FIXED** | 45-01 must_haves line 27: "TopologyBuilder builds from SchematicGraph or SchematicIR interchangeably" still present. Lines 72, 306, 408 still reference SchematicIR. No `from_schematic_ir()` method planned. |
| Orig H-3 | HIGH | SignalIntegrity rule ordering -- CONTROL before power-by-topology | **NOT FIXED** | 45-02 lines 171-189: Clock (172) -> Digital control/CONTROL (176) -> Power by name (179) -> Ground by name (181) -> Power by topology (183). Power-by-topology is still AFTER CONTROL patterns, not before. |
| Orig H-4 | HIGH | Generic pin patterns "A", "B", "D" in _INPUT_PIN_PATTERNS | **NOT FIXED** | 45-01 line 629: `_INPUT_PIN_PATTERNS = ["IN", "INPUT", "IN+", "IN-", "A", "B", "D"]` -- single-letter patterns still present. |
| Orig H-5 | HIGH | Op-amp pin number error in test prose | **NOT FIXED** | 45-01 line 505: "pin 8 (OUT) classified as OUTPUT" -- NE5532 pin 8 is V+, not OUT. Mock data at line 534 correctly uses pin_number="1" for OUT, but prose still says pin 8. |

### Still Present (Original MEDIUM/LOW)

All 8 MEDIUM and 4 LOW findings from the original review remain present. These are execution-time tracked and do not block plan approval. Summary:

- M-1: Net resolution reimplemented (use trace_endpoint_to_net)
- M-2: No multi-sheet/hierarchical test
- M-3: No dead-end component type for stub detection
- M-4: Subcircuit clustering hop count not specified
- M-5: Subcircuit.features bare dict
- M-6: Feature keys not formally specified (NOW FIXED by H-03)
- M-7: max_paths=100 not in _trace_signal_paths signature
- M-8: _LIBID_TYPE_MAP prefix ordering not documented
- L-1: No RP2040 pin role rules
- L-2: No EQ subcircuit type rule
- L-3: to_jsonl uses str instead of Path
- L-4: to_numeric_vector field order not documented

---

## SLC Validation

- **TODO/FIXME without tickets:** None found
- **Workaround/hack/temporary:** None found
- **NotImplementedError/UnimplementedError:** None found
- **Placeholder returns (None/empty):** None found
- **Pass stubs:** Present in RED-phase code blocks with explicit replacement instructions. Acceptable for TDD plan structure -- executor must implement during GREEN phase.

**SLC Status:** PASS (with execution-time caveats)

---

## New Findings (Regressions)

No new issues introduced by the five fixes. The changes are narrowly scoped and correct:

1. C-01 fix (input/output net intersection): Correctly uses set intersection with topology boundary nets. `topology.input_nets` and `topology.output_nets` are `tuple[str, ...]` -- the `&` operator works because these are intersected with `sc_net_names` (a `set[str]`). This is correct.

2. H-02 fix (tuple[T, ...]): All three dataclasses now consistently use frozen + tuple. No `list[` in overview. No regression.

3. H-03 fix (feature keys): The 16-key contract is complete and matches all keys consumed by classifier rules in 46-01 (has_sidechain, has_vca_input, has_multiple_inputs, has_crystal checked by _is_compressor, _is_vca, _is_mixer). No regression.

4. H-04 fix (TEENSY): Single string fix, no side effects.

5. H-01 fix (stub instructions): The `# Do NOT leave this as a stub.` pattern is applied consistently across all 6 stubs in 45-01 and 3 stubs in 46-01. Each references the specific task step where the implementation lives.

---

## Verdict: CONDITIONAL

### Rationale

The five targeted fixes are all correctly implemented with no regressions. However, 3 of the original HIGH findings remain unfixed and should be addressed before execution to avoid bugs during implementation:

**Must fix before execution (remaining from original review):**

1. **Orig H-2** (SchematicIR claim): The must_haves truth "TopologyBuilder builds from SchematicGraph or SchematicIR interchangeably" and 4 references to SchematicIR in 45-01 are misleading. No `from_schematic_ir()` method is planned. Either remove the claim or add the method. Recommend: change must_haves truth 7 to "TopologyBuilder builds from SchematicGraph" and update the 4 prose references.

2. **Orig H-3** (Rule ordering): `_is_power_by_topology` is still at position 5 in the SignalIntegrity rules, after the CONTROL pattern match. A net named "SCL" connecting only to power pins would be classified HIGH_SPEED instead of POWER_INTEGRITY. Move `_is_power_by_topology` before the CONTROL patterns line.

3. **Orig H-4** (Generic pin patterns): "A", "B", "D" in `_INPUT_PIN_PATTERNS` cause false positives via `startswith` -- "A" matches "ADJ", "B" matches "BIAS". Remove these single-letter patterns. The IC-specific `_IC_PIN_RULES` already handles analog switch pins correctly.

**Can fix during execution (tracked, not blocking):**

4. **Orig H-5** (Pin number prose): Test behavior text says "pin 8 (OUT)" but should say "pin 1 (OUT)". Mock data is correct. Cosmetically confusing during TDD execution but functionally harmless.

---

## Council Consensus

**Wave Alpha (Core):**
- Rick Sanchez (Code): CONDITIONAL -- fix Orig H-2, H-3, H-4
- Slick Rick (SLC): PASS -- no SLC violations
- Evil Morty (Synthesis): CONDITIONAL

**Wave Beta (Wisdom):**
- Rick Prime (Design): CONDITIONAL -- Orig H-3 rule ordering is a correctness issue
- Rickfucius (Historian): PASS -- fixes follow established patterns, no regressions

**Wave Gamma (Domain):**
- KiCad Rick (PCB/EDA): CONDITIONAL -- Orig H-4 false positives on generic pin names

**Final: Evil Morty -- CONDITIONAL**

---

## Execution Readiness

**Ready to execute after fixing:**
1. Remove SchematicIR claim from 45-01 must_haves truth 7 and prose (Orig H-2)
2. Reorder _SIGNAL_INTEGRITY_RULES: move _is_power_by_topology before CONTROL patterns (Orig H-3)
3. Remove "A", "B", "D" from _INPUT_PIN_PATTERNS (Orig H-4)

**Optional during execution:**
4. Fix "pin 8 (OUT)" to "pin 1 (OUT)" in test behavior text (Orig H-5)
5. All MEDIUM/LOW findings tracked from original review

---

**Review Completed:** 2026-05-31
**Review Type:** Re-Review Wave 1 (fix verification + regression check)
**Previous Review:** 45-COUNCIL-PLAN-REVIEW.md
