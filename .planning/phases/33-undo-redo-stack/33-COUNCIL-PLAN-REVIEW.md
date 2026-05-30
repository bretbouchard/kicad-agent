# Council Plan Review: Phase 33 -- Undo/Redo Stack

**Review Date:** 2026-05-30 (supersedes 2026-05-29 review)
**Reviewers:** Council of Ricks (Plan Review Gate 1)
**Plans Reviewed:** 33-01-PLAN.md, 33-02-PLAN.md

## Stack Assessment

**Detected Project Stack:**
- **Project Type:** Python (kicad-agent)
- **Domain:** KiCad EDA tooling, MCP server, file mutation operations
- **Key Libraries:** Pydantic v2, mcp 1.12.3, kiutils 1.4.8, pytest 8.4.2
- **Testing:** pytest with pytest-asyncio
- **CI/CD:** Not detected in scope

**Council Wave Composition:**
- **Wave Alpha (Core):** Rick Sanchez (Code Quality), Rick C-137 (Security), Slick Rick (SLC), Evil Morty (Synthesis)
- **Wave Beta (Wisdom):** Rick Prime (Design), Rickfucius (Historian)
- **Wave Gamma (Domain):** KiCad Rick (KiCad patterns), Embedded Firmware Rick (Transaction safety)
- **Wave Epsilon (Fresh Eyes):** Go Bubble Tea Rick (Elm Architecture patterns for undo/redo)
- **Total reviewers this session:** 9

---

## Summary

**Verdict: PASS WITH FINDINGS**

The plans are well-researched, architecturally sound, and demonstrate strong alignment with existing codebase patterns (IRCache, Transaction, MCP dispatch). The research phase was thorough. However, the Council identified 16 findings across 4 severity levels that must be addressed before execution. No findings are CRITICAL (no SLC violations, no security showstoppers), but 7 HIGH findings require plan revision to avoid implementation failures or subtle bugs.

---

## Findings

### [HIGH] Finding 01: Missing KICAD_UNDO_MAX_SIZE env var wiring

**Plan:** 33-01
**Section:** Task 1, action
**Issue:** The plan's truths section states "Max 50 entries per file (configurable via KICAD_UNDO_MAX_SIZE env var)" and the threat model references it, but the UndoStack `__init__` only accepts `max_size: int = 50` as a constructor parameter. The plan never specifies WHERE or HOW the env var is read. The `__init__` does not read `os.environ.get("KICAD_UNDO_MAX_SIZE", 50)`. The requirement UNDO-05 explicitly states "env var KICAD_UNDO_MAX_SIZE".
**Fix:** Wire the env var in `server_lifespan()` in `edit_server.py` (Plan 33-02), which is cleaner since the MCP server is the only entry point. Add error handling for invalid values:
```python
try:
    max_undo = max(1, int(os.environ.get("KICAD_UNDO_MAX_SIZE", "50")))
except (ValueError, TypeError):
    max_undo = 50
undo_stack = UndoStack(max_size=max_undo)
```
**Why:** Without this, UNDO-05 is not fully met. Users cannot configure the stack size without code changes.

---

### [HIGH] Finding 02: _execute_pcb described as "same pattern" but is structurally different

**Plan:** 33-01
**Section:** Task 2, step 4
**Issue:** The plan says "Modify `_execute_pcb` (starting line 910): Same pattern: read pre_content before Transaction, read post_content after commit, push to undo_stack." However, the actual `_execute_pcb` code (lines 910-946) does NOT call `normalize_kicad_output()`. It calls `serialize_pcb()` with an `ir._raw_written` guard, then `txn.commit()`. The schematic path has a normalize step that the PCB path lacks. The PCB path is structurally different and the plan should show exact insertion points rather than saying "same pattern."
**Fix:** Provide exact PCB integration code:
```python
def _execute_pcb(self, op, file_path):
    root = op.root
    # [existing cache/parse code unchanged]
    pre_content = file_path.read_text(encoding="utf-8")  # ADD: before Transaction
    with Transaction(file_path) as txn:
        details = self._dispatch_pcb(root.op_type, root, ir, file_path)
        if not ir._raw_written:
            serialize_pcb(parse_result, file_path, uuid_map=uuid_map)
        txn.commit()
    # ADD: after Transaction block
    if self._undo_stack is not None:
        post_content = file_path.read_text(encoding="utf-8")
        self._undo_stack.push(file_path, pre_content, post_content, root.op_type)
    # [existing cache invalidate code unchanged]
```
Note: post_content read happens AFTER the `with` block, same as schematic. The file is already written by this point.
**Why:** Misleading descriptions lead to implementation errors. The PCB path is structurally different from the schematic path.

---

### [HIGH] Finding 03: Missing _execute_project in undo integration

**Plan:** 33-01
**Section:** Task 2
**Issue:** The plan integrates undo snapshot capture into `_execute_schematic`, `_execute_pcb`, `_execute_cross_file`, and `execute_batch`, but misses `_execute_project` (line 1002). Project file operations (add_lib_entry, remove_lib_entry, add_net_class, add_design_rule) modify files like sym-lib-table, fp-lib-table, .kicad_dru, and .kicad_pro. These mutations are NOT wrapped in a Transaction -- they write directly. If a user runs `add_lib_entry` and then calls undo, they get "No operations to undo" because the stack has no entry for that file.
**Fix:** Add undo snapshot capture to `_execute_project()`:
```python
def _execute_project(self, op, file_path):
    root = op.root
    pre_content = None
    if self._undo_stack is not None and file_path.exists():
        pre_content = file_path.read_text(encoding="utf-8")
    details = self._dispatch_project(root.op_type, root, file_path)
    if self._undo_stack is not None and pre_content is not None:
        post_content = file_path.read_text(encoding="utf-8")
        self._undo_stack.push(file_path, pre_content, post_content, root.op_type)
    return {"success": True, "operation": root.op_type, ...}
```
Also add a test: "Test project-file operation captures snapshot: execute add_lib_entry, verify undo_stack.can_undo is True."
**Why:** Project file edits should be undoable for SLC consistency. Users expect undo to work for any mutation.

---

### [HIGH] Finding 04: Missing error handling for file write failures during undo/redo

**Plan:** 33-01
**Section:** Task 2, step 7 (undo method)
**Issue:** The `undo()` method writes `entry.pre_content` to disk via `entry.file_path.write_text(entry.pre_content, encoding="utf-8")`. If the write fails (disk full, permission error, file deleted externally, parent directory gone), the entry has already been popped from the undo stack and pushed to the redo stack. The undo is "consumed" but the file was not actually restored. The user loses both the undo and redo entry.
**Fix:** Wrap the write in a try/except with entry recovery:
```python
try:
    entry.file_path.write_text(entry.pre_content, encoding="utf-8")
except (OSError, PermissionError) as e:
    # Recovery: push entry back to undo stack
    resolved = entry.file_path.resolve()
    if resolved not in self._undo_stack._undo:
        self._undo_stack._undo[resolved] = deque(maxlen=self._undo_stack._max_size)
    self._undo_stack._undo[resolved].append(entry)
    # Remove from redo stack where it was just pushed
    if resolved in self._undo_stack._redo and self._undo_stack._redo[resolved]:
        self._undo_stack._redo[resolved].pop()
    return {"success": False, "error": f"Failed to restore file: {e}"}
```
Or simpler: provide a `_recover_undo` helper on UndoStack that reverses the pop_undo operation.
**Why:** Data loss scenario -- user tries to undo, write fails, and the undo entry is gone forever.

---

### [HIGH] Finding 05: pop_latest_undo/pop_latest_redo split across tasks

**Plan:** 33-01
**Section:** Task 1, action (peek_latest) and Task 2, step 9
**Issue:** Task 1 defines `peek_latest()` as a peek operation (non-destructive), but Task 2 step 9 defines `pop_latest_undo()` and `pop_latest_redo()` as destructive pop operations. These are different methods with different behaviors. The plan adds these methods to UndoStack in Task 2, but Task 1 (which creates the UndoStack module) only defines `peek_latest`. The `_latest_undo` tracking field is specified in Task 1 but `pop_latest_undo()` is added in Task 2. This creates a TDD gap: Task 1 tests won't cover `pop_latest_*`.
**Fix:** Move the design of `pop_latest_undo()` and `pop_latest_redo()` into Task 1 alongside `peek_latest`. These are core UndoStack operations that should be designed and tested together. The `_latest_undo` / `_latest_redo` tracking fields must be updated correctly in `pop_latest_*` methods (after popping, the field becomes stale and needs updating to the new deque top or None).
**Why:** Splitting core data structure methods across tasks creates integration gaps and makes the `_latest_*` tracking inconsistent.

---

### [HIGH] Finding 06: MCP lifespan does not create UndoStack

**Plan:** 33-02
**Section:** Task 1, action (missing)
**Issue:** Plan 33-02 modifies `edit_server.py` to add undo/redo dispatch, but it does NOT modify the `server_lifespan` function (line 223-234) to create an `UndoStack` and pass it to `OperationExecutor`. Currently, `server_lifespan` creates `executor = OperationExecutor(base_dir=base_dir)` without an undo_stack. The dispatch calls `executor.undo()` which checks `self._undo_stack is None` and returns the error "Undo stack not enabled". Undo would never work in production because the stack is never instantiated. This is the single most important wiring step and it is missing from both plans.
**Fix:** Add a step to Plan 33-02 Task 1 to modify `server_lifespan`:
```python
from kicad_agent.ops.undo_stack import UndoStack

@asynccontextmanager
async def server_lifespan(server):
    base_dir_str = os.environ.get("KICAD_PROJECT_DIR", "")
    base_dir = Path(base_dir_str) if base_dir_str else Path.cwd()
    base_dir = base_dir.resolve()
    if not base_dir.is_dir():
        logger.warning("KICAD_PROJECT_DIR does not exist: %s", base_dir)
    try:
        max_undo = max(1, int(os.environ.get("KICAD_UNDO_MAX_SIZE", "50")))
    except (ValueError, TypeError):
        max_undo = 50
    undo_stack = UndoStack(max_size=max_undo)
    executor = OperationExecutor(base_dir=base_dir, undo_stack=undo_stack)
    yield {"executor": executor, "base_dir": base_dir}
```
This also resolves Finding 01 (KICAD_UNDO_MAX_SIZE env var wiring).
**Why:** This is the most critical wiring gap. Without it, the entire undo/redo feature is dead code in production.

---

### [HIGH] Finding 07: _latest_redo tracking lifecycle is underspecified

**Plan:** 33-01
**Section:** Task 2, step 9
**Issue:** The plan specifies `_latest_undo` updated on every `push()` and `_latest_redo` updated on every `pop_undo()`. But when `pop_latest_redo()` is called, it needs to pop from the redo deque containing `_latest_redo`. After the pop, `_latest_redo` is stale. And if `push()` clears the redo dict entry entirely (`self._redo.pop(resolved, None)`), it must also reset `_latest_redo` to None when the cleared file matches `_latest_redo.file_path`. Additionally, if `pop_undo(file_path)` is called directly (not via pop_latest_undo), and the popped entry is `_latest_undo`, the `_latest_undo` field becomes a stale reference to an already-popped entry.
**Fix:** Specify the complete lifecycle of `_latest_undo` and `_latest_redo`:
- `_latest_undo`: Set on `push()`. Set to None when `pop_undo()` pops the entry that matches `_latest_undo.file_path`. Reset on `clear()`.
- `_latest_redo`: Set on `pop_undo()` and `pop_latest_undo()`. Set to None on `push()` (since push clears redo). Set to None when `pop_redo()` pops the entry that matches `_latest_redo.file_path`. Reset on `clear()`.

Alternatively, simplify by removing `_latest_*` fields entirely and iterating all deques to find the latest entry. This is O(number of files) which is always small (typically 1-5 files per project).
**Why:** Without precise tracking, `pop_latest_undo()` could return None when there are entries, or pop from the wrong deque.

---

### [MEDIUM] Finding 08: convert_kicad6_to_10 writes file inside handler -- edge case documentation

**Plan:** 33-01
**Section:** Task 2
**Issue:** The `convert_kicad6_to_10` handler (lines 352-358) writes to the file directly inside the handler, which happens inside the Transaction `with` block. The Transaction already copied the file as a snapshot. The plan's snapshot capture reads `pre_content` before the Transaction, and `post_content` after commit. For this handler, the file gets written twice (once by the handler, once by serialize+normalize). The plan's approach is correct -- pre_content captures original state, post_content captures final normalized state. But this edge case should be documented.
**Fix:** Add a note in Task 2: "Note: Some handlers (convert_kicad6_to_10) write directly to file_path inside the Transaction. This is safe because post_content is read after txn.commit(), capturing the final normalized state."
**Why:** Document edge cases for future maintainers.

---

### [MEDIUM] Finding 09: No path validation in executor.undo()/redo() for target_file

**Plan:** 33-01
**Section:** Task 2, step 7
**Issue:** The `undo()` method resolves `target_file` as `file_path = (self._base_dir / target_file).resolve()` but does NOT check path confinement (is it within base_dir?). The `execute()` method has path confinement (T-24-01, lines 738-744), but `undo()` skips it. A malicious MCP client could pass `target_file="../../../etc/passwd"` and undo would attempt to read from or write to an arbitrary file path. The threat model (T-33-02, T-33-05) claims existing path confinement handles this, but it does not -- the confinement check is only in `execute()`.
**Fix:** Add path confinement check to both `undo()` and `redo()` methods:
```python
if target_file is not None:
    file_path = (self._base_dir / target_file).resolve()
    if not file_path.is_relative_to(self._base_dir.resolve()):
        return {"success": False, "error": "Security: path escapes project directory"}
```
**Why:** Path traversal vulnerability. The threat model incorrectly assumes existing controls cover undo/redo, but they do not.

---

### [MEDIUM] Finding 10: Redo method not fully specified

**Plan:** 33-01
**Section:** Task 2, step 8
**Issue:** Step 8 says "Add `redo()` method following the same pattern but using `pop_latest_redo()` or `pop_redo()`, writing `post_content` instead of `pre_content`." This is too vague. The plan provides full code for `undo()` but only a one-liner for `redo()`. The return key should be `"redone_op"` not `"undone_op"` (matching the test expectation in Plan 33-02), and the error message should differ.
**Fix:** Provide the full `redo()` method implementation including path confinement check (Finding 09) and write error handling (Finding 04).
**Why:** Vague specifications lead to inconsistent implementations. The test in 33-02 expects `"redone_op"` as a key.

---

### [MEDIUM] Finding 11: Thread safety test does not account for max_size pruning

**Plan:** 33-01
**Section:** Task 1, action (tests)
**Issue:** The thread safety test uses 10 threads each pushing 100 entries and verifies total count is 1000. However, with `max_size=50` (the default), each file's deque will prune to 50. The test needs to use a single file path (all threads pushing to the same file) with a stack that has `max_size` greater than 1000, or use different file paths per thread and verify per-file counts. As specified, pushing 1000 entries to a single file with default max_size=50 would leave only 50 entries, and the test assertion "total count is 1000" would fail.
**Fix:** Specify that the thread safety test uses `UndoStack(max_size=2000)` and a single shared file path, or 10 different file paths with default max_size. Also add a concurrent push/pop test for realistic access patterns.
**Why:** The test as described will fail with the default max_size of 50.

---

### [MEDIUM] Finding 12: Create operation bypass needs explicit documentation

**Plan:** 33-01
**Section:** Task 2, step 3
**Issue:** The plan correctly identifies that create operations should NOT push to the undo stack. The truths state "Create operations are NOT pushed to undo stack (file did not exist before)." However, the implementation mechanism is implicit: create operations route through `_execute_create()`, which is a separate method from `_execute_schematic`/`_execute_pcb`. The plan modifies the schematic/PCB paths but does not need to modify `_execute_create`. This should be stated explicitly.
**Fix:** Add an explicit note in Task 2: "Create operations (create_schematic, create_pcb, etc.) route through `_execute_create()` which has no undo snapshot capture. No code changes needed in `_execute_create`. The bypass is by routing, not by conditional logic."
**Why:** Ambiguity about whether create operations need explicit bypass logic could lead to unnecessary code being added or confusion during code review.

---

### [MEDIUM] Finding 13: Missing test for undo when file is deleted externally

**Plan:** 33-01
**Section:** Task 2 (integration tests)
**Issue:** The integration tests cover success paths and "no history" error paths, but do not test the edge case where the file has been deleted externally between the undo snapshot and the undo call. The `undo()` method calls `entry.file_path.write_text(...)` which would raise `FileNotFoundError` if the file or parent directory was deleted. This exception is not caught and would propagate to the MCP dispatch handler, which returns a generic error. This is related to Finding 04 (write error handling).
**Fix:** Either (a) add a test for this edge case (file deleted between snapshot and undo), or (b) add a note in the plan that undo on a deleted file raises FileNotFoundError which is handled by the MCP error handler in Plan 33-02's dispatch code. If Finding 04 is fixed with try/except, this edge case is automatically covered.
**Why:** External file modification is a real-world scenario in MCP contexts where the user might have the file open in KiCad.

---

### [MEDIUM] Finding 14: Plan 33-02 references 33-01-SUMMARY.md that does not exist yet

**Plan:** 33-02
**Section:** context, line 59
**Issue:** The context references `@.planning/phases/33-undo-redo-stack/33-01-SUMMARY.md` which is the output of Plan 33-01 after successful execution. During autonomous execution, this file would exist. But during plan review, it creates a broken context reference. This is a minor issue for review but could cause confusion if the agent tries to load it.
**Fix:** Add a note that this context reference is resolved after 33-01 completes successfully. No action needed for execution quality.
**Why:** Minor -- does not affect execution quality.

---

### [LOW] Finding 15: Docstring and tool count updates are vague

**Plan:** 33-02
**Section:** Task 1, step 3
**Issue:** Step 3 says "Update the docstring at line 7 to say '59 kicad-agent operations' if needed, and update the `list_tools` docstring at line 241 to say '(57 operations + 6 meta-tools)'." But the current docstring at line 7 says "57 kicad-agent operations" -- undo/redo are meta-tools, not operations, so the operation count stays 57. The meta-tool count changes from 4 to 6. The "if needed" qualifier creates ambiguity.
**Fix:** Specify exact changes:
- Line 7: No change needed (stays "57 kicad-agent operations")
- Line 242: Change `"""Return all available MCP tools (57 operations + 4 meta-tools)."""` to `"""Return all available MCP tools (57 operations + 6 meta-tools)."""`
**Why:** Precision prevents confusion during implementation.

---

### [LOW] Finding 16: Missing readOnlyHint assertion in test

**Plan:** 33-02
**Section:** Task 1, action (test)
**Issue:** The `test_undo_redo_have_destructive_hint` test checks `destructiveHint is True` but does not check that `readOnlyHint` is NOT True. The plan's truth states "NOT readOnlyHint" but the test doesn't assert this. Since the default for `readOnlyHint` is None (not False), the test should verify that undo/redo are not accidentally marked as read-only.
**Fix:** Add assertion: `assert undo_tool.annotations.readOnlyHint is not True` and `assert redo_tool.annotations.readOnlyHint is not True`.
**Why:** Ensures undo/redo are correctly categorized as destructive tools, not accidentally read-only.

---

## Requirement Coverage

| Requirement | Covered | Plan | Notes |
|-------------|---------|------|-------|
| UNDO-01 | PARTIAL | 33-01 | UndoStack with deque(maxlen=50) is covered. KICAD_UNDO_MAX_SIZE env var wiring missing (Finding 01). Fixed by Finding 06 (lifespan wiring). |
| UNDO-02 | YES | 33-01 | Standard undo/redo semantics with push clearing redo. Fully specified. |
| UNDO-03 | YES | 33-02 | MCP meta-tools with destructiveHint=True, dispatch via asyncio.to_thread. Well-specified. |
| UNDO-04 | YES | 33-01 | Per-file isolation via dict[Path, deque[UndoEntry]]. Tests cover two-file isolation. |
| UNDO-05 | PARTIAL | 33-01 | Deque maxlen handles pruning. KICAD_UNDO_MAX_SIZE env var mentioned but never wired (Finding 01). Fixed by Finding 06. |

---

## Architecture Assessment

### Pattern Consistency

| Aspect | Consistent? | Notes |
|--------|-------------|-------|
| IRCache pattern (threading.Lock, resolve()) | YES | UndoStack follows exact same pattern |
| Transaction pattern (snapshot before mutation) | YES | pre_content read before Transaction, post_content after commit |
| MCP meta-tool pattern | YES | Follows erc_check/drc_check pattern exactly |
| Executor dispatch pattern | YES | New methods follow existing method signatures |
| Import patterns | YES | New import follows existing ops imports |

### Positive Architectural Decisions

1. **File content snapshots instead of Operation objects** -- correct choice. Re-executing operations is unreliable (UUIDs, reference numbering).
2. **Per-file isolation via dict[Path, deque]** -- clean, consistent with IRCache keyed-by-resolved-path.
3. **Optional undo_stack parameter** -- backward compatible. Existing code works without changes.
4. **Separation of UndoStack module from executor** -- testable in isolation.
5. **Create operations bypass undo** -- correct design. File did not exist before.
6. **IRCache invalidation after undo/redo** -- prevents stale cache reads.
7. **In-memory strings instead of on-disk temp files** -- avoids temp file cleanup complexity.

---

## Threat Model Assessment

| Threat ID | Assessment | Council Notes |
|-----------|------------|---------------|
| T-33-01 (DoS via unbounded stack) | Mitigated | deque(maxlen) handles this. KICAD_UNDO_MAX_SIZE env var needs wiring (Finding 01, 06). |
| T-33-02 (Tampering via file path) | PARTIALLY MITIGATED | Path confinement exists in execute() but NOT in undo()/redo() (Finding 09). Must add. |
| T-33-03 (Stale snapshots) | Accepted | Correct risk acceptance. Same as any editor undo. |
| T-33-04 (Info disclosure via memory) | Accepted | Correct. In-process memory only. |
| T-33-05 (MCP target_file tampering) | PARTIALLY MITIGATED | Depends on T-33-02 fix in undo(). |
| T-33-06 (Redo target_file tampering) | PARTIALLY MITIGATED | Same as T-33-05. |
| T-33-07 (Error message disclosure) | Accepted | Correct. No sensitive data in error messages. |

**Additional security concern (not in original threat model):** undo()/redo() write directly to files without Transaction's symlink protection (H-02) or fcntl locking (H-04). Consider adding `entry.file_path.is_symlink()` check before write.

---

## Historical Context (Rickfucius)

### Relevant Patterns

**IRCache Pattern (Phase 32):** UndoStack follows the same thread-safe pattern as IRCache (threading.Lock, resolve() on all paths, bounded collection). This is a proven pattern in the codebase. Pattern compliance: FOLLOWS.

**Transaction Pattern (Phase 4):** The snapshot capture follows the same "copy before mutation" philosophy as Transaction, but uses in-memory strings instead of on-disk temp files. This is a deliberate deviation documented in the research. Pattern compliance: DEVIATES (documented and justified).

**MCP Meta-Tool Pattern (Phase 24):** The undo/redo MCP tools follow the exact same pattern as erc_check/drc_check meta-tools (static tool definition, dispatch_tool routing, asyncio.to_thread). Pattern compliance: FOLLOWS.

**Anti-pattern avoided:** Storing Operation objects instead of file content. The research correctly identifies that re-executing operations produces different results (UUIDs, refs, timestamps). The plan stores file content strings. Anti-pattern: AVOIDED.

---

## SLC Validation (Slick Rick)

**Status:** PASS

### SLC Anti-Patterns Detected
- **Workarounds:** 0 found
- **Stub Methods:** 0 found
- **TODO/FIXME without tickets:** 0 found
- **Incomplete Implementations:** 0 design-level issues (UndoEntry is a frozen dataclass, all methods have behavior specs)

### SLC Criteria Assessment
- [x] **Simple:** Undo/redo tools have obvious purpose. Optional target_file parameter minimizes friction. Session-scoped semantics match user expectations from editors like KiCad. One concept (file content snapshots), one data structure (bounded deque).
- [x] **Lovable:** destructiveHint=True warns clients appropriately. Error messages are clear ("No operations to undo", "Undo stack not enabled"). Session-scoped limitation is documented in tool descriptions. Create operations not being undoable is documented.
- [x] **Complete:** Plan covers all 5 executor paths (schematic, PCB, cross-file, batch, project). MCP integration is complete with proper error handling. Create operations bypass documented.
- [x] **Secure:** Thread safety via Lock. Path confinement needs adding to undo/redo (Finding 09). Bounded memory via deque(maxlen). Symlink protection could be added (advisory).

**SLC Decision:** PASS (all findings are plan-level refinements, not SLC violations in the design)

---

## Verdict

**PASS WITH FINDINGS**

The plans are well-structured, well-researched, and architecturally sound. The Council approves execution **after** the following changes are incorporated into the plans:

### Required Changes Before Execution (HIGH priority -- all 7 must be addressed)

1. **[Finding 01/06 -- combined]** Wire KICAD_UNDO_MAX_SIZE env var reading and UndoStack instantiation in `server_lifespan()` in Plan 33-02. Add error handling for invalid env var values.
2. **[Finding 02]** Provide exact PCB integration code showing the `_execute_pcb` modification, not "same pattern." Note the `ir._raw_written` check and absence of normalization.
3. **[Finding 03]** Add undo snapshot capture to `_execute_project()` and a corresponding integration test.
4. **[Finding 04]** Add error handling for file write failures in `undo()`/`redo()` -- consume-on-failure is a data loss scenario. Provide try/except with entry recovery.
5. **[Finding 05]** Move `pop_latest_undo()`/`pop_latest_redo()` design into Task 1 alongside the core UndoStack data structure and tests.
6. **[Finding 07]** Specify complete lifecycle of `_latest_undo` and `_latest_redo` tracking fields, including invalidation on direct `pop_undo()`/`pop_redo()` calls.
7. **[Finding 09]** Add path confinement check to `undo()` and `redo()` methods to prevent path traversal via target_file parameter.

### Recommended Changes (MEDIUM priority -- should be addressed)

8. **[Finding 08]** Document the convert_kicad6_to_10 direct-write edge case.
9. **[Finding 10]** Provide full `redo()` method implementation with path confinement check.
10. **[Finding 11]** Fix thread safety test to use `max_size` > 1000 or separate file paths per thread.
11. **[Finding 12]** Add explicit note that create operations bypass undo via routing.
12. **[Finding 13]** Document or test the external file deletion edge case.

### Optional Changes (LOW priority)

13. **[Finding 15]** Specify exact docstring text changes.
14. **[Finding 16]** Add `readOnlyHint is not True` assertion to destructive hint test.

---

## Council Consensus

**Wave Alpha (Core):**
- Rick Sanchez (Code Quality): PASS WITH FINDINGS
- Rick C-137 (Security): PASS WITH FINDINGS (path confinement gap in Finding 09)
- Slick Rick (SLC): PASS

**Wave Beta (Wisdom):**
- Rick Prime (Design): PASS
- Rickfucius (Historian): PASS (pattern compliance verified)

**Wave Gamma (Domain):**
- KiCad Rick: PASS WITH FINDINGS (project-file gap in Finding 03)
- Embedded Firmware Rick: PASS WITH FINDINGS (write error handling in Finding 04)

**Wave Epsilon (Fresh Eyes):**
- Go Bubble Tea Rick: PASS WITH FINDINGS (pop_latest split in Finding 05)

**Final:**
- **Evil Morty:** PASS WITH FINDINGS

---

**Council Motto:** "9 specialists. 2 waves. 16 findings. All HIGH findings must be addressed before execution. Evil Morty makes the final call. No appeals."

**Review Completed:** 2026-05-30
**Review Duration:** ~15 minutes
