---
phase: 100-routingorchestrator-and-human-approval-loop
reviewed: 2026-06-25T00:00:00Z
depth: standard
files_reviewed: 17
files_reviewed_list:
  - pyproject.toml
  - src/kicad_agent/ir/pcb_ir.py
  - src/kicad_agent/parser/pcb_native_parser.py
  - src/kicad_agent/parser/pcb_native_types.py
  - src/kicad_agent/routing/audit.py
  - src/kicad_agent/routing/interactive.py
  - src/kicad_agent/routing/orchestrator.py
  - src/kicad_agent/routing/strategy.py
  - tests/test_phase100_audit.py
  - tests/test_phase100_batch.py
  - tests/test_phase100_cr01_immutability.py
  - tests/test_phase100_deterministic_baseline.py
  - tests/test_phase100_dispatch.py
  - tests/test_phase100_orchestrator.py
  - tests/test_phase100_rollback.py
  - tests/test_phase100_session_freerouting.py
  - tests/test_phase100_strategy.py
findings:
  critical: 2
  warning: 6
  info: 5
  total: 13
status: issues_found
---

# Phase 100: Code Review Report

**Reviewed:** 2026-06-25T00:00:00Z
**Depth:** standard
**Files Reviewed:** 17
**Status:** issues_found

## Summary

Phase 100 implements the `RoutingOrchestrator` (R-1 through R-7) plus the CR-01 immutability refactor of all 14 `NativeBoard` dataclasses. The frozen-dataclass work, `MappingProxyType` enforcement, Protocol-pure strategy contract, and JSONL audit with `fsync` durability are all solid and well-tested. The test suite covers R-1 through R-7 must-haves thoroughly (immutability regression, strategy validation, 10-cycle mock-DRC rollback, Freerouting ingestion, audit recovery).

However, the review surfaced **2 critical correctness issues** in `rollback_net` that defeat the H2 (UUID-based, no-regex) safety guarantee, plus **6 warnings** spanning non-atomic writes, stale `raw_content` after rollback, and a misleading audit invariant. None of the critical issues are blocked by missing tests — the rollback test passes only because the fixture's segment indices happen to line up with the UUID extractor's parent index; the approach is fragile and will silently corrupt real boards.

Cross-reference: the orchestrator imports are clean (no module-level `re`, confirmed by `test_no_regex_import_in_orchestrator`), the `push` signature matches `PersistentUndoStack.push(file_path, pre, post, op_type: str, post_mtime: int = 0)`, and `extract_uuids` returns `UUIDMap` with the expected `entries` tuple of `UUIDEntry(uuid_value, parent_type, parent_index, line_number)`.

## Critical Issues

### CR-01: rollback_net assumes UUID parent_index == NativeBoard segment index — they are computed by DIFFERENT algorithms and will diverge on real boards

**File:** `src/kicad_agent/routing/orchestrator.py:571-599`
**Issue:**

The rollback code assumes that `entry.parent_index` from `extract_uuids()` equals the position of the segment in `board.segments` (from `NativeParser`). This is **not true in general**:

1. `NativeParser._extract_segments` (pcb_native_parser.py:704-775) uses `_find_all_symbols(root, "segment")` which walks **only direct children of `(kicad_pcb ...)`**. It does NOT descend into nested contexts.

2. `_build_parent_count_map` in uuid_extractor.py:166-194 uses `re.compile(r'\(segment\b').finditer(content)` which matches **every** `(segment ...)` opening paren in the file, **including segments nested inside other blocks** (e.g., a `(segment ...)` S-expression embedded inside a `(group ...)`, `(footprint ...)` graphics, or inside `(lib_symbols ...)` if such nesting exists).

3. The `parent_index` returned by `_count_parent_index` is the **sequential count of that parent type as it appears in the raw text**, NOT the index among direct children of root.

When the file contains exactly N top-level `(segment ...)` blocks and zero nested ones, the two indices coincide (which is why `test_rollback_removes_segments_for_net` passes — the fixture and the hand-injected segment are all top-level). On any real board where a `(segment ...)` appears nested inside a `(group ...)`, the UUID `parent_index` will be higher than the `NativeBoard` index, causing the filter `entry.parent_index in seg_indices_to_remove` to either:

- **Miss the UUID entirely** (parent_index > len(board.segments)), silently leaving the routed track in place, OR
- **Match the wrong UUID** (parent_index happens to collide with a different segment's index), deleting an unrelated track.

The same flaw applies to vias (`via` parent_type). The H2 anti-pattern (no regex) is honored at the orchestrator level, but the index-based mapping reintroduces the same class of correctness bug at the UUID-mapping layer.

**Fix:**

Use the UUID value directly as the join key. The NativeBoard's `NativeSegment`/`NativeVia` do not currently carry UUIDs (only `NativeZone` and `NativeFootprint` do), so the correct fix is to either:

(A) Preferred — extract the UUID in the parser and add a `uuid` field to `NativeSegment`/`NativeVia`, then filter by UUID value rather than by parent_index:

```python
# In NativeParser._extract_segments, capture uuid like zones do:
uuid = _find_string_child(seg_block, "uuid")
# Then in rollback_net:
target_uuids = {s.uuid for s in board.segments if s.net_name == net_name}
for entry in uuid_map.entries:
    if entry.uuid_value in target_uuids and entry.parent_type == "segment":
        raw = PcbRawWriter.delete_segment(raw, entry.uuid_value)
```

(B) Minimum-stopgap — delete by UUID for every segment whose `net_name` matches, using a regex/sexp walk that is net-aware (the very approach H2 was supposed to eliminate, so not recommended).

This is a Council-blocking correctness issue. The current rollback path can corrupt boards in production while the test suite reports green.

### CR-02: rollback_net uses `pcb_path.write_text(raw, ...)` — bypasses atomic_write + hash verification used by every other write path

**File:** `src/kicad_agent/routing/orchestrator.py:616`
**Issue:**

Every other PCB mutation in this codebase goes through `PcbIR.commit_raw_content()` (pcb_ir.py:1049-1071), which performs:

1. `atomic_write(file_path, new_raw)` — temp file + `os.replace` for crash safety
2. SHA-256 hash verification on read-back (D-14)
3. Updates `_parse_result.raw_content` so subsequent reads see the new content

`rollback_net` does a bare `pcb_path.write_text(raw, encoding="utf-8")`. If the process crashes between the `delete_segment` string operations and the final write, or if two rollback calls race, the file can be left truncated or half-written. This violates the threat-model claim in the orchestrator docstring ("All writes are scoped to project_dir") and the Council C-02 atomic-write convention.

The same flaw exists at line 636 (`rollback_full`) and at orchestrator.py:485 (`pcb_path.write_text(new_content, ...)` in `_dispatch_freerouting`). Three separate non-atomic write paths in one module.

**Fix:**

Route all writes through the existing atomic helper:

```python
# At top of orchestrator.py
from kicad_agent.io.atomic_write import atomic_write

# In rollback_net (line 616):
atomic_write(pcb_path, raw)

# In rollback_full (line 636):
atomic_write(pcb_path, entry.pre_content)

# In _dispatch_freerouting (line 485):
atomic_write(pcb_path, new_content)
```

`atomic_write` is already a project dependency (imported in pcb_ir.py:1059 and used by `commit_raw_content`). Using it everywhere also gives D-14 hash verification for free.

## Warnings

### WR-01: `_dispatch_freerouting` writes the PCB BEFORE pushing post-route snapshot — the undo stack will capture the wrong "pre" state on subsequent calls

**File:** `src/kicad_agent/routing/orchestrator.py:485` and `:303-304`
**Issue:**

Execution order in `route_board`:

1. Line 222: `stack.push(pcb_path, pre_content, pre_content, op_type=_OP_TYPE_ROUTE_PRE)` — correct
2. Line 485 (inside `_dispatch_freerouting`): `pcb_path.write_text(new_content)` — mutates the file
3. Line 303: `post_content = pcb_path.read_text(...)` — reads post-mutation
4. Line 304: `stack.push(pcb_path, pre_content, post_content, op_type=_OP_TYPE_ROUTE_POST)`

The `pre_content` captured at step 1 is the pre-route content, which is correct. But the `pre_content` argument to the POST push (line 304) is the *same variable* captured at line 221. This means the POST entry's `pre_content` is the pre-route state and `post_content` is the post-route state — which is actually fine.

However, if `rollback_full` is later called, `pop_undo` returns the most recent entry (the POST entry), and restoring `entry.pre_content` only restores to the pre-route state — it does NOT restore any intermediate state between the PRE and POST pushes. For the common case this is acceptable, but the docstring at line 630 ("Pops the most recent undo entry for pcb_path and restores its pre_content") is accurate only if callers understand "pre" means "the pre_content stored at push time", which for a POST entry is the pre-route state. This is confusing.

More seriously: `pop_undo` removes the entry from the stack (persistent_undo.py:314-321). If a user calls `rollback_full` twice, the second call pops the PRE entry and restores to a state that was already restored — silent no-op masked as success.

**Fix:**

Document the PRE/POST duality explicitly in `rollback_full` docstring, OR push only a single PRE entry and have `rollback_full` always restore `pre_content` (dropping the POST push entirely since the audit log already records what happened).

### WR-02: `rollback_net` updates the file but does NOT update any `PcbIR` in-memory state — subsequent operations on a cached IR silently operate on stale content

**File:** `src/kicad_agent/routing/orchestrator.py:616`
**Issue:**

`rollback_net` takes `pcb_path` (not a `PcbIR`), so it has no way to invalidate cached IR state. If a caller holds a `PcbIR` across the rollback (e.g., the `InteractiveRoutingSession` in `interactive.py` which caches `_netlist` and `_suggestions`), subsequent `extract_netlist()` / `get_board_bounds()` calls will return data based on the pre-rollback PCB.

The 10-cycle rollback test (`test_ten_approve_reject_cycles_clean`) happens to pass because it re-parses the board every cycle via `NativeParser.parse_pcb`. But the documented public API of `RoutingOrchestrator` does not warn callers that their IR is now stale.

**Fix:**

Either (a) accept `PcbIR` instead of `pcb_path` in `rollback_net` and call `ir.commit_raw_content(raw)` (which updates `_parse_result.raw_content`), or (b) add a docstring warning that any in-memory IR for this path is invalid after rollback and must be re-parsed.

### WR-03: `_dispatch_astar` always reports `drc_clean=True` in the audit, but the route may actually cross existing tracks (no DRC is run)

**File:** `src/kicad_agent/routing/orchestrator.py:298` and `_dispatch_astar` (lines 321-384)
**Issue:**

The audit entry at line 298 hardcodes `drc_clean=True` with the comment "R-5 Open Question 2: final board DRC only". This is documented as an open question, but the audit trail is now persisted with a field that is **known to be incorrect** for individual nets. Future analysis of the audit log (the explicit purpose of T-100-02-03 Repudiation threat model) will misclassify every A*-routed net as DRC-clean.

This is a data-quality issue, not a correctness bug. But the audit trail's entire value proposition is that it is a durable, queryable record of *what actually happened*. Persisting `True` for a value that was never checked undermines that.

**Fix:**

Use a sentinel value that is distinguishable from a real PASS:

```python
drc_clean=False,  # or None if the schema allows
notes=(nr.notes + " [drc_deferred_to_board_level]").strip(),
```

OR add a separate `drc_checked: bool` field to `RoutingAuditEntry` so consumers can filter.

### WR-04: `InteractiveRoutingSession._generate_suggestions` silently skips nets with fewer than 2 pins — no audit, no warning

**File:** `src/kicad_agent/routing/interactive.py:147-149`
**Issue:**

```python
regular_netlist = {
    name: pins
    for name, pins in self._netlist.items()
    if name not in diff_pair_nets and len(pins) >= 2
}
```

Nets with 0 or 1 pins are dropped from the netlist passed to `route_all_nets`. They never appear in `_suggestions`, so the user sees no feedback that they were skipped. `summary()` then reports `"total_nets": len(self._suggestions)` which undercounts the actual net count on the board.

A net with 1 pin is legitimately un-routable, but it should at least be surfaced as a PENDING suggestion with `clearance_violations=["insufficient pins (1)"]` so the user knows it exists and can decide to ignore it.

**Fix:**

```python
for name, pins in self._netlist.items():
    if name in diff_pair_nets:
        continue
    if len(pins) < 2:
        self._suggestions[name] = RoutingSuggestion(
            net_name=name,
            path=[],
            length_mm=0.0,
            clearance_violations=[f"insufficient pins ({len(pins)})"],
        )
        continue
    # ... route normally
```

### WR-05: `route_board` builds `Pin.footprint_ref` as `f"net_{net_name}"` — destroys the actual footprint reference, breaking any downstream correlation

**File:** `src/kicad_agent/routing/orchestrator.py:200-205`
**Issue:**

```python
for net_name, pin_positions in raw_netlist.items():
    pins: list[Pin] = []
    for idx, (x, y) in enumerate(pin_positions):
        pins.append(Pin(footprint_ref=f"net_{net_name}", pad_number=str(idx), x=x, y=y))
```

`ir.extract_netlist()` (pcb_ir.py:686-714) returns `dict[str, list[(x, y)]]` — it already loses the footprint reference. The orchestrator then synthesizes a fake `footprint_ref` of the form `"net_<netname>"`. This:

1. Makes every pin on the same net appear to belong to the same (nonexistent) footprint.
2. Breaks any Phase 98 strategy that wants to reason about per-footprint pin topology.
3. Produces misleading audit data (the Pin objects are not currently logged, but if Phase 98 logs them, the fake refs will pollute the trail).

**Fix:**

Either extend `PcbIR.extract_netlist()` to return `(footprint_ref, pad_number, x, y)` tuples (preferred — the data is already available in the inner loop at pcb_ir.py:696-713), or document that `Pin.footprint_ref` is unreliable in Phase 100 and must be re-derived before Phase 98 consumes it.

### WR-06: `NativeBoard.general` field is typed `NativeGeneral` but defaults to `None`, then patched in `__post_init__` — mypy strict mode will flag this and the `# type: ignore` is fragile

**File:** `src/kicad_agent/parser/pcb_native_types.py:333`
**Issue:**

```python
general: NativeGeneral = None  # type: ignore[assignment]
```

The `__post_init__` at line 336-340 uses `object.__setattr__` to replace `None` with `NativeGeneral()`. This works at runtime, but:

1. Static analyzers see `NativeGeneral | None` semantically even though the type annotation claims `NativeGeneral`.
2. Any code that reads `board.general` between `__init__` and `__post_init__` (e.g., a subclass override, or a future `__init__` extension) would see `None`.
3. `dataclasses.replace(board, general=None)` is technically valid by type signature but would then be patched back to `NativeGeneral()` by `__post_init__` — surprising behavior.

The existing `None  # type: ignore` works but is the kind of shortcut that accumulates debt.

**Fix:**

Use a `field(default_factory=NativeGeneral)` instead — frozen dataclasses support `default_factory`:

```python
from dataclasses import dataclass, field

@dataclass(frozen=True)
class NativeBoard:
    # ...
    general: NativeGeneral = field(default_factory=NativeGeneral)
    setup: NativeSetup | None = None
```

Then delete `__post_init__`. This is cleaner, type-safe, and removes the `# type: ignore`.

## Info

### IN-01: `MappingProxyType(dict(self._properties_tuple))` rebuilds the dict on every property access

**File:** `src/kicad_agent/parser/pcb_native_types.py:142`
**Issue:**

Every call to `fp.properties` allocates a new `dict` from the tuple and wraps it in a new `MappingProxyType`. For code that calls `fp.properties.get("Reference")` in a hot loop (e.g., `get_footprint_by_ref` at pcb_ir.py:360-364 iterating over all footprints), this is O(n) dict construction per access.

This is not a correctness bug, but if Phase 98's strategy advisor reads properties for thousands of footprints, the overhead adds up. Performance issues are explicitly out of scope for v1 of this review, but noting it because the fix is trivial.

**Fix (when it matters):**

Cache the proxy on first access via `functools.cached_property`, or precompute in `__post_init__` and store as `_properties_view`.

### IN-02: `_dispatch_freerouting` parses the SES file twice (once via `import_ses_into_pcb` internally, once explicitly at line 491-492)

**File:** `src/kicad_agent/routing/orchestrator.py:470-492`
**Issue:**

`import_ses_into_pcb` already parses the SES to extract wires/vias. Then the orchestrator re-reads `fr_result.ses_path` and calls `parse_ses` again at line 491-492 to get per-net attribution. This doubles parse cost and adds an extra file read.

**Fix:**

Have `import_ses_into_pcb` return the parsed `SesParseResult` alongside `(content, stats)`, or accept a pre-parsed result. Out of scope for correctness, but worth a follow-up Bead.

### IN-03: `_check_unsupported` logs warnings for elements that have known unsupported status, but the warning fires per-occurrence — noisy on large boards

**File:** `src/kicad_agent/parser/pcb_native_parser.py:180-194`
**Issue:**

For a board with 500 `(thermal_relief_pads ...)` entries, this logs 500 warnings. Consider deduplicating with a "seen" set, or aggregating into a single summary warning at the end of `_build_board`.

**Fix:**

```python
# Aggregate counts instead of per-occurrence warnings
_unsupported_counts: dict[str, int] = defaultdict(int)
# ... in _check_unsupported:
_unsupported_counts[block_name] += 1
# ... at end of _build_board:
for name, count in _unsupported_counts.items():
    logger.warning("Unsupported element '%s' appeared %d times (data preserved in raw_content)", name, count)
```

### IN-04: Test `test_no_regex_import_in_orchestrator` reads source via relative path — breaks if pytest is invoked from a different cwd

**File:** `tests/test_phase100_rollback.py:76`
**Issue:**

```python
content = Path("src/kicad_agent/routing/orchestrator.py").read_text()
```

This is a relative path. If pytest is run from a directory other than the repo root (e.g., `cd tests && pytest`), the read fails. The pyproject.toml configures `pythonpath = ["src", "tests"]` which means imports work, but raw file reads do not.

**Fix:**

Use `Path(__file__).parent.parent / "src" / "kicad_agent" / "routing" / "orchestrator.py"` to make the test cwd-independent.

### IN-05: `RoutingAuditLog.append` opens/closes the file on every call — 100 nets = 100 open/write/fsync/close cycles

**File:** `src/kicad_agent/routing/audit.py:138-149`
**Issue:**

Durability per entry is correct (H5), but the overhead is noticeable for large boards. The fsync is the expensive part and must stay. The open/close overhead is smaller but avoidable.

This is acceptable for Phase 100. If Phase 98 logs many more entries per run, consider opening the file once in `__init__` and keeping it open for the lifetime of the orchestrator.

**Fix:** None needed for v1. Document as a known trade-off (durability > throughput) in the class docstring, which it already is.

---

## Coverage Assessment (R-1 through R-7)

| Requirement | Coverage | Notes |
|---|---|---|
| R-1 Strategy Protocol + Deterministic | Strong | `test_phase100_strategy.py`, `test_phase100_dispatch.py` cover purity, frozen, all 5 dispatch cases, priority ordering |
| R-2 Dispatch heuristics | Strong | All 5 dispatch cases + L1 priority ordering tested |
| R-3 InteractiveSession + Freerouting ingestion | Strong | `test_phase100_session_freerouting.py` covers wire-to-suggestion, net_filter, unknown nets |
| R-4 Rollback | **Gaps** | Tests pass but CR-01 (index divergence) means the test only covers the happy path. No test for nested `(segment ...)` inside `(group ...)` or other parent contexts |
| R-5 Audit trail | Strong | `test_phase100_audit.py` covers JSONL format, query, enum round-trip, truncated-line recovery (H5) |
| R-6 Deterministic baseline within 5% | Conditional | `test_phase100_deterministic_baseline.py` is `@slow` + `@skipif(not is_freerouting_available())` — will be skipped in most CI runs |
| R-7 Batch orchestration | Strong | `test_phase100_batch.py`, `test_phase100_orchestrator.py` cover end-to-end, result schema, H4 validation |

## Security Posture

- No `shell=True` anywhere in the subprocess path (`freerouting.py:311` uses a list)
- No hardcoded secrets
- No `eval` / `exec` / `innerHTML` patterns
- Depth pre-scan (`_pre_scan_depth`) correctly rejects maliciously nested content before `sexpdata.loads`
- Thread safety explicitly documented as NOT thread-safe (M4) — correct for the current single-orchestrator-per-thread pattern
- The CR-01 (index divergence) and CR-02 (non-atomic writes) findings are correctness issues, not direct security vulnerabilities, but CR-02 weakens the audit-trail integrity story claimed in the threat model

## SLC Compliance

- No stubs or TODOs without tickets
- No workarounds ("it works but...")
- CR-01 and CR-02 must be resolved before this phase ships — both are "the right way or no way" issues per the SLC mindset

---

_Reviewed: 2026-06-25T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
