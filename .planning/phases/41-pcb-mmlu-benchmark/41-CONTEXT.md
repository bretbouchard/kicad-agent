# Benchmark Phases Context (41-44)

## Why Benchmarks Matter

The evaluation benchmarks dimension is at **2/10** — the lowest score on the scorecard. This is the #1 credibility blocker for professional adoption. No engineer takes an AI tool seriously without published benchmarks.

**Current state:** 1392+ tests verify that *operations work correctly*. Nothing tests whether the system *understands circuits*.

**Target state:** Published benchmark suite with baseline scores that demonstrate measurable circuit intelligence.

## Existing Infrastructure

### Training/Evaluation (already built)
- `training/evaluation.py` — GRPO evaluation harness with EvalResult (measures maze-routing reward)
- `training/reward.py` — Reward model for spatial reasoning
- `training/regression.py` — BaselineStore, detect_regression() for model regression
- `generation/evaluation.py` — Design quality evaluation (ERC 0.4, DRC 0.3, Gerber 0.15, BOM 0.15)
- `inference/evaluator.py` — Model inference evaluation

### Schematic Analysis (already built)
- `schematic_routing/schematic_graph.py` — Wire tracing, pin positions, label positions
- `schematic_routing/pin_resolver.py` — Absolute pin coordinates for any component
- `ops/erc_parser.py` — Parse ERC violations into structured ErcViolation objects
- `ops/erc_auto_fix.py` — Automated ERC violation fixing

### Source Data (from analog-ecosystem)
- 55 hardware modules with real schematics
- THAT4301 compressor (43 components, 45 nets, 33 violations)
- CD4066BE, NE5532, RP2040 circuits with known behavior
- Full ERC reports, netlists, BOMs available

## Key Design Decisions

1. **Template-based generation, not LLM-based.** Questions are generated from deterministic templates filled with real schematic data. This ensures reproducibility and eliminates LLM hallucination in the benchmark itself.

2. **Multi-choice for MMLU, open-ended for QA.** PCB MMLU tests recognition/selection (like MMLU). Circuit QA tests explanation/generation. Different skills, different datasets.

3. **Separate phases for generation, running, regression, and adversarial.** Each builds on the previous. Phase 41 creates the dataset, 41-02 makes it runnable, 42 adds training data, 43 adds CI, 44 adds adversarial coverage.

4. **Heuristic baseline, not just random.** Random gives ~25%. A keyword-matching heuristic gives ~30-40%. The gap between heuristic and fine-tuned model demonstrates real learning.

5. **2% regression threshold.** Any category dropping > 2% triggers a CI block. This is tight enough to catch real degradation but loose enough to avoid noise from randomness.

## Success Metrics

| Metric | Current | After 41-44 |
|--------|---------|-------------|
| Benchmark questions | 0 | 500+ |
| QA pairs | 0 | 2000+ |
| Adversarial tests | 0 | 750+ |
| CI integration | None | PR-blocking regression check |
| Published scores | None | Baseline + heuristic + fine-tuned |
| Evaluation scorecard | 2/10 | 10/10 |
