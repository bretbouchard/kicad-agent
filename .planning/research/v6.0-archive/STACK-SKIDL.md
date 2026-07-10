# STACK-SKIDL — SKIDL-Native Design Pipeline Research

**Milestone:** v5.0 — "Skidl-Native Design Pipeline"
**Date:** 2026-07-03
**Purpose:** Document the Python library stack, converter feature surface, architecture integration points, and known pitfalls for adopting SKIDL as the canonical intermediate representation (IR) for all circuit operations in kicad-agent v5.0.

---

## Reference Validation: SchGen's Semantic-Grounded Code Representation (L1/L2/L3)

The decision to use SKIDL as the IR for circuit generation is externally validated by **SchGen** (Luo et al., Microsoft Research Asia / UCSD / UT Austin), the first LLM that generates editable PCB schematics from natural-language requests. SchGen's central contribution is proving that *representation design* — not raw model scale — is the key enabler for LLM-driven schematic generation.

### The 3-Level Representation Ablation

SchGen defines a compact set of Python editing APIs that mirror how engineers draw schematics:

| API | Purpose |
|---|---|
| `add_schematic_symbol(lib, name, x, y, ref, value, rotation, mirror)` | Place a symbol |
| `add_label(pos, text, ref, type, orient)` | Place a net label |
| `get_pin_location(ref, pin_name)` | Query a pin's coordinates |
| `connect_pins(ref_a, pin_a, ref_b, pin_b)` | Connect two pins by **semantic name** |
| `write_out_all_wires()` | Emit the final KiCad schematic |

The paper tests three representation levels (ablation in Table 1 & 2):

- **Code-L1 (proposed, best):** *Relative coordinates* + *pin-name-based wiring*. Symbols are placed using local offsets from an anchor component (`center_x + offset`). Wires are specified via `connect_pins(ref, "VCC", ref, "VIN")` — the model never sees absolute coordinates. This transforms schematic generation from an absolute-geometry prediction problem into a **semantics-driven matching task**.
- **Code-L2:** Removes relative coordinates — uses **absolute coordinates** for symbol placement instead. Still retains pin-name-based `connect_pins`.
- **Code-L3:** Removes *both* relative coordinates and pin-name connectivity. Replaces `connect_pins` with `add_new_wire([x1,y1],[x2,y2])` — raw wire segments drawn at absolute coordinates. The model must independently compute pin locations and draw geometry.

### Why L1 Wins (the key finding for kicad-agent)

L1 achieves the **lowest Minimum Description Length (MDL)**, **lowest Lempel-Ziv complexity**, and **lowest validation loss** — meaning relative coordinates and pin-name connectivity jointly produce a more structured, compressible, and learnable representation. Empirically:

| Representation | Valid Circuits | Netlist Jaccard | Functional Correctness |
|---|---|---|---|
| **Code-L1** | **82%** | **49.08%** | **60.5%** |
| Code-L2 | lower | lower | lower |
| Code-L3 | lower (large netlist drop) | large drop | — |
| Raw KiCad file | 32% | very low | very low |

The L2→L3 drop is the most telling: removing pin-name connectivity causes a *"large drop in netlist accuracy, indicating that pin-name connectivity is critical for correct wiring."* This directly validates SKIDL's design philosophy — SKIDL connects parts via `part["VCC"] += net`, which is precisely the pin-name-based wiring that L1 proves is essential.

**Implication for kicad-agent v5.0:** SKIDL *is* a Code-L1 representation. It uses semantic pin names (`part["ALIAS"] += net`), relative/abstract connectivity (no absolute geometry), and a compact editing primitive set (`Part()`, `Net()`, `+=`). Adopting SKIDL as the IR gives kicad-agent the representation SchGen proved is optimal, without building a custom API layer.

> **Note:** SchGen explicitly does *not* use SPICE for evaluation because "most PCB schematics are system-level mixed-domain designs containing components beyond the scope of available SPICE models." kicad-agent's v5.0 plan to use SPICE results as a reward signal should therefore target **analog sub-circuits** (where the analog-ecosystem mono-arch already demonstrates the pattern), not full-board validation.

---

## STACK — Python Libraries Required

### Current State

| Library | Version | Status in kicad-agent | Action |
|---|---|---|---|
| **skidl** | 2.2.3 | Installed in environment, **NOT in `pyproject.toml`** | **ADD as dependency** |
| ngspice | 45.2 | External binary (CLI simulator) | Wire via subprocess; ensure on PATH |
| PySpice | — | **NOT installed** | **Do NOT add** — spicelib covers ngspice interaction |
| spicelib | ≥1.5.1 | ✅ Already a dependency (`pyproject.toml`) | Used for `.asc`/`.raw` parsing, `AsyReader` |
| networkx | ≥3.0 | ✅ Already a dependency | Net connectivity graphs (both SKIDL & LTspice) |
| kiutils | ≥1.4.8 | ✅ Already a dependency | KiCad file parsing (schematic, PCB, symbol lib) |
| sexpdata | ≥1.0.0 | ✅ Already a dependency | S-expression netlist parsing |

### What Each Library Provides

**`skidl` (the new core IR)** — Programmatic circuit/netlist generation:
- `Circuit()` context for building netlists in Python
- `Part(lib, name, footprint=..., value=...)` for component instantiation
- `Net("name")` for named electrical nets
- `part["PIN_NAME"] += net` for pin-name-based wiring (the Code-L1 pattern)
- `part.aliases += {"alias": pin}` for semantic pin aliases
- `ckt.ERC()` for Electrical Rules Check
- `ckt.generate_netlist(file_="circuit.net")` → KiCad S-expression `.net` format
- `Circuit` read-back from `.net` via `Circuit("name").parse_netlist()` (for SKIDL→graph round-trip)

**Critical initialization constraint** (from analog-ecosystem `parts.py`): `KICAD_SYMBOL_DIR` **must be set BEFORE importing skidl**, otherwise skidl cannot resolve the KiCad symbol libraries for part instantiation:
```python
import os
os.environ.setdefault("KICAD_SYMBOL_DIR", str(KICAD_SYMLIB_PATH))
import skidl
```

**`spicelib`** — Already used in `kicad_agent.ltspice`:
- `AsyReader` for `.asy` symbol files (pin offsets, rotations)
- `.asc`/`.raw` parsing for LTspice import/sim results
- For ngspice interaction, spicelib provides the ngspice shared-library interface that PySpice would otherwise provide — **no need for PySpice**

**`ngspice`** (external binary, v45.2) — The actual simulator engine:
- Invoked as subprocess or via spicelib's shared-library binding
- Consumes SPICE decks (`.cir`/`.sp`), produces `.raw` results
- kicad-agent's `read_raw()` already parses `.raw` output

**`networkx`** — Connectivity graph engine:
- Used by `LTspiceNetGraph` (wire geometry → connected components)
- Used by `extract_nets` indirectly (union-find over wire segments)
- SKIDL circuits produce `Network` objects that map naturally to networkx graphs for analysis

### Dependency to Add

```toml
# pyproject.toml — add to [project] dependencies
dependencies = [
    # ... existing ...
    "skidl>=2.2.3",
]
```

The `KICAD_SYMBOL_DIR` environment variable must be configured at runtime (pointing at the kicad-agent's bundled symbol libraries or the system KiCad install). This should be set in a skidl integration module's import-time guard.

---

## FEATURES — What the SKIDL Converter Must Handle

The v5.0 converter must round-trip between KiCad schematics (`.kicad_sch`) and SKIDL `Circuit` objects. The feature surface below is derived from the analog-ecosystem pipeline (which already does SKIDL→KiCad) and the gap analysis of what KiCad→SKIDL read-back requires.

### 1. Hierarchical Sheets

KiCad hierarchical sheets decompose a board into sub-sheets connected via hierarchical pins (sheet pins ↔ sub-sheet labels). SKIDL has no native hierarchy concept — everything is a flat netlist.

**Requirements:**
- Flatten hierarchy: traverse `.kicad_sch` sheet instances recursively, merge all components into one `Circuit`
- Map hierarchical sheet pins to net labels: a sheet pin "SDA" on the parent sheet and a matching label "SDA" in the sub-sheet must connect to the same `Net("SDA")`
- Preserve sheet membership as metadata (component property or grouping) for the floor planner's module-aware placement
- Handle the `navigate_hierarchy` operation's existing data (kicad-agent already has this handler)

### 2. Custom Symbols (Non-Standard Library Parts)

Not every symbol is in the standard KiCad libraries. The analog-ecosystem `parts.py` defines custom part wrappers with LCSC numbers, footprints, and semantic pin aliases.

**Requirements:**
- Resolve arbitrary `libId` strings (e.g., `"Analog:NE5532"`, `"Switch:DG413"`) against configurable symbol library paths
- Support `KICAD_SYMBOL_DIR` pointing at a custom symlib (the analog-ecosystem pattern)
- Carry part metadata through SKIDL: footprint (`FP` dict), LCSC part number, price, basic/extended flag — these become SKIDL Part attributes or a sidecar manifest
- Semantic pin aliases: map human-readable names (`"IN+"`, `"OUT"`) to pin numbers via `part.aliases += {...}` — the analog-ecosystem `_alias(part, pin_num, *aliases)` pattern

### 3. Power Symbols

Power symbols (`power:GND`, `power:+3V3`, etc.) are special — they define net names implicitly. The analog-ecosystem `symbol_mapper.py` already handles this for the LTspice export path.

**Requirements:**
- Detect power symbols by `power:` library prefix or by the `power` symbol attribute
- Create a single `Net` per unique power rail (e.g., `Net("+3V3")`) and connect all matching power symbol pins to it
- In SKIDL, power symbols can be instantiated as `Part("power", "+3V3")` with their single pin connected to the rail net
- For SPICE export (LTspice path): power symbols become `FLAG` statements, not `SYMBOL` statements (already implemented in `symbol_mapper.py`'s `_POWER_MAPPINGS`)

### 4. Labels (Local, Global, Hierarchical)

KiCad labels define net names at wire endpoints. Three types: local labels (single sheet), global labels (cross-sheet), hierarchical labels (sheet interface).

**Requirements:**
- Local labels → `Net("label_text")`, scoped within the flattened circuit
- Global labels → `Net("label_text")` that spans all sheets (after flattening, all same-named global labels are one net)
- Hierarchical labels → connected to sheet pins on the parent (see hierarchical sheets above)
- The existing `extract_nets` resolver (`net_extractor.py`) already resolves net names with priority: **label name > pin_index name > auto-name (Net_N)**. The SKIDL converter should reuse this resolution priority.

### 5. No-Connects (NC Pins)

KiCad marks intentionally unconnected pins with no-connect flags. SKIDL must represent these so ERC passes.

**Requirements:**
- Detect NC flags (the `(no_connect ...)` S-expression element in `.kicad_sch`)
- Create an `NC` net per unconnected pin, or use SKIDL's built-in `NC` handling (`pin += NC`)
- Ensure ERC does not flag these as errors

### 6. Bidirectional Conversion (the v5.0 bridge)

The milestone calls for a *bidirectional* KiCad↔SKIDL bridge:

| Direction | Path | Status |
|---|---|---|
| **SKIDL → KiCad schematic** | `Circuit.generate_netlist()` → `.net` → `gen_schematic.py` (resolve lib_symbols, place on grid, no wires) | ✅ Proven in analog-ecosystem |
| **SKIDL → KiCad PCB** | `.net` → XML netlist → `populate_pcb_from_netlist` + post-processing | ⚠️ Proven but with workarounds (see PITFALLS) |
| **KiCad schematic → SKIDL** | `.kicad_sch` → `extract_nets` → build `Circuit` with `Part`/`Net` objects | ❌ **Does not exist** — must be built |
| **SKIDL → SPICE** | `Circuit` → SPICE deck (subcircuits for ICs) → ngspice → `.raw` | ❌ **Does not exist** — must be built |

---

## ARCHITECTURE — Integration with Existing kicad-agent Ops

### What Already Exists

kicad-agent has a mature operation pipeline and substantial schematic analysis infrastructure. The SKIDL converter must integrate with — not replace — these systems.

**Operation pipeline pattern:**
```
JSON input → Pydantic validation → gate check → handler(ir, file_path) → post-validation → atomic write
```
Every handler follows the signature `(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]`. Schematic query handlers are registered via `@register_schematic_query("op_type")` in `ops/handlers/schematic_query.py`. There are 98 operation types across 25 categories.

**Existing schematic infrastructure (reusable):**

| Component | Location | Role |
|---|---|---|
| `SchematicIR` | `ir/schematic_ir.py` | Thin wrapper over `kiutils.Schematic` with mutation tracking. Provides `get_component_by_ref()`, `get_labels_by_name()`, `components` property. The IR the converter would read from. |
| `extract_nets` | `schematic_routing/net_extractor.py` | **The closest thing to a KiCad→connectivity extractor that exists.** Builds net topology via union-find over wire segments, resolves net names (label > pin_index > auto). Returns `{nets: {name: [{ref, pin_number, pin_name, position}]}, stats}`. |
| `NetPositionIndex` | `schematic_routing/net_extractor.py` | Maps any schematic position to its net name; detects shorts (multiple labels on one component). Useful for SKIDL validation. |
| `SchematicGraph` | `schematic_routing/schematic_graph.py` | Wire/pin/label/junction graph from `.kicad_sch`. Foundation for `extract_nets`. |
| `navigate_hierarchy` | `ops/handlers/schematic_query.py` → `sheet_ops.py` | Hierarchical sheet traversal. |
| `validate_power_nets` | `ops/validation_gates.py` | Power net validation (already hierarchical-aware). |
| `pre_pcb_schematic_gate` | `ops/validation_gates.py` | Stage gate: SCHEMATIC → PCB_SETUP. |
| `SymbolMapper` | `ltspice/symbol_mapper.py` | KiCad libId → LTspice symbol / power FLAG. **Directly reusable** for SKIDL→SPICE power symbol handling. |

**LTspice module as architectural precedent:**
The `kicad_agent.ltspice` package is the existing model for a self-contained subsystem with parse → IR → graph → export. Its structure should be mirrored for a `kicad_agent.skidl` (or `circuit_ir`) package:
```
ltspice/
  __init__.py          # public API exports
  asc_parser.py        # parse_asc()
  asc_writer.py        # AscWriter, export_schematic_to_asc()
  net_graph.py         # LTspiceNetGraph (networkx)
  raw_reader.py        # read_raw()
  sim_commands.py      # AcCommand, TranCommand, etc.
  symbol_mapper.py     # SymbolMapper
  types.py             # frozen dataclasses
  asy_stubs/           # bundled .asy symbol stubs
```

### What Is Missing (the v5.0 build surface)

**1. SKIDL package** — No `skidl`/`circuit_ir` module exists. A `grep` for "skidl" across `src/kicad_agent/` returns zero results. Must build:
```
circuit_ir/ (proposed)
  __init__.py
  skidl_circuit.py      # Circuit builder from SchematicIR/extract_nets output
  skidl_to_kicad.py     # SKIDL → .kicad_sch (port of gen_schematic.py)
  skidl_to_pcb.py       # SKIDL → PCB (port of gen_pcb.py, with fixes)
  skidl_to_spice.py     # SKIDL → SPICE deck → ngspice
  spice_runner.py       # ngspice subprocess wrapper + read_raw()
  parts_registry.py     # Part wrappers + LCSC/footprint metadata (port of parts.py)
  net_graph.py          # Circuit → networkx graph (for analysis)
  types.py              # frozen dataclasses for CircuitIR
```

**2. KiCad → SKIDL read-back** — The reverse of `gen_schematic.py`. Input: `.kicad_sch` (via `SchematicIR` + `extract_nets`). Output: `skidl.Circuit` object with `Part` and `Net` instances. This is the foundational new capability — it enables importing legacy designs as editable SKIDL.

The read-back should compose existing pieces:
```
.kicad_sch
  → parse_schematic() [exists] → SchematicIR [exists]
  → extract_nets() [exists] → {nets: {name: [{ref, pin, ...}]}}
  → for each component in SchematicIR.components: create skidl.Part(lib, name, footprint, value)
  → for each net in extract_nets output: create skidl.Net(name), connect pins
  → return Circuit
```

**3. SchematicIR enhancements** — `SchematicIR` currently wraps `kiutils.Schematic` but does not expose: hierarchical flattening, lib_symbol extraction (the `_match_lib_symbol` helper handles the `libraryNickname=None` case but there's no public API for full lib_symbol → SKIDL Part resolution). The converter needs access to each component's full pin list (numbers + names + electrical type), which requires lib_symbol lookup.

**4. New operation handlers** — Register in `schematic_query.py` (or a new `circuit` handler category):
- `convert_to_skidl` — KiCad schematic → SKIDL Circuit (read-back)
- `convert_from_skidl` — SKIDL Circuit → KiCad schematic
- `run_spice` — SKIDL Circuit → SPICE → ngspice → `.raw` results
- `validate_spice` — Compare SPICE results against expected behavior (reward signal)

**5. No schematic NativeParser** — `NativeParser` (in `ir/pcb_ir.py`, `execution.py`, `orchestrator.py`, `dsn_generator.py`) is **PCB-only**. There is no equivalent native schematic parser. The SKIDL read-back path must build on `SchematicIR` + `net_extractor` rather than a parallel native parser. This is acceptable — `extract_nets` already does the heavy lifting (union-find connectivity + net name resolution).

### Integration with Stage Gates

The v5.0 pipeline stages map to existing gates:

| Stage | Gate | SKIDL Role |
|---|---|---|
| NL → Circuit | (new) | SKIDL Circuit is the output IR for the text model |
| Circuit → Schematic | `pre_pcb_schematic_gate` | SKIDL → `.kicad_sch` via converter |
| Schematic → Simulation | (new) | SKIDL → SPICE → ngspice → `.raw`; results feed back as reward signal |
| Schematic → PCB | existing `pcb_transfer` ops | SKIDL `.net` → `populate_pcb_from_netlist` (with fixes from PITFALLS) |
| PCB → Floor Plan | existing autolayout ops | Module-aware placement from SKIDL hierarchy metadata |
| PCB → Routing | existing `pcb_auto_route` ops | Netlist from SKIDL drives the router |
| PCB → Manufacturing | existing gerber/export ops | Unchanged |

---

## PITFALLS — What Breaks When Converting Legacy Schematics to SKIDL

These pitfalls are drawn from the analog-ecosystem pipeline (`gen_schematic.py`, `gen_pcb.py`, `parts.py`), which is the only proven SKIDL↔KiCad implementation. Every one of these has a documented workaround that must be ported into kicad-agent.

### 1. Multi-Unit Symbols Break lib_symbol Extraction

**Problem:** KiCad symbols with complex unit structures (multiple `(symbol ...)` blocks for units U1, U2, etc.) break the `gen_schematic.py` lib_symbol extraction logic. The extraction assumes a single-unit symbol and fails to correctly resolve pins when a symbol has demorgan units or split representation.

**Documented case:** In `parts.py`, `USBLC6` (USB ESD protection) and `USBC_Receptacle` (USB-C connector) are explicitly modeled as **generic `Conn_01xNN` connectors** instead of their real symbols, with a comment: *"modeled as generic connector — KiCad symbol has complex unit structure that breaks gen_schematic.py lib_symbol extraction."*

**Impact on read-back:** When converting a legacy `.kicad_sch` that contains multi-unit symbols (op-amps split across units, large connectors, FPGAs with power units), the SKIDL `Part` creation may:
- Misattribute pins to the wrong unit
- Miss pins entirely (units not enumerated)
- Produce incorrect pin-number-to-name mappings

**Mitigation:**
- Port `gen_schematic.py`'s `resolve_lib_symbol()` which resolves `extends` inheritance and merges parent units/pins with child properties
- Port the `_resolve_extends` merge logic (parent's units/pins + child's overrides)
- Handle the `_0_0` → `_1_1` unit rename convention (common pins live in unit `_0_0` in lib but `_1_1` in instances)
- For symbols that still break: fall back to generic connector modeling (the analog-ecosystem pattern)

### 2. Power Flags and Power Symbol Handling

**Problem:** Power symbols (`power:GND`, `power:+3V3`) are not "real" components — they're net-name declarators. If treated as normal parts in SKIDL, they create spurious components in the BOM and break SPICE export (SPICE expects net names, not power-symbol components).

**Impact:**
- BOM generation counts power symbols as parts
- SPICE deck contains nonsensical GND/voltage "components"
- Net name resolution duplicates power nets (one from the symbol, one from labels)

**Mitigation** (already partially solved):
- `symbol_mapper.py`'s `_POWER_MAPPINGS` maps power libIds to FLAG/net-name semantics. `power:GND` → `"0"` (SPICE ground), `power:+5V` → `"+5V"`. Reuse this.
- In SKIDL, instantiate power symbols as `Part("power", "+3V3")` but mark them as virtual/non-BOM
- For SPICE: power symbols emit `.nodeset` or `FLAG` directives, not component lines

### 3. Hierarchical Pin / Sheet Pin Resolution

**Problem:** Hierarchical sheets expose interface pins that connect to labels inside the sub-sheet. The pin name on the sheet instance and the label name inside must match, but:
- Sheet pins and labels can have name collisions with other nets
- The `libraryNickname=None` bug (Issue #6 in `_match_lib_symbol`) means some lib symbols lack the library prefix, breaking resolution
- Hierarchical labels that are also global labels create ambiguous net connections

**Mitigation:**
- Flatten hierarchy *before* net resolution (the `navigate_hierarchy` handler provides the traversal)
- Apply the `_match_lib_symbol` fallback (match by `entryName` when `libraryNickname` is None)
- Use `NetPositionIndex.detect_shorts()` to catch multi-name net collisions during read-back

### 4. lib_symbol Mismatches (extends Inheritance, Unit Renames)

**Problem:** The KiCad symbol library uses `extends` inheritance — a child symbol inherits pins/units from a parent but overrides properties. When extracting a symbol for SKIDL, the converter must walk the inheritance chain or it will produce an incomplete pin set.

**Specific sub-issues (from `gen_schematic.py`):**
- `extends` inheritance: child symbol may define zero pins itself, inheriting all from parent. Must call `_resolve_extends` to merge.
- Unit rename: common pins (power, NC) live in unit `_0_0` in the library definition but are referenced as `_1_1` in schematic instances. The converter must handle this rename.
- Pin number extraction: `get_pin_numbers_from_lib` must parse all units, not just the primary unit.
- `get_pin_numbers_from_lib` in `gen_schematic.py` is the reference implementation for this.

**Impact:** Missing or wrong pins → SKIDL `Part` has incorrect pin map → `part["VCC"] += net` fails (pin not found) → circuit is incorrect.

### 5. PCB Population: Name-Only Pads and Missing Net Tables

**Problem:** When going SKIDL → PCB via `populate_pcb_from_netlist`, kicad-agent's netlist parser has known issues that require external workarounds (documented in `gen_pcb.py`):

1. **S-expression layout parsing:** SKIDL's `generate_netlist()` produces a multiline S-expression that kicad-agent's parser doesn't handle. `gen_pcb.py` pre-parses it into temp XML first.
2. **Missing net table:** `populate_pcb_from_netlist` doesn't inject the `(net N "name")` declarations. `_inject_net_table` must be called.
3. **Name-only pads:** `populate_pcb_from_netlist` writes pads with name-only `(net "name")` but KiCad and the Quilter router need numeric `(net N "name")`. `_rewrite_pad_nets_to_numeric` converts these.
4. **Pin-count mismatches:** Extra pads (mounting holes, thermal pads, crystal ground pads) have no net assignment. `_assign_ground_to_unconnected_pads` assigns GND to fix the mismatch.
5. **Parser key mismatch:** kicad-agent's `_parse_netlist_xml` reads `node.get("pad")` not `node.get("pin")` — the XML conversion must use "pad" as the key.

**Mitigation:** These five workarounds from `gen_pcb.py` must either be (a) ported into kicad-agent's `populate_pcb_from_netlist` to fix it at the source, or (b) wrapped in a `skidl_to_pcb.py` adapter. Option (a) is preferable — it fixes the parser for all callers.

### 6. KICAD_SYMBOL_DIR Initialization Race

**Problem:** SKIDL resolves symbols against KiCad library files at `import skidl` time. If `KICAD_SYMBOL_DIR` is not set before the import, skidl silently fails to resolve any `Part()` call (parts have no pins). This is a **module-level side effect** that is easy to miss.

**Mitigation** (from `parts.py` lines 22-25):
```python
import os
os.environ.setdefault("KICAD_SYMBOL_DIR", str(_KICAD_SYMLIB_PATH))
import skidl  # MUST come after env var is set
```
The skidl integration module must enforce this ordering, ideally with an import guard that raises a clear error if the env var is unset.

### 7. Raw S-expression Generation (kiutils Drops Fields)

**Problem:** `gen_schematic.py` produces raw S-expression text by string concatenation, NOT via kiutils serialization, because *"kiutils drops fields"* needed for valid KiCad 10 schematics. This means the SKIDL→schematic converter cannot simply use `kiutils.Schematic().sexify()`.

**Impact:** The output path must maintain its own S-expression emitter (the `gen_schematic.py` approach) or contribute the missing fields back to kiutils. This is a maintenance burden but currently unavoidable.

### 8. SPICE Model Availability for Full Boards

**Problem** (from SchGen): "most PCB schematics are system-level mixed-domain designs containing components beyond the scope of available SPICE models." Microcontrollers, digital ICs, and connectors have no usable SPICE model.

**Impact on v5.0 SPICE reward signal:** The SPICE-as-reward-signal plan can only validate **analog sub-circuits** (power supplies, filter networks, analog signal chains). Full-board SPICE simulation is not feasible.

**Mitigation:**
- Identify analog sub-circuits within the SKIDL Circuit (connected components of analog parts: resistors, caps, op-amps, transistors, diodes)
- Extract each as a standalone SPICE subcircuit, simulate independently
- Use the analog-ecosystem mono-arch (116 parts, NE5532/DG413 op-amps) as the reference for what's simulatable
- Aggregate sub-circuit SPICE results as a partial reward signal, not a binary pass/fail

---

## Summary

| Question | Answer |
|---|---|
| **STACK** | Add `skidl>=2.2.3` to dependencies (already installed, just not declared). Reuse spicelib/networkx/kiutils. Do NOT add PySpice — spicelib covers ngspice. Configure `KICAD_SYMBOL_DIR` at import time. |
| **FEATURES** | Bidirectional KiCad↔SKIDL bridge handling: hierarchical sheet flattening, custom symbol resolution, power-as-net semantics, label→net mapping, NC pin handling. Two new directions don't exist: KiCad→SKIDL read-back and SKIDL→SPICE. |
| **ARCHITECTURE** | Build a `circuit_ir/` package mirroring `ltspice/` structure. Compose existing `extract_nets` + `SchematicIR` for read-back. Register new ops in `schematic_query.py`. No schematic NativeParser exists (PCB-only) — build on SchematicIR instead. Fix `populate_pcb_from_netlist` at source rather than external workarounds. |
| **PITFALLS** | 8 documented pitfalls, all with analog-ecosystem workarounds. Highest risk: multi-unit symbol extraction (#1), PCB population parser issues (#5), KICAD_SYMBOL_DIR race (#6). SPICE reward signal limited to analog sub-circuits (#8). |

The SchGen paper provides strong external validation: SKIDL *is* a Code-L1 representation (relative-free, pin-name-based wiring), which SchGen proved achieves 82% valid circuit rate and outperforms both raw KiCad files (32%) and much larger models. Adopting SKIDL as the IR is the right call.

---

## Sources

- [SchGen: PCB Schematic Generation with Semantic-Grounded Code Representations (arXiv:2605.30345)](https://arxiv.org/abs/2605.30345)
- [SchGen Full HTML (arXiv HTML v1)](https://arxiv.org/html/2605.30345v1)
- [SchGen Source Code (GitHub: microsoft/SchGen)](https://github.com/microsoft/SchGen)
- [SKiDL Documentation](https://devboudren.github.io/skidl/)
- [KiCad Symbol Library Format (extends inheritance)](https://dev-docs.kicad.org/en/file-formats/sexpr-symbols/)
