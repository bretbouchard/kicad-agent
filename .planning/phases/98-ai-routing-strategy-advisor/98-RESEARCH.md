# Phase 98: AI Routing Strategy Advisor - Research

**Researched:** 2026-06-25
**Domain:** Vision LLM inference, structured output extraction, routing strategy advisory
**Confidence:** HIGH (contract verified against source, adapter verified on disk, training data inspected)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **Reframe:** Phase 98 is an ADVISOR, not a closed loop. It produces `RoutingStrategyResult` consumed by the Phase 100 orchestrator. It does NOT parse coordinates to ops directly.
- **Dependency chain:** Phase 99 (multi-layer backend) + Phase 100 (orchestrator with pluggable `RoutingStrategy` interface) must be complete. Both are complete (see STATE.md).
- **Trained adapter:** Use existing V2 LoRA at `/Volumes/Storage/models/kicad-agent/adapters/kicad-vision-v2-mlx/` — rank 64, 2000 steps, loss 0.06, ~98.7% token accuracy. NO RETRAINING.
- **Existing pipeline:** Extend `KiCadVisionPipeline` at `src/kicad_agent/inference/vision_pipeline.py`.
- **Safety:** All model-emitted coordinates/net refs/layers validated before application. Invalid output → deterministic fallback (Phase 100 R-6). DRC is mandatory even with AI guidance.

### Claude's Discretion
- Prompt design for structured JSON extraction (training data is free-text, so prompt engineering bridges the gap)
- Whether to feed image-only or image+netlist text (CONTEXT.md Open Question 1)
- Re-strategize cadence during routing (CONTEXT.md Open Question 2)
- AI vs Freerouting disagreement resolution (CONTEXT.md Open Question 3)

### Deferred Ideas (OUT OF SCOPE)
- Retraining the model (use existing V2 adapter)
- Building a new router (using Freerouting Phase 99 + existing A*)
- Closed-loop autonomous routing without human approval (Phase 100 gates every strategy through approval)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| R-1 | `KiCadVisionPipeline` wired into `RoutingOrchestrator` via `RoutingStrategy` interface | Strategy Protocol verified (`strategy.py:114-146`). Implement `AiRoutingStrategy` class with `strategize(board_state, netlist) -> RoutingStrategyResult`. Constructor takes `KiCadVisionPipeline` + `PcbIR` (for rendering). Protocol uses structural subtyping — no inheritance needed. |
| R-2 | Strategy prompt emits structured JSON | CRITICAL GAP: Training data contains free-text analysis (6696 samples, 0 with strategy JSON). Must use prompt engineering + JSON grammar constraints. mlx-vlm 0.6.3 supports `GenerationResult`. Recommend few-shot prompt with schema example + temperature 0.0 for determinism. |
| R-3 | Strategy-to-constraints translator | `RoutingStrategyResult` already IS the contract. Translator parses model JSON → builds `RoutingStrategyResult(net_priorities, layer_hints, keepouts, router_assignment, routing_notes)`. Orchestrator currently only consumes `net_priorities` + `router_assignment`; `layer_hints`/`keepouts` land in audit trail (forward-looking). |
| R-4 | Validation gate | `Keepout` bounds checked against `BoardState.board_bounds`. Net names checked against `netlist.keys()`. Layer names validated via regex `^(F\|B\|In\d+)\.Cu$` against `NativeBoard.layers` (from `general.layers` tuple). Orchestrator's `_validate_strategy_result` (H4) is the belt-and-suspenders second gate. |
| R-5 | Eval harness: AI-guided vs deterministic baseline | Pattern from `scripts/phase99_baseline.py` — `FixtureMetrics` dataclass with `completion_pct`, `via_count`, `total_trace_length_mm`, `drc_pass`. Compare AI strategy vs `DeterministicStrategy` on 3 fixtures (smd_test_board, RaspberryPi-uHAT, phase99_synthetic_4layer). |
| R-6 | Graceful degradation | On invalid/empty model output → return `DeterministicStrategy().strategize(board_state, netlist)` with `routing_notes="ai_fallback_to_deterministic"`. Orchestrator's H4 validation raises `ValueError` if fallback also fails — but DeterministicStrategy is trusted code. |
</phase_requirements>

## Summary

Phase 98 wires the trained Gemma 4 12B V2 vision LoRA into the Phase 100 `RoutingOrchestrator` as a `RoutingStrategy` implementation. The architecture is clean: `AiRoutingStrategy` implements the Protocol, renders the PCB to a PNG via `kicad-cli`, passes it to `KiCadVisionPipeline.generate_from_image()`, parses the model's output into structured JSON, validates every field, and returns a `RoutingStrategyResult`. On any failure (model unavailable, unparseable output, invalid coordinates/nets/layers), it falls back to `DeterministicStrategy`.

**The central challenge is prompt engineering, not integration.** Inspection of the 6696-sample training dataset (`training_output/vision_data/train`) revealed that zero samples contain routing strategy JSON (`net_priorities`, `layer_hints`, `keepouts`). The training data is free-text PCB analysis — component descriptions, board summaries, and routing quality scores. Only 3 of 6696 samples are routing-related, and they produce natural-language "Routing Elegance Score" assessments. The model learned to describe PCBs; it did not learn to emit structured strategy. Phase 98 must bridge this gap with few-shot prompting, JSON schema examples in the prompt, and robust parsing that extracts whatever JSON fragments the model produces.

**Primary recommendation:** Build `AiRoutingStrategy` as a thin adapter around the existing `KiCadVisionPipeline`. Invest the bulk of effort in (1) prompt design with a concrete JSON schema example and 2-3 few-shot exemplars, (2) a defensive JSON extractor that handles markdown fences, partial JSON, and natural-language preambles, and (3) the validation gate (R-4) that rejects impossible outputs before they reach the orchestrator. Treat the eval harness (R-5) as the long pole — it needs Freerouting installed (currently missing) and must run end-to-end on 3 fixtures.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| PCB rendering to PNG | CLI subprocess (kicad-cli) | Export module | kicad-cli is the authoritative renderer; `pcb_image_renderer.py` wraps it |
| Vision model inference | Local model (mlx-vlm) | — | Gemma 4 12B runs on Apple Silicon via MLX; no API calls |
| Strategy JSON extraction | Python parsing layer | — | Model emits free-text; parser extracts structured JSON |
| Strategy validation | AiRoutingStrategy (R-4 gate) | Orchestrator (H4 gate) | Two-layer defense: Phase 98 validates semantic correctness, orchestrator validates structural correctness |
| Routing execution | RoutingOrchestrator (Phase 100) | Freerouting / A* | Phase 98 produces strategy; Phase 100 consumes it — strict separation |
| Fallback policy | DeterministicStrategy | — | On any AI failure, deterministic heuristics from Phase 99 baseline take over |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| mlx-vlm | 0.6.3 | Vision LLM inference on Apple Silicon | Only MLX-based VLM runner; matches training environment `[VERIFIED: pip install]` |
| Pillow (PIL) | 12.2.0 | Image handling for model input | Already installed; required by `render_pcb_layer_png` and `KiCadVisionPipeline.generate_from_image` `[VERIFIED: pip list]` |
| pydantic | 2.x (existing) | Config + schema validation | Project standard for frozen configs (`KiCadVisionConfig` already uses it) `[CITED: pyproject.toml]` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| datasets | 5.0.0 (just installed) | Load training data for few-shot exemplars | Pulling real board analysis examples for prompt context |
| kicad-cli | 10.0.1 | PCB rendering to PNG/SVG | `pcb export svg` → PIL conversion (existing pattern in `pcb_image_renderer.py`) `[VERIFIED: command -v kicad-cli]` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| mlx-vlm | transformers + accelerate | mlx-vlm is Apple-native, 2-3x faster on MPS, matches training. transformers would require CUDA. |
| Free-text prompt + JSON parser | JSON grammar constraints (outlines/guidance) | mlx-vlm 0.6.3 has `llguidance` installed but grammar-constrained decoding for Gemma vision is unverified. Free-text + robust parser is safer for v1. |
| kicad-cli SVG export | kicad-cli 3D render (`pcb render`) | SVG 2D top-down is what training used (`render_pcb_layer_png`). 3D render introduces perspective distortion the model wasn't trained on. |

**Installation:**
```bash
# mlx-vlm was missing from pyproject.toml — installed during research:
.venv/bin/python -m pip install mlx-vlm datasets
# Verify:
.venv/bin/python -c "import mlx_vlm; print(mlx_vlm.__version__)"  # 0.6.3
```

**CRITICAL: mlx-vlm is NOT declared in pyproject.toml** (not even as optional dependency). The existing `KiCadVisionPipeline` imports it lazily inside methods. Phase 98 should add it to `[project.optional-dependencies]` under a `vision` extra to make the dependency explicit. `[VERIFIED: pyproject.toml grep shows no mlx-vlm]`

## Architecture Patterns

### System Architecture Diagram

```
                    ┌─────────────────────────────────┐
                    │       AiRoutingStrategy          │
                    │  (implements RoutingStrategy)    │
                    │                                  │
  BoardState ──────►│  1. Render PCB → PNG             │
  Netlist ─────────►│  2. Build prompt (few-shot JSON) │
                    │  3. KiCadVisionPipeline.generate │
                    │  4. Extract JSON from free-text  │
                    │  5. Validate (R-4 gate)          │
                    │  6. Build RoutingStrategyResult  │
                    └──────────────┬───────────────────┘
                                   │
                          (success)│(failure/invalid)
                                   │
                   ┌───────────────▼───────────────┐
                   │                               │
                   ▼                               ▼
  ┌────────────────────────┐        ┌────────────────────────┐
  │  RoutingStrategyResult │        │  DeterministicStrategy │
  │  (AI-guided)           │        │  .strategize() fallback│
  └───────────┬────────────┘        └───────────┬────────────┘
              │                                 │
              └──────────┬──────────────────────┘
                         │
                         ▼
          ┌──────────────────────────────────┐
          │   RoutingOrchestrator            │
          │   (Phase 100 — unchanged)        │
          │   _validate_strategy_result (H4) │
          │   → dispatch per-net to A*/FR    │
          │   → audit trail (JSONL, fsync)   │
          │   → rollback if DRC fails        │
          └──────────────────────────────────┘
```

Data flows top-to-bottom: `AiRoutingStrategy` is the only new component. The orchestrator, audit trail, rollback, and dispatch are all Phase 100 — unchanged.

### Recommended Project Structure
```
src/kicad_agent/routing/
├── strategy.py              # Phase 100 — Protocol + DeterministicStrategy (UNCHANGED)
├── orchestrator.py          # Phase 100 — RoutingOrchestrator (UNCHANGED)
├── ai_strategy.py           # NEW — AiRoutingStrategy (R-1, R-2, R-3)
├── strategy_validator.py    # NEW — R-4 validation gate (coordinates, nets, layers)
├── strategy_parser.py       # NEW — JSON extraction from free-text model output (R-2)
└── strategy_prompts.py      # NEW — Prompt templates + few-shot exemplars (R-2)

scripts/
└── phase98_eval.py          # NEW — R-5 eval harness (AI vs deterministic baseline)

tests/
├── test_phase98_ai_strategy.py       # R-1, R-2, R-3 unit tests
├── test_phase98_strategy_validator.py # R-4 validation gate tests
├── test_phase98_strategy_parser.py    # R-2 JSON extraction tests
└── test_phase98_eval.py              # R-5 eval harness smoke test
```

### Pattern 1: Thin Adapter Around Existing Pipeline
**What:** `AiRoutingStrategy` wraps `KiCadVisionPipeline` — it does NOT subclass or modify it. The pipeline's `generate_from_image(image, prompt) -> str` interface is preserved unchanged.
**When to use:** Always for Phase 98. The pipeline is tested (`tests/inference/test_vision_pipeline.py`) and used by `evaluation/vision_benchmark.py`. Wrapping (not modifying) keeps those tests green.
**Example:**
```python
# Source: pattern from evaluation/vision_benchmark.py:73,142
class AiRoutingStrategy:
    def __init__(self, pipeline: KiCadVisionPipeline, validator: StrategyValidator):
        self._pipeline = pipeline
        self._validator = validator

    def strategize(self, board_state, netlist) -> RoutingStrategyResult:
        image = self._render_board(...)  # uses pcb_image_renderer
        prompt = build_strategy_prompt(board_state, netlist)
        raw = self._pipeline.generate_from_image(image, prompt)
        parsed = parse_strategy_json(raw)  # R-2 parser
        result = build_result(parsed, board_state, netlist)  # R-3 translator
        self._validator.validate(result, board_state, netlist)  # R-4 gate
        return result
```

### Pattern 2: Defensive JSON Extraction
**What:** The model emits free-text (training data shows natural language, not JSON). The parser must handle: markdown fences ```` ```json ... ``` ``, natural-language preambles ("Here is the strategy:"), partial JSON, and missing fields.
**When to use:** Always — this is the bridge between model output and structured data.
**Example:**
```python
# Extract JSON from mixed free-text + JSON output
def parse_strategy_json(raw: str) -> dict:
    # 1. Try direct json.loads (ideal case)
    # 2. Extract from ```json ... ``` fences
    # 3. Find first { ... last } and try json.loads
    # 4. If all fail, return {} → triggers fallback
```

### Pattern 3: Two-Layer Validation
**What:** Phase 98's R-4 validation gate checks semantic correctness (coordinates in bounds, nets exist, layers valid for stackup). Phase 100's H4 `_validate_strategy_result` checks structural correctness (every net has a backend, backend is valid enum). Both must pass.
**When to use:** On every `RoutingStrategyResult` produced by `AiRoutingStrategy` before returning it.
**Why two layers:** R-4 catches domain-specific errors (In3.Cu on a 2-layer board). H4 catches contract errors (unknown net, invalid enum). Defense in depth — the model output is untrusted.

### Anti-Patterns to Avoid
- **Modifying `KiCadVisionPipeline`:** It's tested and used elsewhere. Wrap it, don't change it. Adding strategy-specific logic to the pipeline couples rendering/inference to routing.
- **Regex on S-expressions:** Phase 100 H2 explicitly forbids this. Use `NativeParser` + `PcbIR` for board queries.
- **Trusting model coordinates:** The model can hallucinate coordinates like `<point 999.9, 999.9>`. Every coordinate in keepouts must be validated against `BoardState.board_bounds`.
- **Skipping the fallback:** Even if the model output "looks right," run it through validation. The model can produce syntactically valid JSON with semantically wrong values (e.g., net names that don't exist in the netlist).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| PCB rendering | Custom renderer | `render_pcb_layer_png` in `export/pcb_image_renderer.py` | Already handles kicad-cli subprocess, SVG→PNG conversion, fallback to 3D. Used in training data generation. |
| Model inference | Raw mlx-vlm calls | `KiCadVisionPipeline.generate_from_image()` | Already handles chat template, lazy imports, error recovery. |
| Board/netlist extraction | Regex on .kicad_pcb | `NativeParser.parse_pcb()` → `PcbIR.from_native()` → `extract_netlist_with_refs()` | Phase 76+76 verified. Handles all KiCad 10 constructs. |
| Layer stackup | Manual layer counting | `NativeBoard.layers` (via `general.layers` tuple) or `LayerStackup.from_board()` | Phase 99 R-4 typed this as `tuple[NativeStackupLayer, ...]`. |
| Routing execution | Custom dispatch | `RoutingOrchestrator.route_board()` (Phase 100) | Already does dispatch, audit, rollback. Phase 98 only produces strategy. |
| Deterministic fallback | Heuristic reimplementation | `DeterministicStrategy` from `strategy.py` | Phase 100's 5-case dispatch. Instantiate and call `.strategize()`. |

**Key insight:** Phase 98 is a thin integration layer. The heavy lifting (rendering, inference, parsing, routing) already exists. The novel work is prompt design, JSON extraction, and validation.

## Common Pitfalls

### Pitfall 1: Training Distribution Mismatch
**What goes wrong:** The model was trained on free-text PCB analysis. Asking it to emit structured JSON may produce poor results because the model has never seen that output format.
**Why it happens:** Training data inspection (`training_output/vision_data/train`, 6696 samples) shows zero samples with strategy JSON. The 3 routing-related samples produce "Routing Elegance Score: 0.669" text. The model's learned distribution is natural language.
**How to avoid:** (1) Use few-shot prompting with 2-3 concrete JSON examples in the prompt. (2) Set temperature=0.0 for deterministic output. (3) Build a robust JSON extractor that handles partial output. (4) Accept that SC-1 (≥95% parseable) may be hard to hit — the fallback (R-6) exists for this reason. (5) If SC-1 fails, consider adding netlist as text context (Open Question 1 resolution).
**Warning signs:** Model output starts with "Here is" or "The routing strategy is" instead of `{`. JSON is wrapped in markdown fences. JSON fields are present but values are wrong types (strings instead of arrays).

### Pitfall 2: 8bit vs 4bit Base Model Mismatch
**What goes wrong:** The pipeline defaults to `mlx-community/gemma-4-12B-it-8bit` but only the 4bit version is cached locally (`~/.cache/huggingface/hub/models--mlx-community--gemma-4-12B-it-4bit`). The adapter was trained against the 8bit base.
**Why it happens:** Training ran on a different machine or the 8bit model was downloaded and later deleted. The adapter `adapter_config.json` specifies `base_model_name_or_path: google/gemma-4-12b-it` — but MLX LoRA fuses against the quantized MLX weights, so the adapter expects the 8bit MLX base.
**How to avoid:** (1) Download the 8bit model before first run: `huggingface-cli download mlx-community/gemma-4-12B-it-8bit` (~13GB). (2) OR override `KiCadVisionConfig(model_name="mlx-community/gemma-4-12B-it-4bit")` and accept potential quality degradation. (3) Document the model path in the config so it's explicit, not implicit.
**Warning signs:** Model loads but output quality is significantly worse than training metrics suggest. Adapter fusion fails with shape mismatch error.

### Pitfall 3: Freerouting Not Installed (Blocks R-5 Eval)
**What goes wrong:** `command -v freerouting` returns NOT FOUND. The eval harness (R-5) needs Freerouting to route the nets that `DeterministicStrategy` assigns to `RouterBackend.FREEROUTING`.
**Why it happens:** Phase 99 hardened Freerouting integration but the JAR isn't installed on this machine. `is_freerouting_available()` returns False.
**How to avoid:** (1) Install Freerouting before running the eval: `scripts/install_freerouting.sh` (if exists) or manual JAR download. (2) For the eval harness, the orchestrator already falls back to A* when Freerouting is unavailable — but this changes the baseline. Document the discrepancy. (3) Mark R-5 eval tests as `@pytest.mark.integration` and skip if Freerouting unavailable.
**Warning signs:** Orchestrator logs "Freerouting failed (success=False); falling back to A*". Baseline completion rate is lower than Phase 99 SC-4 metrics (50% for smd_test_board).

### Pitfall 4: Orchestrator Doesn't Consume layer_hints/keepouts
**What goes wrong:** Phase 98 populates `layer_hints` and `keepouts` in `RoutingStrategyResult`, but the Phase 100 orchestrator only reads `net_priorities` and `router_assignment`. The hints are metadata-only.
**Why it happens:** The orchestrator was built before Phase 98. The `layer_hints` and `keepouts` fields are documented as "Phase 98 may populate" — they land in the audit trail but don't affect routing behavior.
**How to avoid:** This is acceptable for an "advisor" phase. The value of Phase 98 is in (1) `net_priorities` (routing order — diff pairs first) and (2) `router_assignment` (which backend per net). Document that `layer_hints`/`keepouts` are forward-looking and will be consumed in a future phase. Do NOT modify the orchestrator in Phase 98 — that's out of scope.
**Warning signs:** Eval metrics (completion rate, via count) don't improve despite "good" layer_hints. This is expected — the hints aren't acted upon yet.

### Pitfall 5: 5.6 tok/s Inference Latency
**What goes wrong:** The model loads at 23.8 GB and generates at 5.6 tok/s on Apple Silicon (per CONTEXT.md). A 2048-token generation takes ~6 minutes. For a board with 50 nets, this is acceptable (one-shot). For iterative re-strategizing, it's prohibitive.
**Why it happens:** Gemma 4 12B is a large model. MLX swaps to unified memory but bandwidth-limited.
**How to avoid:** (1) Strategize ONCE at the start (Open Question 2 resolution). (2) Reduce `max_tokens` to 1024 (strategy JSON is compact — a 50-net board needs ~500 tokens). (3) Cache the strategy result — if `board_state` hasn't changed, reuse the previous result. (4) Document latency in the eval harness.
**Warning signs:** Eval harness takes >30 minutes per fixture. CLI feels sluggish.

## Validation Gate Architecture (R-4)

The R-4 validation gate sits between JSON parsing and `RoutingStrategyResult` construction. It validates three categories:

### 1. Coordinate Bounds (Keepouts)
```python
def validate_keepout(keepout: Keepout, board_bounds: tuple[float, float, float, float]) -> None:
    x1, y1, x2, y2 = board_bounds  # (min_x, min_y, max_x, max_y)
    if not (x1 <= keepout.x1 <= x2 and x1 <= keepout.x2 <= x2):
        raise ValueError(f"keepout x out of bounds: {keepout}")
    if not (y1 <= keepout.y1 <= y2 and y1 <= keepout.y2 <= y2):
        raise ValueError(f"keepout y out of bounds: {keepout}")
    # x1 < x2, y1 < y2 (positive area)
    if keepout.x1 >= keepout.x2 or keepout.y1 >= keepout.y2:
        raise ValueError(f"keepout has zero/negative area: {keepout}")
```

### 2. Net Name Validation
```python
def validate_net_references(
    net_priorities: list[str],
    router_assignment: dict[str, RouterBackend],
    layer_hints: dict[str, str],
    netlist: dict[str, list[Pin]],
) -> None:
    known_nets = set(netlist.keys())
    for net in net_priorities:
        if net not in known_nets:
            raise ValueError(f"unknown net in priorities: {net}")
    for net in router_assignment:
        if net not in known_nets:
            raise ValueError(f"unknown net in assignment: {net}")
    for net in layer_hints:
        if net not in known_nets:
            raise ValueError(f"unknown net in layer_hints: {net}")
    # Every net in netlist must have a router_assignment
    missing = known_nets - set(router_assignment.keys())
    if missing:
        raise ValueError(f"nets missing router_assignment: {missing}")
```

### 3. Layer Assignment Validation
```python
import re

_COPPER_LAYER_RE = re.compile(r"^(F|B|In\d+)\.Cu$")

def validate_layer_hints(
    layer_hints: dict[str, str],
    board: NativeBoard,
) -> None:
    # Extract valid copper layer names from board stackup
    valid_layers: set[str] = set()
    if board.setup and board.setup.stackup:
        for layer in board.setup.stackup.layers:
            if hasattr(layer, "type") and layer.type == "copper":
                valid_layers.add(layer.name)
    # Fallback: derive from general.layers (may be untyped strings)
    if not valid_layers:
        for layer_name in board.general.layers:
            if _COPPER_LAYER_RE.match(str(layer_name)):
                valid_layers.add(str(layer_name))
    # Default 2-layer if no stackup info
    if not valid_layers:
        valid_layers = {"F.Cu", "B.Cu"}

    for net, layer in layer_hints.items():
        if layer not in valid_layers:
            raise ValueError(
                f"invalid layer '{layer}' for net '{net}' "
                f"(valid: {sorted(valid_layers)})"
            )
```

**Test coverage (SC-4):** Unit tests with synthetic invalid outputs — out-of-bounds coordinates, unknown net names, `In3.Cu` on a 2-layer board. All must be rejected. The validation gate must reject 100% of synthetic invalid outputs.

## Eval Harness Design (R-5)

### Architecture
The eval harness compares two strategies on the same fixtures:

```
For each fixture board:
  1. Parse PCB → extract netlist + board_state
  2. Run DeterministicStrategy → orchestrator.route_board() → baseline metrics
  3. Run AiRoutingStrategy → orchestrator.route_board() → AI metrics
  4. Run kicad-cli pcb drc on both results
  5. Compare: completion_pct, via_count, total_trace_length_mm, drc_pass
```

### Metrics (from `scripts/phase99_baseline.py`)
```python
@dataclass(frozen=True)
class StrategyEvalResult:
    fixture_name: str
    strategy_name: str  # "deterministic" or "ai"
    total_nets: int
    routed_nets: int
    completion_pct: float
    via_count: int
    total_trace_length_mm: float
    drc_pass: bool
    drc_unconnected: int
    elapsed_seconds: float
    # AI-specific
    model_output_chars: int  # raw output length
    parse_success: bool      # did JSON extraction succeed?
    validation_passed: bool  # did R-4 gate pass?
```

### Success Criteria Mapping
| SC | Metric | Threshold |
|----|--------|-----------|
| SC-1 | `parse_success` rate across fixtures | ≥95% |
| SC-2 | AI beats deterministic on ≥2 of {completion_pct, via_count, trace_length} | majority |
| SC-3 | `drc_pass` for AI ≥ `drc_pass` for deterministic | no regression |
| SC-4 | Validation gate rejects 100% synthetic invalid | unit tests |
| SC-5 | End-to-end on ≥3 fixtures | all 3 fixtures complete |

### Fixtures (verified present)
- `tests/fixtures/smd_test_board.kicad_pcb` — 2-layer, ~50% baseline completion
- `tests/fixtures/RaspberryPi-uHAT/RaspberryPi-uHAT.kicad_pcb` — 2-layer, ~3.2% baseline
- `tests/fixtures/phase99_synthetic_4layer_mixedsignal.kicad_pcb` — 4-layer, has zones

## Graceful Degradation Strategy (R-6)

### Fallback Chain
```
1. AiRoutingStrategy.strategize() attempts:
   a. Render PCB → PNG (may fail if kicad-cli unavailable)
   b. Model inference (may fail if mlx-vlm/model unavailable, or returns "")
   c. JSON extraction (may fail if output is unparseable)
   d. R-4 validation (may fail if coordinates/nets/layers invalid)

2. On ANY failure in steps a-d:
   → Log the failure reason to audit trail
   → Return DeterministicStrategy().strategize(board_state, netlist)
   → Set routing_notes="ai_fallback: <reason>"

3. DeterministicStrategy is trusted code — it always succeeds.
```

### Implementation
```python
class AiRoutingStrategy:
    def strategize(self, board_state, netlist) -> RoutingStrategyResult:
        try:
            image = self._render_board(self._pcb_path)
            prompt = build_strategy_prompt(board_state, netlist)
            raw = self._pipeline.generate_from_image(image, prompt)
            if not raw or len(raw) < 10:
                raise ValueError("empty or too-short model output")
            parsed = parse_strategy_json(raw)
            if not parsed:
                raise ValueError("JSON extraction failed")
            result = build_result(parsed, board_state, netlist)
            self._validator.validate(result, board_state, netlist)
            return result
        except Exception as exc:
            logger.warning("AI strategy failed, falling back: %s", exc)
            fallback = DeterministicStrategy().strategize(board_state, netlist)
            return replace(fallback, routing_notes=f"ai_fallback: {exc}")
```

**Why catch broad Exception:** The model output is untrusted. Any failure mode (network, parsing, validation) must not crash the orchestrator. The fallback is always safe.

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Model can't produce structured JSON (training mismatch) | HIGH | HIGH (SC-1 fails) | Few-shot prompting, robust parser, temperature 0.0. If SC-1 fails, escalate to user — may need to add JSON-formatted examples to next training run. |
| 8bit base model not downloaded | MEDIUM | HIGH (can't load model) | Download before first run OR override config to 4bit with documented quality risk. |
| Freerouting not installed (blocks R-5 eval) | HIGH | MEDIUM (eval incomplete) | Install Freerouting JAR. If unavailable, document that orchestrator falls back to A* and baseline metrics differ from Phase 99 SC-4. |
| Inference latency (5.6 tok/s) makes eval slow | MEDIUM | LOW (functional, just slow) | Reduce max_tokens to 1024. Strategize once per board. Cache results. |
| Model hallucinates coordinates that pass bounds check but are wrong | LOW | MEDIUM (bad keepouts) | Orchestrator doesn't consume keepouts yet (Pitfall 4), so impact is limited. Future phase must add semantic validation. |
| mlx-vlm version drift breaks adapter loading | LOW | HIGH (can't load model) | Pin mlx-vlm==0.6.3 in pyproject.toml `vision` extra. Test adapter load in Wave 0. |

## Validation Architecture

> `workflow.nyquist_validation` is `true` in `.planning/config.json` — this section is required.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x (existing) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `.venv/bin/python -m pytest tests/test_phase98_*.py -q -x` |
| Full suite command | `.venv/bin/python -m pytest tests/test_phase98_*.py tests/test_phase100_*.py tests/test_routing*.py -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| R-1 | AiRoutingStrategy implements Protocol | unit | `pytest tests/test_phase98_ai_strategy.py::TestProtocolCompliance -x` | ❌ Wave 0 |
| R-2 | JSON extraction from free-text | unit | `pytest tests/test_phase98_strategy_parser.py -x` | ❌ Wave 0 |
| R-2 | Prompt includes schema + few-shot | unit | `pytest tests/test_phase98_ai_strategy.py::TestPromptConstruction -x` | ❌ Wave 0 |
| R-3 | Translator builds RoutingStrategyResult | unit | `pytest tests/test_phase98_ai_strategy.py::TestResultTranslation -x` | ❌ Wave 0 |
| R-4 | Reject out-of-bounds coordinates | unit | `pytest tests/test_phase98_strategy_validator.py::TestCoordinateBounds -x` | ❌ Wave 0 |
| R-4 | Reject unknown net names | unit | `pytest tests/test_phase98_strategy_validator.py::TestNetValidation -x` | ❌ Wave 0 |
| R-4 | Reject impossible layers (In3.Cu on 2-layer) | unit | `pytest tests/test_phase98_strategy_validator.py::TestLayerValidation -x` | ❌ Wave 0 |
| R-4 | 100% synthetic invalid rejection | unit | `pytest tests/test_phase98_strategy_validator.py::TestSyntheticInvalid -x` | ❌ Wave 0 |
| R-5 | Eval harness smoke test (mocked model) | unit | `pytest tests/test_phase98_eval.py::TestEvalHarnessSmoke -x` | ❌ Wave 0 |
| R-5 | AI vs deterministic comparison | integration | `pytest tests/test_phase98_eval.py::TestAiVsDeterministic -x -m integration` | ❌ Wave 0 |
| R-6 | Fallback on empty model output | unit | `pytest tests/test_phase98_ai_strategy.py::TestFallback -x` | ❌ Wave 0 |
| R-6 | Fallback on invalid JSON | unit | `pytest tests/test_phase98_ai_strategy.py::TestFallbackInvalidJson -x` | ❌ Wave 0 |
| R-6 | Fallback on validation failure | unit | `pytest tests/test_phase98_ai_strategy.py::TestFallbackValidationFail -x` | ❌ Wave 0 |
| SC-5 | End-to-end on 3 fixtures | integration | `pytest tests/test_phase98_eval.py::TestEndToEnd -x -m integration` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `.venv/bin/python -m pytest tests/test_phase98_*.py -q -x` (unit tests only, <30s)
- **Per wave merge:** `.venv/bin/python -m pytest tests/test_phase98_*.py tests/test_phase100_*.py -q` (Phase 100 regression check)
- **Phase gate:** Full suite green + integration tests (with model + Freerouting) before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_phase98_ai_strategy.py` — R-1, R-2, R-3, R-6 unit tests
- [ ] `tests/test_phase98_strategy_validator.py` — R-4 validation gate tests (SC-4)
- [ ] `tests/test_phase98_strategy_parser.py` — R-2 JSON extraction tests
- [ ] `tests/test_phase98_eval.py` — R-5 eval harness (unit + integration)
- [ ] `tests/conftest_phase98.py` — shared fixtures (mock pipeline, mock image, synthetic board_state)
- [ ] Register `integration` marker if not already (Phase 100 added it — verify)

## Open Questions (RESOLVED)

### Q1: Image-only vs image+netlist input
**Recommendation:** Start with IMAGE-ONLY (matches training distribution). If SC-1 (<95% parseable) fails, add netlist as text context.

**Rationale:** Training data (`vision_data_builder.py:193-207`) used `[{"type": "image"}, {"type": "text", "text": vision_prompt}]` — no netlist text. The model learned to infer nets from the image. Adding netlist text in inference creates a distribution shift from training.

**Fallback plan:** If image-only produces <95% parseable JSON, modify the prompt to include the netlist as structured text: "The board has these nets: ['GND', 'VCC', 'SIG1', ...]". This gives the model explicit net names to reference, reducing hallucination.

### Q2: Re-strategize cadence
**Recommendation:** ONCE AT START. Do not re-strategize during routing.

**Rationale:** (1) Training was one-shot (single image → single analysis). (2) At 5.6 tok/s, re-strategizing per-net would take hours. (3) The board doesn't change during routing — the strategy is valid for the whole run. (4) Phase 100's orchestrator dispatches all nets in one `route_board()` call.

**Future extension:** If iterative routing is added later, re-strategize only on DRC failure (after rollback). This is out of scope for Phase 98.

### Q3: AI vs Freerouting disagreement
**Recommendation:** AI WINS for `router_assignment` (which backend). FREEROUTING WINS for execution details (trace paths, via positions).

**Rationale:** (1) `router_assignment` is a strategic decision — "use A* for this diff pair, Freerouting for this dense net." The AI's board-level view informs this. (2) Once a net is assigned to Freerouting, Freerouting optimizes the actual path — it has better algorithms for dense routing than the AI's coordinate suggestions. (3) The orchestrator already implements this separation: strategy picks the backend, backend executes the route.

**Conflict logging:** If the AI strategy assigns a net to A* but A* fails AND Freerouting would have succeeded, log this to the audit trail as `dispatch_reason="ai_assignment_suboptimal"`. This is data for future improvement, not a runtime intervention.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | mlx-vlm 0.6.3 is API-compatible with the adapter trained on 0.6.2 | Standard Stack | Adapter won't load; need to pin to 0.6.2 or retrain |
| A2 | The 8bit base model produces better output than 4bit with the 8bit-trained adapter | Pitfall 2 | Quality degradation; SC-1/SC-2 may fail if 4bit is used |
| A3 | Few-shot prompting can bridge the training distribution gap (free-text → JSON) | Pitfall 1 | SC-1 fails; need to either retrain with JSON examples or accept lower bar |
| A4 | Freerouting will be installed before R-5 eval runs | Pitfall 3 | Eval harness can't measure true baseline; A* fallback inflates AI's relative performance |
| A5 | The orchestrator's H4 validation is sufficient as a second gate (no need for a third) | Pattern 3 | Invalid strategy slips through; but H4 + R-4 cover different domains (structural vs semantic) |
| A6 | `NativeBoard.layers` returns usable copper layer names for validation | Validation Gate | May return untyped strings; regex fallback handles this |

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| mlx-vlm | R-1, R-2 (model inference) | ✓ (installed during research) | 0.6.3 | — |
| Pillow (PIL) | R-1 (image handling) | ✓ | 12.2.0 | — |
| datasets | Few-shot exemplar loading | ✓ (installed during research) | 5.0.0 | Hardcode exemplars in prompt template |
| kicad-cli | R-1 (PCB rendering) | ✓ | 10.0.1 | — |
| Gemma 4 12B 8bit MLX model | R-1 (base model) | ✗ | — | Use 4bit (cached) with quality risk, OR download 8bit (~13GB) |
| Trained V2 adapter | R-1 (LoRA weights) | ✓ | rank 64, 2000 steps | — |
| Freerouting | R-5 (eval baseline) | ✗ | — | A* fallback (changes baseline metrics) |
| Python 3.11 | All | ✓ | 3.11.13 | — |

**Missing dependencies with no fallback:**
- **Gemma 4 12B 8bit MLX model** — must be downloaded before first run. The adapter was trained against this base. Using 4bit may degrade quality. Download command: `huggingface-cli download mlx-community/gemma-4-12B-it-8bit`

**Missing dependencies with fallback:**
- **Freerouting** — orchestrator falls back to A* when unavailable. Eval harness will show lower baseline completion rates than Phase 99 SC-4 documented. Install Freerouting JAR for accurate baseline comparison.

## Sources

### Primary (HIGH confidence)
- `src/kicad_agent/routing/strategy.py` — RoutingStrategy Protocol, RoutingStrategyResult, DeterministicStrategy (verified line-by-line)
- `src/kicad_agent/routing/orchestrator.py` — RoutingOrchestrator, H4 validation, dispatch flow (verified line-by-line)
- `src/kicad_agent/inference/vision_pipeline.py` — KiCadVisionPipeline, KiCadVisionConfig (verified line-by-line)
- `training_output/vision_data/train` — 6696-sample HuggingFace dataset inspected directly (task type distribution, prompt format, assistant response format)
- `/Volumes/Storage/models/kicad-agent/adapters/kicad-vision-v2-mlx/adapter_config.json` — LoRA rank 64, base model google/gemma-4-12b-it
- `.planning/phases/100-routingorchestrator-and-human-approval-loop/100-02-SUMMARY.md` — Phase 100 completion report, 74/74 tests pass, 431 combined regression

### Secondary (MEDIUM confidence)
- `src/kicad_agent/training/vision_data_builder.py` — training data conversion logic, prompt templates (PCB_VISION_PROMPT, ROUTING_VISION_PROMPT)
- `scripts/phase99_baseline.py` — FixtureMetrics pattern for eval harness
- `src/kicad_agent/export/pcb_image_renderer.py` — render_pcb_layer_png implementation
- `src/kicad_agent/parser/pcb_native_types.py` — NativeBoard, NativeGeneral, NativeStackupLayer types

### Tertiary (LOW confidence)
- mlx-vlm 0.6.3 API stability with 0.6.2-trained adapter — `[ASSUMED]` based on semver; verify in Wave 0

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — mlx-vlm installed and verified (0.6.3), PIL verified, kicad-cli verified
- Architecture: HIGH — Protocol contract verified against source, all consumers traced
- Pitfalls: HIGH — training data inspected directly (6696 samples), model cache checked, Freerouting availability checked
- Validation gate: HIGH — all validation inputs (board_bounds, netlist, NativeBoard.layers) traced to verified sources
- Eval harness: MEDIUM — pattern from Phase 99 baseline, but Freerouting availability blocks true baseline measurement

**Research date:** 2026-06-25
**Valid until:** 2026-07-25 (30 days — stable codebase, no upstream API changes expected)
**Graph freshness note:** `graph.json` is 418h stale (built 2026-06-08). Semantic relationships are approximate — treat graph queries as advisory. All key findings verified by direct file reads, not graph queries.
