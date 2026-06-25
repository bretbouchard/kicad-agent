# Phase 101: Schematic Ops Bug Fixes - Research

**Researched:** 2026-06-25
**Domain:** KiCad 10 schematic operation handlers (bug fixing, not new features)
**Confidence:** HIGH (all 5 bugs verified against source code; reproduction fixtures confirmed accessible)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

1. **Fix all 5 bugs (P0-001 through P0-005)** — no descoping. All five are blocking analog-ecosystem backplane cleanup.
2. **R-3 is DEPRECATE ONLY this phase** — full raw S-expr rewrite of `erc_auto_fix` is explicitly deferred to a follow-up phase. This phase marks both `erc_auto_fix` and `erc_auto_fix_hierarchical` as DEPRECATED in op metadata. The PWR_FLAG nesting bug is NOT fixed in-line.
3. **General fixes only** — no backplane-specific workarounds. Fixes must work for any KiCad 10 project.
4. **Recommended fix priority** (from CONTEXT.md §Recommended Fix Priority):
   1. R-3 (P0-003) — Deprecate `erc_auto_fix` ops immediately (~1 hour, preventive)
   2. R-1 (P0-001) — Quick attribute access fix (~2 hours)
   3. R-2 (P0-002) + R-4 (P0-004) — Position transform bugs, shared helper (~1 day)
   4. R-5 (P0-005) — Criteria alignment (~half day)
5. **Standalone phase** — no new infrastructure, no deps on other phases.
6. **Existing patterns must be reused** — the codebase already has position-transform logic in `SchematicIR.get_pin_positions()` (schematic_ir.py:965-1042) that R-2 and R-4 fixes should build on.

### Claude's Discretion

- Exact structure of the shared `apply_symbol_transform()` helper (function signature, module placement)
- Whether to add a new `deprecated` field to `OpMeta` vs using description prefix vs runtime warning
- Test fixture strategy: use analog-ecosystem backplane directly, or synthesize minimal fixtures
- Whether R-5's fix is "trust ERC report over internal criteria" (simple) or "align internal criteria with ERC definition" (thorough)

### Deferred Ideas (OUT OF SCOPE)

- Full `erc_auto_fix` raw S-expr rewrite (defer to follow-up phase)
- AI-assisted ERC repair (separate stream)
- New schematic ops (only fixing existing ones)
- Backplane-specific workarounds
- CR-01 immutability migration of NativeBoard dataclasses (Phase 99 deferred item, unrelated)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| R-1 (P0-001) | `update_symbols_from_library` crashes with `'Symbol' object has no attribute 'name'` | Root cause VERIFIED at `src/kicad_agent/ops/repair_components.py:146` — `sym.name == symbol_name`. kiutils `Symbol` class exposes `libId`/`entryName`/`libraryNickname`, NOT `name`. Fix: replace with `sym.entryName == symbol_name` or `sym.libId == lib_id` (both already used elsewhere in the same function). |
| R-2 (P0-002) | `place_missing_units` places multi-unit components at colliding positions | Code at `repair_components.py:439-714`. Position dedup via `_occupied_positions` set ALREADY EXISTS (line 497, 645-652, 693) — added during Issue #3. Dedup only applies to the FALLBACK path. When `_find_position_for_unit` returns a position, it BYPASSES the collision check. Fix: route ALL returned positions through the dedup set, or make `_find_position_for_unit` aware of `_occupied_positions`. |
| R-3 (P0-003) | `erc_auto_fix` rewrites entire file, corrupts KiCad 10 schematics | Code at `erc_auto_fix.py:177-450` (symptom mode) and `640-750+` (hierarchical). Uses `ir.schematic.to_file()` (kiutils re-serialization) at lines 341, 359, 388, 409, 438. This phase: DEPRECATE only. Add `deprecated` field to `OpMeta`, mark both ops, emit runtime warning. |
| R-4 (P0-004) | `place_no_connects_from_erc` places markers at wrong positions | Code at `repair_erc.py:194-350`. Violation positions come from `extract_violation_positions()` (erc_parser.py:106) which reads kicad-cli JSON. Positions are ALREADY in sheet-absolute mm coordinates (erc_parser.py:169 multiplies by 100). Pin positions from `ir.get_pin_positions()` ALSO apply symbol transforms (schematic_ir.py:1026-1031). The mismatch is likely a ROUNDING tolerance issue: `pos_to_type` dict keys use `round(p["x"], 2)` (2 decimal places = 10μm), but violation positions may not land within that grid. Fix: use `SNAP_TOLERANCE`-based matching (already imported at line 215) for pin type lookup, not exact dict key. |
| R-5 (P0-005) | `remove_dangling_wires` uses geometric criteria, not KiCad ERC electrical criteria | Code at `repair_wires.py:406-515`. Current criteria (line 449-454): endpoint is "anchored" if it has a pin, label, junction, OR 2+ wires meeting. This MISSES: wires ending at label of wrong type, wires crossing without junction, wires ending at no-connect. Simplest fix aligned with CONTEXT.md note: accept an optional `erc_positions` parameter — if ERC reports `wire_dangling` at position X, remove that wire directly. |
</phase_requirements>

## Summary

Phase 101 closes 5 P0/P1 schematic operation bugs discovered during analog-ecosystem backplane ERC cleanup (Phases 123-127, 2026-06-24). All 5 bugs are in existing operation handlers — no new infrastructure needed. The bugs collectively block ~600 ERC violations from being addressed via script-driven cleanup on a 12-sheet KiCad 10 hierarchical schematic with 188 components.

**Root causes cluster into three classes:**

1. **Attribute access bug (R-1):** Single line — `sym.name` should be `sym.entryName` or `sym.libId`. kiutils `Symbol` class exposes `libId` as a property (no `name` attribute exists). Fix is a one-character-class change.

2. **Position transform / collision-detection bugs (R-2, R-4, R-5):** Three bugs share a theme but have distinct mechanisms. R-2 is a bypassed dedup set (the dedup logic exists but only runs in the fallback path). R-4 is a rounding-tolerance mismatch between ERC violation coordinates and pin-position dict keys. R-5 is a criteria mismatch (geometric vs electrical "dangling" definition). The CONTEXT.md "shared helper" framing is slightly misleading — each bug needs its own targeted fix, though R-2 and R-4 both benefit from consistent tolerance-based coordinate comparison.

3. **kiutils re-serialization corruption (R-3):** Known issue documented in project memory (`kiutils-root-sheet-danger.md`). The `erc_auto_fix` ops call `ir.schematic.to_file()` which re-serializes the entire schematic through kiutils, stripping KiCad 10 strict formatting. **This phase DEPRECATES both ops only** — full raw S-expr rewrite is deferred.

**Primary recommendation:** Execute the 4-step priority order from CONTEXT.md. R-3 deprecation first (1 hour, prevents ongoing data loss), then R-1 quick fix (2 hours, unblocks 242 violations), then R-2+R-4 together (1 day, shared tolerance-matching helper), then R-5 (half day, ERC-position-passthrough approach).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Op handler bug fixes (R-1,2,4,5) | `src/kicad_agent/ops/` | — | All bugs live in operation handler functions; fixes are localized to handler modules |
| Registry deprecation metadata (R-3) | `src/kicad_agent/ops/registry.py` | `OpMeta` Pydantic model | Central registry owns op lifecycle status; `OpMeta` is the schema for per-op metadata |
| Pin position calculation | `src/kicad_agent/ir/schematic_ir.py` | — | `get_pin_positions()` already applies symbol transforms correctly (lines 965-1042); R-2/R-4 fixes should reuse this pattern, not duplicate it |
| ERC violation parsing | `src/kicad_agent/ops/erc_parser.py` | — | `extract_violation_positions()` owns the ERC-report-to-coordinate pipeline; positions are already mm-normalized (×100) |
| Test fixtures | `tests/fixtures/` + analog-ecosystem backplane | — | Existing fixtures cover regression; backplane provides real-world reproduction (VERIFIED accessible at `/Users/bretbouchard/apps/analog-ecosystem/hardware/backplane/`) |
| Validation gates | `kicad-cli sch erc` | — | Every fix must be verified by running ERC before and after; non-negotiable per project CLAUDE.md |

## Standard Stack

### Core (all already installed — no new dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| kiutils | 1.4.8 | KiCad S-expression parsing (used by all 5 buggy handlers) | Project standard for schematic I/O. Known limitation: re-serialization corrupts KiCad 10 root sheets (R-3 root cause). `[VERIFIED: /opt/homebrew/lib/python3.11/site-packages/kiutils/symbol.py]` |
| Pydantic | 2.12.5 | `OpMeta` schema validation, op schemas | Already used for `OpMeta` at registry.py:17. R-3 deprecation field adds to this model. `[VERIFIED: src/kicad_agent/ops/registry.py:17]` |
| sexpdata | 1.0.0 | Low-level S-expression parsing | Used by `raw_parser.py` — the long-term R-3 fix pattern. NOT used this phase but documents the target architecture. `[VERIFIED: src/kicad_agent/parser/raw_parser.py]` |
| kicad-cli | 10.0.3 | ERC validation gate | Required for every fix verification. `[VERIFIED: /usr/local/bin/kicad-cli --version → 10.0.3]` |
| pytest | 8.0+ | Test framework | Project standard. Config in `pyproject.toml [tool.pytest.ini_options]`. `[VERIFIED: pyproject.toml]` |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| networkx | (installed) | Net connectivity graph | R-5 may reuse `NetPositionIndex` (already imported in repair_erc.py:194) for electrical-connection checks |
| math (stdlib) | — | Rotation transforms | R-2, R-4 pin position calculation: `rot_px = px * cos(θ) - py * sin(θ)` (already in schematic_ir.py:1026) |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Adding `deprecated` bool field to `OpMeta` | Description string prefix `"[DEPRECATED] "` | Field is cleaner, queryable, type-safe. Description prefix is zero-schema-change but hacky. **Recommend: add `deprecated: bool = False` field** — minimal change, forward-compatible. |
| Rewriting `erc_auto_fix` with raw S-expr (this phase) | DEPRECATE only (this phase) | CONTEXT.md explicitly defers rewrite. Raw S-expr rewrite is ~2-3 days work and belongs in a follow-up. **Decision: DEPRECATE only.** |
| Synthesizing minimal test fixtures | Using analog-ecosystem backplane directly | Backplane is 12 sheets / 188 components — slow for unit tests, but VERIFIED accessible. Best approach: unit tests on minimal synthesized schematics (fast), integration/smoke tests on backplane (real reproduction). |

**Installation:** No installation needed. All dependencies already in `pyproject.toml`.

## Architecture Patterns

### System Architecture Diagram — Bug Fix Verification Flow

```
BUG REPORT (BUGS/P0-00X.md)
    │
    ▼
REPRODUCE on fixture (analog-ecosystem/backplane/*.kicad_sch)
    │
    ├── kicad-cli sch erc BEFORE  ──► baseline violation count
    │
    ▼
LOCATE bug in handler (src/kicad_agent/ops/repair_*.py)
    │
    ▼
WRITE failing test first (TDD — RED)
    │   test must assert the SPECIFIC success criterion from CONTEXT.md
    │
    ▼
APPLY targeted fix
    │   R-1: sym.name → sym.entryName (1 line)
    │   R-2: route _find_position_for_unit results through _occupied_positions
    │   R-3: add deprecated=True to OpMeta + registry entries
    │   R-4: SNAP_TOLERANCE-based pin-type lookup (replace exact dict key)
    │   R-5: accept erc_positions param, bypass geometric criteria when provided
    │
    ▼
VERIFY test passes (GREEN)
    │
    ▼
RUN kicad-cli sch erc AFTER  ──► compare to baseline
    │   net violation delta must be ≤ 0 (SC-3, SC-5)
    │   or removal rate ≥ 90% (SC-6)
    │
    ▼
REGRESSION: run existing test suite
    │   test_erc_auto_fix.py, test_schematic_repair.py,
    │   test_place_no_connects_power_aware.py must stay green (SC-7)
```

### Recommended Project Structure (no new files needed)

```
src/kicad_agent/
├── ops/
│   ├── registry.py              # R-3: add `deprecated` field to OpMeta, mark 2 ops
│   ├── repair_components.py     # R-1 (line 146), R-2 (lines 620-652 dedup bypass)
│   ├── repair_erc.py            # R-4 (lines 194-350 tolerance matching)
│   ├── repair_wires.py          # R-5 (lines 406-515 criteria alignment)
│   └── erc_auto_fix.py          # R-3: add runtime DeprecationWarning at entry
├── ir/
│   └── schematic_ir.py          # REFERENCE: get_pin_positions() — correct transform pattern
└── ops/
    └── erc_parser.py            # REFERENCE: extract_violation_positions() — mm-normalized

tests/
├── test_schematic_repair.py     # EXTEND: add R-1, R-2, R-4 regression tests
├── test_erc_auto_fix.py         # EXTEND: add R-3 deprecation warning test
├── test_place_no_connects_power_aware.py  # EXTEND: add R-4 tolerance test
└── (new file for R-5)           # test_remove_dangling_wires_erc_aligned.py
```

### Pattern 1: Symbol Transform Application (REUSE — do not reinvent)

**What:** Compute absolute pin positions from symbol-local pin offsets + symbol placement transform.
**When to use:** ANY operation that needs to compare ERC violation coordinates against pin locations (R-4) or place new units relative to existing ones (R-2).
**Reference implementation:** `src/kicad_agent/ir/schematic_ir.py:965-1042` (`get_pin_positions()`).

```python
# Source: src/kicad_agent/ir/schematic_ir.py:1020-1031 [VERIFIED]
for pin_def in pin_defs:
    px = pin_def.position.X
    py = pin_def.position.Y
    # Apply rotation to pin offset, then translate.
    angle_rad = math.radians(angle_deg)
    rot_px = px * math.cos(angle_rad) - py * math.sin(angle_rad)
    rot_py = px * math.sin(angle_rad) + math.cos(angle_rad)
    # T-10-11: pin absolute position = (sx + rot_px, sy - rot_py)
    # Y-inversion: KiCad pin Y is inverted relative to sheet coords.
    abs_x = sx + rot_px
    abs_y = sy - rot_py
```

**R-2 and R-4 fixes should NOT duplicate this.** They should call `ir.get_pin_positions()` or factor out a shared `apply_symbol_transform(symbol, pin_offset)` helper if inline reuse is cleaner.

### Pattern 2: Tolerance-Based Position Matching (R-4 fix pattern)

**What:** KiCad coordinates have sub-micron precision but ERC output rounds differently. Exact dict-key matching fails; tolerance-based matching succeeds.
**When to use:** Comparing ERC violation positions against pin/wire/label position sets.

```python
# Source: src/kicad_agent/ops/repair_erc.py:215, 288, 309-311 [VERIFIED]
from kicad_agent.ops.repair_wires import SNAP_TOLERANCE, _near_anchor

# BAD (current R-4 bug): exact dict key lookup
pos_key = (round(vp.x, 2), round(vp.y, 2))
pin_type = pos_to_type.get(pos_key, "passive")  # ← fails if vp is 0.003mm off

# GOOD: tolerance-based lookup
pin_type = _lookup_pin_type_with_tolerance(vp.x, vp.y, pin_positions, SNAP_TOLERANCE)
```

### Pattern 3: Op Deprecation (R-3 — new pattern, minimal)

**What:** Mark an op as deprecated without removing it. Runtime warning + metadata flag.
**When to use:** When an op has a data-loss bug (R-3) but cannot be removed without breaking callers.

```python
# Source: NEW — add `deprecated: bool = False` to OpMeta [RECOMMENDED]
class OpMeta(BaseModel):
    op_type: str
    category: str
    description: str
    file_types: list[str]
    is_readonly: bool
    scope: Literal["single_point", "single_file", "multi_file"]
    requires: list[str]
    conflicts: list[str]
    deprecated: bool = False  # NEW FIELD — default False for backward compat

# Registry entry:
"erc_auto_fix": {
    "category": "erc_smart",
    "description": "Meta-operation: run ERC, dispatch repairs by violation type, iterate",
    # ... existing fields ...
    "deprecated": True,  # NEW
},
```

Runtime warning (in handler or executor):
```python
import warnings
if meta.deprecated:
    warnings.warn(
        f"Op '{op_type}' is DEPRECATED: {deprecation_reason}. "
        f"Use targeted individual ops instead. See BUGS/P0-003.md.",
        DeprecationWarning,
        stacklevel=2,
    )
```

### Anti-Patterns to Avoid

- **DO NOT** rewrite `erc_auto_fix` with raw S-expr this phase (CONTEXT.md defers this)
- **DO NOT** duplicate the pin-transform math from `schematic_ir.py` — call `ir.get_pin_positions()` or extract a shared helper
- **DO NOT** add backplane-specific conditionals — fixes must be general
- **DO NOT** use `round(x, 2)` for coordinate comparison — use `SNAP_TOLERANCE` (already imported in repair_erc.py)
- **DO NOT** skip the kicad-cli ERC verification step — SC-3, SC-5, SC-6 require before/after ERC counts

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Pin absolute position calculation | Manual `(sx + px, sy + py)` without rotation | `ir.get_pin_positions()` (schematic_ir.py:965) | Already handles rotation, Y-inversion, multi-unit lib symbol lookup, nickname-less fallback |
| ERC violation position extraction | Parse `.rpt` text format | `extract_violation_positions()` (erc_parser.py:106) | Already handles kicad-cli JSON, mm normalization (×100), sheet filtering |
| Wire connectivity graph | Manual endpoint matching | `ir.get_wire_endpoints()` + `NetPositionIndex` (already imported) | Handles junctions, multi-wire intersections, net membership |
| Position dedup set | New `_occupied_positions` tracking | Existing `_occupied_positions` in `place_missing_units` (repair_components.py:497) | Already tracks placed positions — R-2 fix routes ALL positions through it, not just fallback |

**Key insight:** Every utility needed to fix these bugs ALREADY EXISTS in the codebase. The bugs are integration gaps where existing utilities are bypassed or used inconsistently. The fix is wiring, not invention.

## Common Pitfalls

### Pitfall 1: R-2 Dedup Bypass (THE bug to fix)

**What goes wrong:** `_find_position_for_unit()` (repair_components.py:317) returns a position. That position is used directly (line 654: `new_x, new_y = pos`) WITHOUT checking `_occupied_positions`. When multiple parent components (U30, U31, U32, U33) each need unit C placed, and `_find_position_for_unit` uses the same wire/label heuristics for each, it returns the SAME position for all of them. Collision.
**Why it happens:** The dedup set (line 645-652) only runs in the `if pos is None:` fallback branch. The happy path skips it.
**How to avoid:** After `pos = _find_position_for_unit(...)`, check `_occupied_positions` and offset if needed. OR pass `_occupied_positions` into `_find_position_for_unit` so it never returns a colliding position.
**Warning signs:** Test with 4+ instances of same multi-unit component. If all unit C instances land at the same (x, y), the bug is present.

### Pitfall 2: R-4 Rounding-Tolerance Mismatch

**What goes wrong:** `pos_to_type` dict (repair_erc.py:229-232) uses `round(p["x"], 2)` as keys (2 decimal places = 10μm grid). ERC violation positions may have coordinates like `(127.003, 85.997)` which rounds to `(127.00, 86.00)` — but if the pin position dict was built from a symbol at `(127.005, 85.995)`, it rounds to `(127.01, 86.00)` — DIFFERENT key. Lookup fails, defaults to `"passive"`, skips the UNSAFE_PIN_TYPES check.
**Why it happens:** KiCad schematic coordinates and kicad-cli ERC JSON output use different precision. The ×100 normalization (erc_parser.py:169) can introduce floating-point drift.
**How to avoid:** Use `SNAP_TOLERANCE`-based fuzzy matching for ALL position comparisons. The project already has `_near_anchor()` (repair_wires.py) for this — use it consistently.
**Warning signs:** Test with a pin that has 3+ decimal places of precision. If the op places a no_connect on a pin whose type should have been skipped, the bug is present.

### Pitfall 3: R-3 Premature Rewrite Temptation

**What goes wrong:** Developer reads P0-003, sees "kiutils re-serialization corrupts files," and decides to rewrite `erc_auto_fix` with raw S-expr manipulation in this phase.
**Why it happens:** The fix feels obviously correct. But CONTEXT.md explicitly defers it: "Full `erc_auto_fix` raw S-expr rewrite (defer to follow-up — this phase only deprecates)."
**How to avoid:** Add `deprecated: True` to registry, add `DeprecationWarning` at handler entry, create a Bead tracking the deferred rewrite. Do NOT touch the kiutils serialization calls.
**Warning signs:** If the plan includes changes to `ir.schematic.to_file()` call sites or new raw S-expr parsing in erc_auto_fix.py, it's out of scope.

### Pitfall 4: R-5 Over-Engineering the Criteria

**What goes wrong:** Developer tries to fully replicate KiCad ERC's internal "dangling" definition (label type validation, crossing-without-junction detection, etc.).
**Why it happens:** The thorough fix feels more correct than a passthrough.
**How to avoid:** CONTEXT.md note on P0-005 (line 56): "if ERC reports wire_dangling at position X, the op should remove that wire even if its internal criteria don't flag it." This is the SIMPLE passthrough approach — accept ERC positions as ground truth, bypass geometric heuristics.
**Warning signs:** If the R-5 plan adds >50 lines of new label-type-validation logic, it's over-engineered. The passthrough is ~10 lines.

### Pitfall 5: Skipping ERC Verification on "Simple" Fixes

**What goes wrong:** R-1 is a one-line fix. Developer skips the before/after ERC comparison because "obviously it just unblocks the op."
**Why it happens:** ERC takes 10-30 seconds per sheet. Tempting to skip.
**How to avoid:** EVERY fix must include a kicad-cli ERC run before and after. SC-3, SC-5, SC-6 all require violation-count deltas. The op may "work" but introduce new violations (as P0-004 did — +2 violations).
**Warning signs:** Test plan lacks `kicad-cli sch erc` invocation. Fix it before approval.

## Code Examples

### R-1 Fix (one line)

```python
# Source: src/kicad_agent/ops/repair_components.py:146 [VERIFIED BUG]
# CURRENT (broken):
for sym in lib.symbols:
    if sym.libId == lib_id or sym.name == symbol_name:  # ← AttributeError
        source_symbol = sym
        break

# FIXED:
for sym in lib.symbols:
    # kiutils Symbol class has libId (property) and entryName, NOT name.
    # [VERIFIED: /opt/homebrew/lib/python3.11/site-packages/kiutils/symbol.py:221,297]
    if sym.libId == lib_id or sym.entryName == symbol_name:
        source_symbol = sym
        break
```

### R-2 Fix (route all positions through dedup)

```python
# Source: src/kicad_agent/ops/repair_components.py:620-654 [VERIFIED]
# CURRENT (broken — dedup only in fallback):
for i, missing_num in enumerate(missing_unit_nums):
    center = (first_comp.position.X, first_comp.position.Y)
    pos = _find_position_for_unit(
        ir, lib_sym, missing_num, rotation,
        wire_endpoints, label_positions,
        center=center, max_distance=100.0,
        net_index=net_index,
        placed_unit_roots=placed_unit_roots,
    )
    if pos is None:
        # fallback with dedup (existing, correct)
        ...
    # BUG: pos used directly without dedup check
    new_x, new_y = pos

# FIXED — always check dedup:
for i, missing_num in enumerate(missing_unit_nums):
    center = (first_comp.position.X, first_comp.position.Y)
    pos = _find_position_for_unit(...)
    if pos is None:
        # fallback (existing logic)
        offset_idx = len(components) + i
        pos = (first_comp.position.X + offset_idx * offset_x,
               first_comp.position.Y + offset_idx * offset_y)
    # ALWAYS check dedup, regardless of pos source
    pos_key = _round_pos(pos[0], pos[1])
    while pos_key in _occupied_positions:
        # nudge by offset_x until clear
        pos = (pos[0] + offset_x, pos[1] + offset_y)
        pos_key = _round_pos(pos[0], pos[1])
    new_x, new_y = pos
```

### R-4 Fix (tolerance-based pin-type lookup)

```python
# Source: src/kicad_agent/ops/repair_erc.py:229-232, 322 [VERIFIED BUG]
# CURRENT (broken — exact dict key):
pos_to_type: dict[tuple[float, float], str] = {}
for p in pin_positions:
    key = (round(p["x"], 2), round(p["y"], 2))  # 10μm grid
    pos_to_type[key] = p.get("electrical_type", "passive")
# ...later...
pin_type = pos_to_type.get(pos_key, "passive")  # ← miss if 0.003mm off

# FIXED — tolerance-based lookup using existing helper:
def _lookup_pin_type(
    x: float, y: float,
    pin_positions: list[dict],
    tolerance: float,
) -> str:
    """Find pin electrical type at (x,y) within tolerance. Default 'passive'."""
    for p in pin_positions:
        if abs(x - p["x"]) <= tolerance and abs(y - p["y"]) <= tolerance:
            return p.get("electrical_type", "passive")
    return "passive"

# Usage:
pin_type = _lookup_pin_type(vp.x, vp.y, pin_positions, SNAP_TOLERANCE)
```

### R-5 Fix (ERC-position passthrough — simplest approach)

```python
# Source: src/kicad_agent/ops/repair_wires.py:406-515 [VERIFIED]
# CURRENT (geometric criteria only):
def remove_dangling_wires(ir, file_path, *, max_length_mm=None, dry_run=False):
    # ... geometric detection ...
    return {"removed_count": len(removed), "details": removed}

# FIXED — accept ERC positions as ground truth:
def remove_dangling_wires(
    ir, file_path, *,
    max_length_mm=None,
    dry_run=False,
    trust_erc: bool = True,  # NEW
):
    # ... existing geometric detection ...

    # NEW: If trust_erc, also remove any wire whose endpoint matches an ERC
    # wire_dangling violation position, even if geometric criteria didn't flag it.
    if trust_erc:
        from kicad_agent.ops.erc_parser import extract_violation_positions
        erc_positions = extract_violation_positions(file_path, "wire_dangling")
        erc_pos_set = {(round(p.x, 2), round(p.y, 2)) for p in erc_positions}
        # ... add any wire touching an erc_pos to wires_to_remove ...
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `place_missing_units` without dedup | Dedup added (Issue #3) | Pre-Phase 101 | Reduced collisions but bypass remains in happy path — R-2 closes the gap |
| `place_no_connects_from_erc` without power-pin filtering | Pin type + power net + co-location checks added (Phase 68, Issues #4, #13) | Pre-Phase 101 | Added safety filters but tolerance mismatch prevents them from firing — R-4 fixes the lookup |
| Manual ERC report parsing | `extract_violation_positions()` with mm normalization | Phase 40+ | Centralized ERC parsing; R-4/R-5 fixes should reuse it |
| kiutils-only schematic I/O | NativeParser exists for PCB (Phase 76) | Phase 76 | Raw S-expr pattern established for PCB; schematic equivalent is the deferred R-3 long-term fix |

**Deprecated/outdated:**
- `ir.schematic.to_file()` on KiCad 10 root sheets: Known dangerous (project memory `kiutils-root-sheet-danger.md`). R-3 deprecation formalizes this for `erc_auto_fix` ops.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The R-2 dedup bypass is the sole cause of position collisions (not `_find_position_for_unit` returning genuinely identical positions for identical inputs) | Per-Bug R-2 | If `_find_position_for_unit` itself is deterministic-per-input AND returns same position for U30/U31/U32/U33, the dedup loop fixes it anyway. Low risk. |
| A2 | R-4's tolerance mismatch is the root cause (not a coordinate-system error) | Per-Bug R-4 | If the real bug is a coordinate-system mismatch (e.g., ERC reports sheet-relative, pin positions are root-relative), tolerance fix won't help. MEDIUM risk — verify by printing actual coordinates from both sources in a test. |
| A3 | Adding `deprecated: bool = False` to `OpMeta` won't break existing consumers | R-3 Deprecation Strategy | If any code does `OpMeta(**dict)` without filtering unknown keys, adding a field is safe (Pydantic accepts new fields). If code iterates `model_fields` and asserts exact count, it breaks. LOW risk — Pydantic models are designed for additive changes. |
| A4 | The analog-ecosystem backplane will remain accessible for the duration of Phase 101 execution | Validation Architecture | If the repo moves or sheets are renamed, integration tests fail. LOW risk — confirmed accessible at research time. |
| A5 | R-5's "trust ERC positions" approach is acceptable to the user (vs thorough criteria alignment) | Per-Bug R-5 | CONTEXT.md line 56 explicitly endorses this approach. LOW risk. |

## Open Questions (RESOLVED)

1. **Should the `deprecated` field also surface in MCP tool annotations?**
   - What we know: MCP server (Phase 30, pending) auto-derives annotations from registry. Adding `deprecated` to `OpMeta` is forward-compatible.
   - What's unclear: Whether MCP clients (Claude, Cursor) consume a `deprecated` hint.
   - RESOLVED: Add the field now, surface as `(deprecated)` prefix in MCP tool description when Phase 30 ships. No blocker for Phase 101.

2. **Should R-1's fix also handle the `libId == lib_id` check more defensively?**
   - What we know: Line 146 has `sym.libId == lib_id or sym.name == symbol_name`. The first clause already works. The bug only fires when `libId` doesn't match and the code falls through to `sym.name`.
   - RESOLVED: Replace `sym.name` with `sym.entryName`. The `libId` match handles qualified IDs (`Device:R`); `entryName` handles unqualified (`R`). Both are correct kiutils attributes.

3. **Does R-2's `_find_position_for_unit` need to be audited for returning colliding positions even when passed `_occupied_positions`?**
   - What we know: Current signature (repair_components.py:317) does NOT accept `_occupied_positions`. The dedup loop after the call handles it.
   - RESOLVED: Post-call dedup loop (the R-2 fix) is sufficient. Passing the set into the function is an optimization, not a correctness requirement. Defer internal awareness to a follow-up if performance matters.

4. **Should R-5 keep the geometric criteria as a fallback when ERC reports no `wire_dangling` violations?**
   - What we know: Phase 123 Wave 2 successfully used geometric criteria (removed 143 violations). The geometric approach catches SOME cases.
   - RESOLVED: Yes — keep geometric as fallback. When `trust_erc=True` and ERC reports positions, use those AND the geometric results (union). When ERC reports nothing, fall back to geometric only. This preserves Wave 2's success while fixing the silent no-op.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| kicad-cli | ERC verification (all fixes) | ✓ | 10.0.3 | — |
| pytest | Test execution | ✓ | 8.0+ | — |
| kiutils | All 5 handler modules | ✓ | 1.4.8 | — |
| Pydantic | OpMeta schema (R-3) | ✓ | 2.12.5 | — |
| analog-ecosystem backplane | Integration reproduction | ✓ | KiCad 10, 12 sheets | Synthesized minimal fixtures for unit tests |
| `tests/fixtures/Arduino_Mega/` | Regression tests | ✓ | KiCad 10 | — |
| `tests/fixtures/RaspberryPi-uHAT/` | Regression tests | ✓ | KiCad 10 | — |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:** None — all required tools and fixtures are present.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.0+ |
| Config file | `pyproject.toml [tool.pytest.ini_options]` |
| Quick run command | `cd ~/apps/kicad-agent && python3 -m pytest tests/test_schematic_repair.py tests/test_erc_auto_fix.py tests/test_place_no_connects_power_aware.py -x -q` |
| Full suite command | `cd ~/apps/kicad-agent && python3 -m pytest tests/ -x -q --ignore=tests/inference --ignore=tests/integration` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| R-1 (SC-1) | `update_symbols_from_library` does not crash on schematic with lib_symbol_mismatch | unit | `python3 -m pytest tests/test_schematic_repair.py -k update_symbols -x` | ✅ (test_erc_auto_fix.py:43 — extend) |
| R-2 (SC-2) | `place_missing_units` produces N distinct positions for N missing units | unit | `python3 -m pytest tests/test_schematic_repair.py -k place_missing_units_collisions -x` | ❌ Wave 0 — new test |
| R-3 (SC-3, SC-4) | `erc_auto_fix` registry entry has `deprecated=True`; handler emits DeprecationWarning | unit | `python3 -m pytest tests/test_erc_auto_fix.py -k deprecation -x` | ❌ Wave 0 — new test |
| R-4 (SC-5) | `place_no_connects_from_erc` produces zero new `no_connect_connected` violations | integration | `python3 -m pytest tests/test_place_no_connects_power_aware.py -k tolerance -x` | ✅ (extend) |
| R-5 (SC-6) | `remove_dangling_wires` removes ≥90% of ERC `wire_dangling` violations | integration | `python3 -m pytest tests/test_schematic_repair.py -k dangling_erc -x` | ❌ Wave 0 — new test |
| SC-7 (regression) | Existing Phase 23, 38, 40 tests pass | regression | `python3 -m pytest tests/test_schematic_repair.py tests/test_erc_auto_fix.py tests/test_place_no_connects_power_aware.py -x` | ✅ |

### Sampling Rate

- **Per task commit:** `python3 -m pytest tests/test_schematic_repair.py tests/test_erc_auto_fix.py tests/test_place_no_connects_power_aware.py -x -q` (~15 seconds)
- **Per wave merge:** `python3 -m pytest tests/ -x -q --ignore=tests/inference --ignore=tests/integration` (~3 minutes)
- **Phase gate:** Full suite green + kicad-cli ERC before/after comparison on backplane codecs.kicad_sch and audio-buffers.kicad_sch

### Wave 0 Gaps

- `tests/test_schematic_repair.py::test_place_missing_units_no_collisions` — covers R-2 (SC-2). Build minimal schematic with 2+ instances of same multi-unit component, assert distinct positions.
- `tests/test_erc_auto_fix.py::test_erc_auto_fix_deprecation_warning` — covers R-3 (SC-4). Assert `warnings.simplefilter("always")` catches `DeprecationWarning` on op execution.
- `tests/test_erc_auto_fix.py::test_erc_auto_fix_registry_deprecated_flag` — covers R-3 (SC-4). Assert `OPERATION_REGISTRY["erc_auto_fix"].deprecated is True`.
- `tests/test_schematic_repair.py::test_remove_dangling_wires_erc_passthrough` — covers R-5 (SC-6). Build schematic with known wire_dangling pattern, verify ≥90% removal with `trust_erc=True`.
- `tests/test_place_no_connects_power_aware.py::test_no_connect_tolerance_matching` — covers R-4 (SC-5). Build schematic with pins at sub-0.01mm precision offsets, verify no false `passive` defaults.

## Sources

### Primary (HIGH confidence — codebase verified)

- `src/kicad_agent/ops/repair_components.py:146` — R-1 bug location (`sym.name`), `[VERIFIED]`
- `src/kicad_agent/ops/repair_components.py:439-714` — R-2 `place_missing_units` full implementation, `[VERIFIED]`
- `src/kicad_agent/ops/repair_components.py:497,645-652,693` — R-2 existing dedup logic (bypassed in happy path), `[VERIFIED]`
- `src/kicad_agent/ops/repair_erc.py:194-350` — R-4 `place_no_connects_from_erc` full implementation, `[VERIFIED]`
- `src/kicad_agent/ops/repair_erc.py:229-232,322` — R-4 rounding-tolerance bug location, `[VERIFIED]`
- `src/kicad_agent/ops/repair_wires.py:406-515` — R-5 `remove_dangling_wires` full implementation, `[VERIFIED]`
- `src/kicad_agent/ops/erc_auto_fix.py:177-450,640-750` — R-3 erc_auto_fix + hierarchical, `[VERIFIED]`
- `src/kicad_agent/ops/erc_auto_fix.py:341,359,388,409,438` — R-3 `to_file()` call sites (corruption source), `[VERIFIED]`
- `src/kicad_agent/ir/schematic_ir.py:965-1042` — `get_pin_positions()` correct transform reference, `[VERIFIED]`
- `src/kicad_agent/ops/erc_parser.py:106-170` — `extract_violation_positions()` + mm normalization, `[VERIFIED]`
- `src/kicad_agent/ops/registry.py:17-38` — `OpMeta` class (no `deprecated` field yet), `[VERIFIED]`
- `src/kicad_agent/ops/registry.py:856,883,892,1144,1153` — registry entries for all 5 ops, `[VERIFIED]`
- `/opt/homebrew/lib/python3.11/site-packages/kiutils/symbol.py:211-300` — `Symbol` class: `libId` is property (line 221), `entryName` is field (line 297), NO `name` attribute, `[VERIFIED]`
- `/Users/bretbouchard/apps/analog-ecosystem/hardware/backplane/*.kicad_sch` — all 12 sheets accessible for reproduction, `[VERIFIED]`
- `kicad-cli --version` → 10.0.3 at `/usr/local/bin/kicad-cli`, `[VERIFIED]`
- `pyproject.toml [tool.pytest.ini_options]` — pytest config confirmed, `[VERIFIED]`

### Secondary (MEDIUM confidence — documentation)

- `BUGS/P0-001` through `P0-005` — bug reports with reproduction steps
- `.planning/phases/101-schematic-ops-bug-fixes/CONTEXT.md` — approved scope, success criteria, deferred items
- Project memory: `kiutils-root-sheet-danger.md` (referenced in CONTEXT.md, confirms R-3 root cause)

### Tertiary (LOW confidence — needs validation)

- Assumption that R-4's tolerance mismatch is the sole cause (A2) — `MEDIUM` confidence, needs empirical verification during execution

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all dependencies verified installed with versions
- Architecture: HIGH — all 5 bugs located in source with line numbers; root causes confirmed against kiutils API
- Pitfalls: HIGH — derived from actual code reading, not hypothetical
- R-3 deprecation strategy: MEDIUM — the `deprecated` field addition is a recommendation (A3), not yet verified against all consumers
- R-5 passthrough approach: HIGH — explicitly endorsed by CONTEXT.md note

**Research date:** 2026-06-25
**Valid until:** 2026-07-25 (30 days — stable codebase, no external API dependencies)
