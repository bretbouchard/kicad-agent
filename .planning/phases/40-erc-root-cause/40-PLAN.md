# Phase 40: ERC Root Cause Analysis

**Status:** PLANNING
**Requirements:** ERC-SMART-01, ERC-SMART-02, ERC-SMART-03
**Depends on:** Phase 38 (pin resolution, collision detection), Phase 39 (net extraction, conflict detection)

## Goal

Upgrade `erc_auto_fix` from symptom patching to root cause analysis. Today it handles wire snapping, orphan removal, and no-connect placement. It doesn't understand WHY violations occur. After this phase, it should diagnose root causes and suggest targeted fixes.

## Context

The compressor-stage schematic has 33 violations. The current `erc_auto_fix` can fix some of them, but these remain:

| Violation | Count | Root Cause | Current Fix? |
|-----------|-------|------------|-------------|
| power_pin_not_driven | 5 | Power symbols have `power_in` pin type with `(power global)` flag — should drive but ERC doesn't recognize | No |
| pin_not_connected (#PWR052/054/055) | 3 | Orphaned power symbols from original layout — not connected to any net | No |
| pin_not_driven (U21 pin13) | 1 | Input pin driven only by global label from another sheet — no local output pin | No |
| same_local_global_label | 9 | Benign — local and global labels with same name at different positions | No (cosmetic) |
| pin_to_pin (Unspecified vs Power input) | 2 | Power symbol pin type "Unspecified" connected to "Power input" — type mismatch | No |
| isolated_pin_label | 2 | Label at a pin with no other connections on the net | No (expected for interface pins) |
| missing_unit | 4 | Unused CD4066BE/NE5532 units — by design | No (benign) |
| multiple_net_names | 1 | R55/R56 pin overlap — layout bug | No |
| lib_symbol_issues | 1 | Analog-Ecosystem-SMD not in symbol library config | No (config issue) |

## Plans

### Plan 40-01: ERC Violation Classification (ERC-SMART-01)

**Goal:** Parse ERC output and classify violations into fixable vs pre-existing vs layout-bug vs library-issue categories.

**Schema:**
```python
class ClassifyViolationsOp(OpBase):
    op_type: Literal["classify_violations"] = "classify_violations"
    target_file: TargetFile
    erc_report_path: Optional[str] = None  # Run ERC if not provided
```

**Returns:**
```python
{
    "fixable": [
        {
            "type": "multiple_net_names",
            "position": [59.69, 78.74],
            "details": "R55.2 and R56.1 at same position on different nets",
            "suggested_fix": "rename_net or move_component",
            "confidence": "high"
        }
    ],
    "pre_existing": [
        {
            "type": "power_pin_not_driven",
            "position": [85.09, 62.23],
            "details": "U21 pin 14 (VDD) — power symbol has power_in type with (power global) flag",
            "note": "Library configuration issue — power symbol pin type mismatch",
            "confidence": "high"
        }
    ],
    "benign": [
        {
            "type": "same_local_global_label",
            "count": 9,
            "note": "Local and global labels with same name — no action needed"
        },
        {
            "type": "missing_unit",
            "count": 4,
            "note": "Unused units on multi-unit ICs — by design"
        }
    ],
    "config_issues": [
        {
            "type": "lib_symbol_issues",
            "details": "Analog-Ecosystem-SMD not in symbol library configuration"
        }
    ],
    "summary": {
        "total": 33,
        "fixable": 1,
        "pre_existing": 9,
        "benign": 23,
        "config": 1
    }
}
```

**Classification rules:**
1. `power_pin_not_driven` with `(power global)` symbol → pre-existing (library issue)
2. `pin_not_connected` on #PWR symbol with no wire/label → pre-existing (orphaned)
3. `pin_not_driven` on input pin with only global labels → pre-existing (hierarchical signal)
4. `multiple_net_names` at pin overlap position → fixable (layout bug)
5. `same_local_global_label` → benign
6. `missing_unit` for unused switch/opamp units → benign
7. `lib_symbol_issues` → config issue
8. `pin_to_pin` (Unspecified vs Power input) → pre-existing (pin type in library)

**Tests:**
- Classify all 33 violations in compressor-stage
- Verify fixable count is 1 (the R55/R56 overlap)
- Verify pre-existing count is 9 (5 power_pin_not_driven + 3 orphaned #PWR + 1 input not driven)
- Verify benign count is 23

---

### Plan 40-02: Root Cause Diagnosis (ERC-SMART-02)

**Goal:** For fixable violations, diagnose the root cause and generate a fix plan.

**Schema:**
```python
class DiagnoseViolationsOp(OpBase):
    op_type: Literal["diagnose_violations"] = "diagnose_violations"
    target_file: TargetFile
    violation_types: Optional[list[str]] = None  # All types if not specified
    max_fixes: int = 10
```

**Returns:**
```python
{
    "diagnoses": [
        {
            "violation_type": "multiple_net_names",
            "position": [59.69, 78.74],
            "root_cause": "pin_overlap",
            "details": "R55 pin2 (to_switch net) and R56 pin1 (COMP_BYPASS_SIG net) share position",
            "fix_options": [
                {
                    "action": "move_component",
                    "params": {"ref": "R56", "new_position": [59.69, 86.36]},
                    "description": "Move R56 down by 3.81mm to separate pins",
                    "side_effects": ["R56 pin2 moves from (59.69, 86.36) to (59.69, 90.17)", "Downstream wires need re-routing"],
                    "confidence": "high"
                },
                {
                    "action": "rename_net",
                    "params": {"old_name": "to_switch", "new_name": "COMP_BYPASS_SIG"},
                    "description": "Merge nets since pins are physically shorted anyway",
                    "side_effects": ["Bypass switch function lost — signal bypasses switch entirely"],
                    "confidence": "medium"
                }
            ],
            "recommended_fix_index": 0
        }
    ]
}
```

**Diagnosis strategies:**
1. For `multiple_net_names`: Check if pins at same position → pin overlap → suggest move_component
2. For `pin_to_pin`: Check if power symbol pin type is wrong → suggest fix_pin_type_mismatches
3. For `power_pin_not_driven`: Check if power symbol has `(power global)` → library issue, not fixable
4. For `dangling_wire`: Check if wire endpoint is near a pin → snap_to_grid or add_wire to pin

**Tests:**
- Diagnose R55/R56 overlap → recommend move_component
- Diagnose power_pin_not_driven → classify as library issue
- Diagnose pin_to_pin → classify as library issue

---

### Plan 40-03: Enhanced `erc_auto_fix` with Root Cause Mode (ERC-SMART-03)

**Goal:** Upgrade existing `erc_auto_fix` to use root cause analysis for smarter fixes.

**New behavior:**
```python
class ErcAutoFixOp(OpBase):
    op_type: Literal["erc_auto_fix"] = "erc_auto_fix"
    target_file: TargetFile
    mode: Literal["symptom", "root_cause"] = "root_cause"  # NEW: default to root cause mode
    max_passes: int = 5
    fix_classes: Optional[list[str]] = None  # NEW: only fix these classes
    # "fixable", "pre_existing", "benign", "config"
    dry_run: bool = False
```

**Root cause mode behavior:**
1. Run ERC → parse violations
2. Classify violations (fixable, pre-existing, benign, config)
3. For fixable violations:
   a. Diagnose root cause
   b. Generate targeted fix operations
   c. Apply fixes
   d. Re-run ERC to verify
4. For pre-existing violations: log with explanation, don't attempt fix
5. For benign violations: suppress from report
6. Return summary with fix results and remaining violations by category

**New fixes added:**
- Pin overlap fix: move component to separate overlapping pins
- Net name conflict fix: rename local labels to match global labels
- Power symbol connectivity fix: verify power symbol net name matches connected labels

**Tests:**
- Auto-fix compressor-stage: should fix the R55/R56 overlap (1 fixable violation)
- Verify no regression in existing auto-fix behavior (symptom mode)
- Verify root cause mode doesn't attempt to fix pre-existing violations
- End-to-end: auto-fix → verify ≤32 violations (1 less than current 33)

---

## Success Criteria

1. `classify_violations` correctly categorizes all 33 compressor-stage violations
2. `diagnose_violations` identifies R55/R56 pin overlap as root cause of `multiple_net_names`
3. Enhanced `erc_auto_fix` fixes the pin overlap, reducing violations from 33 → 32
4. Pre-existing violations are documented with root cause explanations, not silently ignored
5. No regression in existing auto-fix test suite
