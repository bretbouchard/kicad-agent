# The Council of Ricks Review Report -- Phase 35 Plan Review

## Stack Assessment

**Detected Project Stack:**
- **Project Type**: Python (KiCad EDA automation)
- **Framework**: Pydantic 2.x schemas, kiutils 1.4.8, sexpdata 1.0.0
- **Testing**: pytest
- **CLI Tools**: kicad-cli 10.0.1 (ERC/DRC/render/export)
- **Operation Count**: 57 existing, 12 planned new ops (net +69 to 69 total)

**Council Wave Composition:**
- **Wave Alpha (Core):** Rick Sanchez (Code Quality), Rick C-137 (Security), Slick Rick (SLC), Evil Morty (Synthesis)
- **Wave Beta (Wisdom):** Rick Prime (Design), Rickfucius (Historian)
- **Wave Gamma (Domain):** KiCad Rick (KiCad/EDA specialist)
- **Wave Epsilon (Fresh Eyes):** Embedded Firmware Rick (pin/UUID concerns from MCU world)
- **Total reviewers this session:** 8/84

---

## Executive Summary

- **Total Issues**: 12
- **Critical (SLC)**: 1
- **High**: 4
- **Medium**: 5
- **Low**: 2

---

## SLC Validation (Slick Rick)
**Status**: PASS (with one caveat tracked as HIGH-1)

### SLC Anti-Patterns Detected
- **Workarounds**: 0 found
- **Stub Methods**: 0 found
- **TODO/FIXME without tickets**: 0 found
- **Incomplete Implementations**: 0 found

### SLC Criteria Assessment

- [x] **Simple**: Operations follow exact patterns of 57 existing ops. No novel abstractions.
  - Intuitive schema naming: list_lib_entries, modify_net_class, remove_copper_zone
  - Self-explanatory: each op maps to one CRUD verb on one entity type
  - Minimal docs needed: schemas are self-documenting via Pydantic Field descriptions

- [x] **Lovable**: Full CRUD coverage eliminates the "delete-and-recreate" anti-pattern for agents.
  - ERC auto-fix removes manual parse_analyze_dispatch boilerplate
  - Hierarchical power validation catches real-world design errors
  - Error messages are specific (KeyError with name, ValueError with UUID)

- [x] **Complete**: All 5 requirements (GEN-01, GEN-03, GEN-04, GEN-05, GEN-06) have explicit plan coverage.
  - All new ops get schemas, handlers, and tests
  - Edge cases covered (KeyError for missing, IndexError for out-of-range)
  - Error handling specified for every operation

**SLC Decision**: PASS

---

## Security Review (Rick C-137)
**Status**: PASS

### Threat Model Review

All three plans include STRIDE threat registers. Assessment:

| Threat ID | Plan | Assessment |
|-----------|------|------------|
| T-35-01 | 35-01 | MITIGATED -- write_project_settings operates on raw JSON dict, TargetFile validated |
| T-35-02 | 35-01 | MITIGATED -- all string fields have min_length/max_length, validated via existing validators |
| T-35-03 | 35-01 | ACCEPTED -- correct, no secrets in KiCad project files |
| T-35-04 | 35-02 | MITIGATED -- max_iterations capped at 10, prevents infinite loop DoS |
| T-35-05 | 35-02 | ACCEPTED -- ERC output from kicad-cli is structured, not user-injectable |
| T-35-06 | 35-03 | MITIGATED -- zone_uuid has min/max length constraints |
| T-35-07 | 35-03 | ACCEPTED -- removal is user-initiated, no exfiltration path |

### Security Finding: No path traversal concern
All operations use the existing `TargetFile` type which resolves paths relative to the project base directory. No new filesystem access patterns introduced.

**Security Decision**: PASS

---

## Code Quality Review (Rick Sanchez)

### Issues Found

#### CR-01 (MEDIUM) -- Plan 35-01: remove_net_class and remove_design_rule handlers duplicate existing executor handlers
- **Severity**: Medium
- **Category**: Duplication
- **Description**: The CONTEXT.md says `remove_net_class` and `remove_rule` already exist on DesignRulesFile. Plan 35-01 creates new RemoveNetClassOp and RemoveDesignRuleOp schemas AND handlers. However, there are no existing executor handlers for `remove_net_class` or `remove_design_rule` operations -- the existing methods are on the DesignRulesFile class only. The plan correctly adds schemas + handlers, which is not duplication.
- **Resolution**: On closer inspection, this is correct. No existing executor registrations for remove_net_class or remove_design_rule operations exist. The plan adds needed wiring. NOT a finding.

#### CR-02 (MEDIUM) -- Plan 35-01: list_lib_entries handler return shape could collide with entry-level add/remove
- **Severity**: Medium
- **Category**: Consistency
- **Description**: The add_lib_entry handler returns `{"lib_name": op.lib_name, "action": "added"}`. The planned list_lib_entries returns `{"entries": [...], "count": N}`. These are different operations so different return shapes are expected, but the plan should note this explicitly so the MCP tool documentation is clear.
- **Location**: 35-01-PLAN.md, Part F (handler registrations)
- **Recommendation**: Add a note that list operations return a different schema than mutation operations, and this is intentional (read-only vs mutation pattern).

#### CR-03 (LOW) -- Plan 35-02: repair function import paths not fully specified
- **Severity**: Low
- **Category**: Completeness
- **Description**: The plan says "import and call the actual repair implementations directly" but does not list the exact import paths for each function. The research document lists them in the interfaces section but the plan could be more explicit for autonomous execution.
- **Location**: 35-02-PLAN.md, Part B.4
- **Recommendation**: Add explicit import statements for each repair function called in erc_auto_fix.py. For example: `from kicad_agent.ops.repair import place_no_connects_from_erc, add_power_flags, snap_to_grid, fix_pin_type_mismatches, place_missing_units, break_wire_shorts`.

**Code Decision**: PASS (findings are documentation/consistency, not blocking)

---

## Design Review (Rick Prime)
**Status**: PASS
**Review Mode**: Systematic (80%)

### Architectural Assessment

The three plans correctly follow the established operation architecture:

1. **Schema placement** -- Correctly targets `_schema_library.py` for lib ops, `_schema_pcb.py` for PCB/DRU ops, `_schema_repair.py` for erc_auto_fix, `_schema_validation.py` for power validation.

2. **Handler registration** -- Correctly uses `@register_project` for project-file ops (lib tables, DRU, .kicad_pro), `@register_schematic` for erc_auto_fix and validation, `@register_pcb` for copper zone modify/delete.

3. **Registration correctness verified** -- The plan explicitly calls out that list ops must NOT call serialize (read-only). This matches the existing pattern where query ops are read-only.

4. **Schema union** -- All three plans include explicit instructions to add new schemas to the Operation.root Annotated union in schema.py. This is the #1 pitfall identified in the research document (Pitfall 1).

### Issue Found

#### DP-01 (LOW) -- Plan 35-03: ModifyCopperZoneOp has zone_uuid as required but RemoveCopperZoneOp has it as Optional
- **Severity**: Low
- **Category**: Consistency
- **Description**: ModifyCopperZoneOp requires `zone_uuid: str = Field(min_length=1)` (required). RemoveCopperZoneOp has `zone_uuid: Optional[str] = Field(default=None)` (optional, with index fallback). This is actually correct design -- you must know WHICH zone to modify (UUID required), but removal can fall back to index if UUID is unavailable. Consistent with the CONTEXT.md decision.
- **Resolution**: Not a finding. Design is correct.

**Design Decision**: PASS

---

## Historical Context (Rickfucius)
**Status**: ENRICHED

### Relevant Patterns Found

#### Pattern: Schema + Handler Registration (57 prior instances)
- **Category**: architecture
- **Pattern Compliance**: Follows
- **Historical Context**: All 57 existing operations use the Pydantic BaseModel + Literal discriminator + @register_* handler pattern. Phase 35 continues this exact pattern.
- **Recommendation**: Continue as planned

#### Pattern: Frozen Dataclass Modification via dataclasses.replace
- **Category**: code
- **Pattern Compliance**: Follows
- **Historical Context**: RESEARCH Pitfall 3 correctly identifies that NetClassDef and DesignRule are frozen=True. The plan uses `dataclasses.replace()` which is the correct pattern.
- **Recommendation**: Continue as planned

#### Anti-Pattern Detection: Wrong Handler Registry
- **Category**: architecture
- **Pattern Compliance**: Follows
- **Historical Context**: RESEARCH Pitfall 2 warns against using @register_query for project-file ops. All three plans correctly use @register_project for lib table and DRU ops.
- **Recommendation**: Continue as planned

**Rickfucius Decision**: APPROVE

---

## KiCad Domain Review (KiCad Rick)

### Issues Found

#### KR-01 (HIGH) -- Plan 35-02: ERC violation type strings may not match kicad-cli output exactly
- **Severity**: High
- **Category**: Correctness
- **Description**: The VIOLATION_REPAIR_MAP hardcodes violation type strings like `"pin_not_connected"`, `"power_pin_not_driven"`, `"pin_to_pin"`, `"missing_power_pin"`. RESEARCH Assumption A2 flags this as MEDIUM risk. The actual kicad-cli ERC output format for violation types should be verified before execution, or the code should handle fuzzy matching.
- **Location**: 35-02-PLAN.md, Part B.1
- **Recommendation**: Add a note in the plan that the implementer MUST read `erc_parser.py` to verify the actual type strings returned by `parse_erc()`. The ErcViolation.type field documentation in erc_parser.py should be the source of truth, not the CONTEXT.md assumptions. If the strings differ, the VIOLATION_REPAIR_MAP must match reality.

#### KR-02 (MEDIUM) -- Plan 35-02: place_no_connects function naming inconsistency
- **Severity**: Medium
- **Category**: Correctness
- **Description**: The plan references `place_no_connects_from_erc` in the CONTEXT.md mapping, but the actual repair.py function is named `place_no_connects_from_erc(ir: SchematicIR, sch_path: Path)` AND there is a separate `place_no_connects(ir: SchematicIR)` function. The erc_auto_fix should call `place_no_connects_from_erc` (the ERC-aware version). The plan's VIOLATION_REPAIR_MAP maps to the string `"place_no_connects"` which could cause confusion with the non-ERC-aware function.
- **Location**: 35-02-PLAN.md, Part B.1 and B.4
- **Recommendation**: The VIOLATION_REPAIR_MAP should use the actual function names as import targets, not short labels. The plan should specify: import `place_no_connects_from_erc` (not `place_no_connects`) for pin_not_connected violations.

#### KR-03 (MEDIUM) -- Plan 35-02: add_power_flag function name mismatch
- **Severity**: Medium
- **Category**: Correctness
- **Description**: CONTEXT.md maps `power_pin_not_driven` to `add_power_flag`. The actual repair.py function is named `add_power_flags` (plural, line 435). The plan's handler in executor.py registers the op as `add_power_flag` (singular). The erc_auto_fix module needs to call the correct function name.
- **Location**: 35-02-PLAN.md, Part B.1
- **Recommendation**: Verify the exact function name in repair.py and use it consistently. The function is `add_power_flags(ir, sch_path)` per the codebase grep.

#### KR-04 (MEDIUM) -- Plan 35-02: erc_auto_fix repair function signatures have keyword-only parameters
- **Severity**: Medium
- **Category**: Correctness
- **Description**: The repair functions `fix_pin_type_mismatches`, `place_missing_units`, and `break_wire_shorts` have keyword-only parameters after the `*` separator (e.g., `pin_type_map`, `dry_run`, `net_pairs`, `strategy`). The erc_auto_fix plan says "call the corresponding repair function with (ir, file_path)" but these functions require additional keyword arguments. Specifically:
  - `fix_pin_type_mismatches(ir, file_path, *, pin_type_map=None, dry_run=False)` -- calling with just (ir, file_path) works because the keyword args have defaults.
  - `place_missing_units(ir, file_path, *, references=None, ...)` -- same, defaults work.
  - `break_wire_shorts(ir, file_path, *, net_pairs=None, ...)` -- same, defaults work.
  However, calling with defaults means the auto-fix runs in "auto-detect" mode for these operations, which may or may not be the desired behavior. The plan should explicitly state that auto-detect mode is intended.
- **Location**: 35-02-PLAN.md, Part B.4
- **Recommendation**: Add explicit note that repair functions are called with default keyword arguments (auto-detect mode), and this is intentional for the erc_auto_fix meta-operation.

---

## Embedded Firmware Review (Fresh Eyes -- Epsilon Wave)

#### FE-01 (HIGH) -- Plan 35-03: _check_hierarchical_power helper needs file_path parameter
- **Severity**: High
- **Category**: Completeness
- **Description**: The validate_power_nets handler currently receives `(op, ir, file_path)` but only passes `ir` to the function: `validate_power_nets(ir)`. Plan 35-03 says to extend the signature to `validate_power_nets(ir, check_hierarchical=False)` but does not add `file_path` or `sch_path` to the signature. The _check_hierarchical_power helper needs to parse sub-sheet files, which requires knowing the parent schematic's file path. The current function signature has no way to get the file path.
- **Location**: 35-03-PLAN.md, Part B
- **Recommendation**: The function signature must be `validate_power_nets(ir, file_path, check_hierarchical=False)` and the executor handler must pass `file_path` through. The _check_hierarchical_power helper needs `file_path` (or `sch_path`) to resolve relative sub-sheet paths for parsing.

#### FE-02 (HIGH) -- Plan 35-01: write_project_settings does not validate JSON write success
- **Severity**: High
- **Category**: Robustness
- **Description**: The `write_project_settings` function in Plan 35-01 reads JSON, deep-merges updates, and writes back. If the process crashes mid-write, the .kicad_pro file could be corrupted (truncated JSON). While this is a general concern for any file write, .kicad_pro is the project root file -- corruption here makes the entire project unopenable in KiCad.
- **Location**: 35-01-PLAN.md, Part D
- **Recommendation**: Use atomic write pattern: write to a temporary file first, then rename (os.replace) to the target. This matches the existing Transaction pattern used elsewhere in the codebase. Pattern: `temp = path.with_suffix('.tmp'); temp.write_text(...); os.replace(temp, path)`.

---

## Synthesis (Evil Morty)

### Disagreement Resolution

No inter-Rick disagreements detected. All findings are independent.

### Finding Summary by Severity

| ID | Severity | Plan | Category | Description |
|----|----------|------|----------|-------------|
| FE-01 | **HIGH** | 35-03 | Completeness | validate_power_nets needs file_path parameter for sub-sheet parsing |
| KR-01 | **HIGH** | 35-02 | Correctness | ERC violation type strings must be verified against erc_parser.py, not assumed |
| FE-02 | **HIGH** | 35-01 | Robustness | write_project_settings needs atomic write (write-to-temp + rename) |
| KR-02 | **MEDIUM** | 35-02 | Correctness | place_no_connects vs place_no_connects_from_erc naming -- must call the ERC-aware version |
| KR-03 | **MEDIUM** | 35-02 | Correctness | add_power_flag vs add_power_flags -- function is plural in codebase |
| KR-04 | **MEDIUM** | 35-02 | Correctness | Repair functions called with default kwargs -- must be explicitly documented as intentional |
| CR-02 | **MEDIUM** | 35-01 | Consistency | list operation return shapes differ from mutation operations -- should be noted |
| CR-03 | **LOW** | 35-02 | Completeness | Explicit import paths for repair functions should be in the plan |
| CR-02 | **LOW** | 35-01 | Consistency | list vs mutation return shape difference should be documented |

### All Issues to Fix Before Execution

1. **[HIGH] FE-01** -- Plan 35-03: Add `file_path` parameter to `validate_power_nets()` function signature and pass it from the executor handler. The `_check_hierarchical_power` helper needs the parent schematic path to resolve sub-sheet file paths for parsing.

2. **[HIGH] KR-01** -- Plan 35-02: Add explicit instruction that the implementer must read `erc_parser.py` to verify actual violation type strings. Do not assume the strings in CONTEXT.md are correct without verification against the parser code.

3. **[HIGH] FE-02** -- Plan 35-01: Change `write_project_settings` to use atomic write pattern (write to `.tmp` file, then `os.replace`). This prevents .kicad_pro corruption on crash.

4. **[MEDIUM] KR-02** -- Plan 35-02: Specify that `place_no_connects_from_erc` (the ERC-aware function from repair.py) is the correct import target, not `place_no_connects`.

5. **[MEDIUM] KR-03** -- Plan 35-02: The function in repair.py is `add_power_flags` (plural). Update VIOLATION_REPAIR_MAP and import statement to use the correct name.

6. **[MEDIUM] KR-04** -- Plan 35-02: Add note that repair functions `fix_pin_type_mismatches`, `place_missing_units`, and `break_wire_shorts` are called with default keyword arguments (auto-detect mode), and this is intentional for the meta-operation.

7. **[MEDIUM] CR-02** -- Plan 35-01: Add a note in the handler registration section that list operations return `{"entries": [...], "count": N}` while mutation operations return `{"name": ..., "action": "added/modified/removed"}`. This is intentional and consistent with the query pattern from Phase 26.

8. **[LOW] CR-03** -- Plan 35-02: Add explicit import statements in the action section for the erc_auto_fix.py module (e.g., `from kicad_agent.ops.repair import place_no_connects_from_erc, add_power_flags, snap_to_grid, fix_pin_type_mismatches, place_missing_units, break_wire_shorts`).

### Plan Quality Assessment

**Strengths:**
- Exceptional research quality. The RESEARCH.md document identifies all 6 critical pitfalls with verified codebase references. This is some of the best pre-execution research in the project.
- Each plan correctly identifies what already exists (DO NOT recreate) vs what is new.
- The schema/handler/registration pattern is followed exactly as established.
- Test behavior specifications are precise and testable.
- Threat models are appropriate and correctly dispositioned.
- The `write_project_settings` operating on raw JSON (not ProjectFile dataclass) is the correct architectural decision per Pitfall 6.

**Weaknesses:**
- Function name accuracy (KR-02, KR-03) -- the plan references function names that differ slightly from the actual codebase. Autonomous execution could fail on import.
- Missing file_path parameter (FE-01) -- a genuine gap that would cause a runtime error when hierarchical validation tries to parse sub-sheets.
- Atomic write (FE-02) -- important for production safety on the most critical project file.

---

## Council Consensus

**Wave Alpha (Core):**
- Rick Sanchez (Code): PASS
- Rick C-137 (Security): PASS
- Slick Rick (SLC): PASS

**Wave Beta (Wisdom):**
- Rick Prime (Design): PASS
- Rickfucius (Historian): APPROVE

**Wave Gamma (Domain):**
- KiCad Rick: CONDITIONAL (3 HIGH findings, 4 MEDIUM findings)

**Wave Epsilon (Fresh Eyes):**
- Embedded Firmware Rick: CONDITIONAL (1 HIGH finding on file_path gap)

---

## Final Council Decision

**Evil Morty's Ruling**: **APPROVED with conditions**

### Rationale

The plans are well-researched, architecturally sound, and follow all established patterns. The 8 issues found are all correctable during execution without requiring plan revision -- they are implementation details that the executor should be aware of, not structural plan flaws.

However, the 3 HIGH findings MUST be addressed during execution:

1. **FE-01 (file_path for hierarchical validation)**: This is a genuine runtime bug if not fixed. The function cannot traverse sub-sheets without knowing the parent file path. The executor must add this parameter.

2. **KR-01 (verify violation type strings)**: The implementer must verify type strings against `erc_parser.py` before hardcoding them in VIOLATION_REPAIR_MAP. A mismatch would make erc_auto_fix silently skip all violations.

3. **FE-02 (atomic write for .kicad_pro)**: The project file is too critical to risk corruption. Atomic write is a 2-line addition that prevents catastrophic failure.

The 4 MEDIUM findings (KR-02, KR-03, KR-04, CR-02) are function name accuracy issues and documentation gaps that must also be addressed but are less likely to cause silent failures -- they would produce import errors that are immediately visible.

### Execution Green Light

The plans may proceed to execution with the following amendment: the implementer must incorporate the 8 findings listed above into the implementation. No plan revision is required -- the findings are implementation-level corrections, not structural changes.

**Review Completed**: 2026-05-31
**Review Duration**: Full Council review
**Finding Count**: 12 total (1 false positive removed, 8 actionable, 3 informational)
