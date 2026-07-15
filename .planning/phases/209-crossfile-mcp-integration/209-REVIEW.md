---
phase: 209-crossfile-mcp-integration
plan: 01
role: code-reviewer
reviewed: 2026-07-10
verdict: PASS
---

# Phase 209 Code Review

**Reviewer:** ZCode (code-reviewer role)
**Files reviewed:** 7 source/test files + 1 requirements doc
**Verdict: PASS** — ship-ready. Three minor observations (all nits, none blocking).

## Files Reviewed

| File | Type | LOC Δ |
|------|------|-------|
| `src/volta/manufacturing/manufacturer_client.py` | new | +105 |
| `src/volta/cli.py` | modified | +223 |
| `src/volta/crossfile/project_context.py` | modified | +16 |
| `tests/test_manufacturer_client.py` | new | +104 |
| `tests/test_cli_integration.py` | new | +250 |
| `tests/test_mcp_tools.py` | new | +45 |
| `tests/test_crossfile_submodules.py` | modified | +32 |
| `.planning/REQUIREMENTS.md` | modified | INTEG-01..06 → [x] |

`git diff --stat 65d90e9..HEAD` confirms **zero** changes to `ops/registry.py`, `ops/schema.py`, `ops/handlers/`, or `mcp/edit_server.py` — INTEG-01 (verification-only) and INTEG-06 (registry unchanged) hold at the file level.

## 1. ManufacturerClient — interface-only ABC (PASS)

**TM-4 (import purity):** VERIFIED.
- `grep -c "import httpx\|import requests\|import urllib\|import aiohttp"` → 0
- Module imports only `abc`, `dataclasses`, `typing` (lines 17-21). `from __future__ import annotations` is correct.
- Import smoke prints `import-ok`; `ManufacturerClient()` raises `TypeError` (`abstract-ok`); all 3 dataclasses are frozen (`frozen-ok`).

**ABC shape:** 3 `@abstractmethod`s with docstring-only bodies — `quote(self, board_spec: Any, quantity: int = 1, **kwargs)`, `place_order(self, quote, **kwargs)`, `get_status(self, order_id)`. Signatures match the plan's CONTEXT spec exactly. Class docstring carries the Pitfall 8 quote-only scope guard. `board_spec: Any` is the right choice for an interface seed (no concrete spec coupling).

**Dataclasses (CR-01):** `Quote`, `OrderResult`, `OrderStatus` all `frozen=True` with documented fields and sensible defaults (`currency="USD"`, `notes=""`, `estimated_ship_date=""`, `tracking_number=""`, `last_updated=""`). Field order places required fields before defaulted ones — valid dataclass layout.

**Observation (nit, non-blocking):** The stub-subclass test (`test_manufacturer_client.py:86-104`) uses `# type: ignore[no-untyped-def]` on the method bodies. Acceptable for a test stub, but a production adapter in v7.1 should carry full type annotations.

## 2. CLI subcommands — existing pattern followed (PASS)

**Routing:** All 4 names registered in `_SUBCOMMANDS` (line 38) and `_SUBCOMMAND_DESCRIPTIONS` (lines 62-65); 4 `elif` branches wired in `main()` (lines 1457-1464). Registration verified: `subcommands-ok`.

**Handler pattern:** The implementer made a sound deviation from the plan's per-handler sketch by centralizing dispatch in a single `_dispatch_op_and_print(op, project_dir)` helper (lines 711-728). This is cleaner than the plan's repeated `handle_operation`/`format_result` boilerplate and still dispatches via `handle_operation` (NOT `_run_kicad_cli`) — satisfying the INTEG-02 contract. The helper:
- lazy-imports `handle_operation`, `format_result` (matches `_handle_route:454`),
- prints `format_result(result)` to stdout on success / stderr on failure,
- exits 0/1 (matches `_handle_route:453-461`).

**Nested subparsers:** `_handle_build` (create|list|show), `_handle_drc_vendor` (run|list), `_handle_board_metadata` (read|set-rev|set) all use `add_subparsers(dest="action", required=True)` — matches the `_handle_dfm` nested pattern. `_handle_handoff` is correctly flat (mirrors `_handle_drc`).

**TM-1 (missing-file guard):** Every handler taking `<pcb>` has `if not args.pcb.exists(): print(..., file=sys.stderr); sys.exit(1)` before dispatch — mirrors `_handle_drc:304-306`. Verified by `TestMissingFileGuard`.

**TM-2 (vendor injection):** Correctly deferred — the CLI passes `vendor` straight into the op dict; the op layer enforces `^[a-z0-9_]+$`. No CLI re-validation. Correct.

**TM-5 (title-block write-back):** `board-metadata set`/`set-rev` delegate to the hardened Phase 205 ops — no new write logic in the CLI. Correct.

**Op dict construction:** Spot-checked all 9 op_types built by the 4 handlers against the schema names: `build_handoff_export`, `build_create`, `build_list`, `build_show`, `drc_vendor`, `list_vendor_drc_profiles`, `read_board_metadata`, `set_board_metadata`, `set_board_revision`. All match. `include_step`, `vendor`, `build_id`, `rev`, `title`, `company`, `date` kwargs threaded correctly. `project_dir` derived from `args.pcb.parent` (project-scoped — supports INTEG-04).

**Observation (nit, non-blocking):** `_dispatch_op_and_print` wraps `project_dir` via `Path(project_dir) if project_dir else None` (line 723). `handle_operation` then does `Path(project_dir) if project_dir else Path.cwd()` (handler.py:134). Double-wrapping is harmless (Path(Path(x)) is idempotent) but slightly redundant.

## 3. ProjectContext — backward compatible (PASS)

**New fields:** `build_spec_files: list[Path] = field(default_factory=list)` and `builds_dir: Optional[Path] = None` added after `library_paths` with defaults — backward compatible. Existing `ProjectContext(...)` callers that omit them still work.

**Discovery:** In `discover_project()`, before the constructor call:
```python
build_spec_files = sorted(resolved_root.glob("**/*.kicad_build_spec.json"))
_builds_dir_path = resolved_root / "builds"
builds_dir = _builds_dir_path if _builds_dir_path.is_dir() else None
```
- `build_spec_files` uses the same `**/*` glob depth as the 5 existing file-type globs (TM-3 consistent).
- `builds_dir` is a **direct child** of `resolved_root` only — no upward walk (TM-3: respects the documented `_MAX_WALK_LEVELS=20` threat model). Project-scoped (INTEG-04).
- `is_dir()` check correctly returns `None` when absent (backward-compat path).

**Class docstring:** Updated to document both new fields (lines 38-43).

**Tests:** `tests/test_crossfile_submodules.py` extended with `test_discover_project_finds_build_spec_and_builds_dir` and `test_discover_project_no_builds_is_backward_compat` (both pass).

**Observation (nit, non-blocking):** The new fields are **discovery-only** — no consumer in `src/` reads `ctx.builds_dir` or `ctx.build_spec_files` yet (the CLI handlers derive `project_dir` from `args.pcb.parent`, not from `ProjectContext`). This is fine for Phase 209's goal (the discovery contract exists for future MCP/programmatic consumers and INTEG-03/04 compliance), but worth noting that the fields are currently write-mostly.

## 4. MCP auto-exposure — zero edit_server.py changes (PASS)

`grep -c "def _generate_operation_tools" src/volta/mcp/edit_server.py` is unchanged from pre-phase (1 match, unedited). The auto-generation reads the `Operation` discriminated union, so all 9 v7.0 ops surface as MCP tools for free.

Verification command prints `mcp-exposure-ok 163 tools total` (160 registered + 3 schema-only union variants). `tests/test_mcp_tools.py` locks this as a regression guard — asserts all 9 op_types present and `len(tools) >= 163`.

## 5. Tests — well-scoped, monkeypatch seam correct (PASS)

**`test_manufacturer_client.py`:** Import-purity via `sys.modules` **delta** (not global absence) — robust across full-suite runs where httpx may be loaded by other tests (sound deviation from a naive global-absence check). Frozen-dataclass, abstract-instantiation, and stub-subclass coverage all present.

**`test_cli_integration.py`:** Uses the in-process `main([...])` + `capsys` + `monkeypatch` pattern. The monkeypatch seam is **correct**: `_dispatch_op_and_print` does `from volta.handler import handle_operation` at call time, so patching `volta.handler.handle_operation` is the complete seam (the local re-import re-reads the patched module attribute). Verified empirically — all dispatch tests pass and assert the captured op dict's `op_type`, `target_file`, and key kwargs.

**`test_mcp_tools.py`:** Minimal regression guard, as the plan prescribed.

**Observation (nit, non-blocking):** In `TestNestedMissingArg`, `test_build_no_action_prints_help` calls `capsys.readouterr()` twice on one line (line 81: `.out + capsys.readouterr().err`) — the second call returns empty since the first already drained the buffer. Harmless (the test only asserts `exc.value.code != 0`), but the dead `readouterr()` call is sloppy.

## Security

No new attack surface beyond what the threat model anticipated. TM-1 through TM-5 all mitigated as planned. No network imports. No `eval`/`exec`/`subprocess` added. Path traversal remains the op executor's responsibility (correctly not re-implemented in the CLI).

## SLC Compliance

- **Self-contained:** ManufacturerClient module is pure-stdlib. CLI handlers reuse the existing op-executor path. No new dependencies.
- **Limited:** No scope creep — Pitfall 8 honored (no adapter implementations). The `fastlane/Fastfile` change in the diff (`-skipMacroValidation -skipPackagePluginValidation`) is unrelated to Phase 209 (Xcode build-config tweak from a prior commit `ce4113a`, not part of the 5 task commits) — flagged but not a phase defect.
- **Correct:** All 31 new tests pass; all 45 crossfile/registry tests pass; all 12 existing CLI tests pass.

## Verdict

**PASS.** Code is clean, follows existing idioms, centralizes dispatch in a reusable helper, and honors all 5 threat-model mitigations. The three nits (test-stub type ignores, double Path wrap, dead readouterr) are non-blocking polish items. Ship it.
