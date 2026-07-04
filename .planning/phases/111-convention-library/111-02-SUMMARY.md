---
phase: 111-convention-library
plan: 02
subsystem: conventions
tags: [conventions, catalog, engine, adapters, ieee315]
requires:
  - "111-01 (Convention ABC, LayoutView, Loader, Serializers)"
  - "Phase 48.5 readability rules (wrapped via adapter factory)"
  - "Phase 108 SRS-verification factor data (D-01 selection rationale)"
provides:
  - "v1 Convention catalog: 10 conventions (6 adapters + 4 new IEEE 315)"
  - "ConventionEngine (error-tolerant, severity-sorted, P2-1 config-aware)"
  - "wrap_readability_rule() class-synthesizing adapter factory (P0-3 fix)"
  - "GRID_ALIGNMENT_01 TRANSFORM convention (apply returns new LayoutView)"
affects:
  - "src/kicad_agent/conventions/catalog/* (new)"
  - "src/kicad_agent/conventions/engine.py (new)"
tech-stack:
  added: []
  patterns:
    - "Class-synthesizing factory for adapter pattern (avoids ABC instance-attr anti-pattern)"
    - "RuleSeverity enum → Severity Literal translation map"
    - "Per-convention config thresholds via check(layout, config) (P2-1)"
key-files:
  created:
    - src/kicad_agent/conventions/catalog/__init__.py
    - src/kicad_agent/conventions/catalog/readability_adapters.py
    - src/kicad_agent/conventions/catalog/signal_flow.py
    - src/kicad_agent/conventions/catalog/pin_orientation.py
    - src/kicad_agent/conventions/catalog/grid_alignment.py
    - src/kicad_agent/conventions/catalog/wire_orthogonality.py
    - src/kicad_agent/conventions/engine.py
    - tests/test_convention_engine.py
    - tests/test_convention_catalog.py
decisions:
  - "Adapter factory returns a CLASS (not instance) per P0-3 — class-level rule_id/severity"
  - "v1 catalog size: 10 conventions (within D-01's 10-15 range)"
  - "IEEE315_PIN_ORIENTATION_01 demoted to read-only per P1-R2-1 — writer cannot round-trip angle; DEFERRED-TO-NAMED-TARGET Phase 115 for TRANSFORM"
  - "GRID_ALIGNMENT_01 snaps to 2.54mm grid (KICAD_GRID_MM from Phase 108 layout_graph)"
metrics:
  duration: ~10 minutes
  completed: 2026-07-04
---

# Phase 111 Plan 02: Catalog + Engine Summary

v1 Convention catalog with 10 conventions (6 Phase 48.5 adapters + 4 new IEEE 315) prioritized by ACTUAL Phase 108 SRS-verification data, plus ConventionEngine mirroring Phase 48 DesignRuleEngine.

## What Was Built

### Class-Synthesizing Adapter Factory (`readability_adapters.py`)
- `wrap_readability_rule(design_rule)` returns a Convention **subclass** (not an instance) per P0-3 fix
- Class-level `rule_id` / `severity` / `description` attrs derived from the wrapped Phase 48.5 rule
- Implementation note: closure variables are renamed `_conv_*` to avoid Python class-body scope shadowing (`rule_id = rule_id` would NameError)
- `_SEVERITY_MAP` translates `RuleSeverity` enum (INFO/SUGGESTION/WARNING/CRITICAL) → `Severity` Literal (info/warning/error)
- `_translate()` drops `location` and `details` (coordinate-bearing fields per T-111-06)
- `get_adapted_readability_rules()` returns 6 Convention instances (one per Phase 48.5 rule)

### ConventionEngine (`engine.py`)
- Mirrors Phase 48 `DesignRuleEngine`: error-tolerant, severity-sorted
- `check(layout, config)` signature passes per-convention thresholds (P2-1)
- T-111-07: broken convention → meta-Violation (severity=warning); engine continues
- Disabled conventions skipped; results sorted error → warning → info

### 4 New IEEE 315 Conventions

Each grounded in ACTUAL Phase 108 SRS-verification data per D-01:

| Convention | Type | D-01 Rationale |
|---|---|---|
| `SIGNAL_FLOW_DIRECTION_01` | read-only | Phase 108 Sugiyama stage 1 reverses feedback edges; validates output respects left-to-right signal flow |
| `IEEE315_PIN_ORIENTATION_01` | read-only (v1) | Phase 108 emits `move_symbol` with `angle` field; **DEMOTED per P1-R2-1** — writer drops angle (see below) |
| `GRID_ALIGNMENT_01` | TRANSFORM | Phase 108 `layout_graph.py` declares `KICAD_GRID_MM = 2.54`; off-grid components break wire connectivity (Phase 26 finding) |
| `WIRE_ORTHOGONALITY_01` | read-only | Phase 108 emits `insert_wire` mutations; validates wires use 90° bends |

## D-01 Selection Rationale (citing ACTUAL 108-SRS-VERIFICATION.md)

Phase 108's actual observed behavior per `108-SRS-VERIFICATION.md`:

| Fixture | Baseline SRS | Autolayout SRS | Delta |
|---|---|---|---|
| Arduino_Mega | 0.6840 | 0.6964 | +0.0125 (PASS — autolayout MORE readable) |
| single_sheet_clean | 0.9375 | 0.9375 | 0.0000 (at ceiling) |
| complete_led | 0.6875 | 0.6875 | 0.0000 (at ceiling) |
| single_sheet_unannotated | 0.9375 | 0.9375 | 0.0000 (at ceiling) |

Per-factor deltas (Arduino_Mega only — small fixtures at ceiling):
- density: 1.000 → 1.000 (unchanged)
- clarity: 0.800 → 0.800 (unchanged)
- **spacing: 0.186 → 0.236 (+0.050 — IMPROVED by autolayout)**
- organization: 0.750 → 0.750 (unchanged)

**Interpretation:** Phase 108's autolayout engine already MOVES components well. The v1 catalog encodes rules Phase 108 already respects (positive validation) plus rules a larger board beyond Phase 108's v1 fixture corpus would break (forward-looking but grounded in Phase 108's actual `move_symbol` + `insert_wire` + `insert_label` mutation surface).

## Round 2 Council Fix Applied

**P1-R2-1: IEEE315_PIN_ORIENTATION_01 demoted to read-only for v1**

The original Plan 02 Task 2 specified IEEE315_PIN_ORIENTATION_01 as a TRANSFORM convention that would use `dataclasses.replace(comp_view, orientation=new_angle)` to snap passives to canonical 0°/90°/180°/270°. However, the round-trip path requires `LayoutView.to_mutations()` → `SchematicRawWriter.apply_mutations` → file. Inspection of `schematic_raw_writer.py` lines 420-422 shows:

```python
new_x = float(mutation.get("new_x", 0.0))
new_y = float(mutation.get("new_y", 0.0))
return SchematicRawWriter._move_symbol_by_ref(content, ref, new_x, new_y)
```

The writer reads only `new_x`/`new_y` — it silently ignores `angle`. A TRANSFORM convention that modified `ComponentView.orientation` would have its work silently dropped at write time.

**Resolution per Bureaucracy §7 four-state taxonomy:** SUPERSEDED-BY-ALTERNATIVE
- v1 state: read-only convention (apply = identity). The check() still flags non-canonical orientations.
- Alternative: extend `SchematicRawWriter._move_symbol_by_ref` to honor the `angle` field.
- Evidence: writer source lines 420-422 confirm angle is silently dropped.
- Auto-promotion trigger: when Phase 115 lands the writer angle extension, restore TRANSFORM semantics via `dataclasses.replace(comp, orientation=snapped)`.

## Self-Check: PASSED

- All 9 created files exist
- Task 1 commit: `d391c411`
- Task 2 commit: `b410a103`
- 28 tests passing across `tests/test_convention_{engine,catalog}.py`
- v1 catalog verification: 10 conventions, all class-level rule_ids match Phase 48 regex
