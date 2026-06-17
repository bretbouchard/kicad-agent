---
phase: quick
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/kicad_agent/ops/pre_analysis.py
  - tests/test_pre_analysis.py
autonomous: true
requirements: [QUICK-LABEL-VALIDATION]
---

<objective>
Add a `validate_labels` pre-flight check to the PreAnalysisGate that prevents duplicate global labels from being created on the same net. Currently kicad-agent has no validation preventing operations (add_label, batch_connect, regenerate_wiring, place_net_labels) from creating conflicting global labels — ERC catches it after the damage is done. This check detects duplicates BEFORE any write operation, blocking at creation time instead of discovery time.

Purpose: Prevent a class of ERC errors (duplicate global labels on same net) at pre-flight time, saving the cost of a write + ERC cycle and catching the error before the file is mutated.

Output: New `_analyze_label_operation` method in PreAnalysisGate, wired into the dispatch for all label-creating op types. Returns a blocker when a duplicate global label would be created.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.claude/CLAUDE.md

@src/kicad_agent/ops/pre_analysis.py
@src/kicad_agent/ir/schematic_ir.py
@src/kicad_agent/ops/validation_gates.py

<interfaces>
<!-- Key types and contracts the executor needs. -->

From src/kicad_agent/ops/pre_analysis.py:

```python
class PreAnalysisGate:
    def analyze(self, op: Any, ir: Any, file_path: Path) -> PreAnalysisResult:
        # Routes to specific analyzers based on op_type
        # Currently handles: add_component, move_component, add_wire/connect_pins/batch_connect,
        #   add_power, remove_component
        # MISSING: add_label, place_net_labels, regenerate_wiring (in _MUTATION_OP_TYPES but no analyzer)

@dataclass(frozen=True)
class PreAnalysisFinding:
    severity: str   # "blocker" or "warning"
    category: str   # e.g., "duplicate_global_label"
    message: str
    details: dict[str, Any]

@dataclass
class PreAnalysisResult:
    blockers: list[PreAnalysisFinding]
    warnings: list[PreAnalysisFinding]
    suggestions: list[str]
    enriched_context: dict[str, Any]
    @property
    def blocked(self) -> bool: ...
```

From src/kicad_agent/ir/schematic_ir.py:

```python
class SchematicIR:
    def get_label_positions(self) -> list[dict[str, Any]]:
        """Returns list of {name, x, y, label_type} for all labels.
        label_type is "local", "global", or "hierarchical"."""

    def get_labels_by_name(self, name: str) -> list:
        """Find all local labels with matching text. NOTE: local only, not global."""
```

From kiutils Schematic object (accessed via ir.schematic):
```python
sch.globalLabels  # list[GlobalLabel] -- each has .text, .position.X, .position.Y
sch.labels        # list[LocalLabel]  -- each has .text, .position.X, .position.Y
sch.hierarchicalLabels  # list[HierarchicalLabel]
```

From src/kicad_agent/ops/_schema_wire.py:

```python
class AddLabelOp(BaseModel):
    op_type: Literal["add_label"] = "add_label"
    target_file: TargetFile
    name: str
    label_type: str  # "local", "global", "hierarchical"
    position: PositionSpec  # has .x, .y, .angle
    shape: str  # "input", "output", "bidirectional", etc.
```

From src/kicad_agent/ops/_schema_schematic_routing.py:

```python
class BatchConnectOp(BaseModel):
    op_type: Literal["batch_connect"] = "batch_connect"
    nets: list[NetDef]  # each has .name
    global_labels: list[GlobalLabelDef]  # each has .name, .position, .shape

class GlobalLabelDef(BaseModel):
    name: str
    position: PositionSpec
    shape: str = "bidirectional"
```

From src/kicad_agent/ops/handlers/schematic.py:
- `batch_connect` handler calls `ir.add_label(name=gl["name"], label_type="global", ...)` for each global label in the result
- `regenerate_wiring` handler similarly creates global labels from the wiring engine output
- `place_net_labels` handler creates local and global labels from net definitions
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Implement _analyze_label_operation with duplicate global label detection</name>
  <files>src/kicad_agent/ops/pre_analysis.py, tests/test_pre_analysis.py</files>
  <behavior>
    - Test: add_label with label_type="global" and a name that already exists as a global label in the schematic → result.blocked is True, blocker category is "duplicate_global_label"
    - Test: add_label with label_type="global" and a name that does NOT exist as a global label → result.blocked is False (no blocker)
    - Test: add_label with label_type="local" → no duplicate check (local labels can repeat), result.blocked is False
    - Test: add_label with label_type="hierarchical" → no duplicate check, result.blocked is False
    - Test: add_label with label_type="global" where a global label with same name exists at a DIFFERENT position → result.blocked is True (global label names must be unique regardless of position — two global labels with the same name are by definition the same net, so a second one is always a duplicate/error)
    - Test: batch_connect with global_labels containing a name that already exists in the schematic → result.blocked is True
    - Test: batch_connect with global_labels containing only new names → result.blocked is False
    - Test: regenerate_wiring with no existing global labels → result.blocked is False (regenerate_wiring replaces all wiring, so existing labels are stripped first — no duplicates possible from the operation alone, but if the operation's global_labels field specifies names already in the schematic from other sources, still warn)
    - Test: place_net_labels with no global labels specified → result.blocked is False
    - Test: add_label with label_type="global" on an empty schematic (no existing labels) → result.blocked is False
    - Test: batch_connect with duplicate global label names WITHIN the operation itself (same name in global_labels list twice) → result.blocked is True with category "duplicate_global_label" and details noting the intra-operation duplicate
  </behavior>
  <action>
    1. Add `_analyze_label_operation(self, op, ir, result)` method to PreAnalysisGate class.

    2. The method extracts existing global label names from the IR via `ir.get_label_positions()` filtered to `label_type == "global"`, building a set of existing names.

    3. For `add_label` ops:
       - Skip if `op.label_type != "global"` (local and hierarchical labels can legitimately repeat).
       - Check if `op.name` is in the existing global label names set.
       - If yes: append a blocker PreAnalysisFinding with category="duplicate_global_label", severity="blocker", message like f"Global label '{op.name}' already exists in schematic — duplicate global labels on the same net are not allowed", details with existing positions.

    4. For `batch_connect` ops:
       - Extract global label names from `op.global_labels` list (each has `.name`).
       - Check for duplicates within the operation itself (intra-operation duplicates).
       - Check each name against existing global label names in the schematic.
       - Block on any duplicate.

    5. For `regenerate_wiring` ops:
       - Extract global label names from `op.global_labels` list.
       - Check for intra-operation duplicates.
       - Check against existing labels (regenerate strips its own labels, but a name conflict with labels that survive regeneration is still a problem — be conservative and block).

    6. For `place_net_labels` ops:
       - This op creates local labels from net names. Check if it also creates global labels (inspect op schema for global label fields).
       - If global labels are specified, apply the same duplicate check.

    7. Wire the new analyzer into the dispatch in `PreAnalysisGate.analyze()`:
       Add `elif op_type in ("add_label", "batch_connect", "regenerate_wiring", "place_net_labels"): self._analyze_label_operation(op, ir, result)` BEFORE the existing `elif op_type in ("add_wire", "connect_pins", "batch_connect")` branch, or restructure the dispatch so batch_connect hits both the wiring analyzer and the label analyzer. The cleanest approach: add a separate dispatch line after the existing if/elif chain (not inside it) so label analysis runs IN ADDITION TO wiring analysis for batch_connect:

       ```python
       # After the existing if/elif chain:
       if op_type in ("add_label", "batch_connect", "regenerate_wiring", "place_net_labels"):
           self._analyze_label_operation(op, ir, result)
       ```

    8. Add a helper `_get_existing_global_label_names(ir) -> dict[str, list[tuple[float, float]]]` that returns a dict mapping label name to list of positions. This allows the blocker details to include WHERE the existing labels are, not just that they exist.

    9. Do NOT use regex or fuzzy matching — exact string match on label names. KiCad global labels are case-sensitive and exact.
  </action>
  <verify>
    <automated>python -m pytest tests/test_pre_analysis.py -x -q 2>&1 | tail -20</automated>
  </verify>
  <done>
    - _analyze_label_operation method exists and is wired into PreAnalysisGate.analyze() dispatch
    - Duplicate global label detection blocks add_label operations with label_type="global" when the name already exists
    - batch_connect, regenerate_wiring, and place_net_labels also checked for global label duplicates
    - Local and hierarchical labels are NOT checked for duplicates (legitimate to repeat)
    - All 11+ test cases pass
    - No false positives on existing passing tests (all pre_analysis tests still pass)
  </done>
</task>

<task type="auto">
  <name>Task 2: Integration test — verify executor blocks on duplicate global labels end-to-end</name>
  <files>tests/test_pre_analysis.py</files>
  <action>
    Add an integration test class `TestDuplicateLabelExecutorIntegration` that:

    1. Creates a real .kicad_sch fixture file with a global label named "SDA" using kiutils Schematic API.
    2. Attempts to execute an add_label operation for a second "SDA" global label via OperationExecutor.execute().
    3. Verifies the result has success=False, the error message mentions "Pre-analysis blocked" and "duplicate_global_label".
    4. Verifies the file was NOT modified (Transaction rollback / pre-gate block prevented write).

    5. Second test: execute add_label for a NEW global label name (e.g., "SCL") and verify success=True.

    Use the existing test helper pattern from test_pre_analysis.py:
    - Build Schematic with kiutils, save to tempfile
    - Parse with parse_schematic(), create SchematicIR
    - Create OperationExecutor with the temp dir
    - Build AddLabelOp with target_file pointing to the temp schematic
    - Call executor.execute(op)
    - Assert on the result dict

    This test proves the pre-flight check works in the real execution path, not just in isolation.
  </action>
  <verify>
    <automated>python -m pytest tests/test_pre_analysis.py::TestDuplicateLabelExecutorIntegration -xvs 2>&1 | tail -30</automated>
  </verify>
  <done>
    - Integration test proves executor blocks duplicate global labels before write
    - Integration test proves non-duplicate labels still succeed
    - File integrity verified (no mutation on blocked operations)
  </done>
</task>

</tasks>

<verification>
- `python -m pytest tests/test_pre_analysis.py -x -q` — all pre-analysis tests pass (existing + new)
- No regression in executor tests: `python -m pytest tests/ -k "executor or pre_analysis" -x -q`
- The check fires at pre-flight time (before Transaction/write), not post-write
</verification>

<success_criteria>
- PreAnalysisGate.analyze() returns a blocker with category "duplicate_global_label" when add_label, batch_connect, regenerate_wiring, or place_net_labels would create a global label whose name already exists in the schematic
- The check runs BEFORE the file is written (verified by integration test showing no file mutation on blocked ops)
- Local and hierarchical labels are NOT subject to duplicate blocking
- All existing pre_analysis tests continue to pass
- 12+ new test cases pass (11 from Task 1 TDD + 2 from Task 2 integration)
</success_criteria>

<output>
After completion, create `.planning/quick/260616-wqd-build-a-validate-labels-pre-flight-check/260616-wqd-SUMMARY.md`
</output>
