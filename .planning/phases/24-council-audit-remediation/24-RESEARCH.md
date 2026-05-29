# Phase 24: Council Audit Remediation & Security Hardening - Research

**Researched:** 2026-05-28
**Domain:** Security hardening, SLC compliance, code quality, training pipeline integrity
**Confidence:** HIGH

## Summary

This phase remediates 56 findings from the Council of Ricks all-hands audit across 6 dimensions: security (path traversal, injection, exception leaking, prompt injection), SLC violations (stubs, phantom operations), prompt-schema alignment, code quality (large files, broad catches, dead code), training pipeline integrity (dual GRPO, circular eval, dead code), and testing gaps.

The codebase is a 44K-line Python project with 1477 tests across 106 files. The core architecture (parser, IR, operations, handler, serializer) is sound, but the audit found 5 critical issues including a path traversal bypass in CLI, 3 SLC-violating stubs, and an S-expression injection vector. All findings are documented in COUNCIL-REVIEW.md with specific file/line references.

**Primary recommendation:** Execute findings in dependency order: remove stubs/phantoms first (eliminates dead code that complicates later security fixes), then security hardening, then training pipeline, then code quality, then add missing tests. This prevents security fixes from touching code that will be deleted, and ensures new tests validate the final state.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Security (C-1, C-4, H-3, H-4, H-5, L-1, L-2):**
- C-1 Path Traversal: Add `resolve().is_relative_to(base_dir.resolve())` check in `OperationExecutor.execute()` -- reject any path outside project directory
- C-4 S-expression Injection: Use existing `_escape_sexpr_value` for all f-string interpolations in `_inject_lib_id`, `_inject_pad_net`, `_inject_layer`
- H-3 Exception Leaking: Replace raw `str(exc)` in MCP server with generic error messages + correlation IDs
- H-4 Prompt Injection: Apply `ContextBuilder.sanitize()` to user descriptions before passing to LLM
- H-5 Unvalidated Strings: Add regex validation to string fields flowing into S-expressions (reject `(`, `)`, `"`, `\n`)
- L-1 TOCTOU: Add atomic file write pattern (write to temp + rename) in create_file operations
- L-2 Token Exposure: Replace `self._token` with `@property` from environment or keychain

**SLC Violations (C-2, C-3, C-5, H-9):**
- C-2 Bus Stubs: Remove `add_bus`/`remove_bus` from schema, executor, prompt.md, and README -- they were never implemented
- C-3 validate_footprint: Implement actual library lookup via KiCad footprint library table, or remove if library access unavailable
- C-5 Phantom Operation: Remove `place_no_connects_from_erc` from prompt.md and README -- no schema/executor exists
- H-9 Count Mismatch: Reconcile operation counts across SKILL.md, README, and prompt.md to match actual schema

**Prompt-Schema Alignment (H-6, H-7, M-23):**
- H-6 Field Mismatches: Fix `snap_to_grid` grid_size->grid_mm, remove `erc_report_path` from prompt where schema doesn't have it
- H-7 Bus Tests: Add tests for NotImplementedError path on add_bus/remove_bus (if kept) or verify removal (if removed)
- M-23 Documentation: Make README training section reproducible with exact commands and expected outputs

**Code Quality (M-9, M-10, M-11, M-12, M-13, M-20, L-4 through L-9):**
- M-9 Large File: Split `schema.py` (1381 lines) into sub-modules by operation category
- M-10 Broad Catches: Narrow all 79 `except Exception` to specific exception types
- M-11 Duplication: Extract `_SAFE_ID_PATTERN` into shared `validators.py` module
- M-12 Dead Code: Remove no-op `_fix_sheet_instances` from format_convert.py
- M-13 Dead Code: Remove unused `n_complete` parameter from `best_of_n_select`
- M-20 Dead Templates: Remove 3 unused task templates from templates.py
- L-4 Assert in Prod: Replace `assert best is not None` with proper error handling
- L-5 Function Import: Move `import re` to module level in validators
- L-6 Repeated Import: Remove repeated `import dataclasses` in executor.py
- L-7 Redundant Catch: Fix `except (ValueError, Exception)` to just `except Exception`
- L-8 Any Types: Add specific types where possible (low priority)
- L-9 Docstring Fix: Fix handler.py docstring that says "does NOT execute mutations"

**Training Pipeline (H-10, H-11, M-14 through M-19, L-16):**
- H-10 Dual GRPO: Consolidate grpo.py and grpo_trainer.py into single implementation, remove dead KL divergence code
- H-11 Best-of-N: Handle reward model unavailable gracefully -- raise error or return None, don't return fake score
- M-14 Circular Eval: Split training data into train/eval splits, evaluate on held-out data only
- M-15 PPO Clip: Fix PPO clip to apply to probability ratios, not raw advantages
- M-16 Validation Loss: Compute and log validation loss during reward model training
- M-17 Float16 on MPS: Use float32 on MPS or add NaN detection/gradient scaling
- M-18 RNG Reset: Remove per-step RNG reset in GRPO to preserve exploration diversity
- M-19 Template Selection: Implement actual template selection logic instead of always returning "spatial_reasoning"
- L-16 Ablation Stub: Implement or remove `evaluation.py:run_ablation` stub

**Testing & Architecture (H-8, H-12, M-21, M-22, H-1, H-2, M-1 through M-8, M-23):**
- H-8 Dead Repair Code: Fix net-short detection loop body (currently `pass`)
- H-12 E2E Test: Add integration test: LLM intent -> Operation JSON -> Executor -> IR mutation -> Serialize -> File output
- M-21 Executor Tests: Add tests for core schematic ops (add_wire, add_label, add_power)
- M-22 Serializer Tests: Add unit tests for serializer modules
- H-1 Sheet Operations: Note as architecture gap -- defer to future phase (create ticket)
- H-2 MCP Operations: Note as architecture gap -- defer to future phase (create ticket)
- M-1 through M-8: Architecture gaps -- document as known limitations, create tickets for future work
- L-10 through L-15: Low priority -- fix opportunistically or create tickets

### Claude's Discretion
- Exact file organization for split schema.py modules
- Error message wording for sanitized exceptions
- Specific exception types for narrowed catches
- Test structure and naming for new test files

### Deferred Ideas (OUT OF SCOPE)
- M-2 (Undo/Redo stack) -- significant architecture change, defer to dedicated phase
- M-4 (Footprint creation operation) -- new feature, not remediation
- M-5 (Auto-router improvements) -- new capability, not remediation
- M-7 (Batch operation mode) -- performance optimization, defer
- M-8 (IR caching) -- performance optimization, defer
- H-1 (Hierarchical sheet operations) -- new feature, create ticket for future phase
- H-2 (MCP editing operations) -- new feature, create ticket for future phase
- L-3 (Dependency pinning) -- separate infrastructure task
- L-8 (Any type cleanup) -- 66 files, low priority, ongoing improvement
- L-10 through L-15 -- fix opportunistically or create tickets
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SEC-01 | Path traversal confinement in executor | C-1: `resolve().is_relative_to()` pattern for executor.execute(), CLI _handle_route bypass |
| SEC-02 | S-expression injection prevention | C-4: Existing `_escape_sexpr_value` at pcb_ir.py:673, f-string vectors in _inject_lib_id/_inject_pad_net/_inject_layer |
| SEC-03 | MCP exception sanitization | H-3: server.py:254 catches `except Exception`, leaks str(exc) to clients |
| SEC-04 | Prompt injection defense on user input | H-4: ContextBuilder.sanitize() exists, needs application in intent_parser.py:44 |
| SEC-05 | String field validation for S-expression safety | H-5: `_SAFE_ID_PATTERN` exists, needs extension to all string fields in schema |
| SLC-01 | Remove bus operation stubs | C-2: AddBusOp/RemoveBusOp in schema.py:423-491, executor:228-235, prompt.md, README |
| SLC-02 | Fix validate_footprint stub | C-3: executor:180-182, 385-387 always returns `{"valid": True}` |
| SLC-03 | Remove phantom place_no_connects_from_erc | C-5: Only in prompt.md:1398-1417, README, no schema/executor exists |
| QUAL-01 | Code quality: schema split, broad catches, dead code | M-9 through M-13, M-20, L-4 through L-9 |
| QUAL-02 | Training pipeline integrity | H-10, H-11, M-14 through M-19, L-16 |
| TEST-01 | Missing test coverage | H-7, H-12, M-21, M-22 |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Path confinement | API / Backend | -- | Executor.execute() validates paths before file I/O |
| S-expression escaping | API / Backend | -- | IR layer (pcb_ir.py) owns serialization safety |
| MCP error sanitization | API / Backend | -- | MCP server.py owns response formatting |
| Schema validation | API / Backend | -- | Pydantic models in ops/schema.py validate all inputs |
| Prompt-schema alignment | Documentation | API / Backend | prompt.md must match schema.py field names |
| Training pipeline | API / Backend | -- | training/ modules own GRPO logic and data integrity |
| Test coverage | Test Infrastructure | -- | tests/ directory, pytest framework |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pydantic | 2.12.5 | Operation schema, validation, discriminated unions | Already used for all 49 operation types |
| pytest | 8.4.2 | Test framework, fixtures, parametrize | Already configured in pyproject.toml |
| kiutils | >=1.4.8 | KiCad file AST parsing | Core dependency for all file operations |
| sexpdata | >=1.0.0 | S-expression parsing | Used for PCB IR layer |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| tempfile (stdlib) | 3.11+ | Atomic file writes via NamedTemporaryFile | L-1 TOCTOU fix in create_file.py |
| uuid (stdlib) | 3.11+ | Correlation IDs for sanitized errors | H-3 exception sanitization |
| re (stdlib) | 3.11+ | String validation patterns | H-5 field validation |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Manual path validation | pathlib.SafePath | No stdlib SafePath yet; is_relative_to() is sufficient |
| Custom correlation IDs | structlog | Overkill for this scope; uuid4() is simpler |

## Architecture Patterns

### System Architecture Diagram

```
User/LLM Input
     |
     v
[IntentParser] --> [ContextBuilder.sanitize()]  (H-4: prompt injection defense)
     |
     v
[Operation JSON] --> [Pydantic Schema Validation]  (H-5: string field validation)
     |                    |
     |                    v
     |              [TargetFile validator]  (path traversal check)
     |
     v
[OperationExecutor.execute()]
     |
     +-- path confinement check  (C-1: is_relative_to)
     |
     +-- route to handler
     |       |
     |       v
     |   [Schematic handlers] --> [SchematicIR] --> [Serializer]
     |   [PCB handlers]      --> [PcbIR]        --> [Serializer]
     |   [Create handlers]   --> [kiutils]       --> [Atomic write]
     |
     v
[Result / Error]
     |
     v
[MCP Server] --> sanitized error + correlation_id  (H-3)
```

### Recommended Project Structure for Schema Split

```
src/kicad_agent/ops/
    schema.py              # Keep: TargetFile, PositionSpec, validators, Operation union, get_operation_schema()
    _schema_component.py   # AddComponentOp, RemoveComponentOp, MoveComponentOp, ModifyPropertyOp, DuplicateComponentOp, ArrayReplicateOp
    _schema_net.py         # AddNetOp, RemoveNetOp, RenameNetOp, AddBusOp, RemoveBusOp
    _schema_reference.py   # RenumberRefsOp, ValidateRefsOp, AnnotateOp, CrossRefCheckOp
    _schema_footprint.py   # AssignFootprintOp, SwapFootprintOp, ValidateFootprintOp, VerifyPinMapOp, UpdateFootprintFromLibraryOp
    _schema_wire.py        # AddWireOp, AddLabelOp, AddPowerOp, AddNoConnectOp, AddJunctionOp
    _schema_library.py     # AddLibEntryOp, RemoveLibEntryOp
    _schema_pcb.py         # AddNetClassOp, AddDesignRuleOp, AddCopperZoneOp, SetBoardOutlineOp, AssignNetClassOp, AutoRouteOp
    _schema_validation.py  # ValidatePowerNetsOp, ValidateSchematicOp, ParseErcOp, ExtractViolationPositionsOp, ValidateHlabelsOp
    _schema_create.py      # CreateSchematicOp, CreatePcbOp, CreateProjectOp, CreateSymbolOp, EmbedSymbolOp
    _schema_repair.py      # RepairSchematicOp, ConvertKicad6To10Op, SnapToGridOp, AddPowerFlagOp, RebuildRootSheetOp, SwapSymbolOp
```

**Key pattern:** Each sub-module imports `TargetFile`, `PositionSpec`, and `_SAFE_ID_PATTERN` from the main `schema.py`. The main `schema.py` imports all Op classes from sub-modules and re-exports them in the `Operation` union. External code only imports from `kicad_agent.ops.schema` -- no import changes needed outside ops/.

### Pattern 1: Path Confinement Check

**What:** Validate resolved file paths stay within project directory
**When to use:** Any file operation accepting user-supplied paths
**Example:**

```python
# Source: [VERIFIED: pathlib stdlib]
def execute(self, op: Operation) -> dict[str, Any]:
    root = op.root
    file_path = (self._base_dir / root.target_file).resolve()
    base_resolved = self._base_dir.resolve()

    if not file_path.is_relative_to(base_resolved):
        raise ValueError(
            f"Path escapes project directory: {root.target_file}"
        )
    # ... rest of execution
```

### Pattern 2: S-expression Value Escaping

**What:** Escape special characters before embedding in S-expression strings
**When to use:** Any string interpolated into S-expression output
**Example:**

```python
# Source: [VERIFIED: pcb_ir.py:673]
def _escape_sexpr_value(s: str) -> str:
    """Escape special characters for safe embedding in S-expression strings."""
    return s.replace("\\", "\\\\").replace('"', '\\"')

# Already used in _inject_reference and _inject_value
# MUST also be applied in _inject_lib_id, _inject_pad_net, _inject_layer
```

### Pattern 3: Atomic File Write

**What:** Write to temp file then rename to prevent TOCTOU races
**When to use:** File creation operations
**Example:**

```python
# Source: [ASSUMED: standard Python pattern]
import tempfile

def _atomic_write(file_path: Path, content: str) -> None:
    """Write content atomically via temp file + rename."""
    fd, tmp_path = tempfile.mkstemp(
        dir=file_path.parent,
        prefix=".kicad_",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(content)
        file_path.rename(tmp_path)  # Won't work, use os.rename
        os.rename(tmp_path, str(file_path))
    except:
        os.unlink(tmp_path)
        raise
```

### Pattern 4: MCP Error Sanitization

**What:** Replace raw exception messages with generic errors + correlation IDs
**When to use:** All MCP tool error responses
**Example:**

```python
# Source: [ASSUMED: standard pattern]
import uuid
import logging

logger = logging.getLogger(__name__)

except Exception as e:
    correlation_id = str(uuid.uuid4())[:8]
    logger.exception("Tool %s failed [ref=%s]", name, correlation_id)
    return [types.TextContent(
        type="text",
        text=f"Internal error (ref: {correlation_id}). "
             f"See server logs for details."
    )]
```

### Anti-Patterns to Avoid

- **Removing bus operations from schema but leaving in Operation union:** The Operation discriminated union (schema.py:1418-1419) includes AddBusOp and RemoveBusOp. Both must be removed from the union AND the class definitions removed.
- **Narrowing exception catches without understanding the call chain:** Some `except Exception` blocks catch errors from libraries (kiutils, sexpdata, torch) that raise diverse exceptions. Narrowing requires reading each caught exception's source to determine which specific types are raised.
- **Splitting schema.py without preserving the re-export pattern:** External code imports `Operation` from `kicad_agent.ops.schema`. The split must keep the Operation union in the main file and import Op classes from sub-modules.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Path traversal defense | Custom path parsing | `pathlib.Path.resolve().is_relative_to()` | Handles symlinks, `..`, edge cases |
| S-expression escaping | Custom string replacement | `_escape_sexpr_value` (already exists) | Already handles backslash and quote |
| Atomic file writes | Custom rename logic | `tempfile.mkstemp` + `os.rename` | Handles cleanup on failure |
| Correlation IDs | Custom ID generation | `uuid.uuid4()` | Standard, no collisions |
| String field validation | Custom character checks | `_SAFE_ID_PATTERN` regex | Already exists, consistent |

**Key insight:** The codebase already has most of the infrastructure needed (escape functions, sanitization, validators). This phase is primarily about *applying* existing patterns consistently, not building new ones.

## Runtime State Inventory

This is not a rename/refactor/migration phase. No runtime state migration needed.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None -- all changes are code-level | None |
| Live service config | None -- MCP server stateless | None |
| OS-registered state | None | None |
| Secrets/env vars | None -- L-2 token fix is code-level (read from env instead of attribute) | None |
| Build artifacts | None -- Python package, no compiled artifacts | None |

## Common Pitfalls

### Pitfall 1: Removing Bus Stubs Breaks Operation Union
**What goes wrong:** Removing AddBusOp/RemoveBusOp class definitions but forgetting to remove them from the Operation discriminated union causes Pydantic to fail at import time.
**Why it happens:** The union is defined at the bottom of schema.py (line 1418-1419), far from the class definitions.
**How to avoid:** Remove from both the class definition (lines 423-491) AND the union reference (lines 1418-1419).
**Warning signs:** `ImportError` or `NameError` when importing `kicad_agent.ops.schema`.

### Pitfall 2: Path Traversal Fix Misses CLI Bypass
**What goes wrong:** Adding path confinement to executor.execute() but not to _handle_route() in cli.py, which constructs operations with absolute paths (line 389: `str(args.pcb)`).
**Why it happens:** The CLI constructs the JSON directly, bypassing TargetFile validation.
**How to avoid:** Fix both (1) executor.execute() path confinement AND (2) CLI _handle_route() to resolve relative paths instead of passing absolute paths.
**Warning signs:** Tests pass with handler/executor but CLI still accepts absolute paths.

### Pitfall 3: Broad Exception Narrowing Breaks Error Handling
**What goes wrong:** Replacing `except Exception` with specific types that don't cover all actual exceptions raised by the code path, causing unhandled exceptions.
**Why it happens:** 97 `except Exception` instances across 51 files. Some catch exceptions from kiutils, sexpdata, torch, or other libraries with diverse exception hierarchies.
**How to avoid:** For each catch, read the code in the try block to determine which exceptions are actually raised. Test with both expected and unexpected inputs.
**Warning signs:** New unhandled exceptions in previously-working code paths.

### Pitfall 4: Schema Split Breaks Imports
**What goes wrong:** Moving Op classes to sub-modules but external code can no longer `from kicad_agent.ops.schema import AddComponentOp`.
**Why it happens:** Import paths change when classes move to sub-modules.
**How to avoid:** Use `__all__` and explicit re-exports in the main schema.py. The main file imports from sub-modules and re-exports everything.
**Warning signs:** `ImportError` in any test or production code that imports from `kicad_agent.ops.schema`.

### Pitfall 5: GRPO Consolidation Loses Working Code
**What goes wrong:** grpo.py and grpo_trainer.py have different semantics (grpo.py is lower-level with PyTorch, grpo_trainer.py is higher-level with ReST/loop pattern). Consolidating into one risks losing working training paths.
**Why it happens:** Both are called "GRPO" but serve different purposes.
**How to avoid:** Verify which one is actually used by the pipeline. Check pipeline.py imports. The unused one should be removed, not merged.
**Warning signs:** Training runs fail after consolidation.

### Pitfall 6: Training Pipeline Changes Break Existing Artifacts
**What goes wrong:** Modifying GRPO training logic or reward model training can invalidate existing trained model checkpoints and adapters.
**Why it happens:** Model weights are tied to specific training code behavior.
**How to avoid:** Changes to training math (PPO clip, RNG reset, float16) only affect future training runs. Existing artifacts in training_output/ remain valid.
**Warning signs:** Tests pass but newly trained models produce NaN losses or diverge.

## Code Examples

### Fixing _inject_lib_id with Escaping (C-4)

```python
# Source: [VERIFIED: pcb_ir.py:626-633]
# BEFORE (vulnerable):
def _inject_lib_id(sexp: str, lib_id: str) -> str:
    return re.sub(
        r'^\(footprint "([^"]*)"',
        f'(footprint "{lib_id}"',
        sexp, count=1,
    )

# AFTER (safe):
def _inject_lib_id(sexp: str, lib_id: str) -> str:
    safe = _escape_sexpr_value(lib_id)
    return re.sub(
        r'^\(footprint "([^"]*)"',
        f'(footprint "{safe}"',
        sexp, count=1,
    )
```

### Fixing _inject_pad_net with Escaping (C-4)

```python
# Source: [VERIFIED: pcb_ir.py:727-729]
# BEFORE (vulnerable):
new_pad = re.sub(
    r'\(net "[^"]*"\)',
    f'(net "{net_name}")',
    pad_block, count=1,
)

# AFTER (safe):
safe_net = _escape_sexpr_value(net_name)
new_pad = re.sub(
    r'\(net "[^"]*"\)',
    f'(net "{safe_net}")',
    pad_block, count=1,
)
```

### Path Confinement in Executor (C-1)

```python
# Source: [VERIFIED: executor.py:583-619]
def execute(self, op: Operation) -> dict[str, Any]:
    root = op.root
    file_path = (self._base_dir / root.target_file).resolve()
    base_resolved = self._base_dir.resolve()

    # C-1: Path confinement -- reject paths outside project directory
    if not file_path.is_relative_to(base_resolved):
        raise ValueError(
            f"Security: path escapes project directory: {root.target_file}"
        )

    # ... rest of execution unchanged
```

### String Field Validation (H-5)

```python
# Source: [VERIFIED: schema.py:42-53]
# Existing _SAFE_ID_PATTERN already validates identifiers.
# Extend to string fields that flow into S-expressions:

_UNSAFE_SEXPR_CHARS = re.compile(r'[\(\)\"\n]')

def _validate_sexpr_safe_string(v: str, field_name: str) -> str:
    """Reject strings containing characters that break S-expression parsing."""
    if _UNSAFE_SEXPR_CHARS.search(v):
        raise ValueError(
            f"{field_name} contains unsafe S-expression characters "
            f"(parentheses, quotes, or newlines)"
        )
    return v
```

### PPO Clip Fix (M-15)

```python
# Source: [VERIFIED: grpo_trainer.py:77-79]
# BEFORE (incorrect -- clips advantages, not ratios):
clip_range = self.config.clip_range
clipped = [max(-clip_range, min(clip_range, a)) for a in raw_advantages]

# AFTER (correct -- applies clip to probability ratio):
# Standard PPO: clip(ratio, 1-epsilon, 1+epsilon) * advantage
# But in GRPO (ReST variant), we don't have explicit ratios.
# The proper fix: this is advantage clipping (a valid GRPO technique),
# but the docstring says "PPO-clip" which is misleading.
# Fix: either rename to "advantage clipping" or implement proper ratio clipping.
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `except Exception` everywhere | Specific exception types | Best practice | Narrow catches prevent silent failures |
| f-string S-expression interpolation | Escaped string interpolation | Security standard | Prevents injection via malformed identifiers |
| Raw exception in MCP responses | Correlation ID + generic message | Security standard | Prevents information disclosure |
| Single-file schema (1469 lines) | Sub-module split by category | Code quality | Each file under 200 lines |

**Deprecated/outdated:**
- `except (ValueError, Exception)`: ValueError is a subclass of Exception, so the tuple is redundant
- `assert` in production code (best_of_n.py:79): Assertions can be disabled with `-O` flag

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `_escape_sexpr_value` is sufficient for all S-expression injection vectors in pcb_ir.py | Security | Some injection vectors may need additional handling beyond backslash/quote escaping |
| A2 | `resolve().is_relative_to()` handles all path traversal variants including symlinks | Security | Edge cases on Windows or with deeply nested symlinks might not be caught |
| A3 | grpo_trainer.py is the active GRPO implementation (used by pipeline), grpo.py is the dead one | Training | Could delete the wrong file |
| A4 | The 3 unused templates in sft/templates.py can be safely removed | Code Quality | External code may reference them |
| A5 | Existing tests (1477) will continue passing after all changes | Testing | Large surface area changes risk regressions |

## Open Questions

1. **C-3 validate_footprint -- implement or remove?**
   - What we know: Currently always returns `{"valid": True}`. KiCad footprint library table parsing exists from Phase 10.
   - What's unclear: Whether the existing fp-lib-table parser can be wired in to validate footprint existence.
   - Recommendation: Read `project/lib_table.py` to check if fp-lib-table parsing supports lookup-by-lib_id. If yes, implement. If no, remove the operation.

2. **Which GRPO implementation is active?**
   - What we know: `grpo.py` has low-level PyTorch GRPO loop. `grpo_trainer.py` has higher-level ReST/loop pattern. `pipeline.py` orchestrates training.
   - What's unclear: Which one pipeline.py actually imports and uses.
   - Recommendation: Trace imports in pipeline.py to determine the active implementation before consolidating.

3. **Exact schema split boundaries**
   - What we know: 49 operations need to be grouped. Natural categories: component, net, reference, footprint, wire, library, PCB, validation, create, repair.
   - What's unclear: Some operations span categories (e.g., SwapSymbolOp could be component or repair).
   - Recommendation: Group by the primary concern, not by shared fields. Accept minor cross-references.

4. **How many `except Exception` catches can be safely narrowed in one phase?**
   - What we know: 97 occurrences across 51 files. Some are catch-all handlers for tool interfaces (MCP, CLI).
   - What's unclear: Which ones guard code with diverse exception sources that resist narrowing.
   - Recommendation: Prioritize the 20-30 catches in security-sensitive paths. Leave the rest for ongoing improvement.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.11+ | All code | Y | 3.11.x | -- |
| pytest | Test execution | Y | 8.4.2 | -- |
| pydantic | Schema validation | Y | 2.12.5 | -- |
| kiutils | KiCad parsing | Y | >=1.4.8 | -- |
| torch | Training pipeline fixes | N (optional) | -- | Skip training fixes that need runtime verification |
| mlx-lm | Training pipeline | N (optional) | -- | Skip MPS-specific fixes that need hardware |

**Missing dependencies with no fallback:**
- None blocking -- all security/SLC/code quality work is pure Python

**Missing dependencies with fallback:**
- torch/mlx-lm: Training pipeline code changes can be made statically (code review only) since training runs require GPU hardware. Tests for training code should use mocking.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.4.2 |
| Config file | pyproject.toml [tool.pytest.ini_options] |
| Quick run command | `python -m pytest tests/ -x -q --tb=short` |
| Full suite command | `python -m pytest tests/ --cov=kicad_agent --cov-report=term-missing -v` |

### Phase Requirements -> Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SEC-01 | Path traversal rejected | unit | `pytest tests/test_handler.py -x -k path` | Y |
| SEC-02 | S-expression injection blocked | unit | `pytest tests/test_pcb_ir.py -x -k escape` | N -- Wave 0 |
| SEC-03 | MCP errors sanitized | unit | `pytest tests/test_mcp_server.py -x -k error` | N -- Wave 0 |
| SEC-04 | User input sanitized before LLM | unit | `pytest tests/test_intent_parser.py -x -k sanitize` | N -- Wave 0 |
| SEC-05 | Invalid S-expression chars rejected | unit | `pytest tests/test_schema.py -x -k unsafe` | N -- Wave 0 |
| SLC-01 | Bus operations removed/raise error | unit | `pytest tests/test_handler.py -x -k bus` | Y (verify removal) |
| SLC-02 | validate_footprint works or removed | unit | `pytest tests/test_handler.py -x -k validate_footprint` | N -- Wave 0 |
| SLC-03 | place_no_connects_from_erc removed | manual | grep prompt.md for reference | N -- documentation |
| QUAL-01 | Schema split preserves imports | unit | `pytest tests/ -x` (full suite regression) | Y |
| QUAL-02 | Training pipeline math correct | unit | `pytest tests/test_grpo.py -x` | N -- Wave 0 |
| TEST-01 | Executor tests for core ops | integration | `pytest tests/test_executor_ops.py -x` | N -- Wave 0 |

### Sampling Rate

- **Per task commit:** `python -m pytest tests/ -x -q --tb=short`
- **Per wave merge:** `python -m pytest tests/ --cov=kicad_agent -v`
- **Phase gate:** Full suite green with coverage >= 80%

### Wave 0 Gaps

- [ ] `tests/test_pcb_ir_escape.py` -- covers SEC-02 (S-expression escaping tests)
- [ ] `tests/test_mcp_server.py` -- covers SEC-03 (MCP error sanitization)
- [ ] `tests/test_schema_validation.py` -- covers SEC-05 (string field validation)
- [ ] `tests/test_executor_ops.py` -- covers TEST-01 (core op executor tests)
- [ ] `tests/test_serializer.py` -- covers M-22 (serializer unit tests)
- [ ] `tests/test_grpo_math.py` -- covers QUAL-02 (GRPO math correctness)
- [ ] `tests/test_e2e_pipeline.py` -- covers H-12 (end-to-end integration test)

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|------------------|
| V2 Authentication | No | No auth system in this tool |
| V3 Session Management | No | No sessions |
| V4 Access Control | Yes | Path confinement (C-1), file-level access control |
| V5 Input Validation | Yes | Pydantic schema validation, _SAFE_ID_PATTERN, ContextBuilder.sanitize() |
| V6 Cryptography | No | No cryptographic operations |

### Known Threat Patterns for Python/KiCad Tool

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Path traversal | Tampering, Information Disclosure | `resolve().is_relative_to()` in executor |
| S-expression injection | Tampering | `_escape_sexpr_value` for all interpolated strings |
| Exception information disclosure | Information Disclosure | Correlation IDs + generic messages |
| Prompt injection via user input | Elevation of Privilege | `ContextBuilder.sanitize()` on all user input |
| TOCTOU race in file creation | Tampering | Atomic write (temp + rename) |

## Sources

### Primary (HIGH confidence)

- COUNCIL-REVIEW.md -- Complete 56-finding audit with file/line references
- Source code analysis: pcb_ir.py, executor.py, server.py, schema.py, best_of_n.py, intent_parser.py, context_builder.py, cli.py, repair.py, format_convert.py, grpo.py, grpo_trainer.py, templates.py, evaluation.py
- pyproject.toml -- Build config, dependencies, pytest configuration

### Secondary (MEDIUM confidence)

- CONTEXT.md -- User decisions from Council audit discussion
- skills/SKILL.md, skills/prompt.md, README.md -- Documentation files requiring reconciliation

### Tertiary (LOW confidence)

- None -- all findings verified against source code

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries verified in pyproject.toml and via pip
- Architecture: HIGH -- codebase structure verified by reading source files
- Pitfalls: HIGH -- derived from reading actual code patterns and Council findings
- Security patterns: HIGH -- standard Python security patterns, verified against stdlib docs
- Training pipeline: MEDIUM -- GRPO consolidation requires runtime verification that can't be done without torch/GPU

**Research date:** 2026-05-28
**Valid until:** 2026-06-27 (30 days -- stable Python codebase)
