# Phase 205: Board Metadata Foundation — Pattern Mapping

**Purpose:** For each file to create/modify, identify the closest existing analog and extract the concrete code pattern the executor should follow. The planner uses these excerpts verbatim as templates.

**Verified current state:**
- Registry count: **151** (test at `tests/test_registry.py:26` still asserts `== 142` — STALE)
- 3 ops already missing from registry: `add_design_note`, `apply_floor_plan`, `place_and_wire_power_units` (pre-existing tech debt, out of scope for Phase 205)
- Schema union has variants matching registry. After adding 3 ops: **154 registry entries**.

---

## 1. CREATE: `src/volta/manufacturing/__init__.py`

**Role:** Package init — exports public API.
**Closest analog:** `src/volta/dfm/__init__.py` (lines 1-31).

**Pattern excerpt** (`dfm/__init__.py`):
```python
"""Design for Manufacturing module.

DFM-01 through DFM-05: Pluggable DFM check framework with manufacturer profiles...
"""
from volta.dfm.checker import DfmChecker, DfmCheck, DfmReport, DfmFinding, DfmSeverity
from volta.dfm.profiles import ManufacturerProfile, load_profile, get_builtin_profiles

__all__ = [
    "DfmChecker", "DfmCheck", "DfmReport", "DfmFinding", "DfmSeverity",
    "ManufacturerProfile", "load_profile", "get_builtin_profiles",
]
```

**Apply:** docstring + imports from `board_spec.py` + `__all__`. RESEARCH.md RQ7 provides the exact content:
```python
"""Manufacturing layer — board specs, build records, handoff packages.

Phase 205: BoardSpec model + sidecar JSON persistence.
"""
from volta.manufacturing.board_spec import (
    BoardSpec, ImpedanceRequirement,
    SurfaceFinish, SoldermaskColor, SilkscreenColor,
    load_board_spec, save_board_spec,
)
__all__ = [
    "BoardSpec", "ImpedanceRequirement",
    "SurfaceFinish", "SoldermaskColor", "SilkscreenColor",
    "load_board_spec", "save_board_spec",
]
```

---

## 2. CREATE: `src/volta/manufacturing/board_spec.py`

**Role:** Pydantic model + enums + sidecar JSON load/save functions.
**Closest analog (model):** `src/volta/dfm/profiles.py` `ManufacturerProfile` (lines 24-102) — pydantic `BaseModel` with `Field(...)` constraints + `from_json`/`from_dict` classmethods.
**Closest analog (atomic write):** `src/volta/io/atomic_write.py` `atomic_write` (lines 15-43).

### 2a. Model + Enum pattern

**Excerpt** (`dfm/profiles.py:24-54`):
```python
from pydantic import BaseModel, Field

class ManufacturerProfile(BaseModel):
    """Manufacturer-specific PCB manufacturing constraints."""
    name: str = Field(min_length=1, max_length=256)
    min_trace_width_mm: float = Field(gt=0, description="Minimum trace width (mm)")
    min_drill_mm: float = Field(gt=0, description="Minimum drill diameter (mm)")
    supports_blind_vias: bool = Field(default=False)
    extra: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_json(cls, path_or_string: str) -> ManufacturerProfile:
        path = Path(path_or_string)
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            data = json.loads(path_or_string)
        return cls.model_validate(data)
```

**Apply — BoardSpec structure:**
```python
from enum import Enum
from pathlib import Path
from pydantic import BaseModel, Field
from volta.io.atomic_write import atomic_write

class SurfaceFinish(str, Enum):
    HASL = "HASL"
    ENIG = "ENIG"
    # ... (str, Enum subclasses — serialize as name string per RQ4)

class SoldermaskColor(str, Enum):
    GREEN = "GREEN"
    # ...

class SilkscreenColor(str, Enum):
    WHITE = "WHITE"
    BLACK = "BLACK"

class ImpedanceRequirement(BaseModel):
    net_name: str
    target_ohms: float = Field(gt=0)
    reference_layer: str

class BoardSpec(BaseModel):
    schema_version: int = 1
    surface_finish: SurfaceFinish = SurfaceFinish.HASL
    copper_weight_outer_oz: float = 1.0
    copper_weight_inner_oz: float = 0.5
    soldermask_color: SoldermaskColor = SoldermaskColor.GREEN
    silkscreen_color: SilkscreenColor = SilkscreenColor.WHITE
    impedance_requirements: tuple[ImpedanceRequirement, ...] = ()
```

### 2b. Sidecar load/save pattern

**Excerpt** (`io/atomic_write.py:15-43`) — used by `PcbIR.commit_raw_content` and `serialize_pcb`:
```python
def atomic_write(file_path: Path, content: str) -> None:
    file_path = Path(file_path)
    fd, tmp_path = tempfile.mkstemp(dir=file_path.parent, prefix=".kicad_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(file_path))
    except BaseException:
        try: os.unlink(tmp_path)
        except OSError: pass
        raise
```

**Apply — load/save functions** (per RESEARCH RQ5):
```python
def load_board_spec(pcb_path: Path) -> BoardSpec | None:
    sidecar = pcb_path.with_suffix(".kicad_build_spec.json")
    if not sidecar.is_file():
        return None
    return BoardSpec.model_validate_json(sidecar.read_text(encoding="utf-8"))

def save_board_spec(pcb_path: Path, spec: BoardSpec) -> Path:
    sidecar = pcb_path.with_suffix(".kicad_build_spec.json")
    atomic_write(sidecar, spec.model_dump_json(indent=2))
    return sidecar
```
**Verified round-trip:** `model_dump_json(indent=2)` → `model_validate_json` reproduces BoardSpec exactly (RESEARCH RQ4). str-Enum serializes as the name (`"ENIG"`), tuple serializes as JSON array.

---

## 3. CREATE: `tests/test_board_spec.py`

**Role:** Model tests + sidecar persistence tests.
**Closest analog:** `tests/test_pcb_ops.py` (uses `tempfile` + `Path`, autouse fixture pattern at lines 26-32) for the test structure; `dfm/profiles.py` `from_json` round-trip is the model-test analog.

**Excerpt** (`tests/test_pcb_ops.py:26-32` — autouse clear + tempfile pattern):
```python
@pytest.fixture(autouse=True)
def _clear_ir_registry():
    from volta.ir.base import _clear_registry
    _clear_registry()
    yield
    _clear_registry()
```

**Apply** — BoardSpec tests:
```python
def test_default_construction():
    spec = BoardSpec()
    assert spec.surface_finish == SurfaceFinish.HASL
    assert spec.copper_weight_outer_oz == 1.0
    assert spec.impedance_requirements == ()

def test_json_round_trip():
    spec = BoardSpec(surface_finish=SurfaceFinish.ENIG, impedance_requirements=(
        ImpedanceRequirement(net_name="USB_DM", target_ohms=90.0, reference_layer="GND"),
    ))
    restored = BoardSpec.model_validate_json(spec.model_dump_json(indent=2))
    assert restored == spec

def test_sidecar_load_save(tmp_path):
    pcb = tmp_path / "board.kicad_pcb"
    pcb.write_text("(kicad_pcb)", encoding="utf-8")
    spec = BoardSpec(surface_finish=SurfaceFinish.ENIG)
    save_board_spec(pcb, spec)
    assert (tmp_path / "board.kicad_build_spec.json").is_file()
    assert load_board_spec(pcb) == spec

def test_sidecar_missing_returns_none(tmp_path):
    pcb = tmp_path / "board.kicad_pcb"
    pcb.write_text("(kicad_pcb)", encoding="utf-8")
    assert load_board_spec(pcb) is None
```

---

## 4. CREATE: `tests/test_board_metadata_ops.py`

**Role:** Operation tests for `read_board_metadata`, `set_board_metadata`, `set_board_revision` + round-trip.
**Closest analog:** `tests/test_pcb_ops.py` — `_create_minimal_pcb` helper (lines 35-68) and op test classes.

**Excerpt** (`tests/test_pcb_ops.py:35-68` — minimal PCB helper):
```python
def _create_minimal_pcb(tmpdir: Path, name: str = "test.kicad_pcb") -> tuple[Path, PcbIR]:
    from volta.ir.base import _clear_registry
    _clear_registry()
    pcb_path = tmpdir / name
    board = Board.create_new()
    board.general.thickness = 1.6
    board.nets.append(Net(number=1, name="GND"))
    # ... add outline ...
    board.to_file(str(pcb_path))
    result = parse_pcb(pcb_path)
    uuid_map = extract_uuids(result.raw_content, "pcb")
    ir = PcbIR(_parse_result=result, _uuid_map=uuid_map)
    return pcb_path, ir
```

**Apply** — For title_block tests, either (a) use the Arduino_Mega fixture (has date-only title_block) or (b) generate a custom fixture inline with a full title_block. Round-trip test pattern (per RESEARCH RQ3):
```python
def test_set_board_revision_round_trip(tmp_path):
    pcb_path, ir = _create_minimal_pcb_with_title_block(tmp_path)
    handler = _PCB_HANDLERS["set_board_revision"]
    result = handler(SetBoardRevisionOp(rev="2.1", target_file="test"), ir, pcb_path)
    assert result["rev"] == "2.1"
    # Re-read from disk
    re_read = _PCB_HANDLERS["read_board_metadata"](
        ReadBoardMetadataOp(target_file="test"), ir, pcb_path
    )
    assert re_read["rev"] == "2.1"
```

---

## 5. MODIFY: `src/volta/parser/pcb_native_types.py`

**Role:** Add `NativeTitleBlock` frozen dataclass + add field to `NativeBoard` + export.
**Closest analog:** `NativeGeneral` (lines 295-304) — flat frozen dataclass with simple typed fields and defaults.

**Excerpt** (`pcb_native_types.py:295-304`):
```python
@dataclass(frozen=True)
class NativeGeneral:
    """General board settings: (general ...).

    Council CRITICAL-2: needed by spatial/layer_stackup.py (board.general.thickness)
    and export/general.py (board.general.layers).
    """
    thickness: float = 1.6
    layers: tuple = ()
```

**Apply** — add `NativeTitleBlock` before the `NativeBoard` class (around line 343), following the flat-field pattern:
```python
@dataclass(frozen=True)
class NativeTitleBlock:
    """Title block metadata: (title_block ...).

    Fields map to KiCad title_block children. Comments are position-indexed
    by KiCad comment number: comment 1 -> index 0, comment 2 -> index 1, etc.
    Empty comments are empty strings. Tuple (not dict) for CR-01 immutability.
    """
    title: str = ""
    date: str = ""
    rev: str = ""
    company: str = ""
    comments: tuple[str, ...] = ()
```

**Field on NativeBoard** (line 376 area, after `setup`):
```python
    setup: NativeSetup | None = None
    title_block: NativeTitleBlock | None = None   # None = no element present
```

**Export** — add `"NativeTitleBlock"` to `__all__` (lines 394-410), alphabetically before `NativeVia` or after `NativeStackupLayer`.

---

## 6. MODIFY: `src/volta/parser/pcb_native_parser.py`

**Role:** Remove `title_block` from `_UNSUPPORTED_ELEMENTS`, add to `_KNOWN_TOP_LEVEL`, add `_extract_title_block`, wire into `_build_board`.
**Closest analog:** `_extract_setup` classmethod (lines 1234-1255) — uses `_find_symbol` to find a block, extracts children, returns typed dataclass or None.

### 6a. Remove from `_UNSUPPORTED_ELEMENTS`

**Excerpt** (`pcb_native_parser.py:53-63`):
```python
_UNSUPPORTED_ELEMENTS: frozenset[str] = frozenset({
    "thermal_relief_pads",
    "keepout_areas",
    "soldermask_expansion",
    "paste_expansion",
    "courtyard",
    "fp_text",
    "3d_model_refs",
    "page_info",
    "title_block",    # <-- REMOVE THIS LINE
})
```

### 6b. Add to `_KNOWN_TOP_LEVEL`

**Excerpt** (`pcb_native_parser.py:379-384`):
```python
_KNOWN_TOP_LEVEL = {
    "version", "generator", "general", "layers", "setup",
    "net", "net_class", "footprint", "segment", "via",
    "zone", "gr_line", "gr_arc", "gr_circle", "gr_rect",
    "gr_poly", "gr_curve", "kicad_pcb",
}
# ADD: "title_block" to this set
```

### 6c. Extractor pattern

**Excerpt** (`pcb_native_parser.py:1234-1255` — `_extract_setup`):
```python
@classmethod
def _extract_setup(cls, root: list) -> NativeSetup | None:
    setup_block = _find_symbol(root, "setup")
    if setup_block is None:
        return None
    stackup: NativeStackup | None = None
    stackup_block = _find_symbol(setup_block, "stackup")
    if stackup_block is not None:
        stackup = NativeStackup(
            layers=tuple(cls._extract_stackup_layers(stackup_block))
        )
    return NativeSetup(stackup=stackup)
```

**Apply** — `_extract_title_block` classmethod. Uses `_find_string_child` for title/date/rev/company (verified compatible in RESEARCH RQ1 table). Numbered comments need a dedicated loop (RESEARCH RQ1, no existing helper handles `(comment N "...")`):
```python
@classmethod
def _extract_title_block(cls, root: list) -> NativeTitleBlock | None:
    tb_block = _find_symbol(root, "title_block")
    if tb_block is None:
        return None
    title = _find_string_child(tb_block, "title")
    date = _find_string_child(tb_block, "date")
    rev = _find_string_child(tb_block, "rev")
    company = _find_string_child(tb_block, "company")
    # Numbered comments: (comment N "text") where N is 1-9, non-sequential
    comments_map: dict[int, str] = {}
    for item in tb_block:
        if isinstance(item, list) and len(item) >= 3 and _sym(item[0]) == "comment":
            try:
                num = int(item[1])
                text = item[2] if isinstance(item[2], str) else str(item[2])
                comments_map[num] = text
            except (ValueError, TypeError):
                continue
    # Convert to tuple (index 0 = comment 1)
    if comments_map:
        max_n = max(comments_map)
        comments = tuple(comments_map.get(i, "") for i in range(1, max_n + 1))
    else:
        comments = ()
    return NativeTitleBlock(title=title, date=date, rev=rev, company=company, comments=comments)
```

### 6d. Wire into `_build_board`

**Excerpt** (`pcb_native_parser.py:367-414` — extractor calls + constructor):
```python
# Extract all element types
nets = tuple(cls._extract_nets(root))
# ...
general = cls._extract_general(root)
setup = cls._extract_setup(root)
# ADD: title_block = cls._extract_title_block(root)
# ...
return NativeBoard(
    version=version,
    # ...
    general=general,
    setup=setup,
    title_block=title_block,   # ADD
)
```

---

## 7. MODIFY: `src/volta/ops/_schema_pcb.py`

**Role:** Add 3 Op classes: `ReadBoardMetadataOp` (read-only), `SetBoardMetadataOp` (mutating, partial update), `SetBoardRevisionOp` (mutating).
**Closest analog (read-only):** `ListNetClassesOp` (lines 283-294).
**Closest analog (mutating, partial update):** `ModifyNetClassOp` (lines 237-266) — Optional fields defaulting to None mean "keep existing".
**Closest analog (mutating, required field):** `SetBoardOutlineOp` (lines 98-111).

### 7a. ReadBoardMetadataOp

**Excerpt** (`_schema_pcb.py:283-294`):
```python
class ListNetClassesOp(BaseModel):
    """List all net classes in a .kicad_dru file.
    Read-only operation -- returns all net classes without modifying the file.
    """
    op_type: Literal["list_net_classes"] = "list_net_classes"
    target_file: TargetFile
```
**Apply:**
```python
class ReadBoardMetadataOp(BaseModel):
    """Read board metadata (title, date, rev, company, comments) from a PCB.
    Read-only operation -- returns title_block fields + board_spec sidecar if present.
    """
    op_type: Literal["read_board_metadata"] = "read_board_metadata"
    target_file: TargetFile
```

### 7b. SetBoardMetadataOp (partial update)

**Excerpt** (`_schema_pcb.py:237-266`):
```python
class ModifyNetClassOp(BaseModel):
    """Modify an existing net class in .kicad_dru.
    Only specified (non-None) fields are updated; None means keep existing value.
    """
    op_type: Literal["modify_net_class"] = "modify_net_class"
    target_file: TargetFile
    name: str = Field(min_length=1, max_length=64, description="Net class name to modify")
    clearance: Optional[float] = Field(default=None, gt=0, description="Clearance in mm")
    track_width: Optional[float] = Field(default=None, gt=0, description="Track width in mm")
    # ... more Optional fields ...
```
**Apply:**
```python
class SetBoardMetadataOp(BaseModel):
    """Set board metadata fields in a PCB title_block.
    Only specified (non-None) fields are updated; None means leave unchanged.
    """
    op_type: Literal["set_board_metadata"] = "set_board_metadata"
    target_file: TargetFile
    title: Optional[str] = Field(default=None, max_length=256)
    date: Optional[str] = Field(default=None, max_length=64)
    rev: Optional[str] = Field(default=None, max_length=64)
    company: Optional[str] = Field(default=None, max_length=256)
    comments: Optional[list[str]] = Field(default=None)
```

### 7c. SetBoardRevisionOp (required field)

**Excerpt** (`_schema_pcb.py:98-111`):
```python
class SetBoardOutlineOp(BaseModel):
    op_type: Literal["set_board_outline"] = "set_board_outline"
    target_file: TargetFile
    width: float = Field(gt=0, le=1000, description="Board width in mm")
    height: float = Field(gt=0, le=1000, description="Board height in mm")
```
**Apply:**
```python
class SetBoardRevisionOp(BaseModel):
    op_type: Literal["set_board_revision"] = "set_board_revision"
    target_file: TargetFile
    rev: str = Field(min_length=1, max_length=64, description="Board revision string")
```

---

## 8. MODIFY: `src/volta/ops/schema.py`

**Role:** Add 3 Op classes to the `Operation.root` discriminated union + import + `__all__`.
**Three touch points:**

### 8a. Import block (line 239-268 area)
**Excerpt** (`schema.py:239-248`):
```python
from volta.ops._schema_pcb import (  # noqa: E402
    AddNetClassOp,
    AddDesignRuleOp,
    AddCopperZoneOp,
    SetBoardOutlineOp,
    AssignNetClassOp,
    # ...
```
**Apply:** add `ReadBoardMetadataOp, SetBoardMetadataOp, SetBoardRevisionOp` to this import block.

### 8b. Union (line 402-557)
**Excerpt** (`schema.py:402-403, 448-449`):
```python
class Operation(BaseModel):
    root: Annotated[
        AddComponentOp
        | RemoveComponentOp
        # ...
        | SetBoardOutlineOp
        | AssignNetClassOp
        # ...
        | AutoLayoutSchOp,
        Field(discriminator="op_type"),
    ]
```
**Apply:** add `| ReadBoardMetadataOp | SetBoardMetadataOp | SetBoardRevisionOp` before the closing `AutoLayoutSchOp,`.

### 8c. `__all__` (line 629 area)
**Excerpt** (`schema.py:626-630`):
```python
    # PCB ops
    "AddNetClassOp",
    "AddDesignRuleOp",
    "AddCopperZoneOp",
    "SetBoardOutlineOp",
    "AssignNetClassOp",
```
**Apply:** add `"ReadBoardMetadataOp", "SetBoardMetadataOp", "SetBoardRevisionOp"`.

---

## 9. MODIFY: `src/volta/ops/registry.py`

**Role:** Add 3 `_RAW_CATALOG` entries.
**Closest analog:** `set_board_outline` entry (lines 372-380) for mutating; `list_net_classes` entry (lines 525-533) for read-only.

**Excerpt** (`registry.py:372-380` — mutating):
```python
"set_board_outline": {
    "category": "pcb",
    "description": "Define PCB board shape as a rectangle on Edge.Cuts",
    "file_types": [".kicad_pcb"],
    "is_readonly": False,
    "scope": "single_file",
    "requires": [],
    "conflicts": [],
},
```
**Excerpt** (`registry.py:525-533` — read-only):
```python
"list_net_classes": {
    "category": "pcb",
    "description": "List all net classes in a .kicad_dru file",
    "file_types": [".kicad_dru"],
    "is_readonly": True,
    "scope": "single_file",
    "requires": [],
    "conflicts": [],
},
```
**Apply** — add 3 entries to `_RAW_CATALOG`:
```python
"read_board_metadata": {
    "category": "query",
    "description": "Read board metadata (title, date, rev, company, comments) from PCB",
    "file_types": [".kicad_pcb"],
    "is_readonly": True,
    "scope": "single_file",
    "requires": [],
    "conflicts": [],
},
"set_board_metadata": {
    "category": "pcb",
    "description": "Set board metadata fields (title, date, rev, company, comments)",
    "file_types": [".kicad_pcb"],
    "is_readonly": False,
    "scope": "single_file",
    "requires": [],
    "conflicts": [],
},
"set_board_revision": {
    "category": "pcb",
    "description": "Set the board revision field in the title_block",
    "file_types": [".kicad_pcb"],
    "is_readonly": False,
    "scope": "single_file",
    "requires": [],
    "conflicts": [],
},
```
**Note:** `read_board_metadata` uses `category: "query"` (matches CONTEXT.md META-01 and the query dispatch path in `execute_query`).

---

## 10. MODIFY: `src/volta/ops/handlers/query.py`

**Role:** Add `read_board_metadata` handler via `@register_query`.
**Closest analog:** the existing `query_connectivity` handler (lines 25-28).

**Excerpt** (`handlers/query.py:14-28`):
```python
_QUERY_HANDLERS: dict[str, Callable] = {}

def register_query(op_type: str) -> Callable:
    def decorator(fn: Callable) -> Callable:
        _QUERY_HANDLERS[op_type] = fn
        return fn
    return decorator

@register_query("query_connectivity")
def _handle_query_connectivity(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    from volta.ops.connectivity_query import handle_connectivity_query
    return handle_connectivity_query(op, ir, file_path)
```
**Apply:**
```python
@register_query("read_board_metadata")
def _handle_read_board_metadata(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    """Read title_block fields + board_spec sidecar.
    CRITICAL: execute_query uses kiutils path, NOT native parser.
    Parse title_block from ir.raw_content using native parser helpers directly.
    """
    from volta.parser.pcb_native_parser import NativeParser, _find_symbol, _find_string_child, _sym
    import sexpdata
    tree = sexpdata.loads(ir.raw_content)
    tb = _find_symbol(tree, "title_block")
    # ... extract fields, build result dict ...
    # Also load board_spec sidecar if present:
    from volta.manufacturing.board_spec import load_board_spec
    spec = load_board_spec(file_path)
    result = {"title": ..., "date": ..., "rev": ..., "company": ..., "comments": [...],
              "board_spec": spec.model_dump() if spec else None}
    return result
```
**CRITICAL per RESEARCH RQ1:** The `execute_query` path (execution.py:193-230) builds PcbIR via kiutils (NOT native parser), so `ir.board` is a kiutils Board — `ir.board.title_block` will NOT exist. The handler must parse title_block from `ir.raw_content` using `sexpdata.loads` + the native parser's `_find_symbol`/`_find_string_child` helpers directly.

---

## 11. MODIFY: `src/volta/ops/handlers/pcb.py`

**Role:** Add `set_board_metadata` and `set_board_revision` handlers via `@register_pcb`.
**Closest analog:** `move_footprint` handler (lines 225-245) — the raw-writer + `commit_raw_content` mutation pattern.

**Excerpt** (`handlers/pcb.py:225-245`):
```python
@register_pcb("move_footprint")
def _handle_move_footprint(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    """Move a footprint via PcbRawWriter (Council C-01: returns content, executor writes)."""
    from volta.ops.pcb_raw_writer import PcbRawWriter
    raw = ir.raw_content
    new_content = PcbRawWriter.modify_footprint_position(raw, op.reference, op.x, op.y, op.angle)
    if new_content == raw:
        raise ValueError(f"Footprint '{op.reference}' not found in PCB")
    ir.commit_raw_content(new_content)
    return {"reference": op.reference, "x": op.x, "y": op.y, "angle": op.angle}
```
**Apply:**
```python
@register_pcb("set_board_metadata")
def _handle_set_board_metadata(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    from volta.ops.pcb_raw_writer import PcbRawWriter
    raw = ir.raw_content
    new_content = PcbRawWriter.set_title_block_fields(
        raw, title=op.title, date=op.date, rev=op.rev, company=op.company, comments=op.comments
    )
    ir.commit_raw_content(new_content)
    return {"title": op.title, "date": op.date, "rev": op.rev, "company": op.company, "comments": op.comments}

@register_pcb("set_board_revision")
def _handle_set_board_revision(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    from volta.ops.pcb_raw_writer import PcbRawWriter
    new_content = PcbRawWriter.set_title_block_fields(ir.raw_content, rev=op.rev)
    ir.commit_raw_content(new_content)
    return {"rev": op.rev}
```
**Note:** Handlers must be added inside `handlers/pcb.py` (the mutating path uses `@register_pcb`). Both delegate to the new `PcbRawWriter` method (see file #12).

---

## 12. MODIFY: `src/volta/ops/pcb_raw_writer.py`

**Role:** Add title_block modification methods to `PcbRawWriter`.
**Closest analog (block find + replace):** `find_zone_block` (lines 167-194) + `modify_zone_field` (lines 221-279).
**Closest analog (insert-if-absent):** `assign_net_class` (lines 366-416).
**Reusable helper:** `_find_matching_close` (lines 938-975) — handles nested parens + quoted strings with KiCad's doubled-quote escaping.

### 12a. find_zone_block (block-locate pattern)

**Excerpt** (`pcb_raw_writer.py:167-194`):
```python
@staticmethod
def find_zone_block(content: str, zone_uuid: str) -> tuple[Optional[int], Optional[int]]:
    uuid_pat = re.compile(r'\(uuid\s+"' + re.escape(zone_uuid) + r'"')
    for match in re.finditer(r"^\s*\(zone\b", content, re.MULTILINE):
        start = match.start()
        end = PcbRawWriter._find_matching_close(content, start + 1)
        if end is None:
            continue
        block = content[start : end + 1]
        if uuid_pat.search(block):
            return start, end + 1
    return None, None
```

### 12b. assign_net_class (find-or-insert pattern)

**Excerpt** (`pcb_raw_writer.py:366-416`):
```python
@staticmethod
def assign_net_class(content: str, net_name: str, net_class_name: str) -> str:
    # Remove this net from any existing net_class blocks
    add_net_pattern = re.compile(r'\(add_net "' + re.escape(net_name) + r'"\)\s*\n?')
    content = add_net_pattern.sub("", content)
    # Find or create the target net_class block
    class_pattern = re.compile(r'\(net_class "' + re.escape(net_class_name) + r'"')
    match = class_pattern.search(content)
    if match:
        start = match.start()
        end = PcbRawWriter._find_matching_close(content, start)
        # ... insert into existing block ...
    else:
        # Create new net_class block before the first (net ... ) line
        new_class = (...)
        first_net = re.search(r'\n  \(net \d+ ', content)
        # ... insert ...
    return content
```

### 12c. _find_matching_close (helper)

**Excerpt** (`pcb_raw_writer.py:938-975`):
```python
@staticmethod
def _find_matching_close(content: str, open_pos: int) -> Optional[int]:
    """Find the matching closing paren. Handles nested parens and quoted strings
    using KiCad's doubled-quote escaping convention ("" inside string = literal ")."""
    depth = 0
    i = open_pos
    in_string = False
    while i < len(content):
        c = content[i]
        if in_string:
            if c == '"':
                if i + 1 < len(content) and content[i + 1] == '"':
                    i += 2
                    continue
                in_string = False
            i += 1
            continue
        if c == '"':
            in_string = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None
```

**Apply** — new method(s) for title_block. Two viable designs:
- **Field-level:** `set_title_field(content, field_name, value)` — find existing `(field "...")` inside title_block, replace it; or add it if absent. Regex per field: `r'\(title\s+"[^"]*"\)'` → `(title "new value")`.
- **Block-level:** `replace_title_block(content, new_tb_sexp)` — find existing `(title_block ...)` via `_find_matching_close`, replace entire block; or insert new block after `(paper ...)` if absent.

**Recommended: block-level replacement** — simplest, avoids partial-update edge cases (non-sequential comments). Build the new `(title_block ...)` S-expression string from desired field values, find the existing block via `re.search(r"^\s*\(title_block\b", content, re.MULTILINE)` + `_find_matching_close`, replace it. If absent, insert after the `(paper ...)` line (title_block comes after paper, before layers — per fixture line 9-12 of Arduino_Mega).

**Signature:**
```python
@staticmethod
def set_title_block_fields(
    content: str,
    title: Optional[str] = None,
    date: Optional[str] = None,
    rev: Optional[str] = None,
    company: Optional[str] = None,
    comments: Optional[list[str]] = None,
) -> str:
    """Set title_block fields. None fields are left unchanged.
    Reads existing values first (to support partial update), rebuilds the block.
    """
```

---

## 13. MODIFY: `tests/test_pcb_native_parser.py`

**Role:** Add title_block parsing tests.
**Closest analog:** existing setup/general tests (lines 362-378) using the `arduino_board` module fixture (lines 38-47).

**Excerpt** (`test_pcb_native_parser.py:38-47` — fixture pattern):
```python
@pytest.fixture(scope="module")
def arduino_board() -> NativeBoard:
    return NativeParser.parse_pcb(ARDUINO_MEGA)
```
**Excerpt** (`test_pcb_native_parser.py:371-378` — setup test pattern):
```python
def test_native_board_setup_exists(self, arduino_board):
    assert hasattr(arduino_board, "setup")
    assert arduino_board.setup is not None

def test_native_board_setup_stackup(self, arduino_board):
    assert arduino_board.setup is not None
    assert arduino_board.setup.stackup is not None
    assert isinstance(arduino_board.setup.stackup, NativeStackup)
```
**Apply:**
```python
def test_native_board_title_block_exists(self, arduino_board):
    assert arduino_board.title_block is not None
    assert isinstance(arduino_board.title_block, NativeTitleBlock)

def test_native_board_title_block_date(self, arduino_board):
    # Arduino fixture has date-only title_block
    assert arduino_board.title_block.date == "mar. 31 mars 2015"
    assert arduino_board.title_block.title == ""
    assert arduino_board.title_block.rev == ""

def test_native_board_title_block_absent(self):
    # Use a board with no title_block (smd_test_board or phase99_synthetic)
    board = NativeParser.parse_pcb(SMD_TEST_BOARD)
    assert board.title_block is None

def test_title_block_full_fields(self):
    # Inline custom fixture with all fields + non-sequential comments
    content = '''(kicad_pcb (version 20241229) (generator "test")
      (paper "A4")
      (title_block
        (title "Test Board (prototype)")
        (date "2026-07-10")
        (rev "2.1")
        (company "Smith & Co.")
        (comment 1 "First")
        (comment 3 "Third")
        (comment 9 "Ninth")
      )
      (layers (0 "F.Cu" signal))
    )'''
    board = NativeParser.parse_pcb_content(content)
    tb = board.title_block
    assert tb.title == "Test Board (prototype)"
    assert tb.company == "Smith & Co."
    assert tb.comments[0] == "First"   # comment 1 -> index 0
    assert tb.comments[1] == ""        # comment 2 absent -> empty
    assert tb.comments[2] == "Third"   # comment 3 -> index 2
```

---

## 14. MODIFY: `tests/test_registry.py`

**Role:** Update count assertion.
**Current line 26:**
```python
def test_registry_has_98_operations(self) -> None:
    # Phase 101-06: 141 ops ...
    assert len(OPERATION_REGISTRY) == 142
```
**Apply:** change `== 142` to `== 154` (151 current + 3 new ops). Also rename the test method (currently `test_registry_has_98_operations` is misleading) or update the comment.

**Verified:** `validate_registry_completeness()` will fail if the 3 new ops are added to registry but NOT to schema union (or vice versa) — both must be added together (see files #8 and #9).

---

## Cross-Cutting Notes

### Mutation Path (RESEARCH RQ2 — CRITICAL)
The PCB serializer (`serialize_pcb` in `pcb_ser.py:64-66`) uses `kiutils_obj.to_file()` — it does NOT emit NativeBoard fields. Therefore:
- **Do NOT use native-path mutation** (`replace(self._native_board, title_block=new_tb)` + `_record_mutation`). It would update the in-memory NativeBoard but the serializer would not write it.
- **USE raw-writer path**: `PcbRawWriter.set_title_block_fields(...)` → `ir.commit_raw_content(new_content)`. When `raw_written` is True, the executor skips `serialize_pcb` (execution.py:533-534), so the raw content (with the modified title_block) is what lands on disk.

### Query Path (RESEARCH RQ1 — CRITICAL)
`execute_query` (execution.py:193-230) builds PcbIR via kiutils (`parse_pcb`), NOT the native parser. So `ir.board` is a kiutils Board, and `ir.board.title_block` does not exist. The `read_board_metadata` handler must parse title_block from `ir.raw_content` using `sexpdata.loads` + native parser helpers.

### Mutating Path (execution.py:470+)
`execute_pcb` DOES use the native parser via `try_native_parse` (line 496). So mutating handlers have `ir.board` as a NativeBoard. However, since mutation goes through the raw-writer path, this doesn't matter — the handler reads `ir.raw_content` and calls `commit_raw_content`.

### Registry Count Math
| State | Registry entries | Schema variants |
|-------|-----------------|-----------------|
| Current (verified) | 151 | 154 |
| After Phase 205 (+3 ops) | **154** | **157** |
| Pre-existing missing-from-registry | 3 (`add_design_note`, `apply_floor_plan`, `place_and_wire_power_units`) | — |

The test assertion at `tests/test_registry.py:26` is currently `== 142` (stale, test was failing or not run). Update to `== 154`.

### Handler Dispatch Wiring
- `read_board_metadata`: `@register_query` in `handlers/query.py` → dispatched by `dispatch_query` (execution.py:233-256) via `_QUERY_HANDLERS`. No Transaction, no serialization.
- `set_board_metadata` / `set_board_revision`: `@register_pcb` in `handlers/pcb.py` → dispatched by `dispatch_pcb` via `_PCB_HANDLERS` (merged into at handlers/__init__.py). Transaction-wrapped, undo-tracked.
- `handlers/__init__.py` already merges `_QUERY_HANDLERS` and `_PCB_HANDLERS` — no new merge logic needed (CONTEXT IP-3).
