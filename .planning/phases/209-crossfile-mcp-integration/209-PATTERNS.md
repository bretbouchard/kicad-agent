# Phase 209 Pattern Map — Files to Codebase Analogs

**Status:** Complete
**Purpose:** Map every Phase 209 file (CREATE/MODIFY) to its closest proven analog in the codebase, so implementation follows established conventions rather than inventing new ones.

## CREATE: `src/volta/manufacturing/manufacturer_client.py`

**Closest analogs:**
- `src/volta/dfm/checker.py:99` — `DfmCheck(ABC)` with `@abstractmethod`. Class-level docstring, typed method signatures, abstract method only (no implementation body beyond docstring).
- `src/volta/analysis/design_rules.py:102` — `DesignRule(ABC)`. Second ABC reference for the same idiom.
- `src/volta/manufacturing/board_spec.py` — frozen dataclass in the same target package (`manufacturing/`). Use as the frozen-dataclass model for `Quote`/`OrderResult`/`OrderStatus`.

**What to copy:**
- ABC declaration: `class ManufacturerClient(ABC):` with module + class docstrings.
- `@abstractmethod` on `quote()`, `place_order()`, `get_status()` (3 methods, matching CONTEXT spec).
- 3 supporting `@dataclass(frozen=True)` value objects with type hints + defaults (CR-01 frozen convention, matching `BoardSpec`).

**What NOT to copy:** No subclass implementations, no `httpx`/`requests` imports (interface-only — INTEG-05, Pitfall 8). The module must import with zero network deps.

**Diff from analog:** `DfmCheck` carries class attributes (`name`, `description`); `ManufacturerClient` does not need them — it is a pure method interface. Methods return the new frozen dataclasses, not `list[DfmFinding]`.

---

## CREATE: `tests/test_manufacturer_client.py`

**Closest analogs:**
- `tests/test_crossfile_submodules.py:41` — `TestProjectContextModule` shows the "import smoke + interface-shape" test style used for new modules.
- Any ABC test that asserts `abstractmethod` enforcement via `pytest.raises(TypeError)` on direct instantiation.

**What to test:**
1. Import smoke: `from volta.manufacturing.manufacturer_client import ManufacturerClient, Quote, OrderResult, OrderStatus` succeeds with no network imports.
2. The 3 dataclasses are frozen (`Quote(...)` constructs; `dataclasses.fields(Quote)` shows `frozen=True`).
3. `ManufacturerClient` cannot be instantiated directly (`pytest.raises(TypeError)` — abstractmethods unimplemented).
4. A trivial stub subclass implementing all 3 methods CAN be instantiated and returns the right types.

**Pattern:** pytest classes, no fixtures beyond `tmp_path` if needed. Mirror the lightweight import-and-assert style of `test_crossfile_submodules.py`.

---

## CREATE: `tests/test_cli_integration.py`

**Closest analogs:**
- `tests/test_cli.py:171` — `test_analyze_subcommand_calls_generate_analysis(tmp_path, capsys)` calls `main(["analyze", str(pcb_file)])` in-process and inspects `capsys`. **This is the exact pattern** — invoke `main([...])`, assert exit/behavior.
- `tests/test_cli.py:42` — `_run(*args)` subprocess helper for end-to-end CLI invocation (use for the "unknown subcommand errors" and `--help` tests).

**What to test:**
1. The 4 new subcommand names are present in `_SUBCOMMANDS` and route (no "Unknown command" error).
2. `build`/`drc-vendor`/`board-metadata` nested subcommands (create/list/show; vendor/list; read/set-rev/set) parse correctly — at minimum that a missing required arg prints help + exits non-zero (matching `_handle_dfm` `sys.exit(2)` on no `func`).
3. `handoff <pcb>` constructs the right op and dispatches (mock `handle_operation` via `monkeypatch` on `volta.cli.handle_operation` to avoid needing a real KiCad install).
4. JSON output goes to stdout on success, errors to stderr (matching `_handle_route`'s `format_result(result), file=sys.stderr`).

**Pattern:** prefer in-process `main([...])` + `monkeypatch` + `capsys` for unit-level coverage; reserve subprocess `_run` for routing/help smoke tests. Do NOT invoke real `kicad-cli` or real operations — `handle_operation` is the seam to mock.

---

## MODIFY: `src/volta/cli.py`

**Closest analogs:**
- **Routing** — `main()` at `cli.py:1204` + `_SUBCOMMANDS` set at `cli.py:38`. Add `"build", "handoff", "drc-vendor", "board-metadata"` to the set and 4 `elif` branches (lines ~1242+).
- **Nested-subcommand handler** — `_handle_dfm` at `cli.py:688` (uses `parser.add_subparsers()` + delegated register function). Use this shape for `build`, `drc-vendor`, `board-metadata` (which have sub-actions).
- **Operation-dispatch handler** — `_handle_route` at `cli.py:443` and `_handle_review_schematic` at `cli.py:755` (build op dict → `handle_operation(op_json)` → `format_result`). **This is the dispatch mechanism for all 4 new handlers**, since they wrap volta operations, not the KiCad binary.
- **Flat handler** — `_handle_drc` at `cli.py:290` (argparse + single action). Use this shape for `handoff` (no sub-actions).

**Exact changes:**
1. Line 38 `_SUBCOMMANDS`: add the 4 names.
2. Line ~49 `_SUBCOMMAND_DESCRIPTIONS`: add 4 one-line descriptions (existing dict pattern).
3. Add 4 functions: `_handle_build`, `_handle_handoff`, `_handle_drc_vendor`, `_handle_board_metadata` (place near `_handle_dfm`, ~line 706).
4. In `main()` elif chain (~line 1242): add 4 branches routing to the handlers.

**Diff from analog:** `_handle_dfm` delegates to `dfm_command(args)` from a separate `dfm/cli.py`. The new handlers stay inline in `cli.py` and dispatch via `handle_operation` (no separate command module) — simpler, because the operation layer already does the work.

---

## MODIFY: `src/volta/crossfile/project_context.py`

**Closest analog:** itself — `ProjectContext` dataclass (`project_context.py:27`) and `discover_project()` (`project_context.py:85`). This is an additive extension of an existing file, so the analog is the file's own conventions.

**Exact changes:**
1. Lines 40-46 (dataclass body): add 2 fields after `library_paths`:
   ```python
   build_spec_files: list[Path] = field(default_factory=list)
   builds_dir: Optional[Path] = None
   ```
2. Update the class docstring (lines 28-38) to document the two new attributes.
3. In `discover_project()`, before the `return ProjectContext(...)` at line 123, add discovery:
   ```python
   build_spec_files = sorted(resolved_root.glob("**/*.kicad_build_spec.json"))
   builds_dir_path = resolved_root / "builds"
   builds_dir = builds_dir_path if builds_dir_path.is_dir() else None
   ```
4. Pass `build_spec_files=build_spec_files, builds_dir=builds_dir` into the constructor at line 123.

**Backward-compat guarantee:** Both new fields have defaults (`field(default_factory=list)` / `None`). The existing constructor call uses keyword args, and any external `ProjectContext(...)` construction that omits the new fields still works unchanged. Frozen dataclass permits additive defaulted fields.

**Diff from analog:** None — pure additive extension following the file's own glob-and-construct pattern.

---

## MODIFY: `tests/test_crossfile_submodules.py` (NOT test_project_context.py)

**Rationale:** `tests/test_project_context.py` does NOT exist. ProjectContext tests live in `tests/test_crossfile_submodules.py:41` (`TestProjectContextModule`, including a real-project `discover_project` test at line 56) and `tests/test_crossfile_coverage.py`. Extend the existing submodules file rather than create a new one.

**Closest analog:** `TestProjectContextModule.test_discover_project` at `test_crossfile_submodules.py:56` — builds a tiny fake KiCad project in `tmp_path`, calls `discover_project`, asserts returned fields.

**What to add:**
1. A test that creates a `builds/` dir + a `.kicad_build_spec.json` sidecar in the fake project and asserts `ctx.build_spec_files` is populated and `ctx.builds_dir` points at the dir.
2. A backward-compat test: a project with NO builds/ and NO sidecar returns `build_spec_files == []` and `builds_dir is None`.

**Pattern:** `tmp_path` fixture, `Path.write_text`, then assert on returned `ProjectContext` fields. Identical to the existing `test_discover_project`.

---

## MODIFY: `tests/test_registry.py` — VERIFY ONLY (no change)

**Closest analog:** itself — `test_registry_has_98_operations` at line 23 (asserts `== 160`) and `test_validate_registry_completeness_passes` at line 27 (tolerates the 3 known-missing).

**Action:** None required. Phase 209 adds 0 ops, so the count stays 160 and the completeness test already passes. The plan's Task 4 re-runs these tests as an acceptance gate (INTEG-06), but no edit is made to this file. Listed here only to make the "no change" decision explicit.

---

## Pattern-Compliance Summary

| File | Action | Analog | Convention Followed |
|------|--------|--------|---------------------|
| `manufacturing/manufacturer_client.py` | CREATE | `dfm/checker.py:99` + `manufacturing/board_spec.py` | ABC + frozen dataclasses (CR-01) |
| `tests/test_manufacturer_client.py` | CREATE | `test_crossfile_submodules.py:41` | Import-smoke + interface-shape tests |
| `tests/test_cli_integration.py` | CREATE | `test_cli.py:171` | In-process `main([...])` + monkeypatch + capsys |
| `src/volta/cli.py` | MODIFY | `_handle_dfm` (cli.py:688) + `_handle_route` (cli.py:443) | argparse subparsers + `handle_operation` dispatch |
| `crossfile/project_context.py` | MODIFY | itself (project_context.py:27,85) | additive frozen-dataclass fields + glob discovery |
| `tests/test_crossfile_submodules.py` | MODIFY | `test_discover_project` (line 56) | tmp_path fake-project + assert fields |
| `tests/test_registry.py` | VERIFY | itself | no change (count already 160) |

**No invented conventions.** Every CREATE/MODIFY traces to a proven codebase pattern.
