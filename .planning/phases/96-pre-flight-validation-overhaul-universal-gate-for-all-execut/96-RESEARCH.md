# Phase 96: Pre-flight Validation Overhaul - Research

**Researched:** 2026-06-17
**Domain:** Execution pipeline validation gates, silent failure hardening, structural fragility
**Confidence:** HIGH

## Summary

Phase 96 extends the existing PreAnalysisGate (schematic-only) into a UniversalPreFlightGate covering ALL execution paths: `execute_schematic()`, `execute_pcb()`, `execute_cross_file()`, and `execute_batch()`. The existing gate (542+ lines in `pre_analysis.py`) covers 21 schematic mutation ops with overlap detection, collision zones, pin resolution, wire collision, ref validation, and label duplication. PCB operations currently bypass the gate entirely at lines 430-503 of `execution.py`.

The batch executor silently swallows per-op exceptions (lines 321-332 of `batch_executor.py`), marking them as failed but continuing to mutate the file and serialize. The lock file creation silently passes on OSError (`execution.py:89-90`). Transaction cleanup silently passes on `FileNotFoundError` and `OSError` (`transaction.py:226-234`). These silent failure patterns mask data corruption.

PCB-specific pre-flight checks are feasible because PcbIR exposes `get_footprint_pads()`, `get_net_pads()`, `get_footprint_by_ref()`, `get_net_by_name()`, and `extract_netlist()` -- sufficient for pad-count comparison, net connectivity, and footprint overlap checks. The native parser (NativeBoard) provides the same data via `NativeFootprint.pads` and `NativeNet`.

**Primary recommendation:** Extend PreAnalysisGate with file-type dispatch (`_analyze_pcb()`, `_analyze_cross_file()`) and wire into `execute_pcb()` and `execute_cross_file()` at the same position where `execute_schematic()` currently calls the gate (lines 344-357 of `execution.py`).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- D-01: Extend PreAnalysisGate into UniversalPreFlightGate that wraps ALL execution paths -- not just `execute_schematic()`. Gate must be called in `execute_pcb()`, `execute_cross_file()`, and `execute_batch()` at `src/kicad_agent/ops/execution.py`.
- D-02: Gate uses file-type dispatch -- `analyze_schematic()`, `analyze_pcb()`, `analyze_cross_file()` -- each with type-specific checks. Single `analyze()` entry point dispatches based on file extension and operation type.
- D-03: Batch operations MUST use cumulative IR state. After each op in a batch, the gate checks the next op against the mutated state, not the original.
- D-04: All gate checks return a `GateResult` with `blockers` (prevent execution) and `warnings` (log but proceed). No exceptions -- every check must produce a structured result.
- D-05: PCB pre-flight checks: swap_footprint pad count validation, remove_net connected pad blocking, move_footprint overlap check, zone overlap warnings.
- D-06: Cross-file pre-flight checks: propagate_symbol_change lib_id validation, repopulate_pcb_from_schematic ERC check, rebuild_pcb_nets 50% change threshold.
- D-07: Schematic operation-specific checks: swap_symbol pin count compatibility, duplicate/array_replicate overlap, remove_labels wire reference check, add_wire endpoint validation, regenerate_wiring force requirement.
- D-08: batch_executor.py -- On individual op failure, stop batch and rollback. Use existing Transaction/undo infrastructure.
- D-09: transaction.py snapshot cleanup -- Remove `except OSError: pass` suppression. Log cleanup failures loudly.
- D-10: execution.py lock file failures -- MUST raise LockError instead of silently continuing.
- D-11: repair_wires.py and persistent_undo.py -- Convert silent continues to logged failures with WARNING level.
- D-12: Remove `--force` flag from handlers/pcb_transfer.py.
- D-13: pcb_raw_writer.py -- Replace hardcoded net number `1` in regex substitutions.
- D-14: pcb_ir.py `commit_raw_content()` MUST verify write by reading back and comparing content hash.
- D-15: execution.py:628-637 cross-file path validation must check valid KiCad file extensions.
- D-16: create_file.py -- Validate generated content starts with valid KiCad S-expression header before writing.

### Claude's Discretion
- Test organization: group new tests by category (gate_schematic, gate_pcb, gate_crossfile, batch_rollback, structural) following existing `tests/test_pre_analysis.py` patterns
- Whether to extract the universal gate into its own module (`ops/universal_gate.py`) or extend the existing `ops/pre_analysis.py`
- Exact warning/blocker thresholds (e.g., 20% pin count difference in D-07, 50% net assignment change in D-06)
- Whether batch rollback should use Transaction snapshots or the PersistentUndoStack

### Deferred Ideas (OUT OF SCOPE)
- kiutils serialization bugs (known bug, complex fix -- separate phase)
- Auto_route pre-flight clearance estimation (requires spatial engine integration)
- Post-mutation automatic DRC/ERC running (performance concern -- expensive for every operation)
- Rate limiting on validation checks (no current need)
</user_constraints>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| PCB pre-flight gate checks | API / Backend (execution.py) | -- | Gate runs server-side before mutation, not in any client tier |
| Cross-file pre-flight validation | API / Backend (execution.py) | -- | Multi-file coordination is backend-only logic |
| Batch cumulative IR tracking | API / Backend (batch_executor.py) | -- | Re-parse after each mutation is a server-side operation |
| Batch rollback on failure | API / Backend (batch_executor.py + transaction.py) | -- | Transaction rollback is a server-side file operation |
| Silent failure hardening | API / Backend (all execution paths) | -- | Logging/error handling is server-side |
| Structural fragility fixes | API / Backend (ir/, ops/) | -- | File write verification, content validation |
| Pad count / net connectivity data | Database / Storage (PcbIR from parsed file) | -- | IR is an in-memory representation of stored PCB data |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `kiutils` | 1.4.8 [VERIFIED: codebase] | KiCad file I/O for schematic + PCB (kiutils path) | Existing project dependency. Provides Board/Schematic/Footprint objects. |
| `sexpdata` | 1.0.0 [VERIFIED: codebase] | Low-level S-expression parsing | Existing project dependency. Used by NativeParser. |
| `Pydantic` | 2.12.5 [VERIFIED: codebase] | Schema validation for operations | Existing project dependency. All operation schemas are Pydantic models. |
| Python stdlib `dataclasses` | -- | GateResult/PreAnalysisFinding types | Already used throughout (frozen=True for Finding, mutable for Result). |
| Python stdlib `re` | -- | Net number regex in pcb_raw_writer.py | Already used for S-expression manipulation. |
| Python stdlib `hashlib` | -- | Content hash verification in commit_raw_content | Will be added for D-14 write verification. |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `networkx` | [existing] | Net connectivity graph (for ERC-like pre-flight) | Cross-file net connectivity validation |
| `Shapely` | [existing] | Spatial overlap detection for PCB footprints | PCB move_footprint overlap check (D-05) |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Extending `pre_analysis.py` | New `ops/universal_gate.py` | New file is cleaner separation but breaks existing imports. Recommend extending with internal dispatch methods -- lower blast radius. |
| Transaction rollback for batch | PersistentUndoStack | Transaction already exists per-file in batch_executor. UndoStack is higher-level. Transaction is correct layer for this. |

**Installation:** No new packages required. All dependencies already installed.

**Version verification:** [VERIFIED: codebase grep] kiutils 1.4.8 is the only KiCad file I/O library needed. No external validation tools needed -- all checks are code-level.

## Architecture Patterns

### System Architecture Diagram

```
                          Operation JSON
                               |
                               v
                     +------------------+
                     |   executor.py    |  Route by file extension + op_type
                     +------------------+
                          |  |  |  |
              +-----------+  |  +-----------+
              |              |              |
              v              v              v
     +----------------+  +------------+  +-----------------+
     | execute_sch()  |  |execute_pcb |  |execute_crossfile|
     | gate.already() |  | gate.NONE  |  | gate.NONE       |
     +----------------+  +------------+  +-----------------+
              |              |              |
              +--------------+--------------+
                               |
                               v
                     +------------------+
                     | UniversalGate    |  D-02: dispatch by file ext + op
                     | .analyze()       |
                     +------------------+
                      /         |         \
                     v          v          v
              +----------+ +----------+ +----------+
              |_analyze  | |_analyze  | |_analyze  |
              |_schematic| |_pcb()    | |_crossfile|
              +----------+ +----------+ +----------+
                     |          |          |
                     v          v          v
              GateResult  GateResult  GateResult
              {blockers, {blockers,  {blockers,
               warnings}  warnings}   warnings}
                     |          |          |
                     v          v          v
              BLOCK or   BLOCK or    BLOCK or
              PROCEED    PROCEED     PROCEED
```

### Recommended Project Structure

```
src/kicad_agent/ops/
  pre_analysis.py          # EXTEND: add _analyze_pcb(), _analyze_cross_file(), expanded _MUTATION_OP_TYPES
  execution.py              # MODIFY: insert gate calls in execute_pcb() and execute_cross_file()
  batch_executor.py         # MODIFY: cumulative IR state + stop-and-rollback on failure (D-08)
  validation_gates.py       # EXISTING: pre_pcb_schematic_gate(), check_erc_clean() -- reusable
  pcb_raw_writer.py         # MODIFY: replace hardcoded net 1 (D-13)
  repair_wires.py           # MODIFY: silent continue -> logged WARNING (D-11)
  create_file.py            # MODIFY: content header validation (D-16)
  persistent_undo.py        # MODIFY: silent failures -> logged WARNING (D-11)
  handlers/pcb_transfer.py  # MODIFY: remove force flag (D-12)

src/kicad_agent/ir/
  pcb_ir.py                 # MODIFY: commit_raw_content() write verification (D-14)
  transaction.py             # MODIFY: _cleanup_snapshot() loud logging (D-09)

tests/
  test_pre_analysis.py      # EXTEND: new TestPreFlightGatePcb, TestPreFlightGateCrossfile, etc.
  test_batch_executor.py     # EXTEND: batch rollback tests
```

### Pattern 1: GateResult Dispatch (D-02)

**What:** Single `analyze()` method dispatches to type-specific analyzers based on file extension and op_type.

**When to use:** Every execution path must hit this gate before mutation.

**Example:**

```python
# Source: [VERIFIED: codebase pre_analysis.py:140-181]
class PreAnalysisGate:
    def analyze(self, op: Any, ir: Any, file_path: Path) -> PreAnalysisResult:
        result = PreAnalysisResult()
        op_type = getattr(op, "op_type", None)
        ext = Path(file_path).suffix

        # Route to file-type-specific analyzer (D-02)
        if ext == ".kicad_pcb":
            return self._analyze_pcb(op, ir, file_path)
        elif ext == ".kicad_sch":
            return self._analyze_schematic(op, ir, file_path)
        else:
            return result  # Non-KiCad files: no checks
```

### Pattern 2: Batch Cumulative IR State (D-03)

**What:** After each successful op in a batch, re-parse the file to get mutated IR for the next op's pre-flight check.

**When to use:** All batch operations with multiple mutations to the same file.

**Example:**

```python
# Current batch_executor.py Phase 3 (lines 288-345) parses once then mutates.
# D-03 requires re-parse after each mutation:
for file_path in file_order:
    ops_for_file = file_ops[file_path]
    ir = ir_map[file_path]

    for op in ops_for_file:
        root = op.root
        # Pre-flight check against CURRENT (possibly mutated) IR
        pre = gate.analyze(root, ir, file_path)
        if pre.blocked:
            raise BlockedError(pre.blockers)

        # Execute mutation
        details = dispatch_pcb(root.op_type, root, ir, file_path)

        # D-03: Re-parse after mutation for next op's check
        if file_path.suffix == ".kicad_pcb":
            fresh_result = parse_pcb(file_path)
            fresh_uuid = extract_uuids(fresh_result.raw_content, "pcb")
            ir = PcbIR(_parse_result=fresh_result, _uuid_map=fresh_uuid)
```

### Pattern 3: Transaction Rollback on Batch Failure (D-08)

**What:** Stop batch execution on individual op failure and rollback ALL changes in the batch using Transaction.

**When to use:** Currently batch silently swallows exceptions (lines 321-332). New behavior: raise, let Transaction.__exit__ auto-rollback.

**Example:**

```python
# Current (FORBIDDEN -- lines 321-332 of batch_executor.py):
except Exception as e:
    logger.error("Batch op failed: %s on %s: %s", ...)
    all_results.append({"success": False, ...})
    # CONTINUES MUTATING -- this is the silent failure bug

# New (D-08):
except Exception as e:
    logger.error("Batch op failed: %s on %s: %s", ...)
    # Re-raise to trigger Transaction.__exit__ -> auto-rollback
    raise BatchOpFailedError(root.op_type, root.target_file, str(e))
```

### Pattern 4: Write Verification (D-14)

**What:** After atomic_write, read back and compare hash to verify write integrity.

**When to use:** `commit_raw_content()` in pcb_ir.py -- raw PCB writes bypass kiutils serialization.

**Example:**

```python
def commit_raw_content(self, new_raw: str) -> None:
    expected_hash = hashlib.sha256(new_raw.encode("utf-8")).hexdigest()
    atomic_write(self._parse_result.file_path, new_raw)
    # D-14: Verify write
    actual = self._parse_result.file_path.read_text(encoding="utf-8")
    actual_hash = hashlib.sha256(actual.encode("utf-8")).hexdigest()
    if actual_hash != expected_hash:
        raise IOError(
            f"Write verification failed for {self._parse_result.file_path}: "
            f"expected {expected_hash[:16]}..., got {actual_hash[:16]}..."
        )
```

### Anti-Patterns to Avoid

- **Gate bypass in batch_executor.py:** Current code at line 247 only calls gate for `.kicad_sch` files. PCB files in a batch get zero pre-flight checks. Fix: extend the `if file_path.suffix == ".kicad_sch":` branch to also handle `.kicad_pcb`.
- **Silent exception swallowing:** `batch_executor.py:321-332` catches Exception and continues. This masks data corruption -- the file is serialized with partial mutations applied. Fix: re-raise to trigger Transaction rollback.
- **Lock file best-effort:** `execution.py:89-90` does `except OSError: pass` on lock file creation. Concurrent writes to KiCad files cause silent corruption. Fix: raise LockError (D-10).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Pad count comparison | Custom regex on raw S-expression | `len(footprint.pads)` from PcbIR/NativeBoard | NativeBoard and kiutils Board both expose `pads` as a list. One-liner comparison. |
| Footprint overlap detection | Custom bounding box math | Shapely `box.intersection()` (already in project) | Project already uses Shapely for spatial analysis (Phase 51+). `import` and reuse. |
| File content hash verification | Custom checksum | `hashlib.sha256` | stdlib, zero-dependency. |
| Net connectivity check | Wire graph traversal | `PcbIR.get_net_pads()` | Returns (footprint_libId, pad_number) tuples. Zero connected pads = safe to remove. |
| Batch rollback mechanism | Custom backup/restore | `Transaction.rollback()` | Transaction already creates file snapshots and has rollback with fcntl locking. |
| Lock file semantics | Custom PID-based locking | `Transaction` with `fcntl.flock` | Transaction already handles stale lock cleanup, symlink protection, and permissions. |
| ERC running | Custom ERC parser | `validation.erc_drc.run_erc()` | Already exists and returns structured results. |

**Key insight:** All data needed for pre-flight checks is already exposed through PcbIR methods and NativeBoard attributes. No new parsing infrastructure needed.

## Runtime State Inventory

> Not a rename/refactor phase. Omitted.

## Common Pitfalls

### Pitfall 1: Gate check order matters for PCB operations

**What goes wrong:** If `swap_footprint` check runs pad-count comparison BEFORE verifying the new footprint exists in the library, you get a confusing error about pad counts instead of "footprint not found."

**Why it happens:** PcbIR.get_footprint_by_ref() only finds footprints already on the board, not in external libraries. Pad count comparison requires resolving the new footprint from the library first.

**How to avoid:** Order PCB checks: (1) footprint exists in library, (2) pad count comparison, (3) net connectivity impact. Check 1 blocks early with a clear message. Check 2 only runs if check 1 passes.

**Warning signs:** Unit tests that mock the library resolver -- they may skip the existence check entirely.

### Pitfall 2: Batch cumulative IR re-parse is expensive

**What goes wrong:** Re-parsing a large PCB (1000+ components) after every op in a 50-op batch makes batch execution 50x slower.

**Why it happens:** `parse_pcb()` reads the full file from disk, runs sexpdata parsing, and builds the kiutils Board object. For PCB files, this is O(n) where n = file size.

**How to avoid:** Only re-parse when the IR was actually mutated (check `ir.dirty` flag). For read-only operations in a batch (queries), skip re-parse. For the D-03 requirement, re-parse after each MUTATION op, not after each op in general.

**Warning signs:** Batch execution time > 2x the single-op execution time for the same number of operations.

### Pitfall 3: Transaction rollback in batch does not undo all files

**What goes wrong:** A batch operates on 3 files. Op on file 2 fails. File 1's Transaction already committed. File 1 is now mutated but file 2 and 3 are rolled back -- inconsistent state.

**Why it happens:** `batch_executor.py` opens a Transaction per file (line 293) and commits per-file (line 345). If an op on file 2 fails, file 1's commit is already done.

**How to avoid:** Use AtomicOperation (from `crossfile/atomic.py`) instead of per-file Transaction for multi-file batches. Or, change the batch execution order: apply ALL mutations in memory, then commit ALL files at once. The existing `AtomicOperation` already handles multi-file rollback.

**Warning signs:** Test with a batch that touches 2+ files, force failure on the 2nd file, check file 1's state.

### Pitfall 4: NativeParser vs kiutils data access divergence

**What goes wrong:** Pre-flight check works for kiutils-backed PcbIR but fails for NativeBoard-backed PcbIR because attribute names differ (e.g., `pad.net.name` vs `pad.net_name`).

**Why it happens:** PcbIR has `_is_native` property and both kiutils and native paths. The gate code must handle both access patterns.

**How to avoid:** Always use PcbIR methods (`get_footprint_pads()`, `get_net_pads()`) rather than directly accessing `fp.pads[i].net.name`. The PcbIR methods already handle the native/kiutils branching.

**Warning signs:** Any code path that accesses `fp.pads` directly instead of going through PcbIR methods.

### Pitfall 5: Lock file becomes a single point of failure

**What goes wrong:** D-10 converts the silent `except OSError: pass` to `raise LockError`. But if the project directory is read-only (e.g., a fixture directory in tests), all operations fail.

**Why it happens:** `_check_concurrent_access` creates a lock file in the target file's parent directory. Tests often use read-only fixture directories.

**How to avoid:** Make LockError catchable and non-fatal. Tests should be able to skip lock checks. Consider a `_TESTING` mode or making the lock check a warning (not a hard error) when the directory is read-only. The CONTEXT.md says "MUST raise LockError" but the implementation should handle the edge case gracefully.

## Code Examples

### Current Gate Call Site (schematic only)

```python
# Source: [VERIFIED: execution.py:343-357]
# execute_schematic() -- gate IS called
gate = get_pre_analysis_gate()
pre_result = gate.analyze(root, ir, file_path)
if pre_result.blocked:
    blocker_msgs = [f.message for f in pre_result.blockers]
    return {
        "success": False,
        "operation": root.op_type,
        "target_file": root.target_file,
        "pre_analysis": pre_result.to_dict(),
        "error": f"Pre-analysis blocked: {'; '.join(blocker_msgs)}",
    }
```

### Missing Gate Call Site (PCB -- NO gate)

```python
# Source: [VERIFIED: execution.py:430-472]
# execute_pcb() -- gate is NOT called between parse and Transaction
def execute_pcb(op, file_path, cache, undo_stack):
    # ... parse PcbIR ...
    # <<< NO GATE CALL HERE -- this is where the gap is >>>
    with Transaction(file_path) as txn:
        details = dispatch_pcb(root.op_type, root, ir, file_path)
        # ... serialize ...
```

### Missing Gate Call Site (cross-file -- NO gate)

```python
# Source: [VERIFIED: execution.py:613-665]
# execute_cross_file() -- gate is NOT called
def execute_cross_file(op, file_path, base_dir, cache, undo_stack):
    # ... resolve paths, security checks ...
    # <<< NO GATE CALL HERE -- this is where the gap is >>>
    with AtomicOperation(file_paths) as atomic:
        handler = _CROSSFILE_HANDLERS.get(root.op_type)
        details = handler(root, ir_map, base_dir)
```

### PCB Pad Count Comparison for swap_footprint

```python
# Source: [VERIFIED: pcb_ir.py:320-557, pcb_native_types.py:84-100]
# PcbIR.swap_footprint() preserves pad-to-net connections by pad number matching.
# Pre-flight check: compare old vs new pad counts BEFORE swap.

def _check_swap_footprint_pads(self, op, ir, result):
    """D-05: Validate new footprint has >= pad count of old."""
    ref = op.reference
    fp = ir.get_footprint_by_ref(ref)
    if fp is None:
        result.blockers.append(PreAnalysisFinding(
            severity="blocker",
            category="unknown_ref",
            message=f"Footprint '{ref}' not found on PCB",
            details={"reference": ref},
        ))
        return

    old_pad_count = len(fp.pads)
    # NOTE: new footprint not on board yet -- need library resolution
    # For pre-flight, use op.new_footprint_lib_id to resolve from library
    # and count pads. This requires adding a library resolution step.

    # Alternative (simpler): check in handler after library load,
    # before mutation. Pre-flight can warn if old_pad_count > expected
    # threshold based on the new footprint's lib_id pattern.
```

### Current Batch Silent Failure (FORBIDDEN)

```python
# Source: [VERIFIED: batch_executor.py:321-332]
# D-08: This pattern must be replaced with re-raise
except Exception as e:
    logger.error(
        "Batch op failed: %s on %s: %s",
        root.op_type, root.target_file, e,
    )
    all_results.append({
        "success": False,
        "operation": root.op_type,
        "target_file": root.target_file,
        "error": str(e),
        "error_type": type(e).__name__,
    })
    # Execution CONTINUES with next op -- file is partially mutated
```

### Transaction Cleanup Silent Pass (D-09 target)

```python
# Source: [VERIFIED: transaction.py:218-237]
def _cleanup_snapshot(self) -> None:
    try:
        if self._snapshot_path and self._snapshot_path.exists():
            self._snapshot_path.unlink()
    except FileNotFoundError:
        pass  # D-09: This is acceptable (already cleaned up)
    try:
        if self._snap_dir:
            snap_dir_path = Path(self._snap_dir)
            if snap_dir_path.exists():
                snap_dir_path.rmdir()
    except (FileNotFoundError, OSError):
        pass  # D-09: THIS is the problem -- OSError silently swallowed
        # Should log: logger.warning("Failed to cleanup snapshot: %s", exc)
```

### Hardcoded Net Number (D-13 target)

```python
# Source: [VERIFIED: pcb_raw_writer.py:238-242]
if field == "net_name":
    # Replace (net N "old_name") with (net N "new_name")
    block = re.sub(
        r'\(net\s+\d+\s+"[^"]*"\)',
        f'(net 1 "{value}")',  # <-- HARDCODED net 1
        block,
        count=1,
    )
# D-13: Replace with actual net ID from PcbIR
# net = ir.get_net_by_name(value)
# net_number = net.number if net else 0
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Schematic-only pre-flight gate | Universal gate for all file types | Phase 96 (this phase) | Closes PCB and cross-file validation gaps |
| Silent exception swallowing in batch | Stop-and-rollback on failure | Phase 96 (this phase) | Prevents partial mutation corruption |
| Best-effort lock file creation | LockError on failure | Phase 96 (this phase) | Prevents concurrent write corruption |
| Write without read-back verification | Hash-verified writes | Phase 96 (this phase) | Detects silent write corruption |
| Force flag bypasses validation | No force flag in production handlers | Phase 96 (this phase) | Eliminates unsafe validation bypass |

**Deprecated/outdated:**
- `_MUTATION_OP_TYPES` frozenset in `pre_analysis.py` only lists schematic ops. Must be expanded to include PCB and cross-file mutation ops.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | PcbIR methods (get_footprint_pads, get_net_pads, get_footprint_by_ref) work identically for both native and kiutils-backed IRs | Architecture Patterns | Pre-flight checks may fail for native-only PCBs. LOW risk -- PcbIR methods handle branching internally (verified in code). |
| A2 | Resolving a new footprint's pad count from library at pre-flight time is feasible without parsing the entire .kicad_mod file | PCB Checks (D-05) | May need to add a lightweight pad-count-only parse or accept a warning-only check for swap_footprint pad count. MEDIUM risk. |
| A3 | Batch cumulative IR re-parse (D-03) will not cause unacceptable performance regression | Pattern 2 (Batch IR) | For large PCBs with many batch ops, this could be very slow. Need per-file dirty-check to skip re-parse for unchanged files. MEDIUM risk. |
| A4 | The `force` parameter in `handle_update_from_schematic` is only used by CLI and never by MCP | Structural Fixes (D-12) | If MCP callers somehow pass force=True, removing the parameter would break them. LOW risk -- code comment explicitly says "CLI-only bypass flag." |
| A5 | Cross-file operations only touch `.kicad_sch` and `.kicad_pcb` files | Cross-file checks (D-15) | If cross-file ops are extended to `.kicad_sym` or `.kicad_mod` in a future phase, the valid extension list needs updating. LOW risk. |

## Open Questions

1. **How to resolve new footprint pad count for swap_footprint pre-flight?**
   - What we know: The old footprint's pads are available via `ir.get_footprint_pads(ref)`. The new footprint is specified by `lib_id` but not yet loaded.
   - What's unclear: Whether `lib_resolver.resolve_footprint_path()` can return a parseable .kicad_mod fast enough for pre-flight, or whether we should just parse pad count from the file.
   - Recommendation: Add a lightweight `count_footprint_pads(lib_id)` utility that parses only the pad count from a .kicad_mod file (regex or sexpdata, not full kiutils parse).

2. **Should the gate be a separate module or extend pre_analysis.py?**
   - What we know: `pre_analysis.py` is 542+ lines and handles only schematics. Adding PCB + cross-file checks would push it to 900+ lines.
   - What's unclear: Whether the planner prefers a single gate class with internal dispatch or separate modules with a facade.
   - Recommendation: Extend `pre_analysis.py` with `_analyze_pcb()` and `_analyze_cross_file()` private methods. Keep the single `analyze()` entry point. If the file exceeds 800 lines, the planner should extract PCB checks into `pre_analysis_pcb.py` and cross-file into `pre_analysis_crossfile.py`.

3. **Batch rollback scope: per-file or entire batch?**
   - What we know: Current batch_executor opens one Transaction per file and commits per-file. D-08 says "rollback all changes in the batch."
   - What's unclear: If op 3 of 5 fails on file_A, should we also rollback file_B's ops that already committed?
   - Recommendation: Per-file rollback is sufficient for the common case (batch ops target one file). For multi-file batches, the existing `AtomicOperation` from `crossfile/atomic.py` provides multi-file rollback. Wire the batch executor to use `AtomicOperation` when multiple files are involved.

## Environment Availability

> Step 2.6: SKIPPED (no external dependencies identified -- all tools are existing codebase modules)

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest [VERIFIED: codebase conftest.py] |
| Config file | pyproject.toml ( pytest section ) |
| Quick run command | `python3 -m pytest tests/test_pre_analysis.py -x -q` |
| Full suite command | `python3 -m pytest tests/test_pre_analysis.py tests/test_batch_executor.py -v` |

### Phase Requirements -> Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| D-01 | Gate called in execute_pcb and execute_cross_file | unit | `pytest tests/test_pre_analysis.py::TestPreFlightGatePcb -x` | No -- Wave 0 |
| D-02 | File-type dispatch routes to correct analyzer | unit | `pytest tests/test_pre_analysis.py::TestGateDispatch -x` | No -- Wave 0 |
| D-03 | Batch re-parses IR after each mutation | unit | `pytest tests/test_batch_executor.py::TestCumulativeIR -x` | No -- Wave 0 |
| D-04 | GateResult has blockers and warnings | unit | (existing -- TestPreAnalysisResult) | Yes |
| D-05 | PCB swap_footprint pad count check | unit | `pytest tests/test_pre_analysis.py::TestPcbSwapFootprint -x` | No -- Wave 0 |
| D-06 | Cross-file ERC check before repopulate | unit | `pytest tests/test_pre_analysis.py::TestCrossFileErcGate -x` | No -- Wave 0 |
| D-07 | Schematic swap_symbol pin count check | unit | `pytest tests/test_pre_analysis.py::TestSwapSymbolPinCount -x` | No -- Wave 0 |
| D-08 | Batch stops and rolls back on op failure | unit | `pytest tests/test_batch_executor.py::TestBatchRollback -x` | No -- Wave 0 |
| D-09 | Transaction cleanup logs OSError | unit | `pytest tests/test_transaction.py -x -k cleanup` | No -- Wave 0 |
| D-10 | Lock file failure raises LockError | unit | `pytest tests/test_execution.py -x -k lock` | No -- Wave 0 |
| D-11 | repair_wires/persistent_undo log warnings | unit | `pytest tests/test_pre_analysis.py -x -k silent_failure` | No -- Wave 0 |
| D-12 | Force flag removed from pcb_transfer | unit | `pytest tests/test_pcb_transfer.py -x -k force` | No -- Wave 0 |
| D-13 | pcb_raw_writer uses actual net ID | unit | `pytest tests/test_pcb_raw_writer.py -x -k net_id` | No -- Wave 0 |
| D-14 | commit_raw_content verifies write | unit | `pytest tests/test_pcb_ir.py -x -k commit_verify` | No -- Wave 0 |
| D-15 | Cross-file validates file extensions | unit | `pytest tests/test_execution.py -x -k crossfile_ext` | No -- Wave 0 |
| D-16 | create_file validates content header | unit | `pytest tests/test_create_file.py -x -k header` | No -- Wave 0 |

### Sampling Rate

- **Per task commit:** `python3 -m pytest tests/test_pre_analysis.py -x -q`
- **Per wave merge:** `python3 -m pytest tests/test_pre_analysis.py tests/test_batch_executor.py -v`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `tests/test_pre_analysis.py` -- add TestPreFlightGatePcb, TestPreFlightGateCrossfile, TestGateDispatch classes
- [ ] `tests/test_batch_executor.py` -- add TestCumulativeIR, TestBatchRollback classes
- [ ] `tests/test_execution.py` -- add lock file and cross-file extension validation tests
- [ ] `tests/test_pcb_ir.py` -- add commit_raw_content verification tests

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | -- |
| V3 Session Management | no | -- |
| V4 Access Control | no | -- |
| V5 Input Validation | yes | Pre-flight gate validates all operation inputs before mutation (gate IS the validation layer) |
| V6 Cryptography | no | -- |

### Known Threat Patterns for Python / File Mutation

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Concurrent file corruption | Tampering | D-10: LockError on lock file failure (fcntl already in Transaction) |
| Silent write corruption | Tampering | D-14: Hash-verified writes in commit_raw_content |
| Partial batch mutation | Tampering | D-08: Stop-and-rollback on individual op failure |
| Path traversal in cross-file ops | Tampering | Already handled: T-24-01 path confinement in execution.py:629-634 |
| Symlink TOC/TOU | Spoofing | Already handled: Transaction checks is_symlink before resolve() |

## Sources

### Primary (HIGH confidence)

- `src/kicad_agent/ops/pre_analysis.py` -- Full 542+ line implementation read. Class structure, method signatures, gate integration points verified.
- `src/kicad_agent/ops/execution.py` -- Full 700 line implementation read. All execution paths mapped, gate call sites identified (schematic: line 344, PCB: NONE, cross-file: NONE).
- `src/kicad_agent/ops/batch_executor.py` -- Full 371 line implementation read. Silent failure at lines 321-332 verified. Pre-analysis gate only for schematics at line 247.
- `src/kicad_agent/ir/transaction.py` -- Full implementation read. Cleanup silent pass at lines 226-234. Transaction.rollback() and auto-rollback in __exit__ verified.
- `src/kicad_agent/ir/pcb_ir.py` -- Key methods verified: get_footprint_pads(), get_net_pads(), get_footprint_by_ref(), get_net_by_name(), commit_raw_content(), from_native().
- `src/kicad_agent/parser/pcb_native_types.py` -- NativeBoard, NativeFootprint, NativePad, NativeZone, NativeNet types verified for PCB data access.
- `src/kicad_agent/crossfile/atomic.py` -- AtomicOperation multi-file rollback verified.

### Secondary (MEDIUM confidence)

- `src/kicad_agent/ops/pcb_raw_writer.py` -- Hardcoded net 1 at line 242 verified via grep.
- `src/kicad_agent/ops/create_file.py` -- Content header validation gap confirmed (no check exists).
- `src/kicad_agent/ops/handlers/pcb_transfer.py` -- Force flag at lines 201-246 verified.
- `tests/test_pre_analysis.py` -- 8 test classes verified: TestPreAnalysisResult, TestCollisionZones, TestWireCollisionCheck, TestEstimatedBbox, TestPreAnalysisGateRouting, TestPreAnalysisGateWithFixtures, TestDuplicateGlobalLabelDetection, TestDuplicateLabelExecutorIntegration.

### Tertiary (LOW confidence)

- None -- all findings verified against codebase.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries already in codebase, verified by grep
- Architecture: HIGH -- execution.py fully read, all gate insertion points identified
- Pitfalls: HIGH -- derived from verified code patterns and existing bug patterns documented in KNOWN_LIMITATIONS.md

**Research date:** 2026-06-17
**Valid until:** 30 days (stable codebase, no major executor refactor expected)
