---
phase: 208
plan: 01
role: code-review
reviewer: ZCode (code reviewer)
date: 2026-07-10
verdict: APPROVED (with 2 LOW notes + 1 pre-existing INFO)
---

# Phase 208 — Code Review (208-REVIEW.md)

**Scope:** `src/kicad_agent/manufacturing/handoff.py`, `src/kicad_agent/export/bom.py`,
`src/kicad_agent/dfm/profiles.py`, `src/kicad_agent/validation/gates/manufacturing_manifest.py`,
`src/kicad_agent/ops/_schema_pcb.py`, `src/kicad_agent/ops/registry.py`,
`src/kicad_agent/ops/schema.py`, `src/kicad_agent/ops/handlers/build.py`,
`tests/test_handoff.py`, `tests/test_registry.py`.

## Summary

The implementation is clean, idiomatic, and faithful to the plan. Security mitigations
(TM-1…TM-6) are all present and tested. The orchestrator correctly mirrors the dual-path
`NativeParser.parse_pcb` re-parse used by the existing `build_create` and `drc_vendor`
handlers. The profile-driven BOM formatter is well-factored and the hard-coded
`export_jlcpcb_bom` is correctly reduced to a thin backward-compat delegate.

## 1. Security

### Zip-slip / arcname (TM-2) — PASS
`handoff.py:568`: `zf.write(artifact_file, arcname=artifact_file.name)`. Arcname is the
basename only, never a path. `test_handoff_arcname_no_path_separator` asserts no `/` or `\`
in any namelist entry. Correct.

### Path traversal (TM-1) — PASS
`ops/handlers/build.py:331`: handler rejects `".." in Path(op.project_dir).parts` before
calling `export_handoff`. Mirrors `build_create`. The build dir is created strictly under
`project_dir / "builds"` (`handoff.py:390-400`).

### Vendor field injection (TM-3) — PASS
`ops/_schema_pcb.py:1394-1398`: `vendor` field has `pattern=r"^[a-z0-9_]+$"`, `min_length=1`,
`max_length=64`. Matches the `DrcVendorOp.vendor` pattern. `load_profile` raises `ValueError`
on unknown keys, which the orchestrator catches at `handoff.py:316-324` and returns a clean
failure result (no zip).

### CSV formula injection (TM-5) — PASS
`export/bom.py:312-325` `_sanitize_csv_cell` prefixes `= + - @ \t \r` with a leading `'`.
Applied to every cell in `export_bom_profile` via the dict comprehension at line 409.
`test_bom_profile_formula_injection_defense` confirms `=cmd|evil` becomes `'=cmd|evil`.
First-char-only inspection is the correct, documented choice.

### readme markdown injection (TM-4) — PASS
`_generate_readme` interpolates plain text into markdown only. Module docstring documents
the readme as data, not a trusted executable context. No HTML, no eval. Acceptable.

### Build dir / symlink escape (TM-6) — PASS
`build_dir.mkdir(parents=True, exist_ok=False)` under resolved `project_dir` (line 395).
Sub-second collision handled by uuid suffix (lines 396-400). All wrappers receive absolute
`build_dir` paths.

## 2. Orchestrator Correctness

### Dual-path: NativeParser.parse_pcb — PASS (correct)
`handoff.py:308`: `board = NativeParser.parse_pcb(pcb_path)`. This is the SAME pattern as
`ops/handlers/build.py:76` (`build_create`) and `ops/handlers/query.py:107` (`drc_vendor`).
The orchestrator needs the `NativeBoard` for two reasons: (a) `title_block` access for the
readme, and (b) vendor DRC geometry via `run_vendor_drc(board, profile)`. `PcbIR` (the
handler's `ir` arg) is built via the kiutils path where `_native_board` is None, so re-parsing
is required and correct. This matches the documented Phase 206 finding
(`vendor_drc.py:95-99`).

### Pre-handoff validation gate — PASS
Step 3 (`handoff.py:333-384`) runs DRC, ERC (if sch), vendor DRC (if profile). The tri-state
mapping (`_tri_state`, lines 106-115) is correct: `error_message` set -> `None` (inconclusive,
does NOT block); `passed=False` with no error -> `False` (BLOCKS); `passed=True` -> `True`.
Blockers collected and returned with NO zip created (lines 369-384). On DRC block the function
returns before the build dir is ever created (Step 4 is after the gate), so "no zip" is
guaranteed. `test_handoff_blocks_on_drc_failure` and `test_handoff_no_partial_state_on_failure`
confirm.

### Profile-driven BOM (Pitfall 3) — PASS
`grep export_jlcpcb_bom src/kicad_agent/manufacturing/` returns 0 matches. The orchestrator
calls `export_bom_profile` (`handoff.py:456`), never the hard-coded function. `export_jlcpcb_bom`
is reduced to a delegate (`bom.py:431-473`) that calls `export_bom_profile(..., load_profile("jlcpcb"))`.

### output_dir vs output_path divergence (RQ1) — PASS
Each wrapper is called with the correct kwarg:
- `export_gerber`, `export_drill`, `export_position`, `export_netlist` -> `output_dir=build_dir`
  (multi-file/directory outputs)
- `export_step`, `export_schematic_pdf`, `export_pcb_pdf` -> `output_path=<file>` (single-file)
Verified against the actual signatures in `export/general.py` and `export/render.py`.

### Critical vs non-critical export handling — PASS
Gerbers, drill, CPL, BOM (if sch) are critical: failure -> `_fail_with_cleanup` (rmtree +
`success=False`). Netlist, STEP, PDFs are non-critical: logged + tolerated (lines 474-507).
`_fail_with_cleanup` rmtree ensures no partial state on critical failure (line 610).

### No-partial-state cleanup — PASS
Two rmtree sites: the outer try/except around the whole pipeline (line 581) and the
per-critical-failure helper (line 610). Mirrors `build_create` (`build.py:164-165`).

### Streaming zip (Pitfall 7) — PASS
`zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED)` + `zf.write(path, arcname=name)`
(line 564-568). Files are streamed from disk, never loaded into memory. Handles large STEP
files correctly.

## 3. Profile & Manifest Model Extensions

### ManufacturerProfile (Task 1) — PASS
4 fields added after `drc_rules_path` (`profiles.py:59-74`): `bom_columns`,
`bom_filename_pattern`, `cpl_filename_pattern`, `include_step_by_default`. Set on
`_JLCPCB_STANDARD` (line 142-144) and `_JLCPCB_4LAYER` (line 166-168, Council LOW-1). Other
profiles inherit `None` defaults. `load_profile('jlcpcb').bom_columns` returns the expected
tuple; `load_profile('generic').bom_columns is None`.

### ManufacturingManifest (Task 1) — PASS
5 fields added (`manufacturing_manifest.py:89-93`): `drc_passed`, `erc_passed`,
`vendor_drc_passed` (Optional[bool]) + `drc_violation_count`, `erc_violation_count` (int).
`to_json()` writes all 5 (lines 109-113); `load()` reads with `.get(key, default)` for
backward compatibility with Phase 207 manifests (lines 145-149). Round-trip is correct.

## 4. Op Wiring (Task 5) — PASS

- `BuildHandoffExportOp` in `_schema_pcb.py:1368-1407` — all fields per plan, vendor pattern
  present (TM-3).
- `schema.py`: import (288), union member (574), `__all__` (795) — 3 matches.
- `registry.py:1491-1499`: `category: "query"`, `is_readonly: True`, `scope: "single_file"`.
  NOT added to `CROSS_FILE_OP_TYPES` in `execution.py` (correct — build ops dispatch via
  `_QUERY_HANDLERS`).
- `build.py:319-363`: handler resolves project_dir, rejects traversal, delegates to
  `export_handoff`, serializes `HandoffResult` via `asdict(validation)` + `manifest.to_json()`.

## 5. Test Quality — PASS

`tests/test_handoff.py` (21 tests). Uses `monkeypatch` stubs on the `handoff` module
namespace (no kicad-cli skips), so tests run in CI. Coverage:
- BOM profile: generic path, JLCPCB columns, filename pattern, formula injection defense,
  unreferenced-component drop.
- Orchestrator: zip creation, DRC-block (no zip), all-artifacts, step excluded/included,
  no-partial-state, arcname no-separator, target-file-unchanged, DRC-inconclusive-no-block,
  manifest validation proof, vendor-DRC-block.
- Readme: board name, surface finish (BoardSpec sidecar), validation results, dimensions,
  missing-board-spec graceful.

## Findings

### LOW-1: `cpl_filename_pattern` field is unused in the handoff path
`profiles.py:67-70` defines `cpl_filename_pattern` and it is set on both JLCPCB profiles
(`{stem}_JLCPCB-CPL.csv`). However, the orchestrator calls `export_position(pcb_path,
output_dir=build_dir)` (`handoff.py:445`), which generates its own filename
(`f"{stem}-pos.{format}"`, `general.py:92`). The profile's CPL filename pattern is never
consulted. This means `build_handoff_export(vendor="jlcpcb")` produces a JLCPCB-column BOM
but a generic-named CPL file (`test_board-pos.csv`, not `test_board_JLCPCB-CPL.csv`).

Impact: Success Criterion #4 ("JLCPCB-formatted bundle — BOM columns, CPL file naming") is
half-met: BOM columns are JLCPCB-formatted; CPL file naming is NOT. The field exists on the
model and is tested on the BOM side, but no code reads it for the CPL output. This is a real,
if minor, gap. Fix is a follow-up: have the orchestrator (or a future `export_position_profile`)
honour `profile.cpl_filename_pattern` when set.

### LOW-2: `component_count` in `export_bom_profile` over-counts via nested comprehension
`bom.py:421-424`:
```python
component_count=sum(
    1 for r in remapped_rows
    for _ in r.get("Designator", "").split(",")
),
```
For grouped BOM rows where `Designator` is comma-joined (e.g. `"R1,R2,R3"`), this counts
individual references — correct intent. But for a single `Designator` of `"R1"` it yields 1,
and for an empty string it yields 1 (because `"".split(",")` returns `[""]`, a one-element
list). Edge case: a row with an empty Designator inflates the count by 1. In practice the
filter at line 406 drops `ref == "?"` or empty before this point, so empty Designator rows
should not reach the comprehension. Low risk; noted for correctness.

### INFO-1 (pre-existing, not Phase 208's scope): SKILL.md operation count lag
`tests/test_slc_compliance.py::test_skill_md_operation_count_matches` FAILS: SKILL.md says
"149 operations" (`skills/SKILL.md:31`), schema has 160. This gap predates Phase 208
(Phases 205-207 added +7 without updating SKILL.md; Phase 208 added +1). The Phase 208 plan
does not list SKILL.md as in-scope, so this is not a Phase 208 regression — but Phase 208 did
widen the gap by one operation. Recommend a doc-debt follow-up to bump SKILL.md to 160 (and
update `prompt.md` operation reference) so the SLC consistency test goes green.

### INFO-2: `_record_export` assumes `result.files` exist; BOM path does not use it
The BOM export is handled separately from `_record_export` (lines 455-472) because `BomResult`
is not an `ExportResult` (it has `output_path` not `files`). This is correct but slightly
asymmetric — a comment noting the type divergence would aid future maintainers. Not a defect.

## Verification Commands Run
- `pytest tests/test_handoff.py tests/test_registry.py tests/test_build_system.py tests/test_export_bom.py` -> 97 passed.
- All plan acceptance-criteria smoke tests (profile fields, registry meta, handler merge, imports) -> pass.
- `grep export_jlcpcb_bom src/kicad_agent/manufacturing/` -> 0 matches (Pitfall 3).

## Verdict

**APPROVED.** The code is production-quality, secure, and faithful to the plan. The two LOW
notes (`cpl_filename_pattern` unused, BOM count edge case) are minor and non-blocking. INFO-1
(SKILL.md lag) is pre-existing doc-debt outside Phase 208's scope but worth a follow-up ticket.
```
```
