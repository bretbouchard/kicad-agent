# Phase 158: SPICE Pipeline — Execution Plan

**Goal:** A headless, scriptable ngspice simulation pipeline that turns a SKIDL `Circuit` into validated electrical behavior — AC (gain/BW/phase), transient (step response), noise (input/output floor), THD, and Monte Carlo — with structured JSON results that serve as a reward signal for AI training (Phase 159). Zero new dependencies (ngspice 45.2, spicelib 1.5.1, skidl 2.2.3 + InSpice 1.6.3.3 all installed).

**Requirements:** SPICE-01 through SPICE-11 (11 requirements)
**Depends on:** Nothing in v5.0 (independent of Phase 156; runs on any SKIDL Circuit)
**Estimated new code:** ~1,900 lines across 12 modules + curated `.lib` model files + tests

---

## Reference: Requirements → Tasks

| Req | Description | Wave | Primary Task |
|-----|-------------|------|--------------|
| SPICE-01 | skidl → ngspice export (`generate_netlist(tool="spice")`) | 1 | Task 3 |
| SPICE-02 | SPICE models for NE5532, THAT340, DG413, TL072, LM358 | 1 | Task 2 |
| SPICE-03 | AK4619VN marked `UNSIMULATABLE` | 1 | Task 2 |
| SPICE-04 | Testbench: AC analysis (gain, phase, BW) | 2 | Tasks 4, 5 |
| SPICE-05 | Testbench: Transient (step response) | 2 | Tasks 4, 5 |
| SPICE-06 | Testbench: Noise analysis | 2 | Tasks 4, 5 |
| SPICE-07 | Testbench: THD | 2 | Tasks 4, 5 |
| SPICE-08 | Result parser: `.raw` + `.log` → structured JSON | 3 | Tasks 7, 8 |
| SPICE-09 | Regression baselines (store JSON for comparison) | 3 | Task 9 |
| SPICE-10 | Test: simulate mono blade preamp → +18dB, BW > 100kHz | 4 | Task 11 |
| SPICE-11 | Parasitic injection: PCB trace parasitics → re-simulate | 4 | Task 10 |
| (bonus) | SimRewardAdapter for AI training (→ Phase 159 TRAIN-04) | 4 | Task 12 |

---

## Key Design Decisions (from STACK-SPICE.md research)

These decisions are **LOCKED** — they were verified by live execution on ngspice 45.2 / spicelib 1.5.1. Do not re-litigate during implementation.

- **D-S1: ngspice over LTspice.** ngspice runs headless (`-b deck.cir -r out.raw`); LTspice cannot run on this macOS host. ngspice is the v5.0 engine.
- **D-S2: Layer `spice/` alongside `ltspice/`.** Move the engine-agnostic result layer (`sim_commands`, `types`, `raw_reader`) into a new `kicad_agent/spice/` package. Leave `ltspice/` as the `.asc`/`.asy` schematic bridge. Do NOT break v2.0 Phase 11/14 callers — re-export or alias.
- **D-S3: skidl + InSpice for netlist export.** Use `Circuit.generate_netlist(tool="spice")` (→ InSpice `Circuit`). Do NOT hand-write deck generation. Layer stimulus/analysis on top of the skidl-produced netlist.
- **D-S4: Curated model registry + `UNSIMULATABLE` sentinel.** `models/registry.py` maps `lib_id → (model_name, lib_file, pin_map)`. AK4619VN (delta-sigma codec) is explicitly unsimulatable — the testbench generator substitutes an ideal source at its analog pins.
- **D-S5: Two output channels, two parsers.** AC/Tran/DC/MC → `.raw` (binary, via generalized `read_raw`). THD/`.meas` → `.log` (text, via new `log_parser`). Noise requires the `.control/write` idiom to reach `.raw`.
- **D-S6: Monte Carlo via parameter-override spawning.** N independent ngspice processes with `-D` overrides (parallelizable with GRPO batch infra), NOT in-deck `.control repeat` loops. Names are **case-sensitive**: `-D R1VAL` must match `{R1VAL}` exactly.
- **D-S7: Closed-form parasitics in-loop; field solvers offline.** Trace R/L/C from microstrip/stripline formulas (reuse `routing/impedance.py`). ms-scale per net — suitable for GRPO rollout. openEMS reserved for held-out validation.

---

## Target Package Layout

```
src/kicad_agent/spice/
├── __init__.py              # ~30 lines — package marker, re-exports
├── types.py                 # ~120 lines — SimResult, Trace (engine-agnostic, aliased from ltspice)
├── raw_reader.py            # ~120 lines — read_raw(path, dialect=None) with auto-detect (generalized)
├── log_parser.py            # ~150 lines — parse THD/.meas from ngspice .log text
├── analyses.py              # ~250 lines — AcAnalysis, TranAnalysis, NoiseAnalysis, ThdAnalysis, MonteCarlo
├── testbench.py             # ~200 lines — TestbenchBuilder: netlist + stimulus + analysis → .cir
├── ngspice_runner.py        # ~150 lines — run(deck_path) → RunResult(raw_path, log_path, returncode, converged)
├── result_schema.py         # ~200 lines — AcResult, ThdResult, NoiseResult, MonteCarloResult (pydantic)
├── metrics.py               # ~250 lines — gain_db, bandwidth_3db, noise_floor, thd_from_harmonics, mc_yield
├── baselines.py             # ~120 lines — store/load/compare regression baselines as JSON
├── parasitics.py            # ~250 lines — extract trace R/L/C from routed PCB; inject as lumped elements
├── netlist_exporter.py      # ~150 lines — skidl Circuit → InSpice netlist string (with model .lib includes)
└── models/
    ├── __init__.py
    ├── registry.py          # ~150 lines — lib_id → (model_name, lib_file, pin_map); UNSIMULATABLE sentinel
    ├── NE5532.lib           # curated TI macromodel (PSpice → ngspice-compatible)
    ├── TL072.lib            # curated TI macromodel
    ├── LM358.lib            # curated TI macromodel
    ├── DG413.lib            # curated Vishay/Renesas model
    ├── THAT340.lib          # discrete BJT .model cards (BC847/BC857 matched)
    └── README.md            # provenance, license, version for each model file

src/kicad_agent/training/
└── sim_reward_adapter.py    # ~200 lines — SimRewardAdapter mirroring LegibilityRewardAdapter

tests/
├── test_spice_raw_reader.py
├── test_spice_log_parser.py
├── test_spice_analyses.py
├── test_spice_testbench.py
├── test_spice_ngspice_runner.py
├── test_spice_model_registry.py
├── test_spice_netlist_exporter.py
├── test_spice_metrics.py
├── test_spice_baselines.py
├── test_spice_parasitics.py
├── test_sim_reward_adapter.py
└── test_mono_blade_preamp_sim.py   # integration test (SPICE-10)
```

---

## SPICE Model Sourcing Strategy

This is the single biggest gap: the repo has **zero** `.lib`/`.cir`/`.mod` files today (`find analog-ecosystem -iname "*.lib"` → 0 hits). Every complex IC in `parts.py` is modeled as a generic connector with no electrical behavior.

### Per-IC sourcing plan

| IC | Model type | Source | Priority | License/notes |
|----|-----------|--------|----------|---------------|
| **NE5532** | Opamp macromodel (`.SUBCKT`) | Texas Instruments PSpice model (NE5532 PSpice Model, `.lib`) | **P0** — used 5×/channel in EQ gyrators | TI distributes freely; convert to ngspice-compatible (strip PSpice-only directives). Standard 5-pin macromodel: input stage + output stage + pole-zero compensation. |
| **TL072** | Opamp macromodel | TI TL072 PSpice model | **P1** — common jellybean opamp | Same conversion as NE5532. |
| **LM358** | Opamp macromodel | TI/National LM358 PSpice model | **P1** — common jellybean opamp | Single-supply opamp; model has different output stage. |
| **THAT340** | Discrete BJT `.model` cards | BC847 (NPN) + BC857 (PNP) from ngspice's built-in `bjt` models, OR THAT Corp published β/VAF-matched models | **P0** — trivial; transistor array = 4 discrete BJTs | A transistor array is literally 4 BJTs in one package. Use `.model` cards (not `.SUBCKT`). Spec expects V_n ≈ 1 nV/√Hz at 1kHz — verifiable by sim. |
| **DG413** | Analog switch subcircuit | Vishay DG413DY SPICE model, or Renesas DG413 | **P1** — utility switching | Model = 4× controlled-resistor + on-resistance + charge injection. **Pin mapping gotcha**: the KiCad `DG413xY` symbol's pin assignment differs from the Vishay datasheet (see `parts.py` comment). The SPICE model's node order must match the alias table in `registry.py`, not the raw pin numbers. |
| **AK4619VN** | **UNSIMULATABLE** (sentinel) | N/A — black-box stub | **P0** | Delta-sigma codec: mixed-signal, requires digital I2S stimulus + decimation filter = Verilog/AMS problem, not SPICE. The testbench generator substitutes an ideal voltage source at analog pins (ADC input impedance, DAC output buffer). Marked in registry with `UNSIMULATABLE` sentinel. |
| THAT4301 | VCA macromodel | THAT Corp SPICE macromodel | **P2** (deferred) | Complex log-domain gain cell. Not in P0 scope (compressor stage). Stub for now. |
| MCP4728 / MCP4131 / MCP23008 | Ideal stubs | N/A | **P2** | Digital control ICs. Model as ideal voltage source (DAC) / variable resistor (digipot) at analog pins; ignore digital control. |

### Curation process (Task 2)

1. Download manufacturer models from official vendor pages (TI.com, Vishay.com, THATcorp.com). Record the exact URL, model version, and download date in `models/README.md`.
2. Convert PSpice → ngspice-compatible: strip `.PARAM` constructs ngspice doesn't support, rename PSpice-only functions, ensure `.SUBCKT` bodies are complete. Verify each converts by loading in ngspice (`ngspice -b` with a trivial test deck).
3. Store as plain-text `.lib` files under `spice/models/`. These are vendored artifacts (not generated) — commit to git.
4. The `registry.py` maps each KiCad `lib_id` (e.g. `"Amplifier_Operational:NE5532"`) to `(model_name, lib_file, pin_map)` where `pin_map` translates KiCad pin numbers → SPICE node order (inverting/non-inverting/output/+V/-V for opamps).
5. **License:** Manufacturer SPICE models are typically redistributable for design use. The `README.md` records each model's license/terms. If a model is non-redistributable, fall back to a behavioral macromodel (opamp pole-zero approximation) built from the datasheet specs.

---

## Wave-Based Task Breakdown

Each wave's tasks are independent enough to run in parallel within the wave; waves are sequential (Wave N depends on Wave N-1's interfaces). TDD throughout: tests written first (RED), then implementation (GREEN).

---

### Wave 1: Foundation Layer (engine-neutral, no simulation I/O)

**Goal:** Stand up the `spice/` package with the generalized result layer, the model registry, and the netlist exporter. No ngspice execution yet — pure data structures and string generation.

**Depends on:** Nothing (builds on existing `ltspice/` + `parts.py`).

---

#### Task 1: Generalize result layer — `spice/types.py` + `spice/raw_reader.py` (D-S2)

**Requirements touched:** (foundation for SPICE-08)
**Files:** `src/kicad_agent/spice/__init__.py`, `src/kicad_agent/spice/types.py`, `src/kicad_agent/spice/raw_reader.py`, `tests/test_spice_raw_reader.py`

**Behavior (tests):**
- `read_raw(path, dialect="ngspice")` parses an ngspice `.raw` (use a committed fixture: a simple RC lowpass AC sweep `.raw` generated by ngspice — commit it under `tests/fixtures/spice/rc_lowpass_ac.raw`).
- `read_raw(path, dialect="ltspice")` still works for existing LTspice raws (regression — existing `ltspice/raw_reader.py` callers unaffected).
- `read_raw(path, dialect=None)` auto-dects the dialect by sniffing the `Plotname:`/`Title:`/`Program:` header markers (ngspice raws carry `Program: ngspice 45.2`).
- AC traces return complex values (real + imag), not just real floats (LTspice reader casts to float, which loses phase for AC — the ngspice path must preserve complex for gain/phase extraction).
- Path traversal protection preserved (T-11-05 from Phase 11).

**Action:**
1. Create `spice/types.py` — alias `SimResult = SimulationResult` and `Trace = LTspiceTrace` from `ltspice.types` (re-export, don't duplicate). Add a `ComplexTrace` frozen dataclass for AC traces (carries `real`, `imag`, `magnitude`, `magnitude_db`, `phase_deg` tuples). This is the one structural addition vs LTspice.
2. Create `spice/raw_reader.py`:
   ```python
   def read_raw(raw_path, dialect: str | None = None) -> SimulationResult:
       resolved = Path(raw_path).resolve()
       if ".." in Path(raw_path).parts: raise ValueError(...)
       if not resolved.is_file(): raise FileNotFoundError(...)
       if dialect is None:
           dialect = _detect_dialect(resolved)  # sniff header
       raw = RawRead(str(resolved), dialect=dialect, verbose=False)
       # ... extract traces; for AC raws, build ComplexTrace preserving complex values
   ```
3. Update `ltspice/__init__.py` to re-export from `spice/` (backward compat: `from kicad_agent.ltspice import read_raw` still works, now routes through `spice.raw_reader`).
4. Commit ngspice-generated fixtures: `tests/fixtures/spice/rc_lowpass_ac.raw`, `rc_lowpass_tran.raw` (generated once by running ngspice on a trivial deck — these are the golden-parser inputs).

**Done when:**
- ngspice `.raw` parses with correct complex values for AC traces
- LTspice callers unaffected (no regression in `tests/test_ltspice_*`)
- Auto-dialect detection works on both formats

---

#### Task 2: SPICE model registry + `UNSIMULATABLE` sentinel (SPICE-02, SPICE-03)

**Requirements:** SPICE-02 (models for NE5532, THAT340, DG413, TL072, LM358), SPICE-03 (AK4619VN unsimulatable)
**Files:** `src/kicad_agent/spice/models/__init__.py`, `registry.py`, `README.md`, 5 `.lib` files, `tests/test_spice_model_registry.py`

**Behavior (tests):**
- `ModelRegistry.lookup("Amplifier_Operational:NE5532")` returns `ModelEntry(model_name="NE5532", lib_file="NE5532.lib", pin_map={...}, status=ModelStatus.AVAILABLE)`.
- `lookup("Analog_Switch:DG413xY")` returns the DG413 entry with pin_map matching the `parts.py` alias table (not the raw datasheet pin order).
- `lookup("analog:AK4619VN")` returns `ModelEntry(..., status=ModelStatus.UNSIMULATABLE)`.
- `lookup("Device:R")` returns a `ModelStatus.PRIMITIVE` entry (R/C/L are SPICE primitives — no `.lib` needed).
- `available_models()` returns the set of lib_ids with `AVAILABLE` status.
- Each `.lib` file loads in ngspice without error (verified by a smoke test: `ngspice -b` reading the `.lib` with a trivial instantiation deck).
- For THAT340: `.model` cards for BC847 (NPN) and BC857 (PNP) are present and instantiate correctly.

**Action:**
1. Create `spice/models/registry.py`:
   ```python
   class ModelStatus(Enum):
       AVAILABLE = "available"        # has a real .lib model
       UNSIMULATABLE = "unsimulatable" # AK4619VN — substitute ideal source
       PRIMITIVE = "primitive"        # R/C/L/V/I — SPICE builtins
       STUB = "stub"                  # ideal approximation (DAC, digipot)

   @dataclass(frozen=True)
   class ModelEntry:
       lib_id: str            # KiCad lib_id, e.g. "Amplifier_Operational:NE5532"
       model_name: str        # SPICE subckt/model name, e.g. "NE5532"
       lib_file: str | None   # relative path within models/, e.g. "NE5532.lib"
       pin_map: dict[str, str]  # KiCad pin num → SPICE node role (e.g. {"1": "OUT_A", ...})
       status: ModelStatus

   class ModelRegistry:
       _REGISTRY: dict[str, ModelEntry] = { ... }  # hardcoded table
       def lookup(cls, lib_id: str) -> ModelEntry | None
       def available_models(cls) -> set[str]
       def lib_dir(cls) -> Path   # path to the models/ directory
   ```
2. Source and curate the `.lib` files (see "SPICE Model Sourcing Strategy" above). Each file gets a header comment with provenance: source URL, model version, download date, license, and any PSpice→ngspice conversions applied.
3. The `pin_map` for each IC must match the `parts.py` alias table exactly (the aliases in `parts.py` ARE the canonical pin names — the registry maps those to SPICE node order). For NE5532: `OUT_A/INV_A/NONINV_A/VNEG/VPOS` → SPICE opamp nodes.
4. `README.md` documents every model: vendor, version, URL, license, conversion notes.

**Done when:**
- 5 `.lib` files present and ngspice-loadable (NE5532, TL072, LM358, DG413, THAT340 BJT cards)
- AK4619VN returns `UNSIMULATABLE`
- `pin_map` entries match `parts.py` aliases for all ICs
- Smoke test: each model instantiates in a trivial ngspice deck without error

---

#### Task 3: skidl → ngspice netlist exporter (SPICE-01)

**Requirements:** SPICE-01 (`Circuit.generate_netlist(tool="spice")`)
**Files:** `src/kicad_agent/spice/netlist_exporter.py`, `tests/test_spice_netlist_exporter.py`

**Behavior (tests):**
- Given a skidl `Circuit` with an NE5532 opamp (with `.pyspice` attached via the registry), `export_netlist(circuit)` returns a valid SPICE deck string containing `.title`, device lines, and `.lib` includes for the model files.
- Parts without `.pyspice` (KiCad-sourced parts that the registry has a model for) get their model attached automatically by the exporter before calling `generate_netlist(tool="spice")`.
- Parts with `UNSIMULATABLE` status are detected; the exporter raises a clear error (or substitutes an ideal source if a stub is configured — see Task 5).
- The output deck is valid ngspice input (verified by feeding it to `ngspice -b` in a smoke test).
- Pin mapping is SPICE-ordered (opamps use inv/non-inv/out/+V/-V node order), verified against the registry's `pin_map`.

**Action:**
1. Create `spice/netlist_exporter.py`:
   ```python
   def attach_spice_models(circuit: Circuit, registry: ModelRegistry) -> Circuit:
       """Walk circuit.parts, attach .pyspice dict from the registry for each
       part that has a model. Uses skidl's convert_for_spice(part, spice_part, pin_map)
       helper (skidl/tools/spice/spice.py:606) for pin remapping."""
       for part in circuit.parts:
           entry = registry.lookup(part.lib_id)
           if entry is None or entry.status in (PRIMITIVE,):
               continue
           if entry.status == UNSIMULATABLE:
               continue  # handled by testbench stub substitution
           # Attach: part.pyspice = {'lib': SpiceLibrary(registry.lib_dir()),
           #           'model': entry.model_name, 'add': add_subcircuit_to_circuit}
       return circuit

   def export_netlist(circuit: Circuit, title: str = "kicad-agent SPICE deck") -> str:
       """Export skidl Circuit → ngspice deck string via generate_netlist(tool='spice')."""
       circuit = attach_spice_models(circuit, ModelRegistry)
       spice_circuit = circuit.generate_netlist(tool="spice")  # → InSpice Circuit
       return str(spice_circuit)
   ```
2. The exporter uses `skidl.tools.spice.add_subcircuit_to_circuit` for `.SUBCKT` parts (opamps, DG413) and the registry's `pin_map` for the `convert_for_spice` remapping.
3. SpiceLibrary: point to `registry.lib_dir()` so `.lib` includes resolve to the curated files.
4. **Known gap to document:** skidl's `generate_netlist(tool="spice")` skips parts without `.pyspice` with "Part has no SPICE model" error. The exporter's `attach_spice_models` closes this gap for all registry-covered parts. Parts with no registry entry AND no `.pyspice` raise a clear `MissingSpiceModelError` naming the part ref.

**Done when:**
- A skidl Circuit with NE5532 + R/C exports a valid ngspice deck string
- `.lib` includes resolve to the curated model files
- Pin mapping is SPICE-correct (opamp node order)

---

### Wave 2: Simulation Engine (testbench generation + execution)

**Goal:** Generate `.cir` decks for each analysis type and run them through ngspice headlessly.

**Depends on:** Wave 1 (netlist exporter, model registry).

---

#### Task 4: Analysis command types (SPICE-04 through SPICE-07)

**Requirements:** SPICE-04 (AC), SPICE-05 (Transient), SPICE-06 (Noise), SPICE-07 (THD), + Monte Carlo
**Files:** `src/kicad_agent/spice/analyses.py`, `tests/test_spice_analyses.py`

**Behavior (tests):**
- `AcAnalysis(input_node="_in", output_node="out", fstart=10, fstop=100e3, n_per_dec=100).deck_fragment()` returns a string containing the source definition (`Vin _in 0 DC 0 AC 1`) + analysis command (`.ac dec 100 10 100k`) and declares `output_channel = OutputChannel.RAW`.
- `TranAnalysis(input_node="_in", output_node="out", tstep=1e-6, tstop=5e-3, waveform="SINE(0 1 1000)").deck_fragment()` returns transient deck fragment. `output_channel = RAW`.
- `NoiseAnalysis(output_node="out", input_source="Vin", fstart=10, fstop=100e3, n_per_dec=10).deck_fragment()` returns a deck fragment using the `.control/run/write` idiom (NOT plain `.print noise` — that doesn't reliably emit raw). `output_channel = RAW` (via the write block).
- `ThdAnalysis(input_node="_in", output_node="out", fundamental_hz=1000, tstep=1e-6, tstop=5e-3).deck_fragment()` returns a deck with `.four 1k v(out)` and declares `output_channel = OutputChannel.LOG` (THD goes to the log file, not raw).
- `MonteCarlo(analysis=ac, n_runs=100, tolerances={"R1": 0.02, "C1": 0.1}, distribution="gaussian").override_params(run_index=42, rng=Random(42))` returns `{"R1VAL": 980.0, "C1VAL": 1.02e-6}` — the `-D` parameters for run 42. Case-sensitive keys match deck `{R1VAL}`.
- Each analysis type has an `output_channel` attribute (`RAW` or `LOG`) so the runner knows which parser to invoke.

**Action:**
1. Create `spice/analyses.py` with a frozen-dataclass-per-analysis-type pattern, mirroring `ltspice/sim_commands.py`:
   ```python
   class OutputChannel(Enum):
       RAW = "raw"   # binary vectors — parse via raw_reader
       LOG = "log"   # text (THD/.meas) — parse via log_parser

   @dataclass(frozen=True)
   class AcAnalysis:
       input_node: str
       output_node: str
       fstart: float
       fstop: float
       n_per_dec: int = 100
       sweep_type: str = "dec"  # dec | oct | lin
       output_channel: OutputChannel = OutputChannel.RAW

       def deck_fragment(self) -> str:
           return (f"Vin {self.input_node} 0 DC 0 AC 1\n"
                   f".ac {self.sweep_type} {self.n_per_dec} {self.fstart} {self.fstop}\n")

   # ... TranAnalysis, NoiseAnalysis (with .control/write block), ThdAnalysis (.four), MonteCarlo
   ```
2. **Noise deck fragment** uses the verified idiom:
   ```
   .control
     run
     write {raw_path} frequency onoise inoise
   .endc
   ```
   The `{raw_path}` is filled by the testbench builder (Task 5) since it depends on the output directory.
3. **Monte Carlo** does NOT generate an in-deck loop — it generates per-run `-D` parameter overrides (D-S6). The `MonteCarlo` class holds the tolerance spec; `override_params(run_index, rng)` produces the dict for one run. Python controls the RNG (Gaussian/correlated tolerances via numpy).

**Done when:**
- 5 analysis types each emit a valid ngspice deck fragment
- Noise uses `.control/write` idiom (verified against the STACK-SPICE.md finding)
- THD declares `LOG` output channel
- Monte Carlo produces case-correct `-D` override dicts

---

#### Task 5: Testbench builder (SPICE-04 through SPICE-07)

**Requirements:** SPICE-04, SPICE-05, SPICE-06, SPICE-07
**Files:** `src/kicad_agent/spice/testbench.py`, `tests/test_spice_testbench.py`

**Behavior (tests):**
- `TestbenchBuilder(circuit, analysis).build(deck_path)` writes a complete `.cir` file = netlist (from skidl/InSpice) + stimulus + analysis command + `.lib` includes + output directive.
- For `AcAnalysis`, the deck contains: `.title`, the device netlist, `Vin _in 0 DC 0 AC 1`, `.ac dec 100 10 100k`, `.end`.
- For `NoiseAnalysis`, the deck contains the `.control/run/write` block (noise vectors don't reach `-r` raw otherwise).
- For `ThdAnalysis`, the deck contains `.four 1k v(out)`.
- For a circuit containing an `UNSIMULATABLE` part (e.g. AK4619VN), the builder substitutes an ideal source at the part's analog pins and emits a warning (does not crash).
- Output directory is configurable; the builder resolves `{raw_path}` in noise decks to the actual output path.
- `build_monte_carlo(circuit, mc_spec, output_dir)` generates N decks (one per run) with `-D` parameters embedded, OR returns a single deck + a list of override dicts for the runner to spawn.

**Action:**
1. Create `spice/testbench.py`:
   ```python
   @dataclass(frozen=True)
   class TestbenchBuilder:
       circuit: Circuit
       analysis: Analysis  # AcAnalysis | TranAnalysis | NoiseAnalysis | ThdAnalysis
       title: str = "kicad-agent testbench"
       output_dir: Path = Path.cwd()

       def build(self, deck_path: Path | None = None) -> str:
           netlist = export_netlist(self.circuit)  # Wave 1 Task 3
           fragment = self.analysis.deck_fragment()
           # Resolve {raw_path} for noise decks
           # Combine: title + netlist + fragment + .lib includes + .end
           deck = f".title {self.title}\n{netlist}\n{fragment}\n.end\n"
           if deck_path:
               deck_path.write_text(deck)
           return deck
   ```
2. **UNSIMULATABLE handling:** before building, scan `circuit.parts` for UNSIMULATABLE entries. For each, replace the part with an ideal source/termination at its analog pins. For AK4619VN: terminate ADC inputs with the documented input impedance, replace DAC outputs with ideal voltage sources. Emit a warning log line.
3. **Monte Carlo:** `build_monte_carlo(circuit, mc: MonteCarlo, output_dir)` generates the base deck once (with `{R1VAL}` placeholders) and returns `(base_deck, override_dicts)` for N runs. The runner (Task 6) spawns N ngspice processes.

**Done when:**
- 4 analysis types each produce a runnable `.cir` deck
- Noise deck contains the `.control/write` idiom
- THD deck contains `.four`
- UNSIMULATABLE parts degrade to ideal stubs without crashing

---

#### Task 6: ngspice runner (batch execution)

**Requirements:** (enables SPICE-08, SPICE-09)
**Files:** `src/kicad_agent/spice/ngspice_runner.py`, `tests/test_spice_ngspice_runner.py`

**Behavior (tests):**
- `run_ngspice(deck_path)` executes `ngspice -b deck.cir -r out.raw` and returns `RunResult(raw_path, log_path, returncode, converged)`.
- Captures both stdout and stderr to a `.log` file alongside the `.raw`.
- `converged` is `True` when returncode == 0 AND no "TRAN: time step too small" / "timestep too small" / "GMIN stepping failed" / "singular matrix" errors in the log.
- Timeout configurable (default 30s per run; Monte Carlo runs share the per-run limit).
- For Monte Carlo: `run_monte_carlo(base_deck, override_dicts, output_dir)` spawns N independent ngspice processes (parallelizable via `concurrent.futures.ProcessPoolExecutor`), each with `-D` overrides, returns a list of `RunResult`.
- ngspice binary is discovered via `NGspiceSimulator._spice_exe_paths` (spicelib) or falls back to `/usr/local/bin/ngspice`.

**Action:**
1. Create `spice/ngspice_runner.py`:
   ```python
   @dataclass(frozen=True)
   class RunResult:
       raw_path: Path | None
       log_path: Path
       returncode: int
       converged: bool
       runtime_seconds: float

   _CONVERGENCE_ERRORS = re.compile(
       r"timestep too small|GMIN stepping failed|singular matrix|"
       r"could not converge|TRAN: trouble", re.IGNORECASE)

   def run_ngspice(deck_path: Path, raw_path: Path | None = None,
                   timeout: float = 30.0) -> RunResult:
       """Run ngspice in batch mode on a .cir deck."""
       # subprocess.run(["ngspice", "-b", str(deck_path), "-r", str(raw_path)],
       #                capture_output=True, timeout=timeout)
       # write stderr → log_path; check convergence via regex on log

   def run_monte_carlo(base_deck: str, override_dicts: list[dict],
                       output_dir: Path, n_workers: int = 4) -> list[RunResult]:
       """Spawn N ngspice processes with -D overrides, parallel."""
       # Each run: write deck with {R1VAL}→value substitutions (or pass -D),
       #           ngspice -b deck_runN.cir -r runN.raw
       # Use ProcessPoolExecutor for parallelism
   ```
2. Use direct `subprocess.run` (not spicelib's `NGspiceSimulator`) for simplicity and control over the raw/log paths. spicelib's simulator is available as a fallback if direct subprocess has issues.
3. Monte Carlo parallelism via `concurrent.futures.ProcessPoolExecutor` — composes with GRPO batch infra (D-S6).

**Done when:**
- A valid deck runs to completion and produces a parseable `.raw` + `.log`
- Convergence detection correctly flags a deliberately-broken deck
- Monte Carlo spawns N parallel runs and returns N results

---

### Wave 3: Results & Metrics

**Goal:** Parse simulation outputs into structured JSON and compute the electrical metrics that feed the reward signal.

**Depends on:** Wave 2 (runner produces `.raw` + `.log`).

---

#### Task 7: Log parser — THD/`.meas` from ngspice `.log` (SPICE-08)

**Requirements:** SPICE-08 (THD parse)
**Files:** `src/kicad_agent/spice/log_parser.py`, `tests/test_spice_log_parser.py`

**Behavior (tests):**
- `parse_thd_log(log_text)` returns `ThdParse(thd_percent=0.58, harmonics=[Harmonic(n=1, freq=1000, magnitude=0.99, phase=0.0, norm_mag=1.0), ...])`.
- Parses the "Fourier analysis for v(out)" block: `THD: X%` via `re.search(r'THD:\s*([\d.eE+-]+)\s*%', log)`.
- Parses the per-harmonic table: `re.findall(r'^\s*(\d+)\s+([\d.eE+-]+)\s+([\d.eE+-]+)', log, re.M)`.
- Returns `thd_percent = None` if no THD block found (graceful — not all decks have `.four`).
- `parse_meas_log(log_text)` parses `.meas` results (e.g. `meas1: ... = 1.234e-3`).
- Test with a real ngspice THD log fixture (committed under `tests/fixtures/spice/thd_output.log`).

**Action:**
1. Create `spice/log_parser.py` — pure regex parsing, no spicelib dependency. This is the text-channel counterpart to `raw_reader.py` (the binary channel), per D-S5.
2. The parser is deliberately tolerant: missing THD block → `None`, partial harmonic table → truncated list. Never raise on parse failure (return what you can + a `parse_warnings` list).

**Done when:**
- Real ngspice THD log parses to correct `thd_percent` + harmonic list
- Graceful on missing/malformed data

---

#### Task 8: Result schemas + metric extraction (SPICE-08)

**Requirements:** SPICE-08 (gain, BW, noise, THD → structured JSON)
**Files:** `src/kicad_agent/spice/result_schema.py`, `src/kicad_agent/spice/metrics.py`, `tests/test_spice_metrics.py`

**Behavior (tests):**
- `AcResult` (pydantic): contains `analysis_type`, `engine`, `engine_version`, `converged`, `sweep`, `traces` (frequency + complex v(out)), `metrics` (gain_db_at_1khz, bandwidth_3db_hz, gain_margin_db, phase_margin_deg). `.model_dump_json()` produces the JSON schema from STACK-SPICE.md Q4.
- `ThdResult`: `fundamental_hz`, `thd_percent`, `harmonics` list.
- `NoiseResult`: `noise_floor_v_per_sqrt_hz` (at target freq), `integrated_noise_vrms`, `ein_dbu`.
- `MonteCarloResult`: `n_runs`, `metric`, `distribution` (mean/std/min/max/p95/yield_pct).
- `extract_ac_metrics(sim_result, target_freq_hz=1000)` → dict with `gain_db_at_1khz`, `bandwidth_3db_hz` (find -3dB crossing from peak), `phase_margin_deg`.
- `extract_noise_metrics(sim_result, freq_hz=1000)` → dict with spot noise + integrated noise (∫ via `np.trapz`).
- `thd_from_harmonics(harmonics)` → `sqrt(sum(H2..Hn)^2) / H1` (cross-check against ngspice's printed THD).
- `monte_carlo_yield(per_run_values, spec_lo, spec_hi)` → `n_within_spec / n_runs`.

**Action:**
1. Create `spice/result_schema.py` with pydantic models matching the JSON schema in STACK-SPICE.md Q4. Each model has `model_config = ConfigDict(frozen=True)`.
2. Create `spice/metrics.py` with numpy-based extraction functions. These are pure functions (numpy in, dict out) — no I/O.
3. **EIN computation:** `ein_dbu = 20*log10(integrated_noise_vrms / 0.7746)` (0.7746V = 0 dBu reference).
4. **Bandwidth:** find the highest frequency where `mag_db >= peak_db - 3`. Handle monotonic and peaked responses.

**Done when:**
- 4 result schemas serialize to the documented JSON shape
- Metric extraction produces correct values on the RC lowpass fixture (known: gain ≈ 0dB at DC, -3dB at f_c = 1/(2πRC))
- EIN computation correct against the CIRCUIT-DESIGN.md target (-128 dBu)

---

#### Task 9: Regression baselines (SPICE-09)

**Requirements:** SPICE-09 (store simulation results as JSON for comparison)
**Files:** `src/kicad_agent/spice/baselines.py`, `tests/test_spice_baselines.py`, `tests/fixtures/spice/baselines/`

**Behavior (tests):**
- `store_baseline(result, name, baselines_dir)` writes a JSON file (e.g. `mono_blade_ac_baseline.json`) containing the result schema + a timestamp + a content hash.
- `load_baseline(name, baselines_dir)` returns the stored result.
- `compare_to_baseline(current_result, baseline_result, tolerances)` returns a `ComparisonReport` with per-metric pass/fail + delta. E.g. `gain_db` within ±0.5dB, `bandwidth_3db_hz` within ±5%, `thd_percent` within ±0.1%.
- `RegressionError` raised (or flagged) when a metric exceeds tolerance — the signal for CI regression detection.
- Baseline files are committed to git under `tests/fixtures/spice/baselines/` — they are the golden reference for regression testing.

**Action:**
1. Create `spice/baselines.py` with `store_baseline`, `load_baseline`, `compare_to_baseline`.
2. Default tolerances per metric type (configurable):
   - `gain_db`: ±0.5 dB
   - `bandwidth_3db_hz`: ±5%
   - `noise_floor`: ±10%
   - `thd_percent`: ±0.1% absolute
3. The baseline is a snapshot of the "known-good" simulation. When a code change shifts the simulation result beyond tolerance, `compare_to_baseline` flags it — the developer either fixes the regression or updates the baseline (explicit `update_baseline(name)` call).

**Done when:**
- Baselines store/load correctly as JSON
- Comparison detects a deliberately-shifted metric
- Default tolerances documented and configurable

---

### Wave 4: Integration, Parasitics & Reward Signal

**Goal:** Wire the pipeline end-to-end on the real mono blade preamp (SPICE-10), add parasitic injection (SPICE-11), and produce the reward adapter for Phase 159.

**Depends on:** Waves 1-3 (full pipeline).

---

#### Task 10: Parasitic injection (SPICE-11)

**Requirements:** SPICE-11 (PCB trace parasitics → re-simulate → measure degradation)
**Files:** `src/kicad_agent/spice/parasitics.py`, `tests/test_spice_parasitics.py`

**Behavior (tests):**
- `extract_trace_parasitics(pcb_ir_or_paths)` computes per-net lumped R/L/C from the routed PCB geometry: trace resistance `R = ρ_Cu * length / (width * thickness)`, trace inductance via microstrip/stripline closed-form (reuse `routing/impedance.py`), coupling capacitance via parallel-plate approximation, via inductance (~1nH/via).
- Returns a `ParasiticNetwork` (list of `ParasiticElement(net_name, node_a, node_b, kind, value)`).
- `inject_parasitics(netlist_str, parasitics)` inserts lumped R/L/C elements into the netlist at trace endpoints (e.g. inserts `Rtrace_SIG_HOT  N001 N002 0.05` between the source and load).
- `simulate_pre_vs_post_route(circuit, pcb_ir, analyses)` runs the full analysis suite on (a) the ideal schematic and (b) the parasitic-injected netlist, returns a `DegradationReport` with per-metric deltas (e.g. `gain_delta_db`, `noise_delta_db`, `thd_delta_percent`).
- The degradation report is the **reward delta** — the physical ground truth that geometry-only signals cannot provide.

**Action:**
1. Create `spice/parasitics.py`:
   ```python
   @dataclass(frozen=True)
   class ParasiticElement:
       net_name: str
       node_a: str
       node_b: str
       kind: str   # "R" | "L" | "C"
       value: float  # ohms, henries, farads

   def extract_trace_parasitics(pcb_paths) -> list[ParasiticElement]:
       """Closed-form parasitic extraction from routed PCB (D-S7).
       Reuses routing/impedance.py for microstrip L, spatial/ for overlap C."""
       # For each net: sum trace lengths × R per length (ρ_Cu * L / (w*t))
       #               microstrip L per length (from impedance.py)
       #               coupling C to adjacent nets (parallel-plate, overlap area × ε)
       # Vias: 1nH each (empirical)

   def inject_parasitics(deck: str, parasitics: list[ParasiticElement]) -> str:
       """Insert lumped parasitic elements into the netlist."""
       # Insert before .ac/.tran/.noise/.four lines
   ```
2. Reuse `routing/impedance.py:microstrip_z0` (not directly, but the same Hammerstad-Jensen / IPC-2141 formulas) for per-unit-length inductance from trace geometry. Reuse `spatial/pcb_model.py` for trace geometry extraction.
3. **Performance (D-S7):** closed-form, ms-scale per net — suitable for in-loop RL. Field solvers (openEMS) explicitly NOT used here (reserved for offline validation).
4. **Caching:** the parasitic network depends only on (netlist, PCB geometry) — hash and memoize for repeated GRPO rollouts.

**Done when:**
- Trace parasitics extracted from a routed PCB fixture
- Injected into a netlist and re-simulated
- Degradation report shows measurable deltas (e.g. noise increases, BW decreases with parasitics)

---

#### Task 11: Mono blade preamp integration test (SPICE-10)

**Requirements:** SPICE-10 (simulate mono blade preamp → verify +18dB gain, BW > 100kHz)
**Files:** `tests/test_mono_blade_preamp_sim.py` (integration test), `tests/fixtures/spice/mono_blade_ac_baseline.json`

**Behavior (integration test):**
- Imports `build_mono_blade.py` from `analog-ecosystem/.../mono-arch/` and builds the skidl Circuit.
- Runs AC analysis on the preamp path (input → THAT340 → output): `gain_db_at_1khz >= 17.5` (target +18dB, tolerance ±0.5dB for model variation).
- Verifies `bandwidth_3db_hz > 100_000` (100 kHz).
- Runs noise analysis: verifies `ein_dbu < -120.0` (target -128 dBu; allow ±8dB tolerance for macromodel vs discrete — the spec value is the design intent).
- Runs THD analysis at 1kHz: verifies `0.0 < thd_percent < 5.0` (the spec targets 0.5-2% "warm" coloration; macromodels may differ — verify it's non-zero and reasonable, not exact).
- Stores the result as the regression baseline under `tests/fixtures/spice/mono_blade_ac_baseline.json`.
- **Handles partial simulatability:** the mono blade contains DG413 switches, THAT4301 (stub), and ideal terminations. The test simulates only the analog signal path (preamp → EQ → output buffer), with unsimulatable parts stubbed.

**Action:**
1. This is primarily an integration test — it exercises the full Wave 1-3 pipeline on a real circuit.
2. The test may need to extract a sub-circuit (the preamp path alone) rather than simulating the full 116-part blade, because (a) the full blade has unsimulatable parts (AK4619VN is on the base board, but THAT4301 compressor is a stub), and (b) AC analysis of the full signal chain is more meaningful than simulating disconnected sub-blocks.
3. **Sub-circuit extraction:** build a dedicated test circuit (a simplified preamp: THAT340 differential pair → NE5532 buffer) that uses the same parts.py wrappers. This isolates the analog path for simulation while remaining representative.
4. If the full mono blade sim is too slow or has convergence issues (common with BJT macromodels), document the fallback: simulate the NE5532-based stages (EQ, output buffer) which use well-behaved opamp macromodels, and verify the THAT340 stage separately with discrete BJT models.
5. Store the baseline JSON; subsequent runs compare against it (SPICE-09 regression).

**Done when:**
- Mono blade preamp (or representative sub-circuit) simulates and meets spec targets:
  - Gain ≥ +17.5 dB at 1 kHz
  - BW > 100 kHz
  - EIN < -120 dBu (macromodel tolerance)
  - THD in (0%, 5%) range
- Baseline JSON committed
- Test passes in CI (with ngspice installed)

---

#### Task 12: SimRewardAdapter (→ Phase 159 TRAIN-04)

**Requirements:** (bonus — bridges to Phase 159 TRAIN-04: SPICE degradation as reward signal)
**Files:** `src/kicad_agent/training/sim_reward_adapter.py`, `tests/test_sim_reward_adapter.py`

**Behavior (tests):**
- `SimRewardAdapter` mirrors `LegibilityRewardAdapter` (frozen dataclass, `from_config()` classmethod, `compute()` method).
- `compute(pre_route_result, post_route_result)` → `SimRewardSignal` with per-component reward terms:
  - `reward_noise = clip(1 - (EIN_post - EIN_pre) / delta_max, 0, 1)` — noise degradation
  - `reward_gain = clip(1 - |gain_post - gain_pre| / tol, 0, 1)` — gain stability
  - `reward_thd = clip((thd_post - thd_lo) / (thd_hi - thd_lo), 0, 1)` — THD windowed target (NOT minimize-to-zero; the spec wants 0.5-2% "warm" coloration)
  - `reward_yield = n_within_spec / n_runs` — Monte Carlo yield
- `combine()` produces a weighted total per `SimRewardWeights` (defaults from CIRCUIT-DESIGN.md targets; weights sum to 1.0, validated).
- Graceful fallback: if a sim fails to converge, return a **penalty** reward (not zero) so the model learns the layout is suspect — per STACK-SPICE.md "Fall back gracefully."
- `from_config(config)` parses a `training.sim_reward` block from config.json (weights, tolerances, spec targets).

**Action:**
1. Create `training/sim_reward_adapter.py` following the `LegibilityRewardAdapter` pattern:
   ```python
   @dataclass(frozen=True)
   class SimRewardWeights:
       noise: float = 0.30
       gain: float = 0.25
       thd: float = 0.15
       yield_: float = 0.30
       def __post_init__(self):
           total = self.noise + self.gain + self.thd + self.yield_
           if abs(total - 1.0) > 1e-6: raise ValueError(...)

   @dataclass(frozen=True)
   class SimRewardAdapter:
       weights: SimRewardWeights = field(default_factory=SimRewardWeights)
       spec_targets: SpecTargets = field(default_factory=SpecTargets)  # from CIRCUIT-DESIGN.md
       delta_max_ein_db: float = 6.0   # max acceptable EIN degradation
       gain_tol_db: float = 1.0        # max acceptable gain shift
       thd_window: tuple[float, float] = (0.5, 2.0)  # spec THD range (%)

       def compute(self, pre: AcResult | None, post: AcResult | None,
                   converged: bool = True) -> SimRewardSignal:
           if not converged or post is None:
               return SimRewardSignal(sim_score=0.1, ...)  # penalty, not zero
           # compute per-term rewards, combine via weights

       @classmethod
       def from_config(cls, config: Mapping) -> "SimRewardAdapter": ...
   ```
2. **Spec targets** (from CIRCUIT-DESIGN.md, verified): EIN ≈ -128 dBu (§4.3), gain +18dB (§4.3), THD 0.5-2% windowed (§7), EQ ±18dB (§8), rail noise <50µVrms (§9.3).
3. The adapter is **pure compute** — it takes result objects (from Wave 3) and returns reward terms. It does NOT run simulations itself (the caller — GRPO rollout — does that via the runner). This separation mirrors how `LegibilityRewardAdapter` takes `CritiqueResult` rather than calling the critic.
4. **Integration with BoardChainReward (Phase 159):** the `sim_score` folds into `BoardChainReward` as a new component alongside `format_score`/`quality_score`/`accuracy_score`. This wiring is Phase 159's job; Phase 158 only ships the adapter.

**Done when:**
- SimRewardAdapter computes reward terms from pre/post route results
- Convergence failure → penalty reward (not zero)
- Weights validated to sum to 1.0
- Spec targets match CIRCUIT-DESIGN.md
- Pattern matches LegibilityRewardAdapter (frozen, from_config, combine)

---

## Test Strategy

### Unit tests (Waves 1-3)
Every module gets a dedicated test file (see package layout). Tests use committed fixtures under `tests/fixtures/spice/`:
- `rc_lowpass_ac.raw`, `rc_lowpass_tran.raw` — ngspice-generated golden raws for parser tests (known values: gain, BW, phase).
- `thd_output.log` — real ngspice THD log for parser test.
- `baselines/*.json` — regression baselines.

### Integration test (Wave 4, Task 11 — SPICE-10)
The mono blade preamp simulation is the canonical integration test. It exercises the full pipeline: skidl Circuit → netlist export → testbench generation → ngspice execution → result parsing → metric extraction → spec verification.

**Simplification strategy:** the full 116-part mono blade is too complex for a single AC sweep (multiple signal paths, unsimulatable parts). The integration test extracts the **preamp signal path** (input → impedance select → HPF → THAT340 preamp → output) as a representative sub-circuit. This:
1. Uses the same `parts.py` wrappers (NE5532, THAT340, DG413, R, C).
2. Exercises all 4 analysis types on a real circuit.
3. Has known spec targets (+18dB gain, BW > 100kHz, EIN < -128 dBu).
4. Is fast enough for CI (< 30s per analysis).

If the full preamp path has convergence issues (BJT macromodels can be finicky), the fallback is to verify the NE5532-based stages (output buffer, EQ) with opamp macromodels, and the THAT340 stage with discrete BJT `.model` cards separately.

### CI considerations
- ngspice must be installed on the CI runner (`brew install ngspice` on macOS, `apt install ngspice` on Linux).
- Tests that require ngspice are marked `@pytest.mark.requires_ngspice` and skipped if `ngspice` is not on PATH.
- The mono blade integration test is `@pytest.mark.integration` (slower, runs in a separate CI stage).

---

## Dependency & Import Graph

```
Wave 1 (no deps):
  spice/types.py         ← ltspice/types.py (re-export + ComplexTrace)
  spice/models/registry  ← (standalone)
  spice/netlist_exporter ← skidl, InSpice, models/registry

Wave 2 (deps Wave 1):
  spice/analyses         ← (standalone dataclasses)
  spice/testbench        ← netlist_exporter, analyses
  spice/ngspice_runner   ← subprocess

Wave 3 (deps Wave 2):
  spice/raw_reader       ← spicelib.RawRead, types (Wave 1)
  spice/log_parser       ← re (standalone)
  spice/result_schema    ← pydantic
  spice/metrics          ← numpy, raw_reader, log_parser
  spice/baselines        ← result_schema

Wave 4 (deps Waves 1-3):
  spice/parasitics       ← routing/impedance, spatial/pcb_model, netlist_exporter
  training/sim_reward_adapter ← spice/result_schema, spice/metrics, spice/parasitics
```

`ltspice/__init__.py` re-exports `read_raw` from `spice/` (backward compat). No v2.0 caller breaks.

---

## pyproject.toml Changes

```toml
[project.optional-dependencies]
spice = [
    "skidl>=2.0",      # already installed transitively; make explicit for the spice export path
    "InSpice>=1.6",    # PySpice fork; skidl's SPICE tool requires it (NOT PySpice — not installed)
]
```

`spicelib>=1.5.1` is already a core dependency (line 24 of pyproject.toml). No new solver binary — ngspice is installed system-wide (`/usr/local/bin/ngspice`). Document the ngspice requirement in the README (not a pip dependency — it's a system binary).

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| NE5532/TI model doesn't convert cleanly to ngspice | MEDIUM | HIGH (blocks SPICE-02, SPICE-10) | Fall back to a behavioral opamp macromodel (pole-zero approximation from datasheet GBW/slew rate). Document the substitution. |
| THAT340 discrete BJT model gives wrong noise floor | LOW | MEDIUM | The spec computes expected noise (1 nV/√Hz); if sim differs, tune the BJT model parameters (β, VAF, RB) to match. Discrete models are well-understood. |
| Mono blade full-chain sim doesn't converge | MEDIUM | MEDIUM | Simulate sub-circuits (preamp path alone). BJT macromodels at sharp transients are known to diverge — use `.options reltol=0.01` / `gmin stepping`. |
| DG413 pin map mismatch (KiCad symbol vs datasheet) | HIGH | MEDIUM | The `parts.py` comment already flags this. The registry `pin_map` follows the `parts.py` aliases (canonical), verified by a unit test that checks switch continuity in sim. |
| ngspice not on CI runner | LOW | HIGH (blocks all sim tests) | `@pytest.mark.requires_ngspice` skip guard. Document install in CI workflow. |
| InSpice API drift from PySpice | LOW | MEDIUM | skidl targets the PySpice API; InSpice is a drop-in fork. Verified importable in STACK-SPICE.md. If a specific method differs, wrap it in the exporter. |

---

## Success Criteria Mapping (ROADMAP.md Phase 158)

| # | Success Criterion | Achieved By |
|---|-------------------|-------------|
| 1 | SKIDL Circuit exports to ngspice deck and runs headless | Tasks 3, 5, 6 (export → deck → `ngspice -b`) |
| 2 | Curated models for NE5532/THAT340/DG413/TL072/LM358; AK4619VN UNSIMULATABLE | Task 2 (registry + 5 `.lib` files + sentinel) |
| 3 | Four testbench generators (AC, transient, noise, THD); noise uses `.control/write`, THD parses from `.log` | Tasks 4, 5 (analyses + testbench builder) |
| 4 | Result parser converts `.raw` + `.log` → structured JSON; regression baselines stored | Tasks 1, 7, 8, 9 (raw_reader, log_parser, schemas, baselines) |
| 5 | Mono blade preamp verifies +18dB / BW>100kHz; parasitic injection measures degradation | Tasks 10, 11 (parasitics + integration test) + Task 12 (reward adapter) |

---

## Execution Order Summary

```
Wave 1 (parallel within wave):
  Task 1: types.py + raw_reader.py (generalized)
  Task 2: models/registry.py + 5 .lib files + UNSIMULATABLE
  Task 3: netlist_exporter.py (skidl → ngspice)

Wave 2 (sequential after Wave 1):
  Task 4: analyses.py (5 analysis types)
  Task 5: testbench.py (deck builder)
  Task 6: ngspice_runner.py (batch exec)

Wave 3 (sequential after Wave 2):
  Task 7: log_parser.py (THD from .log)
  Task 8: result_schema.py + metrics.py
  Task 9: baselines.py

Wave 4 (sequential after Wave 3):
  Task 10: parasitics.py (closed-form trace R/L/C)
  Task 11: test_mono_blade_preamp_sim.py (SPICE-10 integration)
  Task 12: sim_reward_adapter.py (→ Phase 159)
```

**Total:** 12 tasks, 4 waves, ~1,900 lines new code + 5 curated `.lib` files + 12 test files + integration test. Zero new dependencies.
