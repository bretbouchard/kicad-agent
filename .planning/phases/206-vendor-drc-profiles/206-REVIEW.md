---
phase: 206
plan: 01
title: "Phase 206 Code Review — Vendor DRC Profiles"
reviewer: zcode-reviewer
date: 2026-07-10
status: issues
tests_run: "tests/test_vendor_drc.py tests/test_drc_vendor_ops.py tests/test_drc_profiles.py tests/test_registry.py"
tests_result: "86 passed"
findings:
  critical: 0
  high: 1
  medium: 2
  low: 3
  nit: 2
---

# Phase 206 Code Review — Vendor DRC Profiles

## Summary

Phase 206 ships 9 bundled `.kicad_dru` files, an internal Python geometric
DRC evaluator (`manufacturing/vendor_drc.py`), two new read-only ops
(`drc_vendor`, `list_vendor_drc_profiles`), and the supporting schema /
registry / package-data wiring. The architecture is sound: the pivot away
from the non-existent `kicad-cli --custom-rules` flag to an in-process
evaluator is correct and well-documented, the dual-path NativeParser usage
is right, and the threat-model defenses (vendor-name allowlist + pattern)
are properly implemented at both the schema and resolver layers.

All 86 phase tests pass. However, one **high-severity** key-mismatch bug
makes the advertised `oshpark` vendor unreachable through the `drc_vendor`
op, and a **medium** evaluator correctness gap produces same-net false
positives. Both are masked by the test suite (schema-validation tests pass,
but no handler-resolution test exercises the broken key).

## Pytest Result

```
tests/test_vendor_drc.py tests/test_drc_vendor_ops.py
tests/test_drc_profiles.py tests/test_registry.py
86 passed in 3.17s
```

---

## Findings

### HIGH-1: `oshpark` vendor key unreachable — key-space mismatch between two registries

**Severity: HIGH** (advertised feature is broken end-to-end; test gap hides it)

The `drc_vendor` handler resolves the profile via `load_profile(op.vendor)`
(`src/kicad_agent/dfm/profiles.py`), but every other layer advertises a
different key for OSH Park:

| Layer | OSH Park key |
|---|---|
| `drc_profiles/__init__.py` `_PROFILE_INFOS` | `oshpark` |
| `list_drc_profiles()` return value | `oshpark` |
| `get_drc_profile_path("oshpark")` | resolves |
| `DrcVendorOp.vendor` schema (description lists examples) | `oshpark` |
| `dfm/profiles.py` `_PROFILES` dict (what the handler actually reads) | **`osh_park`** |

So `drc_vendor(vendor="oshpark")` — the canonical name returned by
`list_vendor_drc_profiles` and the one any caller will use — raises:

```
ValueError: Unknown profile 'oshpark'. Available built-in profiles:
... osh_park ...
```

Reproduced end-to-end:

```python
op = DrcVendorOp(target_file='t.kicad_pcb', vendor='oshpark', run_kicad_drc=False)
handler(op, ir, p)   # -> ValueError: Unknown profile 'oshpark'
```

The reverse direction also fails: `load_profile("osh_park")` works, but the
schema pattern `^[a-z0-9_]+$` would accept `osh_park` — except
`get_drc_profile_path("osh_park")` then fails (no such DRU file). The two
registries are simply out of sync on this one key.

**Why the tests miss it.** `test_drc_vendor_all_vendor_keys_valid`
(`tests/test_drc_vendor_ops.py:111`) iterates `list_drc_profiles()` and
asserts each `info.vendor` validates against the schema — but it never
runs the handler. Only `pcbway` is exercised through the handler
(`test_drc_vendor_pcbway_via_handler`), and `pcbway` happens to be a key
that matches in both registries. `oshpark` is never handler-resolved in
any test.

**Fix (either direction, pick one and make both registries agree):**
- Preferred: rename `_PROFILES["osh_park"]` → `"oshpark"` in
  `dfm/profiles.py` (matches the DRU filename and the advertised key), or
- Add an `"oshpark"` alias, or
- Rename the DRU/registry side to `osh_park`.
Then add a handler-resolution test that loops over every
`list_drc_profiles()` vendor key and asserts `drc_vendor(vendor=k)` runs
without `ValueError`.

**Files:**
- `/Users/bretbouchard/apps/kicad-agent/src/kicad_agent/dfm/profiles.py:260` (`_PROFILES` dict, key `osh_park`)
- `/Users/bretbouchard/apps/kicad-agent/src/kicad_agent/manufacturing/drc_profiles/__init__.py:125` (`oshpark`)
- `/Users/bretbouchard/apps/kicad-agent/src/kicad_agent/ops/handlers/query.py:106` (`load_profile(op.vendor)`)
- `/Users/bretbouchard/apps/kicad-agent/tests/test_drc_vendor_ops.py:111` (test gap)

---

### MEDIUM-1: Clearance check produces same-net false positives

**Severity: MEDIUM** (evaluator over-reports violations on legitimate routing)

`_check_clearance` (`vendor_drc.py:369`) compares every same-layer track
pair but never skips pairs on the same net. Real DRC engines never flag
same-net copper (segments of one route, meanders, fill). Consequence: a
board with two adjacent `GND` segments 0.15mm apart (generic min 0.2mm)
gets a spurious `vendor_clearance` ERROR and `passed=False`, even though
it is electrically correct.

Reproduced:

```python
# Two segments, SAME net "GND", 0.15mm apart, generic min_clearance 0.2mm
# -> 1 clearance violation (FALSE POSITIVE), passed=False
```

The docstring (line 380-382) scopes v1 to "track-to-track checks on the
same layer," but same-net exclusion is a foundational DRC rule, not an
advanced feature — KiCad's own clearance check always exempts same-net
items. The check captures `net1`/`net2` in the tuple (line 405) and emits
them in the violation (`net_a`/`net_b`), so the fix is a one-line guard
before the gap comparison:

```python
if net1 and net2 and net1 == net2:
    continue
```

(The `net1 and net2` guard preserves behavior for unnamed nets, which
KiCad represents as `net 0`/empty — those should still be checked since
two distinct unnamed nets could legitimately be different.)

Note: `NativeSegment.net_name` is populated for both KiCad 10
string-only (`net "NAME"`) and KiCad 9 (`net N "NAME"`) formats
(`pcb_native_parser.py:757-772`), so the comparison is reliable.

**Why the tests miss it.** `test_clearance_below_limit_violation`
(`tests/test_vendor_drc.py:161`) deliberately uses `net 0` and `net 1`,
so the false positive never surfaces.

**File:** `/Users/bretbouchard/apps/kicad-agent/src/kicad_agent/manufacturing/vendor_drc.py:404-423`

---

### MEDIUM-2: `test_drc_vendor_all_vendor_keys_valid` tests schema only, not resolution

**Severity: MEDIUM** (this is the test gap that allowed HIGH-1 to ship green)

The test named "all vendor keys valid"
(`tests/test_drc_vendor_ops.py:111-122`) validates that each
`list_drc_profiles()` vendor key is accepted by the Pydantic schema, then
stops. It does not confirm the handler can actually resolve and run that
key. This is exactly the seam where HIGH-1 lives. A passing test here
gives false confidence that all advertised vendors work.

**Fix:** extend the test to dispatch the handler (against an empty/clean
board) for every vendor key and assert no `ValueError`:

```python
def test_all_advertised_vendors_resolve_via_handler(self, tmp_path):
    from kicad_agent.ops.handlers.query import _QUERY_HANDLERS
    pcb_path = _write_clean_pcb(tmp_path)
    ir = _build_ir(pcb_path)
    handler = _QUERY_HANDLERS["drc_vendor"]
    for info in list_drc_profiles():
        op = DrcVendorOp(target_file="clean.kicad_pcb",
                         vendor=info.vendor, run_kicad_drc=False)
        result = handler(op, ir, pcb_path)   # must not raise
        assert result["vendor"]  # profile resolved
```

This single test would have caught HIGH-1.

**File:** `/Users/bretbouchard/apps/kicad-agent/tests/test_drc_vendor_ops.py:111`

---

### LOW-1: `_JLCPCB_4LAYER` annular ring left at the old permissive 0.1mm

**Severity: LOW** (out of stated DRC-07 scope; possible latent inconsistency)

DRC-07 corrected `min_annular_ring_mm` from `0.1` → `0.15` for
`_JLCPCB_STANDARD` and `_PCBWAY_STANDARD` (per the plan, lines 268-269).
`_JLCPCB_4LAYER` (`dfm/profiles.py:130`) still carries
`min_annular_ring_mm=0.1`. If JLC's 4-layer annular limit is genuinely
0.1mm this is fine, but it is now inconsistent with the 2-layer profile
and there is no comment explaining why it differs. Worth a one-line
comment or a confirmation against the vendor spec. (Note: this profile is
keyed `jlcpcb-4layer` with a hyphen, which the op schema pattern
`^[a-z0-9_]+$` rejects — see LOW-2 — so it is currently unreachable via
`drc_vendor` regardless.)

**File:** `/Users/bretbouchard/apps/kicad-agent/src/kicad_agent/dfm/profiles.py:130`

---

### LOW-2: `jlcpcb-4layer` profile is unreachable via `drc_vendor` (hyphen)

**Severity: LOW** (pre-existing; not a Phase 206 regression)

`_PROFILES["jlcpcb-4layer"]` exists in `load_profile`, but the
`DrcVendorOp.vendor` field pattern is `^[a-z0-9_]+$`, which rejects
hyphens. So `drc_vendor(vendor="jlcpcb-4layer")` fails schema validation
before it ever reaches the handler. This predates Phase 206 (the profile
and the pattern both predate it), and the new DRU set does not include a
4-layer JLC variant, so it is not in scope — but worth flagging since the
two vendor-name namespaces (`load_profile` keys vs op `vendor` keys) now
have two divergences (this + HIGH-1). A future cleanup should align them.

**File:** `/Users/bretbouchard/apps/kicad-agent/src/kicad_agent/dfm/profiles.py:258`

---

### LOW-3: Top-level `(arc ...)` copper tracks are not evaluated

**Severity: LOW** (documented v1 limitation; arcs are rarer than segments)

The evaluator iterates `board.segments` only. The native parser's
`_KNOWN_TOP_LEVEL` (`pcb_native_parser.py:380`) does not include `"arc"`,
and `NativeBoard` has no `arcs` field, so top-level KiCad 10 `(arc ...)`
copper tracks are neither parsed nor checked. A board routed with arc
tracks would have those tracks silently skipped by the track-width and
clearance checks. This is consistent with the "v1" framing, but it is a
silent skip of a real copper feature — worth at least a docstring note
that arc tracks are out of scope, and ideally a follow-up to parse them.

**File:** `/Users/bretbouchard/apps/kicad-agent/src/kicad_agent/manufacturing/vendor_drc.py:114-116` (and `parser/pcb_native_parser.py:380`)

---

### NIT-1: Test method name `test_registry_has_98_operations` asserts 156

**Severity: NIT** (pre-existing staleness, not introduced here)

`tests/test_registry.py:23` — the method is named
`test_registry_has_98_operations` but asserts `== 156`. Phase 206
correctly bumped the body (`154 → 156`) and updated the comment, but
perpetuated the stale method name that has drifted since at least Phase
101 (git history shows the body has been 141 → 142 → 154 → 156 while the
name stayed "98"). Rename to `test_registry_op_count` or
`test_registry_has_156_operations` to stop the drift.

**File:** `/Users/bretbouchard/apps/kicad-agent/tests/test_registry.py:23`

---

### NIT-2: `asdict` leaves `severity` as a `Severity` enum in handler output

**Severity: NIT** (consumers use `json.dumps(..., default=str)`; pre-existing pattern)

`_handle_drc_vendor` returns `asdict(result)`, and each `Violation` keeps
its `severity` as the `Severity.ERROR` enum (a `str` subclass). Plain
`json.dumps(res)` would fail; consumers must pass `default=str`. The CLI
already does this consistently (`cli.py` uses `default=str` everywhere),
and this matches the pre-existing `read_board_metadata` /
`run_kicad_drc` handler pattern, so it is not a regression. If the
agent/MCP layer ever serializes without `default=str`, it will surface
here first. No action required for this phase; noted for awareness.

**File:** `/Users/bretbouchard/apps/kicad-agent/src/kicad_agent/ops/handlers/query.py:123`

---

## What was done well

- **Dual-path is correct.** `_handle_drc_vendor` re-parses via
  `NativeParser.parse_pcb(file_path)` (`query.py:107`) and does not touch
  `ir.board`. The docstring documents the kiutils-vs-native `_native_board
  is None` issue and explicitly references the Phase 205 precedent. This
  is exactly right and avoids the silent-empty-results trap.
- **Threat model scenario 1 (path traversal) is well-defended.** Defense
  in depth: `DrcVendorOp.vendor` carries `pattern="^[a-z0-9_]+$"`
  (`_schema_pcb.py:1260`), and `get_drc_profile_path` independently
  re-validates the same regex plus an `is_file()` existence check
  (`drc_profiles/__init__.py:187-196`). Tests cover traversal, slashes,
  dots, and uppercase (`test_drc_profiles.py:120-141`).
- **Threat model scenario 2 (malformed board) is well-defended.** Every
  geometry access uses `getattr(..., default)` and each check is wrapped
  in its own `try/except` so one bad feature never aborts the run
  (`vendor_drc.py:118-161`). The evaluator never re-raises. The
  `width 0.0` test (`test_vendor_drc.py:247`) proves graceful handling.
- **Package-data wiring is correct and necessary.** The
  `[tool.setuptools.package-data]` block (`pyproject.toml:96-97`) is the
  right fix for the "works in editable, vanishes from wheel" pitfall, and
  the comment explains why.
- **Evaluator geometry math is sound.** Segment-to-segment distance
  (`_segment_gap` / `_point_to_segment_dist` / `_segments_intersect`),
  the annular-ring `(diameter - drill) / 2` formula, the
  centerline-distance clearance corridor (`limit + w1/2 + w2/2`), and the
  `_EPS` tolerance for boundary equality are all correct. The field
  accesses line up exactly with the `NativeSegment` / `NativeVia` /
  `NativePad` dataclasses in `pcb_native_types.py` (`.width`, `.drill`,
  `.diameter`, `.layer`, `.net_name`, `.pad_type`, `.size`, `.number`).
- **SLC compliance is clean** — no stubs, no TODOs, no `NotImplemented`,
  no `pass`-only bodies, no workaround markers across any of the new or
  modified source files.
- **Frozen dataclasses + tuple collections** for `VendorDrcResult` and
  `VendorDrcProfileInfo` are consistent with the project's CR-01
  immutability rule.
- **Registry/schema/union stay in sync.** The `156` count, the two new
  readonly-set members, the union members, and the `__all__` exports all
  line up; `validate_registry_completeness` passes.

---

## Verdict

**Status: issues.** Ship-blocking: HIGH-1 (the `oshpark` key mismatch
breaks an advertised, documented feature and is masked by a test gap).
Should-fix before merge: MEDIUM-1 (same-net false positives) and MEDIUM-2
(add the handler-resolution test that would have caught HIGH-1). The LOW
and NIT items can be follow-ups. The core architecture, security posture,
and test coverage of the evaluator's per-check logic are strong.
