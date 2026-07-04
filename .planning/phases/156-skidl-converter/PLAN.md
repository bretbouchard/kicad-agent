# Phase 156 — SKIDL Converter

**Goal:** Build the bidirectional KiCad↔SKIDL bridge. The foundational new capability is the KiCad→SKIDL read-back path (the one direction that does not exist) by composing `SchematicIR` + `extract_nets`. Then make the proven SKIDL→KiCad path (analog-ecosystem `gen_schematic.py`) a first-class kicad-agent op. SKIDL becomes the canonical IR for all downstream circuit operations (floor planning, SPICE, training data) — a Code-L1 representation (pin-name-based wiring) that SchGen proved achieves 82% valid circuit generation vs 32% for raw KiCad files.

**Depends on:** Phases 108–111 (autolayout + conventions provide the schematic generation foundation). The `SchematicIR` + `extract_nets` infrastructure from Phases 38–39 provides the connectivity extraction.
**Requirements:** CONV-01, CONV-02, CONV-03, CONV-04, CONV-05, CONV-06, CONV-07, CONV-08, CONV-09, CONV-10
**Research basis:** `.planning/research/STACK-SKIDL.md` (SchGen L1/L2/L3 ablation, 8 pitfalls, architecture integration points)
**Integration target:** `src/kicad_agent/circuit_ir/` (new package, modeled on `ltspice/`), wired into `ops/handlers/schematic_query.py` + `ops/registry.py` + `ops/schema.py`

---

## Design Principles

1. **Compose, don't rebuild.** kicad-agent already has the connectivity extraction (`extract_nets` via union-find over wire segments + net-name resolution with label > pin_index > auto priority), the schematic IR (`SchematicIR` with `_match_lib_symbol` fallback for the `libraryNickname=None` bug), and the LTspice module as the architectural template. The KiCad→SKIDL read-back is a *composition* of these existing pieces — the only genuinely new logic is the SKIDL `Circuit`/`Part`/`Net` builder and the `build_*.py` emitter.

2. **SKIDL *is* the Code-L1 representation.** SchGen proved pin-name-based wiring (`part["VCC"] += net`) is the key enabler. SKIDL's `+=` operator *is* `connect_pins`. The L1/L2 distinction in this phase is an **emission mode** over the same parsed Circuit, not two separate pipelines — L1 emits exact per-pin wiring (the round-trip-faithful target), L2 emits a compact component-level summary (the training-data-friendly form).

3. **Fail closed, degrade gracefully.** On unresolvable symbols (multi-unit that breaks extraction), the converter falls back to generic connector modeling (the proven analog-ecosystem pattern: USBLC6/USBC modeled as `Conn_01xNN`) and records the fallback in a `diagnostics` list — never silently produces an incomplete circuit. On `KICAD_SYMBOL_DIR` unset, the import guard raises a clear error before any `Part()` call.

4. **Each wave is independently shippable.** Wave 1 (read-back) delivers the foundational capability alone. Wave 2 (L1/L2 emission) makes it useful. Wave 3–5 handle the hard cases. Wave 6 is the round-trip + bidirectional proof.

### Critical constraints from research (STACK-SKIDL)

- **Pitfall #6 — `KICAD_SYMBOL_DIR` race:** skidl resolves symbols against the KiCad library at `import skidl` time. The env var MUST be set before the import. Confirmed in the live environment: `import skidl` emits `KICAD8_SYMBOL_DIR is missing` warnings and parts get no pins. The `circuit_ir/__init__.py` enforces this ordering with an import guard (porting the `parts.py` lines 22–25 pattern).
- **Pitfall #1 — multi-unit symbols:** `gen_schematic.py`'s `resolve_lib_symbol()` + `_resolve_extends()` + the `_0_0 → _1_1` unit rename convention must be ported. Symbols that still break fall back to generic connector modeling.
- **Pitfall #2 — power symbols:** `symbol_mapper.py`'s `_POWER_MAPPINGS` already maps `power:GND → "0"`, `power:+5V → "+5V"`. The converter reuses this (power symbols → `Net` assignments, never BOM components).
- **Pitfall #5 — PCB population parser:** The 5 `populate_pcb_from_netlist` workarounds from `gen_pcb.py` (`_inject_net_table`, `_rewrite_pad_nets_to_numeric`, `_assign_ground_to_unconnected_pads`, XML pre-parse with `pad` key, name-only→numeric) are ported **to the source** (`crossfile/pcb_populate.py`) in Wave 6 so all callers benefit.

---

## New Package: `src/kicad_agent/circuit_ir/`

Modeled on the `ltspice/` package structure (parse → IR → graph → export), as prescribed by STACK-SKIDL §ARCHITECTURE:

```
src/kicad_agent/circuit_ir/
├── __init__.py          # public API exports + KICAD_SYMBOL_DIR import guard (pitfall #6)
├── types.py             # frozen dataclasses: CircuitIR, PartDescriptor, NetDescriptor, PinRef
├── skidl_circuit.py     # build_circuit(ir, nets) -> skidl.Circuit  (KiCad→SKIDL read-back)
├── skidl_emitter.py     # emit_build_py(circuit, mode="L1"|"L2", out_path)  (build_*.py generation)
├── parts_registry.py    # Part wrappers + LCSC/footprint metadata (port of mono-arch parts.py)
├── symbol_resolver.py   # resolve_lib_symbol + _resolve_extends (port of gen_schematic.py)
├── hierarchy_flattener.py  # recursive sub-sheet flatten → flat Circuit (uses navigate_hierarchy)
├── skidl_to_kicad.py    # SKIDL Circuit → .kicad_sch (port of gen_schematic.py)
└── skidl_to_pcb.py      # SKIDL Circuit → .kicad_pcb (thin: generate_netlist → populate + fixes)
```

**Why a top-level `circuit_ir/` subpackage (not `skidl/skidl_circuit.py`)?** The STACK-SKIDL research prescribes this location and mirrors the `ltspice/` precedent. SKIDL is the IR for the entire v5.0 milestone (Phases 156–160) — floor planning, SPICE, and training data all consume `CircuitIR`. A cohesive subpackage with 8 concerns avoids a monolithic file and keeps the bidirectional bridge, the SPICE export hook (Phase 158), and the parts registry in one place.

### Module responsibilities

| Module | Role | Ported from | New logic |
|---|---|---|---|
| `__init__.py` | Import guard (env var before `import skidl`) + public exports | `parts.py:22-25` | The `_ensure_skidl_env()` guard |
| `types.py` | Frozen dataclasses: `CircuitIR`, `PartDescriptor`, `NetDescriptor`, `PinRef` | `ltspice/types.py` (precedent) | SKIDL-specific fields |
| `skidl_circuit.py` | `build_circuit(schematic_ir, nets) -> skidl.Circuit` | (new composition) | The read-back core |
| `skidl_emitter.py` | `emit_build_py(circuit, mode, out_path)` — emits `build_*.py` | analog-ecosystem build scripts | L1 vs L2 emission modes |
| `parts_registry.py` | `LCSC` dict + `FP` dict + `_alias()` + wrapper registry | `mono-arch/parts.py` | Bundled, importable by emitted scripts |
| `symbol_resolver.py` | `resolve_lib_symbol()`, `_resolve_extends()`, `get_pin_numbers_from_lib()` | `gen_schematic.py:60-180` | The multi-unit + extends fixes |
| `hierarchy_flattener.py` | `flatten_hierarchy(root_sch) -> FlatComponents + FlatNets` | `navigate_hierarchy` handler | Recursive traversal + sheet-pin↔label merge |
| `skidl_to_kicad.py` | `circuit_to_kicad_sch(circuit, out_path)` | `gen_schematic.py` (full port) | Raw S-expr emitter (not kiutils — pitfall #7) |
| `skidl_to_pcb.py` | `circuit_to_pcb(circuit, out_path)` | `gen_pcb.py` (netlist → populate) | Calls fixed `populate_pcb_from_netlist` |

### Reused primitives (no duplication)

| SKIDL concept | Existing primitive | Location |
|---|---|---|
| Net topology extraction | `extract_nets()` | `schematic_routing/net_extractor.py` |
| Net name resolution priority | `extract_nets` (label > pin_index > auto) | `net_extractor.py` |
| Short detection | `NetPositionIndex.detect_shorts()` | `net_extractor.py` |
| Symbol→lib match | `SchematicIR._match_lib_symbol` | `ir/schematic_ir.py:31` |
| Hierarchical traversal | `navigate_hierarchy` handler | `ops/sheet_ops.py` |
| Power symbol mapping | `SymbolMapper._POWER_MAPPINGS` | `ltspice/symbol_mapper.py:38` |
| Schematic graph | `SchematicGraph` | `schematic_routing/schematic_graph.py` |
| PCB populate | `populate_pcb_from_netlist` | `crossfile/pcb_populate.py` |
| Raw S-expr write | `SchematicRawWriter` | `ops/schematic_raw_writer.py` |
| Self-serializing ops set | `SELF_SERIALIZING_OPS` | `ops/execution.py:120` |

---

## Operation Schema Definition

Two new ops registered alongside the schematic-query handlers. `convert_to_skidl` is **read-only** (generates files outside the project tree, no IR mutation); `convert_from_skidl` mutates the schematic and is self-serializing (like `auto_layout_sch`).

### `ConvertToSkidlOp` (`ops/_schema_circuit.py`)

```python
class ConvertToSkidlOp(BaseModel):
    """CONV-01..07: Read a .kicad_sch and generate a SKIDL build_*.py program.

    Reads components + nets via extract_nets, builds a skidl.Circuit with
    pin-name-based wiring (Code-L1), emits build_<stem>.py. Handles multi-unit
    symbols, power symbols (as Net assignments), and hierarchical sheets.

    Attributes:
        op_type: Discriminator literal "convert_to_skidl".
        target_file: Relative path to the source .kicad_sch file.
        representation: "L1" (pin-level, exact) or "L2" (component-level, training).
            "both" emits two files. SchGen ablation: L1 achieves 82% valid circuits.
        output_dir: Directory to write build_*.py (default: alongside source).
        flatten_hierarchy: If True (default), recursively flatten sub-sheets into one Circuit.
        symbol_dir: Optional override for KICAD_SYMBOL_DIR (default: system KiCad app).
        run_erc: If True, run skidl ERC on the built circuit and return violations.
    """

    op_type: Literal["convert_to_skidl"] = "convert_to_skidl"
    target_file: TargetFile
    representation: Literal["L1", "L2", "both"] = Field(
        default="L1",
        description="L1=pin-level exact, L2=component-level training data, both=two files",
    )
    output_dir: Optional[str] = Field(default=None, max_length=512)
    flatten_hierarchy: bool = Field(default=True, description="Recursively flatten sub-sheets")
    symbol_dir: Optional[str] = Field(default=None, max_length=512)
    run_erc: bool = Field(default=True, description="Run skidl ERC on built circuit")
```

### `ConvertFromSkidlOp` (`ops/_schema_circuit.py`)

```python
class ConvertFromSkidlOp(BaseModel):
    """CONV-08: Build a .kicad_sch from a SKIDL build_*.py (or .net) program.

    Runs the SKIDL→KiCad path proven in analog-ecosystem gen_schematic.py:
    Circuit.generate_netlist() → .net → resolve lib_symbols → place on grid →
    emit raw S-expr (not kiutils — pitfall #7: kiutils drops fields).

    Attributes:
        op_type: Discriminator literal "convert_from_skidl".
        target_file: Relative path to the OUTPUT .kicad_sch file (created/overwritten).
        source: Path to SKIDL program (build_*.py) or netlist (.net).
        source_type: "skidl" (run Python) or "netlist" (parse .net directly).
        place_components: If True (default), place on grid (gen_schematic placement).
        wire: If True, attempt net-name-based wiring (default False — isolated components).
    """

    op_type: Literal["convert_from_skidl"] = "convert_from_skidl"
    target_file: TargetFile
    source: str = Field(min_length=1, max_length=512)
    source_type: Literal["skidl", "netlist"] = "skidl"
    place_components: bool = True
    wire: bool = False
```

### Registration points

1. **Schema union** — add `ConvertToSkidlOp | ConvertFromSkidlOp` to the `Operation` discriminated union in `ops/schema.py` (line ~395 root `Annotated[...]`).
2. **Handler dispatch** — register `convert_to_skidl` in `_SCHEMATIC_QUERY_HANDLERS` (read-only, routes through `execute_schematic_query`); register `convert_from_skidl` in `_SCHEMATIC_HANDLERS` (mutating, self-serializing — add to `SELF_SERIALIZING_OPS`).
3. **Registry metadata** — add both to `_RAW_CATALOG` in `ops/registry.py`.
4. **New schema sub-module** — `ops/_schema_circuit.py` (matches the `_schema_<category>.py` convention).

---

## Wave-Based Task Breakdown

Each wave is independently shippable. Waves 2–5 depend only on the *interface* of Wave 1 (`CircuitIR` dataclasses frozen), so they can be parallelized. Wave 6 (round-trip) depends on all prior waves.

### Wave 1 — Foundation: CircuitIR types + KiCad→SKIDL read-back (CONV-01, CONV-04)
**Goal:** Build the one direction that does not exist: `.kicad_sch` → `skidl.Circuit`. Compose `SchematicIR` + `extract_nets` into `Part`/`Net` objects with pin-name-based wiring. No `build_*.py` emission yet (Wave 2), no hierarchy (Wave 4) — single-sheet, single-unit parts only.

**Files:**
- `src/kicad_agent/circuit_ir/__init__.py` (new) — import guard + exports
- `src/kicad_agent/circuit_ir/types.py` (new) — `CircuitIR`, `PartDescriptor`, `NetDescriptor`, `PinRef` frozen dataclasses
- `src/kicad_agent/circuit_ir/skidl_circuit.py` (new) — `build_circuit()` core
- `src/kicad_agent/circuit_ir/symbol_resolver.py` (new) — port of `gen_schematic.py` lib_symbol resolution
- `src/kicad_agent/circuit_ir/parts_registry.py` (new) — port of `mono-arch/parts.py` LCSC/FP/alias
- `tests/circuit_ir/__init__.py` (new)
- `tests/circuit_ir/test_skidl_circuit.py` (new)
- `tests/circuit_ir/test_symbol_resolver.py` (new)
- `tests/circuit_ir/conftest.py` (new) — `KICAD_SYMBOL_DIR` fixture, tiny schematic fixtures

**Tasks:**
- [ ] **W1-1** (`__init__.py`): Implement `_ensure_skidl_env(symbol_dir=None)`. Sets `KICAD_SYMBOL_DIR` (and `KICAD6..9_SYMBOL_DIR` variants) to the system KiCad app path (`/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols`) if unset, **then** imports skidl. This is the pitfall #6 guard. Raise `RuntimeError("KICAD_SYMBOL_DIR not set and KiCad not found at standard path")` if neither env nor default exists. Confirm: importing `circuit_ir` must not emit the `KICAD8_SYMBOL_DIR is missing` warning seen in the live environment.
- [ ] **W1-2** (`types.py`): Define frozen dataclasses:
  - `PinRef(reference: str, pin_number: str, pin_name: str, unit: int | None)`
  - `PartDescriptor(lib_id: str, reference: str, value: str, footprint: str | None, unit: int, is_power: bool, pins: list[PinRef], sheet: str | None)`
  - `NetDescriptor(name: str, pins: list[PinRef], is_power: bool)`
  - `CircuitIR(parts: tuple[PartDescriptor,...], nets: tuple[NetDescriptor,...], diagnostics: tuple[str,...], source_file: str)` — immutable, hashable.
- [ ] **W1-3** (`symbol_resolver.py`): Port `gen_schematic.py`'s `resolve_lib_symbol(filename, part)` + `_resolve_extends()` + `get_pin_numbers_from_lib()`. Handles: (a) `extends` inheritance (child inherits parent pins/units), (b) `_0_0 → _1_1` unit rename for common pins, (c) multi-unit symbol enumeration. Caches loaded lib files (`_lib_cache`, `_symbol_cache`). This addresses pitfalls #1 and #4.
- [ ] **W1-4** (`parts_registry.py`): Port the `LCSC` dict, `FP` footprint constants, and `_alias(part, pin_num, *aliases)` helper from `mono-arch/parts.py`. Add `is_known_part(lib_id) -> bool` and `resolve_wrapper(lib_id) -> PartDescriptor | None` for CONV-04 (map to existing wrappers for known parts). Unknown parts → `None` (Wave 3 generates wrappers).
- [ ] **W1-5** (`skidl_circuit.py`): Implement `build_circuit(schematic_ir: SchematicIR, nets: dict, *, symbol_dir: str | None = None) -> tuple[skidl.Circuit, CircuitIR]`. Pipeline:
  1. `_ensure_skidl_env(symbol_dir)` — set env, import skidl.
  2. For each component in `schematic_ir.components`: resolve lib_symbol via `symbol_resolver` → build `PartDescriptor` (lib_id, ref, value, footprint, pins). Mark `is_power` if lib_id starts with `power:`. Check `parts_registry.resolve_wrapper()` first (CONV-04 known-part fast path).
  3. For each net in `extract_nets` output: build `NetDescriptor` (name, pins). Coalesce power-symbol pins into their rail net (pitfall #2 — reuse `SymbolMapper._POWER_MAPPINGS`).
  4. Create `skidl.Circuit("name")`. Instantiate `skidl.Part(lib, name, footprint=..., value=...)` per `PartDescriptor`. For power symbols: `Part("power", "+3V3")` marked virtual (non-BOM).
  5. For each `NetDescriptor`: create `skidl.Net(name)`, then `part[pin_name] += net` for each `PinRef` (the Code-L1 pin-name-based wiring). Handle NC pins via `pin += NC`.
  6. Return `(circuit, circuit_ir)` where `circuit_ir` carries `diagnostics` (fallbacks, missing pins).
- [ ] **W1-6**: Test `build_circuit` on a tiny 3-component fixture (R-C-LED + GND) — assert `circuit.parts` has 3 non-power parts + 1 power net, `circuit.get_nets()` connects R1.2 to C1.1 to LED1.A. Assert ERC passes (0 errors).
- [ ] **W1-7**: Test `symbol_resolver` on `Device:R` (single unit), `Device:Opamp` (single unit, named pins), and a synthetic multi-unit fixture — assert correct pin counts and `_0_0` common-pin handling.
- [ ] **W1-8**: Test import guard — assert `import kicad_agent.circuit_ir` does not emit the `KICAD*_SYMBOL_DIR is missing` warning (the live-environment failure mode).

**Acceptance:** `build_circuit` turns any single-sheet `.kicad_sch` into a `skidl.Circuit` with correct parts + pin-name-based nets. ERC passes on simple circuits. Diagnostics list is empty on clean schematics. The import guard eliminates the env-var warning.

---

### Wave 2 — L1/L2 Emission: build_*.py generation (CONV-02, CONV-03)
**Goal:** Emit executable `build_<stem>.py` SKIDL programs from a `Circuit`. Two representation modes per the SchGen ablation: **L1** (pin-level, exact — the round-trip-faithful target) and **L2** (component-level, training-data-friendly). Both consume the same `CircuitIR`/`skidl.Circuit` — they differ only in emission format.

**Files:**
- `src/kicad_agent/circuit_ir/skidl_emitter.py` (new)
- `tests/circuit_ir/test_skidl_emitter.py` (new)
- `tests/fixtures/circuit_ir/expected_L1_sample.py` (new) — golden expected output
- `tests/fixtures/circuit_ir/expected_L2_sample.py` (new) — golden expected output

**Tasks:**
- [ ] **W2-1** (`skidl_emitter.py`): `emit_build_py(circuit, circuit_ir, mode: Literal["L1","L2"], out_path: Path) -> Path`. Emits a standalone Python file with: (a) the `_ensure_skidl_env` import guard header, (b) `from skidl import Part, Net, NC`, (c) part instantiation, (d) net wiring, (e) optional `circuit.ERC()`.
- [ ] **W2-2** — **L1 emission** (CONV-02, pin-level exact): One `+=` statement per pin connection. This is the *exact reproduction* mode — every pin-to-net assignment is explicit, matching the source schematic's connectivity 1:1.
  ```python
  # L1: pin-level, exact (Code-L1 representation)
  R1 = Part("Device", "R", footprint="Resistor_SMD:R_0603_1608Metric", value="10k", dest=TEMPLATE)
  R1.value = "10k"  # set per-instance
  ...
  net_VCC = Net("VCC")
  R1["1"] += net_VCC          # pin 1 → VCC
  U1["VCC"] += net_VCC        # named pin → VCC (pin-name-based wiring)
  U1["IN+"] += net_INPUT
  ```
- [ ] **W2-3** — **L2 emission** (CONV-03, component-level training): Compact, grouped by component with a comment-style net summary. Fewer statements, human-readable, optimized for LLM training-token efficiency (this is the form SchGen fine-tunes on). Each component block lists its net connections as a dict.
  ```python
  # L2: component-level (training-data-friendly)
  R1 = Part("Device", "R", value="10k", footprint="R_0603")
  # nets: {"1": "VCC", "2": "NET_U1_IN+"}
  U1 = Part("Analog", "NE5532", footprint="SOIC-8")
  # nets: {"VCC": "VCC", "IN+": "NET_U1_IN+", "OUT": "NET_OUT"}
  ```
- [ ] **W2-4**: Handle power nets in both modes — L1 emits `net_GND = Net("GND")` + connections; L2 collapses power into the component net summary. Power symbols themselves are *not* emitted as parts (they're Net declarations only — pitfall #2 BOM-correctness).
- [ ] **W2-5**: `representation="both"` emits two files (`build_<stem>_L1.py` + `build_<stem>_L2.py`) and returns the first.
- [ ] **W2-6**: Test — emit L1 from the W1 R-C-LED circuit, **execute the emitted file** via `subprocess`, assert the resulting `skidl.Circuit` has identical parts + nets to the original (`_circuits_equivalent(c1, c2)` helper comparing part-count, net-count, and pin-membership sets). This is the L1 round-trip-equivalence proof.
- [ ] **W2-7**: Test — emit L2, assert it parses, has the same part-count, and the net summary dicts are correct. (L2 is not round-trip-exact by design — it's the training form.)
- [ ] **W2-8**: Test — golden-file comparison against `expected_L1_sample.py` / `expected_L2_sample.py` to catch emitter drift (regenerate fixtures with a `--update-golden` flag, commit the checked-in versions).

**Acceptance:** `emit_build_py(circuit, "L1", path)` produces a file that, when executed, reconstructs an equivalent circuit. L2 produces a compact training-friendly form. Both are deterministic (sorted part/net ordering for reproducible output).

---

### Wave 3 — Multi-Unit Symbols & Part Wrappers (CONV-04, CONV-05)
**Goal:** Handle the highest-risk pitfall. Multi-unit symbols (NE5532 units A/B/C, RP2350B power/GPIO/peripheral units) and unknown/custom parts. Generate `parts.py` wrappers for unknown parts; map to existing wrappers for known parts.

**Files:**
- `src/kicad_agent/circuit_ir/symbol_resolver.py` (edit) — multi-unit enumeration
- `src/kicad_agent/circuit_ir/parts_registry.py` (edit) — wrapper generation
- `src/kicad_agent/circuit_ir/wrapper_generator.py` (new) — generate parts.py entries
- `tests/circuit_ir/test_multi_unit.py` (new)
- `tests/circuit_ir/test_wrapper_generation.py` (new)
- `tests/fixtures/circuit_ir/ne5532_dual_opamp.kicad_sch` (new) — NE5532 units A+B
- `tests/fixtures/circuit_ir/rp2350b_power_units.kicad_sch` (new) — multi-unit MCU

**Tasks:**
- [ ] **W3-1** (`symbol_resolver.py`): Extend `resolve_lib_symbol` to enumerate all units of a multi-unit symbol. For each `(symbol "NAME_U_x_y" ...)` sub-block, collect pins per unit. Handle the demorgan variant (`_0_1` conversion symbols) by preferring unit 1. Return `pins_by_unit: dict[int, list[PinRef]]`.
- [ ] **W3-2** (`symbol_resolver.py`): Implement the `_0_0 → _1_1` common-pin rename (pitfall #1). Common pins (power, NC) live in unit `_0_0` in the library but are referenced as `_1_1` in schematic instances. The resolver must attribute these to the correct unit so all parts get their power pins.
- [ ] **W3-3** (`skidl_circuit.py`): For multi-unit component instances (component has `unit > 1`), create a single `skidl.Part` and wire only the pins belonging to that unit (the SKIDL model: one Part per logical component, all units share the pin namespace). Validate pin count matches `get_pin_numbers_from_lib`.
- [ ] **W3-4** (`parts_registry.py`): Implement `is_known_part(lib_id) -> bool` against the ported LCSC registry. Known parts (NE5532, DG413, RP2350B, etc.) map to semantic-alias wrappers; the emitter imports from `parts_registry` instead of raw `Part()`.
- [ ] **W3-5** (`wrapper_generator.py`): `generate_wrapper(part_descriptor) -> str` — for unknown parts, emit a `parts.py`-style wrapper function with semantic pin aliases derived from the lib_symbol pin names. Falls back to generic `Conn_01xNN` connector modeling when the symbol still breaks extraction (the proven analog-ecosystem USBLC6/USBC pattern — pitfall #1 mitigation). Record the fallback in `diagnostics`.
- [ ] **W3-6** (`skidl_emitter.py` edit): When a part is known, emit `from kicad_agent.circuit_ir.parts_registry import NE5532, DG413` and use the wrapper. When unknown, emit the generated wrapper inline (or a `parts_generated.py` sidecar).
- [ ] **W3-7**: Test NE5532 — fixture with U1A (unit 1) + U1B (unit 2). Assert the built Circuit has ONE NE5532 part with all 8 pins, both units' connections wired to the correct pins (OUT_A, INV_A, OUT_B, INV_B).
- [ ] **W3-8**: Test RP2350B — multi-unit MCU (power unit + GPIO unit). Assert all power pins (VDD, GND) attributed correctly despite the `_0_0` rename.
- [ ] **W3-9**: Test fallback — a fixture with a deliberately-malformed multi-unit symbol triggers the generic-connector fallback; assert `diagnostics` contains the fallback record and the circuit still builds (no crash, no missing pins).

**Acceptance:** NE5532 dual-opamp, RP2350B multi-unit MCU, and USBLC6 (fallback case) all convert correctly with complete pin sets. Known parts use semantic-alias wrappers; unknown parts get generated wrappers. The 3 highest-risk pitfalls (#1, #4, #7) are handled.

---

### Wave 4 — Hierarchical Sheets (CONV-07)
**Goal:** Recursively flatten hierarchical sub-sheets into one flat `Circuit`. SKIDL has no native hierarchy — everything is a flat netlist. Sheet pins ↔ sub-sheet labels must connect to the same `Net`.

**Files:**
- `src/kicad_agent/circuit_ir/hierarchy_flattener.py` (new)
- `tests/circuit_ir/test_hierarchy_flattener.py` (new)
- `tests/fixtures/circuit_ir/hierarchical/` (new) — root + 2 sub-sheets + 1 nested sub-sub-sheet

**Tasks:**
- [ ] **W4-1** (`hierarchy_flattener.py`): `flatten_hierarchy(root_sch_path: Path) -> tuple[list[PartDescriptor], list[NetDescriptor]]`. Recursively traverse sheet instances using the `navigate_hierarchy` logic (reuse `ops/sheet_ops.navigate_hierarchy`). For each sub-sheet: parse via `SchematicIR`, extract components + nets, merge into the accumulating flat list. Tag each `PartDescriptor.sheet` with the originating sheet path (preserved as metadata for the Phase 157 floor planner's module-aware placement).
- [ ] **W4-2**: **Sheet-pin ↔ label merge.** A hierarchical sheet pin "SDA" on the parent and a hierarchical label "SDA" in the sub-sheet must connect to the same `Net("SDA")`. After flattening, merge: for each sheet instance, read its pins; for each sub-sheet hierarchical label with matching name, union their nets. Apply the `_match_lib_symbol` fallback for the `libraryNickname=None` bug (pitfall #3).
- [ ] **W4-3**: **Global label spanning.** After flattening all sheets, global labels with the same name across sheets are one net. Local labels are scoped per-sheet (but after flatten, same-named locals on different sheets are distinct unless connected via sheet pin). Use `NetPositionIndex.detect_shorts()` to catch multi-name net collisions during the merge (pitfall #3 mitigation).
- [ ] **W4-4** (`skidl_circuit.py` edit): When `flatten_hierarchy=True` (the `ConvertToSkidlOp` default), call `flatten_hierarchy` instead of single-sheet `extract_nets`. Preserve sheet membership in `PartDescriptor.sheet` → emitted as a comment in the `build_*.py` (for floor-planner consumption).
- [ ] **W4-5**: Test — 3-sheet fixture (root + sub1 + sub2, sub2 nested in sub1). Assert all components from all 3 sheets appear in the flat Circuit. Assert a net connected via sheet-pin↔hlabel (e.g., "SDA" on root sheet pin → "SDA" hlabel in sub1) is ONE net with pins from both sheets.
- [ ] **W4-6**: Test — global label "VCC" present on root + sub2 connects all VCC pins across sheets into one net.
- [ ] **W4-7**: Test — sheet metadata preserved. `PartDescriptor.sheet` is non-None for sub-sheet components; `None` for root-sheet components.

**Acceptance:** A 3-level hierarchical schematic flattens into one Circuit with correct cross-sheet net merging. Sheet membership is preserved as metadata. Pitfall #3 (hierarchical pin/sheet-pin resolution) is handled.

---

### Wave 5 — Power Symbols & No-Connects (CONV-06)
**Goal:** Power symbols (GND, +3V3) as `Net` assignments (never BOM components), and NC pins represented so ERC passes. This wave formalizes the power-net coalescing that Wave 1 sketched and wires it into both emission modes.

**Files:**
- `src/kicad_agent/circuit_ir/skidl_circuit.py` (edit) — power detection + NC handling
- `src/kicad_agent/circuit_ir/skidl_emitter.py` (edit) — power-as-Net emission
- `tests/circuit_ir/test_power_symbols.py` (new)
- `tests/circuit_ir/test_no_connects.py` (new)

**Tasks:**
- [ ] **W5-1** (`skidl_circuit.py`): Detect power symbols by `power:` lib_id prefix OR the `power` symbol attribute. Reuse `SymbolMapper._POWER_MAPPINGS` (from `ltspice/symbol_mapper.py:38`) to map `power:GND → "0"`, `power:+5V → "+5V"`. Create ONE `Net` per unique power rail; connect all matching power-symbol pins to it. Do NOT instantiate power symbols as BOM parts (pitfall #2 — they're net-name declarators).
- [ ] **W5-2** (`skidl_circuit.py`): If a power symbol is needed for ERC/schematic faithfulness (e.g., the `convert_from_skidl` path needs the symbol to place), instantiate `Part("power", "+3V3")` but mark it `virtual=True` / exclude from BOM. The read-back path (`convert_to_skidl`) treats them purely as Net assignments.
- [ ] **W5-3** (`skidl_circuit.py`): Detect NC flags — the `(no_connect ...)` S-expression element in `.kicad_sch`. For each NC pin, `pin += NC` (skidl's built-in no-connect handling) so ERC does not flag it as an unconnected-pin error.
- [ ] **W5-4** (`skidl_emitter.py`): In L1 mode, emit `net_GND = Net("GND")` + power-pin connections. In L2 mode, power nets appear in the component net-summary dicts. Neither mode emits power symbols as `Part()` instantiations (BOM correctness).
- [ ] **W5-5**: Test — fixture with +3V3, GND, +12V, -12V power symbols. Assert 4 power nets created, 0 power-symbol BOM parts, all power pins connected to correct rails.
- [ ] **W5-6**: Test — fixture with 2 NC pins. Assert `pin += NC` called, ERC passes (no "unconnected pin" violations for those pins).
- [ ] **W5-7**: Test — mixed power + signal net coalescence. A `+3V3` power symbol and a `+3V3` global label on the same sheet connect to one net (not two).

**Acceptance:** Power symbols become Net assignments (not BOM parts), NC pins pass ERC, and power rails coalesce correctly with same-named labels. Pitfall #2 fully handled.

---

### Wave 6 — Bidirectional Bridge & PCB Parser Fixes (CONV-08, CONV-09, CONV-10)
**Goal:** Close the loop. (a) Port `gen_schematic.py` (SKIDL→KiCad) and `gen_pcb.py` (SKIDL→PCB) into `circuit_ir/`. (b) Port the 5 `populate_pcb_from_netlist` workarounds **to the source** so all callers benefit. (c) Round-trip validation: convert ADSR + backplane → SKIDL → verify ERC matches original.

**Files:**
- `src/kicad_agent/circuit_ir/skidl_to_kicad.py` (new) — port of `gen_schematic.py`
- `src/kicad_agent/circuit_ir/skidl_to_pcb.py` (new) — thin wrapper over fixed populate
- `src/kicad_agent/crossfile/pcb_populate.py` (edit) — port the 5 fixes to source
- `src/kicad_agent/ops/handlers/schematic.py` (edit) — register `convert_from_skidl`
- `src/kicad_agent/ops/handlers/schematic_query.py` (edit) — register `convert_to_skidl`
- `src/kicad_agent/ops/_schema_circuit.py` (new) — both op schemas
- `src/kicad_agent/ops/schema.py` (edit) — add to union
- `src/kicad_agent/ops/registry.py` (edit) — add to catalog
- `src/kicad_agent/ops/execution.py` (edit) — add `convert_from_skidl` to `SELF_SERIALIZING_OPS`
- `scripts/validate_skidl_adsr.py` (new) — CONV-09 harness
- `scripts/validate_skidl_backplane.py` (new) — CONV-10 harness
- `tests/circuit_ir/test_round_trip.py` (new)
- `tests/circuit_ir/test_skidl_to_kicad.py` (new)

**Tasks:**
- [ ] **W6-1** (`skidl_to_kicad.py`): Port `gen_schematic.py` wholesale: `circuit_to_kicad_sch(circuit, out_path, *, place=True)`. Emits raw S-expression text via string construction (pitfall #7 — NOT kiutils serialization, which drops fields). Embeds lib_symbol definitions resolved from system `.kicad_sym` files via `symbol_resolver` (Wave 1). Places components as flat `(symbol ...)` instances on grid. No wires by default (`wire=False`) — ERC violations for unconnected pins are expected and acceptable (matches analog-ecosystem behavior).
- [ ] **W6-2** (`skidl_to_pcb.py`): Implement `circuit_to_pcb(circuit, out_path)`. Pipeline: `circuit.generate_netlist()` → `.net` → pre-parse to XML in the format `_parse_netlist_xml` expects → `populate_pcb_from_netlist` → (the 5 fixes, now in source) → write `.kicad_pcb`. This is a thin wrapper now that the fixes live in `populate_pcb_from_netlist`.
- [ ] **W6-3** (`crossfile/pcb_populate.py` edit — pitfall #5 source fixes): Port the 5 workarounds from `gen_pcb.py` into the populate function itself:
  1. S-expression netlist parsing: accept SKIDL's multiline S-expr `.net` (pre-parse to XML internally).
  2. `_inject_net_table`: inject `(net N "name")` declarations.
  3. `_rewrite_pad_nets_to_numeric`: convert name-only `(net "name")` pads to numeric `(net N "name")`.
  4. `_assign_ground_to_unconnected_pads`: assign GND to extra pads (mounting holes, thermal pads).
  5. Parser key: use `pad` (not `pin`) as the XML key in `_parse_netlist_xml`.
  Add regression tests ensuring existing callers still work (the fixes are additive — they activate only when the input lacks the table/numeric pads).
- [ ] **W6-4** (`ops/handlers/schematic_query.py` edit): Register `convert_to_skidl` handler:
  ```python
  @register_schematic_query("convert_to_skidl")
  def _handle_convert_to_skidl(op, ir, file_path):
      from kicad_agent.circuit_ir import build_circuit, emit_build_py
      from kicad_agent.schematic_routing.net_extractor import extract_nets
      nets = extract_nets(sch_path=file_path)
      circuit, circuit_ir = build_circuit(ir, nets, symbol_dir=op.symbol_dir)
      if op.run_erc:
          erc_errors = circuit.ERC()
      out_dir = Path(op.output_dir) if op.output_dir else file_path.parent
      path = emit_build_py(circuit, circuit_ir, mode=op.representation, out_path=out_dir / f"build_{file_path.stem}.py")
      return {"output_path": str(path), "parts": len(circuit_ir.parts), "nets": len(circuit_ir.nets),
              "diagnostics": list(circuit_ir.diagnostics), "erc": circuit.ERC() if op.run_erc else None}
  ```
- [ ] **W6-5** (`ops/handlers/schematic.py` edit): Register `convert_from_skidl` handler (mutating, self-serializing). Calls `circuit_to_kicad_sch` and writes the output. Add `"convert_from_skidl"` to `SELF_SERIALIZING_OPS` (it writes raw S-expr, not via kiutils).
- [ ] **W6-6** (`ops/_schema_circuit.py`, `ops/schema.py`, `ops/registry.py`): Add both op schemas, add to the `Operation` discriminated union, add to `_RAW_CATALOG`. Validate `validate_registry_completeness()` shows no drift.
- [ ] **W6-7** (`scripts/validate_skidl_adsr.py` — CONV-09): Convert `analog-ecosystem/hardware/adsr/adsr.kicad_sch` (35 parts — note: 106 `(symbol ...)` blocks include power/labels; ~35 BOM parts). Steps: `convert_to_skidl` → `build_adsr.py` → execute → `circuit.ERC()` → compare ERC error/warning count to the original `adsr-erc.rpt`. **Pass criterion:** ERC error count matches (both 0, or both equal — the SKIDL circuit must reproduce the same ERC result as the original KiCad schematic).
- [ ] **W6-8** (`scripts/validate_skidl_backplane.py` — CONV-10): Convert `analog-ecosystem/hardware/backplane/backplane.kicad_sch` (16 sheets, 94 parts). Steps: `convert_to_skidl` with `flatten_hierarchy=True` → `build_backplane.py`. **Pass criteria:** (a) all 94 parts present across all 16 sheets, (b) hierarchical structure preserved as `PartDescriptor.sheet` metadata, (c) cross-sheet nets merged correctly (spot-check GNDA, I2C_SDA, I2C_SCL rails), (d) ERC runs without new errors vs the original.
- [ ] **W6-9** (`test_round_trip.py`): Round-trip test — convert tiny fixture → SKIDL → `convert_from_skidl` → KiCad → `convert_to_skidl` again. Assert the two SKIDL circuits are equivalent (part-count, net-count, pin-membership sets stable across the round trip). This is the bidirectional proof (CONV-08).

**Acceptance:** SKIDL→KiCad and SKIDL→PCB paths work. `populate_pcb_from_netlist` is fixed at source (all 5 workarounds). ADSR converts with matching ERC; backplane converts with all 94 parts across 16 sheets and preserved hierarchy. Round-trip SKIDL↔KiCad is stable.

---

## Test Strategy

### Canonical tests: ADSR + backplane (CONV-09, CONV-10)

These are the two real-world schematics from analog-ecosystem that prove the converter works on designs Bret actually built.

| Schematic | Path | Parts | Sheets | Key challenge |
|---|---|---|---|---|
| **ADSR** (CONV-09) | `analog-ecosystem/hardware/adsr/adsr.kicad_sch` | ~35 BOM | 1 (flat) | Multi-unit (RP2350B), power rails, passives |
| **Backplane** (CONV-10) | `analog-ecosystem/hardware/backplane/backplane.kicad_sch` | 94 BOM | 16 (hierarchical) | Hierarchical flatten, cross-sheet nets, 16 sub-sheets |

**ADSR validation (CONV-09):** `convert_to_skidl` → `build_adsr.py` → execute → `circuit.ERC()`. Compare ERC error/warning count to original `adsr-erc.rpt`. The SKIDL circuit's ERC must match the original's result (same errors, same warnings — proving the conversion preserved electrical semantics). Part count and net topology verified against `extract_nets` baseline.

**Backplane validation (CONV-10):** `convert_to_skidl(flatten_hierarchy=True)` → `build_backplane.py`. Assert: (a) 94 BOM parts across all 16 sheets, (b) `PartDescriptor.sheet` metadata preserves which sheet each part came from (for Phase 157 floor planner), (c) cross-sheet rails (GNDA, I2C_SDA, I2C_SCL) merge into single nets, (d) ERC runs without *new* errors vs original. This is the hierarchical-flatten proof.

### Test pyramid

| Layer | What | Count |
|---|---|---|
| Unit (W1) | `build_circuit` on tiny fixtures, `symbol_resolver` pin counts, import guard | ~18 |
| Unit (W2) | L1/L2 emission, golden-file comparison, execute-emitted-file round-trip | ~12 |
| Unit (W3) | Multi-unit NE5532/RP2350B, wrapper generation, fallback connector | ~14 |
| Unit (W4) | Hierarchy flatten, sheet-pin↔label merge, global-label spanning | ~10 |
| Unit (W5) | Power-as-Net, NC pins, power+label coalescence | ~10 |
| Unit (W6) | `skidl_to_kicad`, `skidl_to_pcb`, round-trip stability, `populate` fixes | ~12 |
| Integration (W6) | `convert_to_skidl` op via executor, `convert_from_skidl` op | ~6 |
| **Canonical** (W6) | ADSR ERC match (CONV-09), backplane 16-sheet flatten (CONV-10) | ~2 harnesses |
| **Total** | | **~84 tests + 2 validation harnesses** |

### Fixtures

- `tests/fixtures/circuit_ir/tiny_rc_led.kicad_sch` (W1) — 3 parts + GND, single sheet
- `tests/fixtures/circuit_ir/ne5532_dual_opamp.kicad_sch` (W3) — NE5532 units A+B
- `tests/fixtures/circuit_ir/rp2350b_power_units.kicad_sch` (W3) — multi-unit MCU
- `tests/fixtures/circuit_ir/hierarchical/` (W4) — root + sub1 + nested sub2
- `tests/fixtures/circuit_ir/power_symbols.kicad_sch` (W5) — +3V3, GND, +12V, -12V, NC pins
- `tests/fixtures/circuit_ir/expected_L1_sample.py` / `expected_L2_sample.py` (W2) — golden emitters
- External (not vendored, read via path): `analog-ecosystem/hardware/adsr/adsr.kicad_sch`, `analog-ecosystem/hardware/backplane/backplane.kicad_sch`

---

## Requirement → Wave Coverage

| Req | Description | Wave |
|---|---|---|
| CONV-01 | `convert_to_skidl` reads .kicad_sch → generates build_*.py | **W1** (build) + **W2** (emit) + **W6** (op) |
| CONV-02 | L1 representation (pin-level, exact) | **W2** |
| CONV-03 | L2 representation (component-level, training) | **W2** |
| CONV-04 | Map to existing wrappers / generate new | **W1** (registry) + **W3** (generation) |
| CONV-05 | Multi-unit symbols (NE5532 A/B/C, RP2350B) | **W3** |
| CONV-06 | Power symbols as Net assignments | **W5** |
| CONV-07 | Hierarchical sheets (recursive flatten) | **W4** |
| CONV-08 | Bidirectional: SKIDL → KiCad via gen_schematic | **W6** |
| CONV-09 | Test: ADSR (35 parts) → ERC matches | **W6** |
| CONV-10 | Test: backplane (16 sheets, 94 parts) → hierarchy preserved | **W6** |

## Roadmap Success Criteria → Wave Coverage

1. `convert_to_skidl` reads any `.kicad_sch` → generates `build_*.py` (pin-name wiring) → **W1 + W2 + W6**
2. Both L1 and L2 representations emitted per SchGen ablation → **W2**
3. Multi-unit, power symbols, hierarchical sheets handled (pitfalls #1, #2, #3) → **W3 + W4 + W5**
4. Bidirectional: SKIDL → valid `.kicad_sch` + 5 populate fixes ported to source → **W6**
5. ADSR ERC matches; backplane preserves 16-sheet/94-part hierarchy → **W6**

---

## Risks & Mitigations (from STACK-SKIDL §PITFALLS)

| # | Pitfall | Risk | Mitigation | Wave |
|---|---|---|---|---|
| 6 | `KICAD_SYMBOL_DIR` race | skidl import fails silently, parts get no pins (confirmed in live env: `KICAD8_SYMBOL_DIR is missing` warning) | `_ensure_skidl_env()` import guard in `__init__.py` sets env BEFORE `import skidl` (port `parts.py:22-25`); W1-8 test asserts no warning | W1 |
| 1 | Multi-unit symbol extraction | NE5532/RP2350B pins misattributed or missing | Port `resolve_lib_symbol` + `_resolve_extends` + `_0_0→_1_1` rename; fallback to generic `Conn_01xNN` (USBLC6 pattern); W3 tests on real multi-unit fixtures | W3 |
| 4 | lib_symbol extends inheritance | Child symbol has zero pins (inherits all) → incomplete pin map | `_resolve_extends` walks inheritance chain, merges parent units/pins; `get_pin_numbers_from_lib` parses all units | W1/W3 |
| 2 | Power flags / power symbols | Power symbols become spurious BOM parts; SPICE breaks | Reuse `SymbolMapper._POWER_MAPPINGS`; power → `Net` assignments only; `virtual=True` if symbol needed for placement; W5 tests | W5 |
| 3 | Hierarchical pin / sheet-pin | Cross-sheet nets don't merge; `libraryNickname=None` bug | Flatten before net resolution; `_match_lib_symbol` fallback; `NetPositionIndex.detect_shorts()` for collisions; W4 tests | W4 |
| 5 | PCB population parser | SKIDL netlist malformed; missing net table; name-only pads | Port 5 workarounds to `crossfile/pcb_populate.py` source (option (a) in research — fixes for all callers); W6 regression tests | W6 |
| 7 | kiutils drops fields | SKIDL→KiCad output invalid | `skidl_to_kicad.py` emits raw S-expr via string construction (not kiutils `sexify`); W6 round-trip parse validates | W6 |
| 8 | SPICE model availability | Full-board SPICE infeasible (out of scope for 156) | Deferred to Phase 158 (analog sub-circuits only); this phase's ERC check is the validation gate, not SPICE | — |

### Additional project-specific risks

| Risk | Mitigation |
|---|---|
| skidl not in `pyproject.toml` (confirmed: only `spicelib` declared, skidl installed but undeclared) | W1 adds `skidl>=2.2.3` to `pyproject.toml` dependencies (research STACK §Dependency to Add) |
| ADSR/backplane live in `analog-ecosystem`, not `kicad-agent` | Validation harnesses read via absolute path; fixtures stay external (not vendored — they're large and evolve). Tests skip gracefully if path absent (`pytest.skip`) but CI expects them present on Bret's machine |
| Emitted `build_*.py` executes arbitrary code | Emitter produces only `skidl` imports + `Part`/`Net`/`+=` statements (no `os`, `subprocess`, `eval`). W2-6 executes emitted files in a subprocess with `KICAD_SYMBOL_DIR` set — no network/filesystem side effects beyond `circuit.generate_netlist()` |
| `gen_schematic.py` is ~600 LOC of proven analog-ecosystem code | Port wholesale into `skidl_to_kicad.py` with minimal refactoring; adapt the hardcoded paths to use `symbol_resolver` (Wave 1). Preserve the proven raw-S-expr emitter. Do not "improve" it in Wave 6 — port first, refactor later if needed |
| L2 emission not round-trip-exact (by design) | Document clearly: L1 is the round-trip target, L2 is the training form. W2-7 tests L2 structural correctness (part-count, net-summary), not equivalence |

---

## Definition of Done

- [ ] All 10 CONV requirements checked off in `REQUIREMENTS.md`
- [ ] All 5 Roadmap success criteria TRUE
- [ ] `src/kicad_agent/circuit_ir/` ships with: `build_circuit`, `emit_build_py`, `circuit_to_kicad_sch`, `circuit_to_pcb`, `parts_registry`, `symbol_resolver`, `hierarchy_flattener`
- [ ] `convert_to_skidl` and `convert_from_skidl` ops registered in schema + handlers + registry; `validate_registry_completeness()` shows no drift
- [ ] `skidl>=2.2.3` declared in `pyproject.toml`
- [ ] `populate_pcb_from_netlist` fixed at source (5 workarounds ported); existing callers unaffected
- [ ] ADSR converts → `build_adsr.py` → ERC matches original (CONV-09)
- [ ] Backplane converts (16 sheets, 94 parts) → hierarchy preserved as metadata, cross-sheet nets merged (CONV-10)
- [ ] ~84 tests green, coverage ≥90% on `circuit_ir/`
- [ ] Round-trip KiCad → SKIDL → KiCad → SKIDL stable (CONV-08 bidirectional proof)
