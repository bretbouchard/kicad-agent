# Spatial Reasoning Model Assessment

**Date:** 2026-06-08 01:06
**Total tasks:** 162
**Total duration:** 144.8s
**Benchmark:** Phase 80-03, seed=42

## Models Evaluated

| Model | Size | Type | Local | Adapter | Status |
|---|---|---|---|---|---|
| Qwen2.5-0.5B-Instruct | 0.5B params | Text-only | Yes (mlx-lm) | GRPO LoRA | Evaluated |
| Gemma 4 12B-it-Q4_K_M | 12B params | Encoder-free vision | No (~8GB download) | N/A | Not evaluated |

Gemma 4 12B was **not evaluated** — model not cached locally. Download command:
```bash
huggingface-cli download ggml-org/gemma-4-12B-it-Q4_K_M
```

## Per-Category Accuracy

| Category | Tasks | Input Type | Qwen2.5-0.5B (text-only) | Text Baseline | Assessment |
|---|---|---|---|---|---|
| coordinate_proximity | 30 | text | 3.3% (1/30) | native | FAIL — model outputs bounding box dims, not Euclidean distance |
| routing_feasibility | 27 | vision | 25.9% (7/27) | text-only | FAIL — model biased toward "no"; no visual context |
| clearance_diagnosis | 27 | text | 0.0% (0/27) | native | FAIL — generic non-answers, not root cause analysis |
| net_completion | 27 | vision | **85.2%** (23/27) | text-only | PASS — model generates correct coordinate waypoints without renders |
| drc_fix_selection | 27 | vision | 0.0% (0/27) | text-only | FAIL — echoes violation instead of selecting "Fix N"; no visual context |
| unrouted_cause | 24 | vision | 0.0% (0/24) | text-only | FAIL — repeats question; no visual context to identify blockers |
| **Overall** | **162** | — | **19.1%** (31/162) | — | **Insufficient for autonomous gap filling** |

**Text-only vs Vision distinction:** Vision-category tasks (routing_feasibility, net_completion, drc_fix_selection, unrouted_cause) were evaluated in text-only mode — no PCB renders provided. The 0% scores on drc_fix_selection and unrouted_cause partly reflect missing visual context, not purely reasoning failure. net_completion's strong 85.2% demonstrates that text coordinates alone can suffice for path tasks. Gemma 4 12B vision evaluation is needed to determine the true vision uplift.

## Per-Category Latency (ms/task)

| Category | Qwen2.5-0.5B |
|---|---|
| coordinate_proximity | 692ms |
| routing_feasibility | 941ms |
| clearance_diagnosis | 1075ms |
| net_completion | 1189ms |
| drc_fix_selection | 855ms |
| unrouted_cause | 603ms |
| **Average** | **893ms** |

## Failure Mode Analysis

### Qwen2.5-0.5B — 131/162 failures

**Pattern 1: Instruction following** (clearance_diagnosis, drc_fix_selection, unrouted_cause — 78 failures)
The model echoes the question or gives generic responses rather than answering the specific spatial reasoning question. Example:
- Question: "What is the root cause of this DRC violation?"
- Model: "The DRC violation is due to the fact that the PCB is not fully designed"
- Likely a capacity limitation at 0.5B params. Vision tasks also lack the PCB render context that would ground the question.

**Pattern 2: Format mismatch** (coordinate_proximity — 29 failures)
The model computes bounding box dimensions (`10.5mm x 1.6mm`) instead of Euclidean distance (`34.6673mm`). It interprets "clearance" as component dimensions rather than point-to-point distance. This is a reasoning error independent of visual input.

**Pattern 3: Negativity bias** (routing_feasibility — 20 failures)
The model defaults to "no" for ~74% of routing questions, even when the correct answer is "yes" (most synthetic routes have clear direct paths). Without seeing the PCB layout, the model assumes obstruction. Vision input may resolve this.

**Pattern 4: Path generation works** (net_completion — 4 failures)
The model generates correct coordinate waypoints 85% of the time despite having no PCB renders. It understands `(x, y)` format and can reason about spatial connectivity from text coordinates alone. This is the strongest capability and the only category suitable for Qwen-only inference.

## Decision Matrix

| Task Type | Recommended Model | Rationale | Confidence |
|---|---|---|---|
| coordinate_proximity | **Gemma 4 12B (vision)** — pending benchmark | Euclidean distance reasoning requires visual geometry understanding | Low (no Gemma data) |
| routing_feasibility | **Gemma 4 12B (vision)** — pending benchmark | Negativity bias likely resolved by visual context | Low (no Gemma data) |
| clearance_diagnosis | **Gemma 4 12B (vision)** — pending benchmark | Root cause analysis requires seeing violation area | Low (no Gemma data) |
| net_completion | **Qwen2.5-0.5B (text)** | 85.2% accuracy — vision not required for coordinate-based paths | **High** |
| drc_fix_selection | **Gemma 4 12B (vision)** — pending benchmark | Multi-choice selection likely requires visual comparison | Low (no Gemma data) |
| unrouted_cause | **Gemma 4 12B (vision)** — pending benchmark | Obstacle identification requires visual inspection | Low (no Gemma data) |

**Confidence levels:** "High" = backed by benchmark data. "Low" = inferred from Qwen's failure modes; Gemma evaluation needed to confirm.

## Phase 82 Model Routing Recommendation

### Default Strategy (pending Gemma benchmark)
- **Text tasks** (net_completion): Qwen2.5-0.5B with GRPO adapter — proven 85% accuracy
- **Vision tasks** (all others): Gemma 4 12B encoder-free vision — recommended pending benchmark confirmation
- **Fallback**: If Gemma 4 12B unavailable, use Qwen2.5-0.5B for all tasks (accept 19% overall accuracy)

### Before Phase 82: Required Actions
1. **Download Gemma 4 12B** (~8GB) and re-run benchmark with `--gemma` flag
2. Compare Gemma vision scores against Qwen text baseline per category
3. Update this decision matrix with actual Gemma data

### Trigger for Phase 84 (Conditional Fine-Tuning)
Phase 84 fine-tuning is triggered **only if Gemma 4 12B shows <50% accuracy** on routing_feasibility or net_completion after benchmarking. Qwen2.5-0.5B scores cannot predict Gemma's performance.

**Current status:** Cannot assess trigger — Gemma benchmark required first.

## Methodology Notes

- **Ground truth**: Deterministic computation via Shapely geometry and line-crossing tests. No LLM judgment in scoring.
- **Scoring**: Category-specific extractors (numeric tolerance 10%, keyword overlap 30%, waypoint proximity 2mm, exact match for yes/no)
- **Task distribution**: 20% easy / 60% medium / 20% hard across all categories
- **Data source**: Synthetic spatial primitives (30 points + 10 boxes) with seeded RNG (seed=42)
- **Routing feasibility ground truth**: Uses geometric line-crossing heuristic (Shapely `LineString.crosses`), not A* pathfinding. "Yes" means a direct straight-line path exists without crossing any obstacle bounding box. "No" means at least one obstacle intersects the direct line. This is a **necessary but not sufficient** condition for routability — A* might find multi-segment routes around obstacles that block direct lines. Phase 82 implementers should interpret feasibility results as lower-bound estimates.
- **A* pathfinding**: Available via `TaskGenerator(use_astar=True)` for stricter ground truth, but takes ~60s per generation (not used in this run)
- **Vision tasks as text baseline**: Qwen ran all 162 tasks as text-only (no PCB renders). This measures text reasoning capability in isolation. Gemma 4 12B evaluation will add the vision dimension.
