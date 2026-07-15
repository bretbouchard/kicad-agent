# Phase 209 — Council of Ricks Plan Review

**Phase:** 209 — Crossfile + MCP Integration (FINAL active phase of v7.0)
**Plan reviewed:** `209-01-PLAN.md`
**Review type:** Plan review (pre-execution)
**Reviewed:** 2026-07-10
**Reviewer:** Council of Ricks (plan-reviewer seat)
**Verdict:** APPROVE

---

## Executive Summary

Phase 209 is the integration capstone of v7.0 — it wires the operations from
Phases 205-208 into MCP (verification-only, no code change) and CLI (4 new
subcommands), extends `ProjectContext` to discover `builds/` + sidecars
(backward-compatible), and defines the `ManufacturerClient` ABC as the interface
seed for v7.1. The plan is unusually disciplined about scope: it adds **zero
operations, zero handlers, zero schema changes, zero MCP code edits**. Every
"new" thing is either a thin wrapper over already-shipped logic or an
interface-only seed. After this phase the v7.0 milestone is complete (Phase 210
is DEFERRED to v7.1).

The plan's core claims were **all verified against live code** at review time:

- `_generate_operation_tools()` is verification-only — it reads the `Operation`
  union and emits one tool per variant. All 9 target op_types are already
  present (163/163 tools, 9/9 required present). No edit to `edit_server.py`
  needed. (CONFIRMED)
- `OPERATION_REGISTRY` count is 160 and `validate_registry_completeness()`
  passes with exactly the 3 pre-existing missing ops. Phase 209 adds 0 ops.
  (CONFIRMED — count asserted in `tests/test_registry.py:25` at `== 160`)
- Both `DrcVendorOp.vendor` and `BuildHandoffExportOp.vendor` enforce
  `pattern=r"^[a-z0-9_]+$"` (`_schema_pcb.py:1258`, `:1389`). TM-2's "reuse,
  don't re-validate in CLI" claim is sound. (CONFIRMED)
- `ProjectContext` is a frozen dataclass with all defaulted fields — adding 2
  defaulted fields is backward-compatible. (CONFIRMED at
  `project_context.py:26`)
- The `_handle_route` lazy-import + `handle_operation` dispatch pattern exists
  (`cli.py:450`), and the missing-file guard exists at `_handle_drc:300`.
  (CONFIRMED)
- Target files `manufacturer_client.py`, `test_manufacturer_client.py`,
  `test_cli_integration.py` do NOT exist yet. (CONFIRMED)
- The `DfmCheck(ABC)` idiom exists (`checker.py:99`) as the referenced analog.
  (CONFIRMED)

Requirement coverage is complete (all 6 INTEG requirements map to must_haves
and tasks). The threat model is thorough (5 entries) and each maps to a task.
The Pitfall 8 quote-only scope guard is baked into the `ManufacturerClient`
docstring as specified. The plan correctly resists the IP-1/IP-3 scope creep by
noting the registry count and handler merges were already done in Phases
205-208.

There are **no blocking issues**. Findings are 4 LOW (minor consistency nits)
and 3 INFO (observations). The plan is ready for execution.

---

## Severity Summary

| Severity | Count | Meaning |
|----------|-------|---------|
| CRITICAL | 0 | Blocks execution — must fix before plan approval |
| HIGH | 0 | Will cause test failures or incorrect behavior if not addressed |
| MEDIUM | 0 | Should address during execution; non-blocking but worth fixing |
| LOW | 4 | Minor inconsistencies / suggestions; accept or defer |
| INFO | 3 | Observations for awareness; no action required |

---

## Role 1: Plan Checker Results

| # | Check | Result | Notes |
|---|-------|--------|-------|
| 1 | All 6 INTEG requirements in plan frontmatter AND addressed by tasks | PASS | Frontmatter lists INTEG-01..06. Must Haves 1-7 map to all 6 (MH-6 covers INTEG-06; MH-7 covers backward-compat, an IP-3-class concern). Task headers cite requirements. Full traceability matrix below. |
| 2 | must_haves align with ROADMAP success criteria | PASS | MH-1 ↔ ROADMAP SC-1 (MCP+CLI exposure); MH-2,3,4 ↔ SC-2 (ProjectContext discovers builds/sidecars); MH-5 ↔ SC-3 (ManufacturerClient ABC, no network deps); MH-6 ↔ SC-4 (registry count + completeness). All 4 ROADMAP success criteria covered. |
| 3 | MCP auto-exposure is verification-only (no `edit_server.py` edit) | PASS | Task 4 action step 1: "NO code change to `edit_server.py`". Acceptance criterion greps `def _generate_operation_tools` and asserts count unchanged. Live-verified: function reads the union via `get_args(ann)` (`edit_server.py:133-136`); all 9 ops present in 163 tools. INTEG-01 is genuinely free. |
| 4 | Registry count stays 160 (no new ops) | PASS | Live-verified: `len(OPERATION_REGISTRY) == 160`, `validate_registry_completeness()` missing == the 3 pre-existing ops. Task 4 action step 2 asserts count == 160 and the exact 3 known-missing. `tests/test_registry.py:25` already at `== 160`. Arithmetic consistent — Phase 209 adds 0 ops. |
| 5 | ManufacturerClient ABC is interface-only (no network imports, abstract) | PASS | Task 1 action step 2 restricts imports to `abc`, `dataclasses`, `typing`. Acceptance criteria assert no network modules in `sys.modules` after import (TM-4) and that `ManufacturerClient()` raises `TypeError`. `grep` assertion returns 0 for `httpx\|requests\|urllib\|aiohttp`. Live-verified: `dfm/checker.py:99` is the established ABC analog. |
| 6 | CLI subcommands follow existing patterns (operation-dispatch, not kicad-cli passthrough) | PASS | Task 3 action step 3 specifies `handle_operation` dispatch (the `_handle_route:443` pattern), NOT `_run_kicad_cli`. Acceptance criterion greps `handle_operation` >= 4 new matches and asserts `_run_kicad_cli` count does not increase. Live-verified: `_handle_route:450` does the lazy `from volta.handler import handle_operation, format_result` inside the function body, exactly as Task 3 prescribes. |
| 7 | ProjectContext extension is backward-compatible (defaulted fields) | PASS | Task 2 action step 1 adds `build_spec_files: list[Path] = field(default_factory=list)` and `builds_dir: Optional[Path] = None` — both defaulted. Live-verified: `ProjectContext` is `@dataclass(frozen=True)` with all-optional fields after the required two (`project_context.py:26`). Existing `ProjectContext(...)` keyword construction at `:123-131` omits these and will continue to work. New test `test_discover_project_no_builds_is_backward_compat` asserts the no-builds path returns `[]`/`None`. |
| 8 | Pitfall 8 quote-only guard baked into docstring | PASS | Task 1 action step 4 + CONTEXT lines 106-113 specify the class docstring text: "Scope guard (Pitfall 8): If activated, scope to QUOTE ONLY first — quoting is read-only and safe; ordering has financial consequences." Matches PITFALLS.md Pitfall 8 prevention verbatim. Also notes "Implementations are Phase 210 (DEFERRED to v7.1)". |
| 9 | Every task has read_first + acceptance_criteria | PASS | Tasks 1-5 each have `<read_first>` and `<acceptance_criteria>` sections. |
| 10 | threat_model present and each TM maps to a task | PASS | 5-entry threat model table (TM-1 through TM-5) at plan top. TM-1/TM-5 → Task 3; TM-2 → Task 3 (reuse vendor pattern); TM-3 → Task 2 (reuse existing glob depth, no upward walk); TM-4 → Task 1 (no network imports). All 5 traceable. |

**Plan Checker Verdict: VERIFICATION PASSED** (10/10 checks pass).

---

## Role 2: Council of Ricks Plan Review

### Requirement Coverage (Traceability Matrix)

| REQ-ID | Must Have | Task(s) | Status |
|--------|-----------|---------|--------|
| INTEG-01 | MH-1 | Task 4 (MCP verification, no code change) | Covered |
| INTEG-02 | MH-2 | Task 3 (4 CLI subcommands + routing) | Covered |
| INTEG-03 | MH-3 | Task 2 (build_spec_files + discover_project) | Covered |
| INTEG-04 | MH-4 | Task 2 (builds_dir resolves to project root child) | Covered |
| INTEG-05 | MH-5 | Task 1 (ManufacturerClient ABC, interface-only) | Covered |
| INTEG-06 | MH-6 | Task 4 (registry count 160 + completeness verified) | Covered |
| (backward-compat) | MH-7 | Task 2 (defaulted fields + backward-compat test) | Covered |

All 6 INTEG requirements have a clear must_have, task, and acceptance criteria
chain. No orphan requirements. No orphan tasks. MH-7 (backward compatibility)
is a bonus guard beyond the 6 requirements — good defensive practice.

---

### SLC (Single Level of Correctness) Compliance

**Score: STRONG.**

1. **Single MCP tool source.** `_generate_operation_tools()` is the one and only
   place MCP tools are defined. Phase 209 does not add a parallel/competing
   manual wiring. The verification task (Task 4) asserts against the output of
   that single function. No second list of "MCP tool names" exists.
2. **Single registry source.** `OPERATION_REGISTRY` is the one source; the test
   asserts the derived count. Phase 209 adds nothing, so no drift is possible.
3. **Single vendor-validation layer.** The `pattern=r"^[a-z0-9_]+$"` lives on
   the op schema (`DrcVendorOp`, `BuildHandoffExportOp`). The CLI deliberately
   does NOT re-validate (Task 3 / TM-2). This is the correct SLC choice —
   validation lives at the schema, not duplicated in the CLI wrapper.
4. **Single path-sanitization layer.** The op-executor's `target_file`
   resolution (T-06 series) is reused. The CLI adds only a missing-file guard,
   not a second sanitization pass (TM-1). Correct — no defense-in-depth
   duplication that could drift.
5. **Single discovery glob.** `discover_project()` already globs 5 file types
   with `**/*.<ext>`. Task 2 adds the build-spec glob using the identical
   pattern, immediately before the constructor. No second discovery path.

**Minor SLC risk (LOW):** Task 4 action step 3 offers an *optional* new
`tests/test_mcp_tools.py` regression test. This is good (it locks the
auto-exposure contract against future union drift), but the plan leaves the
location ambiguous ("`tests/test_cli_integration.py` (or a focused
`tests/test_mcp_tools.py`)"). Pick one at execution time to avoid two test
files both asserting the same 9 op_types. (FINDING-1)

---

### Security Review

**Score: STRONG.** The threat model is tight, and every mitigation is a
"reuse the existing layer" decision rather than a new defense — which is the
right call for an integration phase.

#### Path traversal via CLI `<pcb>` positional (TM-1) — MITIGATED
The plan correctly does NOT add a new path-sanitization layer. The existing
op-executor `target_file` resolution (T-06 series) already applies. The CLI
adds only a missing-file guard mirroring `_handle_drc:300` (live-verified:
that exact guard exists at `cli.py:300-302`). The guard prints to stderr +
`sys.exit(1)`. Reuse over re-implementation. Good.

#### Vendor/profile name injection (TM-2) — MITIGATED
TM-2's claim is fully verified: both `DrcVendorOp.vendor` (`_schema_pcb.py:1258`)
and `BuildHandoffExportOp.vendor` (`:1389`) enforce `pattern=r"^[a-z0-9_]+$"`.
The CLI passes `vendor` straight into the op dict and lets the schema reject
bad input. `vendor="../../etc/passwd"` is rejected by the regex (slashes/dots
not in `[a-z0-9_]`) before it reaches any path resolution. The plan's
"reuse; do not re-validate in CLI" instruction is the correct SLC + security
posture.

#### Unbounded glob / traversal DoS (TM-3) — MITIGATED
Task 2 reuses the existing `resolved_root.glob("**/*.kicad_build_spec.json")`
pattern — identical depth to the 5 existing globs in `discover_project`. No
upward walk is added; `builds_dir` is a direct child of the resolved root only
(`resolved_root / "builds"`). Consistent with the documented
`_MAX_WALK_LEVELS=20` threat model in `project_context.py:7-11` (live-verified).

#### ABC import side-effects (TM-4) — MITIGATED
Task 1 restricts imports to `abc`, `dataclasses`, `typing`. Acceptance
criterion asserts `'httpx' not in sys.modules and 'requests' not in
sys.modules` after import. This is a strong, executable check. Importing the
module is a pure-Python no-op, satisfying INTEG-05's "no network libraries or
credentials" clause.

#### Title-block corruption on write-back (TM-5) — MITIGATED
The CLI delegates to the already-hardened `set_board_metadata` /
`set_board_revision` ops (Phase 205 round-trip-validated). No new write logic
in the CLI. Correct reuse.

**Council note (INFO):** The threat model has no entry for the `_handle_drc_vendor
--list` path, which does not take a `<pcb>` and calls `list_vendor_drc_profiles`.
This path is lower-risk (no path input, no write) but the op still requires a
`target_file` per its schema. The plan's Task 3 action for `_handle_drc_vendor`
should ensure the `--list` form supplies a `target_file` (e.g., the dummy or the
project's pcb) as the dispatch layer expects, or document that the handler
ignores `ir` (which the `ListVendorDrcProfilesOp` docstring confirms it does).
Minor — handle during execution. (OBSERVATION-1)

---

### Architectural Soundness

**Score: STRONG.**

#### MCP auto-exposure — CORRECT, genuinely free
The plan correctly identifies INTEG-01 as a verification-only task. The
auto-generation design (`_generate_operation_tools` reading the union via
`get_args`) means every op added in Phases 205-208 is already an MCP tool.
Live-verified: 163 tools, all 9 required present. Task 4 makes the "free win"
explicit and adds an optional regression test. This is the cleanest possible
integration — zero MCP code, zero risk of MCP/registry drift.

#### ManufacturerClient ABC — CORRECT, correctly deferred
The ABC follows the established `DfmCheck(ABC)` idiom (`checker.py:99`).
The 3 abstractmethods + 3 frozen dataclasses match CONTEXT exactly. The
quote-only scope guard (Pitfall 8) is in the docstring. No adapter
implementations — Pitfall 8 scope-creep is structurally prevented (there is
nothing to creep into). This seeds the v7.1 contract without committing to it.

#### CLI subcommands — CORRECT pattern choice
The plan correctly distinguishes the two existing handler patterns and chooses
operation-dispatch (the `_handle_route` / `_handle_review_schematic` pattern)
over kicad-cli passthrough. The new subcommands wrap native volta ops,
not the KiCad binary, so `handle_operation` + `format_result` is right. The
nested-subcommand structure (`build create|list|show`, `board-metadata
read|set-rev|set`) mirrors `_handle_dfm`'s `add_subparsers` usage. Lazy import
inside each handler body matches `_handle_route:450`.

#### ProjectContext extension — CORRECT, minimal
Two defaulted fields on a frozen dataclass is the least-invasive extension.
The glob reuse + direct-child `builds_dir` keeps the discovery surface
identical to the existing 5 globs. Backward compatibility is structurally
guaranteed (defaults) AND explicitly tested
(`test_discover_project_no_builds_is_backward_compat`).

#### Registry/schema/handler discipline — CORRECT
The plan correctly recognizes that IP-1 (count assertion), IP-2 (schema union
drift), and IP-3 (handler merge) were all already satisfied by Phases 205-208.
Phase 209 adds 0 ops, so the count stays 160, the union stays in sync, and no
handler merge is needed. The acceptance criteria assert the end state rather
than re-doing the work. This is the right read of the codebase.

#### "Final phase" claim — VERIFIED
With Phase 210 explicitly DEFERRED to v7.1 (ROADMAP line 20, REQUIREMENTS line
79), Phase 209 is genuinely the final active phase. On completion: all 40
active requirements (META-01..07, DRC-01..08, BUILD-01..10, HANDOFF-01..09,
INTEG-01..06) are satisfied, the registry is at 160 with completeness passing,
MCP exposes all v7.0 ops, the CLI exposes all v7.0 ops, and the v7.1 adapter
contract is seeded. The milestone is complete. (Task 5 marks INTEG-01..06 to
`[x]` as the final gate step.)

---

### Missing Edge Cases

The plan is an integration phase with no new logic, so the edge-case surface is
small. A few worth flagging:

1. **`builds_dir` as a symlink:** TM-3 addresses unbounded glob / upward
   traversal but does not address the case where `builds/` itself is a symlink
   pointing outside the project root. `_builds_dir_path.is_dir()` follows
   symlinks, so `builds_dir` would resolve to a target outside the project.
   This is low-risk (the field is informational; build ops resolve
   `project_dir` independently and reject `..`), but worth a one-line comment
   or `is_dir(follow_symlinks=False)` consideration. **(LOW — see FINDING-2)**

2. **`board-metadata set` with no flags:** `_handle_board_metadata` `set <pcb>`
   with no `--title/--company/--date` constructs a `set_board_metadata` op with
   all-optional fields unset. The op should either no-op cleanly or error. The
   plan does not specify this case. **(LOW — handle during execution: argparse
   `required` group or a "nothing to set" guard.)**

3. **`build show` / `build list` project_dir derivation:** Task 3 derives
   `project_dir` from `args.pcb.parent`. If the `.kicad_pcb` is nested below
   the project root (common in multi-board projects), `pcb.parent` is not the
   project root. The build ops use `project_dir` to locate `builds/`. This
   could point to the wrong directory. The existing `build_create` handler uses
   `_resolve_project_dir` (build.py) which handles this; the CLI should pass
   `project_dir=str(args.pcb.parent)` and let the op layer resolve, OR use
   `detect_project_root`. The plan's choice (pass `pcb.parent`) is acceptable
   IF the op layer re-resolves, but this should be confirmed. **(LOW — see
   FINDING-3)**

4. **Concurrent CLI invocations writing metadata:** `board-metadata set-rev`
   writes the `.kicad_pcb`. Two concurrent invocations on the same board could
   race. This is pre-existing behavior (the op is Phase 205), not new to 209,
   so it is out of scope. **(Already pre-existing — no action.)**

---

## Findings Detail

### FINDING-1 (LOW): Ambiguous location for the MCP-exposure regression test

**Where:** Task 4, action step 3.
**Issue:** The optional regression test location is given as
"`tests/test_cli_integration.py` (or a focused `tests/test_mcp_tools.py`)".
Leaving this ambiguous risks two test files both asserting the same 9 op_types,
or neither being created.
**Impact:** Low — SLC nit. Either location works; the test itself is optional
regression protection.
**Fix:** Pick one at execution time. Recommend `tests/test_mcp_tools.py` (the
MCP-exposure concern is distinct from CLI integration; separate file aids
future grep-ability). If deferred entirely, the inline `.venv/bin/python -c`
check in the acceptance criteria is still a valid gate.

### FINDING-2 (LOW): `builds_dir` symlink-following not addressed

**Where:** Task 2, action step 3 / TM-3.
**Issue:** `_builds_dir_path.is_dir()` follows symlinks. A `builds/` symlink
pointing outside the project root would make `builds_dir` resolve externally.
**Impact:** Low — `builds_dir` is informational; build ops independently
validate `project_dir` and reject `..`. No write occurs through this field.
**Fix:** Either use `is_dir(follow_symlinks=False)` (Python 3.12+) or add a
one-line comment that `builds_dir` is informational and ops re-resolve. Not a
blocker.

### FINDING-3 (LOW): `project_dir` derivation from `pcb.parent` for nested PCBs

**Where:** Task 3, `_handle_build` / `_handle_drc_vendor` / `_handle_handoff`.
**Issue:** The plan derives `project_dir` from `args.pcb.parent`. For a PCB
nested below the project root, this is the PCB's directory, not the project
root. Build/handoff ops use `project_dir` to locate `builds/`.
**Impact:** Low-moderate — could cause `build list`/`build show` to look in the
wrong directory for a nested PCB. However, the op layer (`_resolve_project_dir`
in build.py) may re-resolve, in which case the CLI's `project_dir` is
overridden.
**Fix:** Confirm whether the build/handoff op handlers re-resolve
`project_dir` via `detect_project_root` when given a non-root directory. If
they do, no change needed. If they don't, the CLI should call
`detect_project_root(args.pcb)` instead of `args.pcb.parent`. Verify during
execution.

### FINDING-4 (LOW): Abstractmethod body convention (`...` vs docstring-only)

**Where:** Task 1, action step 5.
**Issue:** Task 1 says "Each method body is a docstring only (no
implementation)." The codebase's established ABC analogs use a docstring
followed by `...` as the body (`DfmCheck.check` at `checker.py:129` ends with
`...`). "Docstring only" without `...` is valid Python (a bare docstring is a
valid statement) but diverges from the referenced analog.
**Impact:** Negligible — both are functionally equivalent (abstract methods
can't be instantiated). Pure style consistency.
**Fix:** Follow the `DfmCheck` idiom exactly: docstring + `...` body. One-line
alignment with the codebase convention.

### OBSERVATION-1 (INFO): `_handle_drc_vendor --list` target_file handling

**Where:** Task 3, `_handle_drc_vendor`.
**Issue:** The `--list` form does not take a `<pcb>` positional but
`ListVendorDrcProfilesOp` requires a `target_file` per its schema (required by
query dispatch, though the handler ignores `ir`).
**Impact:** None operationally if the handler ignores `ir`, but the CLI must
still construct a valid op dict with a `target_file` field, or dispatch will
reject it before the handler runs.
**Action:** Ensure the `--list` form supplies a `target_file` (e.g., a dummy
path, or require a `<pcb>` even for `--list`). Confirm during execution.

### OBSERVATION-2 (INFO): ROADMAP "Key work" list includes items already done

**Where:** ROADMAP.md Phase 209 "Key work" bullets (lines 165-167).
**Issue:** The ROADMAP still lists "Update `tests/test_registry.py:26` count
assertion (currently `== 142`)" and "Merge `_MANUFACTURING_HANDLERS`" as 209
work items. Both were completed in Phases 205-208 (the count is already 160;
handlers are already merged). The plan correctly treats these as verification
rather than work, but the ROADMAP text is stale.
**Impact:** None for execution — the plan is correct. Documentation drift only.
**Action:** No 209 blocker. The ROADMAP "Key work" list could be reconciled
with reality post-milestone.

### OBSERVATION-3 (INFO): This is genuinely the final active phase

**Where:** ROADMAP dependency graph + Phase 210 status.
**Issue:** (None — confirmation.) Phase 210 is explicitly DEFERRED to v7.1
(ROADMAP line 20, REQUIREMENTS "Out of Scope" line 79). All 40 active
requirements map to Phases 205-209. On Phase 209 completion, v7.0 is done.
**Action:** None. Confirmed.

---

## SLC Compliance Checklist

- [x] Single MCP tool source (`_generate_operation_tools`) — no parallel wiring (Task 4)
- [x] Single registry source — Phase 209 adds 0 ops, count derived (Task 4)
- [x] Single vendor-validation layer — schema `pattern`, CLI does not re-validate (TM-2)
- [x] Single path-sanitization layer — op executor reused, CLI adds only missing-file guard (TM-1)
- [x] Single discovery glob pattern — build-spec glob mirrors existing 5 globs (Task 2)
- [x] `handle_operation`/`format_result` reused (not reimplemented) from `_handle_route`
- [~] MCP regression test location ambiguous (FINDING-1, LOW)

## Security Checklist

- [x] Path traversal via `<pcb>` reuses executor guards, CLI adds missing-file guard (TM-1)
- [x] Vendor/profile name injection prevented by schema regex (TM-2, verified live)
- [x] Unbounded glob / traversal DoS avoided — reuse existing glob depth, no upward walk (TM-3)
- [x] ABC import is a pure-Python no-op — no network modules (TM-4, asserted in tests)
- [x] Title-block write-back delegated to hardened Phase 205 ops (TM-5)
- [~] `builds_dir` symlink-following not addressed (FINDING-2, LOW)
- [~] `_handle_drc_vendor --list` target_file handling unspecified (OBSERVATION-1, INFO)

## Requirement Coverage Checklist

- [x] INTEG-01 (MCP auto-exposure — verification only, no edit to edit_server.py)
- [x] INTEG-02 (4 CLI subcommands: build, handoff, drc-vendor, board-metadata)
- [x] INTEG-03 (ProjectContext discovers build_spec_files + builds_dir)
- [x] INTEG-04 (builds_dir is project-scoped — direct child of project root)
- [x] INTEG-05 (ManufacturerClient ABC, interface-only, no network deps)
- [x] INTEG-06 (registry count 160 + validate_registry_completeness pass)

## Pitfall Coverage Checklist

- [x] Pitfall 8 (API adapter scope creep) — ABC is interface-only; quote-only guard in docstring; Phase 210 DEFERRED
- [x] IP-1 (registry count) — already 160; verification only, no edit
- [x] IP-2 (schema union drift) — Phase 209 adds 0 ops; union stays in sync
- [x] IP-3 (handler merge) — already merged in Phases 205-208; no new module
- [x] IP-4 (CROSS_FILE_OP_TYPES) — not applicable (Phase 209 adds no ops)

---

## Verdicts

### Plan Checker Verdict: VERIFICATION PASSED

All 10 automated checks pass. MCP auto-exposure is genuinely verification-only
(live-confirmed). Registry arithmetic is correct (160, +0 ops). The
ManufacturerClient ABC is interface-only with no network imports. CLI handlers
use the operation-dispatch pattern. ProjectContext extension is
backward-compatible. The Pitfall 8 quote-only guard is in the docstring. All
target files are confirmed absent; all referenced analogs are confirmed
present.

### Council Verdict: APPROVE

This is a disciplined, well-scoped integration plan. Its central virtue is
restraint: it adds zero operations, zero handlers, zero schema changes, and
zero MCP code, choosing instead to wire, verify, and seed. Every architectural
decision is a "reuse the existing layer" choice — the auto-generating MCP tool
factory, the schema-layer vendor validation, the op-executor path guards, the
frozen-dataclass extension, the established ABC idiom. This minimizes the risk
surface of what is, by design, a capstone phase.

All load-bearing claims were verified against live code at review time and
hold. Requirement coverage (INTEG-01..06) is complete with full traceability.
The threat model is thorough and each entry maps to a task. The security
posture is strong. The plan correctly identifies Phase 209 as the final active
phase of v7.0 and structures Task 5 to mark the milestone complete.

The four LOW findings (MCP test location ambiguity, builds_dir symlink,
project_dir derivation for nested PCBs, abstractmethod `...` convention) are
minor consistency/robustness nits addressable during execution without
re-planning. The three INFO observations (drc-vendor --list target_file,
stale ROADMAP key-work bullets, final-phase confirmation) require no action.

**Conditions (non-blocking, address during execution):**
1. Pick a single location for the MCP-exposure regression test (FINDING-1).
2. Decide on `builds_dir` symlink handling — comment or `follow_symlinks=False` (FINDING-2).
3. Confirm whether build/handoff op handlers re-resolve `project_dir`; if not, use `detect_project_root(args.pcb)` in the CLI (FINDING-3).
4. Follow the `DfmCheck` `docstring + ...` body idiom in the ABC (FINDING-4).

**Recommendation:** Proceed to execution. This plan is ready, and on its
completion the v7.0 milestone is done.

---

*Review by: Council of Ricks (plan-reviewer seat)*
*Date: 2026-07-10*
