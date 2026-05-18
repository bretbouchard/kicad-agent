# Phase 2: Operation Schema and IR Layer - Research

**Researched:** 2026-05-18
**Domain:** Pydantic v2 JSON schema design, kiutils-based IR layer, transaction-based mutation with rollback, deterministic S-expression serialization
**Confidence:** HIGH

## Summary

Phase 2 builds the three pillars between the parser (Phase 1) and the mutators (Phase 4): (1) a Pydantic v2 operation schema that defines the JSON contract the LLM uses to express edit intents, (2) file-type-specific IR classes that wrap kiutils parsed objects and track mutation state for rollback, and (3) a transaction engine that snapshots files before mutation and restores on failure. The key design decision is D-05 (thin wrapper over kiutils objects) which means the IR does NOT duplicate the AST into separate canonical dataclasses -- instead, IR classes hold a reference to the mutable kiutils object and expose typed mutation methods. This trades the immutability benefits of a separate IR for simplicity, fewer mapping bugs, and direct kiutils serialization compatibility.

The serialization challenge (D-11 through D-14) centers on making kiutils output byte-identical to KiCad-native output. kiutils 1.4.8 has known formatting quirks (property ordering, whitespace, quoting) that require a post-processing normalizer. The two-pass round-trip test from Phase 1 proves kiutils output is deterministic across runs, but not yet identical to KiCad-native output. Phase 2 must close that gap.

**Primary recommendation:** Build the Pydantic discriminated union schema first, then the IR wrapper classes, then the transaction engine. The normalizer is the hardest part -- tackle it last after IR mutation is proven correct.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- D-01: One Pydantic model per operation type (not a generic dict with `type` field)
- D-02: Atomic operations (one mutation per op, no compound operations)
- D-03: Single file per operation (each op targets one file via `target_file` field)
- D-04: Export full JSON Schema via Pydantic v2 `model_json_schema()`
- D-05: Thin wrapper over kiutils objects (IR holds reference, not deep copy)
- D-06: Mutation tracking with rollback data + UUID map reference + dirty flag
- D-07: Separate IR classes per file type (SchematicIR, PcbIR, SymbolLibIR, FootprintIR)
- D-08: File-level snapshots (full file copy before mutation)
- D-09: Auto-rollback on validation failure/exception/manual trigger
- D-10: Full file copy for snapshots (`shutil.copy2`)
- D-11: KiCad-native property ordering (post-process normalizer after kiutils serialization)
- D-12: Match KiCad native whitespace (spaces, 4-char indent)
- D-13: Post-process normalizer for quoting/escape/token formatting
- D-14: Full KiCad-native byte-identical output (zero diff noise)

### Implementation Constraints
- Python 3.11+ with Pydantic v2
- kiutils 1.4.8 for parsing (known UUID limitation, handled by uuid_extractor)
- No additional parser dependencies -- build on Phase 1 foundation
- Tests must cover: schema validation, IR mutation tracking, rollback correctness, serialization determinism
- Round-trip tests from Phase 1 must continue to pass

### Deferred Ideas (OUT OF SCOPE)
- Cross-file operations (Phase 6)
- ERC/DRC validation gates (Phase 3)
- Actual mutation operations like add_component (Phase 4+)
- networkx graph analysis (Phase 5)
- GSD Skill integration (Phase 7)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| OPS-01 | JSON operation schema for all edit intents (Pydantic v2 models with JSON Schema export) | Pydantic v2.12.5 verified installed; discriminated union pattern with `Field(discriminator=...)` for typed dispatch; `model_json_schema()` for LLM-consumable schema export |
| OPS-02 | Operation validation: reject structurally invalid intents before mutation | Pydantic BaseModel auto-validates on construction; `ValidationError` provides structured field-level errors; `model_validate()` for dict/JSON input |
| OPS-03 | Operation execution: translate validated intent -> IR mutation -> serialized file | IR wrapper classes (D-05/D-07) provide typed mutation methods; Phase 1 serializer layer handles file output; transaction engine (D-08/D-09) wraps the execute-validate-commit cycle |
| FND-07 | Transaction-based mutation with rollback capability | File-level snapshots via `shutil.copy2` (D-08/D-10); auto-rollback on validation failure/exception (D-09); mutation tracking with dirty flag (D-06) |
| FND-08 | Deterministic, SCM-friendly serialization (stable output ordering) | kiutils two-pass round-trip proven stable (Phase 1, 48 tests); post-process normalizer for KiCad-native output (D-11-D-14); known kiutils formatting gaps documented in PITFALLS.md |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Operation schema validation | Python library (Pydantic) | -- | Schema is pure data validation, no I/O |
| IR mutation tracking | Python library (IR classes) | -- | State tracking on kiutils objects |
| Transaction management | Python library (Transaction class) | Filesystem (snapshots) | Snapshots use shutil.copy2 to disk |
| Deterministic serialization | Python library (normalizer) | kiutils (to_sexpr/to_file) | Post-process kiutils output |
| JSON Schema export | Python library (Pydantic) | LLM consumer | Schema generated once, consumed by LLM |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pydantic | 2.12.5 | Operation schema models, JSON Schema export, input validation | [VERIFIED: pip show pydantic] Industry standard, Rust core, native discriminated unions, `model_json_schema()` |
| kiutils | 1.4.8 | Parsed object types that IR wraps | [VERIFIED: pip show kiutils] KiCad-specific dataclass AST, already in use from Phase 1 |

### Supporting (already installed from Phase 1)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| sexpdata | 1.0.0 | Raw S-expression parsing for normalizer edge cases | [VERIFIED: pip show sexpdata] When kiutils output needs structural patching |
| pytest | 8.x | Test framework | All tests |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Pydantic discriminated union | Pydantic with generic `type` field | Discriminated union gives better validation errors and cleaner dispatch. Generic type field requires manual validation logic. |
| File-level snapshot | Delta-based undo log | Delta is complex. KiCad files <10MB make full copy negligible (D-10 decision). |
| Post-process normalizer | Custom kiutils fork | Forking kiutils is high-maintenance. Post-processing is simpler and upstream-compatible. |

**Installation:**
No new dependencies needed. Phase 2 builds entirely on Phase 1's installed packages.

## Architecture Patterns

### System Architecture Diagram

```
                    LLM emits JSON intent
                           |
                           v
                  +------------------+
                  | Pydantic Schema  |  OPS-01, OPS-02
                  | (discriminated   |  Validates intent structure
                  |  union dispatch) |
                  +--------+---------+
                           |
                     validated intent
                           |
                           v
                  +------------------+
                  | Transaction      |  FND-07
                  | begins:          |
                  | 1. shutil.copy2  |  Snapshot original file
                  | 2. Parse file    |  Reuse Phase 1 parsers
                  | 3. Create IR     |  Wrap kiutils obj
                  +--------+---------+
                           |
                           v
                  +------------------+
                  | IR Mutation      |  OPS-03
                  | (SchematicIR,    |  D-05: thin wrapper
                  |  PcbIR, etc.)    |  D-06: mutation tracking
                  |                  |  D-07: per-file-type
                  +--------+---------+
                           |
                           v
                  +------------------+
                  | Serialize +      |  FND-08
                  | Normalize        |  D-11-D-14:
                  | 1. kiutils       |  KiCad-native output
                  | 2. UUID re-inject|
                  | 3. Post-process  |
                  +--------+---------+
                           |
                    +------+------+
                    |             |
                    v             v
              +----------+  +----------+
              | Commit   |  | Rollback |
              | (success)|  | (failure)|
              | Write to |  | Restore  |
              | disk     |  | snapshot |
              +----------+  +----------+
                    |             |
                    v             v
              +----------------------+
              | Result: success or   |
              | error with details   |
              +----------------------+
```

### Recommended Project Structure

```
src/kicad_agent/
+-- schema/                     # NEW: Pydantic operation schema
|   +-- __init__.py
|   +-- operations.py           # Discriminated union of all operation types
|   +-- types.py                # Shared field types (PositionSpec, PropertySpec, etc.)
+-- ir/                         # NEW: Intermediate Representation layer
|   +-- __init__.py
|   +-- base.py                 # BaseIR with mutation tracking (dirty flag, rollback data)
|   +-- schematic_ir.py         # SchematicIR wrapping kiutils.schematic.Schematic
|   +-- pcb_ir.py               # PcbIR wrapping kiutils.board.Board
|   +-- symbol_ir.py            # SymbolLibIR wrapping kiutils.symbol.SymbolLib
|   +-- footprint_ir.py         # FootprintIR wrapping kiutils.footprint.Footprint
+-- transaction/                # NEW: Transaction engine
|   +-- __init__.py
|   +-- transaction.py          # File snapshot, commit, rollback
+-- serializer/
|   +-- normalizer.py           # NEW: Post-kiutils normalization (D-11-D-14)
|   (existing serializers updated to use normalizer)
+-- parser/                     # EXISTING: No changes needed
+-- validation/                 # EXISTING: No changes needed
```

### Pattern 1: Pydantic Discriminated Union for Operations

**What:** Use a Literal discriminator field (`op_type`) on each operation model. A parent `Operation` model uses `Field(discriminator='op_type')` to dispatch validation to the correct subclass.

**When to use:** For all LLM-submitted operation intents. This is the entry point contract.

**Example:**
```python
# Source: Pydantic v2 docs (Context7: /pydantic/pydantic)
from typing import Literal
from pydantic import BaseModel, Field

class AddComponent(BaseModel):
    op_type: Literal["add_component"] = "add_component"
    target_file: str
    library_id: str
    reference: str = "R?"
    value: str = ""
    position: PositionSpec

class RemoveComponent(BaseModel):
    op_type: Literal["remove_component"] = "remove_component"
    target_file: str
    reference: str  # or uuid

class MoveComponent(BaseModel):
    op_type: Literal["move_component"] = "move_component"
    target_file: str
    reference: str
    position: PositionSpec

class Operation(BaseModel):
    """Discriminated union of all operation types."""
    operation: AddComponent | RemoveComponent | MoveComponent | ... = Field(
        discriminator="op_type"
    )

# LLM sends:
Operation.model_validate({
    "operation": {
        "op_type": "add_component",
        "target_file": "motor-driver.kicad_sch",
        "library_id": "Device:R_Small_US",
        "reference": "R?",
        "value": "10k",
        "position": {"x": 50.0, "y": 30.0, "angle": 0}
    }
})

# Export schema for LLM consumption:
schema = Operation.model_json_schema()
```

### Pattern 2: Thin IR Wrapper Over kiutils (D-05)

**What:** Each IR class holds a reference to the parsed kiutils object (not a copy). Mutations apply directly to the kiutils object through IR methods. The IR adds mutation tracking (original values, dirty flag) on top.

**When to use:** For all file-type-specific mutation operations.

**Trade-off vs. separate canonical IR (original architecture research Pattern 2):**
- The original architecture research recommended bidirectional IR mapping (separate canonical dataclasses). D-05 overrides this with thin wrappers.
- Thin wrapper: simpler, fewer mapping bugs, direct kiutils serialization. Risk: tight coupling to kiutils data model.
- Separate IR: cleaner domain model, testable without kiutils. Risk: mapping drift, more code.

**Example:**
```python
from dataclasses import dataclass, field
from typing import Any, Optional
from kiutils.schematic import Schematic
from kicad_agent.parser.uuid_extractor import UUIDMap

@dataclass
class SchematicIR:
    """Thin wrapper over a kiutils Schematic object with mutation tracking."""

    _kiutils_obj: Schematic                           # D-05: reference, not copy
    _uuid_map: Optional[UUIDMap] = None               # D-06: UUID reference for serialization
    _dirty: bool = False                              # D-06: mutation flag
    _mutations: list[dict[str, Any]] = field(default_factory=list)  # D-06: rollback data

    @property
    def schematic(self) -> Schematic:
        return self._kiutils_obj

    @property
    def dirty(self) -> bool:
        return self._dirty

    @property
    def components(self) -> list:
        """Access to schematic symbols (components)."""
        return self._kiutils_obj.schematicSymbols

    def get_component_by_ref(self, reference: str) -> Optional[Any]:
        """Find a component by its reference designator."""
        for sym in self._kiutils_obj.schematicSymbols:
            for prop in sym.properties:
                if prop.key == "Reference" and prop.value == reference:
                    return sym
        return None

    def mark_mutated(self, field_name: str, old_value: Any, new_value: Any) -> None:
        """Record a mutation for potential rollback."""
        self._mutations.append({"field": field_name, "old": old_value, "new": new_value})
        self._dirty = True
```

### Pattern 3: File-Level Transaction with Auto-Rollback (D-08/D-09/D-10)

**What:** Before any mutation, snapshot the entire file with `shutil.copy2`. On failure (validation, exception, or manual), restore from snapshot. No partial states.

**When to use:** For every file-modifying operation. The transaction wraps the entire parse-mutate-serialize-validate cycle.

**Example:**
```python
import shutil
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

@dataclass
class TransactionResult:
    success: bool
    snapshot_path: Optional[Path] = None
    error: Optional[str] = None

class Transaction:
    def __init__(self, file_path: Path):
        self._file_path = file_path.resolve()
        self._snapshot_path: Optional[Path] = None
        self._committed = False
        self._rolled_back = False

    def __enter__(self) -> "Transaction":
        # D-08/D-10: Full file copy before mutation
        self._snapshot_path = self._file_path.with_suffix(
            self._file_path.suffix + ".kicad-agent-snap"
        )
        shutil.copy2(self._file_path, self._snapshot_path)
        return self

    def commit(self) -> TransactionResult:
        """Mark transaction as successful. Removes snapshot."""
        if self._snapshot_path and self._snapshot_path.exists():
            self._snapshot_path.unlink()
        self._committed = True
        return TransactionResult(success=True)

    def rollback(self) -> TransactionResult:
        """D-09: Restore from snapshot on any failure."""
        if self._snapshot_path and self._snapshot_path.exists():
            shutil.copy2(self._snapshot_path, self._file_path)
            self._snapshot_path.unlink()
        self._rolled_back = True
        return TransactionResult(success=False)

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        # D-09: Auto-rollback on exception
        if exc_type is not None and not self._committed:
            self.rollback()
        elif not self._committed and not self._rolled_back:
            self.rollback()
        return False  # Don't suppress exceptions

    @property
    def snapshot_path(self) -> Optional[Path]:
        return self._snapshot_path
```

### Pattern 4: Post-Process Normalizer (D-11/D-12/D-13/D-14)

**What:** After kiutils `to_file()`, run a normalizer pass that fixes property ordering, whitespace, quoting, and token formatting to match KiCad's native output.

**When to use:** After every kiutils serialization. The normalizer is the bridge between kiutils' output and KiCad-native byte-identical output.

**Key normalization rules (from PITFALLS.md and kiutils issues):**
1. Property ordering within S-expression forms must match KiCad canonical order (D-11)
2. Indentation must be spaces with 4-char indent, not tabs (D-12)
3. Floats must use fixed-point notation, never scientific (Pitfall 13)
4. Layer names may need quoting normalization (Pitfall 11)
5. Symbol text angles are in tenths of degrees (Pitfall 1)

**Example:**
```python
import re

def normalize_kicad_output(content: str) -> str:
    """Post-process kiutils output to match KiCad-native format."""
    # Fix scientific notation (Pitfall 13)
    content = _fix_scientific_notation(content)

    # Normalize whitespace (D-12)
    content = _normalize_whitespace(content)

    # Normalize property ordering (D-11)
    # This requires parsing S-expression structure to reorder tokens
    content = _normalize_property_order(content)

    return content

def _fix_scientific_notation(content: str) -> str:
    """Replace scientific notation floats with fixed-point."""
    # Match patterns like 1.5e-07 -> 0.00000015
    def replace_sci(match):
        value = float(match.group(0))
        return f"{value:.6f}"  # or context-aware precision
    return re.sub(r'[-+]?\d+\.?\d*[eE][-+]?\d+', replace_sci, content)
```

### Anti-Patterns to Avoid

- **Mutable global state for transactions:** The transaction must be scoped to a single file operation. Never use module-level mutable state for tracking mutations.
- **Partial rollback:** Never attempt to undo individual mutations. Roll back to the full file snapshot. Partial rollback creates inconsistent states.
- **Normalizer as regex-only:** The normalizer needs structural awareness (understanding S-expression nesting) for property reordering, not just regex substitution. Consider sexpdata for structural passes.
- **Pydantic model per file type for the schema:** The schema models operations (add_component, move_component), not file types. File type is a field on the operation, not a discriminator.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON Schema generation | Custom schema dict builder | Pydantic `model_json_schema()` | [VERIFIED: Context7 /pydantic/pydantic] Handles nested models, discriminated unions, descriptions, required/optional automatically |
| JSON input validation | Manual isinstance checks | Pydantic `model_validate()` | Handles type coercion, nested validation, and produces structured `ValidationError` |
| S-expression serialization | Custom S-expression writer | kiutils `to_file()` / `to_sexpr()` | kiutils handles token ordering, escaping, and nesting. Custom writer will get ordering wrong (Pitfall 7) |
| UUID re-injection for PCB/footprint | New UUID injection code | Phase 1 `uuid_reinjector.reinject_uuids()` | Already proven with 48 passing tests. Handles parent_type cross-checking and positional matching |
| File snapshot/restore | Custom diff-based undo | `shutil.copy2` (D-10) | Full copy is simple, correct, and fast for KiCad file sizes (<10MB typically) |

**Key insight:** Phase 1 already solved the hardest parsing/serialization problems. Phase 2 layers schema, IR, and transaction on top. Do not re-solve Phase 1 problems.

## Common Pitfalls

### Pitfall 1: Pydantic Discriminated Union Requires Literal on Every Model

**What goes wrong:** If any model in the union is missing the discriminator field (e.g., `op_type: Literal["add_component"]`), Pydantic raises `PydanticUserError: Discriminator ... is missing in ...` at class definition time, not validation time.

**Why it happens:** The discriminated union pattern requires every variant to have the discriminator field with a unique Literal value. Missing it on one model breaks the entire union.

**How to avoid:** Define a base class with the discriminator field, or add it to every model explicitly. Verify with a test that instantiates the union model.

**Warning signs:** Import error or class definition error when loading `operations.py`.

### Pitfall 2: kiutils Objects Are Mutable -- IR Mutations Have Side Effects

**What goes wrong:** Since D-05 uses thin wrappers (references to kiutils objects), mutating through the IR mutates the original kiutils object. If the same kiutils object is referenced from multiple IR instances, mutations affect all of them.

**Why it happens:** kiutils dataclasses are mutable (verified: `Position.X = 10` succeeds). The IR wrapper does not copy the object.

**How to avoid:** Enforce one-IR-per-parse-result. Never share kiutils objects between IR instances. Document this invariant clearly in the IR base class.

**Warning signs:** Two IR instances appear to "share" mutations. Tests fail non-deterministically.

### Pitfall 3: Normalizer Breaks Round-Trip Stability

**What goes wrong:** Adding a normalizer pass changes the serialized output. If the normalizer produces output that kiutils cannot parse back identically, the two-pass stability test from Phase 1 breaks.

**Why it happens:** The normalizer modifies kiutils output. If the modification introduces a format that kiutils interprets differently on re-parse, the output diverges on the second pass.

**How to avoid:** Run the two-pass round-trip stability test AFTER adding each normalizer rule. If pass1 != pass2, the normalizer introduced a regression.

**Warning signs:** Phase 1 round-trip tests fail after normalizer is added.

### Pitfall 4: Transaction Snapshot Left on Disk After Crash

**What goes wrong:** If the process crashes between snapshot creation and commit/rollback, the `.kicad-agent-snap` file remains on disk. A subsequent transaction may use a stale snapshot or fail because the snapshot already exists.

**Why it happens:** Crash recovery requires the OS to clean up temp files. There is no guaranteed cleanup.

**How to avoid:** Use unique snapshot names (include PID or timestamp). On transaction start, check for and clean up any existing stale snapshots for the same file. Consider using `tempfile.mkstemp` for the snapshot location.

**Warning signs:** `.kicad-agent-snap` files accumulating in project directories.

### Pitfall 5: JSON Schema Export Produces References (`$defs`) That Confuse LLMs

**What goes wrong:** Pydantic's `model_json_schema()` produces JSON Schema with `$defs` and `$ref` references. Some LLMs (especially when used as tool-calling agents) struggle with `$ref` resolution and may not understand the full schema.

**Why it happens:** Pydantic v2 follows JSON Schema 2020-12 specification, which uses `$defs` for shared definitions. Complex discriminated unions generate many `$ref` entries.

**How to avoid:** Use `model_json_schema(mode='validation')` which produces the validation schema. Consider also providing a flattened version for LLM consumption. Test that the exported schema is usable by the target LLM.

**Warning signs:** LLM sends malformed operations despite schema being provided. Operations consistently miss required fields that are behind `$ref`.

### Pitfall 6: IR Rollback Data Grows Unbounded for Long Sessions

**What goes wrong:** The mutation tracking list (`_mutations`) in the IR accumulates every mutation's old/new values. For long editing sessions with hundreds of mutations, this list grows without bound.

**Why it happens:** D-06 requires tracking mutations for rollback. The thin wrapper approach records every mutation.

**How to avoid:** Since D-08 uses file-level snapshots (not per-mutation rollback), the mutation tracking is primarily for diagnostics/audit, not for actual rollback. Consider making mutation tracking optional or capping the list size. The actual rollback mechanism is the file snapshot, not replaying mutations backwards.

**Warning signs:** Memory usage grows with session length. `_mutations` list has thousands of entries.

## Code Examples

Verified patterns from official sources and existing codebase:

### Pydantic Discriminated Union Schema (OPS-01, OPS-02)

```python
# Source: Context7 /pydantic/pydantic -- discriminated unions
from typing import Literal, Optional
from pydantic import BaseModel, Field
import json

class PositionSpec(BaseModel):
    """Position specification for place operations."""
    x: float
    y: float
    angle: float = 0.0

class AddComponentOp(BaseModel):
    """Add a component to a schematic or PCB."""
    op_type: Literal["add_component"] = "add_component"
    target_file: str
    library_id: str = Field(description="Library reference, e.g. 'Device:R_Small_US'")
    reference: str = Field(default="R?", description="Reference designator")
    value: str = Field(default="", description="Component value")
    position: PositionSpec

class RemoveComponentOp(BaseModel):
    """Remove a component by reference or UUID."""
    op_type: Literal["remove_component"] = "remove_component"
    target_file: str
    reference: str = Field(description="Reference designator to remove")

class MoveComponentOp(BaseModel):
    """Move a component to a new position."""
    op_type: Literal["move_component"] = "move_component"
    target_file: str
    reference: str
    position: PositionSpec

class ModifyPropertyOp(BaseModel):
    """Modify a component property (value, footprint, reference, custom field)."""
    op_type: Literal["modify_property"] = "modify_property"
    target_file: str
    reference: str
    property_name: str
    new_value: str

class Operation(BaseModel):
    """Top-level discriminated union of all operation types."""
    root: AddComponentOp | RemoveComponentOp | MoveComponentOp | ModifyPropertyOp = Field(
        discriminator="op_type"
    )

# Schema export for LLM consumption (OPS-01, D-04)
schema = Operation.model_json_schema()
print(json.dumps(schema, indent=2))

# Validation: reject invalid intents (OPS-02)
from pydantic import ValidationError
try:
    Operation.model_validate({
        "root": {
            "op_type": "add_component",
            "target_file": "test.kicad_sch",
            # Missing required "library_id"
        }
    })
except ValidationError as e:
    print(e)  # Structured error with field path
```

### IR Base with Mutation Tracking (D-05, D-06, D-07)

```python
# Source: Phase 1 codebase patterns + D-05/D-06/D-07 decisions
from dataclasses import dataclass, field
from typing import Any, Optional
from kicad_agent.parser.types import ParseResult
from kicad_agent.parser.uuid_extractor import UUIDMap

@dataclass
class BaseIR:
    """Base class for all IR types. Tracks mutation state.

    D-05: Holds reference to kiutils object (not a copy).
    D-06: Tracks mutations, UUID map reference, dirty flag.
    """
    _parse_result: ParseResult
    _uuid_map: Optional[UUIDMap] = None
    _dirty: bool = False
    _mutation_log: list[dict[str, Any]] = field(default_factory=list)

    @property
    def file_path(self) -> Any:
        return self._parse_result.file_path

    @property
    def file_type(self) -> str:
        return self._parse_result.file_type

    @property
    def dirty(self) -> bool:
        return self._dirty

    @property
    def kiutils_obj(self) -> Any:
        """Direct access to the underlying kiutils object."""
        return self._parse_result.kiutils_obj

    def _record_mutation(self, description: str, details: dict[str, Any]) -> None:
        """Record a mutation for audit/diagnostic purposes."""
        self._mutation_log.append({"description": description, **details})
        self._dirty = True
```

### Transaction with File-Level Snapshot (D-08, D-09, D-10)

```python
# Source: D-08/D-09/D-10 decisions + shutil.copy2
import shutil
import tempfile
from pathlib import Path
from typing import Optional
from contextlib import contextmanager
from dataclasses import dataclass

@dataclass(frozen=True)
class TransactionResult:
    success: bool
    target_file: Path
    snapshot_created: bool
    error: Optional[str] = None

@contextmanager
def file_transaction(file_path: Path):
    """Context manager for file-level transaction with auto-rollback.

    D-08: Snapshot entire file before mutation.
    D-10: Use shutil.copy2 for full copy.
    D-09: Auto-rollback on exception or explicit rollback call.
    """
    resolved = file_path.resolve()
    # Create snapshot in temp directory to avoid polluting project
    snap_dir = tempfile.mkdtemp(prefix="kicad-agent-")
    snap_path = Path(snap_dir) / resolved.name

    # D-10: Full file copy
    shutil.copy2(resolved, snap_path)

    result = TransactionResult(
        success=False,
        target_file=resolved,
        snapshot_created=True,
    )

    try:
        yield resolved
        # If we reach here without exception, caller should call commit()
    except Exception:
        # D-09: Auto-rollback on exception
        shutil.copy2(snap_path, resolved)
        result = TransactionResult(
            success=False,
            target_file=resolved,
            snapshot_created=False,
            error="Rolled back due to exception",
        )
        raise
    finally:
        # Clean up snapshot
        snap_path.unlink(missing_ok=True)
        Path(snap_dir).rmdir()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Pydantic v1 `schema_of()` | Pydantic v2 `model_json_schema()` | Pydantic v2 release | New API, better JSON Schema 2020-12 compliance, `mode` parameter |
| Pydantic v1 `parse_obj()` | Pydantic v2 `model_validate()` | Pydantic v2 release | Unified validation entry point |
| Separate canonical IR dataclasses | Thin wrapper over kiutils (D-05) | 2026-05-18 discuss-phase | Simpler, fewer mapping bugs, tighter kiutils coupling |
| Delta-based undo logs | File-level snapshots (D-08) | 2026-05-18 discuss-phase | Simpler rollback, negligible cost for KiCad file sizes |
| Accept kiutils formatting differences | Post-process normalizer (D-13) | 2026-05-18 discuss-phase | Zero diff noise but adds normalizer complexity |

**Deprecated/outdated:**
- Bidirectional IR mapping (from architecture research): Replaced by D-05 thin wrapper. The separate canonical IR pattern is still valid for larger projects, but overkill when kiutils provides a usable data model.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | kiutils `to_sexpr()` output is deterministic across runs (same input produces same output) | Serialization | Phase 1 two-pass test proves this for pass1==pass2, but not yet proven for KiCad-native byte-identical |
| A2 | Pydantic v2 discriminated unions export correctly to JSON Schema with `$defs` that LLMs can consume | Schema | LLM may struggle with `$ref` resolution; may need flattened schema |
| A3 | The post-process normalizer can achieve byte-identical output to KiCad-native format | Normalizer | kiutils may have fundamental structural differences that regex/sexpdata cannot normalize |
| A4 | File-level snapshot with `shutil.copy2` is fast enough for KiCad files (typically <10MB) | Transaction | Very large PCB files (>50MB) could make snapshot slow, but these are rare |
| A5 | kiutils mutable dataclasses will remain mutable in future versions | IR Layer | If kiutils freezes dataclasses, the thin wrapper approach breaks |

**If this table is empty:** All claims in this research were verified or cited.

## Open Questions

1. **Normalizer scope: How many normalization rules are needed?**
   - What we know: kiutils has known issues with scientific notation (Pitfall 13), property ordering (D-11), and layer quoting (Pitfall 11). The two-pass test proves deterministic output.
   - What's unclear: Whether normalization requires structural S-expression parsing (via sexpdata) or can be done with regex. Property reordering (D-11) likely needs structural awareness.
   - Recommendation: Start with regex-based fixes (scientific notation, whitespace). Add sexpdata-based structural normalization for property ordering. Test after each rule.

2. **Schema scope: How many operation types for Phase 2?**
   - What we know: Phase 2 defines the schema framework, not specific operations. Operations are added in Phase 4+.
   - What's unclear: Should Phase 2 define a minimal set of "example" operations (add_component, remove_component, move_component) to prove the schema works end-to-end?
   - Recommendation: Yes -- define 3-5 example operations in Phase 2 to validate the discriminated union pattern. These serve as templates for Phase 4+.

3. **IR mutation tracking granularity**
   - What we know: D-06 says track which fields were mutated and original values. D-08 says use file-level snapshots for rollback.
   - What's unclear: Whether mutation tracking is for audit/diagnostics only, or for per-field undo.
   - Recommendation: Mutation tracking is for audit only. Actual rollback uses the file snapshot. This simplifies the IR significantly.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.11+ | Runtime | True | 3.11.x | -- |
| pydantic | Schema | True | 2.12.5 | -- |
| kiutils | IR/Parsing | True | 1.4.8 | -- |
| sexpdata | Normalizer | True | 1.0.0 | -- |
| pytest | Testing | True | 8.x | -- |
| kicad-cli | Validation (Phase 3) | True | 10.0.1 | Not needed for Phase 2 |

**Missing dependencies with no fallback:**
- None. All Phase 2 dependencies are installed.

**Missing dependencies with fallback:**
- None needed for Phase 2. kicad-cli is not required until Phase 3.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x |
| Config file | pyproject.toml `[tool.pytest.ini_options]` |
| Quick run command | `cd ~/apps/kicad-agent && python -m pytest tests/ -x -q` |
| Full suite command | `cd ~/apps/kicad-agent && python -m pytest tests/ -v --tb=short` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| OPS-01 | Pydantic schema validates valid intents and rejects invalid ones | unit | `pytest tests/test_schema/test_operations.py -x` | Wave 0 |
| OPS-01 | JSON Schema exportable for LLM consumption | unit | `pytest tests/test_schema/test_operations.py::test_json_schema_export -x` | Wave 0 |
| OPS-02 | Invalid intents produce structured ValidationError | unit | `pytest tests/test_schema/test_operations.py::test_invalid_intent_rejection -x` | Wave 0 |
| OPS-03 | Validated intent translates to IR mutation on parsed file | integration | `pytest tests/test_ir/test_schematic_ir.py::test_mutation_from_intent -x` | Wave 0 |
| OPS-03 | Mutated IR serializes to deterministic output | integration | `pytest tests/test_ir/test_serialization_determinism.py -x` | Wave 0 |
| FND-07 | Failed mutation rolls back to pre-mutation state | unit | `pytest tests/test_transaction/test_transaction.py::test_rollback -x` | Wave 0 |
| FND-07 | Successful mutation commits and removes snapshot | unit | `pytest tests/test_transaction/test_transaction.py::test_commit -x` | Wave 0 |
| FND-08 | Serialized output is deterministic (same input -> same output) | unit | `pytest tests/test_serializer/test_normalizer.py::test_determinism -x` | Wave 0 |
| FND-08 | Normalized output matches KiCad-native format | integration | `pytest tests/test_serializer/test_normalizer.py::test_kicad_native -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `cd ~/apps/kicad-agent && python -m pytest tests/ -x -q`
- **Per wave merge:** `cd ~/apps/kicad-agent && python -m pytest tests/ -v --tb=short`
- **Phase gate:** Full suite green + Phase 1 round-trip tests still pass

### Wave 0 Gaps
- `tests/test_schema/test_operations.py` -- covers OPS-01, OPS-02
- `tests/test_schema/__init__.py` -- package init
- `tests/test_ir/test_schematic_ir.py` -- covers IR creation and mutation tracking
- `tests/test_ir/test_pcb_ir.py` -- covers PCB IR
- `tests/test_ir/test_symbol_ir.py` -- covers symbol IR
- `tests/test_ir/test_footprint_ir.py` -- covers footprint IR
- `tests/test_ir/__init__.py` -- package init
- `tests/test_transaction/test_transaction.py` -- covers FND-07
- `tests/test_transaction/__init__.py` -- package init
- `tests/test_serializer/test_normalizer.py` -- covers FND-08

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V5 Input Validation | yes | Pydantic v2 BaseModel auto-validates all inputs; `model_validate()` for dict/JSON input; `ValidationError` for structured error reporting |
| V6 Cryptography | no | No encryption or hashing in Phase 2 |
| V2 Authentication | no | No authentication in Phase 2 |
| V4 Access Control | partial | File-path validation (target_file must exist and be a KiCad file type) |

### Known Threat Patterns for Pydantic Schema / File Mutation

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Malformed JSON injection via LLM intent | Tampering | Pydantic `model_validate()` rejects non-conforming JSON with structured errors |
| Path traversal in target_file | Tampering | Validate `target_file` resolves to an existing file with expected suffix |
| Excessive mutation log memory | Denial of Service | Cap `_mutation_log` size; file-level snapshots don't require log replay |
| Snapshot file left on crash | Information Disclosure | Use temp directory for snapshots; unique names per transaction |

## Sources

### Primary (HIGH confidence)
- Context7 `/pydantic/pydantic` -- discriminated unions, model_json_schema, model_validate, Field discriminator
- Context7 `/mvnmgrx/kiutils` -- Schematic, Board, Footprint, SymbolLib APIs; to_file, to_sexpr, from_file
- Phase 1 codebase: parser/types.py, parser/uuid_extractor.py, serializer/uuid_reinjector.py, validation/roundtrip.py -- all verified locally
- pip show verification: pydantic 2.12.5, kiutils 1.4.8, sexpdata 1.0.0

### Secondary (MEDIUM confidence)
- Pydantic v2 official docs (pydantic docs via Context7 `/websites/pydantic_dev_validation`) -- JSON Schema generation, validation modes
- kiutils GitHub issues: #14 (scientific notation), #102 (layer quoting), #120 (hidden properties) -- verified 2026-05-18
- PITFALLS.md from project research -- 18 pitfalls documented with prevention strategies

### Tertiary (LOW confidence)
- A1: kiutils output will eventually be byte-identical to KiCad-native after normalization -- needs implementation to verify
- A3: The normalizer can close the gap between kiutils output and KiCad-native format -- unproven until implemented

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all dependencies verified installed, versions confirmed
- Architecture: HIGH -- patterns verified against Context7 docs and existing codebase
- Pitfalls: HIGH -- derived from official KiCad spec, kiutils issues, and Phase 1 experience
- Normalizer feasibility: MEDIUM -- kiutils output is deterministic (proven), but byte-identical to KiCad-native is aspirational

**Research date:** 2026-05-18
**Valid until:** 2026-06-17 (30 days -- stable dependencies)
