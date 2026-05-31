# Phase 41: PCB MMLU Benchmark

**Status:** PLANNING
**Requirements:** BENCH-01, BENCH-02
**Depends on:** Phase 37 (production hardening complete)
**Milestone:** v2.5

## Goal

Create a standardized multi-choice circuit analysis benchmark — the "PCB MMLU" — that measures kicad-agent's understanding of electronics design. This is the #1 credibility blocker: no professional takes an AI tool seriously without published benchmarks.

## Context

The evaluation benchmarks dimension is at 2/10. We have 1392+ tests that verify *operations work*, but nothing that tests whether the system *understands circuits*. Existing evaluation infrastructure in `training/evaluation.py` measures GRPO reward on maze-routing tasks — that's spatial reasoning, not circuit intelligence.

The benchmark needs 500+ questions across 8 categories, sourced from real schematics and datasheets in the analog-ecosystem project. Baseline: run Qwen2.5-0.5B LoRA against it. Target: >70% accuracy after fine-tuning.

## Plans

### Plan 41-01: PCB MMLU Benchmark Dataset (BENCH-01)

**Goal:** Generate 500+ multi-choice circuit analysis questions across 8 categories with ground truth.

**Categories:**
1. **Component Identification** — What does this component do? (given schematic context)
2. **Topology Recognition** — What type of circuit is this subcircuit? (amplifier, filter, oscillator, etc.)
3. **Signal Flow** — Trace the signal from input to output, identify gain stages, feedback paths
4. **Power Design** — Identify power rails, decoupling adequacy, regulator selection
5. **Pin Function** — What is the function of pin N on this IC in this circuit?
6. **Net Purpose** — What is the purpose of this net in the circuit?
7. **Design Rules** — Is this design rule satisfied? (bypass cap proximity, impedance match)
8. **Troubleshooting** — What is the root cause of this ERC violation?

**Schema:**
```python
class BenchmarkQuestion(BaseModel):
    id: str                          # "pcb-mmlu-0001"
    category: str                    # "topology_recognition"
    difficulty: Literal["easy", "medium", "hard"]
    question: str                    # "What type of circuit is formed by U22, R60-R65, C46-C48?"
    choices: list[str]               # ["Compressor", "Filter", "Oscillator", "Amplifier"]
    correct_index: int               # 0
    explanation: str                 # "U22 is a THAT4301 VCA, R60/R61 form the sidechain..."
    source: str                      # "compressor-stage.kicad_sch"
    source_type: Literal["schematic", "datasheet", "erc_report", "netlist"]
    tags: list[str]                  # ["vca", "compressor", "that4301"]

class BenchmarkDataset(BaseModel):
    version: str                     # "1.0.0"
    generated_at: str                # ISO timestamp
    questions: list[BenchmarkQuestion]
    metadata: dict                   # category counts, difficulty distribution, source distribution
```

**Question generation sources:**
1. **Schematics** (55 modules in analog-ecosystem): Extract subcircuits, ask about topology, function, signal flow
2. **ERC reports**: Generate troubleshooting questions from real violations
3. **Datasheets** (THAT4301, CD4066BE, NE5532, RP2040): Pin function, application circuit questions
4. **Netlists**: Net purpose, connectivity questions
5. **BOMs**: Component selection, value calculation questions

**Question generation algorithm:**
1. Parse each schematic → extract subcircuits (groups of connected components)
2. For each subcircuit, identify function (heuristic: IC type + surrounding passives)
3. Generate questions from templates per category:
   - Topology: "What type of circuit is formed by [components]?" with IC function as correct answer
   - Signal flow: "What is the signal path from [input] to [output]?" with traced path as correct answer
   - Pin function: "What is the function of [IC].[pin] in this circuit?" with datasheet function as correct answer
   - Troubleshooting: "[ERC violation description]. What is the root cause?" with classification as correct answer
4. Generate 3 plausible distractors per question (same category, wrong answer)
5. Validate: each question has exactly 1 correct answer, all distractors are plausible

**Distribution targets:**
- 60% medium difficulty, 20% easy, 20% hard
- Minimum 50 questions per category
- At least 5 different source schematics per category
- Questions must be answerable from the schematic context alone (no external references needed for easy/medium)

**Implementation:**
1. Create `src/kicad_agent/benchmarks/` package
2. Create `src/kicad_agent/benchmarks/question_generator.py` — template-based generation
3. Create `src/kicad_agent/benchmarks/dataset_builder.py` — orchestrates generation across sources
4. Output: `benchmarks/pcb-mmlu-v1.json` — the canonical benchmark file

**Tests:**
- All generated questions validate against BenchmarkQuestion schema
- No duplicate question IDs
- Correct answer index is within bounds
- Each category has >= 50 questions
- Difficulty distribution within 5% of targets
- No empty or whitespace-only fields
- Distractors are different from correct answer

---

### Plan 41-02: Benchmark Runner + Baseline Evaluation (BENCH-02)

**Goal:** Create a runner that evaluates any model against PCB MMLU and produces scored results.

**Schema:**
```python
class BenchmarkConfig(BaseModel):
    dataset_path: str                # Path to benchmark JSON
    model_name: str                  # "qwen2.5-0.5b-lora" or "baseline-random"
    split: Literal["all", "easy", "medium", "hard"] = "all"
    categories: list[str] | None = None  # Filter to specific categories
    max_questions: int | None = None

class BenchmarkResult(BaseModel):
    model_name: str
    dataset_version: str
    total_questions: int
    correct: int
    accuracy: float                  # overall accuracy
    category_accuracy: dict[str, float]  # per-category accuracy
    difficulty_accuracy: dict[str, float]  # per-difficulty accuracy
    evaluated_at: str                # ISO timestamp
    duration_seconds: float
```

**Runner design:**
1. Load benchmark dataset from JSON
2. For each question:
   a. Format as prompt: question + numbered choices
   b. Get model prediction (LLM completion or random baseline)
   c. Compare prediction to correct_index
3. Compute accuracy: overall, per-category, per-difficulty
4. Output: JSON results file + human-readable summary

**Model integrations:**
- `BaselineRandomModel` — random choice (lower bound)
- `BaselineHeuristicModel` — keyword matching (simple heuristic)
- `LocalLoRAModel` — Qwen2.5-0.5B with LoRA adapter (existing inference pipeline)
- `APIModel` — any OpenAI-compatible API (for Claude, GPT-4 comparisons)

**Integration with existing code:**
- Reuse `inference/evaluator.py` pattern for model loading
- Reuse `training/evaluation.py` `EvalResult` pattern for result reporting
- New module: `src/kicad_agent/benchmarks/runner.py`

**CLI interface:**
```bash
python -m kicad_agent.benchmarks.run \
  --dataset benchmarks/pcb-mmlu-v1.json \
  --model random \
  --output results/random-baseline.json

python -m kicad_agent.benchmarks.run \
  --dataset benchmarks/pcb-mmlu-v1.json \
  --model qwen2.5-0.5b-lora \
  --adapter-path models/kicad-lora-v1 \
  --output results/lora-v1.json
```

**Tests:**
- Random baseline achieves ~25% accuracy (4 choices) ± 10%
- Heuristic baseline achieves >25% accuracy
- BenchmarkResult schema validates for all model outputs
- Category accuracy dict has entry for every category in dataset
- CLI accepts all valid model types
- Empty dataset returns 0 accuracy with no crash

---

## Success Criteria

1. PCB MMLU dataset has 500+ questions across 8 categories with ground truth
2. Benchmark runner produces scored results for any model
3. Random baseline achieves ~25% (sanity check)
4. Questions are sourced from real schematics in analog-ecosystem
5. Dataset is a single portable JSON file
6. CLI runner is self-contained and documented
