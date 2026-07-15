# Phase 209: Crossfile + MCP Integration - Context

**Gathered:** 2026-07-11
**Status:** Ready for planning
**Source:** Derived from v7.0 ROADMAP.md + REQUIREMENTS.md + codebase pattern analysis + user directive ("maximum flexibility, no compromises")

<domain>
## Phase Boundary

Phase 209 is the final active phase of v7.0 — it wires all new operations into MCP and CLI, extends ProjectContext to discover builds/ and sidecar files, and defines the ManufacturerClient ABC for future API adapters. After this phase, the v7.0 milestone is complete (Phase 210 is DEFERRED to v7.1).

**What ships:**
- MCP auto-exposure: all new ops (read_board_metadata, set_board_metadata, set_board_revision, drc_vendor, list_vendor_drc_profiles, build_create, build_list, build_show, build_handoff_export) appear automatically as MCP tools (free — `_generate_operation_tools()` reads from the Operation union)
- CLI subcommands: `build`, `handoff`, `drc-vendor`, `board-metadata`
- `ProjectContext` extended to discover `builds/` directories and `.kicad_build_spec.json` sidecars
- `ManufacturerClient` ABC defined (interface only — `quote()`, `place_order()`, `get_status()` abstract methods)
- Registry count assertion and `validate_registry_completeness()` verified

**What does NOT ship:**
- Vendor API adapter implementations (Phase 210, DEFERRED to v7.1)
- Actual API calls to any manufacturer

</domain>

<decisions>
## Implementation Decisions

### MCP Auto-Exposure (INTEG-01)

- **FREE — no code changes needed.** `_generate_operation_tools()` at `mcp/edit_server.py:133` already reads from the `Operation` discriminated union via `get_args(ann)`. Every op added in Phases 205-208 is already in the union, so MCP tools are auto-generated.
- **Verification only:** Confirm all 9 new ops appear as MCP tools by running the tool generation and checking the tool names.
- **No manual MCP wiring** — this is the beauty of the auto-generation design.

### CLI Subcommands (INTEG-02)

Add 4 new subcommands to `cli.py`:

1. **`build`** — wraps build_create, build_list, build_show
   - `volta build create <pcb>` → build_create op
   - `volta build list <pcb>` → build_list op
   - `volta build show <pcb> --id <build_id>` → build_show op

2. **`handoff`** — wraps build_handoff_export
   - `volta handoff <pcb> [--vendor <name>] [--no-step]` → build_handoff_export op

3. **`drc-vendor`** — wraps drc_vendor
   - `volta drc-vendor <pcb> --vendor <name>` → drc_vendor op
   - `volta drc-vendor <pcb> --list` → list_vendor_drc_profiles op

4. **`board-metadata`** — wraps read_board_metadata, set_board_metadata, set_board_revision
   - `volta board-metadata read <pcb>` → read_board_metadata op
   - `volta board-metadata set-rev <pcb> <rev>` → set_board_revision op
   - `volta board-metadata set <pcb> [--title <t>] [--company <c>] [--date <d>]` → set_board_metadata op

- **Pattern:** Follow existing `_handle_dfm` / `_handle_drc` pattern — parse argv, construct op dict, call `OperationExecutor`, print JSON result
- **Add to `_SUBCOMMANDS` set** and create `_handle_build`, `_handle_handoff`, `_handle_drc_vendor`, `_handle_board_metadata` functions
- **Output:** JSON to stdout (consistent with existing subcommands)

### ProjectContext Extension (INTEG-03, INTEG-04)

- **Extend `ProjectContext`** in `crossfile/project_context.py`:
  ```python
  # New fields:
  build_spec_files: list[Path] = field(default_factory=list)  # .kicad_build_spec.json sidecars
  builds_dir: Path | None = None  # builds/ directory if it exists
  ```
- **Extend `discover_project()`** to scan for:
  - `.kicad_build_spec.json` files (same stem as .kicad_pcb files)
  - `builds/` directory (if it exists in project root)
- **Builds are project-scoped:** Each project has its own `builds/` directory under the project root (INTEG-04)

### ManufacturerClient ABC (INTEG-05, Pitfall 8)

- **New file:** `src/volta/manufacturing/manufacturer_client.py`
- **ABC definition:**
  ```python
  from abc import ABC, abstractmethod
  from dataclasses import dataclass
  from typing import Any

  @dataclass(frozen=True)
  class Quote:
      vendor: str
      unit_price_usd: float
      quantity: int
      lead_time_days: int
      currency: str = "USD"
      notes: str = ""

  @dataclass(frozen=True)
  class OrderResult:
      order_id: str
      status: str
      vendor: str
      estimated_ship_date: str = ""

  @dataclass(frozen=True)
  class OrderStatus:
      order_id: str
      status: str
      vendor: str
      tracking_number: str = ""
      last_updated: str = ""

  class ManufacturerClient(ABC):
      """Abstract interface for manufacturer API adapters.

      Implementations (Phase 210, DEFERRED to v7.1) connect to specific
      vendor APIs (PCBWay, MacroFab, JLCPCB) for quote/order/status.

      Scope guard (Pitfall 8): If activated, scope to QUOTE ONLY first —
      quoting is read-only and safe; ordering has financial consequences.
      """

      @abstractmethod
      def quote(self, board_spec: Any, quantity: int = 1, **kwargs) -> Quote:
          """Request a manufacturing quote for a board specification."""

      @abstractmethod
      def place_order(self, quote: Quote, **kwargs) -> OrderResult:
          """Place an order based on a previously obtained quote."""

      @abstractmethod
      def get_status(self, order_id: str) -> OrderStatus:
          """Check the status of a previously placed order."""
  ```
- **NO adapter implementations** — just the interface (INTEG-05, Pitfall 8 scope-creep prevention)
- **Importing it does NOT require any network libraries or credentials** — pure interface

### Registry and Schema Validation (INTEG-06, IP-1, IP-2)

- **Registry count:** Currently 160 (after Phase 208). Phase 209 adds NO new ops — it only wires existing ops into CLI and verifies MCP/registry parity.
- **`validate_registry_completeness()` must pass** — registry, schema union, and handlers all in sync
- **Update `test_registry.py`** if the count assertion needs updating (it shouldn't — no new ops)
- **The 3 pre-existing missing-from-registry ops** (`add_design_note`, `apply_floor_plan`, `place_and_wire_power_units`) are documented tech debt, not Phase 209's responsibility

### Handler Registry (IP-3)

- **No new handler module needed** — all ops from Phases 205-208 are already registered:
  - Phase 205: `read_board_metadata`, `set_board_metadata`, `set_board_revision` in `handlers/query.py` and `handlers/pcb.py`
  - Phase 206: `drc_vendor`, `list_vendor_drc_profiles` in `handlers/query.py`
  - Phase 207: `build_create`, `build_list`, `build_show` in `handlers/build.py` (merged via `_BUILD_HANDLERS`)
  - Phase 208: `build_handoff_export` in `handlers/build.py`
- All handlers are already merged in `handlers/__init__.py`

### CROSS_FILE_OP_TYPES (IP-4)

- **Already resolved** — all build/handoff ops are query ops (not CROSS_FILE_OP_TYPES), as decided in Phases 207-208. No changes needed.

### Claude's Discretion

- **CLI argument parsing:** Use simple `argv` parsing (no argparse) to match existing `_handle_*` pattern. The existing subcommands use manual `argv` index parsing.
- **Error handling:** CLI subcommands print JSON errors to stderr and exit with non-zero codes, matching existing pattern.
- **ProjectContext backward compat:** New fields default to empty list / None — existing callers are unaffected.
- **ManufacturerClient dataclasses:** `Quote`, `OrderResult`, `OrderStatus` are frozen dataclasses (consistent with the codebase's CR-01 frozen convention). They carry enough info to be useful without being vendor-specific.

</decisions>

<canonical_refs>
## Canonical References

### MCP Tool Generation
- `src/volta/mcp/edit_server.py` — `_generate_operation_tools()` (line 133), reads from `Operation` union via `get_args(ann)`, auto-generates one MCP tool per variant

### CLI Structure
- `src/volta/cli.py` — `_SUBCOMMANDS` set (line 38), `_handle_dfm` (line 688) as the closest analog for a subcommand that delegates to operations, `_handle_drc` (line 290) for a simpler pattern, `main(argv)` routing (line ~1204)

### ProjectContext
- `src/volta/crossfile/project_context.py` — `ProjectContext` class (line 27), `discover_project()` (line 85), `detect_project_root()` (line 52)

### ABC Pattern
- `src/volta/dfm/checker.py` — `DfmCheck(ABC)` (line 99) with `@abstractmethod` (line 113) — the codebase's standard ABC pattern
- `src/volta/analysis/design_rules.py` — `DesignRule(ABC)` (line 102)
- `src/volta/conventions/base.py` — another ABC example

### Handler Registry
- `src/volta/ops/handlers/__init__.py` — handler merge pattern (lines 28-35), `_BUILD_HANDLERS` already merged (line 35)

### Registry Validation
- `tests/test_registry.py` — count assertion (line ~26), `validate_registry_completeness()`
- `src/volta/ops/registry.py` — `OPERATION_REGISTRY`, `_RAW_CATALOG`

### Pitfalls
- `.planning/research/PITFALLS.md` — Pitfall 8 (API adapter scope creep — guarded by DEFERRED status + quote-only scope rule)

</canonical_refs>

<specifics>
## Specific Ideas

- MCP auto-exposure is the "free" win of this phase — the auto-generation design means all 9 new ops are already MCP tools without writing any MCP code. This is a verification-only task.
- The CLI subcommands make the v7.0 features accessible to users who don't use MCP — `volta handoff board.kicad_pcb --vendor jlcpcb` is the one-command manufacturing handoff.
- ProjectContext extension is small but important — it means build operations can discover the project's build history and BoardSpec without the user specifying paths.
- ManufacturerClient ABC is the seed for v7.1 — it defines the interface that future API adapters will implement. The quote-only scope guard (Pitfall 8) is baked into the docstring.
- The `Quote` dataclass is vendor-neutral — it carries price, quantity, lead time, and currency. Any vendor adapter can populate it.
- This is the last active phase — after verification passes, the v7.0 milestone is complete.

</specifics>

<deferred>
## Deferred Ideas

- Vendor API adapter implementations (PCBWay, MacroFab, JLCPCB) — Phase 210 (DEFERRED to v7.1)
- Quote comparison across multiple vendors — Phase 210
- Order tracking with status notifications — Phase 210
- CLI autocomplete — future enhancement
- MCP tool annotations enrichment — future (currently auto-generated descriptions are sufficient)
- ProjectContext build history API (query past builds programmatically) — future

</deferred>

---

*Phase: 209-crossfile-mcp-integration*
*Context gathered: 2026-07-11 via user directive ("maximum flexibility") + codebase pattern analysis*
