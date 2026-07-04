---
phase: 111-convention-library
plan: 01
subsystem: conventions
tags: [conventions, infra, layout-view, yaml-loader, serializers]
requires:
  - "Phase 48 DesignRule ABC + RuleConfigLoader (template)"
  - "Phase 100 CR-01 frozen dataclass pattern"
  - "Phase 101 SchematicRawWriter (apply_mutation contract)"
provides:
  - "Convention ABC (class-level rule_id/severity) + Violation model + LayoutView frozen dataclass"
  - "ConventionConfigLoader (project-local .kicad-agent/conventions.yaml, mirrors Phase 48)"
  - "Dual JSON + markdown serializers (D-04)"
affects:
  - "src/kicad_agent/conventions/ (new package)"
tech-stack:
  added: []
  patterns:
    - "Phase 48 DesignRule ABC + RuleConfigLoader mirror (class-level attrs, yaml.safe_load, threshold bounds)"
    - "Phase 100 CR-01 frozen dataclass + dataclasses.replace for apply() returns"
    - "P1-R2-1 (Council Round 2): LayoutView.to_mutations emits new_x/new_y keys (NOT x/y)"
key-files:
  created:
    - src/kicad_agent/conventions/__init__.py
    - src/kicad_agent/conventions/base.py
    - src/kicad_agent/conventions/layout_view.py
    - src/kicad_agent/conventions/loader.py
    - src/kicad_agent/conventions/serializers.py
    - tests/test_convention_abc.py
    - tests/test_convention_loader.py
    - tests/test_convention_serializers.py
    - tests/fixtures/conventions/sample_conventions.yaml
decisions:
  - "Convention ABC uses class-level rule_id + severity (not instance attrs) per P0-3"
  - "rule_id regex matches Phase 48 exactly: ^[A-Z][A-Z0-9_]*\\d{2}$ — two-digit suffix mandatory"
  - "LayoutView.to_mutations emits new_x/new_y keys per P1-R2-1 (writer ignores x/y and angle)"
  - "discover() stops at first .git ancestor or fs root per P2-3"
  - "Markdown severity grouping: Errors first (most actionable), then Warnings, then Info"
metrics:
  duration: ~12 minutes
  completed: 2026-07-04
---

# Phase 111 Plan 01: Convention Infrastructure Summary

Convention ABC + Violation model + LayoutView frozen dataclass + project-local YAML loader + dual JSON/markdown serializers — infrastructure layer that ships independent of Phase 108 violation data (per Plan 02 D-01).

## What Was Built

### Convention ABC (`src/kicad_agent/conventions/base.py`)
- ABC with `check(layout, config=None) -> list[Violation]` and `apply(layout) -> LayoutView` (D-03)
- `rule_id` and `severity` declared as **class-level attributes** mirroring Phase 48 `DesignRule.name` / `default_severity` (P0-3 fix)
- `Severity = Literal["error", "warning", "info"]` — simpler than RuleSeverity enum, JSON-native

### Violation Pydantic Model
- `rule_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]*\d{2}$")` — matches Phase 48 exactly (P0-3)
- Field set exactly `{rule_id, severity, message, component_refs, suggestion_relative}` (LO-04 scoped per P1-2)
- `to_json() -> dict` and `to_markdown() -> str` methods (D-04 dual output)

### LayoutView Frozen Dataclass (`src/kicad_agent/conventions/layout_view.py`)
- `@dataclass(frozen=True)` per Phase 100 CR-01
- `from_schematic_ir(ir)` projects kiutils SchematicSymbols / graphicalItems.Connection wires / labels into frozen ComponentView / WireView / LabelView tuples (P1-1)
- NEVER calls `.serialize()` / `.write()` / `.to_file()` on the IR (P0-2)
- `to_mutations()` emits `{"op": "move_symbol", "ref": <ref>, "new_x": <x>, "new_y": <y>}` dicts — **P1-R2-1 (Council Round 2 fix)**: SchematicRawWriter.apply_mutation reads `new_x`/`new_y` keys (NOT legacy `x`/`y`); the writer silently ignores `angle`.

### ConventionConfigLoader (`src/kicad_agent/conventions/loader.py`)
- Mirrors Phase 48 RuleConfigLoader pattern (yaml.safe_load, threshold bounds, unknown-name rejection)
- `discover()` walks up from cwd, **stops at first `.git` ancestor or filesystem root** (P2-3 fix)
- Lazy catalog refresh via `_refresh_known_convention_names()` — empty frozenset until Plan 02 ships catalog
- `yaml.safe_load` only (T-111-01, grep-enforced)
- Threshold values bounded `[-1e6, 1e6]` (T-111-03)

### Dual Serializers (`src/kicad_agent/conventions/serializers.py`)
- `violations_to_json` — machine output, no truncation, round-trips through `json.loads`
- `violations_to_markdown` — human output, groups by severity (Errors → Warnings → Info), caps at 500 violations (T-48-01)
- `write_json_report` / `write_markdown_report` use `atomic_write` (never raw open/write)

## Round 1 Council Fixes Applied

| Fix | How |
|---|---|
| P0-3 (class-level attrs) | Convention declares `rule_id: str` and `severity: Severity` as class-level annotations; subclasses set them with `rule_id = "NAME_01"` (no `__init__` instance attrs) |
| P0-3 (rule_id regex) | Pattern `r"^[A-Z][A-Z0-9_]*\d{2}$"` — two-digit suffix mandatory, exactly matches Phase 48 `DesignRuleViolation.rule_id` |
| P1-1 (from_schematic_ir contract) | Reads `ir.components` (kiutils_obj.schematicSymbols), `ir.schematic.graphicalItems` (Connection wires), `ir.schematic.labels` — all read-only, never serializes |
| P1-2 (LO-04 scoped) | Verification introspects `Violation.model_fields` only (not broad source grep); ComponentView.position allowed in source |
| P2-1 (config param) | `check(layout, config=None)` signature mirrors Phase 48 |
| P2-3 (bounded discover) | `discover()` halts at first `.git` ancestor or fs root |

## Round 2 Council Fix Applied (NEW)

**P1-R2-1**: The original Plan 01 specified `LayoutView.to_mutations()` emit `{"op": "move_symbol", "ref": ..., "x": ..., "y": ..., "angle": ...}`. Inspection of `src/kicad_agent/ops/schematic_raw_writer.py` lines 420-421 revealed:
```python
new_x = float(mutation.get("new_x", 0.0))
new_y = float(mutation.get("new_y", 0.0))
```
The writer reads `new_x`/`new_y` (not `x`/`y`) and silently ignores `angle`. Emitting legacy `x`/`y` keys would silently no-op — the `--apply` path in Plan 03 would do nothing.

**Fix applied**: `to_mutations()` emits `{"op": "move_symbol", "ref": <ref>, "new_x": <x>, "new_y": <y>}` exclusively. No `x`/`y` keys, no `angle` field (writer cannot apply rotation — Phase 115 will extend the writer to honor angle for `IEEE315_PIN_ORIENTATION_01`). Enforced by `test_layout_view_to_mutations_emits_new_x_new_y_keys`.

## Deviations from Plan

None — plan executed exactly as written, with P1-R2-1 applied during execution per the orchestrator's execution-context instructions.

## Self-Check: PASSED

- All 5 created files exist (`src/kicad_agent/conventions/{__init__,base,layout_view,loader,serializers}.py` + 3 test files + 1 fixture)
- All 3 task commits present in git log: `04d05821`, `f0cd5d87`, `a76e1f17`
- 35 tests passing across `tests/test_convention_{abc,loader,serializers}.py`
- `grep frozen=True layout_view.py` → 5 matches
- `grep atomic_write serializers.py` → 6 matches
- `grep yaml.safe_load loader.py` → 3 matches (no other `yaml.` calls)
