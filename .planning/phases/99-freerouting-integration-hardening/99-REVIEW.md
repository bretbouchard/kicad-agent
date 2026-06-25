---
phase: 99-freerouting-integration-hardening
reviewed: 2026-06-24T00:00:00Z
depth: standard
files_reviewed: 28
files_reviewed_list:
  - scripts/phase99_baseline.py
  - src/kicad_agent/handler.py
  - src/kicad_agent/ir/pcb_ir.py
  - src/kicad_agent/ops/_schema_pcb.py
  - src/kicad_agent/ops/handlers/pcb.py
  - src/kicad_agent/parser/pcb_native_parser.py
  - src/kicad_agent/parser/pcb_native_types.py
  - src/kicad_agent/routing/FreerouteBatch.java
  - src/kicad_agent/routing/bridge.py
  - src/kicad_agent/routing/dsn_generator.py
  - src/kicad_agent/routing/freerouting.py
  - src/kicad_agent/routing/graph.py
  - src/kicad_agent/routing/pathfinder.py
  - tests/test_phase99_dsn_r1_courtyard.py
  - tests/test_phase99_dsn_r1_footprints.py
  - tests/test_phase99_dsn_r2_netclass.py
  - tests/test_phase99_dsn_r3_zones.py
  - tests/test_phase99_dsn_r4_viatypes.py
  - tests/test_phase99_dsn_r5_snap_angle.py
  - tests/test_phase99_e2e_drc.py
  - tests/test_phase99_r3_keepout_compliance.py
  - tests/test_phase99_r5_baseline_45deg.py
  - tests/test_phase99_r6_roundtrip.py
  - tests/test_phase99_r7_comment_sweep.py
  - tests/test_phase99_ses_r6_multilayer.py
  - tests/test_phase99_snap_angle_threading.py
  - tests/test_phase99_snap_angle_threading.py
  - tests/test_routing.py
findings:
  critical: 1
  warning: 8
  info: 7
  total: 16
status: issues_found
---

# Phase 99: Code Review Report

**Reviewed:** 2026-06-24
**Depth:** standard
**Files Reviewed:** 28
**Status:** issues_found

## Summary

Phase 99 delivers a substantial Freerouting integration hardening: the DSN generator was refactored to consume `NativeBoard` (eliminating UUID loss), per-stackup via padstacks were added (R-4), SES multi-layer bridge issues were fixed (R-6), snap-angle threading was wired end-to-end (R-5), and 3-way zone classification (C-1) prevents Freerouting from being told to avoid regions the source PCB allows tracks through. Test coverage for R-1 through R-7 is good, with both unit tests (fast, no external deps) and slow integration tests that skip gracefully when Freerouting/Java/kicad-cli is missing.

The most significant finding is a **critical immutability violation**: `NativeBoard` and all leaf dataclasses (`NativeNet`, `NativeFootprint`, `NativePad`, `NativeSegment`, `NativeVia`, `NativeZone`, etc.) are declared as **mutable** dataclasses, which directly violates the project's coding-style rule ("ALWAYS create new objects, NEVER mutate existing ones. Apply value-type semantics in all languages."). The module docstring acknowledges this ("All dataclasses are mutable (not frozen) to support the PcbIR adapter pattern"), but the correct pattern for immutable-with-append is `dataclasses.replace()`, which `PcbIR` already uses elsewhere. Making these mutable is a project-wide style violation that will compound as more code touches `NativeBoard`.

Other notable issues: `snap_angle` is not threaded from `AutoRouteOp` through `_handle_auto_route` to `route_with_freerouting` (R-5 works at the CLI/export level but NOT when invoked via the `auto_route` op); the handler calls `route_with_freerouting(max_passes=10)` which exceeds the schema's documented `max_iterations` cap of 5; and the DSN generator emits `(pin {padstack} {name} X Y)` without quoting `name`, which will break on pad numbers containing spaces or special characters.

Security: the Freerouting subprocess invocation uses argument lists (no shell=True), validates `snap_angle` against an enum before passing it to Java, and enforces a 50MB size limit + depth pre-scan on PCB parsing. No injection vulnerabilities found. The depth pre-scan (Council CRITICAL-1) correctly prevents `RecursionError` from malicious nested content.

## Critical Issues

### CR-01: NativeBoard dataclasses are mutable (violates project immutability rule)

**File:** `src/kicad_agent/parser/pcb_native_types.py:58-329`
**Issue:** Every dataclass in this module (`NativeNet`, `NativeNetClass`, `NativePad`, `NativeFootprint`, `NativeSegment`, `NativeVia`, `NativeZone`, `NativeGraphicItem`, `NativeBoardOutline`, `NativeGeneral`, `NativeStackupLayer`, `NativeStackup`, `NativeSetup`, `NativeBoard`) is declared with `@dataclass` (not `@dataclass(frozen=True)`). The module docstring explicitly states this is intentional ("All dataclasses are mutable (not frozen) to support the PcbIR adapter pattern where PcbIR methods append to board.nets, etc."), but this directly violates `~/.claude/rules/coding-style.md`:

> **Immutability (CRITICAL)** — ALWAYS create new objects, NEVER mutate existing ones. Apply value-type semantics in all languages.

Mutable dataclasses enable aliasing bugs: any code that holds a reference to a `NativeFootprint` (or a list inside `NativeBoard`) sees mutations made by unrelated code. This is especially dangerous for `NativeBoard` because it's cached on `PcbIR` and shared across handler calls. The `PcbIR` class itself already demonstrates the correct pattern elsewhere (`replace(self._parse_result, raw_content=new_raw)` on line 1000), so the mutable declaration here is inconsistent with the rest of the codebase.

The specific mutation sites that motivated the mutability:
- `PcbIR.add_net` (line 193): `self.board.nets.append(net)` — should use `replace` to create a new board with a new nets list.
- `PcbIR.rename_net` (line 247): `n.name = new_name` — should use `replace` on the net.
- `NativeParser._build_board` (lines 356-389): sets fields directly (`board.version = ...`, `board.nets = ...`) — should construct the board once at the end.

**Fix:** Make all dataclasses frozen, and update the ~8 mutation sites to use `dataclasses.replace()`:

```python
# pcb_native_types.py — all leaf dataclasses
@dataclass(frozen=True)
class NativeNet:
    number: int = 0
    name: str = ""

@dataclass(frozen=True)
class NativeBoard:
    version: str = ""
    nets: tuple[NativeNet, ...] = ()  # or use a frozenlist / return new list
    # ...

# pcb_ir.py — PcbIR.add_net
def add_net(self, net_name: str = "", net_number: int | None = None) -> Any:
    # ...
    if self._is_native:
        from kicad_agent.parser.pcb_native_types import NativeNet
        net = NativeNet(number=net_number, name=net_name)
        new_nets = [*self.board.nets, net]
        self._native_board = replace(self._native_board, nets=new_nets)
    # ...
```

If full immutability is too large a refactor for this phase, at minimum file a tracked deferral Bead per bureaucracy §7.7 and mark the module with a `# TODO(immutability): see BEAD-XXX` comment. The current state (documented mutation) is a silent style violation.

## Warnings

### WR-01: snap_angle not threaded from AutoRouteOp to route_with_freerouting

**File:** `src/kicad_agent/ops/handlers/pcb.py:529`
**Issue:** The `_handle_auto_route` handler calls `route_with_freerouting(file_path, max_passes=10)` without passing `snap_angle`. The `AutoRouteOp` schema (`_schema_pcb.py:132`) has no `snap_angle` field, and `BLOCKER-1` (tested in `test_phase99_snap_angle_threading.py`) only verifies the `export_dsn` -> `generate_dsn` path. When a user invokes `{"op": "auto_route", "strategy": "freerouting"}`, the snap_angle defaults to `"none"` regardless of any caller intent. The R-5 feature is therefore inaccessible through the operation executor, which is the primary user-facing entry point.

**Fix:** Add `snap_angle` to `AutoRouteOp` (with `Literal["none", "fortyfive_degree", "ninety_degree"]` and default `"none"`), then thread it:

```python
# _schema_pcb.py — AutoRouteOp
snap_angle: Literal["none", "fortyfive_degree", "ninety_degree"] = Field(
    default="none",
    description="Trace angle mode threaded to Freerouting (R-5).",
)

# handlers/pcb.py — _handle_auto_route
fr_result = route_with_freerouting(
    file_path,
    max_passes=min(op.max_iterations, 5),
    snap_angle=getattr(op, "snap_angle", "none"),
)
```

### WR-02: auto_route handler bypasses max_iterations cap (passes=10)

**File:** `src/kicad_agent/ops/handlers/pcb.py:529`
**Issue:** `_handle_auto_route` calls `route_with_freerouting(file_path, max_passes=10)`, but the `AutoRouteOp.max_iterations` field (`_schema_pcb.py:189-196`) is documented as "Council C-03 caps at 5 to prevent runaway loops" with `le=5`. The handler ignores `op.max_iterations` entirely and hardcodes 10, which:
1. Exceeds the documented cap of 5.
2. Ignores the user's `max_iterations` setting.
3. Can trigger runaway Freerouting loops on dense boards (each pass can take minutes).

**Fix:**
```python
max_passes = min(getattr(op, "max_iterations", 3), 5)
fr_result = route_with_freerouting(file_path, max_passes=max_passes, ...)
```

### WR-03: DSN pin name emitted unquoted (injection / parse-failure risk)

**File:** `src/kicad_agent/routing/dsn_generator.py:217-221`
**Issue:** The pin emission is:
```python
pin_name = pin['name'] if pin['name'] else "pad"
lines.append(
    f"      (pin {pin['padstack']} {pin_name}"
    f" {int(pin['x'] * _MM_TO_UM)} {int(pin['y'] * _MM_TO_UM)})"
)
```
If a pad number contains spaces, quotes, or parentheses (rare but possible in custom footprints — KiCad allows arbitrary string pad numbers), the DSN will be malformed and Freerouting will reject it with a parse error. The `padstack` value comes from a generated key (`f"TH_{size_um}:{drill_um}_um"`) so it's safe, but `pin_name` is user-supplied data from the PCB.

**Fix:** Quote the pin name and escape embedded quotes (DSN uses doubled-quote escaping, which `(string_quote ")` in the parser header declares):
```python
safe_name = pin['name'].replace('"', '""') if pin['name'] else "pad"
lines.append(
    f'      (pin {pin["padstack"]} "{safe_name}"'
    f' {int(pin["x"] * _MM_TO_UM)} {int(pin["y"] * _MM_TO_UM)})'
)
```
Verify against Freerouting's Specctra parser whether quoted pin names are accepted; if not, add a validator that rejects pad names containing whitespace/quotes at the `NativeParser` layer.

### WR-04: _strip_library_metadata regex does not handle CRLF line endings

**File:** `src/kicad_agent/ir/pcb_ir.py:1081-1088`
**Issue:** The patterns use `\n` in the replacement and `^\t` anchors with `re.MULTILINE`, but if the library `.kicad_mod` file uses CRLF (`\r\n`) line endings (Windows-produced libraries), the `\s*\n` suffix won't match the `\r`, and the `^\t` anchor may fail depending on whether `\r` is treated as non-whitespace. KiCad itself writes LF on Unix and CRLF on Windows, so this is a real cross-platform concern.

**Fix:** Either normalize line endings on read (`content.replace("\r\n", "\n")` at the top of `update_footprint_from_library`), or use `[ \t]*` and `\r?\n` in the patterns:
```python
r'^\t\(version [^\)]*\)[ \t]*\r?\n'
```

### WR-05: FreerouteBatch.java hardcodes job.name = "analog-board"

**File:** `src/kicad_agent/routing/FreerouteBatch.java:69`
**Issue:** `job.name = "analog-board";` is a hardcoded string tied to a specific fixture. This doesn't affect routing correctness but leaks the wrong identifier into Freerouting's logs, thread names, and any future job-tracking UI. On a production board (e.g., "Arduino_Mega" or "x64-smart-grid"), the log output is misleading.

**Fix:** Derive the job name from the input DSN filename:
```java
File dsnFile = new File(inputDsn);
job.name = dsnFile.getName().replace(".dsn", "");
```

### WR-06: phase99_baseline.py route_with_freerouting missing snap_angle

**File:** `scripts/phase99_baseline.py:152`
**Issue:** `_collect_metrics` calls `route_with_freerouting(fixture, max_passes=max_passes)` without `snap_angle`. The baseline therefore always routes in `none` mode, which (per the R-5 baseline test docstring) is Freerouting's any-angle mode and may produce different results than a caller that explicitly sets `fortyfive_degree`. The baseline numbers won't match what an `auto_route` op with explicit snap_angle produces.

**Fix:** Either add a `--snap-angle` CLI flag (defaulting to `"none"`) and thread it through, or document in the script's docstring that the baseline is always run in `none` mode and cannot be used to validate 45° output.

### WR-07: PcbIR.remove_net mutates NativePad in place

**File:** `src/kicad_agent/ir/pcb_ir.py:218-220`
**Issue:** When removing a net, the code iterates footprints and pads, and for the native path does:
```python
if pad.net_name == net_name:
    pad.net_name = ""
    pad.net_number = 0
```
This mutates the `NativePad` object in place (same immutability violation as CR-01, scoped to this one method). Worse, it mutates a pad that may still be referenced by the original `NativeBoard.footprints[i].pads[j]` — so the "removed" net actually disappears from the live board even if the caller expected a transactional rollback.

**Fix:** Same as CR-01 — use `replace(pad, net_name="", net_number=0)` and rebuild the footprint's pads list, then rebuild the board's footprints list.

### WR-08: _parse_via_block numeric heuristic is fragile (misclassifies "default" tokens)

**File:** `src/kicad_agent/routing/freerouting.py:603-636`
**Issue:** `_parse_via_block` splits the inner block on whitespace and treats anything passing `float()` as a coordinate. This is fragile for two cases:

1. **Padstack declarations with numeric-looking names**: `(via "Via[0-1]" "Via[0-1]" default)` — the second `"Via[0-1]"` and `default` are correctly filtered, but if a future Freerouting build emits `(via "Via[0-1]" 800 400 default)` as a declaration with size+drill, the declaration would be misclassified as an actual via instance at (800, 400). The current guard `len(numeric_tokens) < 2` catches declarations with 0-1 numerics, but not 2.

2. **Net name that looks numeric**: `(net 123 4)` inside a via block (net number 123, code 4) would be parsed as coordinates. The `_find_net_name_in_block` regex `\(net\s+(?:"([^"]+)"|(\S+))\s+\d+\)` matches `net` followed by either a quoted string or a bare token then a digit — but on `(net 123 4)` it would capture `123` as the net name.

The current Freerouting v2.2.4 format is safe, but this parsing is brittle against future SES format changes.

**Fix:** Use the paren-balanced extraction (already available via `_extract_paren_block`) to isolate the `(net ...)` child first, then parse coordinates from the remaining tokens. Or use a proper S-expression parser instead of regex + split.

## Info

### IN-01: Duplicate import statement in _schema_pcb.py

**File:** `src/kicad_agent/ops/_schema_pcb.py:5-8`
**Issue:** `from pydantic import BaseModel, Field` is imported on line 5, then again (with additions) on line 8:
```python
from pydantic import BaseModel, Field
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator
```
The second import shadows the first and is the one actually used. The first is dead code.

**Fix:** Delete lines 5-6 (the first import) and keep the consolidated import on line 8.

### IN-02: phase99_baseline.py temp file cleanup race on .drc.json

**File:** `scripts/phase99_baseline.py:186-187`
**Issue:** The cleanup does:
```python
temp_path.unlink(missing_ok=True)
temp_path.with_suffix(".drc.json").unlink(missing_ok=True)
```
The `.drc.json` suffix replacement uses `with_suffix`, but `temp_path` is something like `tmpXXXX.kicad_pcb`, so `with_suffix(".drc.json")` produces `tmpXXXX.drc.json` (correct). However, if kicad-cli changes its output naming convention in a future version, this cleanup silently leaves files behind. Not a bug today, just brittle.

**Fix:** Capture the actual output path passed to kicad-cli (`out_path`) and unlink that directly, rather than reconstructing it from the temp path.

### IN-03: _parse_net_nested_wires returns result but caller ignores return value

**File:** `src/kicad_agent/routing/freerouting.py:769`
**Issue:** `_parse_net_nested_wires` ends with `return result`, but the caller `parse_ses` (line 481) calls it as a statement (`_parse_net_nested_wires(...)`) without using the return value. The function mutates `result` in place (appends to `result.wires`), so the return is redundant.

**Fix:** Either drop the `return result` (make it a void function) or have the caller use the return value. The former is simpler given the mutation-based contract.

### IN-04: Test fixture path inconsistency (Arduino_Mega lock files)

**File:** `tests/fixtures/Arduino_Mega/` (per git status)
**Issue:** The git status shows untracked files `tests/fixtures/Arduino_Mega/.kicad_agent.lock` and `tests/fixtures/Arduino_Mega/~Arduino_Mega.kicad_pro.lck`. The tilde-prefixed `.lck` file is a KiCad lock file that should be in `.gitignore`, and the `.kicad_agent.lock` suggests a prior test run left a transaction lock behind. Both risk being committed accidentally and polluting the fixture directory.

**Fix:** Add `*.lck`, `~$*`, and `.kicad_agent.lock` to `.gitignore`. Verify the lock files are not already tracked.

### IN-05: FreerouteBatch.java uses undeclared exception in main signature

**File:** `src/kicad_agent/routing/FreerouteBatch.java:30`
**Issue:** `public static void main(String[] args) throws Exception` declares `throws Exception` broadly. If any of the `FileInputStream`, `FileOutputStream`, or `Integer.parseInt` calls throw, the JVM prints a stack trace and exits with code 1 — which is indistinguishable from the explicit `System.exit(1)` for the usage error. The Python side (`freerouting.py:316`) checks `returncode != 0` and reports stderr, so this works, but a narrower `throws IOException` and explicit catch with `System.exit(N)` for each failure mode would give better diagnostics.

**Fix:** Catch specific exceptions and exit with distinct codes:
```java
} catch (NumberFormatException e) {
    System.err.println("Invalid passes argument: " + e.getMessage());
    System.exit(6);
} catch (IOException e) {
    System.err.println("IO error: " + e.getMessage());
    System.exit(4);
}
```

### IN-06: test_r7_comment_sweep targets "Phase 99" references but phase number is arbitrary

**File:** `tests/test_phase99_r7_comment_sweep.py:21-30`
**Issue:** The sweep test hardcodes three specific (file, substring) pairs:
```python
targets = [
    ("src/kicad_agent/handler.py", "Phase 99 Gap 4"),
    ("src/kicad_agent/routing/pathfinder.py", "Phase 99 Gap 2"),
    ("src/kicad_agent/routing/graph.py", "Phase 99 Gap 2"),
]
```
This couples the test to the specific phase number. If the comments are later updated to reference a different phase (e.g., during a renumbering), the test breaks. The test name ("Phase 99 references present") also encodes the phase number.

**Fix:** Either (a) loosen to check that the referenced comments exist without asserting the phase number, or (b) accept the coupling as intentional (this is a regression test for the 122B -> 99 sweep, so the specificity is the point). Document the intent in the test docstring if (b).

### IN-07: test_phase99_dsn_r4_viatypes.py accesses .planning/ at test time

**File:** `tests/test_phase99_dsn_r4_viatypes.py:239-250`
**Issue:** `TestMicroviaDeferralBeadExists.test_microvia_deferral_documented` reads `.planning/phases/99-freerouting-integration-hardening/99-02-SUMMARY.md` from inside a unit test and asserts the string "microvia" appears in it. This couples test pass/fail to the presence and content of a planning artifact outside `src/`. If the SUMMARY is renamed or the phase is renumbered, the test skips (which is benign) but the coupling between code tests and planning docs is unusual.

**Fix:** This is a creative workaround for the bureaucracy §7.7 "no silent deferral" rule without Beads MCP access. Acceptable as-is, but consider moving the deferral tracking to a `DEFERRALS.md` in the phase directory or a `tool-gap` Bead once Beads is available in the test environment. Document the workaround in the test docstring (already partially done).

---

_Reviewed: 2026-06-24_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
