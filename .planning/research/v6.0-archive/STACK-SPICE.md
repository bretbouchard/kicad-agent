# Technology Stack -- v5.0 SPICE Simulation Pipeline

**Project:** volta -- SPICE testbench generation, simulation, and reward-signal extraction
**Milestone:** v5.0 (SPICE simulation pipeline)
**Researched:** 2026-07-03
**Confidence:** HIGH (all claims verified by live execution: ngspice 45.2 runs, spicelib parses output, skidl/InSpice export path confirmed)

---

## Executive Summary

The v5.0 SPICE pipeline needs **zero new top-level dependencies**. The simulation engine (ngspice 45.2), the result parser (spicelib 1.5.1, already a core dep for the v2.0 LTspice module), and the circuit-to-netlist exporter (skidl 2.2.3 + InSpice 1.6.3.3) are all already installed and working. The entire pipeline runs on the open-source ngspice -- **no LTspice/Wine installation required**, unlike the existing Phase 11 module which can *export* `.asc` files but cannot *run* LTspice simulations on this macOS host.

The real work for v5.0 is threefold: (1) build a **testbench generator** that emits ngspice `.cir` decks (AC/transient/noise/THD/Monte-Carlo), (2) generalize the existing `raw_reader.py` from LTspice-only to LTspice+ngspice, and (3) wire simulation outputs into a **reward signal** (pre-routing vs post-routing metric delta) that plugs into the existing GRPO training infrastructure (`training/board_reward.py`, `training/grpo_*`).

The single biggest **gap is SPICE models for the custom ICs**. The repo has zero `.lib`/`.cir`/`.mod` files, and `parts.py` models every complex IC (THAT4301, AK4619VN, XMOS, MCP4728) as a generic *connector* with no electrical behavior. v5.0 must either curate manufacturer SPICE models or build behavioral macromodels for the analog ICs (NE5532, DG413, THAT340). The AK4619VN codec is fundamentally **not SPICE-simulatable** (mixed-signal, requires digital stimulus) -- the pipeline must mark it as a behavioral stub.

---

## Installed Stack (Verified Live)

| Technology | Version | Status | Evidence |
|------------|---------|--------|----------|
| **ngspice** | 45.2 | Installed, runs in batch | `ngspice --version` → "ngspice-45.2 : Circuit level simulation program, Compiled with KLU Direct Linear Solver". Batch sim of RC lowpass produced valid `.raw`. |
| **spicelib** | 1.5.1 | Core dep (since v2.0) | `RawRead`, `AscEditor`, `NGspiceSimulator`, `SimRunner` all importable. Already used by `raw_reader.py`, `asc_parser.py`, `net_graph.py`. |
| **skidl** | 2.2.3 | Core dep (analog-ecosystem) | `Circuit.generate_netlist()` + `tools/spice/spice.py` → PySpice/InSpice `Circuit`. |
| **InSpice** | 1.6.3.3 | Installed | PySpice fork; skidl's SPICE tool imports `InSpice.Spice.Netlist.Circuit`. **Replaces** PySpice (which is NOT installed: `ModuleNotFoundError: No module named 'PySpice'`). |
| **networkx** | 3.6.1 | Core dep | Used by `net_graph.py`; reused for testbench node bookkeeping. |
| **numpy** | 1.26.4 | Core dep | Frequency-array math, gain/phase extraction from raw vectors. |
| PySpice | -- | **NOT installed** | `import PySpice` → ModuleNotFoundError. Do not depend on it; depend on InSpice (skidl's chosen fork). |

**ngspice binary location:** `/usr/local/bin/ngspice` (found by `NGspiceSimulator._spice_exe_paths`).

---

## Research Question 6 First: LTspice Module ↔ ngspice Relationship

This is the architectural keystone, so it comes first.

### What the existing `volta/ltspice/` module actually is

The module is **misleadingly named**: it is really a *KiCad-schematic ↔ SPICE-schematic bridge*, not an LTspice simulator. Of its 7 files:

| File | LTspice-specific? | Reusable for ngspice? |
|------|-------------------|------------------------|
| `sim_commands.py` | **No** -- parses `.tran/.ac/.dc/.noise/.op`, which is **standard SPICE syntax** (ngspice uses identical keywords). The `parse_eng_value()` SI-prefix parser is generic. | **YES, verbatim.** `serialize_sim_command()` emits `.ac dec 100 10 100k` -- valid ngspice. |
| `types.py` | **No** -- `SimulationResult`, `LTspiceTrace` are simulation-result containers, named for LTspice only by accident. | **YES.** Rename to `SimResult`/`Trace` or alias; structure is engine-agnostic. |
| `raw_reader.py` | **Partly** -- calls `RawRead(path, dialect="ltspice")`. The dialect is a one-arg change. | **YES, with `dialect="ngspice"`.** spicelib parses both formats (verified: ngspice `.raw` parses cleanly). |
| `asc_parser.py` | **Yes** -- parses LTspice `.asc` schematic geometry via `AscEditor`. | No -- ngspice consumes netlists (`.cir`/`.net`), not schematics. |
| `asc_writer.py` | **Yes** -- writes `.asc` from KiCad schematic. | No -- ngspice path writes `.cir`, not `.asc`. |
| `symbol_mapper.py` | **Yes** -- KiCad libId → LTspice `.asy` symbol name. | No -- ngspice has no symbol concept; it needs SPICE primitive types (R/C/X/...). |
| `net_graph.py` | **Yes** -- derives connectivity from LTspice wire geometry + `.asy` pin offsets. | No -- ngspice netlists already declare connectivity (node names per device line). |

### Decision: layer ngspice *alongside*, do not fork

The three "reusable" files (`sim_commands.py`, `types.py`, `raw_reader.py`) form a **simulation-command + simulation-result** layer that is engine-agnostic. The four `.asc`/`.asy` files are an **LTspice-schematic-bridge** layer. v5.0 should:

1. **Extract a new `spice/` package** (e.g. `volta/spice/`) holding the engine-agnostic pieces: `sim_commands.py` (move or re-export), `types.py` (move or re-export), and a **generalized `raw_reader.py`** that takes an optional `dialect` (`"ltspice"` | `"ngspice"`, default auto-detect).
2. **Keep `volta/ltspice/`** as the `.asc`/`.asy` schematic bridge, importing from the new `spice/` package. This avoids breaking the v2.0 Phase 11/14 callers.
3. **Add `volta/spice/ngspice_runner.py`** -- the new ngspice batch-execution + testbench-generation layer (the v5.0 work).

This mirrors how spicelib itself is organized: one `raw/raw_read.py` reads *both* dialects, separate `simulators/{ltspice,ngspice,qspice,xyce}_simulator.py` run *each* engine.

### The one asymmetry that matters

The LTspice module **cannot run LTspice** on this host (no LTspice.app, no Wine). It only *writes* `.asc` files for a human to open in LTspice, and *reads* `.raw` files a human produced. The ngspice module, by contrast, **runs end-to-end with no human in the loop** (`ngspice -b deck.cir -r out.raw`). This is exactly what makes ngspice suitable as an AI reward signal: it is scriptable, deterministic, and headless.

---

## Research Question 1: skidl → SPICE Export

### Mechanism (read from `skidl/tools/spice/spice.py:293`)

`Circuit.generate_netlist(tool="spice")` calls `gen_netlist()`, which:

1. Calls `self.merge_nets()` (SPICE needs single-node nets).
2. Creates an **InSpice `Circuit`** (imported as `PySpiceCircuit` -- skidl targets the PySpice API, and InSpice is a drop-in fork).
3. For each part, looks up `part.pyspice` -- a dict with keys `lib`, `lib_path`, `lib_section`, `model`, `add` (the add-function). **KiCad-sourced parts do NOT have `.pyspice` set by default** -- they are skipped with the error *"Part has no SPICE model: {ref}"*.
4. Parts that *do* have `.pyspice` are added via their `add` function (`add_part_to_circuit` for primitives, `add_subcircuit_to_circuit` for `.SUBCKT` parts, `add_xspice_to_circuit` for XSPICE).

### Output format

The return value is an **InSpice `Circuit` object**, not a string. To get a netlist:
- `str(circuit)` → SPICE deck text (`.title`, device lines, `.ends`, `.lib` includes).
- `circuit.simulator('ngspice')` → an InSpice simulator handle that can `.ac()`, `.transient()`, `.noise()` directly (InSpice wraps ngspice under the hood).

### skidl's bundled SPICE libraries

skidl ships two SKiDL-format libraries that *do* carry `.pyspice` metadata:
- `tools/skidl/libs/Simulation_SPICE_sklib.py` -- KiCad-style `Simulation_SPICE` parts (voltage/current sources, grounds) pre-wired for SPICE.
- `tools/skidl/libs/pyspice_sklib.py` -- PySpice-native parts.

These are how you build a *simulation-only* circuit in skidl (sources + loads + the device-under-test), distinct from the *board* circuit (which is for layout).

### Limitations (the ones that bite for this project)

1. **Custom ICs need SPICE models attached.** `parts.py`'s `NE5532()`, `DG413()`, etc. create KiCad `Part` objects with footprints but no `.pyspice`. To simulate them you must either (a) attach a subcircuit: `part.pyspice = {'lib': SpiceLibrary('/path'), 'model': 'NE5532', 'add': add_subcircuit_to_circuit}`, or (b) use `XspiceModel`/`DeviceModel` for behavioral macromodels, or (c) instantiate SPICE primitives directly.
2. **Pin mapping must be SPICE-ordered.** SPICE opamps use inverting/non-inverting/output/+V/-V node order; KiCad `NE5532` uses 1=OUT_A, 2=INV_A... The `convert_for_spice(part, spice_part, pin_map)` helper in `spice.py:606` remaps, but the `pin_map` must be supplied per part. This is the same semantic-alias problem `parts.py` already solves for KiCad -- v5.0 needs a parallel SPICE-alias table.
3. **No automatic parasitic extraction.** skidl emits the *schematic* netlist. Post-routing parasitics (trace R/L/C, coupling) must be injected separately -- see Question 5.
4. **Hierarchy flattens.** `.SUBCKT` parts are emitted as `X`-calls referencing `.lib` includes; the subcircuit body comes from the model file, not skidl.

---

## Research Question 2: SPICE Models for Custom ICs

### Current state in the repo

**No SPICE models exist.** Verified:
- `find analog-ecosystem -iname "*.lib" -o -iname "*.spice" -o -iname "*.cir" -o -iname "*.mod"` → zero hits.
- `grep -rli "subckt\|\.model" analog-ecosystem/hardware --include=*.py` → only matches in build scripts referencing "skidl", not actual models.
- `parts.py` instantiates every complex IC as a **generic connector** (`Conn_01x16`, `Conn_01x32`, `Conn_01x60`) with the comment *"Modeled with generic connector. Swap to real symbol in KiCad GUI."* These have **no electrical behavior** -- they are pure connectivity stubs.

### Per-IC assessment

| IC | Role | SPICE model feasibility | Source / approach |
|----|------|------------------------|-------------------|
| **NE5532** | Dual opamp (EQ, buffers) | **HIGH** -- well-modelled | TI publishes a PSpice/SPICE macromodel (`.SUBCKT NE5532 ...`). Standard 5-pin opamp macromodel (input stage + output stage + pole-zero compensation). ngspice-compatible. Drop into a `models/NE5532.lib`. The CIRCUIT-DESIGN spec uses 5× NE5532 per channel for the EQ gyrators -- this is the highest-value model to obtain. |
| **DG413** | Quad SPST analog switch (impedance/HPF/pad/phase) | **MEDIUM** -- needs subckt | Vishay/Renesas publish DG413 SPICE models. Model = 4× controlled-resistor + on-resistance + charge injection. The spec notes the KiCad `DG413xY` symbol's pin assignment differs from the Vishay datasheet (see `parts.py` comment) -- the SPICE model's node order must match the *alias table*, not the raw pin numbers. |
| **THAT340** | Matched transistor array (Stage 1 preamp, 2×NPN + 2×PNP) | **HIGH** -- discrete BJT models suffice | A transistor array is literally 4 discrete BJTs in one package. Use any low-noise NPN/PNP SPICE model (BC847/BC857 `.model` cards, or THAT Corp's published β/VAF-matched models). The CIRCUIT-DESIGN spec even computes the expected noise: "V_n ≈ 1 nV/√Hz at 1kHz". This is the IC most amenable to verification-by-simulation. |
| **AK4619VN** | 4ch ADC + 4ch DAC codec | **NOT FEASIBLE in SPICE** | Mixed-signal delta-sigma converter. No analog macromodel exists or can be meaningfully built -- simulating it requires digital I2S stimulus + decimation filter, which is a Verilog/AMS problem, not SPICE. **v5.0 must treat the codec as a black-box stub**: terminate its analog pins with the documented input impedance and mark the digital side as `unsimulatable`. The "DAC output buffer" (Section 14 of the spec) *can* be simulated by replacing the codec output with an ideal source. |
| **THAT4301** (in `parts.py`, not the current spec's THAT340) | VCA + RMS detector | **MEDIUM** -- THAT Corp model | THAT Corporation publishes SPICE macromodels for their VCAs. Complex (log-domain gain cell + RMS rectifier opamps). Worth obtaining for the compressor stage. |
| **MCP4728 / MCP4131 / MCP23008** | DAC / digipot / GPIO expander | **STUB** | Digital control ICs. Model as ideal voltage source (MCP4728) or variable resistor (MCP4131) at their *analog* pins; ignore digital control. |

### Recommendation: a `models/` registry

Create `volta/spice/models/` holding curated `.lib` files + a Python registry mapping `lib_id → (model_name, lib_file, pin_map)`. This mirrors `symbol_mapper.py`'s pattern but for SPICE. Priority order: NE5532 (most-used, 5×/channel), THAT340 (discrete BJT models, trivial), DG413 (utility switching), THAT4301 (compressor). AK4619VN gets an explicit `UNSIMULATABLE` entry that the testbench generator handles by substituting an ideal source.

---

## Research Question 3: Testbench Generator

### The five analysis types and how ngspice expresses each

All verified by live execution on ngspice 45.2. The testbench generator emits one `.cir` deck per analysis; each deck = netlist (from skidl/InSpice) + stimulus + analysis command + output directive.

#### 1. AC analysis (gain, phase, bandwidth)
```
.title AC gain/phase
<netlist from skidl>
Vin _in 0 DC 0 AC 1        ; swept source
.ac dec 100 10 100k         ; 100 pts/decade, 10Hz-100kHz
.print ac v(out)            ; OR rely on -r raw capture
.end
```
Run: `ngspice -b deck.cir -r ac.raw` (the `-r` flag writes raw; placement-flexible). Parse: `RawRead('ac.raw', dialect='ngspice')` → `frequency[]`, `V(out)` (complex). Derive: `gain_db = 20*log10(|V(out)|)`, `phase_deg`, `bw_3db` (find -3dB crossing), `gain_margin`, `phase_margin`.

#### 2. Transient (time-domain, step/sine response)
```
.title Transient
Vin _in 0 SINE(0 1 1k)      ; 1Vpk 1kHz sine
.tran 1u 5ms 0 1u           ; tstep tstop tstart tmax
.print tran v(out)
.end
```
Derive: RMS, peak, clipping, settling time. Foundation for THD.

#### 3. THD (total harmonic distortion)
```
.title THD
Vin _in 0 SINE(0 1 1k)
.tran 1u 5ms 0 1u
.four 1k v(out)             ; .four <fundamental_freq> <signal>
.end
```
**Critical finding:** THD output goes to the **log file, not the `.raw`**. ngspice emits a "Fourier analysis for v(out)" block with `THD: X%` + per-harmonic magnitudes. Verified: `re.search(r'THD:\s*([\d.eE+-]+)\s*%', log)` parses cleanly; harmonic table parses via `re.findall(r'^\s*(\d+)\s+([\d.eE+-]+)\s+([\d.eE+-]+)', log, re.M)`. This is a **different output channel** than AC/transient and the parser must handle text logs for THD.

#### 4. Noise (input-referred noise, noise floor)
```
.title Noise
Vin _in 0 DC 0 AC 1
.ac dec 10 10 100k
.noise v(out) Vin dec 10 10 100k
.control
  run
  write noise.raw frequency onoise inoise
.endc
.end
```
**Critical finding:** `.noise` vectors (`onoise`, `inoise`) are **not written to the standard `-r` raw file** -- they live in ngspice's internal vector space and must be flushed via a `.control ... write ... .endc` block. The plain `.print noise onoise` directive does not reliably emit a raw either. The `.control/run/write` idiom is the robust path. Run with `-D ngbehavior=ps` (or `kiltpsa`) for compatibility-mode-correct noise. Derive: `noise_floor` (spot value @1kHz or @20kHz, in V/√Hz), `integrated_noise` (∫ over band, in Vrms), `EIN` (equivalent input noise).

#### 5. Monte Carlo (tolerance distributions)
Two viable approaches:

**(a) In-deck loop** (single ngspice process):
```
.control
  let run = 0
  repeat 100
    let run = run + 1
    alter R1 = 1000*(1 + (rand()-0.5)*0.2)
    alter C1 = 1e-6*(1 + (rand()-0.5)*0.2)
    run
    write mc_{$&run}.raw v(out)
  end
.endc
```
Verified: this produces `mc_1.raw ... mc_100.raw`. Each is a separate raw; aggregate by parsing all and computing the distribution. Downside: ngspice's `rand()` is uniform; for Gaussian you compose `gauss()` or sum 12× uniform (Irwin-Hall).

**(b) Parameter-override spawning** (N ngspice processes, parallelizable):
```
ngspice -b -D R1VAL=980 -D C1VAL=1.02e-6 deck.cir -r run_42.raw
```
Verified: `-D` injects a parameter, referenced in-deck as `R1 out 0 {R1VAL}`. Note the gotcha: ngspice complained `Undefined parameter [rval]` when the deck used `{rval}` lowercase but `-D` passed `Rnom` -- **names are case-sensitive and must match exactly**. This approach pairs naturally with Python's `multiprocessing` and the existing `SimRunner` async machinery.

**Recommendation:** approach (b) for v5.0 -- it composes with the existing GRPO batch infrastructure, each run is independent and parallel, and Python controls the RNG (so Gaussian/ correlated tolerances are trivial in numpy).

### Testbench generator architecture

```
spice/
  testbench.py        # TestbenchBuilder: netlist + stimulus + analysis → .cir deck
  analyses.py         # AcAnalysis, TranAnalysis, NoiseAnalysis, ThdAnalysis, MonteCarlo
                      #   (each emits its deck fragment + knows its output channel)
  ngspice_runner.py   # run_ngspice(deck_path) → raw_path + log_path
  models/
    registry.py       # lib_id → (model_name, lib_file, pin_map)
    NE5532.lib        # curated model files
    ...
```

`analyses.py` mirrors the existing `sim_commands.py` frozen-dataclass pattern (`AcCommand`, `TranCommand`, ...) but adds the **stimulus** (source definition) and **output channel** metadata (raw vs log). The two layers compose: `AcCommand` describes the sweep; `AcAnalysis` wraps it with a source + output handling.

---

## Research Question 4: ngspice Output → Structured JSON

### Two output channels (this is the key insight)

ngspice emits results through **two different channels**, and a unified parser must handle both:

| Channel | Analyses | Format | Parser |
|---------|----------|--------|--------|
| **`.raw` (binary)** | AC, Transient, DC, OP, Monte-Carlo runs | spicelib `RawRead(path, dialect="ngspice")` → vectors of complex (AC) or real (tran) floats | Generalize existing `raw_reader.py` |
| **`.log` (text)** | THD (`.four`), `.meas` results, warnings/errors | Free-form text with regex-parseable tables | New `log_parser.py` |

For noise, the vectors reach `.raw` *only* via the `.control/write` idiom (see Q3 #4) -- treat noise as a raw-channel analysis but require the control-block deck form.

### Proposed JSON schema

```json
{
  "analysis_type": "ac",
  "engine": "ngspice",
  "engine_version": "45.2",
  "deck_path": ".../ac.cir",
  "raw_path": ".../ac.raw",
  "log_path": ".../ac.log",
  "converged": true,
  "sweep": {"variable": "frequency", "n_points": 301, "unit": "Hz"},
  "traces": {
    "frequency": [10.0, 10.5, ...],
    "v(out)": {
      "real": [0.99, ...],
      "imag": [-0.01, ...],
      "magnitude": [0.99, ...],
      "magnitude_db": [-0.087, ...],
      "phase_deg": [-0.58, ...]
    }
  },
  "metrics": {
    "gain_db_at_1khz": 19.4,
    "bandwidth_3db_hz": 96500,
    "gain_margin_db": 12.3,
    "phase_margin_deg": 65.2
  }
}
```

For THD:
```json
{
  "analysis_type": "thd",
  "output_channel": "log",
  "fundamental_hz": 1000,
  "thd_percent": 0.58,
  "harmonics": [
    {"n": 1, "freq": 1000, "magnitude": 0.99, "phase": 0.0, "norm_mag": 1.0},
    {"n": 2, "freq": 2000, "magnitude": 0.0021, "phase": 167.5, "norm_mag": 0.0021},
    ...
  ]
}
```

For Monte Carlo (aggregate of N runs):
```json
{
  "analysis_type": "monte_carlo",
  "n_runs": 100,
  "metric": "gain_db_at_1khz",
  "distribution": {
    "mean": 19.38, "std": 0.42, "min": 18.1, "max": 20.6,
    "p95": [18.71, 20.05],
    "n_within_spec": 97, "yield_pct": 97.0
  },
  "per_run_raws": ["mc_1.raw", "mc_2.raw", ...]
}
```

### Extraction math (numpy, trivial)

- **Gain/phase from AC:** `mag = np.abs(complex_vector)`, `phase = np.angle(complex_vector, deg=True)`. spicelib returns complex values for AC traces (verified: the RC test printed complex values, with a benign `ComplexWarning` when cast to real).
- **Bandwidth:** find last frequency where `mag_db >= peak_db - 3`.
- **Noise floor:** spot value at target freq, or `np.sqrt(np.trapz(onoise**2, freq))` for integrated.
- **THD from harmonics:** `sqrt(sum(H2..Hn)^2) / H1` (ngspice already prints this as `THD: X%`).
- **Monte Carlo yield:** `sum(spec_met) / n_runs`.

### Generalizing `raw_reader.py`

The existing `read_raw(path)` hardcodes `dialect="ltspice"`. Change to:

```python
def read_raw(raw_path, dialect: str | None = None) -> SimulationResult:
    ...
    if dialect is None:
        dialect = _detect_dialect(resolved)   # sniff "Plotname:" / "Title:" header
    raw = RawRead(str(resolved), dialect=dialect, verbose=False)
```

`_detect_dialect` checks for ngspice-vs-LTspice header markers (ngspice raws carry `Program: ngspice 45.2` or `Date: ...` styling differences). This single change makes `read_raw` engine-neutral and the LTspice callers continue working (they can pass `dialect="ltspice"` explicitly or rely on detection). The downstream `SimulationResult`/`LTspiceTrace` types need no changes -- rename to `SimResult`/`Trace` cosmetically if desired, but the structure is identical.

---

## Research Question 5: SPICE as a Reward Signal for AI Training

### The core idea

SPICE gives a **physical ground truth** that geometry-only reward signals cannot. The existing `training/board_reward.py` scores reasoning chains on *format + quality + coordinate accuracy* -- useful for "did the model reason about the right region" but silent on *"did the routing actually work electrically."* SPICE closes that gap:

- **Pre-routing simulation** = ideal schematic (no parasitics). This is the *design intent* baseline. Run once per design.
- **Post-routing simulation** = the routed board with parasitics extracted from the PCB (trace resistance/inductance, coupling capacitance, via inductance). Run per candidate layout the model proposes.
- **Reward** = how well post-routing preserves pre-routing electrical performance. A layout that destroys the -128 dBu noise target or adds 2% THD gets a low reward even if it "looks neat."

### Concrete reward components (mapping to CIRCUIT-DESIGN.md targets)

The spec states explicit targets. Each becomes a reward term:

| Spec target (from CIRCUIT-DESIGN.md) | Metric | Reward term |
|---------------------------------------|--------|-------------|
| Stage 1: EIN ≈ -128 dBu (Q4.3) | integrated input noise | `reward_noise = clip(1 - (EIN_post - EIN_pre)/delta_max, 0, 1)` |
| Stage 1: gain +18dB (Q4.3) | gain_db @ 1kHz | `reward_gain = clip(1 - |gain_post - gain_pre|/tol, 0, 1)` |
| EQ: ±18dB per band (§8) | AC sweep flatness in bypass | `reward_flatness = 1 - max_deviation_db` |
| Stage 3: THD ≈ 0.5-2% (§7, "warm") | THD % from `.four` | `reward_thd = clip((thd_post - thd_lo)/(thd_hi - thd_lo), 0, 1)` -- *note this is a windowed target, not minimize-to-zero* |
| Power rail noise <50µVrms (§9.3) | rail noise from `.noise` | `reward_rail = clip(1 - rail_noise/50e-6, 0, 1)` |
| Monte Carlo yield | % runs within all specs | `reward_yield = n_within_spec / n_runs` |

Total: weighted sum (weights tunable, following the `BoardChainReward` aggregate pattern). The reward is **differentiable-friendly** (clip + linear) for GRPO.

### Where it plugs into existing training infrastructure

The repo already has the full RL loop:
- `training/grpo.py`, `training/grpo_trainer.py`, `training/grpo_config.py` -- GRPO trainer.
- `training/board_reward.py` -- `BoardRewardSignal` (per-step) + `BoardChainReward` (aggregate), `score_board_chain(chain, sample)`.
- `training/reward.py`, `training/reward_hacking.py` -- reward shaping + hacking mitigations.

**Integration pattern:** add a `SimRewardAdapter` (mirroring `LegibilityRewardAdapter`, which already exists) that:
1. Takes a candidate layout (from the board chain).
2. Extracts a netlist (skidl) + injects routing parasitics (from `PcbIR` traces/vias -- trace R = ρL/A, L from geometry, C from overlap area + dielectric).
3. Runs the testbench suite (AC + noise + THD + MC) via `ngspice_runner`.
4. Parses results → metric dict → reward terms → folds into `BoardChainReward` as a new `sim_score` component alongside `format_score`/`quality_score`/`accuracy_score`.

### The pre-vs-post-parasitic delta (the actual signal)

Two ways to model routing parasitics, in order of fidelity/cost:

**(a) Closed-form parasitics (fast, no field solver):**
- Trace resistance: `R = rho_Cu * length / (width * thickness)`.
- Trace inductance: microstrip/stripline closed-form (the v3.0 STACK already plans `spatial/impedance.py` with Hammerstad-Jensen / IPC-2141 -- reuse it).
- Coupling capacitance: parallel-plate approximation from `PcbSpatialModel` overlap area × dielectric ε.
- Via inductance: ~1nH/via empirical.
Inject as lumped R/L/C into the netlist at trace endpoints. This is fast enough to run inside a GRPO rollout (ms-scale per net).

**(b) Field-extracted parasitics (accurate, slow):**
- Run a 2D/3D field solver (openEMS, fastcap/fasthenry). Too slow for in-loop RL -- use only for offline validation.

**Recommendation:** (a) for the training loop; (b) for a held-out validation set. The reward signal *shape* (delta from ideal) is what teaches the model, and (a) captures the dominant effects (long high-impedance traces pick up noise; parallel mic/line traces couple crosstalk).

### Cost & caching (critical for RL)

- A full per-channel AC + noise + THD + 100-run MC suite is ~seconds on ngspice. Across a GRPO batch (e.g., 8 rollouts × 64 samples), this is minutes -- acceptable but not free.
- **Cache aggressively:** the pre-routing baseline is computed *once per design*. Post-routing sims depend only on (netlist, parasitics) -- hash the parasitic-injection block and memoize results. Identical candidate layouts (common in early training) hit the cache.
- **Fall back gracefully:** if a sim fails to converge (common with ideal-opamp macromodels at sharp transients), return a *penalty* reward (not zero) so the model learns the layout is suspect, rather than treating divergence as a free pass.

---

## Recommended Stack for v5.0

### New core dependencies: NONE

Everything is installed. Explicit confirmation:
- ngspice 45.2 ✓ (binary)
- spicelib 1.5.1 ✓ (already core dep)
- skidl 2.2.3 + InSpice 1.6.3.3 ✓ (the SPICE-export path)
- networkx, numpy ✓ (core)

### Do NOT add

| Avoid | Why |
|-------|-----|
| **PySpice** | Not installed; skidl migrated to **InSpice** (PySpice fork) which *is* installed. Depending on `PySpice` would fail at import. InSpice exposes the identical API (`InSpice.Spice.Netlist.Circuit`). |
| **Qucs / Qucs-S** | Another GUI simulator. ngspice is scriptable and headless; Qucs adds nothing and loses batch-mode reproducibility. |
| **openEMS** (FDTD field solver) | Too slow for in-loop RL (minutes/hours per sim). Use closed-form parasitics in-loop; reserve field solvers for offline validation. |
| **Xyce / commercial SPICE** | ngspice 45.2 has every analysis we need (AC/tran/noise/MC/`.four`). Xyce adds parallelism we don't need at PCB scale. |
| **A custom `.raw` parser** | spicelib `RawRead` already parses ngspice raw (verified). Reuse it; generalize the dialect arg. |

### New modules to build

| Module | Est. lines | Depends on | Purpose |
|--------|-----------|------------|---------|
| `spice/__init__.py` | ~20 | -- | Package marker; re-exports |
| `spice/raw_reader.py` (generalized) | ~120 | spicelib, `ltspice/types.py` | `read_raw(path, dialect=None)` with auto-detect; superset of current LTspice-only reader |
| `spice/log_parser.py` | ~150 | re | Parse THD/`.meas` from ngspice `.log` text |
| `spice/analyses.py` | ~250 | `sim_commands` types | `AcAnalysis`, `TranAnalysis`, `NoiseAnalysis`, `ThdAnalysis`, `MonteCarlo` -- each emits deck fragment + declares output channel (raw/log) |
| `spice/testbench.py` | ~200 | analyses, skidl/InSpice | `TestbenchBuilder`: combine netlist + stimulus + analysis → `.cir` deck string |
| `spice/ngspice_runner.py` | ~150 | subprocess, spicelib NGspiceSimulator | `run(deck_path) → RunResult(raw_path, log_path, returncode, converged)`; wraps `NGspiceSimulator.run()` or direct subprocess |
| `spice/result_schema.py` | ~200 | pydantic | `AcResult`, `ThdResult`, `NoiseResult`, `MonteCarloResult` JSON schemas (Q4) |
| `spice/metrics.py` | ~250 | numpy | `gain_db`, `bandwidth_3db`, `noise_floor`, `thd_from_harmonics`, `monte_carlo_yield` extraction fns |
| `spice/models/registry.py` | ~150 | -- | `lib_id → (model_name, lib_file, pin_map)`; `UNSIMULATABLE` sentinel for AK4619VN |
| `spice/parasitics.py` | ~250 | numpy, PcbIR, `spatial/impedance.py` (v3.0) | Extract trace R/L/C from routed board; inject as lumped elements |
| `training/sim_reward_adapter.py` | ~200 | `training/board_reward`, spice/* | `SimRewardAdapter`: layout → sim → reward terms → fold into `BoardChainReward` |

**Total estimated new code:** ~1,900 lines across 11 modules.

### pyproject.toml changes

```toml
dependencies = [
    # ... existing ...
    "spicelib>=1.5.1",   # already present; ngspice raw + NGspiceSimulator used by v5.0
]

[project.optional-dependencies]
spice = [
    "skidl>=2.0",        # already a dep via analog-ecosystem; make explicit for the spice export path
    "InSpice>=1.6",      # PySpice fork; skidl's SPICE tool requires it
]
```

Two changes: document `skidl`/`InSpice` in a new `spice` optional group (they may already be installed transitively; making them explicit is correct packaging). No new solver binary -- ngspice is installed system-wide.

---

## Key Design Decisions

### D-S1: ngspice over LTspice as the v5.0 engine
**Decision:** v5.0 runs ngspice, not LTspice.
**Why:** ngspice is installed, headless, scriptable, and runs end-to-end on this macOS host with no Wine. The LTspice module can only *write* `.asc` and *read* `.raw` -- it cannot *execute* a sim, which makes it useless as an RL reward signal. ngspice's batch mode (`-b deck.cir -r out.raw`) is exactly the deterministic, no-human-in-the-loop interface RL needs. LTspice remains valuable for human-in-the-loop verification of exported `.asc` files; the two coexist.

### D-S2: Generalize the result layer, keep the LTspice-schematic-bridge separate
**Decision:** Move `sim_commands.py`/`types.py`/`raw_reader.py` semantics into a new engine-neutral `spice/` package; leave `ltspice/` as the `.asc`/`.asy` bridge.
**Why:** `sim_commands.py` parses standard SPICE syntax (`.ac`/`.tran`/`.noise` work identically in ngspice). `SimulationResult`/`Trace` are engine-agnostic containers. Only the `.asc`/`.asy`/`symbol_mapper`/`net_graph` files are LTspice-schematic-specific. Splitting avoids forking shared logic and keeps v2.0 callers working.

### D-S3: skidl + InSpice for netlist export, not hand-written deck generation
**Decision:** Use skidl's `generate_netlist(tool="spice")` (→ InSpice `Circuit`) to produce the device netlist; layer stimulus/analysis on top.
**Why:** skidl already understands the analog-ecosystem circuits (it's how the boards are defined). Hand-writing decks would duplicate the netlist-of-record. The gap (missing `.pyspice` on custom ICs) is solved by the model registry (D-S4), not by abandoning skidl.

### D-S4: Curated model registry with an explicit UNSIMULATABLE sentinel
**Decision:** Build `spice/models/registry.py` mapping each lib_id to a SPICE model file + pin map; mark AK4619VN (and other mixed-signal ICs) `UNSIMULATABLE` and substitute ideal sources at their analog pins.
**Why:** No models exist in-repo today. NE5532/THAT340/DG413 are obtainable and high-value. The AK4619VN codec genuinely cannot be SPICE-simulated (delta-sigma + digital I2S). Pretending otherwise would produce nonsense reward signals. The testbench generator must explicitly handle the stub case so a missing model degrades to "skip this path" rather than crashing.

### D-S5: Two output channels (raw + log), two parsers
**Decision:** `raw_reader.py` (generalized) for AC/Tran/DC/MC; new `log_parser.py` for THD/`.meas`.
**Why:** Verified live: THD/Fourier data goes to `.log`, not `.raw`. AC/Tran go to `.raw`. Noise needs the `.control/write` idiom to reach `.raw`. A single parser cannot handle both binary-raw and free-text-log. This matches spicelib's own architecture (it has `raw/raw_read.py` but no log parser -- we build the log parser ourselves).

### D-S6: Monte Carlo via parameter-override spawning, not in-deck loops
**Decision:** Run N independent ngspice processes with `-D` overrides (parallel), not a single `.control repeat` loop.
**Why:** Parallelizes trivially with the existing GRPO batch infra; Python controls the RNG (Gaussian/correlated tolerances are one numpy line); each run is an independent raw for clean aggregation. The in-deck-loop alternative is serial and uses ngspice's limited `rand()`. Note the case-sensitivity gotcha: `-D R1VAL` must match `{R1VAL}` in-deck exactly.

### D-S7: Closed-form parasitics for in-loop RL; field solvers for offline validation only
**Decision:** Inject trace R/L/C from closed-form formulas (microstrip/stripline, reuse v3.0's planned `spatial/impedance.py`) during training; reserve openEMS/fastcap for a held-out validation set.
**Why:** Closed-form parasitics are ms-scale and capture the dominant routing effects (long high-Z traces = noise pickup; parallel traces = crosstalk). Field solvers are minutes-to-hours -- incompatible with GRPO rollout latency. The reward *shape* (delta from ideal) is what teaches the model; absolute parasitic precision is not required for learning.

---

## Sources

- Live execution: `ngspice --version` (45.2, KLU solver); RC lowpass `.ac` batch sim → valid `.raw`; THD `.four` → parseable log; Monte Carlo `.control repeat` → per-run raws.
- Live import: `spicelib` 1.5.1 (`RawRead` ngspice dialect ✓, `NGspiceSimulator` ✓, `SimRunner` ✓); `skidl` 2.2.3 (`Circuit.generate_netlist` ✓, `tools/spice/spice.py:gen_netlist` ✓); `InSpice` 1.6.3.3 (PySpice fork, importable); `PySpice` → **ModuleNotFoundError**.
- `src/volta/ltspice/sim_commands.py` — SPICE-syntax parser (`.tran/.ac/.dc/.noise/.op`), frozen dataclasses, `parse_eng_value()`.
- `src/volta/ltspice/raw_reader.py` — `RawRead(path, dialect="ltspice")`, `SimulationResult`/`LTspiceTrace` types.
- `src/volta/ltspice/types.py` — engine-agnostic result containers.
- `src/volta/ltspice/{asc_parser,asc_writer,symbol_mapper,net_graph}.py` — LTspice-schematic-specific bridge.
- `analog-ecosystem/.../mono-arch/parts.py` — custom IC wrappers; THAT4301/AK4619VN/XMOS modeled as generic connectors (no SPICE behavior); NE5532/DG413 as real KiCad symbols (no `.pyspice`).
- `analog-ecosystem/.../CIRCUIT-DESIGN.md` — explicit targets: EIN -128dBu (§4.3), gain +18dB (§4.3), THD 0.5-2% windowed (§7), EQ ±18dB (§8), rail noise <50µVrms (§9.3).
- `src/volta/training/board_reward.py` — existing `BoardRewardSignal`/`BoardChainReward` pattern; `LegibilityRewardAdapter` precedent for reward adapters.
- `.planning/research/STACK.md` (v3.0) — `spatial/impedance.py` (Hammerstad-Jensen microstrip) planned; reuse for closed-form parasitics.
- `find analog-ecosystem -iname "*.lib"` → zero SPICE model files (no models in-repo).

---
*Stack research for: volta milestone v5.0 SPICE simulation pipeline*
*Researched: 2026-07-03*
