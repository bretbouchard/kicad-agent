# Phase 209 Research — Crossfile + MCP Integration

**Gathered:** 2026-07-11
**Status:** Complete — all claims verified against live code
**Method:** Direct file reads + runtime introspection (`.venv/bin/python`)

## R1. MCP Auto-Generation — CONFIRMED FREE

`_generate_operation_tools()` at `src/volta/mcp/edit_server.py:133`:

```python
def _generate_operation_tools() -> list[types.Tool]:
    """Generate one MCP tool per Operation union variant."""
    ann = Operation.model_fields["root"].annotation
    variants = get_args(ann)
    tools: list[types.Tool] = []

    for variant_cls in variants:
        op_type = variant_cls.model_fields["op_type"].default
        schema = variant_cls.model_json_schema()
        _inline_refs(schema)
        description = schema.pop("description", f"Execute {op_type} operation.")
        annotations = _annotations_for(op_type)
        tools.append(types.Tool(
            name=op_type, description=description,
            inputSchema=schema, annotations=annotations,
        ))
    return tools
```

**Mechanism:** Reads `Operation` discriminated union via `get_args(ann)`, iterates every variant, and emits one MCP tool per variant keyed by `op_type`. Adding a new op to the union automatically produces an MCP tool — **zero manual MCP wiring required.**

**Runtime verification** — all 9 new ops are PRESENT in the union:

```
Total variants: 163
  read_board_metadata: PRESENT
  set_board_metadata: PRESENT
  set_board_revision: PRESENT
  drc_vendor: PRESENT
  list_vendor_drc_profiles: PRESENT
  build_create: PRESENT
  build_list: PRESENT
  build_show: PRESENT
  build_handoff_export: PRESENT
```

**Conclusion:** INTEG-01 is verification-only. No edits to `edit_server.py` are needed. The plan task is to assert the generated tool list contains all 9 op_types.

## R2. CLI Subcommand Pattern

`_SUBCOMMANDS` set at `src/volta/cli.py:38`:

```python
_SUBCOMMANDS = {"collect", "erc", "drc", "export", "context", "route", "analyze",
                "component-search", "ai-stats", "design-rules", "review-schematic",
                "pre-pcb-gate", "gate", "demo", "playground", "dfm", "undo", "redo",
                "workflow", "critique", "check-conventions"}
```

`main()` routing at `src/volta/cli.py:1204`:

```python
def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv[1:]
    if not argv or argv[0] in ("--help", "-h"):
        _print_help(); sys.exit(0)
    if argv and argv[0] in _SUBCOMMANDS:
        configure_logging()
        subcmd = argv[0]
        subcmd_argv = argv[1:]
        if subcmd == "drc":
            _handle_drc(subcmd_argv)
        # ... elif chain ...
```

**Two handler patterns exist:**

1. **kicad-cli passthrough** (`_handle_drc`, `_handle_export` at `cli.py:290, 312`): build a `kicad-cli` argv list, call `_run_kicad_cli(cmd)`. Used for ops that delegate to the KiCad binary.

2. **Operation dispatch** (`_handle_route` at `cli.py:443`, `_handle_review_schematic` at `cli.py:755`): build an op dict, call `handle_operation(op_json, project_dir=...)`, print `format_result(result)`. **This is the pattern the 4 new subcommands must use** — they wrap native volta operations, not the KiCad binary.

Operation-dispatch skeleton (from `_handle_route`):

```python
op_json = json.dumps({"op_type": "auto_route", "target_file": target_file, ...})
from volta.handler import handle_operation, format_result
result = handle_operation(op_json)
if result.success:
    print(...)            # human-readable success summary
else:
    print(format_result(result), file=sys.stderr)
    sys.exit(1)
sys.exit(0)
```

**`handle_operation` signature** (`src/volta/handler.py:112`):

```python
def handle_operation(
    json_str: str,
    project_dir: Path | None = None,
) -> Union[OperationResult, OperationError]:
```

Accepts a JSON string (or dict — `validate_operation` handles both). Returns `OperationResult` (has `.success`, `.details`) or `OperationError`. The new subcommands will use argparse (matching `_handle_drc`), then dispatch via `handle_operation`.

**Subcommand-as-router:** `build`, `drc-vendor`, `board-metadata` each need a nested subcommand (e.g. `build create|list|show`). Pattern: use `parser.add_subparsers()` (see `_handle_dfm` at `cli.py:688` which calls `register_dfm_parser(subparsers)`).

`_handle_dfm` pattern (`cli.py:688`):

```python
def _handle_dfm(argv: list[str]) -> None:
    from volta.dfm.cli import register_dfm_parser, dfm_command
    parser = argparse.ArgumentParser(prog="volta dfm", description="...")
    subparsers = parser.add_subparsers()
    register_dfm_parser(subparsers)
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help(); sys.exit(2)
    sys.exit(dfm_command(args))
```

## R3. ProjectContext Fields + discover_project()

`ProjectContext` at `src/volta/crossfile/project_context.py:27` — **frozen dataclass**:

```python
@dataclass(frozen=True)
class ProjectContext:
    project_root: Path
    pro_file: Optional[Path]
    schematic_files: list[Path] = field(default_factory=list)
    pcb_files: list[Path] = field(default_factory=list)
    sym_lib_files: list[Path] = field(default_factory=list)
    footprint_files: list[Path] = field(default_factory=list)
    library_paths: list[str] = field(default_factory=list)
```

`discover_project()` at `project_context.py:85` scans via `glob("**/*.kicad_pcb")` etc., then constructs and returns `ProjectContext(...)`. The construction call is at line 123.

**Extension needed (INTEG-03, INTEG-04):**
- Add 2 fields with defaults: `build_spec_files: list[Path] = field(default_factory=list)`, `builds_dir: Optional[Path] = None`.
- In `discover_project()`, before the `return ProjectContext(...)` at line 123, add:
  - `build_spec_files = sorted(resolved_root.glob("**/*.kicad_build_spec.json"))`
  - `builds_dir = resolved_root / "builds"` then set to that Path if `builds_dir.is_dir()` else None.
- Pass both into the constructor call.

**Backward compatibility:** Because both new fields have defaults, every existing `ProjectContext(...)` construction that omits them still works. Frozen dataclass permits adding defaulted fields without breaking positional callers (existing call uses keyword args at line 123-131).

## R4. ManufacturerClient ABC Pattern

The codebase's standard ABC pattern is `DfmCheck(ABC)` at `src/volta/dfm/checker.py:99`:

```python
class DfmCheck(ABC):
    """Abstract base class for DFM checks."""
    name: str
    description: str = ""

    @abstractmethod
    def check(self, spatial_model: Any, profile: Any,
              config: dict[str, Any] | None = None) -> list[DfmFinding]:
        """Check the PCB spatial model against manufacturer profile constraints."""
```

Other ABC exemplars: `DesignRule(ABC)` (`analysis/design_rules.py:102`), conventions `base.py`. **The new `ManufacturerClient(ABC)` will follow this exact pattern** — class-level docstring, `@abstractmethod` on each method, type hints on signatures. Supporting `Quote`, `OrderResult`, `OrderStatus` follow the frozen-dataclass convention (CR-01) used across the codebase.

## R5. Registry Count — 160 (NO NEW OPS)

**Runtime confirmation:**

```
Registry count: 160
validate_registry_completeness():
  registry_count: 160
  schema_count: 163
  missing_from_registry: [add_design_note, apply_floor_plan, place_and_wire_power_units]
  extra_in_registry: []
```

**Phase 209 adds ZERO operations.** All 9 ops from Phases 205-208 are already registered (count moved 142 → 160 across those phases). The 3 missing-from-registry ops are pre-existing documented tech debt (predate Phase 205), tracked in `tests/test_registry.py:33` via `_KNOWN_PREEXISTING_MISSING`.

`tests/test_registry.py:25` already asserts `== 160` — **no edit needed** (Phase 208 already bumped it). INTEG-06 is a verification task: confirm the count stays 160 and `validate_registry_completeness()` continues to pass.

## R6. File Existence Check

Target files that must be CREATED (do not exist yet):
- `src/volta/manufacturing/manufacturer_client.py` — confirmed missing
- `tests/test_manufacturer_client.py` — confirmed missing
- `tests/test_cli_integration.py` — confirmed missing

Target files that must be MODIFIED (exist):
- `src/volta/cli.py` — exists; add 4 entries to `_SUBCOMMANDS` + 4 elif branches in `main()` + 4 `_handle_*` functions
- `src/volta/crossfile/project_context.py` — exists; add 2 fields + 2 discovery lines
- `tests/test_registry.py` — exists; **count already 160, no change required** (verify only)

**No `tests/test_project_context.py` exists.** ProjectContext tests live in `tests/test_crossfile_submodules.py` (class `TestProjectContextModule`) and `tests/test_crossfile_coverage.py`. The plan must extend one of these (prefer `test_crossfile_submodules.py` which already has the `discover_project` real-project test) rather than create a new test file.

Existing CLI tests: `tests/test_cli.py` (subprocess invocation) and `tests/test_cli.py` in-process `main(["analyze", ...])` calls (see `test_analyze_subcommand_calls_generate_analysis` at line 171). The new `test_cli_integration.py` should follow the in-process `main([...])` + `capsys` pattern from `test_cli.py`.

## R7. Handler Registry — NO NEW MODULE

All Phase 205-208 handlers are already registered and merged (confirmed in CONTEXT IP-3). `_BUILD_HANDLERS` is merged in `ops/handlers/__init__.py`. No `manufacturing.py` handler module is needed and no merge is required. INTEG does not touch handlers.

## Summary of Verified Facts

| Claim | Status |
|-------|--------|
| `_generate_operation_tools()` auto-reads Operation union | CONFIRMED (edit_server.py:133) |
| All 9 new ops PRESENT in union | CONFIRMED (runtime: 163 variants, 9/9 present) |
| Registry count == 160 | CONFIRMED (runtime) |
| Phase 209 adds 0 ops | CONFIRMED (no registry edits) |
| 3 missing-from-registry are pre-existing tech debt | CONFIRMED (test_registry.py:33) |
| `validate_registry_completeness()` passes | CONFIRMED (only known-missing remain) |
| Operation-dispatch CLI pattern exists (`_handle_route`) | CONFIRMED (cli.py:443) |
| Nested-subcommand CLI pattern exists (`_handle_dfm`) | CONFIRMED (cli.py:688) |
| `ProjectContext` is frozen dataclass, extensible | CONFIRMED (project_context.py:27) |
| ABC pattern (`DfmCheck`) established | CONFIRMED (dfm/checker.py:99) |
| `tests/test_project_context.py` does NOT exist | CONFIRMED (use test_crossfile_submodules.py) |
| `manufacturer_client.py` does NOT exist | CONFIRMED (must create) |
