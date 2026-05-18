# Phase 2: Operation Schema and IR Layer - Pattern Map

**Mapped:** 2026-05-18
**Files analyzed:** 10 new files
**Analogs found:** 10 / 10

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/kicad_agent/ops/__init__.py` | config | request-response | `src/kicad_agent/parser/__init__.py` | exact (package init pattern) |
| `src/kicad_agent/ops/schema.py` | model | transform | `src/kicad_agent/parser/types.py` + RESEARCH.md Pattern 1 | role-match (Pydantic instead of dataclass) |
| `src/kicad_agent/ir/__init__.py` | config | request-response | `src/kicad_agent/parser/__init__.py` | exact (package init pattern) |
| `src/kicad_agent/ir/base.py` | model | transform | `src/kicad_agent/parser/types.py` | role-match (base dataclass pattern) |
| `src/kicad_agent/ir/schematic_ir.py` | service | CRUD | `src/kicad_agent/parser/schematic_parser.py` + RESEARCH.md Pattern 2 | role-match (wraps Schematic) |
| `src/kicad_agent/ir/pcb_ir.py` | service | CRUD | `src/kicad_agent/parser/pcb_parser.py` + RESEARCH.md Pattern 2 | role-match (wraps Board) |
| `src/kicad_agent/ir/symbol_lib_ir.py` | service | CRUD | `src/kicad_agent/parser/symbol_parser.py` + RESEARCH.md Pattern 2 | role-match (wraps SymbolLib) |
| `src/kicad_agent/ir/footprint_ir.py` | service | CRUD | `src/kicad_agent/parser/footprint_parser.py` + RESEARCH.md Pattern 2 | role-match (wraps Footprint) |
| `src/kicad_agent/ir/transaction.py` | service | file-I/O | `src/kicad_agent/validation/roundtrip.py` + RESEARCH.md Pattern 3 | role-match (orchestration) |
| `src/kicad_agent/serializer/normalizer.py` | utility | transform | `src/kicad_agent/serializer/uuid_reinjector.py` + RESEARCH.md Pattern 4 | role-match (post-processing) |

## Pattern Assignments

### `src/kicad_agent/ops/__init__.py` (config, request-response)

**Analog:** `src/kicad_agent/parser/__init__.py` (lines 1-15)

This is a standard Python package init. Follow the barrel-export pattern.

**Pattern** (from `parser/__init__.py`):
```python
"""KiCad file parsers for all four file types plus raw S-expression fallback."""

from kicad_agent.parser.schematic_parser import parse_schematic
from kicad_agent.parser.pcb_parser import parse_pcb
from kicad_agent.parser.symbol_parser import parse_symbol_lib
from kicad_agent.parser.footprint_parser import parse_footprint
from kicad_agent.parser.raw_parser import parse_raw_sexp

__all__ = [
    "parse_schematic",
    "parse_pcb",
    "parse_symbol_lib",
    "parse_footprint",
    "parse_raw_sexp",
]
```

For ops package, export the Operation discriminated union and shared types:
```python
"""Pydantic v2 operation schema for AI-safe KiCad editing."""

from kicad_agent.ops.schema import Operation

__all__ = ["Operation"]
```

---

### `src/kicad_agent/ops/schema.py` (model, transform)

**Analog:** `src/kicad_agent/parser/types.py` (shared type definitions)

This file defines the Pydantic operation schema. Unlike `types.py` which uses `dataclass(frozen=True)`, this uses Pydantic `BaseModel`. The structural pattern (shared types in one module, consumed by all others) is the same.

**Docstring pattern** (from `parser/types.py` lines 1-6):
```python
"""Shared type definitions for KiCad file parsers.

Centralizes the ParseResult dataclass used by all four typed parsers
(schematic, PCB, symbol library, footprint) to eliminate duplication.
"""
```

**Frozen dataclass pattern** (from `parser/types.py` lines 8-26):
```python
from pathlib import Path
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParseResult:
    """Generic container for parsed KiCad file content."""
    kiutils_obj: Any
    raw_content: str
    file_path: Path
    file_type: str
```

**Core schema pattern** (from RESEARCH.md Pattern 1, verified against Pydantic v2 docs):
```python
from typing import Literal
from pydantic import BaseModel, Field


class PositionSpec(BaseModel):
    """Position specification for place operations."""
    x: float
    y: float
    angle: float = 0.0


class AddComponentOp(BaseModel):
    op_type: Literal["add_component"] = "add_component"
    target_file: str
    library_id: str = Field(description="Library reference, e.g. 'Device:R_Small_US'")
    reference: str = Field(default="R?", description="Reference designator")
    value: str = Field(default="", description="Component value")
    position: PositionSpec


class Operation(BaseModel):
    """Top-level discriminated union of all operation types."""
    root: AddComponentOp | RemoveComponentOp | MoveComponentOp | ModifyPropertyOp = Field(
        discriminator="op_type"
    )
```

**Validation pattern** (from RESEARCH.md, Pydantic v2):
```python
from pydantic import ValidationError

# Auto-validation on construction (OPS-02)
try:
    Operation.model_validate({"root": {...}})
except ValidationError as e:
    # Structured field-level errors
    pass

# Schema export (OPS-01, D-04)
schema = Operation.model_json_schema()
```

**Error handling:** Pydantic `ValidationError` provides structured field-level error messages automatically. No manual validation logic needed.

---

### `src/kicad_agent/ir/__init__.py` (config, request-response)

**Analog:** `src/kicad_agent/parser/__init__.py` (lines 1-15)

Same barrel-export pattern as ops package. Export all IR classes.

```python
"""Intermediate Representation layer for KiCad file mutation tracking."""

from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.ir.pcb_ir import PcbIR
from kicad_agent.ir.symbol_lib_ir import SymbolLibIR
from kicad_agent.ir.footprint_ir import FootprintIR

__all__ = [
    "SchematicIR",
    "PcbIR",
    "SymbolLibIR",
    "FootprintIR",
]
```

---

### `src/kicad_agent/ir/base.py` (model, transform)

**Analog:** `src/kicad_agent/parser/types.py` (shared base types)

This is the base class for all IR types. Follows the same pattern as `ParseResult` -- a shared data class consumed by all type-specific implementations. But uses mutable `dataclass` (not frozen) because D-06 requires tracking mutation state.

**Imports pattern** (from `parser/types.py` lines 8-9):
```python
from pathlib import Path
from dataclasses import dataclass
from typing import Any
```

**Core pattern** (from RESEARCH.md Pattern 2, adapted to project conventions):
```python
"""Base IR class with mutation tracking for all file-type IR wrappers.

D-05: Holds reference to ParseResult (which contains kiutils obj).
D-06: Tracks mutations, UUID map reference, dirty flag.
"""

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
        return self._parse_result.kiutils_obj

    def _record_mutation(self, description: str, details: dict[str, Any]) -> None:
        self._mutation_log.append({"description": description, **details})
        self._dirty = True
```

**Key difference from `types.py`:** `ParseResult` is `frozen=True` (immutable). `BaseIR` is mutable because it tracks state. This is intentional per D-06.

---

### `src/kicad_agent/ir/schematic_ir.py` (service, CRUD)

**Analog:** `src/kicad_agent/parser/schematic_parser.py`

Each IR class wraps a specific kiutils type, just as each parser returns a `ParseResult` for a specific file type. The pattern is parallel: one module per file type, same validation, same docstring structure.

**Docstring pattern** (from `parser/schematic_parser.py` lines 1-12):
```python
"""Schematic (.kicad_sch) file parser.

Parses KiCad schematic files into kiutils Schematic objects with raw content
preservation for downstream processing.

Usage:
    from kicad_agent.parser.schematic_parser import parse_schematic

    result = parse_schematic(Path("my_schematic.kicad_sch"))
    components = result.kiutils_obj.schematicSymbols
"""
```

**Imports pattern** (from `parser/schematic_parser.py` lines 14-18):
```python
from pathlib import Path
from kiutils.schematic import Schematic
from kicad_agent.parser.types import ParseResult
```

**Validation pattern** (from `parser/schematic_parser.py` lines 39-44):
```python
resolved = path.resolve()
if not resolved.exists():
    raise FileNotFoundError(f"Schematic file not found: {path}")
if resolved.suffix != ".kicad_sch":
    raise ValueError(f"Expected .kicad_sch file, got {resolved.suffix}")
```

**Core IR pattern** (from RESEARCH.md Pattern 2):
```python
from dataclasses import dataclass
from typing import Optional, Any

from kicad_agent.ir.base import BaseIR
from kicad_agent.parser.types import ParseResult
from kicad_agent.parser.uuid_extractor import UUIDMap
from kiutils.schematic import Schematic


@dataclass
class SchematicIR(BaseIR):
    """Thin wrapper over a kiutils Schematic object with mutation tracking."""

    @property
    def schematic(self) -> Schematic:
        return self._parse_result.kiutils_obj

    @property
    def components(self) -> list:
        return self._parse_result.kiutils_obj.schematicSymbols

    def get_component_by_ref(self, reference: str) -> Optional[Any]:
        for sym in self._parse_result.kiutils_obj.schematicSymbols:
            for prop in sym.properties:
                if prop.key == "Reference" and prop.value == reference:
                    return sym
        return None
```

---

### `src/kicad_agent/ir/pcb_ir.py` (service, CRUD)

**Analog:** `src/kicad_agent/parser/pcb_parser.py`

Same pattern as `schematic_ir.py` but wrapping `kiutils.board.Board`. Follow the pcb_parser's convention of documenting the UUID limitation.

**Docstring note** (from `parser/pcb_parser.py` lines 5-6):
```python
# CRITICAL: kiutils drops all UUID tokens from PCB files (only handles legacy tstamp).
# Raw content MUST be preserved for UUID extraction via the raw_parser or regex.
```

**Core pattern:** Same structure as `SchematicIR`, but:
- Wraps `Board` instead of `Schematic`
- Exposes `footprints`, `nets`, `segments`, `vias` properties
- Requires `_uuid_map` for serialization (PCB UUIDs are dropped by kiutils)

---

### `src/kicad_agent/ir/symbol_lib_ir.py` (service, CRUD)

**Analog:** `src/kicad_agent/parser/symbol_parser.py`

Same pattern as `schematic_ir.py` but wrapping `kiutils.symbol.SymbolLib`. Note from symbol_parser: kiutils silently drops `exclude_from_sim` tokens.

**Core pattern:** Wraps `SymbolLib`, exposes `symbols` property. No UUID map needed (symbol libraries preserve UUIDs via kiutils).

---

### `src/kicad_agent/ir/footprint_ir.py` (service, CRUD)

**Analog:** `src/kicad_agent/parser/footprint_parser.py`

Same pattern as `pcb_ir.py` -- wraps `kiutils.footprint.Footprint` and requires UUID map for the same reason (kiutils drops UUID tokens from footprint files).

**Core pattern:** Wraps `Footprint`, exposes `pads`, `fp_lines`, `fp_text` properties. Requires `_uuid_map` for serialization.

---

### `src/kicad_agent/ir/transaction.py` (service, file-I/O)

**Analog:** `src/kicad_agent/validation/roundtrip.py` (orchestration layer)

The transaction module orchestrates the parse-mutate-serialize-validate cycle, similar to how `roundtrip.py` orchestrates the two-pass stability test. Both use context managers, file I/O, and coordinate multiple modules.

**Imports pattern** (from `validation/roundtrip.py` lines 19-32):
```python
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from kicad_agent.parser.schematic_parser import parse_schematic
from kicad_agent.parser.pcb_parser import parse_pcb
# ... more imports
```

**Frozen result dataclass** (from `validation/roundtrip.py` lines 57-78):
```python
@dataclass(frozen=True)
class RoundTripResult:
    """Detailed result of a two-pass round-trip stability test."""
    is_stable: bool
    original_path: Path
    pass1_path: Optional[Path] = None
    pass2_path: Optional[Path] = None
    file_type: str = ""
    uuid_preserved: Optional[bool] = None
    error: Optional[str] = None
```

**Core transaction pattern** (from RESEARCH.md Pattern 3):
```python
import shutil
import tempfile
from pathlib import Path
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class TransactionResult:
    success: bool
    target_file: Path
    snapshot_created: bool
    error: Optional[str] = None


class Transaction:
    """File-level transaction with auto-rollback.

    D-08: Snapshot entire file before mutation.
    D-09: Auto-rollback on exception or explicit rollback call.
    D-10: Use shutil.copy2 for full file copy.
    """

    def __init__(self, file_path: Path):
        self._file_path = file_path.resolve()
        self._snapshot_path: Optional[Path] = None
        self._committed = False
        self._rolled_back = False

    def __enter__(self) -> "Transaction":
        snap_dir = tempfile.mkdtemp(prefix="kicad-agent-")
        self._snapshot_path = Path(snap_dir) / self._file_path.name
        shutil.copy2(self._file_path, self._snapshot_path)
        return self

    def commit(self) -> TransactionResult:
        if self._snapshot_path and self._snapshot_path.exists():
            self._snapshot_path.unlink()
            self._snapshot_path.parent.rmdir()
        self._committed = True
        return TransactionResult(
            success=True,
            target_file=self._file_path,
            snapshot_created=True,
        )

    def rollback(self) -> TransactionResult:
        if self._snapshot_path and self._snapshot_path.exists():
            shutil.copy2(self._snapshot_path, self._file_path)
            self._snapshot_path.unlink()
            self._snapshot_path.parent.rmdir()
        self._rolled_back = True
        return TransactionResult(
            success=False,
            target_file=self._file_path,
            snapshot_created=True,
            error="Rolled back",
        )

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is not None and not self._committed:
            self.rollback()
        elif not self._committed and not self._rolled_back:
            self.rollback()
        return False
```

**Error handling pattern** (from `validation/roundtrip.py` lines 176-216):
```python
try:
    # ... operation
    return RoundTripResult(is_stable=is_stable, ...)
except Exception as e:
    return RoundTripResult(is_stable=False, error=str(e))
```

For transactions: exceptions in `__exit__` trigger auto-rollback. Wrap in try/except and return `TransactionResult` with error details.

---

### `src/kicad_agent/serializer/normalizer.py` (utility, transform)

**Analog:** `src/kicad_agent/serializer/uuid_reinjector.py`

The normalizer is a post-processing step after kiutils serialization, just as `uuid_reinjector.py` is a post-processing step. Both take serialized string content, transform it, and return the modified string. Both use regex-based text manipulation.

**Docstring pattern** (from `serializer/uuid_reinjector.py` lines 1-21):
```python
"""UUID re-injection into kiutils serialized output.

kiutils drops UUID tokens from PCB and footprint files during serialization.
This module re-inserts UUIDs into the correct positions within the kiutils
output, using a UUIDMap extracted from the original raw content.

Usage:
    from kicad_agent.serializer.uuid_reinjector import reinject_uuids
    restored = reinject_uuids(serialized_content, uuid_map)
"""
```

**Imports and regex pattern** (from `serializer/uuid_reinjector.py` lines 23-28):
```python
import logging
import re
from kicad_agent.parser.uuid_extractor import UUIDMap

logger = logging.getLogger(__name__)
```

**Core function pattern** (from `serializer/uuid_reinjector.py` lines 150-165):
```python
def reinject_uuids(serialized_content: str, uuid_map: UUIDMap) -> str:
    """Re-inject UUID tokens into kiutils serialized output."""
    if not uuid_map.entries:
        return serialized_content
    # ... process content
    return result
```

**Normalizer pattern** (from RESEARCH.md Pattern 4):
```python
"""Post-process kiutils output to match KiCad-native format.

After kiutils to_file() serialization, run a normalization pass that fixes
property ordering, whitespace, quoting, and token formatting to match
KiCad's native output (D-11 through D-14).

Usage:
    from kicad_agent.serializer.normalizer import normalize_kicad_output
    normalized = normalize_kicad_output(kiutils_output)
"""

import logging
import re

logger = logging.getLogger(__name__)


def normalize_kicad_output(content: str) -> str:
    """Post-process kiutils output to match KiCad-native format."""
    content = _fix_scientific_notation(content)
    content = _normalize_whitespace(content)
    content = _normalize_property_order(content)
    return content
```

**Regex pattern for scientific notation** (from RESEARCH.md):
```python
def _fix_scientific_notation(content: str) -> str:
    """Replace scientific notation floats with fixed-point (Pitfall 13)."""
    def replace_sci(match):
        value = float(match.group(0))
        return f"{value:.6f}"
    return re.sub(r'[-+]?\d+\.?\d*[eE][-+]?\d+', replace_sci, content)
```

---

## Shared Patterns

### Package Init Pattern
**Source:** `src/kicad_agent/parser/__init__.py`, `src/kicad_agent/serializer/__init__.py`, `src/kicad_agent/validation/__init__.py`
**Apply to:** `ops/__init__.py`, `ir/__init__.py`

All packages follow the same convention:
1. Module docstring describing the package purpose
2. Explicit imports from submodules
3. `__all__` list for public API
4. No logic, no side effects

```python
"""One-line package description."""

from package.module import PublicClass

__all__ = ["PublicClass"]
```

### Docstring Convention
**Source:** All existing modules in `parser/`, `serializer/`, `validation/`
**Apply to:** All new files

Every module follows this docstring template:
```python
"""Module purpose in one sentence.

Detailed description of what the module does, key design decisions,
and critical caveats (e.g., UUID dropping, formatting quirks).

Usage:
    from kicad_agent.module import public_api

    result = public_api(args)
"""
```

### Frozen Result Dataclasses
**Source:** `src/kicad_agent/parser/types.py` (ParseResult), `src/kicad_agent/validation/roundtrip.py` (RoundTripResult), `src/kicad_agent/parser/uuid_extractor.py` (UUIDEntry, UUIDMap)
**Apply to:** `TransactionResult`, any result types in the new modules

All result containers use `@dataclass(frozen=True)` for immutability:
```python
@dataclass(frozen=True)
class ResultType:
    """Result description."""
    success: bool
    error: Optional[str] = None
```

Exception: `BaseIR` is intentionally mutable (D-06 requires tracking mutation state).

### Error Handling
**Source:** All parsers (`schematic_parser.py`, `pcb_parser.py`, etc.)
**Apply to:** IR constructors, transaction module, normalizer

Consistent error pattern across the codebase:
```python
# File existence check
if not resolved.exists():
    raise FileNotFoundError(f"{FileTypeName} file not found: {path}")

# File type validation
if resolved.suffix != ".kicad_ext":
    raise ValueError(f"Expected .kicad_ext file, got {resolved.suffix}")

# Size limit (DoS mitigation, from raw_parser.py lines 40-41)
max_size = 50 * 1024 * 1024
if file_size > max_size:
    raise ValueError(f"File exceeds 50MB size limit ({file_size} bytes): {path}")
```

### Testing Pattern
**Source:** `tests/test_parser/test_schematic_parser.py`, `tests/test_roundtrip/test_roundtrip_stability.py`
**Apply to:** All new test files

Test structure follows:
1. Module docstring referencing requirement IDs (e.g., `OPS-01`, `FND-07`)
2. Class per test group (e.g., `TestParseSchematic`)
3. Descriptive test names following `test_<behavior>` convention
4. Fixtures from `conftest.py` for file paths (`arduino_mega_sch`, `tmp_output_dir`)
5. `pytest.raises` for expected failures
6. `@pytest.fixture` decorated functions for test setup

```python
"""Tests for operation schema -- OPS-01, OPS-02."""

from pathlib import Path
import pytest
from kicad_agent.ops.schema import Operation


class TestOperationSchema:
    """OPS-01: Pydantic operation schema validates intents."""

    def test_valid_add_component(self) -> None:
        """Valid add_component intent passes validation."""
        ...

    def test_invalid_intent_rejection(self) -> None:
        """Missing required fields produce ValidationError."""
        with pytest.raises(ValidationError, match="..."):
            Operation.model_validate({...})
```

### Import Ordering Convention
**Source:** All existing modules
**Apply to:** All new files

Consistent import order observed across the codebase:
1. Standard library (`pathlib`, `dataclasses`, `typing`, `re`, `logging`, `shutil`)
2. Third-party (`kiutils`, `pydantic`, `sexpdata`, `pytest`)
3. Project-internal (`from kicad_agent.parser...`, `from kicad_agent.serializer...`)

Groups separated by blank lines.

## No Analog Found

All 10 files have usable analogs in the existing codebase. The closest matches are:

| File | Analog Quality | Notes |
|------|---------------|-------|
| `ops/schema.py` | partial (Pydantic is new to the codebase) | Use `parser/types.py` for structural pattern, RESEARCH.md Pattern 1 for Pydantic specifics |
| `serializer/normalizer.py` | partial (regex post-processing exists in uuid_reinjector) | The structural S-expression normalization (property ordering) is new -- may need `sexpdata` |

For files with partial analogs, the RESEARCH.md Code Examples section provides Pydantic-specific patterns that should be used alongside the codebase conventions above.

## Metadata

**Analog search scope:** `/Users/bretbouchard/apps/kicad-agent/src/kicad_agent/` (parser/, serializer/, validation/)
**Files scanned:** 17 source files + 8 test files
**Pattern extraction date:** 2026-05-18
