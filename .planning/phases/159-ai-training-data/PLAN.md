# Phase 159 — AI Training Data

**Goal:** Turn the Phase 156 SKIDL converter, Phase 157 floor planner, and Phase 158 SPICE pipeline into a training data factory. Three data products flow out of this phase: (1) 71K crawled KiCad repos → SKIDL Python + natural-language descriptions (NL→SKIDL SFT pairs), (2) placement→routing quality pairs from Quilter (placement→RES score, for the Gemma vision adapter), and (3) SPICE pre-route vs post-route degradation as a physical reward signal (`sim_score`) that geometry-only signals cannot provide. Two adapters consume the output: **Qwen text** for circuit generation (SKIDL is pure text — no vision needed) and **Gemma vision** for routing (the Phase 98 model enhanced with placement context).

**Depends on:** Phase 156 (SKIDL converter for the 71K repos), Phase 157 (floor planner for placement pairs), Phase 158 (SPICE for the reward signal)
**Requirements:** TRAIN-01, TRAIN-02, TRAIN-03, TRAIN-04, TRAIN-05, TRAIN-06, TRAIN-07
**Research basis:** `.planning/research/STACK-SKIDL.md` (SchGen L1/L2 ablation — Code-L1 is SKIDL), `.planning/research/STACK-SPICE.md` (D-S7 closed-form parasitics for in-loop RL)
**Integration target:** `src/kicad_agent/training/` (existing SFT/GRPO/reward infrastructure) + `src/kicad_agent/circuit_ir/` (Phase 156) + `src/kicad_agent/spice/` (Phase 158)

---

## Design Principles

1. **Compose, don't rebuild.** kicad-agent already has the full ML pipeline: `sft/converter.py` (chain→ChatML), `sft/quality_filter.py` (reward-model bottom-quartile removal), `sft/trainer.py` (LoRA on Qwen2.5-1.5B, MPS-safe), `grpo.py` + `grpo_trainer.py` (GRPO loop), `legibility_reward_adapter.py` (reward-into-GRPO bridge pattern), `vision_data_builder.py` (mlx-vlm format), `routing_quality.py` (RES score), `generate_gap_training_data.py` (Gemma ChatML + train/val split). Phase 159 adds **a data-generation layer** (`training_data/`) that *feeds* these — it does not fork them.
2. **Two adapters, two formats, one pipeline.** Qwen text consumes ChatML JSONL (`messages` with system/user/assistant). Gemma vision consumes `<start_of_turn>role\n...<end_of_turn>` text + rendered PCB images. Both are already defined (`sft/templates.py` vs `generate_gap_training_data.format_gemma_chatml`). Phase 159 emits both from a shared SKIDL corpus — no conversion step between them.
3. **L2 is the training representation; L1 is the round-trip proof.** Per STACK-SKIDL §"Why L1 Wins", SchGen's Code-L1 (relative coords + pin-name wiring) has the lowest MDL/complexity/validation loss. SKIDL *is* a Code-L1 representation. For training data we emit the **L2 form** (component-level, compact — `part["IN+"] += net`, no absolute geometry) because it is the most compressible and learnable; L1 (pin-level exact) is used only for the round-trip ERC-equality test (CONV-09) that validates the converter, not for training tokens.
4. **NL descriptions are generated, then human-spot-checked on a sample.** Auto-generating NL from a SKIDL circuit is lossy (no README in most crawled repos). We generate a structured NL description from circuit topology (detected sub-circuits, dominant component types, inferred function) and enrich it where a README/README.md exists in the crawled repo. A stratified sample (e.g. 200 circuits across complexity buckets) is spot-checked for label quality before training.
5. **SPICE degradation is a reward signal, not a training target.** TRAIN-04 adds `sim_score` to the existing `BoardChainReward` (format/quality/accuracy). It is computed from the pre-route vs post-route SPICE delta (Phase 158 `DegradationReport`) — a *physical* signal that catches parasitic-induced failures the geometry-only RES score cannot (e.g. a placement that routes cleanly but detunes a high-impedance node). SchGen explicitly notes SPICE is for analog sub-circuits only — we honor that boundary.
6. **Scale via the existing batch/manifest/registry infra.** 71K repos is a batch job. Phase 159 reuses `DataManifest` (SHA256 + versioning), `adapter_registry.py` (adapter metadata registry), and the Vast.ai training scripts (`scripts/vast_train_kicad.py`) from Phase 97. The data generation is embarrassingly parallel (one repo → one SKIDL file, no cross-repo state) and runs as a multiprocess batch.

---

## Reference: Requirements → Tasks

| Req | Description | Wave | Primary Task |
|-----|-------------|------|--------------|
| TRAIN-01 | Convert 71K crawled KiCad repos → SKIDL Python code | 1 | Task 1 |
| TRAIN-02 | Generate natural-language descriptions for each circuit (SFT pairs) | 2 | Task 2 |
| TRAIN-03 | Placement → routing quality pairs (from Quilter results) | 3 | Task 4 |
| TRAIN-04 | SPICE degradation as reward signal (pre-route vs post-route delta) | 3 | Task 5 |
| TRAIN-05 | Qwen text adapter for circuit generation (SKIDL is pure text) | 4 | Task 6 |
| TRAIN-06 | Gemma vision adapter for routing (enhance existing Phase 98 model) | 4 | Task 7 |
| TRAIN-07 | Training data format matches `generate_gap_training_data.py` output | 1 | Task 3 |

---

## Key Design Decisions

These decisions extend the LOCKED decisions from Phases 156 and 158. Do not re-litigate.

- **D-159-1: SKIDL L2 is the NL→SKIDL training target.** SchGen's ablation shows L1 (pin-name + relative) beats L2/L3 on netlist accuracy, but L2 (component-level) is more compact and learnable for an LLM to *generate*. SKIDL's `part["PIN_NAME"] += net` is already the pin-name-based wiring SchGen proved critical (the L2→L3 collapse). We train Qwen to emit L2 SKIDL; ERC (Phase 160) is the correctness gate, not representation purity.
- **D-159-2: NL description = topology-derived structured summary + optional README enrichment.** No crawled repo ships a clean NL prompt. We derive NL from the circuit itself: detected sub-circuits (via Phase 46 `Subcircuit` detection — e.g. "non-inverting op-amp gain stage", "RC low-pass filter"), dominant IC count, inferred function ("16-channel microphone preamp array"). Where `README.md` exists in the repo, its first paragraph is appended as `author_description`. This produces varied, topology-grounded NL rather than templated boilerplate.
- **D-159-3: Placement pairs come from Quilter, scored by RES.** TRAIN-03 is placement→routing-quality pairs. We take each SKIDL circuit → floor-planned PCB (Phase 157) → Quilter route → `compute_routing_quality` (RES score from `routing_quality.py`). The pair is `(placement_spec_or_render, RES_score)`. This trains Gemma vision to predict routing quality from a placement image — directly enhancing the Phase 98 model with placement context.
- **D-159-4: `sim_score` extends `BoardChainReward`, does not replace it.** Phase 158's `SimRewardAdapter` (mirroring `LegibilityRewardAdapter`) computes the SPICE degradation term. The combined reward becomes a weighted sum: existing `0.2*fmt + 0.3*qual + 0.5*acc` gains an optional `sim_score` term weighted by whether the circuit is analog-simulatable (digital circuits get `sim_score=0.5` neutral, honoring SchGen's boundary). See Task 5.
- **D-159-5: Format parity with `generate_gap_training_data.py` is the drop-in contract.** TRAIN-07 is explicit: output must match the existing Gemma ChatML JSONL schema (`messages`, `text`, `task_type`, `source`). The Qwen output matches `sft/converter.py`'s `ChatMLSample` (`messages` tuple, `source`, `source_id`). No conversion step between Phase 159 output and the existing GRPO/SFT pipeline — it drops in directly.

---

## Target Package Layout

```
src/kicad_agent/training_data/
├── __init__.py              # ~40 lines — public exports
├── skidl_corpus.py          # ~300 lines — batch convert 71K repos → SKIDL L2 .py (TRAIN-01)
├── nl_describer.py          # ~250 lines — circuit → NL description (TRAIN-02)
├── sft_pair_builder.py      # ~200 lines — (NL, SKIDL) → ChatML JSONL, Qwen format (TRAIN-02, TRAIN-07)
├── placement_pair_builder.py # ~250 lines — SKIDL → floor plan → Quilter → (render, RES) pairs (TRAIN-03)
├── vision_pair_builder.py   # ~180 lines — placement/RES pairs → Gemma ChatML + rendered images (TRAIN-03, TRAIN-06, TRAIN-07)
├── sim_reward_adapter.py    # ~200 lines — SPICE DegradationReport → sim_score (TRAIN-04)
└── corpus_qa.py             # ~150 lines — spot-check report, complexity-bucket sampling (TRAIN-02 quality)

scripts/
├── build_skidl_corpus.py    # ~120 lines — CLI: convert 71K repos (--input-dir, --output-dir, --workers N)
├── build_training_pairs.py  # ~100 lines — CLI: corpus → SFT pairs (Qwen) + vision pairs (Gemma)
└── run_159_training.py      # ~150 lines — CLI: train Qwen + Gemma adapters (delegates to vast_train_kicad.py)
```

**Why a top-level `training_data/` subpackage (not `training/training_data.py`)?** The existing `training/` package is the *ML infrastructure* (SFT trainer, GRPO loop, reward models, vision builder) — it consumes data. Phase 159 is the *data generation* layer that produces the specific NL→SKIDL and placement→RES datasets. Keeping it separate preserves the clean producer/consumer boundary and avoids bloating `training/` with 7 new domain-specific modules.

### Reused primitives (no duplication)

| Phase 159 concept | Existing primitive | Location |
|---|---|---|
| KiCad→SKIDL conversion | `build_circuit()` + `emit_build_py(mode="L2")` | `circuit_ir/` (Phase 156) |
| Sub-circuit detection (for NL) | `Subcircuit` + `SubcircuitDetector` | Phase 46 (analysis) |
| Circuit intent inference | `DesignIntent` inference | Phase 47 (analysis) |
| Routing quality score (RES) | `compute_routing_quality()` | `training/routing_quality.py:430` |
| PCB image rendering | `render_pcb_layer_png()`, `render_schematic_png()` | `export/pcb_image_renderer.py` |
| Floor plan application | `apply_floor_plan()` | `floorplan/applier.py` (Phase 157) |
| Quilter invocation | existing `pcb_auto_route` ops | Phase 99/100 |
| Gemma ChatML format | `format_gemma_chatml()` | `scripts/generate_gap_training_data.py:41` |
| Qwen ChatML format | `ChatMLSample`, `SYSTEM_PROMPT_SPATIAL` | `sft/converter.py`, `sft/templates.py` |
| Reward-model filtering | `filter_by_reward_model()` | `sft/quality_filter.py:26` |
| Train/val split | `split_and_save()` / `_write_split()` | `sft/quality_filter.py:82`, `generate_gap_training_data.py:261` |
| LoRA SFT training | `run_sft_training()`, `SFTTrainingConfig` | `sft/trainer.py:162` |
| Vision dataset build | `build_vision_dataset()` | `training/vision_data_builder.py:51` |
| Vision LoRA training | `vision_lora_trainer.py` | `training/vision_lora_trainer.py` |
| Data manifest (SHA256) | `DataManifest.from_directory()` | `training/manifest.py:47` |
| Adapter registry | `adapter_registry.py` | `training/adapter_registry.py` |
| Vast.ai training | `vast_train_kicad.py` | `scripts/vast_train_kicad.py` |
| GRPO loop | `grpo.py`, `grpo_trainer.py` | `training/grpo.py` |
| Reward-into-GRPO bridge pattern | `LegibilityRewardAdapter` | `training/legibility_reward_adapter.py` |
| SPICE degradation report | `DegradationReport` | `spice/parasitics.py` (Phase 158) |
| SPICE sim reward adapter | `SimRewardAdapter` | `spice/sim_reward_adapter.py` (Phase 158 Task 12) |
| Board chain reward | `BoardChainReward`, `score_board_chain()` | `training/board_reward.py` |

---

## Wave 1 — SKIDL Corpus (TRAIN-01, TRAIN-07)

**Goal:** Convert the 71K crawled KiCad repos (from Phase 13 `real_dataset.py` corpus) into SKIDL L2 Python files. This is the foundational dataset — every downstream product (NL pairs, placement pairs, SPICE rewards) derives from it.

**Files:** `training_data/skidl_corpus.py`, `training_data/__init__.py`, `scripts/build_skidl_corpus.py`, `tests/test_skidl_corpus.py`

### Task 1: Batch SKIDL conversion (TRAIN-01)

`skidl_corpus.py` wraps the Phase 156 converter (`convert_to_skidl` op / `circuit_ir/skidl_circuit.py`) in a batch driver:

```python
@dataclass(frozen=True)
class CorpusConversionResult:
    repo_id: str
    sch_path: str
    skidl_path: str       # output build_*.py (L2 mode)
    success: bool
    error: str | None
    n_components: int
    n_nets: int
    representation: str   # "L2"
    l1_erc_equal: bool    # did L1 round-trip match original ERC? (CONV-09 check, metadata only)

def convert_repo_to_skidl(
    repo_dir: Path,
    output_dir: Path,
    representation: str = "L2",
    emit_l1_erc_check: bool = False,
) -> CorpusConversionResult:
    """Convert one crawled repo's root .kicad_sch → build_*.py (SKIDL L2)."""

def build_skidl_corpus(
    corpus_root: Path,         # dir of 71K repos (Phase 13 layout)
    output_dir: Path,          # skidl_corpus/
    workers: int = 8,
    representation: str = "L2",
    max_failures: float = 0.30,  # tolerate up to 30% conversion failure (legacy schemas)
) -> CorpusStats:
    """Batch convert all repos. Embarrassingly parallel — one repo per task."""
```

**Key behaviors:**
- **Idempotent + resumable:** writes a `conversion_manifest.jsonl` (repo_id, status, hash) so re-runs skip completed repos. Honors `DataManifest` for integrity.
- **Failure-tolerant:** crawled repos have wildly varying KiCad versions (6/7/8/10), broken hierarchies, missing libs. A repo that fails conversion is logged + skipped — the 71K→target-yield is expected to be ~50K clean conversions (the failure budget is why we start with 71K).
- **L2 default:** emits compact `build_*.py` (component-level, `part["IN+"] += net`). Optionally runs L1 + ERC-equality as a *metadata quality flag* (`l1_erc_equal`) but does not emit L1 as the training token (D-159-1).
- **Multiprocessing:** `ProcessPoolExecutor(workers=N)`; each worker sets `KICAD_SYMBOL_DIR` before importing skidl (the Phase 156 import guard).

**Acceptance (TRAIN-01):**
- `build_skidl_corpus()` runs on the Phase 13 corpus and produces ≥40K valid SKIDL `.py` files (tolerating the failure budget).
- A random sample of 50 converted files each `exec()` cleanly into a `skidl.Circuit` and pass `ERC()` with 0 errors.
- Conversion manifest records per-repo success, component/net counts, and L1-ERC-equality flag.

### Task 3: Format parity contract (TRAIN-07)

`sft_pair_builder.py` and `vision_pair_builder.py` enforce the output schema to match existing tools. Two schemas:

**Qwen text (NL→SKIDL) — matches `sft/converter.py` `ChatMLSample`:**
```jsonl
{"messages": [{"role":"system","content":"<QWEN_CIRCUIT_PROMPT>"},{"role":"user","content":"<NL description>"},{"role":"assistant","content":"<SKIDL python>"}], "source":"skidl_corpus", "source_id": "<repo_id>", "quality_score": 0.87, "task_type":"circuit_generation"}
```

**Gemma vision (placement→RES) — matches `generate_gap_training_data.format_gemma_chatml`:**
```jsonl
{"messages": [{"role":"system","content":"<GEMMA_ROUTING_PROMPT>"},{"role":"user","content":"<placement image + RES question>"},{"role":"assistant","content":"<RES score + rationale>"}], "text": "<start_of_turn>...", "task_type":"placement_quality", "render_path": "<png>", "source":"<repo_id>"}
```

A `test_format_parity` test asserts that the output of `sft_pair_builder` is loadable by `_prepare_dataset()` (`sft/trainer.py:137`) and that `vision_pair_builder` output is loadable by `build_vision_dataset()` (`vision_data_builder.py:51`).

---

## Wave 2 — NL Descriptions + SFT Pairs (TRAIN-02)

**Goal:** Generate a natural-language description per circuit and build NL→SKIDL supervised fine-tuning pairs for Qwen.

**Files:** `training_data/nl_describer.py`, `training_data/sft_pair_builder.py`, `training_data/corpus_qa.py`, `tests/test_nl_describer.py`

### Task 2: NL description generation (TRAIN-02)

`nl_describer.py` derives NL from circuit topology — no external LLM call needed for corpus-scale generation (cost-prohibitive at 50K circuits):

```python
@dataclass(frozen=True)
class CircuitDescription:
    repo_id: str
    nl_description: str          # the SFT user prompt
    detected_function: str       # "microphone preamplifier", "power supply", "unknown"
    sub_circuits: tuple[str, ...]  # detected sub-circuit types
    dominant_components: tuple[str, ...]
    author_description: str | None  # from README.md if present
    confidence: float            # 0..1 — topology-derivation confidence

def describe_circuit(
    circuit: CircuitIR,
    repo_dir: Path | None = None,  # for README lookup
) -> CircuitDescription:
    """Derive an NL description from circuit topology + optional README."""
```

**NL generation strategy (3 signals fused):**
1. **Sub-circuit detection** — reuse Phase 46 `SubcircuitDetector` to find known blocks (op-amp gain stages, filters, regulators, MCU subsystems). Map detected blocks to phrases ("non-inverting amplifier with gain ~100", "3-terminal linear regulator").
2. **Component census** — dominant IC types, connector counts, passives ratio. "16-channel", "8 op-amps (NE5532)", "USB-C connector", "128 decoupling capacitors".
3. **README enrichment** — if `repo_dir/README.md` exists, extract first paragraph (heuristic: text before first `##`). This is the *only* human-authored signal and is appended as `author_description` context. ~20-30% of crawled repos have a usable README.

**NL prompt template (the Qwen user turn):**
```
Design a PCB circuit: {detected_function}.

Requirements inferred from topology:
{sub_circuits bullet list}
{component census}

{author_description if present}

Generate the SKIDL Python code for this circuit.
```

**Quality gate (`corpus_qa.py`):** a stratified sample (200 circuits across 5 complexity buckets: <10, 10-30, 30-80, 80-200, 200+ components) is emitted as a human-reviewable report (`corpus_qa_report.md`) listing the NL description + detected function + confidence. Circuits with `confidence < 0.4` (unrecognized topology, no README) are flagged for exclusion or human labeling. This bounds the label-noise rate before training.

**Acceptance (TRAIN-02):**
- `describe_circuit()` produces a non-empty, topology-grounded NL description for ≥95% of the corpus.
- README enrichment activates for repos with a README (no crash if absent).
- Spot-check report shows ≥70% of sampled descriptions are "plausibly correct" (human judgment) — the bar for auto-generated labels.

### SFT pair builder

`sft_pair_builder.py` assembles `(CircuitDescription.nl_description, build_*.py)` → ChatML JSONL in Qwen format. Applies the existing `filter_by_reward_model()` (bottom-quartile removal) where a reward model is available, otherwise emits unfiltered with `quality_score=None` (filtered later). Writes `train.jsonl`/`val.jsonl` via the existing `_write_split()` (90/10).

---

## Wave 3 — Placement Pairs + SPICE Reward (TRAIN-03, TRAIN-04)

**Goal:** Two physical-grounded data products: placement→routing-quality pairs (for Gemma vision) and SPICE degradation reward signal (for GRPO).

**Files:** `training_data/placement_pair_builder.py`, `training_data/vision_pair_builder.py`, `training_data/sim_reward_adapter.py`, `tests/test_placement_pairs.py`, `tests/test_sim_reward_adapter.py`

### Task 4: Placement → routing quality pairs (TRAIN-03)

`placement_pair_builder.py` runs the full physical pipeline per circuit and captures the (placement, RES score) pair:

```python
@dataclass(frozen=True)
class PlacementPair:
    repo_id: str
    skidl_circuit: str       # source SKIDL
    floor_plan: str          # .floorplan.yaml (Phase 157) or "grid" (no plan)
    pcb_render_path: str     # PNG of placed PCB (pre-route)
    res_score: float         # Routing Elegance Score 0..1
    res_features: dict       # 21-field RES feature vector
    routed: bool             # did Quilter complete routing?
    quilter_stats: dict      # completion %, via count, total length

def build_placement_pairs(
    skidl_corpus_dir: Path,
    output_dir: Path,
    floor_plan_strategy: str = "auto",  # "auto" | "grid" | "yaml"
    route_with_quilter: bool = True,
    max_components: int = 200,  # skip huge boards (Quilter time budget)
) -> list[PlacementPair]:
```

**Pipeline per circuit (the "placement quality" signal):**
1. SKIDL → netlist → PCB populate (Phase 156 `skidl_to_pcb.py`)
2. Apply floor plan (Phase 157 `apply_floor_plan`) — *and* a no-floor-plan grid variant, to create contrastive pairs (same circuit, with/without plan → RES delta). This directly demonstrates the Phase 157 success criterion (floor plan improves Quilter routing).
3. Render PCB to PNG (`render_pcb_layer_png`)
4. Route with Quilter (existing `pcb_auto_route` ops)
5. Score routed PCB with `compute_routing_quality()` (`routing_quality.py:430`) → RES + 21 features

**Contrastive augmentation:** for each circuit, emit 2 pairs — `(floor_plan_render, res_with_plan)` and `(grid_render, res_without_plan)`. This gives Gemma vision a direct signal: "this placement is better than that one." The RES delta is the training label.

### Task 5: SPICE degradation as reward signal (TRAIN-04)

`sim_reward_adapter.py` bridges Phase 158's `DegradationReport` into the existing `BoardChainReward`. It mirrors `LegibilityRewardAdapter` exactly (the proven reward-into-GRPO pattern):

```python
@dataclass(frozen=True)
class SimRewardWeights:
    """Weights for the physical sim_score term."""
    format: float = 0.15
    quality: float = 0.25
    accuracy: float = 0.35
    sim: float = 0.25         # the new physical term
    # validated: sum == 1.0

@dataclass(frozen=True)
class SimRewardAdapter:
    """Bridges Phase 158 DegradationReport into BoardChainReward (TRAIN-04).

    Honors the SchGen boundary: sim_score is only meaningful for analog
    sub-circuits. Digital/non-simulatable circuits get sim_score=0.5 (neutral),
    so the weight folds into accuracy (mirrors LegibilityRewardAdapter
    completeness_source="none" folding, HI-110-05).
    """
    weights: SimRewardWeights = field(default_factory=SimRewardWeights)

    def compute_sim_score(
        self,
        degradation: "DegradationReport",
        is_analog: bool,
    ) -> float:
        """Map pre-vs-post-route SPICE delta → 0..1 reward.

        Low degradation (post-route ≈ pre-route) → high score.
        is_analog=False → 0.5 neutral (SchGen boundary).
        """

    def combine(
        self,
        format_score: float,
        quality_score: float,
        accuracy_score: float,
        sim_score: float | None,
    ) -> float:
        """Weighted combine. sim_score=None folds sim weight into accuracy."""
```

**Reward computation:** the `DegradationReport` (Phase 158 `parasitics.py`) gives per-metric deltas (`gain_delta_db`, `noise_delta_db`, `thd_delta_percent`, `bw_delta_hz`). `compute_sim_score` normalizes these against spec tolerances (e.g. gain delta < 0.5 dB = 1.0; > 3 dB = 0.0) and takes the min (worst-metric-wins, since one detuned node fails the circuit). This is the *physical* signal: a placement that routes cleanly (high RES) but detunes a high-impedance node (high gain delta) gets penalized — something RES alone cannot detect.

**Integration into GRPO:** the `BoardChainReward` (Phase 9, `board_reward.py`) currently computes `0.2*fmt + 0.3*qual + 0.5*acc`. `SimRewardAdapter.combine` produces the new reward with the `sim` term. The adapter plugs into `grpo.py`'s reward hook exactly as `LegibilityRewardAdapter` does (via `from_config()`).

**Acceptance (TRAIN-04):**
- `SimRewardAdapter` is a drop-in: `combine()` returns a value in [-1, 1] matching `BoardChainReward.total_reward` range.
- Analog circuits with high parasitic degradation score lower than the same circuit with low degradation (the signal is real).
- Non-simulatable circuits (AK4619VN, MCUs) get the neutral 0.5 — no crash, no reward distortion.

### Vision pair builder (TRAIN-03 → Gemma format)

`vision_pair_builder.py` converts `PlacementPair`s into Gemma ChatML with rendered images. Reuses `vision_data_builder.build_vision_dataset()` for the HuggingFace dataset format and `format_gemma_chatml()` for the text encoding. The assistant turn is the RES score + a short rationale derived from the top-3 RES features ("high manhattan efficiency 0.91, low via density 0.4/mm², clean right-angle ratio 0.05").

---

## Wave 4 — Adapter Training (TRAIN-05, TRAIN-06)

**Goal:** Train the two adapters. This wave is *thin* — it configures and launches the existing training infrastructure on the Phase 159 datasets. No new training code; new configs + launch scripts.

**Files:** `scripts/run_159_training.py`, config files in `training_configs/159/`

### Task 6: Qwen text adapter (TRAIN-05)

SKIDL is pure text — Qwen needs no vision. The adapter trains via the existing `sft/trainer.py:run_sft_training()`:

- **Base model:** `Qwen/Qwen2.5-1.5B-Instruct` (existing default — MPS-trainable) for development; scale to `Qwen/Qwen2.5-7B-Instruct` on Vast.ai for production.
- **Dataset:** Wave 2 SFT pairs (`sft_pair_builder.py` output, Qwen ChatML format).
- **LoRA config:** existing defaults (`r=16, alpha=32, target_modules=[q,k,v,o]_proj`).
- **System prompt (new):** `SYSTEM_PROMPT_CIRCUIT_GEN` — "You are a circuit design assistant. Given a natural-language description, generate SKIDL Python code that builds the circuit. Use pin-name-based wiring (part['PIN'] += net). Output only valid Python."
- **Optional GRPO:** after SFT, run GRPO with `SimRewardAdapter` (Task 5) to optimize for circuits that not only parse but simulate within spec. This is the RL step that closes the loop on TRAIN-04.

**Vast.ai launch:** `scripts/run_159_training.py` delegates to `scripts/vast_train_kicad.py` (Phase 97) for the GPU run, with a config pointing at the Qwen dataset + `training_configs/159/qwen_circuit.yaml`.

**Acceptance (TRAIN-05):**
- Qwen adapter trains to completion (loss decreases, eval loss does not diverge).
- On a held-out NL→SKIDL eval set, the adapter generates SKIDL that `exec()`s into a valid `skidl.Circuit` at a measurable rate above the base model baseline.

### Task 7: Gemma vision adapter (TRAIN-06)

Enhances the Phase 98/97 Gemma routing model with placement-quality context:

- **Base model:** Gemma 4 12B (existing Phase 97 setup — `vision_lora_trainer.py`, mlx-vlm).
- **Dataset:** Wave 3 vision pairs (`vision_pair_builder.py` output — placement renders + RES labels).
- **Merge with existing data:** the Phase 159 vision pairs are merged with the existing Phase 97 Gemma dataset (200K maze vision + 6,696 PCB samples) via the existing `maze_vision_converter.py` merge CLI (Phase 97-03). The merged adapter registry entry records provenance.
- **LoRA config:** existing Phase 97 Gemma LoRA settings.

**Acceptance (TRAIN-06):**
- Gemma adapter trains to completion on the merged dataset.
- Adapter loads locally via mlx-vlm (Phase 97 verification path).
- Adapter registry (`adapter_registry.py`) records the new adapter with Phase 159 provenance.

---

## End-to-End Pipeline Summary

```
71K crawled repos (Phase 13 corpus)
        │
        ▼  [Wave 1: skidl_corpus.py — TRAIN-01]
~50K SKIDL L2 .py files  ──────────────────────────────┐
        │                                                │
        ▼  [Wave 2: nl_describer.py — TRAIN-02]         │
(NL description, SKIDL) pairs                            │ (Phase 158 SPICE — runs in parallel)
        │                                                │        │
        ▼  [Wave 2: sft_pair_builder.py — TRAIN-07]     │        ▼
Qwen ChatML JSONL (train/val)                            │   DegradationReport
        │                                                │   (pre vs post-route sim delta)
        ▼  [Wave 4: Qwen SFT/GRPO — TRAIN-05]           │        │
Qwen text adapter (circuit generation)                  │        ▼
                                                        │  [Wave 3: sim_reward_adapter.py — TRAIN-04]
~50K SKIDL L2 .py ──► floor plan (P157) ──► PCB ──► Quilter ─► RES score
                                        │                       │      │
                                        ▼                       │      ▼
                                  PCB render PNG                │  sim_score (physical)
                                        │                       │      │
                                        ▼  [Wave 3: vision_pair_builder — TRAIN-03/06/07]
                                  Gemma ChatML + images ◄───────┘      │
                                        │                              │
                                        ▼  [Wave 4: Gemma LoRA — TRAIN-06] │
                                  Gemma vision adapter (routing)         │
                                                                        │
                                  ┌─────────────────────────────────────┘
                                  ▼
                          BoardChainReward + sim_score  →  GRPO loop  →  refined Qwen adapter
```

---

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Conversion yield < 40K (legacy schemas, missing libs) | Medium | Start from 71K precisely to absorb failures; `max_failures=0.30` budget; log every failure for triage. Fall back to L1-or-connector modeling (pitfall #1) for multi-unit symbols. |
| NL descriptions are noisy (auto-generated labels) | High (expected) | `corpus_qa.py` stratified spot-check; exclude `confidence < 0.4`; README enrichment for the ~25% that have one. The ERC/SPICE gates in Phase 160 are the real correctness filter — noisy NL just means a smaller effective training set, not wrong circuits. |
| Quilter too slow for 50K circuits | Medium | `max_components=200` cap; subsample to ~10K circuits for placement pairs (enough for vision LoRA); parallelize across Vast.ai instances. |
| SPICE unavailable for most circuits (digital-heavy corpus) | High (per SchGen) | `sim_score` defaults to neutral 0.5 for non-analog. Analog sub-circuits (~15-20% of corpus) get the physical signal. This is by design, not a failure. |
| Reward hacking (model emits degenerate SKIDL to game sim_score) | Low | Reuse Phase 9 `reward_hacking.py` + `anti_hack.py` smooth penalties. ERC gate (Phase 160) is a hard filter — non-functional circuits never score. |
| Memory/disk for 50K rendered PNGs | Medium | Render at 1024×768 (existing default); store on B2 (Phase 97 pattern); lazy render during dataset construction. |

---

## Success Criteria Traceability (ROADMAP §159)

| ROADMAP criterion | Where satisfied |
|---|---|
| 1. 71K repos convert to SKIDL (batch, parallelizable) | Wave 1 Task 1 — `build_skidl_corpus()` |
| 2. NL descriptions per circuit (SFT pairs) + placement→routing pairs from Quilter | Wave 2 Task 2 (NL) + Wave 3 Task 4 (placement pairs) |
| 3. SPICE degradation feeds `BoardChainReward` as `sim_score` | Wave 3 Task 5 — `SimRewardAdapter` |
| 4. Qwen text adapter (circuit gen) + Gemma vision adapter (routing, enhanced Phase 98) | Wave 4 Tasks 6 + 7 |
| 5. Format matches `generate_gap_training_data.py` | Wave 1 Task 3 — format parity contract + test |
